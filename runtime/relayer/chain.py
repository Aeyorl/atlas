"""Minimal JSON-RPC client and AtlasBridge ABI decoding for the relayer.

Standard-library only (urllib) so the relayer runs without heavy
dependencies. Web3.py can replace this layer later without touching
the service logic.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

# ────────────────────────────────
#  JSON-RPC client
# ────────────────────────────────


class RpcError(RuntimeError):
    """Raised when the node returns a JSON-RPC error response."""


class JsonRpcClient:
    """Tiny synchronous JSON-RPC (HTTP) client."""

    def __init__(self, rpc_url: str, timeout: float = 15.0):
        self.rpc_url = rpc_url
        self.timeout = timeout
        self._id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        body = json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if "error" in payload:
            raise RpcError(f"{method}: {payload['error']}")
        return payload.get("result")

    # Convenience wrappers -------------------------------------------------

    def chain_id(self) -> int:
        return int(self.call("eth_chainId", []), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def call_contract(
        self, to: str, data: str, block: int | None = None
    ) -> str:
        """eth_call, returning the raw hex response."""
        tag = "latest" if block is None else hex(block)
        return self.call("eth_call", [{"to": to, "data": data}, tag]) or "0x"

    def get_logs(self, from_block: int, to_block: int, address: str) -> list[dict]:
        return self.call(
            "eth_getLogs",
            [
                {
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block),
                    "address": address,
                    "topics": [TOPIC_MESSAGE_SENT],
                }
            ],
        ) or []

    def send_raw_transaction(self, signed_tx: str) -> str:
        return self.call("eth_sendRawTransaction", [signed_tx])


# ────────────────────────────────
#  Contract constants
# ────────────────────────────────

def keccak256(data: bytes) -> bytes:
    """Pure-Python Keccak-256 (NOT sha3-256). Fallback-free."""
    # Keccak-f[1600] round constants
    RC = [
        0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
        0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
        0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
        0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
        0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
        0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
    ]
    ROT = [
        [0, 36, 3, 41, 18],
        [1, 44, 10, 45, 2],
        [62, 6, 43, 15, 61],
        [28, 55, 25, 21, 56],
        [27, 20, 39, 8, 14],
    ]

    def _rotl(x: int, n: int) -> int:
        n %= 64
        return ((x << n) | (x >> (64 - n))) & 0xFFFFFFFFFFFFFFFF

    rate = 136  # 1088-bit rate for 256-bit output
    # pad10*1
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    lanes = [0] * 25
    for block_start in range(0, len(padded), rate):
        block = padded[block_start:block_start + rate]
        for i in range(rate // 8):
            lanes[i] ^= int.from_bytes(block[i * 8:(i + 1) * 8], "little")
        for rnd in range(24):
            # θ
            c = [lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20]
                 for x in range(5)]
            d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
            for x in range(5):
                for y in range(5):
                    lanes[x + 5 * y] ^= d[x]
            # ρ and π
            b = [0] * 25
            for x in range(5):
                for y in range(5):
                    b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(lanes[x + 5 * y], ROT[x][y])
            # χ
            for x in range(5):
                for y in range(5):
                    lanes[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y])
            # ι
            lanes[0] ^= RC[rnd]

    return b"".join(lanes[i].to_bytes(8, "little") for i in range(4))


TOPIC_MESSAGE_SENT = "0x" + keccak256(
    b"MessageSent(bytes32,bytes32,address)"
).hex()

TOPIC_MESSAGE_DELIVERED = "0x" + keccak256(
    b"MessageDelivered(bytes32,bytes32)"
).hex()


def event_topic(event_signature: str) -> str:
    return "0x" + keccak256(event_signature.encode()).hex()


# ────────────────────────────────
#  Decoding helpers
# ────────────────────────────────


@dataclass(frozen=True)
class MessageSentEvent:
    """A `MessageSent` event observed on a source bridge.

    Event signature: `MessageSent(bytes32 indexed messageId, bytes32
    targetEcosystem, address indexed sender)` — so `messageId` and `sender`
    arrive as topics, `targetEcosystem` as the data word.
    """

    message_id: str          # 0x-prefixed bytes32
    target_ecosystem: str    # 0x-prefixed bytes32
    sender: str              # EIP-55 address
    block_number: int
    tx_hash: str
    log_index: int
    chain_id: int


def _to_checksum_address(addr_lower: str) -> str:
    """EIP-55 checksummed address from a 20-byte hex string."""
    raw = addr_lower.lower().replace("0x", "").rjust(40, "0")[-40:]
    digest = keccak256(raw.encode()).hex()
    out = "0x"
    for i, ch in enumerate(raw):
        out += ch.upper() if ch.isalpha() and int(digest[i], 16) >= 8 else ch
    return out


def _parse_log(log: dict, chain_id: int) -> MessageSentEvent | None:
    topics = log.get("topics") or []
    if len(topics) < 3 or topics[0] != TOPIC_MESSAGE_SENT:
        return None
    return MessageSentEvent(
        message_id=topics[1],
        sender=_to_checksum_address(topics[2]),
        target_ecosystem="0x" + bytes.fromhex(
            log.get("data", "0x").removeprefix("0x")
        )[-32:].hex(),
        block_number=int(log["blockNumber"], 16),
        tx_hash=log["transactionHash"],
        log_index=int(log["logIndex"], 16),
        chain_id=chain_id,
    )


def parse_message_sent_logs(logs: list[dict], chain_id: int) -> list[MessageSentEvent]:
    """Filter + decode `MessageSent` logs from an eth_getLogs response."""
    events = []
    for log in logs:
        parsed = _parse_log(log, chain_id)
        if parsed is not None:
            events.append(parsed)
    return events


# ────────────────────────────────
#  ABI helpers (outbox fetch)
# ────────────────────────────────

SELECTOR_GET_OUTBOX = "0x" + keccak256(b"getOutboxMessage(bytes32)").hex()[:8]
SELECTOR_OUTBOX_COUNT = "0x" + keccak256(b"outboxCount()").hex()[:8]
SELECTOR_VALID_ATTESTATIONS = "0x" + keccak256(b"validAttestations(bytes32)").hex()[:8]


def _decode_outbox(data_hex: str) -> tuple[str, str, str, int]:
    """Decode `getOutboxMessage` return: (targetEcosystem, sender, payload, sentAt).

    The getter ABI-encodes the `OutboxMessage` struct:
    head = [target bytes32][sender][payload offset][sentAt], with the bytes
    tail at `offset` as [length][data]. `offset` is relative to the tuple start.
    """
    raw = bytes.fromhex(data_hex.removeprefix("0x"))
    if len(raw) < 128:
        raise ValueError(f"outbox response too short: {len(raw)} bytes")
    target_ecosystem = "0x" + raw[0:32].hex()
    # sender is word 1; the 20-byte address occupies the last 20 bytes
    # of that word (bytes 44..64 of the response).
    sender = _to_checksum_address("0x" + raw[44:64].hex())
    offset = int.from_bytes(raw[64:96], "big")
    sent_at = int.from_bytes(raw[96:128], "big")
    if offset + 32 > len(raw):
        raise ValueError(f"outbox payload offset out of range: {offset}")
    payload_len = int.from_bytes(raw[offset:offset + 32], "big")
    payload = raw[offset + 32: offset + 32 + payload_len]
    return target_ecosystem, sender, "0x" + payload.hex(), sent_at


def _decode_uint(data_hex: str) -> int:
    raw = bytes.fromhex(data_hex.removeprefix("0x"))
    if len(raw) < 32:
        raise ValueError(f"uint response too short: {len(raw)} bytes")
    return int.from_bytes(raw[:32], "big")


# ────────────────────────────────
#  High-level bridge reads
# ────────────────────────────────


class BridgeReader:
    """Read-only view over an AtlasBridge deployment."""

    def __init__(self, client: JsonRpcClient, bridge_address: str, chain_id: int):
        self.client = client
        self.bridge_address = bridge_address
        self.chain_id = chain_id

    def outbox_message(self, message_id: str) -> tuple[str, str, str, int]:
        """(targetEcosystem, sender, payload hex, sentAt) for an outbox entry."""
        data = self.client.call_contract(
            self.bridge_address, SELECTOR_GET_OUTBOX + message_id[2:].rjust(64, "0")
        )
        return _decode_outbox(data)

    def outbox_count(self) -> int:
        data = self.client.call_contract(self.bridge_address, SELECTOR_OUTBOX_COUNT)
        return _decode_uint(data)

    def valid_attestations(self, message_id: str) -> int:
        data = self.client.call_contract(
            self.bridge_address, SELECTOR_VALID_ATTESTATIONS + message_id[2:].rjust(64, "0")
        )
        return _decode_uint(data)
