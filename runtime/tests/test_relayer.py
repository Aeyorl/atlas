"""Tests for the NiveBridge relayer (offline; no RPC node required).

Covers the cryptographic and protocol-critical pieces the service depends on:
keccak-256, RFC 6979 secp256k1 signing + EIP-155 recovery, RLP, ABI encoding,
MessageSent log decoding, outbox record decoding, and the full state machine
driven by a fake bidirectional JSON-RPC node that emulates two bridge
deployments.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any

from runtime.relayer.chain import (
    BridgeReader,
    JsonRpcClient,
    _decode_outbox,
    _to_checksum_address,
    decode_get_message,
    keccak256,
    parse_message_sent_logs,
)
from runtime.relayer.config import (
    ECOSYSTEM_EVM,
    ECOSYSTEM_ROBINHOOD,
    ChainConfig,
    RelayerConfig,
    load_config,
)
from runtime.relayer.service import (
    MessageState,
    NiveRelayer,
    Signer,
    _checksum_address,
    _rfc6979_k,
    _rlp_encode,
    abi_encode,
)

# ────────────────────────────────
#  Crypto primitives
# ────────────────────────────────


class TestKeccak(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(
            keccak256(b"").hex(),
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        )

    def test_abc(self) -> None:
        self.assertEqual(
            keccak256(b"abc").hex(),
            "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
        )

    def test_function_selector_message_sent(self) -> None:
        # Sanity: topic is 32 bytes and stable across calls.
        topic = "0x" + keccak256(b"MessageSent(bytes32,bytes32,address)").hex()
        self.assertEqual(len(topic), 66)
        self.assertEqual(topic, "0x" + keccak256(b"MessageSent(bytes32,bytes32,address)").hex())

    def test_eip55_vector(self) -> None:
        # Canonical EIP-55 test vector
        self.assertEqual(
            _to_checksum_address("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"),
            "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        )


class TestSigning(unittest.TestCase):
    def test_rfc6979_k_known_vector(self) -> None:
        # RFC 6979 A.2.5 test vector (secp256k1 / SHA-256):
        # x = 0x1, message = "Satoshi Nakamoto", h1 = SHA256(msg).
        h1 = hashlib.sha256(b"Satoshi Nakamoto").digest()
        k = _rfc6979_k(h1, 1)
        self.assertEqual(
            k,
            0x8F8A276C19F4149656B280621E358CCE24F5F52542772691EE69063B74F15D15,
        )

    def test_signer_address_and_recoverable_signature(self) -> None:
        signer = Signer("0x" + "01" * 32)
        self.assertEqual(signer.address, _checksum_address(_recover_address_from_signed(signer, 1, 0)))
        raw = signer.sign_tx(chain_id=31337, nonce=0, to="0x" + "ab" * 20, data=b"\xde\xad")
        self.assertTrue(raw.startswith(b"\xf8"))

    def test_signed_tx_decodes_as_valid_legacy_transaction(self) -> None:
        # A signed tx must be RLP([nonce, gasPrice, gas, to, value, data, v,
        # r, s]) — r and s as separate minimal-integer items. This is the
        # exact shape every node's decoder expects; a round-trip re-sign
        # check alone cannot catch a malformed envelope.
        signer = Signer("0x" + "02" * 32)
        raw = signer.sign_tx(chain_id=31337, nonce=7, to="0x" + "cd" * 20,
                             data=b"\xbe\xef", value=10**15, gas=120_000,
                             gas_price=2_000_000_000)
        fields = _rlp_decode(raw)
        self.assertIsInstance(fields, list)
        self.assertEqual(len(fields), 9)
        self.assertEqual(int.from_bytes(fields[0], "big"), 7)          # nonce
        self.assertEqual(int.from_bytes(fields[1], "big"), 2_000_000_000)
        self.assertEqual(int.from_bytes(fields[2], "big"), 120_000)
        self.assertEqual(fields[3], bytes.fromhex("cd" * 20))          # to
        self.assertEqual(int.from_bytes(fields[4], "big"), 10**15)     # value
        self.assertEqual(fields[5], b"\xbe\xef")                       # data
        v = int.from_bytes(fields[6], "big")
        r = int.from_bytes(fields[7], "big")
        s = int.from_bytes(fields[8], "big")
        # EIP-155: v = {0,1} + 35 + 2*chain_id (parity depends on k's y)
        self.assertIn(v, (35 + 2 * 31337, 35 + 2 * 31337 + 1))
        self.assertGreater(r, 0)
        self.assertLess(r, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141)
        self.assertGreater(s, 0)
        self.assertLess(s, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141)
        # Signature halves must be minimal-length integers, not 32-byte blobs.
        self.assertLessEqual(len(fields[7]), 32)
        self.assertLessEqual(len(fields[8]), 32)

    def test_rlp(self) -> None:
        self.assertEqual(_rlp_encode(b""), b"\x80")
        self.assertEqual(_rlp_encode(0), b"\x80")
        self.assertEqual(_rlp_encode(b"\x05"), b"\x05")
        self.assertEqual(_rlp_encode(0x05), b"\x05")
        self.assertEqual(_rlp_encode(1024), b"\x82\x04\x00")
        self.assertEqual(_rlp_encode(b"dog"), b"\x83dog")
        self.assertEqual(_rlp_encode([b"cat", b"dog"]), b"\xc8\x83cat\x83dog")
        self.assertEqual(_rlp_encode(b"lorem ipsum dolor sit amet"), b"\x9alorem ipsum dolor sit amet")  # 26 bytes: short form
        self.assertEqual(_rlp_encode(b"x" * 60), b"\xb8<x" + b"x" * 59)  # 60 bytes: long form


def _rlp_decode(data: bytes):
    """Minimal RLP decoder (test helper): returns the first item and its
    encoded length as (item, consumed). Nested lists become Python lists of
    byte strings / nested lists."""
    def _item(buf: bytes, pos: int):
        if pos >= len(buf):
            raise ValueError("rlp: truncated")
        b = buf[pos]
        if b < 0x80:                       # single byte, itself
            return buf[pos:pos + 1], pos + 1
        if b < 0xB8:                       # short string
            n = b - 0x80
            return buf[pos + 1:pos + 1 + n], pos + 1 + n
        if b < 0xC0:                       # long string
            n = b - 0xB7
            ln = int.from_bytes(buf[pos + 1:pos + 1 + n], "big")
            start = pos + 1 + n
            return buf[start:start + ln], start + ln
        if b < 0xF8:                       # short list
            n = b - 0xC0
            end = pos + 1 + n
            items, p = [], pos + 1
            while p < end:
                it, p = _item(buf, p)
                items.append(it)
            return items, end
        n = b - 0xF7                       # long list
        ln = int.from_bytes(buf[pos + 1:pos + 1 + n], "big")
        end = pos + 1 + n + ln
        items, p = [], pos + 1 + n
        while p < end:
            it, p = _item(buf, p)
            items.append(it)
        return items, end
    item, consumed = _item(data, 0)
    if consumed != len(data):
        raise ValueError("rlp: trailing bytes")
    return item


def _recover_address_from_signed(signer: Signer, chain_id: int, nonce: int) -> str:
    """Genuinely ecrecover the address from a signed tx (EIP-155 math)."""
    from runtime.relayer.service import (
        _GX,
        _GY,
        _N,
        _P,
        _point_add,
        _point_mul,
        _rlp_encode,
    )

    raw = signer.sign_tx(chain_id=chain_id, nonce=nonce,
                         to="0x" + "ab" * 20, data=b"")
    fields = _rlp_decode(raw)
    v = int.from_bytes(fields[6], "big")
    r = int.from_bytes(fields[7], "big")
    s = int.from_bytes(fields[8], "big")
    recid = v - 35 - chain_id * 2
    if recid not in (0, 1):
        raise ValueError(f"bad recid {recid}")
    # EIP-155: the signing payload is the tx with the (v, r, s) tail
    # REPLACED by [chain_id, 0, 0] — not a suffix truncation (the encoded
    # bytes of the two tails differ).
    unsigned = _rlp_encode(fields[0:6] + [chain_id, 0, 0])
    z = int.from_bytes(keccak256(unsigned), "big")
    # x = r, y from parity. Recovery algebra (from s = k⁻¹(z + r·d) and
    # R = kG):  Q = (s/r)·R − (z/r)·G.
    y_sq = (pow(r, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq:
        raise ValueError("r is not an x-coordinate on the curve")
    if (y % 2) != recid:
        y = _P - y
    r_inv = pow(r, -1, _N)
    q = _point_add(_point_mul(s * r_inv % _N, (r, y)),
                   _point_mul((-z) * r_inv % _N, (_GX, _GY)))
    return "0x" + keccak256(q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big"))[-20:].hex()


# ────────────────────────────────
#  ABI encoding
# ────────────────────────────────


class TestAbiEncode(unittest.TestCase):
    def test_matches_contract_derivation(self) -> None:
        # The critical property: our encoding must equal Solidity's
        # abi.encode(bytes32, bytes32, bytes, address, uint256, uint256).
        source = "0x" + keccak256(b"robinhood-chain").hex()
        target = "0x" + keccak256(b"evm").hex()
        payload = b"hello bridge"
        sender = "0x1111111111111111111111111111111111111111"
        encoded = abi_encode([source, target, payload, sender, 31337, 0])

        head = encoded[:192]
        tail = encoded[192:]
        # word0/1: ecosystems; word2: payload offset (0xc0); word3: sender;
        # word4/5: chain id, nonce
        self.assertEqual(head[0:32], bytes.fromhex(source[2:]))
        self.assertEqual(head[32:64], bytes.fromhex(target[2:]))
        self.assertEqual(int.from_bytes(head[64:96], "big"), 192)
        self.assertEqual(head[127], 0x11)  # sender word: address left-padded
        self.assertEqual(int.from_bytes(head[128:160], "big"), 31337)
        self.assertEqual(int.from_bytes(head[160:192], "big"), 0)
        # tail: [len][data][pad]
        self.assertEqual(int.from_bytes(tail[0:32], "big"), len(payload))
        self.assertEqual(tail[32:32 + len(payload)], payload)


# ────────────────────────────────
#  Log + outbox decoding
# ────────────────────────────────


class TestDecoding(unittest.TestCase):
    def test_parse_message_sent_log(self) -> None:
        message_id = keccak256(b"test-message").hex()
        target = keccak256(b"evm").hex()
        sender = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
        log = {
            "topics": [
                "0x" + keccak256(b"MessageSent(bytes32,bytes32,address)").hex(),
                "0x" + message_id,
                "0x" + sender[2:].rjust(64, "0"),
            ],
            "data": "0x" + target,
            "blockNumber": hex(100),
            "transactionHash": "0x" + "ff" * 32,
            "logIndex": hex(2),
        }
        events = parse_message_sent_logs([log], 84532)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.message_id, "0x" + message_id)
        self.assertEqual(event.target_ecosystem, "0x" + target)
        self.assertEqual(event.sender, "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")
        self.assertEqual(event.chain_id, 84532)

    def test_decode_outbox_record(self) -> None:
        target = keccak256(b"evm")
        sender_raw = bytes.fromhex("1111111111111111111111111111111111111111")
        payload = b"cross-chain!"
        sent_at = 1_700_000_000
        # Solidity getter encoding of a returned struct is a one-element
        # tuple: [0x20 wrapper offset][struct head][struct tail], with the
        # payload offset relative to the struct start (word 1).
        data = (
            (32).to_bytes(32, "big")             # ABI v2 wrapper offset
            + target
            + sender_raw.rjust(32, b"\x00")
            + (128).to_bytes(32, "big")          # payload offset (relative to struct)
            + sent_at.to_bytes(32, "big")
            + len(payload).to_bytes(32, "big")
            + payload.ljust(32, b"\x00")
        )
        target_hex, sender, payload_hex, decoded_at = _decode_outbox("0x" + data.hex())
        self.assertEqual(target_hex, "0x" + target.hex())
        self.assertEqual(sender, _checksum_address("0x" + sender_raw.hex()))
        self.assertEqual(bytes.fromhex(payload_hex.removeprefix("0x")), payload)
        self.assertEqual(decoded_at, sent_at)

    # ── getMessage (inbox record) ────────────────────────────────

    @staticmethod
    def _inbox_response(message_id: bytes, source_eco: bytes, target_eco: bytes,
                        payload: bytes, sender_raw: bytes, delivered: bool) -> str:
        """ABI-encode a getMessage() return the way the Solidity getter does."""
        data = (
            (32).to_bytes(32, "big")               # ABI v2 wrapper offset
            + message_id
            + source_eco
            + target_eco
            + (192).to_bytes(32, "big")            # payload offset (rel. to struct)
            + sender_raw.rjust(32, b"\x00")
            + (1 if delivered else 0).to_bytes(32, "big")
            + len(payload).to_bytes(32, "big")
            + payload.ljust((len(payload) + 31) // 32 * 32, b"\x00")
        )
        return "0x" + data.hex()

    def test_decode_get_message_delivered(self) -> None:
        mid = keccak256(b"mid")
        src, tgt = keccak256(b"evm"), keccak256(b"virtuals")
        sender_raw = bytes.fromhex("2222222222222222222222222222222222222222")
        payload = b'{"type":"agent-task"}'
        resp = self._inbox_response(mid, src, tgt, payload, sender_raw, True)
        record = decode_get_message(resp)
        self.assertEqual(record["message_id"], "0x" + mid.hex())
        self.assertEqual(record["source_ecosystem"], "0x" + src.hex())
        self.assertEqual(record["target_ecosystem"], "0x" + tgt.hex())
        self.assertEqual(record["sender"], _checksum_address("0x" + sender_raw.hex()))
        self.assertTrue(record["delivered"])
        self.assertEqual(
            bytes.fromhex(str(record["payload"]).removeprefix("0x")), payload)

    def test_decode_get_message_stub(self) -> None:
        """A not-yet-delivered record carries an empty payload and delivered=0."""
        resp = self._inbox_response(keccak256(b"none"), b"\x00" * 32, b"\x00" * 32,
                                    b"", b"\x00" * 20, False)
        record = decode_get_message(resp)
        self.assertFalse(record["delivered"])
        self.assertEqual(record["payload"], "0x")

    def test_is_delivered_reads_flag_not_payload_tail(self) -> None:
        """Regression: is_delivered must read struct word 5, not the last word.

        The old implementation read raw[-32:], which lands in the payload
        tail: it returned False for every delivered message whose payload
        doesn't end in word 1, and True for undelivered ones whose payload
        does. BridgeReader.is_delivered now decodes the struct properly.
        """
        mid, src, tgt = keccak256(b"m"), keccak256(b"a"), keccak256(b"b")
        sender_raw = b"\x33" * 20

        class _StubClient:
            response: str = ""

            def call_contract(self, to: str, data: str,
                              block: int | None = None) -> str:
                return self.response

        reader_client = _StubClient()
        reader = BridgeReader(reader_client, "0x" + "aa" * 20, 31337)
        message_id = "0x" + mid.hex()

        # Delivered, payload's last word != 1 — old code returned False.
        reader_client.response = self._inbox_response(
            mid, src, tgt, b"hello world", sender_raw, True)
        self.assertTrue(reader.is_delivered(message_id))

        # Undelivered, payload's last word == 1 — old code returned True.
        reader_client.response = self._inbox_response(
            mid, src, tgt, b"\x00" * 31 + b"\x01", sender_raw, False)
        self.assertFalse(reader.is_delivered(message_id))

        # Malformed response is treated as not delivered, not an error.
        reader_client.response = "0x1234"
        self.assertFalse(reader.is_delivered(message_id))


# ────────────────────────────────
#  Config
# ────────────────────────────────


class TestConfig(unittest.TestCase):
    def test_friendly_names_resolve(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "relayer.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "chains": [
                            {
                                "name": "rh-testnet",
                                "chain_id": 4663,
                                "rpc_url": "https://example.org",
                                "ecosystem": "robinhood-chain",
                                "bridge_address": "0x" + "11" * 20,
                            }
                        ]
                    },
                    fh,
                )
            config = load_config(path)
        self.assertEqual(config.chains[0].ecosystem, ECOSYSTEM_ROBINHOOD)
        self.assertEqual(config.validate(), [])

    def test_duplicate_chain_ids_rejected(self) -> None:
        chain = ChainConfig(
            name="a", chain_id=1, rpc_url="https://x",
            ecosystem=ECOSYSTEM_EVM, bridge_address="0x" + "11" * 20,
        )
        twin = ChainConfig(
            name="b", chain_id=1, rpc_url="https://y",
            ecosystem=ECOSYSTEM_EVM, bridge_address="0x" + "22" * 20,
        )
        problems = RelayerConfig(chains=[chain, twin]).validate()
        self.assertTrue(any("duplicate" in p for p in problems))


# ────────────────────────────────
#  End-to-end state machine (fake node)
# ────────────────────────────────

MOCK_RELAYER_KEY = "0x" + "02" * 32
MOCK_GUARDIAN_KEY = "0x" + "03" * 32
BRIDGE_A = "0x" + "aa" * 20  # source chain bridge
BRIDGE_B = "0x" + "bb" * 20  # target chain bridge


class FakeChainNode:
    """Emulates the JSON-RPC surface of one chain running an NiveBridge."""

    def __init__(self, chain_id: int, ecosystem: str, bridge: str):
        self.chain_id = chain_id
        self.ecosystem = ecosystem
        self.bridge = bridge
        self.block = 100
        self.logs: list[dict] = []
        self.sent_raw: list[str] = []  # eth_sendRawTransaction payloads
        self.outbox: dict[str, dict] = {}
        self.outbox_count = 0
        self.attestations: dict[str, int] = {}
        self.delivered: list[str] = []
        self.reverts: list[str] = []  # method names to force-revert

    # ── Test helpers ──────────────────────────────────────────────

    def send_message(self, sender: str, target_ecosystem: str, payload: bytes) -> str:
        nonce = self.outbox_count
        message_id = "0x" + keccak256(abi_encode([
            self.ecosystem, target_ecosystem, payload, sender, self.chain_id, nonce,
        ])).hex()
        self.outbox[message_id] = {
            "target": target_ecosystem, "sender": sender, "payload": payload, "sentAt": self.block,
        }
        self.outbox_count += 1
        self.logs.append({
            "topics": [
                "0x" + keccak256(b"MessageSent(bytes32,bytes32,address)").hex(),
                message_id,
                "0x" + sender[2:].rjust(64, "0"),
            ],
            "data": "0x" + target_ecosystem[2:],
            "blockNumber": hex(self.block),
            "transactionHash": "0x" + keccak256(message_id.encode()).hex(),
            "logIndex": hex(len(self.logs)),
        })
        return message_id

    # ── JSON-RPC surface ──────────────────────────────────────────

    def rpc(self, method: str, params: list[Any]) -> Any:
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return hex(self.block)
        if method == "eth_getLogs":
            from_block, to_block = int(params[0]["fromBlock"], 16), int(params[0]["toBlock"], 16)
            if params[0]["address"].lower() != self.bridge.lower():
                return []
            if "revert-getLogs" in self.reverts:
                raise RuntimeError("getLogs reverted")
            return [l for l in self.logs if from_block <= int(l["blockNumber"], 16) <= to_block]
        if method == "eth_call":
            to, data = params[0]["to"], params[0]["data"]
            if to.lower() != self.bridge.lower():
                return "0x"
            selector, args = data[2:10], data[10:]
            if selector == keccak256(b"outboxCount()").hex()[:8]:
                return "0x" + self.outbox_count.to_bytes(32, "big").hex()
            if selector == keccak256(b"getOutboxMessage(bytes32)").hex()[:8]:
                message_id = "0x" + args
                record = self.outbox.get(message_id)
                if record is None:
                    return "0x"
                payload = record["payload"]
                # ABI v2: returned struct is wrapped in a one-element tuple
                # (word0 = 0x20), payload offset relative to struct start.
                return "0x" + (
                    (32).to_bytes(32, "big")
                    + bytes.fromhex(record["target"][2:]).rjust(32, b"\x00")
                    + bytes.fromhex(record["sender"][2:]).rjust(32, b"\x00")
                    + (128).to_bytes(32, "big")
                    + record["sentAt"].to_bytes(32, "big")
                    + len(payload).to_bytes(32, "big")
                    + payload.ljust((len(payload) + 31) // 32 * 32 or 32, b"\x00")
                ).hex()
            if selector == keccak256(b"validAttestations(bytes32)").hex()[:8]:
                message_id = "0x" + args
                return "0x" + self.attestations.get(message_id, 0).to_bytes(32, "big").hex()
            return "0x"
        if method == "eth_getTransactionCount":
            return hex(0)
        if method == "eth_sendRawTransaction":
            if "revert-send" in self.reverts:
                raise RuntimeError("tx rejected")
            self.sent_raw.append(params[0])
            return "0x" + keccak256(params[0].encode()).hex()
        if method == "eth_getTransactionReceipt":
            # Fake node mines instantly with status success (0x1).
            return {"status": "0x1", "transactionHash": params[0]}
        raise AssertionError(f"unexpected rpc method {method}")


class TestRelayerStateMachine(unittest.TestCase):
    def setUp(self) -> None:
        self.node_a = FakeChainNode(4663, ECOSYSTEM_ROBINHOOD, BRIDGE_A)
        self.node_b = FakeChainNode(84532, ECOSYSTEM_EVM, BRIDGE_B)
        self.nodes = {4663: self.node_a, 84532: self.node_b}
        self.signer = Signer(MOCK_GUARDIAN_KEY)
        config = RelayerConfig(chains=[
            ChainConfig(name="rh", chain_id=4663, rpc_url="http://a",
                        ecosystem=ECOSYSTEM_ROBINHOOD, bridge_address=BRIDGE_A,
                        private_key=MOCK_RELAYER_KEY),
            ChainConfig(name="evm", chain_id=84532, rpc_url="http://b",
                        ecosystem=ECOSYSTEM_EVM, bridge_address=BRIDGE_B,
                        private_key=MOCK_RELAYER_KEY),
        ])
        # Deterministic tests: events confirm instantly, retries are free.
        from dataclasses import replace

        tuned = [
            replace(c, confirmations=0, delivery_retry_seconds=0.0)
            for c in config.chains
        ]
        config = RelayerConfig(chains=tuned)
        self.relayer = NiveRelayer(config, signer=self.signer)
        # Patch clients to hit the fake nodes.
        self._orig_client = JsonRpcClient

        def fake_client(rpc_url: str, timeout: float = 15.0) -> Any:
            url_to_node = {"http://a": self.node_a, "http://b": self.node_b}
            node = url_to_node[rpc_url]

            class _C:
                # Mirrors the JsonRpcClient surface the relayer uses.
                def __init__(self) -> None:
                    self.rpc_url = rpc_url
                    self.timeout = timeout
                    self._id = 0

                def call(self, method: str, params: list) -> Any:
                    return node.rpc(method, params)

                def chain_id(self) -> int:
                    return int(node.rpc("eth_chainId", []), 16)

                def block_number(self) -> int:
                    return int(node.rpc("eth_blockNumber", []), 16)

                def call_contract(self, to: str, data: str, block: Any = None) -> str:
                    tag = "latest" if block is None else hex(block)
                    return node.rpc("eth_call", [{"to": to, "data": data}, tag]) or "0x"

                def get_logs(self, from_block: int, to_block: int, address: str,
                             topics: list | None = None) -> list:
                    return node.rpc("eth_getLogs", [
                        {"fromBlock": hex(from_block), "toBlock": hex(to_block),
                         "address": address},
                    ]) or []

                def send_raw_transaction(self, signed: str) -> str:
                    return node.rpc("eth_sendRawTransaction", [signed])

                def wait_for_receipt(self, tx_hash: str,
                                     timeout_seconds: float = 60.0,
                                     poll: float = 0.25) -> dict | None:
                    # Fake nodes mine instantly — receipt is available now.
                    return node.rpc("eth_getTransactionReceipt", [tx_hash])

            return _C()

        import runtime.relayer.chain as chain_mod
        import runtime.relayer.service as service_mod
        self._chain_mod = chain_mod
        self._service_mod = service_mod
        chain_mod.JsonRpcClient = fake_client
        service_mod.JsonRpcClient = fake_client

    def tearDown(self) -> None:
        self._chain_mod.JsonRpcClient = self._orig_client
        self._service_mod.JsonRpcClient = self._orig_client

    def _poll(self) -> None:
        self.relayer.poll_once()

    def test_quarantine_on_tampered_outbox(self) -> None:
        message_id = self.node_a.send_message(
            "0x" + "ab" * 20, ECOSYSTEM_EVM, b"honest payload"
        )
        # Tamper with the stored payload so derivation fails.
        self.node_a.outbox[message_id]["payload"] = b"tampered"
        self._poll()
        msg = self.relayer.tracked()[message_id]
        self.assertEqual(msg.state, MessageState.QUARANTINED)

    def test_failed_delivery_when_no_target_chain(self) -> None:
        # Target ecosystem virtuals has no chain configured.
        message_id = self.node_a.send_message(
            "0x" + "ab" * 20, "0x" + keccak256(b"virtuals").hex(), b"payload"
        )
        self._poll()  # observe + resolve
        self._poll()  # attempt delivery
        msg = self.relayer.tracked()[message_id]
        self.assertEqual(msg.state, MessageState.FAILED)
        self.assertIn("no chain", msg.last_error)

    def test_end_to_end_delivers_after_quorum(self) -> None:
        sender = "0x" + "ab" * 20
        payload = json.dumps({"action": "analysis", "score": 42}).encode()
        message_id = self.node_a.send_message(sender, ECOSYSTEM_EVM, payload)

        # Poll 1: observe + resolve provenance (nonce recovered).
        self._poll()
        msg = self.relayer.tracked()[message_id]
        self.assertEqual(msg.state, MessageState.PENDING_QUORUM)
        self.assertIsNotNone(msg.source_nonce)
        self.assertEqual(msg.payload, payload)

        # Poll 2: quorum unmet (fake node has 0 attestations) → stays pending,
        # attempts increment.
        self._poll()
        self.assertEqual(msg.state, MessageState.PENDING_QUORUM)

        # Guardians (other than the relayer) attest; relayer's own vote was
        # already counted by the fake node when it attested in poll 2.
        self.node_b.attestations[message_id] = 2

        # Poll 3: quorum met → delivery tx broadcast to BRIDGE_B with the
        # deliverMessage selector and the message id in the calldata.
        self._poll()
        self.assertEqual(msg.state, MessageState.DELIVERING)
        delivery_selector = keccak256(b"deliverMessage(bytes32,bytes,bytes)").hex()[:8]
        self.assertTrue(any(
            delivery_selector in raw and message_id[2:] in raw
            for raw in self.node_b.sent_raw
        ))
        self.assertTrue(msg.delivery_tx.startswith("0x"))

    def test_scan_cursor_deduplicates(self) -> None:
        sender = "0x" + "cd" * 20
        self.node_a.send_message(sender, ECOSYSTEM_EVM, b"one")
        self.node_a.send_message(sender, ECOSYSTEM_EVM, b"two")
        self._poll()
        self._poll()
        self._poll()
        self.assertEqual(len(self.relayer.tracked()), 2)


if __name__ == "__main__":
    unittest.main()
