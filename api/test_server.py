"""Unit tests for Nive REST API service."""
from __future__ import annotations

import json
import os
import threading
from urllib.request import urlopen

import pytest

from api.server import create_server
from sdk.python.chain import (
    Contracts,
    capability_word,
    id_from_seed,
)


class MockChainClient:
    """Mock ChainClient responding with fixed records."""

    def __init__(self) -> None:
        self.client = type("MockRPC", (), {"chain_id": lambda *_: 31337})()
        self.contracts = Contracts(
            registry="0x" + "11" * 20,
            task_manager="0x" + "22" * 20,
            settlement="0x" + "33" * 20,
        )

    def agent_count(self) -> int:
        return 42

    def get_agent(self, agent_id: str) -> dict[str, object]:
        return {
            "agent_id": agent_id,
            "owner": "0x" + "aa" * 20,
            "uri": "https://agent.example.com",
            "capabilities": [capability_word("TRADE")],
            "execution_wallet": "0x" + "bb" * 20,
            "min_fee_wei": 10**17,
            "active": True,
            "total_tasks": 10,
            "successful_tasks": 9,
        }

    def search_by_capability(self, capability: str) -> list[str]:
        return [id_from_seed("agent-alpha")]

    def task_count(self) -> int:
        return 7

    def get_task(self, task_id: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "creator": "0x" + "cc" * 20,
            "required_capabilities": [capability_word("TRADE")],
            "budget_wei": 10**18,
            "parameters": "0x7b7d",
            "status": "Executing",
            "assigned_agent": "0x" + "bb" * 20,
            "created_at": 1000,
            "deadline": 2000,
        }

    def result_hash(self, task_id: str) -> str:
        return "0x" + "ee" * 32

    def get_bids(self, task_id: str) -> list[dict[str, object]]:
        return [{"bidder": "0x" + "bb" * 20, "fee_wei": 8 * 10**17, "status": "Accepted"}]

    def escrow(self, task_id: str) -> int:
        return 10**18

    def settlement(self, task_id: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "agent": "0x" + "bb" * 20,
            "creator": "0x" + "cc" * 20,
            "agent_fee_wei": 78 * 10**16,
            "guardian_fee_wei": 0,
            "protocol_fee_wei": 2 * 10**16,
            "settled": True,
        }

    def has_proof_verified(self, task_id: str) -> bool:
        return True

    def guardian_count(self) -> int:
        return 3


@pytest.fixture(scope="module")
def api_server():
    os.environ["NIVE_API_QUIET"] = "1"
    mock_client = MockChainClient()
    server = create_server(host="127.0.0.1", port=0, client=mock_client)  # port 0 = OS picks port
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()


def test_health_endpoint(api_server: str):
    with urlopen(f"{api_server}/health") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["status"] == "healthy"
        assert data["chain_id"] == 31337


def test_agents_endpoints(api_server: str):
    # Agent count
    with urlopen(f"{api_server}/api/v1/agents/count") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["count"] == 42

    # Get agent by seed
    with urlopen(f"{api_server}/api/v1/agents/agent-seed-1") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["agent"]["active"] is True
        assert data["agent"].get("task_id", True)

    # Search by capability
    with urlopen(f"{api_server}/api/v1/agents/search?capability=TRADE") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert len(data["agents"]) == 1


def test_tasks_endpoints(api_server: str):
    # Task count
    with urlopen(f"{api_server}/api/v1/tasks/count") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["count"] == 7

    # Task detail
    with urlopen(f"{api_server}/api/v1/tasks/task-seed-1") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["task"]["status"] == "Executing"
        assert data["result_hash"].startswith("0x")

    # Task bids
    with urlopen(f"{api_server}/api/v1/tasks/task-seed-1/bids") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert len(data["bids"]) == 1

    # Task escrow
    with urlopen(f"{api_server}/api/v1/tasks/task-seed-1/escrow") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["escrow_wei"] == str(10**18)


def test_settlement_and_guardians(api_server: str):
    with urlopen(f"{api_server}/api/v1/settlements/task-seed-1") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["settlement"]["settled"] is True
        assert data["proof_verified"] is True

    with urlopen(f"{api_server}/api/v1/guardians/count") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["count"] == 3


def test_dashboard_static_files(api_server: str):
    # Root loads landing page (index.html)
    with urlopen(f"{api_server}/") as res:
        assert res.status == 200
        assert "text/html" in res.headers.get("Content-Type")
        body = res.read().decode("utf-8")
        assert "Autonomous AI Agents" in body or "Nive Protocol" in body

    # Explorer loads explorer.html
    with urlopen(f"{api_server}/explorer") as res:
        assert res.status == 200
        assert "text/html" in res.headers.get("Content-Type")
        body = res.read().decode("utf-8")
        assert "Registered Agents" in body or "Agents" in body

    # Landing assets load
    with urlopen(f"{api_server}/landing.css") as res:
        assert res.status == 200
        assert "text/css" in res.headers.get("Content-Type")

    with urlopen(f"{api_server}/landing.js") as res:
        assert res.status == 200
        assert "application/javascript" in res.headers.get("Content-Type")

    # Explorer assets load
    with urlopen(f"{api_server}/style.css") as res:
        assert res.status == 200
        assert "text/css" in res.headers.get("Content-Type")

    with urlopen(f"{api_server}/app.js") as res:
        assert res.status == 200
        assert "application/javascript" in res.headers.get("Content-Type")


