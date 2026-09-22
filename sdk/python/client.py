from __future__ import annotations

import uuid
from typing import ClassVar

from .chain import ChainClient, Contracts
from .task import Task, TaskStatus


class NiveClient:
    SUPPORTED_ECOSYSTEMS: ClassVar[set[str]] = {"robinhood-chain", "evm", "virtuals"}

    def __init__(
        self,
        private_key: str | None = None,
        ecosystem: str = "robinhood-chain",
        rpc_url: str | None = None,
        contracts: Contracts | dict[str, str] | None = None,
        chain: ChainClient | None = None,
    ):
        if ecosystem not in self.SUPPORTED_ECOSYSTEMS:
            raise ValueError(f"Unsupported ecosystem: {ecosystem}")
        self.ecosystem = ecosystem
        self._private_key = private_key
        self._rpc_url = rpc_url or {
            "robinhood-chain": "https://rpc.mainnet.chain.robinhood.com",
            "evm": "https://eth.llamarpc.com",
            "virtuals": "https://rpc.virtuals.io",
        }.get(ecosystem)

        if chain is not None:
            self.chain: ChainClient | None = chain
        elif contracts is not None:
            c = contracts if isinstance(contracts, Contracts) else Contracts.from_mapping(contracts)
            from runtime.relayer.service import Signer
            signer = Signer(private_key) if private_key else None
            assert self._rpc_url is not None
            self.chain = ChainClient(self._rpc_url, c, signer=signer)
        else:
            self.chain = None

    def create_task(
        self,
        required_capabilities: list[str],
        budget: float,
        parameters: dict,
        deadline: int | None = None,
    ) -> Task:
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
