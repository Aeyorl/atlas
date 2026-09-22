"""Offline tests for the contract-backed Nive CLI (cli/main.py).

ChainClient is replaced with a recording stub; no RPC node or network needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pytest

from cli import main as cli_main
from runtime.relayer.service import Signer
from sdk.python.chain import capability_word, id_from_seed


@dataclass
class _StubReceipt:
    tx_hash: str
    status: str
    block: int
    gas_used: int


class StubChain:
    """Records calls; signer configurable per test."""

    signer: Signer | None = None
    last: ClassVar[dict[str, Any]] = {}

    @classmethod
    def _build(cls) -> StubChain:
        import os

        instance = cls()
        key = os.environ.get("NIVE_PRIVATE_KEY")
        instance.signer = Signer(key) if key else None
        return instance

    @classmethod
    def from_env(cls) -> StubChain:
        return cls._build()

    @classmethod
    def from_config(cls, path: str) -> StubChain:
        return cls._build()

    def get_agent(self, agent_id: str) -> dict[str, object]:
        StubChain.last["get_agent"] = agent_id
        return {
            "agent_id": agent_id, "owner": "0x" + "11" * 20,
            "uri": "https://x", "capabilities": [capability_word("TRADE")],
            "execution_wallet": "0x" + "22" * 20, "min_fee_wei": 0,
            "active": True, "total_tasks": 2, "successful_tasks": 1,
        }

    def agent_count(self) -> int:
        return 7

    def get_task(self, task_id: str) -> dict[str, object]:
        StubChain.last["get_task"] = task_id
        return {
            "task_id": task_id, "creator": "0x" + "11" * 20,
            "required_capabilities": [capability_word("TRADE")],
            "budget_wei": 10 ** 18, "parameters": "0x7b2278223a317d",
            "status": "Bidding", "assigned_agent": "0x" + "00" * 20,
            "created_at": 1000, "deadline": 2000,
        }

    def get_bids(self, task_id: str) -> list[dict[str, object]]:
        StubChain.last["get_bids"] = task_id
        return [{"bidder": "0x" + "33" * 20, "fee_wei": 5 * 10 ** 17,
                 "status": "Pending"}]

    def search_by_capability(self, capability: str) -> list[str]:
        StubChain.last["search"] = capability
        return [id_from_seed("a")]

    def escrow(self, task_id: str) -> int:
        StubChain.last["escrow"] = task_id
        return 10 ** 18

    def settlement(self, task_id: str) -> dict[str, object]:
        return {"task_id": "0x" + "00" * 32, "agent": "0x" + "33" * 20,
                "creator": "0x" + "11" * 20, "agent_fee_wei": 9 * 10 ** 17,
                "guardian_fee_wei": 5 * 10 ** 16,
                "protocol_fee_wei": 25 * 10 ** 15, "settled": True}

    def guardian_count(self) -> int:
        return 3

    def register_agent(self, agent_id: str, uri: str, capabilities: list[str],
                       execution_wallet: str | None = None,
                       min_fee_wei: int = 0) -> dict:
        StubChain.last["register_agent"] = (agent_id, uri, capabilities, min_fee_wei)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def create_task(self, task_id: str, required_capabilities: list[str],
                    budget_wei: int, parameters: bytes = b"",
                    deadline: int | None = None,
                    value: int | None = None) -> dict:
        StubChain.last["create_task"] = (task_id, required_capabilities,
                                         budget_wei, parameters)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def submit_bid(self, task_id: str, fee_wei: int) -> dict:
        StubChain.last["submit_bid"] = (task_id, fee_wei)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def complete_task(self, task_id: str, result: bytes, proof: bytes = b"") -> dict:
        StubChain.last["complete_task"] = (task_id, result, proof)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def verify_task(self, task_id: str, valid: bool) -> dict:
        StubChain.last["verify_task"] = (task_id, valid)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def dispute_task(self, task_id: str, evidence: bytes = b"") -> dict:
        StubChain.last["dispute_task"] = (task_id, evidence)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def resolve_dispute(self, task_id: str, agent_valid: bool) -> dict:
        StubChain.last["resolve_dispute"] = (task_id, agent_valid)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def withdraw_escrow(self, task_id: str) -> dict:
        StubChain.last["withdraw_escrow"] = task_id
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def settle_task(self, task_id: str) -> dict:
        StubChain.last["settle_task"] = task_id
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def post_bond(self, task_id: str, amount_wei: int) -> dict:
        StubChain.last["post_bond"] = (task_id, amount_wei)
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def get_bond(self, task_id: str, bonder: str) -> int:
        StubChain.last["get_bond"] = (task_id, bonder)
        return 5 * 10 ** 17

    def withdraw_bond(self, task_id: str) -> dict:
        StubChain.last["withdraw_bond"] = task_id
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)

    def send_bridge_message(self, target: str, payload: bytes) -> str:
        StubChain.last["bridge"] = (target, payload)
        return id_from_seed("msg")

    def register_guardian(self, stake_wei: int) -> dict:
        StubChain.last["guardian"] = stake_wei
        return _StubReceipt("0x" + "ff" * 32, "0x1", 1, 100)


@pytest.fixture()
def stub_cls(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> type[StubChain]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NIVE_RPC_URL", "http://stub:1")  # from_env fallback
    monkeypatch.delenv("NIVE_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(cli_main, "ChainClient", StubChain)
    StubChain.last = {}
    return StubChain


def run(argv: list[str]) -> int:
    return cli_main.main(argv)


# ────────────────────────────────
#  init
# ────────────────────────────────


class TestInit:
    def test_writes_config(self, stub_cls) -> None:
        assert run(["init"]) == 0
        data = json.loads(Path("nive.json").read_text(encoding="utf-8"))
        assert data["contracts"]["registry"] == ""
        assert data["rpc_url"].startswith("http")

    def test_refuses_existing_without_force(self, stub_cls) -> None:
        run(["init"])
        with pytest.raises(SystemExit, match="already exists"):
            run(["init"])
        assert run(["init", "--force"]) == 0


# ────────────────────────────────
#  Reads (keyless)
# ────────────────────────────────


class TestReads:
    def test_agent_get_by_seed(self, stub_cls, capsys) -> None:
        assert run(["agent", "get", "--seed", "my-agent"]) == 0
        assert StubChain.last["get_agent"] == id_from_seed("my-agent")
        out = capsys.readouterr().out
        assert "https://x" in out
        assert "TRADE" in out

    def test_task_get(self, stub_cls, capsys) -> None:
        assert run(["task", "get", "--seed", "t1"]) == 0
        assert StubChain.last["get_task"] == id_from_seed("t1")
        assert "Bidding" in capsys.readouterr().out

    def test_task_bids(self, stub_cls, capsys) -> None:
        assert run(["task", "bids", "--seed", "t1"]) == 0
        out = capsys.readouterr().out
        assert "5 NIVE" in out and "Pending" in out

    def test_agent_search_encodes_capability(self, stub_cls) -> None:
        assert run(["agent", "search", "--capability", "TRADE"]) == 0
        assert StubChain.last["search"] == capability_word("TRADE")

    def test_agent_count(self, stub_cls, capsys) -> None:
        assert run(["agent", "count"]) == 0
        assert "7" in capsys.readouterr().out


# ────────────────────────────────
#  Writes (need NIVE_PRIVATE_KEY)
# ────────────────────────────────


class TestWrites:
    KEY = "0x" + "11" * 32

    def test_write_without_key_fails(self, stub_cls, monkeypatch) -> None:
        with pytest.raises(SystemExit, match="NIVE_PRIVATE_KEY"):
            run(["task", "create", "--seed", "t", "--capabilities", "TRADE",
                 "--budget-ether", "1"])

    def test_task_create_escrows_budget(self, stub_cls, monkeypatch) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "create", "--seed", "t9", "--capabilities", "TRADE",
                    "--budget-ether", "2.5", "--parameters", '{"x":1}',
                    "--days", "3"]) == 0
        task_id, caps, budget_wei, params = StubChain.last["create_task"]
        assert task_id == id_from_seed("t9")
        assert caps == [capability_word("TRADE")]
        assert budget_wei == 25 * 10 ** 17
        assert params == b'{"x":1}'

    def test_agent_register(self, stub_cls, monkeypatch) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["agent", "register", "--seed", "a1", "--uri", "https://x",
                    "--capabilities", "TRADE", "ANALYZE",
                    "--min-fee", "0.5"]) == 0
        agent_id, uri, caps, min_fee = StubChain.last["register_agent"]
        assert agent_id == id_from_seed("a1")
        assert uri == "https://x"
        assert caps == [capability_word("TRADE"), capability_word("ANALYZE")]
        assert min_fee == 5 * 10 ** 17

    def test_task_bid(self, stub_cls, monkeypatch) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "bid", "--seed", "t1", "--fee-ether", "0.75"]) == 0
        assert StubChain.last["submit_bid"] == (id_from_seed("t1"),
                                                75 * 10 ** 16)

    def test_bridge_send(self, stub_cls, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["bridge", "send", "--target", "virtuals",
                    "--payload", "hi"]) == 0
        target, payload = StubChain.last["bridge"]
        assert target == "virtuals" and payload == b"hi"
        assert id_from_seed("msg") in capsys.readouterr().out

    def test_task_complete_with_proof(self, stub_cls, monkeypatch) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "complete", "--seed", "t1", "--result", "done", "--proof", "0x1234"]) == 0
        task_id, result, proof = StubChain.last["complete_task"]
        assert task_id == id_from_seed("t1")
        assert result == b"done"
        assert proof == bytes.fromhex("1234")

    def test_task_verify(self, stub_cls, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "verify", "--seed", "t1"]) == 0
        assert StubChain.last["verify_task"] == (id_from_seed("t1"), True)
        assert "verified" in capsys.readouterr().out

        assert run(["task", "verify", "--seed", "t1", "--reject"]) == 0
        assert StubChain.last["verify_task"] == (id_from_seed("t1"), False)
        assert "rejected" in capsys.readouterr().out

    def test_task_dispute(self, stub_cls, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "dispute", "--seed", "t1", "--evidence", "bad output"]) == 0
        assert StubChain.last["dispute_task"] == (id_from_seed("t1"), b"bad output")
        assert "task disputed" in capsys.readouterr().out

    def test_task_resolve_dispute(self, stub_cls, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "resolve-dispute", "--seed", "t1", "--agent-valid"]) == 0
        assert StubChain.last["resolve_dispute"] == (id_from_seed("t1"), True)
        assert "agent's favor" in capsys.readouterr().out

        assert run(["task", "resolve-dispute", "--seed", "t1", "--creator-valid"]) == 0
        assert StubChain.last["resolve_dispute"] == (id_from_seed("t1"), False)
        assert "creator's favor" in capsys.readouterr().out

    def test_task_withdraw_escrow(self, stub_cls, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["task", "withdraw-escrow", "--seed", "t1"]) == 0
        assert StubChain.last["withdraw_escrow"] == id_from_seed("t1")
        assert "escrow withdrawn" in capsys.readouterr().out

    def test_settlement_get(self, stub_cls, capsys) -> None:
        assert run(["settlement", "get", "--seed", "t1"]) == 0
        out = capsys.readouterr().out
        assert "agent fee" in out and "guardian fee" in out

    def test_bond_lifecycle(self, stub_cls, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NIVE_PRIVATE_KEY", self.KEY)
        assert run(["bond", "post", "--seed", "t1", "--amount-ether", "0.5"]) == 0
        assert StubChain.last["post_bond"] == (id_from_seed("t1"), 5 * 10 ** 17)

        assert run(["bond", "get", "--seed", "t1", "--bonder", "0x" + "aa" * 20]) == 0
        assert StubChain.last["get_bond"] == (id_from_seed("t1"), "0x" + "aa" * 20)
        assert "0.5 NIVE" in capsys.readouterr().out

        assert run(["bond", "withdraw", "--seed", "t1"]) == 0
        assert StubChain.last["withdraw_bond"] == id_from_seed("t1")


# ────────────────────────────────
#  Errors / helpers
# ────────────────────────────────


class TestErrors:
    def test_id_required(self, stub_cls) -> None:
        with pytest.raises(SystemExit, match="--id or --seed"):
            run(["agent", "get"])

    def test_unknown_command_exits(self, stub_cls) -> None:
        with pytest.raises(SystemExit):
            run(["nope"])

    def test_runtime_error_reported_not_raised(
            self, stub_cls, monkeypatch, capsys) -> None:
        def boom() -> int:
            raise RuntimeError("rpc down")

        monkeypatch.setattr(cli_main, "cmd_agent_count", lambda args: boom())
        assert run(["agent", "count"]) == 1
        assert "rpc down" in capsys.readouterr().err
