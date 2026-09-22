"""Multi-Chain Deployment Automation for Nive Protocol.

Reads network configurations from `config/networks.json`, validates chain connectivity,
and invokes Foundry's DeployNive.s.sol script with network-specific ecosystem configuration.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
NETWORKS_FILE = REPO_ROOT / "config" / "networks.json"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "DeployNive.s.sol"


def load_networks() -> dict[str, dict]:
    if not NETWORKS_FILE.exists():
        raise FileNotFoundError(f"Networks configuration not found at {NETWORKS_FILE}")
    with open(NETWORKS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("networks", {})


def get_rpc_url(network_data: dict) -> str:
    env_var = network_data.get("rpcEnv")
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return network_data.get("rpcUrl", "")


def check_chain_connectivity(rpc_url: str, expected_chain_id: int | None = None) -> int:
    """Query eth_chainId from RPC endpoint."""
    payload = json.dumps({"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1}).encode("utf-8")
    req = Request(rpc_url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "NiveDeployer/1.0"})
    with urlopen(req, timeout=5) as res:
        data = json.loads(res.read().decode("utf-8"))
        chain_id = int(data.get("result", "0x0"), 16)
        if expected_chain_id is not None and chain_id != expected_chain_id:
            raise ValueError(f"Chain ID mismatch: expected {expected_chain_id}, got {chain_id} from {rpc_url}")
        return chain_id


def deploy_network(
    network_key: str,
    network_data: dict,
    private_key: str,
    broadcast: bool = False,
    vk_json_path: str | None = None,
) -> int:
    rpc_url = get_rpc_url(network_data)
    if not rpc_url:
        print(f"[-] Missing RPC URL for {network_key}")
        return 1

    expected_chain_id = network_data.get("chainId")
    ecosystem = network_data.get("ecosystem", "evm")

    print(f"[*] Target Network: {network_data.get('name', network_key)} (Chain ID: {expected_chain_id})")
    print(f"[*] RPC Endpoint:   {rpc_url}")
    print(f"[*] Ecosystem:      {ecosystem}")

    try:
        chain_id = check_chain_connectivity(rpc_url, expected_chain_id)
        print(f"[+] RPC reachable. Chain ID verified: {chain_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"[-] Failed to verify RPC connection: {exc}")
        if broadcast:
            return 1
        print("    Continuing in dry-run simulation mode...")

    cmd = [
        "forge",
        "script",
        str(DEPLOY_SCRIPT),
        "--rpc-url",
        rpc_url,
    ]
    if broadcast:
        cmd.append("--broadcast")

    env = os.environ.copy()
    env["DEPLOYER_KEY"] = private_key
    env["NIVE_ECOSYSTEM"] = ecosystem
    if vk_json_path:
        env["NIVE_VK_JSON"] = vk_json_path

    print(f"[*] Executing forge script: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, check=False)
    return res.returncode


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Nive Multi-Chain Deployment Tool")
    parser.add_argument("--network", help="Network key from config/networks.json (or 'list')")
    parser.add_argument("--broadcast", action="store_true", help="Broadcast transactions on-chain")
    parser.add_argument("--private-key", default=os.environ.get("DEPLOYER_KEY"), help="Deployer private key (hex)")
    parser.add_argument("--vk", help="Path to verification key JSON for ZK verifier")
    parser.add_argument("--list", action="store_true", help="List configured networks")

    args = parser.parse_args()
    networks = load_networks()

    if args.list or args.network == "list" or not args.network:
        print("\n=== Configured Nive Networks ===")
        for key, info in sorted(networks.items()):
            net_type = "Devnet" if key == "anvil" else "Mainnet"
            print(f"  * {key:24} [Chain {info.get('chainId', '?'):6}] ({info.get('ecosystem'):15}) {net_type:7} -> {info.get('name')}")
        print()
        return

    if args.network not in networks:
        print(f"[-] Unknown network '{args.network}'. Available: {', '.join(networks.keys())}")
        sys.exit(1)

    pk = args.private_key or "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"  # default anvil #0
    code = deploy_network(args.network, networks[args.network], pk, broadcast=args.broadcast, vk_json_path=args.vk)
    sys.exit(code)


if __name__ == "__main__":
    main()
