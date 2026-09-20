#!/usr/bin/env python3
"""Nive CLI — contract-backed command line interface for the Nive Protocol.

Every command talks to deployed Nive contracts (AgentRegistry, TaskManager,
SettlementEngine, NiveBridge, NiveCore). Read commands need only an RPC URL
and contract addresses; write commands additionally need NIVE_PRIVATE_KEY.

Setup:
  1. nive init                       # writes nive.json with address slots
  2. fill contract addresses in nive.json (or export NIVE_*_ADDRESS vars)
  3. export NIVE_PRIVATE_KEY=0x...   # only needed for write commands
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.python.chain import (
    ChainClient,
    capability_word,
    id_from_seed,
)

WEI_PER_ETHER = 10 ** 18
DEFAULT_CONFIG = "nive.json"
CONFIG_TEMPLATE = {
    "rpc_url": "http://127.0.0.1:8545",
    "contracts": {
        "registry": "",
        "task_manager": "",
        "settlement": "",
        "bridge": "",
        "core": "",
    },
}


# ────────────────────────────────
#  Formatting helpers
# ────────────────────────────────


def fmt_ether(wei: int) -> str:
    ether = wei / WEI_PER_ETHER
    text = f"{ether:.6f}".rstrip("0").rstrip(".")
    return f"{text} NIVE ({wei} wei)"


def fmt_word(word: str) -> str:
    """Shorten a bytes32 for display."""
    return word if len(word) <= 18 else f"{word[:10]}…{word[-6:]}"


def fmt_capability(word: str) -> str:
    """Decode a capability bytes32 to its text form when printable."""
    raw = bytes.fromhex(word.removeprefix("0x")).rstrip(b"\x00")
    if not raw:
        return "0x0"
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return word


def resolve_id(value: str | None, seed: str | None, kind: str) -> str:
    if seed:
        return id_from_seed(seed)
    if value:
        return value
    raise SystemExit(f"error: provide --id or --seed for the {kind}")


def parse_capabilities(texts: list[str]) -> list[str]:
    return [capability_word(t) for t in texts]


def parse_ether(value: str) -> int:
    return round(float(value) * WEI_PER_ETHER)


# ────────────────────────────────
#  Client loading
# ────────────────────────────────


def load_client(args: argparse.Namespace) -> ChainClient:
    if getattr(args, "config", None) and Path(args.config).exists():
        client = ChainClient.from_config(args.config)
    else:
        client = ChainClient.from_env()
    if getattr(args, "rpc", None):
        from runtime.relayer.chain import JsonRpcClient

        client.client = JsonRpcClient(args.rpc)
    return client


def require_signer(client: ChainClient) -> None:
    if client.signer is None:
        raise SystemExit(
            "error: this command sends a transaction — export NIVE_PRIVATE_KEY=0x…")


def print_kv(pairs: list[tuple[str, object]]) -> None:
    width = max(len(k) for k, _ in pairs)
    for key, value in pairs:
        print(f"  {key:<{width}}  {value}")


# ────────────────────────────────
#  Command handlers
# ────────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    path = Path(args.config)
    if path.exists() and not args.force:
        raise SystemExit(f"error: {path} already exists (use --force to overwrite)")
    path.write_text(json.dumps(CONFIG_TEMPLATE, indent=2) + "\n", encoding="utf-8")
    print(f"✅ wrote {path}")
    print("  next: fill the contract addresses (forge deploy output), then")
    print("        export NIVE_PRIVATE_KEY=0x… for write commands.")


def cmd_agent_register(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    agent_id = resolve_id(args.id, args.seed, "agent")
    receipt = client.register_agent(
        agent_id,
        args.uri,
        parse_capabilities(args.capabilities),
        execution_wallet=args.wallet,
        min_fee_wei=parse_ether(str(args.min_fee)),
    )
    print(f"✅ agent registered — tx {receipt.tx_hash}")
    print_kv([("agent id", fmt_word(agent_id)), ("owner", client.signer.address)])


def cmd_agent_get(args: argparse.Namespace) -> None:
    client = load_client(args)
    agent_id = resolve_id(args.id, args.seed, "agent")
    record = client.get_agent(agent_id)
    print_kv([
        ("agent id", fmt_word(str(record["agent_id"]))),
        ("owner", record["owner"]),
        ("uri", record["uri"]),
        ("capabilities", ", ".join(fmt_capability(str(c))
                                    for c in record["capabilities"]) or "—"),
        ("execution wallet", record["execution_wallet"]),
        ("min fee", fmt_ether(int(record["min_fee_wei"]))),
        ("active", record["active"]),
        ("tasks", f"{record['successful_tasks']}/{record['total_tasks']} successful"),
    ])


def cmd_agent_search(args: argparse.Namespace) -> None:
    client = load_client(args)
    ids = client.search_by_capability(capability_word(args.capability))
    print(f"agents declaring {args.capability!r}: {len(ids)}")
    for agent_id in ids:
        print(f"  {fmt_word(agent_id)}")


def cmd_agent_count(args: argparse.Namespace) -> None:
    print(f"registered agents: {load_client(args).agent_count()}")


def cmd_agent_deactivate(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    agent_id = resolve_id(args.id, args.seed, "agent")
    receipt = client.deactivate_agent(agent_id)
    print(f"✅ agent deactivated — tx {receipt.tx_hash}")


def cmd_task_create(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    task_id = resolve_id(args.id, args.seed, "task")
    budget_wei = (parse_ether(args.budget_ether) if args.budget_ether
                  else int(args.budget_wei))
    receipt = client.create_task(
        task_id,
        parse_capabilities(args.capabilities),
        budget_wei,
        parameters=(args.parameters or "").encode(),
        deadline=int(time.time()) + args.days * 86_400,
    )
    print(f"✅ task created + budget escrowed — tx {receipt.tx_hash}")
    print_kv([("task id", fmt_word(task_id)), ("budget", fmt_ether(budget_wei))])


def _print_task(task: dict) -> None:
    print_kv([
        ("task id", fmt_word(str(task["task_id"]))),
        ("creator", task["creator"]),
        ("status", task["status"]),
        ("budget", fmt_ether(int(task["budget_wei"]))),
        ("required", ", ".join(fmt_capability(str(c))
                               for c in task["required_capabilities"]) or "—"),
        ("assigned agent", task["assigned_agent"]),
        ("deadline", task["deadline"]),
    ])


def cmd_task_get(args: argparse.Namespace) -> None:
    _print_task(load_client(args).get_task(resolve_id(args.id, args.seed, "task")))


def cmd_task_bids(args: argparse.Namespace) -> None:
    task_id = resolve_id(args.id, args.seed, "task")
    bids = load_client(args).get_bids(task_id)
    print(f"bids on {fmt_word(task_id)}: {len(bids)}")
    for bid in bids:
        print(f"  {bid['bidder']}  fee={fmt_ether(int(bid['fee_wei']))}  {bid['status']}")


def cmd_task_bid(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    task_id = resolve_id(args.id, args.seed, "task")
    receipt = client.submit_bid(task_id, parse_ether(args.fee_ether))
    print(f"✅ bid submitted — tx {receipt.tx_hash} "
          f"(fee {fmt_ether(parse_ether(args.fee_ether))})")


def cmd_task_accept(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    task_id = resolve_id(args.id, args.seed, "task")
    receipt = client.accept_bid(task_id, args.agent)
    print(f"✅ bid accepted — tx {receipt.tx_hash} (agent {args.agent})")


def cmd_task_complete(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    task_id = resolve_id(args.id, args.seed, "task")
    result = Path(args.result_file).read_bytes() if args.result_file \
        else (args.result or "").encode()
    receipt = client.complete_task(task_id, result)
    print(f"✅ task completed — tx {receipt.tx_hash} "
          f"({len(result)}B result, sha256 committed on-chain)")


def cmd_task_settle(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    task_id = resolve_id(args.id, args.seed, "task")
    receipt = client.settle_task(task_id)
    print(f"✅ task settled — tx {receipt.tx_hash}")
    settlement = client.settlement(task_id)
    print_kv([
        ("agent fee", fmt_ether(int(settlement["agent_fee_wei"]))),
        ("guardian fee", fmt_ether(int(settlement["guardian_fee_wei"]))),
        ("protocol fee", fmt_ether(int(settlement["protocol_fee_wei"]))),
        ("settled", settlement["settled"]),
    ])


def cmd_escrow(args: argparse.Namespace) -> None:
    task_id = resolve_id(args.id, args.seed, "task")
    print(f"escrow held: {fmt_ether(load_client(args).escrow(task_id))}")


def cmd_bridge_send(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    message_id = client.send_bridge_message(
        args.target, (args.payload or "").encode())
    print(f"✅ message sent — id {message_id}")
    print("  the relayer will observe, attest, and deliver it to the target chain.")


def cmd_guardian_register(args: argparse.Namespace) -> None:
    client = load_client(args)
    require_signer(client)
    stake_wei = parse_ether(args.stake_ether)
    receipt = client.register_guardian(stake_wei)
    print(f"✅ guardian registered — tx {receipt.tx_hash} "
          f"(stake {fmt_ether(stake_wei)})")


def cmd_guardian_count(args: argparse.Namespace) -> None:
    print(f"guardians: {load_client(args).guardian_count()}")


# ────────────────────────────────
#  Parser
# ────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nive", description="Nive Protocol CLI (contract-backed)")
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help=f"path to nive.json (default: {DEFAULT_CONFIG})")
    parser.add_argument("--rpc", help="override the RPC URL from config/env")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="write a nive.json config template")
    init_p.add_argument("--force", action="store_true")
    init_p.set_defaults(func=cmd_init)

    agent_p = sub.add_parser("agent", help="agent registry commands")
    agent_sub = agent_p.add_subparsers(dest="agent_command", required=True)

    def add_id_args(p: argparse.ArgumentParser, kind: str) -> None:
        p.add_argument("--id", help=f"{kind} id as 0x-hex bytes32")
        p.add_argument("--seed", help=f"{kind} id derived from seed text")

    reg = agent_sub.add_parser("register", help="register an agent")
    add_id_args(reg, "agent")
    reg.add_argument("--uri", required=True, help="agent metadata endpoint")
    reg.add_argument("--capabilities", nargs="+", required=True)
    reg.add_argument("--min-fee", default="0", help="minimum fee in NIVE ether units")
    reg.add_argument("--wallet", help="execution wallet (default: signer address)")
    reg.set_defaults(func=cmd_agent_register)

    get = agent_sub.add_parser("get", help="fetch an agent record")
    add_id_args(get, "agent")
    get.set_defaults(func=cmd_agent_get)

    search = agent_sub.add_parser("search", help="agents declaring a capability")
    search.add_argument("--capability", required=True)
    search.set_defaults(func=cmd_agent_search)

    agent_sub.add_parser("count", help="registered agent count"
                         ).set_defaults(func=cmd_agent_count)

    deact = agent_sub.add_parser("deactivate", help="permanently deactivate an agent")
    add_id_args(deact, "agent")
    deact.set_defaults(func=cmd_agent_deactivate)

    task_p = sub.add_parser("task", help="task lifecycle commands")
    task_sub = task_p.add_subparsers(dest="task_command", required=True)

    create = task_sub.add_parser("create", help="create a task and escrow its budget")
    add_id_args(create, "task")
    create.add_argument("--capabilities", nargs="+", required=True)
    group = create.add_mutually_exclusive_group(required=True)
    group.add_argument("--budget-ether", help="budget in NIVE ether units")
    group.add_argument("--budget-wei", help="budget in wei")
    create.add_argument("--parameters", help="task parameters (stored as bytes)")
    create.add_argument("--days", type=int, default=1, help="deadline in days")
    create.set_defaults(func=cmd_task_create)

    tget = task_sub.add_parser("get", help="fetch a task record")
    add_id_args(tget, "task")
    tget.set_defaults(func=cmd_task_get)

    bids = task_sub.add_parser("bids", help="list bids on a task")
    add_id_args(bids, "task")
    bids.set_defaults(func=cmd_task_bids)

    bid = task_sub.add_parser("bid", help="submit a bid (as a registered agent)")
    add_id_args(bid, "task")
    bid.add_argument("--fee-ether", required=True)
    bid.set_defaults(func=cmd_task_bid)

    accept = task_sub.add_parser("accept", help="accept a bid (task creator)")
    add_id_args(accept, "task")
    accept.add_argument("--agent", required=True, help="bidder address")
    accept.set_defaults(func=cmd_task_accept)

    complete = task_sub.add_parser("complete", help="complete an assigned task")
    add_id_args(complete, "task")
    complete.add_argument("--result", help="result payload as text")
    complete.add_argument("--result-file", help="read the result payload from a file")
    complete.set_defaults(func=cmd_task_complete)

    settle = task_sub.add_parser("settle", help="settle a verified task")
    add_id_args(settle, "task")
    settle.set_defaults(func=cmd_task_settle)

    esc = sub.add_parser("escrow", help="escrow held for a task")
    add_id_args(esc, "task")
    esc.set_defaults(func=cmd_escrow)

    bridge = sub.add_parser("bridge", help="cross-ecosystem messaging")
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    send = bridge_sub.add_parser("send", help="send a message to another ecosystem")
    send.add_argument("--target", required=True,
                      choices=["robinhood-chain", "evm", "virtuals"])
    send.add_argument("--payload", help="message payload text")
    send.set_defaults(func=cmd_bridge_send)

    guardian = sub.add_parser("guardian", help="guardian operations")
    guardian_sub = guardian.add_subparsers(dest="guardian_command", required=True)
    greg = guardian_sub.add_parser("register", help="register as a guardian")
    greg.add_argument("--stake-ether", required=True)
    greg.set_defaults(func=cmd_guardian_register)
    guardian_sub.add_parser("count", help="guardian count"
                            ).set_defaults(func=cmd_guardian_count)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — CLI reports errors, never tracebacks
        label = type(exc).__name__ if not isinstance(exc, (OSError, RuntimeError)) else "error"
        print(f"error: {label}: {exc}" if label != "error" else f"error: {exc}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
