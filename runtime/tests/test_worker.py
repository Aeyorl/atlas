"""Unit tests for Autonomous Agent Worker Daemon."""
from __future__ import annotations

import json

import pytest

from runtime.executor import TaskExecutor
from runtime.worker import AgentWorker
from sdk.python.chain import capability_word, id_from_seed


class DummySigner:
    def __init__(self, address: str) -> None:
        self.address = address


class MockChainClient:
    """Mock client simulating on-chain task states for worker verification."""

    def __init__(self, agent_address: str) -> None:
        self.signer = DummySigner(agent_address)
        self.tasks: dict[str, dict] = {}
        self.bids: dict[str, list[dict]] = {}
        self.bonds: dict[str, int] = {}
        self.completed_tasks: dict[str, tuple[bytes, bytes]] = {}

    def get_task(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            raise KeyError(f"Task {task_id} not found")
        return self.tasks[task_id]

    def get_bids(self, task_id: str) -> list[dict]:
        return self.bids.get(task_id, [])

    def get_bond(self, task_id: str, bonder: str) -> int:
        return self.bonds.get(task_id, 0)

    def post_bond(self, task_id: str, amount_wei: int) -> None:
        self.bonds[task_id] = self.bonds.get(task_id, 0) + amount_wei

    def submit_bid(self, task_id: str, fee_wei: int) -> None:
        if task_id not in self.bids:
            self.bids[task_id] = []
        self.bids[task_id].append({
            "bidder": self.signer.address,
            "fee_wei": fee_wei,
            "status": "Pending",
        })

    def complete_task(self, task_id: str, result: bytes, proof: bytes = b"") -> None:
        self.completed_tasks[task_id] = (result, proof)
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "Verifying"


@pytest.fixture
def worker_setup():
    agent_addr = "0x" + "11" * 20
    agent_id = id_from_seed("test-worker-agent")
    mock_client = MockChainClient(agent_addr)

    executor = TaskExecutor()

    def dummy_inference(payload: dict) -> dict:
        return {"processed": payload.get("data", "none")}

    executor.register_handler("INFERENCE", dummy_inference)

    worker = AgentWorker(
        client=mock_client,  # type: ignore[arg-type]
        executor=executor,
        agent_id=agent_id,
        capabilities=["INFERENCE"],
        min_fee_wei=10**17,  # 0.1 ETH
        auto_bond=True,
    )

    return worker, mock_client, executor


def test_worker_capability_matching(worker_setup):
    worker, _, _ = worker_setup
    assert worker.is_capable([capability_word("INFERENCE")])
    assert not worker.is_capable([capability_word("TRADE")])
    assert worker.is_capable([])


def test_worker_bids_on_matching_task(worker_setup):
    worker, client, _ = worker_setup
    task_id = id_from_seed("task-open-1")

    client.tasks[task_id] = {
        "task_id": task_id,
        "status": "Open",
        "required_capabilities": [capability_word("INFERENCE")],
        "budget_wei": 10**18,  # 1.0 ETH
        "parameters": "0x",
    }

    report = worker.poll_once([task_id])
    assert report["bids_submitted"] == 1
    assert len(client.bids[task_id]) == 1
    assert client.bids[task_id][0]["fee_wei"] == int(10**18 * 0.8)
    # Bond was posted
    assert client.bonds[task_id] == worker.bond_wei


def test_worker_skips_insufficient_budget(worker_setup):
    worker, client, _ = worker_setup
    task_id = id_from_seed("task-low-budget")

    client.tasks[task_id] = {
        "task_id": task_id,
        "status": "Open",
        "required_capabilities": [capability_word("INFERENCE")],
        "budget_wei": 10**16,  # 0.01 ETH (< 0.1 min fee)
        "parameters": "0x",
    }

    report = worker.poll_once([task_id])
    assert report["bids_submitted"] == 0
    assert task_id not in client.bids


def test_worker_executes_assigned_task(worker_setup):
    worker, client, _ = worker_setup
    task_id = id_from_seed("task-exec-1")

    payload_json = json.dumps({"data": "sample-input"}).encode("utf-8")
    client.tasks[task_id] = {
        "task_id": task_id,
        "status": "Executing",
        "assigned_agent": worker.address,
        "required_capabilities": [capability_word("INFERENCE")],
        "budget_wei": 10**18,
        "parameters": "0x" + payload_json.hex(),
    }

    report = worker.poll_once([task_id])
    assert report["tasks_completed"] == 1
    assert task_id in client.completed_tasks
    result_bytes, proof_bytes = client.completed_tasks[task_id]
    assert len(result_bytes) > 0
    assert len(proof_bytes) > 0
    assert client.tasks[task_id]["status"] == "Verifying"
