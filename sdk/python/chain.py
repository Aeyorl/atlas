"""Contract-backed chain layer for the Nive Python SDK.

Talks to deployed Nive contracts over JSON-RPC using the same zero-dependency
primitives as the bridge relayer (stdlib secp256k1 signing, pure-Python
keccak, hand-rolled ABI encoding) — no web3 dependency.

Reads work with just an RPC URL and contract addresses. Writes additionally
need a signer (NIVE_PRIVATE_KEY env var or an explicit `Signer`).

Conventions
-----------
- bytes32 arguments accept a 0x-prefixed 66-char hex string (or an int).
- addresses accept a 0x-prefixed 42-char hex string.
- capabilities are bytes32 words; use `capability_word("TRADE")` to convert
  text (UTF-8, right-padded) or `id_from_seed(seed)` for collision-free ids.
- dynamic arguments are inferred: `bytes` → ABI bytes, `str` (not hex-typed)
  → ABI string, `list[str]` of bytes32 hex → bytes32[].

Example
-------
    client = ChainClient.from_env()
    agent = client.register_agent(
        agent_id=id_from_seed("my-agent"),
        uri="https://my-agent.example.com/meta.json",
        capabilities=[capability_word("TRADE")],
    )
    client.create_task(
        task_id=id_from_seed("task-1"),
        required_capabilities=[capability_word("TRADE")],
        budget_wei=10**18,
        parameters=b'{"pair":"BTC/USD"}',
    )
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from runtime.relayer.chain import (
    JsonRpcClient,
    _decode_uint,
    _strip_struct_wrapper,
    _to_checksum_address,
    keccak256,
)
from runtime.relayer.config import (
    ECOSYSTEM_EVM,
    ECOSYSTEM_ROBINHOOD,
    ECOSYSTEM_VIRTUALS,
)
from runtime.relayer.service import Signer, abi_encode

__all__ = [
    "ECOSYSTEMS",
    "TASK_STATUSES",
    "ChainClient",
    "Contracts",
    "capability_word",
    "compute_verification_limbs",
    "encode_zk_verification",
    "id_from_seed",
    "split_bytes32_to_limbs",
]

ECOSYSTEMS = {
    "robinhood-chain": ECOSYSTEM_ROBINHOOD,
    "evm": ECOSYSTEM_EVM,
    "virtuals": ECOSYSTEM_VIRTUALS,
}

# Mirrors ITaskManager.TaskStatus.
TASK_STATUSES = {
    0: "Pending", 1: "Bidding", 2: "Executing", 3: "Verifying",
    4: "Completed", 5: "Failed", 6: "Disputed",
}

DEFAULT_DEADLINE_SECONDS = 86_400  # 1 day
DEFAULT_GAS = 600_000


def _selector(signature: str) -> bytes:
    return keccak256(signature.encode())[:4]


def capability_word(text: str) -> str:
    """UTF-8 capability text as a bytes32 word (right-padded)."""
    raw = text.encode()
    if len(raw) > 32:
        raise ValueError(f"capability too long (max 32 bytes): {text!r}")
    return "0x" + raw.ljust(32, b"\x00").hex()


def id_from_seed(seed: str) -> str:
    """Deterministic bytes32 id from a seed string."""
    return "0x" + keccak256(seed.encode()).hex()


def split_bytes32_to_limbs(hex_or_bytes: str | bytes) -> tuple[int, int]:
    """Split a 256-bit word into (lo_128, hi_128) limbs.

    Matches SettlementEngine canonical limb binding:
    (hi << 128) | lo == uint256(word)
    """
    if isinstance(hex_or_bytes, bytes):
        raw = hex_or_bytes.rjust(32, b"\x00")
    else:
        raw = bytes.fromhex(hex_or_bytes.removeprefix("0x")).rjust(32, b"\x00")
    val = int.from_bytes(raw[-32:], "big")
    lo = val & ((1 << 128) - 1)
    hi = val >> 128
    return (lo, hi)


def compute_verification_limbs(
    task_id: str | bytes,
    result_hash: str | bytes | None = None,
) -> list[int]:
    """Compute public input limbs [taskId_lo, taskId_hi (, result_lo, result_hi)]."""
    task_lo, task_hi = split_bytes32_to_limbs(task_id)
    limbs = [task_lo, task_hi]
    if result_hash is not None:
        res_lo, res_hi = split_bytes32_to_limbs(result_hash)
        limbs.extend([res_lo, res_hi])
    return limbs


def encode_zk_verification(proof: bytes, public_inputs: list[int]) -> bytes:
    """Encode (proof, publicInputs) as abi.encode(bytes, uint256[]).

    Matches SettlementEngine._verifyProof abi.decode(verification, (bytes, uint256[])).
    """
    proof_bytes = proof
    proof_pad = (32 - (len(proof_bytes) % 32)) % 32
    encoded_proof = (
        len(proof_bytes).to_bytes(32, "big")
        + proof_bytes
        + b"\x00" * proof_pad
    )
    offset0 = (64).to_bytes(32, "big")
    offset1 = (64 + len(encoded_proof)).to_bytes(32, "big")

    encoded_inputs = len(public_inputs).to_bytes(32, "big") + b"".join(
        x.to_bytes(32, "big") for x in public_inputs
    )
    return offset0 + offset1 + encoded_proof + encoded_inputs


# ────────────────────────────────
#  ABI encoding (call arguments)
# ────────────────────────────────


def _is_bytes32(value: object) -> bool:
    return isinstance(value, str) and value.startswith("0x") and len(value) == 66


def _is_address(value: object) -> bool:
    return isinstance(value, str) and value.startswith("0x") and len(value) == 42


def _static_word(value: object) -> bytes:
    if isinstance(value, bool):
        return int(value).to_bytes(32, "big")
    if isinstance(value, int):
        return value.to_bytes(32, "big")
    if _is_address(value):
        return int(value, 16).to_bytes(32, "big")
    if _is_bytes32(value):
        return bytes.fromhex(value[2:])
    raise TypeError(f"unsupported static ABI value: {value!r}")


def _dynamic_block(value: object) -> bytes:
    """[length][padded data] block for a dynamic value."""
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    elif isinstance(value, str):
        data = value.encode()
    elif isinstance(value, list):
        if not all(_is_bytes32(item) for item in value):
            raise TypeError(f"bytes32[] list must contain 0x…66 strings: {value!r}")
        inner = b"".join(bytes.fromhex(item[2:]) for item in value)
        return len(value).to_bytes(32, "big") + inner
    else:
        raise TypeError(f"unsupported dynamic ABI value: {value!r}")
    padded = data + b"\x00" * ((32 - len(data) % 32) % 32)
    return len(data).to_bytes(32, "big") + padded


def encode_args(values: list[object]) -> bytes:
    """abi.encode over the type-inference conventions in the module docstring."""
    head: list[bytes] = []
    tail: list[bytes] = []
    tail_offset = 32 * len(values)
    for value in values:
        is_dynamic = isinstance(value, (bytes, bytearray, list)) or (
            isinstance(value, str) and not (_is_bytes32(value) or _is_address(value))
        )
        if is_dynamic:
            block = _dynamic_block(value)
            head.append(tail_offset.to_bytes(32, "big"))
            tail.append(block)
            tail_offset += len(block)
        else:
            head.append(_static_word(value))
    return b"".join(head) + b"".join(tail)


# ────────────────────────────────
#  ABI decoding (struct returns)
# ────────────────────────────────


def _words(raw: bytes, count: int, base: int = 0) -> list[bytes]:
    if len(raw) < base + 32 * count:
        raise ValueError(f"response too short: need {base + 32 * count} bytes, got {len(raw)}")
    return [raw[base + 32 * i: base + 32 * (i + 1)] for i in range(count)]


def _word_int(word: bytes) -> int:
    return int.from_bytes(word, "big")


def _read_dyn_bytes(struct: bytes, offset: int) -> bytes:
    length = _word_int(_words(struct, 1, offset)[0])
    data_start = offset + 32
    if data_start + length > len(struct):
        raise ValueError("dynamic bytes extends past end of struct")
    return struct[data_start: data_start + length]


def _read_string(struct: bytes, offset: int) -> str:
    return _read_dyn_bytes(struct, offset).decode(errors="replace")


def _read_bytes32_array(struct: bytes, offset: int) -> list[str]:
    length = _word_int(_words(struct, 1, offset)[0])
    words = _words(struct, length, offset + 32)
    return ["0x" + w.hex() for w in words]


def _decode_agent_record(data_hex: str) -> dict[str, object]:
    struct = _strip_struct_wrapper(bytes.fromhex(data_hex.removeprefix("0x")))
    head = _words(struct, 9)
    return {
        "agent_id": "0x" + head[0].hex(),
        "owner": _to_checksum_address("0x" + head[1][-20:].hex()),
        "uri": _read_string(struct, _word_int(head[2])),
        "capabilities": _read_bytes32_array(struct, _word_int(head[3])),
        "execution_wallet": _to_checksum_address("0x" + head[4][-20:].hex()),
        "min_fee_wei": _word_int(head[5]),
        "active": _word_int(head[6]) == 1,
        "total_tasks": _word_int(head[7]),
        "successful_tasks": _word_int(head[8]),
    }


def _decode_task(data_hex: str) -> dict[str, object]:
    struct = _strip_struct_wrapper(bytes.fromhex(data_hex.removeprefix("0x")))
    head = _words(struct, 9)
    return {
        "task_id": "0x" + head[0].hex(),
        "creator": _to_checksum_address("0x" + head[1][-20:].hex()),
        "required_capabilities": _read_bytes32_array(struct, _word_int(head[2])),
        "budget_wei": _word_int(head[3]),
        "parameters": "0x" + _read_dyn_bytes(struct, _word_int(head[4])).hex(),
        "status": TASK_STATUSES.get(_word_int(head[5]), str(_word_int(head[5]))),
        "assigned_agent": _to_checksum_address("0x" + head[6][-20:].hex()),
        "created_at": _word_int(head[7]),
        "deadline": _word_int(head[8]),
    }


def _decode_bids(data_hex: str) -> list[dict[str, object]]:
    # `Bid[]` of an all-static struct: [0x20][len][3 words per bid].
    raw = _strip_struct_wrapper(bytes.fromhex(data_hex.removeprefix("0x")))
    count = _word_int(_words(raw, 1)[0])
    bids = []
    for i in range(count):
        head = _words(raw, 3, 32 + 96 * i)
        bids.append({
            "bidder": _to_checksum_address("0x" + head[0][-20:].hex()),
            "fee_wei": _word_int(head[1]),
            "status": ("Pending", "Accepted", "Rejected")[_word_int(head[2])],
        })
    return bids


def _decode_settlement(data_hex: str) -> dict[str, object]:
    raw = bytes.fromhex(data_hex.removeprefix("0x"))
    if len(raw) >= 32 and int.from_bytes(raw[:32], "big") == 32 and len(raw) >= 32 + (7 * 32):
        raw = raw[32:]
    head = _words(raw, 7)
    return {
        "task_id": "0x" + head[0].hex(),
        "agent": _to_checksum_address("0x" + head[1][-20:].hex()),
        "creator": _to_checksum_address("0x" + head[2][-20:].hex()),
        "agent_fee_wei": _word_int(head[3]),
        "guardian_fee_wei": _word_int(head[4]),
        "protocol_fee_wei": _word_int(head[5]),
        "settled": _word_int(head[6]) == 1,
    }


def _decode_bytes32_array_return(data_hex: str) -> list[str]:
    raw = _strip_struct_wrapper(bytes.fromhex(data_hex.removeprefix("0x")))
    return _read_bytes32_array(raw, 0)


# ────────────────────────────────
#  Contract addresses
# ────────────────────────────────


@dataclass(frozen=True)
class Contracts:
    """Deployed Nive contract addresses (checksummed or lowercase hex)."""

    registry: str
    task_manager: str
    settlement: str
    bridge: str = ""
    core: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, str]) -> Contracts:
        def pick(*names: str) -> str:
            for name in names:
                value = data.get(name, "")
                if value:
                    return value
            return ""

        return cls(
            registry=pick("registry"),
            task_manager=pick("task_manager"),
            settlement=pick("settlement"),
            bridge=pick("bridge"),
            core=pick("core"),
        )


# ────────────────────────────────
#  Chain client
# ────────────────────────────────


@dataclass
class _TxReceipt:
    tx_hash: str
    status: str
    block: int
    gas_used: int


class ChainClient:
    """Reads and writes against deployed Nive contracts.

    Reads need only `rpc_url` + `contracts`. Writes additionally require a
    `signer`; every write returns a `_TxReceipt` after on-chain confirmation.
    """

    def __init__(self, rpc_url: str, contracts: Contracts,
                 signer: Signer | None = None):
        self.client = JsonRpcClient(rpc_url)
        self.contracts = contracts
        self.signer = signer

    # ── Construction ─────────────────────────────────────────────

    @classmethod
    def from_env(cls, signer: Signer | None = None) -> ChainClient:
        """Build from NIVE_RPC_URL + NIVE_{REGISTRY,TASK_MANAGER,SETTLEMENT,BRIDGE,CORE}_ADDRESS."""
        rpc_url = os.environ.get("NIVE_RPC_URL", "")
        if not rpc_url:
            raise ValueError("NIVE_RPC_URL is not set")
        contracts = Contracts.from_mapping({
            "registry": os.environ.get("NIVE_REGISTRY_ADDRESS", ""),
            "task_manager": os.environ.get("NIVE_TASK_MANAGER_ADDRESS", ""),
            "settlement": os.environ.get("NIVE_SETTLEMENT_ADDRESS", ""),
            "bridge": os.environ.get("NIVE_BRIDGE_ADDRESS", ""),
            "core": os.environ.get("NIVE_CORE_ADDRESS", ""),
        })
        if signer is None:
            key = os.environ.get("NIVE_PRIVATE_KEY", "")
            if key:
                signer = Signer(key)
        return cls(rpc_url, contracts, signer=signer)

    @classmethod
    def from_config(cls, path: str, signer: Signer | None = None) -> ChainClient:
        """Build from a nive.json config ({"rpc_url": …, "contracts": {…}}).

        The private key always comes from the environment (NIVE_PRIVATE_KEY);
        config files must never hold keys.
        """
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        rpc_url = data.get("rpc_url", "")
        if not rpc_url:
            raise ValueError(f"{path}: missing rpc_url")
        contracts = Contracts.from_mapping(data.get("contracts", {}))
        if signer is None and os.environ.get("NIVE_PRIVATE_KEY"):
            signer = Signer(os.environ["NIVE_PRIVATE_KEY"])
        return cls(rpc_url, contracts, signer=signer)

    # ── Transport ────────────────────────────────────────────────

    def _require_contracts(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self.contracts, n)]
        if missing:
            raise ValueError(f"missing contract address(es): {', '.join(missing)}")

    def _call(self, contract: str, signature: str, args: list[object]) -> str:
        data = "0x" + (_selector(signature) + encode_args(args)).hex()
        return self.client.call_contract(getattr(self.contracts, contract), data)

    def _transact(self, contract: str, signature: str, args: list[object],
                  value: int = 0, gas: int = DEFAULT_GAS) -> _TxReceipt:
        if self.signer is None:
            raise ValueError(
                "no signer configured — set NIVE_PRIVATE_KEY to send transactions")
        to = getattr(self.contracts, contract)
        calldata = _selector(signature) + encode_args(args)
        nonce_hex = self.client.call(
            "eth_getTransactionCount", [self.signer.address, "pending"])
        raw = self.signer.sign_tx(
            chain_id=self.client.chain_id(), nonce=int(nonce_hex, 16),
            to=to, data=calldata, value=value, gas=gas,
        )
        tx_hash = self.client.send_raw_transaction("0x" + raw.hex())
        receipt = self.client.wait_for_receipt(tx_hash, timeout_seconds=30.0)
        if receipt is None:
            raise RuntimeError(f"tx not mined within 30s: {tx_hash}")
        if receipt.get("status") != "0x1":
            raise RuntimeError(f"tx reverted on-chain: {tx_hash}")
        return _TxReceipt(
            tx_hash=tx_hash,
            status=receipt.get("status", ""),
            block=int(receipt.get("blockNumber", "0x0"), 16),
            gas_used=int(receipt.get("gasUsed", "0x0"), 16),
        )

    # ── AgentRegistry reads ──────────────────────────────────────

    def get_agent(self, agent_id: str) -> dict[str, object]:
        self._require_contracts("registry")
        return _decode_agent_record(
            self._call("registry", "getAgent(bytes32)", [agent_id]))

    def agent_ids_for_owner(self, owner: str) -> list[str]:
        self._require_contracts("registry")
        return _decode_bytes32_array_return(
            self._call("registry", "getAgentByOwner(address)", [owner]))

    def agent_count(self) -> int:
        self._require_contracts("registry")
        return _decode_uint(self._call("registry", "getAgentCount()", []))

    def search_by_capability(self, capability: str) -> list[str]:
        self._require_contracts("registry")
        return _decode_bytes32_array_return(
            self._call("registry", "searchByCapability(bytes32)", [capability]))

    def is_agent_active(self, agent_id: str) -> bool:
        self._require_contracts("registry")
        return _decode_uint(self._call("registry", "isActive(bytes32)", [agent_id])) == 1

    # ── AgentRegistry writes ─────────────────────────────────────

    def register_agent(self, agent_id: str, uri: str, capabilities: list[str],
                       execution_wallet: str | None = None,
                       min_fee_wei: int = 0) -> _TxReceipt:
        if execution_wallet is None:
            if self.signer is None:
                raise ValueError("execution_wallet required when no signer is configured")
            execution_wallet = self.signer.address
        return self._transact(
            "registry", "register(bytes32,string,bytes32[],address,uint256)",
            [agent_id, uri, capabilities, execution_wallet, min_fee_wei])

    def update_agent(self, agent_id: str, uri: str, capabilities: list[str],
                     min_fee_wei: int = 0) -> _TxReceipt:
        return self._transact(
            "registry", "updateAgent(bytes32,string,bytes32[],uint256)",
            [agent_id, uri, capabilities, min_fee_wei])

    def deactivate_agent(self, agent_id: str) -> _TxReceipt:
        return self._transact("registry", "deactivateAgent(bytes32)", [agent_id])

    # ── TaskManager reads ────────────────────────────────────────

    def get_task(self, task_id: str) -> dict[str, object]:
        self._require_contracts("task_manager")
        return _decode_task(
            self._call("task_manager", "getTask(bytes32)", [task_id]))

    def get_bids(self, task_id: str) -> list[dict[str, object]]:
        self._require_contracts("task_manager")
        return _decode_bids(self._call("task_manager", "getBids(bytes32)", [task_id]))

    def task_count(self) -> int:
        self._require_contracts("task_manager")
        return _decode_uint(self._call("task_manager", "getTaskCount()", []))

    def result_hash(self, task_id: str) -> str:
        self._require_contracts("task_manager")
        return self._call("task_manager", "getResultHash(bytes32)", [task_id])

    def protocol_fee_bps(self) -> int:
        self._require_contracts("task_manager")
        return _decode_uint(self._call("task_manager", "protocolFeeBps()", []))

    # ── Task lifecycle writes ────────────────────────────────────

    def create_task(self, task_id: str, required_capabilities: list[str],
                    budget_wei: int, parameters: bytes = b"",
                    deadline: int | None = None,
                    value: int | None = None) -> _TxReceipt:
        """Create a task and escrow `budget_wei` (msg.value must equal it)."""
        if deadline is None:
            deadline = int(time.time()) + DEFAULT_DEADLINE_SECONDS
        return self._transact(
            "task_manager",
            "createTask(bytes32,bytes32[],uint256,bytes,uint256)",
            [task_id, required_capabilities, budget_wei, parameters, deadline],
            value=budget_wei if value is None else value,
        )

    def submit_bid(self, task_id: str, fee_wei: int) -> _TxReceipt:
        return self._transact("task_manager", "submitBid(bytes32,uint256)",
                              [task_id, fee_wei])

    def accept_bid(self, task_id: str, agent_address: str) -> _TxReceipt:
        return self._transact("task_manager", "acceptBid(bytes32,address)",
                              [task_id, agent_address])

    def complete_task(self, task_id: str, result: bytes,
                      proof: bytes = b"") -> _TxReceipt:
        return self._transact("task_manager", "completeTask(bytes32,bytes,bytes)",
                              [task_id, result, proof])

    def verify_task(self, task_id: str, valid: bool) -> _TxReceipt:
        """Governor-only. Valid moves the task into the dispute window."""
        return self._transact("task_manager", "verifyTask(bytes32,bool)",
                              [task_id, valid])

    def dispute_task(self, task_id: str, evidence: bytes = b"") -> _TxReceipt:
        return self._transact("task_manager", "disputeTask(bytes32,bytes)",
                              [task_id, evidence])

    def settle_task(self, task_id: str) -> _TxReceipt:
        """Anyone may settle once verification + the dispute window have passed."""
        return self._transact("task_manager", "settleTask(bytes32)", [task_id])

    def resolve_dispute(self, task_id: str, agent_valid: bool) -> _TxReceipt:
        """Governor-only arbitration for a disputed task.

        `agent_valid=True` settles in the agent's favor; False refunds the
        full escrow to the creator and marks the task Failed.
        """
        return self._transact("task_manager", "resolveDispute(bytes32,bool)",
                              [task_id, agent_valid])

    def withdraw_escrow(self, task_id: str) -> _TxReceipt:
        """Creator-only: recover the escrow from a Failed task."""
        return self._transact("task_manager", "withdrawEscrow(bytes32)", [task_id])

    # ── SettlementEngine reads & writes ──────────────────────────

    def escrow(self, task_id: str) -> int:
        self._require_contracts("settlement")
        return _decode_uint(self._call("settlement", "getEscrow(bytes32)", [task_id]))

    def settlement(self, task_id: str) -> dict[str, object]:
        self._require_contracts("settlement")
        return _decode_settlement(
            self._call("settlement", "getSettlement(bytes32)", [task_id]))

    def post_bond(self, task_id: str, amount_wei: int) -> _TxReceipt:
        """Post or top up a bond on `task_id`."""
        self._require_contracts("settlement")
        return self._transact("settlement", "postBond(bytes32)", [task_id], value=amount_wei)

    def withdraw_bond(self, task_id: str) -> _TxReceipt:
        """Withdraw posted bond once task is terminal."""
        self._require_contracts("settlement")
        return self._transact("settlement", "withdrawBond(bytes32)", [task_id])

    def get_bond(self, task_id: str, bonder: str) -> int:
        """Query bond amount posted by `bonder` on `task_id`."""
        self._require_contracts("settlement")
        return _decode_uint(self._call("settlement", "getBond(bytes32,address)", [task_id, bonder]))

    def slash_bond(self, task_id: str, bonder: str, amount_wei: int) -> _TxReceipt:
        """Governor-only: slash `bonder` bond and forward to task creator."""
        self._require_contracts("settlement")
        return self._transact("settlement", "slash(bytes32,address,uint256)", [task_id, bonder, amount_wei])

    def has_proof_verified(self, task_id: str) -> bool:
        """Check whether `task_id` settlement was gated by a verified ZK proof."""
        self._require_contracts("settlement")
        return _decode_uint(self._call("settlement", "hasProofVerified(bytes32)", [task_id])) == 1

    # ── NiveBridge ───────────────────────────────────────────────

    def send_bridge_message(self, target_ecosystem: str, payload: bytes,
                            gas: int = DEFAULT_GAS) -> str:
        """Send a cross-ecosystem message; returns its on-chain message id.

        The id is derived exactly as the bridge derives it —
        keccak256(abi.encode(localEcosystem, targetEcosystem, payload,
        sender, chainId, outboxCount-before-send)) — by reading the two
        public getters before the send.
        """
        self._require_contracts("bridge")
        if self.signer is None:
            raise ValueError(
                "no signer configured — set NIVE_PRIVATE_KEY to send transactions")
        target = ECOSYSTEMS.get(target_ecosystem, target_ecosystem)
        local = self._call("bridge", "localEcosystem()", [])
        nonce = _decode_uint(self._call("bridge", "outboxCount()", []))
        self._transact("bridge", "sendMessage(bytes32,bytes)", [target, payload],
                       gas=gas)
        message_id = keccak256(abi_encode([
            local, target, payload, self.signer.address,
            self.client.chain_id(), nonce,
        ]))
        return "0x" + message_id.hex()

    # ── NiveCore ─────────────────────────────────────────────────

    def register_guardian(self, stake_wei: int) -> _TxReceipt:
        self._require_contracts("core")
        return self._transact("core", "registerGuardian(uint256)", [stake_wei])

    def guardian_count(self) -> int:
        self._require_contracts("core")
        return _decode_uint(self._call("core", "getGuardianCount()", []))
