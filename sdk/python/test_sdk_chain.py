"""Offline tests for the contract-backed SDK chain layer (sdk/python/chain.py).

No RPC node required: ABI codecs are checked against hand-built payloads and
the client is driven through a stub JSON-RPC transport.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.relayer.chain import keccak256
from runtime.relayer.service import Signer, abi_encode
from sdk.python import chain as chain_mod
from sdk.python.chain import (
    TASK_STATUSES,
    ChainClient,
    Contracts,
    _decode_agent_record,
    _decode_bids,
    _decode_settlement,
    _decode_task,
    capability_word,
    encode_args,
    id_from_seed,
)

# ────────────────────────────────
#  Fixtures / stubs
# ────────────────────────────────

CONTRACTS = Contracts(
    registry="0x" + "aa" * 20,
    task_manager="0x" + "bb" * 20,
    settlement="0x" + "cc" * 20,
    bridge="0x" + "dd" * 20,
    core="0x" + "ee" * 20,
)


class StubTransport:
    """Minimal JsonRpcClient stand-in: canned eth_call responses by selector."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []
        self.raw_txs: list[str] = []
        self.receipt: dict[str, Any] = {
            "status": "0x1", "blockNumber": "0x5", "gasUsed": "0x5208",
        }

    def call(self, method: str, params: list) -> Any:
        if method == "eth_chainId":
            return hex(31337)
        if method == "eth_getTransactionCount":
            return "0x0"
        raise AssertionError(f"unexpected RPC method: {method}")

    def chain_id(self) -> int:
        return 31337

    def send_raw_transaction(self, signed: str) -> str:
        self.raw_txs.append(signed)
        return "0x" + "ff" * 32

    def wait_for_receipt(self, tx_hash: str, timeout_seconds: float = 60.0,
                         poll: float = 0.25) -> dict:
        return dict(self.receipt, transactionHash=tx_hash)

    def call_contract(self, to: str, data: str, block: int | None = None) -> str:
        self.calls.append((to, data))
        return self.responses.get(data[2:10], "0x")


@pytest.fixture()
def stub(monkeypatch: pytest.MonkeyPatch) -> StubTransport:
    transport = StubTransport()
    monkeypatch.setattr(chain_mod, "JsonRpcClient", lambda url: transport)
    return transport


def make_client(stub: StubTransport, key: str | None = None) -> ChainClient:
    signer = Signer(key) if key else None
    return ChainClient("http://localhost:1", CONTRACTS, signer=signer)


def _sel(signature: str) -> str:
    return keccak256(signature.encode())[:4].hex()


def _word(value: int | bytes | str) -> bytes:
    """32-byte ABI word from an int, hex string (left-padded), or text bytes."""
    if isinstance(value, bool):
        return int(value).to_bytes(32, "big")
    if isinstance(value, int):
        return value.to_bytes(32, "big")
    if isinstance(value, str):
        return bytes.fromhex(value.removeprefix("0x")).rjust(32, b"\x00")
    return value.ljust(32, b"\x00") if len(value) < 32 else value


def _rlp_decode(blob: bytes) -> list[Any]:
    """Minimal RLP decoder for a top-level list of items (test helper)."""

    def read_item(buf: bytes, i: int) -> tuple[Any, int]:
        prefix = buf[i]
        if prefix < 0x80:
            return buf[i:i + 1], i + 1
        if prefix < 0xb8:                       # short string
            n = prefix - 0x80
            return buf[i + 1:i + 1 + n], i + 1 + n
        if prefix < 0xc0:                       # long string
            ln = prefix - 0xb7
            n = int.from_bytes(buf[i + 1:i + 1 + ln], "big")
            return buf[i + 1 + ln:i + 1 + ln + n], i + 1 + ln + n
        if prefix < 0xf8:                       # short list
            end, items, j = i + 1 + (prefix - 0xc0), [], i + 1
            while j < end:
                item, j = read_item(buf, j)
                items.append(item)
            return items, end
        ln = prefix - 0xf7                      # long list
        n = int.from_bytes(buf[i + 1:i + 1 + ln], "big")
        end, items, j = i + 1 + ln + n, [], i + 1 + ln
        while j < end:
            item, j = read_item(buf, j)
            items.append(item)
        return items, end

    items, _ = read_item(blob, 0)
    return items


# ────────────────────────────────
#  Encoding
# ────────────────────────────────


class TestEncodeArgs:
    def test_static_only(self) -> None:
        b32 = "0x" + "ab" * 32
        addr = "0x" + "cd" * 20
        encoded = encode_args([b32, addr, 7, True])
        assert encoded == _word(b32) + _word(int(addr, 16)) + _word(7) + _word(1)

    def test_mixed_dynamic_offsets(self) -> None:
        payload = b"hi"
        b32 = "0x" + "ab" * 32
        caps = [capability_word("TRADE")]
        text = "text"
        encoded = encode_args([payload, b32, 7, caps, text])
        # head: [bytes off][bytes32][uint][array off][string off]
        head = [encoded[32 * i: 32 * (i + 1)] for i in range(5)]
        assert int.from_bytes(head[0], "big") == 160          # bytes tail
        assert head[1] == _word(b32)
        assert int.from_bytes(head[2], "big") == 7
        assert int.from_bytes(head[3], "big") == 224          # after bytes tail
        assert int.from_bytes(head[4], "big") == 288          # after array tail
        # tail: bytes block, array block, string block
        tail = encoded[160:]
        assert int.from_bytes(tail[:32], "big") == 2
        assert tail[32:34] == b"hi"
        arr = encoded[224:]
        assert int.from_bytes(arr[:32], "big") == 1
        assert arr[32:64] == bytes.fromhex(caps[0][2:])
        s = encoded[288:]
        assert int.from_bytes(s[:32], "big") == 4
        assert s[32:36] == b"text"

    def test_empty_array_and_bytes(self) -> None:
        encoded = encode_args([[], b""])
        assert len(encoded) == 32 * 4  # 2 head words + 2 length words
        assert int.from_bytes(encoded[64:96], "big") == 0
        assert int.from_bytes(encoded[96:128], "big") == 0

    def test_rejects_bad_bytes32_list(self) -> None:
        with pytest.raises(TypeError):
            encode_args([["not-a-word"]])


# ────────────────────────────────
#  Decoding (hand-built payloads)
# ────────────────────────────────


class TestDecoding:
    def test_agent_record(self) -> None:
        agent_id = keccak256(b"agent")
        owner = bytes.fromhex("11" * 20)
        wallet = bytes.fromhex("22" * 20)
        uri = b"https://a.example"          # 17 bytes → 1 data word
        cap = bytes.fromhex(capability_word("TRADE")[2:])
        struct = (
            agent_id + owner.rjust(32, b"\x00")
            + (288).to_bytes(32, "big")     # uri offset (relative to struct)
            + (352).to_bytes(32, "big")     # capabilities offset
            + wallet.rjust(32, b"\x00")
            + _word(123) + _word(1) + _word(4) + _word(3)
            + len(uri).to_bytes(32, "big") + uri.ljust(32, b"\x00")
            + (1).to_bytes(32, "big") + cap
        )
        data = "0x" + (32).to_bytes(32, "big").hex() + struct.hex()
        record = _decode_agent_record(data)
        assert record["agent_id"] == "0x" + agent_id.hex()
        assert record["owner"] == "0x" + "11" * 20
        assert record["uri"] == uri.decode()
        assert record["capabilities"] == ["0x" + cap.hex()]
        assert record["execution_wallet"] == "0x" + "22" * 20
        assert record["min_fee_wei"] == 123
        assert record["active"] is True
        assert record["total_tasks"] == 4
        assert record["successful_tasks"] == 3

    def test_task(self) -> None:
        task_id = keccak256(b"task")
        creator = bytes.fromhex("33" * 20)
        assigned = bytes.fromhex("44" * 20)
        cap = bytes.fromhex(capability_word("ANALYZE")[2:])
        params = b'{"x":1}'                 # 7 bytes → 1 data word
        struct = (
            task_id + creator.rjust(32, b"\x00")
            + (288).to_bytes(32, "big")     # capabilities offset
            + _word(10 ** 18)
            + (352).to_bytes(32, "big")     # parameters offset
            + _word(1)                      # TaskStatus.Bidding
            + assigned.rjust(32, b"\x00") + _word(1000) + _word(2000)
            + (1).to_bytes(32, "big") + cap
            + len(params).to_bytes(32, "big") + params.ljust(32, b"\x00")
        )
        data = "0x" + (32).to_bytes(32, "big").hex() + struct.hex()
        task = _decode_task(data)
        assert task["task_id"] == "0x" + task_id.hex()
        assert task["creator"] == "0x" + "33" * 20
        assert task["required_capabilities"] == ["0x" + cap.hex()]
        assert task["budget_wei"] == 10 ** 18
        assert bytes.fromhex(str(task["parameters"]).removeprefix("0x")) == params
        assert task["status"] == TASK_STATUSES[1] == "Bidding"
        assert task["assigned_agent"] == "0x" + "44" * 20
        assert task["created_at"] == 1000
        assert task["deadline"] == 2000

    def test_bids(self) -> None:
        bidder1, bidder2 = bytes.fromhex("55" * 20), bytes.fromhex("66" * 20)
        raw = (
            (32).to_bytes(32, "big")        # array offset wrapper
            + (2).to_bytes(32, "big")       # length
            + bidder1.rjust(32, b"\x00") + _word(5 * 10 ** 17) + _word(1)
            + bidder2.rjust(32, b"\x00") + _word(10 ** 18) + _word(2)
        )
        bids = _decode_bids("0x" + raw.hex())
        assert bids == [
            {"bidder": "0x" + "55" * 20, "fee_wei": 5 * 10 ** 17, "status": "Accepted"},
            {"bidder": "0x" + "66" * 20, "fee_wei": 10 ** 18, "status": "Rejected"},
        ]

    def test_settlement(self) -> None:
        task_id = keccak256(b"task")
        agent, creator = bytes.fromhex("77" * 20), bytes.fromhex("88" * 20)
        struct = (
            task_id + agent.rjust(32, b"\x00") + creator.rjust(32, b"\x00")
            + _word(9 * 10 ** 17) + _word(5 * 10 ** 16) + _word(25 * 10 ** 15)
            + _word(1)
        )
        data = "0x" + (32).to_bytes(32, "big").hex() + struct.hex()
        settlement = _decode_settlement(data)
        assert settlement["agent"] == "0x" + "77" * 20
        assert settlement["settled"] is True
        assert settlement["agent_fee_wei"] == 9 * 10 ** 17


# ────────────────────────────────
#  Client behaviour (stub transport)
# ────────────────────────────────


class TestChainClientReads:
    def test_get_agent_sends_selector_and_decodes(self, stub: StubTransport) -> None:
        agent_id = id_from_seed("my-agent")
        cap = bytes.fromhex(capability_word("TRADE")[2:])
        struct = (
            bytes.fromhex(agent_id[2:]) + bytes.fromhex("11" * 20).rjust(32, b"\x00")
            + (288).to_bytes(32, "big") + (352).to_bytes(32, "big")
            + bytes.fromhex("22" * 20).rjust(32, b"\x00")
            + _word(0) + _word(1) + _word(0) + _word(0)
            + (4).to_bytes(32, "big") + b"http".ljust(32, b"\x00")
            + (1).to_bytes(32, "big") + cap
        )
        stub.responses[_sel("getAgent(bytes32)")] = (
            "0x" + (32).to_bytes(32, "big").hex() + struct.hex())
        client = make_client(stub)
        record = client.get_agent(agent_id)
        to, data = stub.calls[0]
        assert to == CONTRACTS.registry
        assert data[2:10] == _sel("getAgent(bytes32)")
        assert bytes.fromhex(data[10:])[0:32] == bytes.fromhex(agent_id[2:])
        assert record["uri"] == "http"

    def test_agent_ids_for_owner(self, stub: StubTransport) -> None:
        owner = "0x" + "11" * 20
        word = keccak256(b"agent")
        stub.responses[_sel("getAgentByOwner(address)")] = "0x" + (
            (32).to_bytes(32, "big") + (1).to_bytes(32, "big") + word
        ).hex()
        client = make_client(stub)
        assert client.agent_ids_for_owner(owner) == ["0x" + word.hex()]

    def test_uint_reads(self, stub: StubTransport) -> None:
        stub.responses[_sel("getAgentCount()")] = "0x" + _word(3).hex()
        stub.responses[_sel("getTaskCount()")] = "0x" + _word(9).hex()
        stub.responses[_sel("getEscrow(bytes32)")] = "0x" + _word(10 ** 18).hex()
        client = make_client(stub)
        assert client.agent_count() == 3
        assert client.task_count() == 9
        assert client.escrow(id_from_seed("t")) == 10 ** 18

    def test_missing_address_raises(self, stub: StubTransport) -> None:
        client = ChainClient("http://localhost:1",
                             Contracts(registry="", task_manager="", settlement=""))
        with pytest.raises(ValueError, match="registry"):
            client.agent_count()

    def test_missing_bridge_address_raises(self, stub: StubTransport) -> None:
        client = ChainClient("http://localhost:1", Contracts(
            registry="0x" + "aa" * 20, task_manager="0x" + "bb" * 20,
            settlement="0x" + "cc" * 20), signer=Signer("0x" + "11" * 32))
        with pytest.raises(ValueError, match="bridge"):
            client.send_bridge_message("evm", b"x")


class TestChainClientWrites:
    KEY = "0x" + "11" * 32

    def test_register_agent_sends_signed_tx(self, stub: StubTransport) -> None:
        client = make_client(stub, key=self.KEY)
        receipt = client.register_agent(
            id_from_seed("a"), "https://x", [capability_word("TRADE")],
            min_fee_wei=5)
        assert len(stub.raw_txs) == 1
        assert receipt.status == "0x1"
        assert receipt.block == 5
        assert receipt.gas_used == 0x5208
        assert receipt.tx_hash == "0x" + "ff" * 32

    def test_write_without_signer_raises(self, stub: StubTransport) -> None:
        client = make_client(stub)
        with pytest.raises(ValueError, match="signer"):
            client.register_agent(id_from_seed("a"), "u", [])

    def test_create_task_escrows_budget_as_value(self, stub: StubTransport) -> None:
        """Decode the signed legacy tx: msg.value must equal the budget."""
        client = make_client(stub, key=self.KEY)
        budget = 10 ** 17
        receipt = client.create_task(
            id_from_seed("task"), [capability_word("TRADE")], budget,
            parameters=b'{"pair":"BTC/USD"}')
        assert receipt.status == "0x1"
        # Signed legacy EIP-155 tx: RLP([nonce, gasPrice, gas, to, value,
        # data, v, r, s]).
        fields = _rlp_decode(bytes.fromhex(stub.raw_txs[0].removeprefix("0x")))
        assert len(fields) == 9
        to = fields[3]
        assert isinstance(to, bytes) and to == bytes.fromhex(CONTRACTS.task_manager[2:])
        assert int.from_bytes(fields[4], "big") == budget  # msg.value == budget
        calldata = fields[5]
        assert calldata[:4] == keccak256(
            b"createTask(bytes32,bytes32[],uint256,bytes,uint256)")[:4]

    def test_reverted_tx_raises(self, stub: StubTransport) -> None:
        stub.receipt = {"status": "0x0", "blockNumber": "0x5", "gasUsed": "0x1"}
        client = make_client(stub, key=self.KEY)
        with pytest.raises(RuntimeError, match="reverted"):
            client.submit_bid(id_from_seed("t"), 1)

    def test_send_bridge_message_derives_id(self, stub: StubTransport) -> None:
        local = keccak256(b"evm")
        target = keccak256(b"virtuals")
        payload = b'{"hello":"world"}'
        stub.responses[_sel("localEcosystem()")] = "0x" + local.hex()
        stub.responses[_sel("outboxCount()")] = "0x" + _word(2).hex()
        client = make_client(stub, key=self.KEY)
        message_id = client.send_bridge_message("virtuals", payload)
        expected = keccak256(abi_encode([
            "0x" + local.hex(), "0x" + target.hex(), payload,
            Signer(self.KEY).address, 31337, 2,
        ]))
        assert message_id == "0x" + expected.hex()
        # Both reads happen before the send.
        to0, _ = stub.calls[0]
        to1, _ = stub.calls[1]
        assert {to0, to1} == {CONTRACTS.bridge}
        assert len(stub.raw_txs) == 1


class TestConstruction:
    def test_from_env_missing_rpc_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NIVE_RPC_URL", raising=False)
        with pytest.raises(ValueError, match="NIVE_RPC_URL"):
            ChainClient.from_env()

    def test_from_env_builds_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NIVE_RPC_URL", "http://node:8545")
        monkeypatch.setenv("NIVE_REGISTRY_ADDRESS", "0x" + "aa" * 20)
        monkeypatch.setenv("NIVE_TASK_MANAGER_ADDRESS", "0x" + "bb" * 20)
        monkeypatch.setenv("NIVE_SETTLEMENT_ADDRESS", "0x" + "cc" * 20)
        monkeypatch.delenv("NIVE_PRIVATE_KEY", raising=False)
        client = ChainClient.from_env()
        assert client.contracts.registry == "0x" + "aa" * 20
        assert client.signer is None

    def test_from_env_picks_up_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NIVE_RPC_URL", "http://node:8545")
        monkeypatch.setenv("NIVE_REGISTRY_ADDRESS", "0x" + "aa" * 20)
        monkeypatch.setenv("NIVE_TASK_MANAGER_ADDRESS", "0x" + "bb" * 20)
        monkeypatch.setenv("NIVE_SETTLEMENT_ADDRESS", "0x" + "cc" * 20)
        monkeypatch.setenv("NIVE_PRIVATE_KEY", "0x" + "11" * 32)
        client = ChainClient.from_env()
        assert client.signer is not None
        assert client.signer.address == Signer("0x" + "11" * 32).address

    def test_from_config(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        config = tmp_path / "nive.json"
        config.write_text(
            '{"rpc_url": "http://n:1", "contracts": {"registry": "'
            + "0x" + "aa" * 20 + '", "task_manager": "", "settlement": ""}}',
            encoding="utf-8")
        monkeypatch.delenv("NIVE_PRIVATE_KEY", raising=False)
        client = ChainClient.from_config(str(config))
        assert client.client is not None
        assert client.contracts.registry == "0x" + "aa" * 20

    def test_from_config_missing_rpc_raises(self, tmp_path) -> None:
        config = tmp_path / "nive.json"
        config.write_text('{"contracts": {}}', encoding="utf-8")
        with pytest.raises(ValueError, match="rpc_url"):
            ChainClient.from_config(str(config))


# ────────────────────────────────
#  Helpers
# ────────────────────────────────


class TestHelpers:
    def test_capability_word(self) -> None:
        assert capability_word("TRADE") == "0x" + b"TRADE".ljust(32, b"\x00").hex()
        assert len(capability_word("x")) == 66
        with pytest.raises(ValueError):
            capability_word("x" * 33)

    def test_id_from_seed_is_keccak(self) -> None:
        assert id_from_seed("seed") == "0x" + keccak256(b"seed").hex()
        assert id_from_seed("a") != id_from_seed("b")
