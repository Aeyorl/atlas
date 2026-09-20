#!/usr/bin/env python3
"""End-to-end relay smoke test — REAL nodes, REAL deployments, REAL relay.

Spawns two local anvil chains, deploys the full Nive stack on each via the
production deploy script (DeployNive.s.sol), then drives a cross-ecosystem
message through the actual NiveRelayer service:

  chain A (evm)  --sendMessage-->  relayer observes/attests/delivers  -->  chain B (virtuals)

Assertions (all against chain state, not mocks):
  1. The relayer reaches DELIVERING state with a recorded delivery tx.
  2. validAttestations(messageId) == 2 on the target bridge (relayer + governor).
  3. The target inbox record is delivered with the exact payload/sender/source.
  4. The relayer recovered source_nonce == 0 (canonical id derivation works).
  5. deliveredCount on the target bridge incremented to 1.

Requires: anvil + forge on PATH. Run from the repo root:
  python scripts/e2e/relay_e2e.py
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

from runtime.relayer.chain import (
    TOPIC_MESSAGE_DELIVERED,
    JsonRpcClient,
    decode_get_message,
    keccak256,
    parse_message_sent_logs,
)
from runtime.relayer.config import (
    ECOSYSTEM_EVM,
    ECOSYSTEM_VIRTUALS,
    ChainConfig,
    RelayerConfig,
)
from runtime.relayer.service import (
    SELECTOR_VERIFY_MESSAGE,
    NiveRelayer,
    Signer,
)

# ────────────────────────────────
#  Topology
# ────────────────────────────────

PORT_A, PORT_B = 18545, 18546
CHAIN_A, CHAIN_B = 31337, 31338
RPC_A = f"http://127.0.0.1:{PORT_A}"
RPC_B = f"http://127.0.0.1:{PORT_B}"

# Anvil's deterministic account #0 = deployer/governor on both chains.
# The relayer key (account #1) also acts as the second guardian on chain B.
GOVERNOR_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
RELAYER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

DEADLINE_SECONDS = 90.0

# Windows consoles default to cp1252; force UTF-8 so unicode output never
# kills the run mid-flight.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(step: str, detail: str = "") -> None:
    print(f"[e2e] {step}" + (f" — {detail}" if detail else ""), flush=True)


def word32(hex_or_int: str | int) -> bytes:
    if isinstance(hex_or_int, int):
        return hex_or_int.to_bytes(32, "big")
    return bytes.fromhex(hex_or_int.removeprefix("0x")).rjust(32, b"\x00")


# ────────────────────────────────
#  Node management
# ────────────────────────────────


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
        except Exception:  # noqa: BLE001 — node not up yet
            time.sleep(0.3)
    raise RuntimeError(f"anvil at {rpc_url} did not come up in {timeout}s")


# ────────────────────────────────
#  Deployment via the production script
# ────────────────────────────────

ADDRESS_RE = r"(AgentRegistry|SettlementEngine|TaskManager|NiveBridge|NiveCore):\s+(0x[0-9a-fA-F]{40})"


def deploy_stack(rpc_url: str, ecosystem: str) -> dict[str, str]:
    env = os.environ | {
        "DEPLOYER_KEY": GOVERNOR_KEY,
        "NIVE_ECOSYSTEM": ecosystem,
    }
    proc = subprocess.run(
        ["forge", "script", "scripts/deploy/DeployNive.s.sol",
         "--rpc-url", rpc_url, "--broadcast"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=REPO_ROOT, timeout=180, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"forge deploy failed for {ecosystem}:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    found = dict(re.findall(ADDRESS_RE, proc.stdout))
    missing = {n for n in ("AgentRegistry", "SettlementEngine", "TaskManager",
                           "NiveBridge", "NiveCore")} - set(found)
    if missing:
        raise RuntimeError(f"deploy output missing {missing}:\n{proc.stdout[-2000:]}")
    return found


# ────────────────────────────────
#  Tx helpers
# ────────────────────────────────


def send_and_wait(client: JsonRpcClient, signer: Signer, to: str, data: bytes,
                  value: int = 0, gas: int = 300_000) -> str:
    nonce_hex = client.call("eth_getTransactionCount", [signer.address, "pending"])
    raw = signer.sign_tx(
        chain_id=client.chain_id(), nonce=int(nonce_hex, 16),
        to=to, data=data, value=value, gas=gas,
    )
    tx_hash = client.send_raw_transaction("0x" + raw.hex())
    deadline = time.time() + 30
    while time.time() < deadline:
        receipt = client.call("eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            if receipt.get("status") != "0x1":
                raise RuntimeError(f"tx reverted: {tx_hash}")
            return tx_hash
        time.sleep(0.2)
    raise RuntimeError(f"tx not mined in time: {tx_hash}")


def calldata_register_guardian(stake_wei: int) -> bytes:
    sel = keccak256(b"registerGuardian(uint256)")[:4]
    return sel + word32(stake_wei)


def calldata_send_message(target_ecosystem: str, payload: bytes) -> bytes:
    sel = keccak256(b"sendMessage(bytes32,bytes)")[:4]
    padded = payload + b"\x00" * ((32 - len(payload) % 32) % 32)
    return (sel + word32(target_ecosystem)
            + (0x40).to_bytes(32, "big")
            + len(payload).to_bytes(32, "big")
            + padded)


def calldata_verify_message(message_id: str, valid: bool) -> bytes:
    return (bytes.fromhex(SELECTOR_VERIFY_MESSAGE)
            + word32(message_id)
            + word32(1 if valid else 0))


def selector_of(signature: str) -> str:
    return "0x" + keccak256(signature.encode()).hex()[:8]


# ────────────────────────────────
#  Main scenario
# ────────────────────────────────


def main() -> int:
    procs: list[subprocess.Popen] = []
    try:
        # 1. Spawn chains --------------------------------------------------
        procs.append(spawn_anvil(PORT_A, CHAIN_A))
        procs.append(spawn_anvil(PORT_B, CHAIN_B))
        wait_for_node(RPC_A)
        wait_for_node(RPC_B)
        log("nodes up", f"A={CHAIN_A}@{RPC_A}  B={CHAIN_B}@{RPC_B}")

        # 2. Deploy via the production script ------------------------------
        stack_a = deploy_stack(RPC_A, "evm")
        stack_b = deploy_stack(RPC_B, "virtuals")
        log("deployed A (evm)", f"bridge={stack_a['NiveBridge']} core={stack_a['NiveCore']}")
        log("deployed B (virtuals)", f"bridge={stack_b['NiveBridge']} core={stack_b['NiveCore']}")

        client_a = JsonRpcClient(RPC_A)
        client_b = JsonRpcClient(RPC_B)
        bridge_a = stack_a["NiveBridge"]
        bridge_b = stack_b["NiveBridge"]
        core_b = stack_b["NiveCore"]

        # 3. Relayer key becomes a guardian on the TARGET chain -------------
        #    (NiveCore.registerGuardian records the 10k minimum without escrow in V1)
        relayer_signer = Signer(RELAYER_KEY)
        send_and_wait(client_b, relayer_signer, core_b,
                      calldata_register_guardian(10_000 * 10**18))
        log("relayer registered as guardian on B", relayer_signer.address)

        # 4. Fund + send a message from an independent sender on A -----------
        sender_signer = Signer("0x" + os.urandom(32).hex())
        governor_signer = Signer(GOVERNOR_KEY)
        send_and_wait(client_a, governor_signer, sender_signer.address,
                      data=b"", value=10**18, gas=21_000)
        log("sender funded", sender_signer.address)

        payload = (b'{"type":"agent-task","ref":"nive-e2e-'
                   + os.urandom(4).hex().encode() + b'"}')
        send_and_wait(client_a, sender_signer, bridge_a,
                      calldata_send_message(ECOSYSTEM_VIRTUALS, payload))
        log("message sent on A", f"payload={len(payload)}B → virtuals")

        # 5. Locate the MessageSent event (exercises the relayer's parser) --
        events = parse_message_sent_logs(
            client_a.get_logs(0, client_a.block_number(), bridge_a), CHAIN_A)
        if len(events) != 1:
            raise RuntimeError(f"expected exactly 1 MessageSent event, got {len(events)}")
        message_id = events[0].message_id
        log("observed MessageSent", f"id={message_id[:14]}…")

        # 6. Drive the real relayer ----------------------------------------
        config = RelayerConfig(chains=[
            ChainConfig(name="anvil-a", chain_id=CHAIN_A, rpc_url=RPC_A,
                        ecosystem=ECOSYSTEM_EVM, bridge_address=bridge_a,
                        start_block=0, confirmations=1,
                        poll_interval_seconds=0.5, delivery_retry_seconds=0.5,
                        delivery_max_attempts=60),
            ChainConfig(name="anvil-b", chain_id=CHAIN_B, rpc_url=RPC_B,
                        ecosystem=ECOSYSTEM_VIRTUALS, bridge_address=bridge_b,
                        start_block=0, confirmations=1,
                        poll_interval_seconds=0.5, delivery_retry_seconds=0.5,
                        delivery_max_attempts=60),
        ])
        relayer = NiveRelayer(config, relayer_signer)

        # 7. Governor acts as the second guardian: vote once the relayer has
        #    attested (validAttestations >= 1), so both attest paths run.
        governor_voted = False
        deadline = time.time() + DEADLINE_SECONDS
        while time.time() < deadline:
            relayer.poll_once()

            attests = int(_uint_at(client_b, bridge_b,
                                   selector_of("validAttestations(bytes32)"), message_id))
            if attests >= 1 and not governor_voted:
                send_and_wait(client_b, governor_signer, bridge_b,
                              calldata_verify_message(message_id, True))
                governor_voted = True
                log("governor attested", "quorum 2/2")

            delivered_count = _uint_at(client_b, bridge_b,
                                       selector_of("deliveredCount()"), "")
            tracked = relayer.tracked().get(message_id)
            if delivered_count == 1 and tracked is not None:
                break
            time.sleep(0.5)
        else:
            state = relayer.tracked().get(message_id)
            raise RuntimeError(
                f"E2E timed out after {DEADLINE_SECONDS}s — "
                f"state={state.state.value if state else 'untracked'} "
                f"err={state.last_error if state else '-'}"
            )

        # 8. Assertions — against chain state -------------------------------
        checks: list[tuple[str, bool, str]] = []

        tracked = relayer.tracked()[message_id]
        checks.append(("relayer confirmed delivery on-chain",
                       tracked.state.value == "delivered" and tracked.delivery_tx.startswith("0x"),
                       f"state={tracked.state.value} tx={tracked.delivery_tx[:18]}…"))
        checks.append(("source nonce recovered (provenance proof)",
                       tracked.source_nonce == 0,
                       f"nonce={tracked.source_nonce}"))

        attests = _uint_at(client_b, bridge_b,
                           selector_of("validAttestations(bytes32)"), message_id)
        checks.append(("quorum met on target", attests == 2, f"attestations={attests}"))

        inbox = decode_get_message(client_b.call_contract(
            bridge_b, selector_of("getMessage(bytes32)") + message_id[2:].rjust(64, "0")))
        checks.append(("inbox delivered flag", bool(inbox["delivered"]),
                       f"delivered={inbox['delivered']}"))
        checks.append(("payload preserved end-to-end",
                       inbox["payload"] == "0x" + payload.hex(), ""))
        checks.append(("sender preserved cross-chain",
                       inbox["sender"].lower() == sender_signer.address.lower(),
                       f"sender={inbox['sender']}"))
        checks.append(("source ecosystem bound",
                       inbox["source_ecosystem"] == ECOSYSTEM_EVM, ""))

        delivered_logs = client_b.get_logs(
            0, client_b.block_number(), bridge_b,
            topics=[TOPIC_MESSAGE_DELIVERED])
        delivered_event = len(delivered_logs) >= 1
        checks.append(("MessageDelivered emitted on target", delivered_event, ""))

        # 9. Report ----------------------------------------------------------
        failed = [name for name, ok, _ in checks if not ok]
        for name, ok, detail in checks:
            log(("PASS" if ok else "FAIL"), f"{name}" + (f" ({detail})" if detail else ""))
        if failed:
            print(f"\n[e2e] RESULT: {len(checks) - len(failed)}/{len(checks)} checks passed — FAILED")
            return 1
        print(f"\n[e2e] RESULT: all {len(checks)} checks passed — PASS")
        return 0
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                proc.kill()


def _uint_at(client: JsonRpcClient, to: str, selector: str, arg: str) -> int:
    data = selector if not arg else selector + arg.removeprefix("0x").rjust(64, "0")
    raw = client.call_contract(to, data).removeprefix("0x")
    return int.from_bytes(bytes.fromhex(raw)[:32], "big") if raw else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — top-level failure report
        print(f"[e2e] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
