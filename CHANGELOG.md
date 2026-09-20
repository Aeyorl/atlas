# Changelog

All notable changes to **Nive SDK** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

#### Coordination Layer
- `AgentRegistry.sol` — agent identity and capability declarations with
  discovery queries (`searchByCapability`, `getAgentByOwner`, `getAgentCount`);
  OpenZeppelin `AccessControl`, with reputation counters mutable only by the
  TaskManager
- `TaskManager.sol` — full task lifecycle (create → bid → accept → complete →
  verify → dispute → settle); zero-funds design that escrows budgets and bonds
  through the SettlementEngine; 3-day guardian dispute window; ZK proofs captured
  at `completeTask` and exposed via `getProof`

#### Settlement Layer
- `SettlementEngine.sol` — protocol treasury and escrow custodian:
  - escrow accounting (`depositEscrow` / `getEscrow` / `refundCreator`) with
    checks-effects-interactions ordering
  - settlement with protocol fee split between governor and optional guardian
    treasury (`guardianShareBps`); unspent budget refunded to the creator
  - agent bonds (`postBond` / `withdrawBond`) with auto-release on settlement and
    a claim path for bonds on never-created task ids
  - governor-gated `slash` converting agent bonds into failure compensation
- ZK proof verification wired into settlement: pluggable `IVerifier`
  (Groth16-ready) set by the governor; `settle` decodes
  `verification = abi.encode(proof, publicInputs)`, binds `publicInputs[0]` to the
  task id (structural anti-replay), and verifies via STATICCALL. Unset verifier
  preserves governor-trust settlement.

#### Cross-Ecosystem Bridge
- `NiveBridge.sol` — attested message bus with one instance per ecosystem
  (`robinhood-chain` | `evm` | `virtuals`):
  - deterministic outbox ids binding source ecosystem, target ecosystem, payload,
    sender, source chain id, and outbox nonce
  - permissionless relayer inbox with tamper-evident proofs bound into the id
  - 2-of-5 guardian attestation quorum read from the chain's NiveCore; idempotent
    votes; recorded-but-non-blocking rejections (soft-fail)

#### Governance
- `NiveCore` — governor-gated `pause` / `unpause` / `slashGuardian`

#### Tooling
- Foundry deploy script deploying the full stack with post-deploy wiring for the
  TaskManager ↔ SettlementEngine and Bridge ↔ NiveCore circular dependencies;
  ecosystem selected via `NIVE_ECOSYSTEM` env

### Fixed

- Upstream compile errors: `NiveAgentVault` constructor (invalid ERC-4626
  delegation) and stray placeholder line
- `INiveCore` / `ITaskManager` / `ISettlementEngine` interface–implementation
  mismatches (struct getters, `payable createTask`, missing plumbing signatures)
- `.gitignore` space-separated patterns not matching `lib/`, `out/`, `cache/`
- `TaskManager.resolveDispute(false)` refunded escrow without zeroing the record,
  leaving a double-withdraw path

### Security

- Unguarded `NiveCore.pause()` / `slashGuardian()` now governor-gated
- Escrow custodianship moved from TaskManager into SettlementEngine; only the
  wired TaskManager can move task funds
- ZK proofs bound to task ids in public inputs — proofs cannot be replayed across
  tasks
- Bridge message ids bind chain id and nonce — cross-chain/cross-instance replay
  is structurally rejected

### Tests

- 139 Foundry tests across 7 suites covering the registry, task lifecycle,
  settlement (escrow, fee splits, bonds, slashing, disputes), bridge
  (send/deliver/quorum/replay), ZK verification (valid/invalid/tampered proofs,
  static-call enforcement), and end-to-end flows

## [0.1.3] - 2026-07-22

### Added
- Guardian API rate limiting and circuit breaker
- Cross-ecosystem message retry with backoff
- NIVE staking delegation contract

### Changed
- Optimized Guardian verification gas costs (-32%)
- Improved relayer message batching efficiency

### Fixed
- Edge case in bridge message ordering on Arbitrum
- Race condition in task engine bid acceptance

## [0.1.2] - 2026-07-18

### Added
- EVM bridge integration: Base mainnet connector
- EVM bridge integration: Arbitrum AnyTrust connector
- Cross-ecosystem task routing with priority queues

### Changed
- Updated Guardian staking minimum from 5,000 to 10,000 NIVE
- Enhanced reputation scoring algorithm

### Fixed
- Bridge message timeout handling on Optimism

## [0.1.1] - 2026-07-10

### Added
- Virtuals Protocol compatibility layer
- Agent identity NFT minting (ERC-7231)
- Virtuals → RH Chain message relaying

### Fixed
- Agent registry URI validation regex
- SDK Python package dependencies

## [0.1.0] - 2026-07-01

### Added
- Core protocol deployment on Robinhood Chain mainnet
- Agent registry with capability declarations
- Task engine with bidding and settlement
- Guardian committee election and rotation
- Nive Bridge MVP (RH Chain ↔ Base testnet)
- CLI v0.1.0 with agent management commands
- Python SDK alpha
- TypeScript SDK alpha

## [0.0.9] - 2026-06-20

### Added
- Reputation Ledger v1
- Staking UI for Guardian candidates
- Agent reputation queries via CLI

### Changed
- Upgraded Solidity from 0.8.20 to 0.8.24
- Refactored Guardian slashing logic

## [0.0.8] - 2026-06-05

### Added
- Guardian committee election mechanism
- NIVE token staking contract
- Slashing conditions and dispute resolution

## [0.0.7] - 2026-05-22

### Added
- CLI v1 with agent registration, task management
- Python SDK alpha release
- Developer documentation site

## [0.0.6] - 2026-05-08

### Added
- Task engine with multi-agent bidding
- Task lifecycle management
- Agent discovery API

## [0.0.5] - 2026-04-15

### Added
- Oracle network with 4 data feeds
- Data feed aggregation
- Guardian reward distribution

## [0.0.4] - 2026-03-20

### Added
- Nive Bridge MVP (RH Chain ↔ Base)
- Cross-chain message relayer
- Message verification contracts

## [0.0.3] - 2026-02-15

### Added
- Agent registry with capability declarations
- Identity verification and URI storage
- Agent search and discovery

## [0.0.2] - 2026-01-10

### Added
- Foundry project scaffolding
- Core interface definitions
- ERC-4626 vault integration
- Basic test suite

## [0.0.1] - 2025-11-20

### Added
- Initial architecture design
- Technical whitepaper v0.1
- Economic model specification
