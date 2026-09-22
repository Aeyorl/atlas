"""Task model for Nive Protocol SDK."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"; CREATED = "created"; BIDDING = "bidding"
    EXECUTING = "executing"; VERIFYING = "verifying"; COMPLETED = "completed"
    FAILED = "failed"; DISPUTED = "disputed"

@dataclass
class Task:
    task_id: str; required_capabilities: list[str]; budget: float
    parameters: dict; ecosystem: str; status: TaskStatus = TaskStatus.PENDING
    assigned_agent: str | None = None; created_at: str | None = None
    deadline: int | None = None; result: dict | None = None

    def assign(self, agent_id: str) -> None:
        self.assigned_agent = agent_id; self.status = TaskStatus.EXECUTING

    def complete(self, result: dict) -> None:
        self.result = result; self.status = TaskStatus.COMPLETED

    def fail(self, reason: str) -> None:
        self.status = TaskStatus.FAILED; self.result = {"error": reason}

    @property
    def is_completed(self) -> bool: return self.status == TaskStatus.COMPLETED
