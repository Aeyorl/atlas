"""Tests for the Nive Python SDK (offline; models only, no network)."""

from __future__ import annotations

import pytest

from sdk.python import Agent, NiveClient, Task, TaskStatus

# ────────────────────────────────
#  NiveClient
# ────────────────────────────────


def test_client_rejects_unknown_ecosystem():
    with pytest.raises(ValueError, match="Unsupported ecosystem"):
        NiveClient(ecosystem="polkadot")


def test_client_accepts_all_supported_ecosystems():
    for ecosystem in ("robinhood-chain", "evm", "virtuals"):
        client = NiveClient(ecosystem=ecosystem)
        assert client.get_ecosystem() == ecosystem
        assert client._rpc_url  # default RPC resolved


def test_client_create_task_starts_in_created_status():
    client = NiveClient(ecosystem="evm")
    task = client.create_task(
        required_capabilities=["TRADE"],
        budget=10.0,
        parameters={"pair": "ETH/USDC"},
        deadline=1234567890,
    )
    assert isinstance(task, Task)
    assert task.status is TaskStatus.CREATED
    assert task.required_capabilities == ["TRADE"]
    assert task.budget == 10.0
    assert task.parameters == {"pair": "ETH/USDC"}
    assert task.deadline == 1234567890
    assert task.ecosystem == "evm"
    assert task.task_id  # an id was assigned


def test_client_tasks_have_unique_ids():
    client = NiveClient()
    t1 = client.create_task([], 1.0, {})
    t2 = client.create_task([], 1.0, {})
    assert t1.task_id != t2.task_id


# ────────────────────────────────
#  Task lifecycle
# ────────────────────────────────


def test_task_assign_transitions_to_executing():
    task = Task(
        task_id="0x1",
        required_capabilities=["TRADE"],
        budget=5.0,
        parameters={},
        ecosystem="evm",
    )
    assert task.status is TaskStatus.PENDING
    task.assign("agent-1")
    assert task.status is TaskStatus.EXECUTING
    assert task.assigned_agent == "agent-1"


def test_task_complete_transitions_and_stores_result():
    task = Task("0x1", ["TRADE"], 5.0, {}, "evm")
    task.assign("agent-1")
    task.complete({"answer": 42})
    assert task.status is TaskStatus.COMPLETED
    assert task.is_completed
    assert task.result == {"answer": 42}


def test_task_fail_records_reason():
    task = Task("0x1", ["TRADE"], 5.0, {}, "evm")
    task.fail("timeout")
    assert task.status is TaskStatus.FAILED
    assert not task.is_completed
    assert task.result == {"error": "timeout"}


def test_task_status_enum_covers_lifecycle():
    assert {s.value for s in TaskStatus} == {
        "pending", "created", "bidding", "executing",
        "verifying", "completed", "failed", "disputed",
    }


# ────────────────────────────────
#  Agent model
# ────────────────────────────────


def test_agent_success_rate_zero_without_tasks():
    agent = Agent(agent_id="a1", owner="o1", name="A", uri="https://x")
    assert agent.total_tasks == 0
    assert agent.success_rate == 0.0


def test_agent_success_rate_percent():
    agent = Agent("a1", "o1", "A", "https://x", total_tasks=8, successful_tasks=6)
    assert agent.success_rate == pytest.approx(75.0)


def test_agent_can_perform():
    agent = Agent("a1", "o1", "A", "https://x", capabilities=["TRADE", "ORACLE"])
    assert agent.can_perform("TRADE")
    assert not agent.can_perform("LEND")
