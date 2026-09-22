# Guide: Driving the Deployed Contracts — ChainClient & CLI

This guide covers the two contract-backed developer interfaces that ship in
this repo:

- **`ChainClient`** (`sdk/python/chain.py`) — the Python SDK's contract layer:
  reads and signed writes against AgentRegistry, TaskManager, SettlementEngine,
  NiveBridge, and NiveCore.
- **`cli/main.py`** — a command-line interface exposing the same operations.

Both are **zero-dependency**: they reuse the bridge relayer's primitives
(stdlib secp256k1 signing, pure-Python keccak, hand-rolled ABI encoding), so
there is no web3 and nothing to `pip install` beyond Python 3.11+. Run
everything from the repository root.

> Deploy the contracts first — `scripts/deploy/DeployNive.s.sol` prints the
> five addresses you need (registry, task_manager, settlement, bridge, core).
> See the [README Quick Start](../../README.md#-quick-start).

---

## 1. Configuration

### Environment variables

| Variable | Used for |
|----------|----------|
| `NIVE_RPC_URL` | JSON-RPC endpoint (**required**) |
| `NIVE_REGISTRY_ADDRESS` | AgentRegistry reads/writes |
| `NIVE_TASK_MANAGER_ADDRESS` | TaskManager reads/writes |
| `NIVE_SETTLEMENT_ADDRESS` | SettlementEngine reads |
| `NIVE_BRIDGE_ADDRESS` | Bridge sends |
| `NIVE_CORE_ADDRESS` | Guardian staking |
| `NIVE_PRIVATE_KEY` | Signing writes (**never** required for reads) |

Each read/write method checks only the addresses it needs — you can work with
just the registry deployed, for example.

### nive.json (CLI default config)

`python cli/main.py init` writes a template into the working directory:

```json
{
  "rpc_url": "http://127.0.0.1:8545",
  "contracts": {
    "registry": "",
    "task_manager": "",
    "settlement": "",
    "bridge": "",
    "core": ""
  }
}
```

Fill the empty strings with the forge deploy output.

> **Private keys never live in config files.** Both `ChainClient.from_config`
> and the CLI always take `NIVE_PRIVATE_KEY` from the environment.

### Building a client in Python

Three equivalent entry points:

```python
from sdk.python.chain import ChainClient, Contracts
from runtime.relayer.service import Signer

# 1. From the environment (see table above)
client = ChainClient.from_env()

# 2. From a nive.json file (key still comes from the environment)
client = ChainClient.from_config("nive.json")

# 3. Explicitly — handy for multi-account scripts
client = ChainClient(
    rpc_url="http://127.0.0.1:8545",
    contracts=Contracts(
        registry="0x…", task_manager="0x…", settlement="0x…",
        bridge="0x…", core="0x…",
    ),
    signer=Signer("0x…"),   # optional — omit for read-only clients
)
```

---

## 2. Core concepts

### Ids: bytes32 + seeds

Ids (`agent_id`, `task_id`) are opaque `bytes32` values. `--seed` /
`id_from_seed` keccak-hash your text into one, so the same seed always
reproduces the same id:

```python
from sdk.python.chain import id_from_seed

id_from_seed("my-agent")   # '0x5f1d…'  (66-char hex, deterministic)
```

### Capabilities: text as bytes32 words

Capabilities are `bytes32` words (UTF-8, right-padded, max 32 bytes):

```python
from sdk.python.chain import capability_word

capability_word("TRADE")   # '0x545241444500000000…'
```

### Units

The SDK speaks **wei** (integers) everywhere. The CLI accepts **ether-unit
flags** (`--budget-ether 2.5`, `--fee-ether 0.75`, `--min-fee 0.5`) and
converts for you; `task create` also offers raw `--budget-wei`.

### Signer and receipts

`Signer` (from `runtime.relayer.service`) signs legacy EIP-155 transactions
from a hex private key; `client.signer.address` is the derived sender.
Every write returns a receipt after the transaction is mined:

```python
receipt.tx_hash    # '0x…'
receipt.status     # '0x1' on success ('0x0' raises instead)
receipt.block      # block number it was mined in
receipt.gas_used   # int
```

---

## 3. Reading state

Reads are plain `eth_call`s; structs are decoded into plain dicts.

```python
client = ChainClient.from_env()   # no key needed

# Registry
client.agent_count()
client.search_by_capability(capability_word("TRADE"))   # -> [agent_id, …]
client.is_agent_active(id_from_seed("my-agent"))
client.agent_ids_for_owner("0x…")                       # by owner address

record = client.get_agent(id_from_seed("my-agent"))
# {'agent_id', 'owner', 'uri', 'capabilities', 'execution_wallet',
#  'min_fee_wei', 'active', 'total_tasks', 'successful_tasks'}

# Tasks
task = client.get_task(id_from_seed("task-1"))
# {'task_id', 'creator', 'required_capabilities', 'budget_wei',
#  'parameters' (0x-hex bytes), 'status' ("Pending"…"Disputed"),
#  'assigned_agent', 'created_at', 'deadline'}
client.get_bids(id_from_seed("task-1"))
# -> [{'bidder', 'fee_wei', 'status' ("Pending"|"Accepted"|"Rejected")}, …]
client.result_hash(id_from_seed("task-1"))   # sha256(result) commitment, 0x0 if none
client.protocol_fee_bps()                    # default 250 (2.5%)

# Settlement + guardians
client.escrow(id_from_seed("task-1"))        # wei held in escrow
client.settlement(id_from_seed("task-1"))    # {'agent_fee_wei', 'guardian_fee_wei',
                                             #  'protocol_fee_wei', 'settled', …}
client.guardian_count()                      # needs NIVE_CORE_ADDRESS
```

---

## 4. Writing: the full task lifecycle

On-chain roles and who may do what:

| Role | May call |
|------|----------|
| **Creator** | `create_task`, `accept_bid`, `dispute_task`, `withdraw_escrow` |
| **Agent** | `submit_bid`, `complete_task` |
| **Governor** | `verify_task`, `resolve_dispute`, `accept_bid` |
| **Anyone** | `settle_task` |

Ground rules enforced by the contracts (violations revert):

- `create_task` escrows the budget as `msg.value` — it must equal
  `budget_wei` exactly; the deadline must be in the future; at least one
  required capability.
- **Bidding requires registration**: the bidder must be a registered,
  *active* agent declaring **every** required capability. The agent id is
  resolved and pinned at bid time. One bid per address; fee ≤ budget.
- `complete_task` commits `sha256(result)` on chain (the Groth16 circuit
  proves SHA-256 preimages, hence not keccak) and stores the proof blob.
- `verify_task(valid=True)` opens a **3-day dispute window**;
  `settle_task` succeeds only after it closes. On dev chains, fast-forward
  time (`anvil_setNextBlockTimestamp`) instead of waiting.
- Settlement pays the agent `fee − protocolCut`, splits the protocol cut
  between guardians and the treasury, refunds the unspent escrow remainder
  to the creator, and releases any posted bond.

```python
import time
from sdk.python.chain import ChainClient, Contracts, capability_word, id_from_seed
from runtime.relayer.service import Signer

creator = ChainClient(rpc_url, contracts, signer=Signer(CREATOR_KEY))
agent   = ChainClient(rpc_url, contracts, signer=Signer(AGENT_KEY))
governor = ChainClient(rpc_url, contracts, signer=Signer(GOVERNOR_KEY))

agent_id = id_from_seed("analyzer")
task_id  = id_from_seed("task-1")
caps     = [capability_word("ANALYZE")]

# 1. Agent registers itself
agent.register_agent(
    agent_id=agent_id,
    uri="https://analyzer.example.com/meta.json",
    capabilities=caps,
    min_fee_wei=10**16,               # 0.01 NIVE minimum fee
)

# 2. Creator posts a task (1 NIVE escrowed)
creator.create_task(
    task_id=task_id,
    required_capabilities=caps,
    budget_wei=10**18,
    parameters=b'{"dataset":"tweets-q3"}',
    deadline=int(time.time()) + 86_400,
)

# 3. Agent bids under budget
agent.submit_bid(task_id, fee_wei=8 * 10**17)

# 4. Creator accepts — all other pending bids are auto-rejected
creator.accept_bid(task_id, agent_address=agent.signer.address)

# 5. Agent delivers the result (+ optional ZK proof blob)
agent.complete_task(task_id, result=b'{"sentiment":0.62}', proof=b"")

# 6. Governor verifies → dispute window opens (3 days)
governor.verify_task(task_id, valid=True)

# 7. Anyone settles once the window closes
creator.settle_task(task_id)
print(creator.settlement(task_id)["agent_fee_wei"])   # agent's take
```

Also available: `update_agent`, `deactivate_agent`, `resolve_dispute`
(governor arbitration: `agent_valid=True` settles in the agent's favor,
`False` refunds the creator), and `withdraw_escrow` (creator recovers the
escrow from a Failed task), plus `register_guardian` (§6).

---

## 5. Cross-ecosystem messaging (bridge)

```python
message_id = client.send_bridge_message("virtuals", b'{"hello":"world"}')
```

- Targets: `"robinhood-chain"`, `"evm"`, `"virtuals"` (or any raw bytes32
  ecosystem word).
- The returned id is the **canonical message id** — the same
  `keccak256(abi.encode(local, target, payload, sender, chainId, nonce))`
  the bridge emits — derived by reading `localEcosystem()`/`outboxCount()`
  before the send, so you can track delivery through the relayer by id.
- The relayer observes the outbox, guardian-attests, and delivers to the
  target chain once the 2-of-5 quorum is met
  (see `python -m runtime.relayer`).

---

## 6. Guardians

```python
client.register_guardian(stake_wei=10_000 * 10**18)  # MIN_GUARDIAN_STAKE
client.guardian_count()
```

Guardians attest bridge messages (2-of-5 quorum) and can be slashed by
governance — see the [security model](../../README.md#-security-model).

---

## 7. Error handling

| Exception | Meaning |
|-----------|---------|
| `ValueError("missing contract address(es) …")` | The address needed for that call is empty |
| `ValueError("no signer configured …")` | Write attempted without `NIVE_PRIVATE_KEY` |
| `RuntimeError("tx reverted on-chain …")` | Mined but reverted (status `0x0`) — check roles/status windows above |
| `RuntimeError("tx not mined within 30s …")` | Receipt never arrived; node may be slow or stalled |
| `ValueError("capability too long …")` | `capability_word` with > 32 bytes |

```python
try:
    agent.submit_bid(task_id, fee_wei=10**19)
except RuntimeError as exc:
    print("bid rejected:", exc)   # e.g. fee > budget, duplicate bid, wrong status
```

---

## 8. CLI reference

Global flags: `--config PATH` (default `nive.json` in the working directory)
and `--rpc URL` (overrides the transport regardless of config).

> **Precedence gotcha:** if `nive.json` exists in the working directory it
> wins over `NIVE_*_ADDRESS` env vars. Delete it or pass `--config` if you
> want the environment to drive.

| Command | Needs key | Notes |
|---------|-----------|-------|
| `init [--force]` | — | Write the config template |
| `agent register --seed/--id --uri … --capabilities … [--min-fee E] [--wallet A]` | ✅ | `--wallet` defaults to the signer |
| `agent get --seed/--id` | — | Decoded AgentRecord |
| `agent search --capability TEXT` | — | Registered agents declaring it |
| `agent count` | — | |
| `agent deactivate --seed/--id` | ✅ | Permanent |
| `task create --seed/--id --capabilities … (--budget-ether E \| --budget-wei W) [--parameters S] [--days N]` | ✅ | Escrows the budget; deadline = now + N days (default 1) |
| `task get --seed/--id` | — | Decoded Task |
| `task bids --seed/--id` | — | All bids with fees and status |
| `task bid --seed/--id --fee-ether E` | ✅ | Caller must be a registered agent (see §4) |
| `task accept --seed/--id --agent ADDR` | ✅ | Creator (or governor) |
| `task complete --seed/--id (--result TEXT \| --result-file PATH)` | ✅ | Assigned agent |
| `task settle --seed/--id` | ✅ | After the dispute window; prints the fee breakdown |
| `escrow --seed/--id` | — | Wei held |
| `bridge send --target {robinhood-chain\|evm\|virtuals} [--payload TEXT]` | ✅ | Prints the canonical message id |
| `guardian register --stake-ether E` | ✅ | Needs NIVE_CORE_ADDRESS |
| `guardian count` | — | |

Exit codes: `0` success; usage errors (`argparse`, missing `--id/--seed`,
missing key) raise `SystemExit`; runtime failures print `error: …` to stderr
and exit `1`.

A full session mirroring §4:

```bash
export NIVE_RPC_URL=http://127.0.0.1:8545
export NIVE_PRIVATE_KEY=0x…           # creator / agent / governor per step
export NIVE_REGISTRY_ADDRESS=0x… NIVE_TASK_MANAGER_ADDRESS=0x…
export NIVE_SETTLEMENT_ADDRESS=0x…

python cli/main.py agent register --seed analyzer --uri https://a.example \
  --capabilities ANALYZE --min-fee 0.01
python cli/main.py task create --seed task-1 --capabilities ANALYZE \
  --budget-ether 1 --parameters '{"dataset":"tweets-q3"}'
python cli/main.py task bid --seed task-1 --fee-ether 0.8
python cli/main.py task accept --seed task-1 --agent 0x…       # bidder address
python cli/main.py task complete --seed task-1 --result '{"sentiment":0.62}'
python cli/main.py escrow --seed task-1
python cli/main.py task settle --seed task-1                   # after 3 days*
```

\* advance time on a dev chain instead of waiting.

---

## 9. Task status reference

| Status | Set by | Meaning |
|--------|--------|---------|
| `Pending` | — | Enum zero; tasks are created in `Bidding` |
| `Bidding` | `createTask` | Accepting bids (until the deadline) |
| `Executing` | `acceptBid` | Assigned agent is working |
| `Verifying` | `completeTask` | Result committed; governor verifies; dispute window runs here |
| `Completed` | `settleTask` / `resolveDispute(true)` | Paid and closed |
| `Failed` | `verifyTask(false)` / `resolveDispute(false)` | Refundable by the creator |
| `Disputed` | `disputeTask` | Governor arbitration pending |

```
createTask ─▶ Bidding ─acceptBid─▶ Executing ─completeTask─▶ Verifying
                 │                                            │
                 │ (deadline passes)            verifyTask(true)│verifyTask(false)
                 ▼                                            ▼            ▼
              (stale)                          settleTask ▶ Completed     Failed
                                                disputeTask ▶ Disputed
                                                              │ resolveDispute
                                                              ▼
                                                     Completed / Failed
```

---

## 10. Testing without a chain

Both layers are covered by offline tests that stub the JSON-RPC transport —
no node required:

```bash
pytest sdk/python/test_sdk_chain.py cli/test_cli.py -v
```

`test_sdk_chain.py` also verifies the ABI codecs against hand-built payloads
and decodes signed raw transactions, so the wire format is checked without a
network.

---

## See also

- [README Quick Start](../../README.md#-quick-start) — install, deploy, one-screen examples
- [Contract architecture](../architecture/CONTRACTS.md) — what the contracts enforce
- Relayer guide — `python -m runtime.relayer relayer.json` (see README)
