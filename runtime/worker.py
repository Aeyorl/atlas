"""Autonomous Agent Worker Daemon for Nive Protocol.

Continuously discovers open tasks on-chain (Robinhood Chain Mainnet / EVM),
evaluates capability compatibility, calculates optimal bids, submits bids,
monitors assignment, executes jobs inside the TaskExecutor sandbox, and
submits task completion on-chain with cryptographic commitments.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from runtime.executor import TaskExecutor
from sdk.python.chain import (
    ChainClient,
    capability_word,
)

logger = logging.getLogger("nive.worker")


class AgentWorker:
    """Autonomous agent daemon for continuous task execution and settlement."""

    def __init__(
        self,
        client: ChainClient,
        executor: TaskExecutor,
        agent_id: str,
        capabilities: list[str],
        min_fee_wei: int = 10**17,  # 0.1 ETH default
        ecosystem: str = "robinhood-chain",
        bid_ratio: float = 0.8,
        auto_bond: bool = True,
        bond_wei: int | None = None,
    ) -> None:
        if client.signer is None:
            raise ValueError("AgentWorker requires a ChainClient configured with a signer private key")

        self.client = client
        self.executor = executor
        self.agent_id = agent_id
        self.capabilities = [c.upper() for c in capabilities]
        self.capability_words = [capability_word(c) for c in self.capabilities]
        self.min_fee_wei = min_fee_wei
        self.ecosystem = ecosystem
        self.bid_ratio = bid_ratio
        self.auto_bond = auto_bond
        self.bond_wei = bond_wei if bond_wei is not None else (min_fee_wei // 2)

        self.processed_tasks: set[str] = set()
        self.bid_tasks: set[str] = set()

    @property
    def address(self) -> str:
        return self.client.signer.address  # type: ignore[union-attr]

    def is_capable(self, required_capabilities: list[str]) -> bool:
        """Check if all required capability words are supported by this agent."""
        if not required_capabilities:
            return True
        for req in required_capabilities:
            req_clean = req.lower()
            if not any(req_clean == cap_word.lower() for cap_word in self.capability_words):
                return False
        return True

    def evaluate_and_bid(self, task_id: str) -> bool:
        """Inspect task, verify capability & budget fit, post bond, and submit bid."""
        try:
            task = self.client.get_task(task_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to fetch task %s: %s", task_id, exc)
            return False

        status = task.get("status")
        if status not in ("Bidding", "Open"):
            return False

        if task_id in self.bid_tasks:
            return False

        # Capability check
        required_caps = task.get("required_capabilities", [])  # type: ignore[assignment]
        if not self.is_capable(required_caps):
            logger.info("Task %s: capabilities %s not matched by agent %s", task_id, required_caps, self.capabilities)
            return False

        budget = int(task.get("budget_wei", 0))  # type: ignore[arg-type]
        if budget < self.min_fee_wei:
            logger.info("Task %s: budget %s wei below agent min fee %s wei", task_id, budget, self.min_fee_wei)
            return False

        # Calculate optimal competitive bid
        optimal_fee = max(self.min_fee_wei, int(budget * self.bid_ratio))
        optimal_fee = min(optimal_fee, budget)

        # Check existing bids
        try:
            existing_bids = self.client.get_bids(task_id)
            for b in existing_bids:
                if str(b.get("bidder", "")).lower() == self.address.lower():
                    self.bid_tasks.add(task_id)
                    return False
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not inspect existing bids for %s: %s", task_id, exc)

        # Post bond if required
        if self.auto_bond and self.bond_wei > 0:
            try:
                current_bond = self.client.get_bond(task_id, self.address)
                if current_bond < self.bond_wei:
                    needed = self.bond_wei - current_bond
                    logger.info("Posting bond of %s wei for task %s...", needed, task_id)
                    self.client.post_bond(task_id, needed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Bond posting failed for task %s: %s", task_id, exc)

        logger.info("Submitting bid of %s wei for task %s...", optimal_fee, task_id)
        try:
            self.client.submit_bid(task_id, optimal_fee)
            self.bid_tasks.add(task_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to submit bid for task %s: %s", task_id, exc)
            return False

    def evaluate_and_execute(self, task_id: str) -> bool:
        """If assigned to this agent and executing, run in sandbox and complete on-chain."""
        if task_id in self.processed_tasks:
            return False

        try:
            task = self.client.get_task(task_id)
        except Exception:  # noqa: BLE001
            return False

        status = task.get("status")
        assigned = str(task.get("assigned_agent", "")).lower()

        if status != "Executing" or assigned != self.address.lower():
            return False

        logger.info("Task %s is assigned to this agent! Executing in sandbox...", task_id)

        # Parse task payload
        raw_params = task.get("parameters", "0x")
        payload: dict[str, Any] = {}
        if isinstance(raw_params, str) and raw_params.startswith("0x") and len(raw_params) > 2:
            try:
                param_bytes = bytes.fromhex(raw_params[2:])
                payload = json.loads(param_bytes.decode("utf-8"))
            except Exception:  # noqa: BLE001
                payload = {"raw": raw_params}
        elif isinstance(raw_params, bytes):
            try:
                payload = json.loads(raw_params.decode("utf-8"))
            except Exception:  # noqa: BLE001
                payload = {"raw": raw_params.hex()}

        # Primary capability
        primary_cap = self.capabilities[0] if self.capabilities else "INFERENCE"

        # Execute sandboxed job
        exec_result = self.executor.execute(
            task_id=task_id,
            agent_id=self.agent_id,
            ecosystem=self.ecosystem,
            payload=payload,
            capability=primary_cap,
        )

        if exec_result.status != "completed":
            logger.error("Task %s execution failed: %s", task_id, exec_result.error)
            return False

        # Prepare completion payload & on-chain proof calldata
        result_bytes, verif_calldata = self.executor.prepare_task_completion(task_id)

        logger.info("Submitting task %s completion on-chain (result_hash=%s)...", task_id, exec_result.result_hash)
        try:
            self.client.complete_task(task_id, result_bytes, verif_calldata)
            self.processed_tasks.add(task_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to complete task %s on-chain: %s", task_id, exc)
            return False

    def poll_once(self, candidate_task_ids: list[str]) -> dict[str, int]:
        """Perform a single discovery, bid, and execution cycle over candidate tasks."""
        bids_submitted = 0
        tasks_completed = 0

        for task_id in candidate_task_ids:
            if self.evaluate_and_bid(task_id):
                bids_submitted += 1
            if self.evaluate_and_execute(task_id):
                tasks_completed += 1

        return {
            "bids_submitted": bids_submitted,
            "tasks_completed": tasks_completed,
        }

    def run(self, candidate_task_ids: list[str], poll_interval: float = 2.0, max_iterations: int | None = None) -> None:
        """Run continuous worker polling loop."""
        iterations = 0
        logger.info("AgentWorker online: agent=%s address=%s capabilities=%s", self.agent_id, self.address, self.capabilities)

        while max_iterations is None or iterations < max_iterations:
            try:
                report = self.poll_once(candidate_task_ids)
                if report["bids_submitted"] > 0 or report["tasks_completed"] > 0:
                    logger.info("Worker cycle: %s", report)
            except Exception as exc:  # noqa: BLE001
                logger.error("Error during worker cycle: %s", exc)

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(poll_interval)
