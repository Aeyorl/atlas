"""Relayer configuration: one tracked chain per (chain_id, ecosystem, bridge)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .chain import keccak256

# Ecosystem identifiers — must match NiveCore / NiveBridge constants.
ECOSYSTEM_ROBINHOOD = "0x" + keccak256(b"robinhood-chain").hex()
ECOSYSTEM_EVM = "0x" + keccak256(b"evm").hex()
ECOSYSTEM_VIRTUALS = "0x" + keccak256(b"virtuals").hex()

ECOSYSTEM_NAMES = {
    ECOSYSTEM_ROBINHOOD: "robinhood-chain",
    ECOSYSTEM_EVM: "evm",
    ECOSYSTEM_VIRTUALS: "virtuals",
}


def ecosystem_name(ecosystem_hex: str) -> str:
    """Human-readable name for an ecosystem bytes32, or the raw hex."""
    return ECOSYSTEM_NAMES.get(ecosystem_hex, ecosystem_hex)


@dataclass(frozen=True)
class ChainConfig:
    """One chain this relayer watches and delivers on."""

    name: str
    chain_id: int
    rpc_url: str
    ecosystem: str            # 0x-prefixed keccak("robinhood-chain"|"evm"|"virtuals")
    bridge_address: str       # NiveBridge proxy/logic address on this chain

    # Delivery signing key. In production this comes from a KMS/HSM;
    # an env var / config file is acceptable for testnets.
    private_key: str | None = None

    # Block to start scanning from on first run. None = current head.
    start_block: int | None = None

    # Poll tuning
    poll_interval_seconds: float = 6.0
    confirmations: int = 1
    max_block_range: int = 2000
    delivery_max_attempts: int = 10
    delivery_retry_seconds: float = 30.0

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.rpc_url.startswith(("http://", "https://")):
            problems.append(f"[{self.name}] rpc_url must be an http(s) URL")
        if self.ecosystem not in ECOSYSTEM_NAMES:
            problems.append(f"[{self.name}] unknown ecosystem: {self.ecosystem}")
        if not self.bridge_address.startswith("0x") or len(self.bridge_address) != 42:
            problems.append(f"[{self.name}] bridge_address must be a 20-byte hex address")
        return problems


@dataclass
class RelayerConfig:
    chains: list[ChainConfig] = field(default_factory=list)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.chains:
            return ["no chains configured"]
        seen_ids: dict[int, str] = {}
        for chain in self.chains:
            problems.extend(chain.validate())
            if chain.chain_id in seen_ids:
                problems.append(
                    f"duplicate chain_id {chain.chain_id}: "
                    f"{seen_ids[chain.chain_id]} and {chain.name}"
                )
            seen_ids[chain.chain_id] = chain.name
        return problems

    def by_chain_id(self, chain_id: int) -> ChainConfig | None:
        for chain in self.chains:
            if chain.chain_id == chain_id:
                return chain
        return None

    def by_ecosystem(self, ecosystem: str) -> ChainConfig | None:
        """First chain configured for `ecosystem` (delivery target)."""
        for chain in self.chains:
            if chain.ecosystem == ecosystem:
                return chain
        return None


# ────────────────────────────────
#  Loading
# ────────────────────────────────


def _coerce_chain(raw: dict[str, Any]) -> ChainConfig:
    return ChainConfig(
        name=raw["name"],
        chain_id=int(raw["chain_id"]),
        rpc_url=raw["rpc_url"],
        ecosystem=raw["ecosystem"],
        bridge_address=raw["bridge_address"],
        private_key=raw.get("private_key") or os.environ.get("NIVE_RELAYER_KEY"),
        start_block=(int(raw["start_block"]) if raw.get("start_block") is not None else None),
        poll_interval_seconds=float(raw.get("poll_interval_seconds", 6.0)),
        confirmations=int(raw.get("confirmations", 1)),
        max_block_range=int(raw.get("max_block_range", 2000)),
        delivery_max_attempts=int(raw.get("delivery_max_attempts", 10)),
        delivery_retry_seconds=float(raw.get("delivery_retry_seconds", 30.0)),
    )


def load_config(path: str) -> RelayerConfig:
    """Load a relayer config JSON file.

    Expected shape:
    {
      "chains": [
        {"name": "base-testnet", "chain_id": 84532, "rpc_url": "https://...",
         "ecosystem": "evm", "bridge_address": "0x..."}
      ]
    }
    `ecosystem` accepts the friendly name or the raw bytes32 hex.
    """
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)

    friendly = {"robinhood-chain": ECOSYSTEM_ROBINHOOD, "evm": ECOSYSTEM_EVM, "virtuals": ECOSYSTEM_VIRTUALS}
    chains = []
    for entry in raw.get("chains", []):
        entry = dict(entry)
        if entry.get("ecosystem") in friendly:
            entry["ecosystem"] = friendly[entry["ecosystem"]]
        chains.append(_coerce_chain(entry))
    return RelayerConfig(chains=chains)
