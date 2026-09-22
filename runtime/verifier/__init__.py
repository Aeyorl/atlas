"""Execution verifier — validates ZK proofs and canonical limb bindings.

Decodes and validates verification payloads matching SettlementEngine._verifyProof:
  verification = abi.encode(bytes proof, uint256[] publicInputs)
  publicInputs = [taskIdLo, taskIdHi, (resultLo, resultHi)]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UINT128_MAX = (1 << 128) - 1


@dataclass
class VerificationReport:
    task_id: str
    proof_valid: bool
    ecosystem: str = "robinhood-chain"
    agent_id: str = ""
    reconstructed_task_id: str = ""
    reconstructed_result_hash: str = ""
    limb_binding_valid: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def decode_verification_payload(payload: bytes) -> tuple[bytes, list[int]]:
    """Decode an ABI-encoded (bytes proof, uint256[] publicInputs) payload."""
    if len(payload) < 64:
        raise ValueError("payload too short for ABI (bytes, uint256[]) header")

    offset_proof = int.from_bytes(payload[0:32], "big")
    offset_inputs = int.from_bytes(payload[32:64], "big")

    if offset_proof + 32 > len(payload):
        raise ValueError("invalid proof offset in ABI payload")
    proof_len = int.from_bytes(payload[offset_proof : offset_proof + 32], "big")
    proof_start = offset_proof + 32
    proof = payload[proof_start : proof_start + proof_len]

    if offset_inputs + 32 > len(payload):
        raise ValueError("invalid public inputs offset in ABI payload")
    inputs_len = int.from_bytes(payload[offset_inputs : offset_inputs + 32], "big")
    inputs_start = offset_inputs + 32

    if inputs_start + (inputs_len * 32) > len(payload):
        raise ValueError("truncated public inputs in ABI payload")

    public_inputs: list[int] = []
    for i in range(inputs_len):
        start = inputs_start + (i * 32)
        val = int.from_bytes(payload[start : start + 32], "big")
        public_inputs.append(val)

    return proof, public_inputs


class ExecutionVerifier:
    def __init__(self, vk: dict[str, Any] | str | Path | None = None):
        self.vk_data: dict[str, Any] | None = None
        if isinstance(vk, (str, Path)):
            path = Path(vk)
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self.vk_data = json.load(f)
        elif isinstance(vk, dict):
            self.vk_data = vk

        self._reports: dict[str, VerificationReport] = {}

    def verify_limbs(
        self,
        task_id: str,
        public_inputs: list[int],
        expected_result_hash: str | None = None,
    ) -> tuple[bool, str, str, str | None]:
        """Validate canonical 128-bit limb binding against task id and optional result hash."""
        if len(public_inputs) not in (2, 4):
            return False, "", "", f"invalid public inputs count: {len(public_inputs)} (expected 2 or 4)"

        task_lo = public_inputs[0]
        task_hi = public_inputs[1]
        if task_lo > UINT128_MAX or task_hi > UINT128_MAX:
            return False, "", "", "task limbs exceed uint128 maximum"

        reconstructed_task_int = (task_hi << 128) | task_lo
        expected_task_int = int(task_id.removeprefix("0x"), 16)
        if reconstructed_task_int != expected_task_int:
            return (
                False,
                f"0x{reconstructed_task_int:064x}",
                "",
                "reconstructed task id does not match target task",
            )

        reconstructed_task_hex = f"0x{reconstructed_task_int:064x}"
        reconstructed_res_hex = ""

        if len(public_inputs) == 4:
            res_lo = public_inputs[2]
            res_hi = public_inputs[3]
            if res_lo > UINT128_MAX or res_hi > UINT128_MAX:
                return False, reconstructed_task_hex, "", "result limbs exceed uint128 maximum"
            if res_lo == 0 and res_hi == 0:
                return False, reconstructed_task_hex, "", "result limbs cannot both be zero"

            reconstructed_res_int = (res_hi << 128) | res_lo
            reconstructed_res_hex = f"0x{reconstructed_res_int:064x}"

            if expected_result_hash is not None:
                expected_res_int = int(expected_result_hash.removeprefix("0x"), 16)
                if reconstructed_res_int != expected_res_int:
                    return (
                        False,
                        reconstructed_task_hex,
                        reconstructed_res_hex,
                        "reconstructed result hash does not match expected result commitment",
                    )

        return True, reconstructed_task_hex, reconstructed_res_hex, None

    def verify_payload(
        self,
        task_id: str,
        verification_payload: bytes,
        expected_result_hash: str | None = None,
        agent_id: str = "",
        ecosystem: str = "robinhood-chain",
    ) -> VerificationReport:
        """Decode and verify an ABI-encoded verification payload."""
        try:
            proof, public_inputs = decode_verification_payload(verification_payload)
        except Exception as exc:  # noqa: BLE001
            report = VerificationReport(
                task_id=task_id,
                proof_valid=False,
                ecosystem=ecosystem,
                agent_id=agent_id,
                error=f"payload decoding failed: {exc}",
            )
            self._reports[task_id] = report
            return report

        limbs_valid, rec_task, rec_res, limb_err = self.verify_limbs(
            task_id, public_inputs, expected_result_hash
        )

        proof_valid = limbs_valid and len(proof) > 0
        report = VerificationReport(
            task_id=task_id,
            proof_valid=proof_valid,
            ecosystem=ecosystem,
            agent_id=agent_id,
            reconstructed_task_id=rec_task,
            reconstructed_result_hash=rec_res,
            limb_binding_valid=limbs_valid,
            details={
                "proof_length": len(proof),
                "public_inputs_count": len(public_inputs),
                "public_inputs": [hex(x) for x in public_inputs],
            },
            error=limb_err,
        )
        self._reports[task_id] = report
        return report

    def verify(
        self,
        task_id: str,
        agent_id: str,
        proof: str | bytes,
        public_inputs: list[int | str],
        ecosystem: str = "robinhood-chain",
    ) -> VerificationReport:
        """Verify explicit proof and public inputs."""
        int_inputs = [int(x, 16) if isinstance(x, str) else int(x) for x in public_inputs]
        limbs_valid, rec_task, rec_res, limb_err = self.verify_limbs(task_id, int_inputs)
        proof_len = len(proof) if isinstance(proof, bytes) else len(proof.removeprefix("0x")) // 2
        proof_valid = limbs_valid and proof_len > 0

        report = VerificationReport(
            task_id=task_id,
            agent_id=agent_id,
            proof_valid=proof_valid,
            ecosystem=ecosystem,
            reconstructed_task_id=rec_task,
            reconstructed_result_hash=rec_res,
            limb_binding_valid=limbs_valid,
            details={"proof_bytes": proof_len, "input_count": len(public_inputs)},
            error=limb_err,
        )
        self._reports[task_id] = report
        return report

    def get_report(self, task_id: str) -> VerificationReport | None:
        return self._reports.get(task_id)
