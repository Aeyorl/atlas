"""Unit tests for Dregg Gaming Escrow Adapter."""
from __future__ import annotations

import pytest

from integrations.dregg.dregg_adapter import DreggNiveEscrowAdapter
from sdk.python.chain import capability_word


class MockChainClient:
    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.completed_tasks: dict[str, tuple[bytes, bytes]] = {}

    def create_task(self, task_id: str, required_capabilities: list[str], budget_wei: int, parameters: bytes = b"", deadline: int | None = None) -> None:
        self.tasks[task_id] = {
            "task_id": task_id,
            "capabilities": required_capabilities,
            "budget": budget_wei,
            "params": parameters,
            "status": "Open",
            "assigned_agent": None,
        }

    def accept_bid(self, task_id: str, agent_address: str) -> None:
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "Executing"
            self.tasks[task_id]["assigned_agent"] = agent_address

    def complete_task(self, task_id: str, result: bytes, proof: bytes = b"") -> None:
        self.completed_tasks[task_id] = (result, proof)
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "Verifying"


@pytest.fixture
def dregg_setup():
    mock_client = MockChainClient()
    adapter = DreggNiveEscrowAdapter(mock_client, network_name="robinhood-chain")  # type: ignore[arg-type]
    return adapter, mock_client


def test_create_arena_match(dregg_setup):
    adapter, client = dregg_setup
    match = adapter.create_arena_match(
        match_id="battle-88",
        arena_id="arena-robinhood-1",
        entry_fee_wei=10**18,
        creator_address="0x" + "aa" * 20,
        capability="TRADE",
    )

    assert match.match_id == "battle-88"
    assert match.entry_fee_wei == 10**18
    assert match.task_id in client.tasks
    assert capability_word("TRADE") in client.tasks[match.task_id]["capabilities"]


def test_assign_combatant(dregg_setup):
    adapter, client = dregg_setup
    match = adapter.create_arena_match(
        match_id="battle-89",
        arena_id="arena-robinhood-1",
        entry_fee_wei=10**18,
        creator_address="0x" + "aa" * 20,
    )
    agent_wallet = "0x" + "bb" * 20
    adapter.assign_combatant_bid(match.match_id, agent_wallet)

    assert match.status == "InGame"
    assert match.assigned_combatant == agent_wallet
    assert client.tasks[match.task_id]["status"] == "Executing"


def test_settle_match_outcome(dregg_setup):
    adapter, client = dregg_setup
    match = adapter.create_arena_match(
        match_id="battle-90",
        arena_id="arena-robinhood-1",
        entry_fee_wei=10**18,
        creator_address="0x" + "aa" * 20,
    )
    winner_wallet = "0x" + "bb" * 20
    transcript = {
        "score_a": 120,
        "score_b": 240,
        "winner": winner_wallet,
        "round_turns": 15,
    }

    report = adapter.settle_match_outcome(match.match_id, winner_wallet, transcript)

    assert report["match_id"] == "battle-90"
    assert report["winner"] == winner_wallet
    assert report["result_hash"].startswith("0x")
    assert len(report["limbs"]) == 4
    assert match.task_id in client.completed_tasks
    assert client.tasks[match.task_id]["status"] == "Verifying"
