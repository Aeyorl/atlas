"""NiveClient — High-level client for the Nive Protocol."""
import uuid
from typing import ClassVar


class NiveClient:
    SUPPORTED_ECOSYSTEMS: ClassVar[set[str]] = {"robinhood-chain", "evm", "virtuals"}
    def __init__(self, private_key: str | None = None, ecosystem: str = "robinhood-chain", rpc_url: str | None = None):
        if ecosystem not in self.SUPPORTED_ECOSYSTEMS:
            raise ValueError(f"Unsupported ecosystem: {ecosystem}")
        self.ecosystem = ecosystem
        self._private_key = private_key
        self._rpc_url = rpc_url or {"robinhood-chain": "https://rpc.mainnet.chain.robinhood.com", "evm": "https://eth.llamarpc.com", "virtuals": "https://rpc.virtuals.io"}.get(ecosystem)

    def create_task(self, required_capabilities: list[str], budget: float, parameters: dict, deadline: int | None = None):
        from .task import Task, TaskStatus
        task = Task(
            task_id=f"task-{uuid.uuid4().hex[:16]}",
            required_capabilities=required_capabilities,
            budget=budget,
            parameters=parameters,
            ecosystem=self.ecosystem,
            deadline=deadline,
        )
        task.status = TaskStatus.CREATED
        return task

    def get_ecosystem(self) -> str:
        return self.ecosystem
