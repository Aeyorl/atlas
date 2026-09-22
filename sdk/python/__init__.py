"""Nive Python SDK — Agent Coordination Layer client library."""
__version__ = "0.1.4"
from .agent import Agent
from .chain import (
    ECOSYSTEMS,
    TASK_STATUSES,
    ChainClient,
    Contracts,
    capability_word,
    compute_verification_limbs,
    encode_zk_verification,
    id_from_seed,
    split_bytes32_to_limbs,
)
from .client import NiveClient
from .task import Task, TaskStatus

__all__ = [
    "ECOSYSTEMS",
    "TASK_STATUSES",
    "Agent",
    "ChainClient",
    "Contracts",
    "NiveClient",
    "Task",
    "TaskStatus",
    "capability_word",
    "compute_verification_limbs",
    "encode_zk_verification",
    "id_from_seed",
    "split_bytes32_to_limbs",
]
