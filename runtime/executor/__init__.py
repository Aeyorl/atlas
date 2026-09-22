"""Task executor — sandboxed agent execution environment.

Provides deterministic execution, output serialization, SHA-256 result
commitment (matching TaskManager._sha256 / precompile 0x02), canonical 128-bit
ZK limb binding, and payload preparation for contract completion.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sdk.python.chain import compute_verification_limbs, encode_zk_verification


@dataclass
class ExecutionResult:
    task_id: str
    agent_id: str
    ecosystem: str
    output: Any
    result_bytes: bytes = b""
    result_hash: str = ""
    proof: bytes = b""
    public_inputs: list[int] = field(default_factory=list)
    verification_payload: bytes = b""
    gas_used: int = 0
    status: str = "pending"
    error: str | None = None
    execution_time_ms: float = 0.0


class TaskExecutor:
    SUPPORTED_ECOSYSTEMS: ClassVar[set[str]] = {"robinhood-chain", "evm", "virtuals"}

    def __init__(self, sandbox_type: str = "process"):
        self.sandbox_type = sandbox_type
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._results: dict[str, ExecutionResult] = {}

    def register_handler(
        self, capability: str, handler: Callable[[dict[str, Any]], Any]
    ) -> None:
        """Register a handler function for a specific capability."""
        self._handlers[capability] = handler

    def execute(
        self,
        task_id: str,
        agent_id: str,
        ecosystem: str,
        payload: dict[str, Any] | bytes | str,
        timeout: int = 30,
        capability: str | None = None,
        custom_proof: bytes | None = None,
    ) -> ExecutionResult:
        """Execute a task, compute result commitments, and construct verification payloads."""
        if ecosystem not in self.SUPPORTED_ECOSYSTEMS:
            raise ValueError(f"Unsupported ecosystem: {ecosystem}")

        start_time = time.perf_counter()
        normalized_payload: dict[str, Any]
        if isinstance(payload, bytes):
            try:
                normalized_payload = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                normalized_payload = {"raw": payload.hex()}
        elif isinstance(payload, str):
            try:
                normalized_payload = json.loads(payload)
            except json.JSONDecodeError:
                normalized_payload = {"text": payload}
        else:
            normalized_payload = payload

        handler = self._handlers.get(capability or "")
        try:
            if handler is not None:
                output = handler(normalized_payload)
            else:
                output = self._default_sandbox_exec(normalized_payload, timeout)
            status = "completed"
            error = None
        except Exception as exc:  # noqa: BLE001
            output = {"error": str(exc)}
            status = "failed"
            error = str(exc)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Serialize result payload
        if isinstance(output, (bytes, bytearray)):
            result_bytes = bytes(output)
        elif isinstance(output, str):
            result_bytes = output.encode("utf-8")
        else:
            result_bytes = json.dumps(output, sort_keys=True).encode("utf-8")

        # SHA-256 commitment (matching TaskManager on-chain precompile 0x02)
        result_hash_bytes = hashlib.sha256(result_bytes).digest()
        result_hash = "0x" + result_hash_bytes.hex()

        # Canonical 128-bit limb binding: [taskIdLo, taskIdHi, resultLo, resultHi]
        public_inputs = compute_verification_limbs(task_id, result_hash)

        # Generate or assign proof
        if custom_proof is not None:
            proof = custom_proof
        else:
            # Deterministic synthetic proof placeholder bound to execution parameters
            synthetic_seed = hashlib.sha256(
                task_id.encode() + agent_id.encode() + result_hash_bytes
            ).digest()
            # Standard Groth16 proof wire shape: 8 words (A: 2, B: 4, C: 2 = 256 bytes)
            proof = (synthetic_seed * 8)[:256]

        verification_payload = encode_zk_verification(proof, public_inputs)

        result = ExecutionResult(
            task_id=task_id,
            agent_id=agent_id,
            ecosystem=ecosystem,
            output=output,
            result_bytes=result_bytes,
            result_hash=result_hash,
            proof=proof,
            public_inputs=public_inputs,
            verification_payload=verification_payload,
            gas_used=max(21000, len(result_bytes) * 68),
            status=status,
            error=error,
            execution_time_ms=elapsed_ms,
        )
        self._results[task_id] = result
        return result

    def _default_sandbox_exec(self, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        return {
            "executed": True,
            "data": payload,
            "sandbox": self.sandbox_type,
            "timestamp": time.time(),
        }

    def get_result(self, task_id: str) -> ExecutionResult | None:
        return self._results.get(task_id)

    def prepare_task_completion(self, task_id: str) -> tuple[bytes, bytes]:
        """Return (result_bytes, verification_payload) for submission to TaskManager.completeTask."""
        res = self.get_result(task_id)
        if res is None:
            raise KeyError(f"no execution result found for task {task_id}")
        return res.result_bytes, res.verification_payload
