"""Scratch diagnostic: eth_call deliverMessage after quorum to get revert reason."""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "e2e"))

import relay_e2e as e2e

from runtime.relayer.chain import (
    SELECTOR_GET_OUTBOX,
    JsonRpcClient,
    _decode_outbox,
    keccak256,
)
from runtime.relayer.config import (
    ECOSYSTEM_EVM,
    ECOSYSTEM_VIRTUALS,
    ChainConfig,
    RelayerConfig,
)
from runtime.relayer.service import (
    BridgeReader,
    NiveRelayer,
    Signer,
    _abi_bytes,
    _word,
    abi_encode,
)

SEL_DELIVER = "0x" + keccak256(b"deliverMessage(bytes32,bytes,bytes)").hex()[:8]


def main() -> None:
    nodes = []
    try:
        nodes = [e2e.spawn_anvil(e2e.PORT_A, e2e.CHAIN_A),
                 e2e.spawn_anvil(e2e.PORT_B, e2e.CHAIN_B)]
        e2e.wait_for_node(e2e.RPC_A)
        e2e.wait_for_node(e2e.RPC_B)
        stack_a = e2e.deploy_stack(e2e.RPC_A, "evm")
        stack_b = e2e.deploy_stack(e2e.RPC_B, "virtuals")
        client_a = JsonRpcClient(e2e.RPC_A)
        client_b = JsonRpcClient(e2e.RPC_B)
        bridge_a, bridge_b = stack_a["NiveBridge"], stack_b["NiveBridge"]

        relayer_signer = Signer(e2e.RELAYER_KEY)
        e2e.send_and_wait(client_b, relayer_signer, stack_b["NiveCore"],
                          e2e.calldata_register_guardian(10_000 * 10**18))

        sender = Signer("0x" + "11" * 32)
        governor = Signer(e2e.GOVERNOR_KEY)
        e2e.send_and_wait(client_a, governor, sender.address, b"", value=10**18, gas=21_000)
        payload = b'{"type":"agent-task","ref":"scratch"}'
        e2e.send_and_wait(client_a, sender, bridge_a,
                          e2e.calldata_send_message(e2e.ECOSYSTEM_VIRTUALS, payload))
        events = e2e.parse_message_sent_logs(
            client_a.get_logs(0, client_a.block_number(), bridge_a), e2e.CHAIN_A)
        mid = events[0].message_id
        print("message_id:", mid)

        config = RelayerConfig(chains=[
            ChainConfig(name="anvil-a", chain_id=e2e.CHAIN_A, rpc_url=e2e.RPC_A,
                        ecosystem=ECOSYSTEM_EVM, bridge_address=bridge_a,
                        start_block=0, confirmations=1, poll_interval_seconds=0.5,
                        delivery_retry_seconds=0.5, delivery_max_attempts=60),
            ChainConfig(name="anvil-b", chain_id=e2e.CHAIN_B, rpc_url=e2e.RPC_B,
                        ecosystem=ECOSYSTEM_VIRTUALS, bridge_address=bridge_b,
                        start_block=0, confirmations=1, poll_interval_seconds=0.5,
                        delivery_retry_seconds=0.5, delivery_max_attempts=60),
        ])
        relayer = NiveRelayer(config, relayer_signer)

        # Poll until the relayer has attested (validAttestations >= 1), then
        # vote as governor to reach quorum 2/2.
        reader_b = BridgeReader(client_b, bridge_b, e2e.CHAIN_B)
        for _ in range(40):
            relayer.poll_once()
            if reader_b.valid_attestations(mid) >= 1:
                break
            time.sleep(0.3)
        print("attestations after relayer:", reader_b.valid_attestations(mid))
        e2e.send_and_wait(client_b, governor, bridge_b,
                          e2e.calldata_verify_message(mid, True))
        print("attestations after governor:", reader_b.valid_attestations(mid))

        tracked = relayer.tracked().get(mid)
        print("relayer state:", tracked.state.value if tracked else None)

        # Build deliverMessage calldata exactly as NiveRelayer._deliver does.
        _te, out_sender, payload_hex, _at = _decode_outbox(
            client_a.call_contract(bridge_a, SELECTOR_GET_OUTBOX
                                   + mid[2:].rjust(64, "0")))
        payload_bytes = bytes.fromhex(payload_hex.removeprefix("0x"))
        proof = abi_encode([ECOSYSTEM_EVM, out_sender, e2e.CHAIN_A,
                            tracked.source_nonce])
        payload_block = _abi_bytes(payload_bytes)
        proof_block = _abi_bytes(proof)
        calldata = (
            bytes.fromhex(SEL_DELIVER.removeprefix("0x"))
            + _word(mid)
            + (0x60).to_bytes(32, "big")
            + (0x60 + len(payload_block)).to_bytes(32, "big")
            + payload_block
            + proof_block
        )
        print("proof:", proof.hex())
        try:
            res = client_b.call("eth_call", [{"to": bridge_b, "data": "0x" + calldata.hex()},
                                             "latest"])
            print("eth_call OK:", res)
        except Exception as exc:  # noqa: BLE001 — diagnostic prints the revert
            print("eth_call revert:", exc)

        # Drive the real relayer through delivery and check the inbox record.
        for _ in range(10):
            relayer.poll_once()
            time.sleep(0.3)
        print("final relayer state:", relayer.tracked()[mid].state.value)

        # Compare each proof field against the id derivation inputs.
        print("out_sender:", out_sender)
        print("tracked.sender:", tracked.sender)
        print("tracked.source_nonce:", tracked.source_nonce)
    finally:
        for n in nodes:
            n.terminate()


if __name__ == "__main__":
    main()
