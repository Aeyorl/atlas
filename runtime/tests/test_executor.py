"""Tests for runtime TaskExecutor."""
from __future__ import annotations

import hashlib
import json

import pytest

from runtime.executor import ExecutionResult, TaskExecutor
from sdk.python.chain import id_from_seed


def test_executor_rejects_unsupported_ecosystem():
    executor = TaskExecutor()
    with pytest.raises(ValueError, match="Unsupported ecosystem"):
        executor.execute(
            task_id="0x" + "11" * 32,
            agent_id="0x" + "22" * 20,
            ecosystem="solana",
            payload={"action": "test"},
        )


def test_executor_default_sandbox_execution():
    executor = TaskExecutor()
    task_id = id_from_seed("task-executor-1")
    agent_id = "0x" + "22" * 20
    payload = {"data": [1, 2, 3], "target": "ETH/USD"}

    result = executor.execute(
        task_id=task_id,
        agent_id=agent_id,
        ecosystem="robinhood-chain",
        payload=payload,
    )

    assert isinstance(result, ExecutionResult)
    assert result.status == "completed"
    assert result.task_id == task_id
    assert result.agent_id == agent_id
    assert result.ecosystem == "robinhood-chain"
    assert result.output["executed"] is True
    assert result.output["data"] == payload

    # Result bytes matches output json
    expected_bytes = json.dumps(result.output, sort_keys=True).encode("utf-8")
    assert result.result_bytes == expected_bytes

    # SHA-256 result hash matches
    expected_hash = "0x" + hashlib.sha256(expected_bytes).hexdigest()
    assert result.result_hash == expected_hash

    # Public inputs limbs match canonical 128-bit binding
    assert len(result.public_inputs) == 4
    task_int = int(task_id, 16)
    rec_task = (result.public_inputs[1] << 128) | result.public_inputs[0]
    assert rec_task == task_int

    res_int = int(expected_hash, 16)
    rec_res = (result.public_inputs[3] << 128) | result.public_inputs[2]
    assert rec_res == res_int

    # Proof is generated (256 bytes Groth16 wire shape)
    assert len(result.proof) == 256
    assert len(result.verification_payload) > 0


def test_executor_custom_handler_registration():
    executor = TaskExecutor()
    task_id = id_from_seed("task-custom-handler")

    def math_handler(payload: dict) -> dict:
        x = payload["x"]
        y = payload["y"]
        return {"sum": x + y, "product": x * y}

    executor.register_handler("MATH", math_handler)

    result = executor.execute(
        task_id=task_id,
        agent_id="0x" + "33" * 20,
        ecosystem="evm",
        payload={"x": 10, "y": 25},
        capability="MATH",
    )

    assert result.status == "completed"
    assert result.output == {"sum": 35, "product": 250}

    # prepare_task_completion returns ready-to-submit tuple
    res_bytes, verif_payload = executor.prepare_task_completion(task_id)
    assert res_bytes == result.result_bytes
    assert verif_payload == result.verification_payload


def test_executor_handler_failure_captured():
    executor = TaskExecutor()
    task_id = id_from_seed("task-failing-handler")

    def failing_handler(payload: dict):
        raise RuntimeError("simulated computation error")

    executor.register_handler("FAIL", failing_handler)

    result = executor.execute(
        task_id=task_id,
        agent_id="0x" + "44" * 20,
        ecosystem="virtuals",
        payload={},
        capability="FAIL",
    )

    assert result.status == "failed"
    assert "simulated computation error" in result.error
    assert result.output == {"error": "simulated computation error"}
