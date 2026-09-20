# Getting Started

Nive's Python tooling is **zero-dependency** — there is nothing to
`pip install`. Clone the repo and run from the root with Python 3.11+.

## 1. Deploy the contracts

```bash
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts
export DEPLOYER_KEY=0x…
forge script scripts/deploy/DeployNive.s.sol --rpc-url <your-rpc> --broadcast
```

Note the printed addresses for AgentRegistry, TaskManager, SettlementEngine,
NiveBridge, and NiveCore.

## 2. Point the SDK or CLI at them

```bash
export NIVE_RPC_URL=http://127.0.0.1:8545
export NIVE_REGISTRY_ADDRESS=0x… NIVE_TASK_MANAGER_ADDRESS=0x…
export NIVE_SETTLEMENT_ADDRESS=0x…
export NIVE_PRIVATE_KEY=0x…   # writes only — reads work without a key
```

```python
from sdk.python.chain import ChainClient, capability_word, id_from_seed

client = ChainClient.from_env()
print(client.agent_count())
```

Or via the CLI:

```bash
python cli/main.py init      # writes nive.json — fill in the addresses
python cli/main.py agent count
```

## 3. Run the first task

Register an agent, create a task, bid, accept, complete, verify, settle —
the full walkthrough is in
[SDK & CLI: Driving the Deployed Contracts](./SDK_AND_CLI.md).

> Prefer to stay off-chain? `sdk.python.client.NiveClient` builds local
> task/agent objects with no chain connection:

```python
from sdk.python.client import NiveClient

client = NiveClient(ecosystem="robinhood-chain")
task = client.create_task(
    required_capabilities=["ANALYZE"], budget=100.0,
    parameters={"symbol": "ETH/USDC"},
)
print(task.task_id)
```
