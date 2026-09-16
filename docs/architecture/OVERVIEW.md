# Atlas Protocol — Architecture Overview

```
┌─────────────────────────────────────┐
│         Developer Layer              │
├─────────────────────────────────────┤
│        Coordination Layer            │
├─────────────────────────────────────┤
│        Execution Layer               │
├─────────────────────────────────────┤
│        Settlement Layer              │
├──────────┬──────────┬────────────────┤
│ Robinhood│   EVM    │   Virtuals     │
│ Chain    │  (ETH,   │   Protocol     │
│          │  Base,   │                │
│          │  Arbitrum)│                │
└──────────┴──────────┴────────────────┘
```

## Core Components

### Implemented (on-chain, this repo)

- **Contracts**: AtlasCore (governance/guardians), AgentRegistry (identity +
  capabilities), TaskManager (task lifecycle state machine), SettlementEngine
  (escrow, fees, bonds, slashing, ZK-gated settlement), AtlasBridge (per-ecosystem
  attested message bus), AtlasAgentVault (ERC-4626)
- **ZK verification**: pluggable `IVerifier` interface wired into settlement with
  task-id-bound public inputs; concrete Groth16 verifier pending
- **Deploy**: Foundry script (`scripts/deploy/DeployAtlas.s.sol`) with per-ecosystem
  bridge binding (`ATLAS_ECOSYSTEM` env)
- **Tests**: 139 Foundry tests across 7 suites (`forge test`)

### Pending (off-chain / future phases)

- **Runtime**: Executor (sandbox), Groth16 Circom verifier, Relayer (cross-chain)
- **SDK**: Python, TypeScript, Rust
- **CLI / API**: agent management commands, REST + GraphQL read layer

See [CONTRACTS.md](./CONTRACTS.md) for the per-contract architecture, wiring model,
and security invariants.
