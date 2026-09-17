"""AtlasBridge relayer: watch `MessageSent` outbox events, attest, deliver.

Flow per message (see contracts/core/AtlasBridge.sol):
  1. Observe `MessageSent(messageId indexed, targetEcosystem, sender indexed)`
     on a source chain; recover `payload`/`sender` via `getOutboxMessage`.
  2. Recover `sourceNonce` by recomputing the contract's canonical id —
     keccak256(abi.encode(source, target, payload, sender, sourceChainId,
     outboxCount-at-send)) — over candidate nonces in [0, outboxCount).
     A match both verifies provenance AND yields the nonce needed for the
     delivery proof; no match means the event/outbox pair is inconsistent
     and the message is quarantined.
  3. Guardian attestation — if the relayer key is a registered guardian
     (or the bridge governor) on the target chain, it submits its own
     `verifyMessage` vote.
  4. Delivery — once `validAttestations >= GUARDIAN_QUORUM` on the target
     bridge, send `deliverMessage(messageId, payload, proof)` where
     `proof = abi.encode(sourceEcosystem, sourceSender, sourceChainId,
     sourceNonce)`.
  5. `deliverMessage` returning `false` ("quorum not met") is retryable:
     the message stays in flight and is re-polled every
     `delivery_retry_seconds` up to `delivery_max_attempts`.

Signing is standard-library secp256k1 (deterministic RFC 6979 nonces,
EIP-155 replay protection). For production, swap `Signer` for a
KMS-backed implementation; nothing else changes.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import threading
import time
from dataclasses import dataclass, field

from .chain import (
    BridgeReader,
    JsonRpcClient,
    MessageSentEvent,
    keccak256,
    parse_message_sent_logs,
)
from .config import ChainConfig, RelayerConfig, ecosystem_name

# Function selectors, computed from canonical signatures (no guessing).
SELECTOR_VERIFY_MESSAGE = keccak256(b"verifyMessage(bytes32,bool)")[:4].hex()
SELECTOR_DELIVER_MESSAGE = keccak256(b"deliverMessage(bytes32,bytes,bytes)")[:4].hex()

GUARDIAN_QUORUM = 2  # mirror of AtlasBridge.GUARDIAN_QUORUM


# ────────────────────────────────
#  Signing (RFC 6979 secp256k1)
# ────────────────────────────────

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _point_add(
    p1: tuple[int, int] | None, p2: tuple[int, int] | None
) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * pow(2 * y1, -1, _P) % _P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (lam * lam - x1 - x2) % _P
    return (x3, (lam * (x1 - x3) - y1) % _P)


def _point_mul(k: int, point: tuple[int, int]) -> tuple[int, int]:
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    assert result is not None
    return result


def _rfc6979_k(msg: bytes, priv: int) -> int:
    """Deterministic nonce per RFC 6979 (HMAC-SHA256)."""
    x = priv.to_bytes(32, "big")
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + msg, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + msg, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < _N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def _checksum_address(addr: str) -> str:
    raw = addr.removeprefix("0x").lower()
    digest = keccak256(raw.encode()).hex()
    return "0x" + "".join(
        ch.upper() if ch.isalpha() and int(digest[i], 16) >= 8 else ch
        for i, ch in enumerate(raw)
    )


def _rlp_encode(item: object) -> bytes:
    if isinstance(item, int):
        if item < 0:
            raise ValueError("cannot RLP-encode negative integers")
        # Integers encode as big-endian minimal byte strings; 0 as the
        # empty string (so RLP(0) == 0x80, per the spec).
        data = b"" if item == 0 else item.to_bytes((item.bit_length() + 7) // 8, "big")
        if len(data) == 1 and data[0] < 0x80:
            return data
        return _rlp_len(len(data), 0x80) + data
    if isinstance(item, (bytes, bytearray)):
        data = bytes(item)
        if len(data) == 1 and data[0] < 0x80:
            return data
        return _rlp_len(len(data), 0x80) + data
    if isinstance(item, (list, tuple)):
        payload = b"".join(_rlp_encode(x) for x in item)
        return _rlp_len(len(payload), 0xC0) + payload
    raise TypeError(f"cannot RLP-encode {type(item)}")


def _rlp_len(length: int, offset: int) -> bytes:
    if length < 56:
        return bytes([offset + length])
    length_bytes = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([offset + 55 + len(length_bytes)]) + length_bytes


class Signer:
    """EIP-155 secp256k1 signer (testnet-grade; swap for KMS in production)."""

    def __init__(self, private_key: str):
        key = private_key.removeprefix("0x")
        if len(key) != 64:
            raise ValueError("private key must be 32 bytes hex")
        self.d = int(key, 16)
        if not 1 <= self.d < _N:
            raise ValueError("private key out of range")
        pub = _point_mul(self.d, (_GX, _GY))
        self.address = _checksum_address(
            "0x" + keccak256(pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big"))[-40:].hex()
        )

    def sign_tx(self, chain_id: int, nonce: int, to: str, data: bytes,
                gas: int = 300_000, gas_price: int = 1_000_000_000,
                value: int = 0) -> bytes:
        to_bytes = bytes.fromhex(to.removeprefix("0x"))
        unsigned = _rlp_encode([nonce, gas_price, gas, to_bytes, value, data,
                                chain_id, 0, 0])
        z = int.from_bytes(keccak256(unsigned), "big")
        k = _rfc6979_k(keccak256(unsigned), self.d)
        point = _point_mul(k, (_GX, _GY))
        r = point[0] % _N
        s = pow(k, -1, _N) * (z + r * self.d) % _N
        if s > _N // 2:
            s = _N - s
        recid = 0 if point[1] % 2 == 0 else 1
        v = recid + 35 + chain_id * 2
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return _rlp_encode([nonce, gas_price, gas, to_bytes, value, data, v, sig])


# ────────────────────────────────
#  Message tracking
# ────────────────────────────────


class MessageState(enum.Enum):
    OBSERVED = "observed"          # seen on source, provenance not yet resolved
    PENDING_QUORUM = "pending"     # id verified, waiting for guardian quorum
    DELIVERING = "delivering"      # delivery tx sent
    DELIVERED = "delivered"
    FAILED = "failed"              # attempts exhausted / unreachable target
    QUARANTINED = "quarantined"    # id derivation failed — manual review


@dataclass
class TrackedMessage:
    message_id: str
    source: ChainConfig
    source_event: MessageSentEvent
    target_ecosystem: str
    sender: str
    payload: bytes = b""
    source_nonce: int | None = None
    state: MessageState = MessageState.OBSERVED
    attempts: int = 0
    next_retry_at: float = 0.0
    last_error: str = ""
    delivery_tx: str = ""
    updated_at: float = field(default_factory=time.time)


# ────────────────────────────────
#  Relayer service
# ────────────────────────────────


class AtlasRelayer:
    """Polls source bridges for `MessageSent`, attests, delivers on target.

    One instance handles any number of tracked chains; routing is driven by
    each message's `targetEcosystem`.
    """

    def __init__(self, config: RelayerConfig, signer: Signer | None = None):
        problems = config.validate()
        if problems:
            raise ValueError("invalid relayer config: " + "; ".join(problems))
        self.config = config
        self.signer = signer
        self._messages: dict[str, TrackedMessage] = {}
        self._cursor: dict[int, int] = {}      # chain_id -> next block to scan
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────

    def poll_once(self) -> list[TrackedMessage]:
        """One sweep: observe, resolve, attest/deliver. Returns touched messages."""
        touched: list[TrackedMessage] = []
        for chain in self.config.chains:
            touched.extend(self._scan_chain(chain))
        now = time.time()
        for msg in list(self._messages.values()):
            if msg.next_retry_at > now:
                continue
            if (
                msg.state in (MessageState.OBSERVED, MessageState.PENDING_QUORUM)
                and self._advance(msg)
            ):
                touched.append(msg)
        return touched

    def run_forever(self) -> None:
        """Blocking loop. Call `stop()` from another thread to end it."""
        interval = min(c.poll_interval_seconds for c in self.config.chains)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 — transient RPC errors must not kill the loop
                self._log("poll error", error=str(exc))
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.5, interval - elapsed))

    def stop(self) -> None:
        self._stop.set()

    def tracked(self) -> dict[str, TrackedMessage]:
        with self._lock:
            return dict(self._messages)

    # ── Scanning ──────────────────────────────────────────────────────

    def _scan_chain(self, chain: ChainConfig) -> list[TrackedMessage]:
        client = JsonRpcClient(chain.rpc_url)
        head = client.block_number()
        confirmed_head = head - chain.confirmations
        with self._lock:
            cursor = self._cursor.get(chain.chain_id)
        if cursor is None:
            cursor = chain.start_block if chain.start_block is not None else confirmed_head

        touched: list[TrackedMessage] = []
        while cursor <= confirmed_head:
            end = min(cursor + chain.max_block_range - 1, confirmed_head)
            logs = client.get_logs(cursor, end, chain.bridge_address)
            for event in parse_message_sent_logs(logs, chain.chain_id):
                tracked = self._track(event, chain)
                if tracked is not None:
                    touched.append(tracked)
            cursor = end + 1
            with self._lock:
                self._cursor[chain.chain_id] = cursor
        return touched

    def _track(self, event: MessageSentEvent, chain: ChainConfig) -> TrackedMessage | None:
        with self._lock:
            if event.message_id in self._messages:
                return None
            msg = TrackedMessage(
                message_id=event.message_id,
                source=chain,
                source_event=event,
                target_ecosystem=event.target_ecosystem,
                sender=event.sender,
            )
            self._messages[event.message_id] = msg
        self._log("observed", msg=msg)
        return msg

    # ── Per-message pipeline ──────────────────────────────────────────

    def _advance(self, msg: TrackedMessage) -> bool:
        """Move one message one step forward. True if state changed."""
        try:
            if msg.state is MessageState.OBSERVED:
                return self._resolve_provenance(msg)
            if msg.state is MessageState.PENDING_QUORUM:
                return self._try_attest_and_deliver(msg)
        except Exception as exc:  # noqa: BLE001 — per-message isolation
            msg.last_error = str(exc)
            msg.updated_at = time.time()
            self._log("error", msg=msg, error=str(exc))
        return False

    def _resolve_provenance(self, msg: TrackedMessage) -> bool:
        """Fetch the outbox record and recover (payload, sender, nonce)."""
        reader = BridgeReader(
            JsonRpcClient(msg.source.rpc_url),
            msg.source.bridge_address,
            msg.source.chain_id,
        )
        target_ecosystem, sender, payload_hex, _sent_at = reader.outbox_message(msg.message_id)
        payload = bytes.fromhex(payload_hex.removeprefix("0x"))
        count = reader.outbox_count()

        nonce = self._recover_nonce(
            source_ecosystem=msg.source.ecosystem,
            target_ecosystem=target_ecosystem,
            payload=payload,
            sender=sender,
            source_chain_id=msg.source.chain_id,
            message_id=msg.message_id,
            candidate_count=count,
        )
        if nonce is None:
            msg.state = MessageState.QUARANTINED
            msg.last_error = "messageId does not derive from outbox record"
            msg.updated_at = time.time()
            self._log("quarantine", msg=msg)
            return True

        msg.target_ecosystem = target_ecosystem
        msg.sender = sender
        msg.payload = payload
        msg.source_nonce = nonce
        msg.state = MessageState.PENDING_QUORUM
        msg.updated_at = time.time()
        self._log("verified", msg=msg, nonce=nonce)
        return True

    @staticmethod
    def _recover_nonce(
        source_ecosystem: str,
        target_ecosystem: str,
        payload: bytes,
        sender: str,
        source_chain_id: int,
        message_id: str,
        candidate_count: int,
    ) -> int | None:
        """Find the outbox nonce whose canonical id matches `message_id`.

        The contract binds `outboxCount` at send time into the id; that value
        is not stored, but it is a small non-negative integer, so we derive
        the id over candidates until one matches. A match authenticates the
        full (source, target, payload, sender, chain, nonce) tuple.
        """
        target_bytes = bytes.fromhex(message_id.removeprefix("0x"))
        for nonce in range(candidate_count):
            candidate = keccak256(abi_encode([
                source_ecosystem, target_ecosystem, payload, sender,
                source_chain_id, nonce,
            ]))
            if candidate == target_bytes:
                return nonce
        return None

    def _try_attest_and_deliver(self, msg: TrackedMessage) -> bool:
        target = self.config.by_ecosystem(msg.target_ecosystem)
        if target is None:
            msg.state = MessageState.FAILED
            msg.last_error = (
                f"no chain configured for target ecosystem "
                f"{ecosystem_name(msg.target_ecosystem)}"
            )
            msg.updated_at = time.time()
            self._log("no-target", msg=msg)
            return True

        reader = BridgeReader(
            JsonRpcClient(target.rpc_url), target.bridge_address, target.chain_id
        )
        attestations = reader.valid_attestations(msg.message_id)

        if attestations < GUARDIAN_QUORUM and self.signer is not None:
            self._attest(target, msg)
            attestations = reader.valid_attestations(msg.message_id)
        if attestations < GUARDIAN_QUORUM and msg.attempts >= target.delivery_max_attempts:
            msg.state = MessageState.FAILED
            msg.last_error = f"quorum unmet after {msg.attempts} attempts"
            msg.updated_at = time.time()
            self._log("failed", msg=msg)
            return True
        if attestations < GUARDIAN_QUORUM:
            msg.attempts += 1
            msg.next_retry_at = time.time() + target.delivery_retry_seconds
            msg.updated_at = time.time()
            return False

        return self._deliver(target, msg)

    # ── On-chain sends ────────────────────────────────────────────────

    def _attest(self, target: ChainConfig, msg: TrackedMessage) -> None:
        """Guardian vote: verifyMessage(messageId, true) on the target bridge."""
        assert self.signer is not None
        calldata = (
            bytes.fromhex(SELECTOR_VERIFY_MESSAGE)
            + _word(msg.message_id)
            + _word(1)  # bool true
        )
        tx_hash = self._send(target, target.bridge_address, calldata)
        self._log("attest", msg=msg, tx=tx_hash)

    def _deliver(self, target: ChainConfig, msg: TrackedMessage) -> bool:
        assert msg.source_nonce is not None
        proof = abi_encode([
            msg.source.ecosystem,
            msg.sender,
            msg.source.chain_id,
            msg.source_nonce,
        ])
        calldata = (
            bytes.fromhex(SELECTOR_DELIVER_MESSAGE)
            + _word(msg.message_id)
            + _abi_bytes(msg.payload)
            + _abi_bytes(proof)
        )
        tx_hash = self._send(target, target.bridge_address, calldata)
        msg.delivery_tx = tx_hash
        msg.state = MessageState.DELIVERING
        msg.updated_at = time.time()
        self._log("deliver", msg=msg, tx=tx_hash)
        return True

    def _send(self, target: ChainConfig, to: str, calldata: bytes) -> str:
        assert self.signer is not None
        client = JsonRpcClient(target.rpc_url)
        nonce_hex = client.call(
            "eth_getTransactionCount", [self.signer.address, "pending"]
        )
        raw = self.signer.sign_tx(
            chain_id=target.chain_id,
            nonce=int(nonce_hex, 16),
            to=to,
            data=calldata,
        )
        return client.send_raw_transaction("0x" + raw.hex())

    # ── Misc ──────────────────────────────────────────────────────────

    def _log(self, event: str, *, msg: TrackedMessage | None = None,
             **fields: object) -> None:
        parts = [f"[relayer] {event}"]
        if msg is not None:
            parts.append(
                f"id={msg.message_id[:10]}… src={msg.source.name} "
                f"state={msg.state.value}"
            )
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        print(" ".join(parts))


# ────────────────────────────────
#  ABI encoding helpers
# ────────────────────────────────


def _word(value: str | int) -> bytes:
    if isinstance(value, int):
        return value.to_bytes(32, "big")
    return bytes.fromhex(value.removeprefix("0x")).rjust(32, b"\x00")


def _abi_bytes(data: bytes) -> bytes:
    length = len(data).to_bytes(32, "big")
    padded = data + b"\x00" * ((32 - len(data) % 32) % 32)
    return length + padded


def abi_encode(values: list[object]) -> bytes:
    """abi.encode for (bytes32|address|uint256)* plus dynamic `bytes`.

    Static values (0x-hex strings of 66 chars = bytes32, 42 chars = address,
    plain ints = uint256) go in the head; `bytes` values are appended to the
    tail with standard word-relative offsets.
    """
    head: list[bytes] = []
    tail: list[bytes] = []
    tail_offset = 32 * len(values)
    for value in values:
        if isinstance(value, (bytes, bytearray)):
            encoded = _abi_bytes(bytes(value))
            head.append(tail_offset.to_bytes(32, "big"))
            tail.append(encoded)
            tail_offset += len(encoded)
        else:
            head.append(_word(value))  # type: ignore[arg-type]
    return b"".join(head) + b"".join(tail)
