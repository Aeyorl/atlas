"""Entry point: `python -m runtime.relayer <config.json>`.

Requires NIVE_RELAYER_KEY (the relayer's funding/guardian key) unless the
config file sets `private_key` per chain (KMS-backed signer or secure env).
"""

from __future__ import annotations

import os
import signal
import sys

from .config import load_config
from .service import NiveRelayer, Signer


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m runtime.relayer <config.json>", file=sys.stderr)
        return 2

    config = load_config(args[0])
    problems = config.validate()
    if problems:
        print("invalid config:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    key = os.environ.get("NIVE_RELAYER_KEY")
    signer = Signer(key) if key else None
    if signer is None:
        print(
            "warning: NIVE_RELAYER_KEY not set — running in observe-only mode "
            "(no attestations, no deliveries)",
            file=sys.stderr,
        )

    relayer = NiveRelayer(config, signer=signer)

    def _shutdown(_sig: int, _frame: object) -> None:
        print("[relayer] shutting down…")
        relayer.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    chains = ", ".join(f"{c.name}({c.chain_id})" for c in config.chains)
    print(f"[relayer] watching {len(config.chains)} chains: {chains}")
    relayer.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
