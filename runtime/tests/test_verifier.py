"""Tests for runtime ExecutionVerifier."""
from __future__ import annotations

import pytest

from runtime.executor import TaskExecutor
from runtime.verifier import (
    ExecutionVerifier,
    decode_verification_payload,
)
from sdk.python.chain import (
    compute_verification_limbs,
    encode_zk_verification,
    id_from_seed,
)


def test_decode_verification_payload_roundtrip():
    proof = b"\xaa\xbb\xcc\xdd" * 8
    public_inputs = [12345, 67890, 111, 222]
    encoded = encode_zk_verification(proof, public_inputs)

    dec_proof, dec_inputs = decode_verification_payload(encoded)
    assert dec_proof == proof
    assert dec_inputs == public_inputs


def test_decode_verification_payload_malformed_rejects():
    with pytest.raises(ValueError, match="payload too short"):
        decode_verification_payload(b"\x00" * 32)


def test_verifier_accepts_valid_payload_from_executor():
    executor = TaskExecutor()
    task_id = id_from_seed("task-verif-valid")
    agent_id = "0x" + "aa" * 20

    exec_result = executor.execute(
        task_id=task_id,
        agent_id=agent_id,
        ecosystem="robinhood-chain",
        payload={"query": "alpha"},
    )

    verifier = ExecutionVerifier()
    report = verifier.verify_payload(
        task_id=task_id,
        verification_payload=exec_result.verification_payload,
        expected_result_hash=exec_result.result_hash,
        agent_id=agent_id,
    )

    assert report.proof_valid is True
    assert report.limb_binding_valid is True
    assert report.reconstructed_task_id.lower() == task_id.lower()
    assert report.reconstructed_result_hash.lower() == exec_result.result_hash.lower()
    assert report.error is None


def test_verifier_rejects_tampered_task_id():
    task_id = id_from_seed("task-original")
    other_task_id = id_from_seed("task-other")
    res_hash = id_from_seed("res-1")

    # Generate limbs for other_task_id
    limbs = compute_verification_limbs(other_task_id, res_hash)
    payload = encode_zk_verification(b"\x12" * 32, limbs)

    verifier = ExecutionVerifier()
    report = verifier.verify_payload(
        task_id=task_id,
        verification_payload=payload,
        expected_result_hash=res_hash,
    )

    assert report.proof_valid is False
    assert report.limb_binding_valid is False
    assert "does not match target task" in report.error


def test_verifier_rejects_tampered_result_hash():
    task_id = id_from_seed("task-result-tamper")
    res_hash_correct = id_from_seed("res-correct")
    res_hash_wrong = id_from_seed("res-wrong")

    limbs = compute_verification_limbs(task_id, res_hash_wrong)
    payload = encode_zk_verification(b"\x12" * 32, limbs)

    verifier = ExecutionVerifier()
    report = verifier.verify_payload(
        task_id=task_id,
        verification_payload=payload,
        expected_result_hash=res_hash_correct,
    )

    assert report.proof_valid is False
    assert report.limb_binding_valid is False
    assert "does not match expected result commitment" in report.error


def test_verifier_rejects_limbs_exceeding_uint128():
    verifier = ExecutionVerifier()
    task_id = id_from_seed("task-overflow")
    overflow_limb = (1 << 128) + 5
    limbs = [overflow_limb, 10]

    valid, _, _, err = verifier.verify_limbs(task_id, limbs)
    assert valid is False
    assert "exceed uint128 maximum" in err
