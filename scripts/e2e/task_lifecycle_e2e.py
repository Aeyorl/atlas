#!/usr/bin/env python3
"""End-to-end task lifecycle test — REAL node, REAL contracts, REAL agent execution.

Flow:
  1. Spawn local anvil node.
  2. Deploy Nive core contracts via DeployNive.s.sol.
  3. Register agent in AgentRegistry with required capability.
  4. Post bond in SettlementEngine.
  5. Create task on TaskManager with escrowed budget.
  6. Submit and accept bid.
  7. Execute task via TaskExecutor (sandbox + SHA-256 commitment + 128-bit limbs + ZK payload).
  8. Complete task on-chain with result & verification payload.
  9. Assert on-chain resultHash commitment (SHA-256 via precompile 0x02).
  10. Verify execution off-chain with ExecutionVerifier.
  11. Verify task on-chain as governor.
  12. Settle task (agent fee paid, fee split distributed, bond returned, reputation updated).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from runtime.executor import TaskExecutor
from runtime.relayer.chain import JsonRpcClient
from runtime.relayer.service import Signer
from runtime.verifier import ExecutionVerifier
from sdk.python.chain import (
    ChainClient,
    Contracts,
    capability_word,
    id_from_seed,
)

# Standard Anvil accounts
GOVERNOR_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"  # account 0
CREATOR_KEY  = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"  # account 1
AGENT_KEY    = "0x5de4111afa1a4b94908f83103eb294814b09e2b32b494630e8e5669b1a7b21ed"  # account 2


def spawn_anvil(port: int, chain_id: int) -> subprocess.Popen:
    exe = shutil.which("anvil")
    if exe is None:
        raise RuntimeError("anvil not found on PATH (install foundry)")
    return subprocess.Popen(
        [exe, "--port", str(port), "--chain-id", str(chain_id),
         "--block-time", "1", "--block-base-fee-per-gas", "1000000000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def wait_for_node(rpc_url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client = JsonRpcClient(rpc_url, timeout=2.0)
            client.chain_id()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError(f"anvil at {rpc_url} did not start in {timeout}s")


def deploy_stack(rpc_url: str) -> Contracts:
    env = os.environ | {
        "DEPLOYER_KEY": GOVERNOR_KEY,
        "NIVE_ECOSYSTEM": "robinhood-chain",
    }
    proc = subprocess.run(
        ["forge", "script", "scripts/deploy/DeployNive.s.sol",
         "--rpc-url", rpc_url, "--broadcast"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=REPO_ROOT, timeout=180, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"forge deploy failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")

    address_re = r"(AgentRegistry|SettlementEngine|TaskManager|NiveBridge|NiveCore):\s+(0x[0-9a-fA-F]{40})"
    found = dict(re.findall(address_re, proc.stdout))
    return Contracts(
        registry=found["AgentRegistry"],
        settlement=found["SettlementEngine"],
        task_manager=found["TaskManager"],
        bridge=found["NiveBridge"],
        core=found["NiveCore"],
    )


def run_test() -> None:
    port = 8555
    chain_id = 31337
    rpc_url = f"http://127.0.0.1:{port}"

    anvil = spawn_anvil(port, chain_id)
    try:
        print(f"1. Spawning Anvil node on port {port}...")
        wait_for_node(rpc_url)

        print("2. Deploying Nive smart contracts...")
        contracts = deploy_stack(rpc_url)
        print(f"   AgentRegistry:    {contracts.registry}")
        print(f"   TaskManager:      {contracts.task_manager}")
        print(f"   SettlementEngine: {contracts.settlement}")

        gov_client = ChainClient(rpc_url, contracts, signer=Signer(GOVERNOR_KEY))
        creator_client = ChainClient(rpc_url, contracts, signer=Signer(CREATOR_KEY))
        agent_client = ChainClient(rpc_url, contracts, signer=Signer(AGENT_KEY))

        # Fund test accounts on local node
        gov_client.client.call("anvil_setBalance", [creator_client.signer.address, hex(10**21)])
        gov_client.client.call("anvil_setBalance", [agent_client.signer.address, hex(10**21)])

        # Check initial protocol state
        assert gov_client.agent_count() == 0
        assert gov_client.task_count() == 0

        # 3. Register Agent
        agent_id = id_from_seed("agent-e2e-1")
        cap_word = capability_word("INFERENCE")
        print(f"3. Registering agent {agent_id[:10]}... with capability 'INFERENCE'...")
        agent_client.register_agent(
            agent_id=agent_id,
            uri="https://nive.agent/inference-v1.json",
            capabilities=[cap_word],
            min_fee_wei=10**17,  # 0.1 NIVE
        )
        assert gov_client.agent_count() == 1
        agent_rec = gov_client.get_agent(agent_id)
        assert agent_rec["active"] is True
        assert cap_word in agent_rec["capabilities"]

        # 4. Create Task
        task_id = id_from_seed("task-e2e-1")
        budget_wei = 10**18  # 1.0 NIVE
        print(f"4. Creating task {task_id[:10]}... with budget {budget_wei} wei...")
        creator_client.create_task(
            task_id=task_id,
            required_capabilities=[cap_word],
            budget_wei=budget_wei,
            parameters=b'{"prompt":"summarize","tokens":100}',
        )
        assert gov_client.task_count() == 1
        task_rec = gov_client.get_task(task_id)
        assert task_rec["status"] == "Bidding"
        assert gov_client.escrow(task_id) == budget_wei

        # 5. Agent Posts Bond
        bond_wei = 5 * 10**17  # 0.5 NIVE
        print(f"5. Posting agent bond ({bond_wei} wei)...")
        agent_client.post_bond(task_id, bond_wei)
        assert gov_client.get_bond(task_id, agent_client.signer.address) == bond_wei

        # 6. Submit Bid and Accept
        fee_wei = 8 * 10**17  # 0.8 NIVE
        print("6. Submitting and accepting bid...")
        agent_client.submit_bid(task_id, fee_wei)
        bids = gov_client.get_bids(task_id)
        assert len(bids) == 1
        assert bids[0]["fee_wei"] == fee_wei

        creator_client.accept_bid(task_id, agent_client.signer.address)
        task_rec = gov_client.get_task(task_id)
        assert task_rec["status"] == "Executing"

        # 7. Agent Sandboxed Execution
        print("7. Running agent task in TaskExecutor sandbox...")
        executor = TaskExecutor(sandbox_type="process")

        def inference_worker(payload: dict) -> dict:
            return {"status": "success", "result": f"processed:{payload.get('prompt')}"}

        executor.register_handler("INFERENCE", inference_worker)
        exec_result = executor.execute(
            task_id=task_id,
            agent_id=agent_id,
            ecosystem="robinhood-chain",
            payload={"prompt": "summarize", "tokens": 100},
            capability="INFERENCE",
        )
        assert exec_result.status == "completed"
        print(f"   Result hash (SHA-256): {exec_result.result_hash}")
        print(f"   Public inputs (4 limbs): {exec_result.public_inputs}")

        # 8. Complete Task on-chain
        print("8. Submitting task completion on-chain with proof...")
        result_bytes, verif_payload = executor.prepare_task_completion(task_id)
        agent_client.complete_task(task_id, result_bytes, verif_payload)

        task_rec = gov_client.get_task(task_id)
        assert task_rec["status"] == "Verifying"

        # 9. Verify on-chain SHA-256 commitment
        committed_hash = gov_client.result_hash(task_id)
        assert committed_hash.lower() == exec_result.result_hash.lower()
        print(f"   On-chain commitment verified: {committed_hash}")

        # 10. Verify off-chain via ExecutionVerifier
        print("10. Validating proof & canonical limb bindings off-chain...")
        verifier = ExecutionVerifier()
        report = verifier.verify_payload(
            task_id=task_id,
            verification_payload=verif_payload,
            expected_result_hash=committed_hash,
            agent_id=agent_id,
        )
        assert report.proof_valid is True
        assert report.limb_binding_valid is True

        # 11. Governor Verifies Task on-chain
        print("11. Verifying task on-chain as governor...")
        gov_client.verify_task(task_id, valid=True)

        # 12. Advance Anvil time past dispute window (3 days = 259,200s)
        print("12. Fast-forwarding time past 3-day dispute window...")
        rpc_client = JsonRpcClient(rpc_url)
        rpc_client.call("evm_increaseTime", [259201])
        rpc_client.call("evm_mine", [])

        # 13. Settle Task
        print("13. Settling task...")
        agent_bal_before = int(rpc_client.call("eth_getBalance", [agent_client.signer.address, "latest"]), 16)
        gov_client.settle_task(task_id)

        task_rec = gov_client.get_task(task_id)
        assert task_rec["status"] == "Completed"

        settlement = gov_client.settlement(task_id)
        assert settlement["settled"] is True
        print(f"   Agent fee:     {settlement['agent_fee_wei']} wei")
        print(f"   Protocol fee:  {settlement['protocol_fee_wei']} wei")
        print(f"   Guardian fee:  {settlement['guardian_fee_wei']} wei")

        # Confirm agent received fee + returned bond
        agent_bal_after = int(rpc_client.call("eth_getBalance", [agent_client.signer.address, "latest"]), 16)
        expected_gain = int(settlement["agent_fee_wei"]) + bond_wei
        assert agent_bal_after - agent_bal_before == expected_gain

        # Confirm agent reputation incremented
        agent_updated = gov_client.get_agent(agent_id)
        assert agent_updated["total_tasks"] == 1
        assert agent_updated["successful_tasks"] == 1

        print("\n✅ All 13 on-chain end-to-end task lifecycle checks passed!")

    finally:
        anvil.terminate()
        anvil.wait()


if __name__ == "__main__":
    run_test()
