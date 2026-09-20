#!/usr/bin/env python3
"""Nive CLI — Command-line interface for the Nive Protocol."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Nive Protocol CLI")
    parser.add_argument("--ecosystem", choices=["robinhood-chain", "evm", "virtuals"], default="robinhood-chain")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="Initialize Nive environment")
    agent_p = sub.add_parser("agent", help="Manage agents")
    agent_sub = agent_p.add_subparsers(dest="agent_command")
    reg = agent_sub.add_parser("register", help="Register a new agent")
    reg.add_argument("--name", required=True)
    reg.add_argument("--capabilities", nargs="+", required=True)
    reg.add_argument("--min-fee", type=float, default=0.0)
    task_p = sub.add_parser("task", help="Manage tasks")
    task_sub = task_p.add_subparsers(dest="task_command")
    tc = task_sub.add_parser("create", help="Create a task")
    tc.add_argument("--budget", type=float, required=True)
    tc.add_argument("--capabilities", nargs="+", required=True)
    args = parser.parse_args()
    if args.command == "init": print(f"✅ Nive initialized for {args.ecosystem}")
    elif args.command == "agent" and args.agent_command == "register": print(f"✅ Agent '{args.name}' registered")
    elif args.command == "task" and args.task_command == "create": print(f"✅ Task created (budget: {args.budget} NIVE)")
    else: parser.print_help()

if __name__ == "__main__":
    main()
