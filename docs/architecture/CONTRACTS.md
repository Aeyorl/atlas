# Atlas Smart Contract Architecture

All contracts target Solidity ^0.8.24, are built with Foundry, and use OpenZeppelin v5.1.0.
Current state: **139 tests passing across 7 suites** (`forge test`).

## Interfaces

| Interface | Purpose |
|-----------|---------|
| IAtlasCore | Protocol entry, guardian management, pause/slash |
| IAgentRegistry | Agent identity & capabilities |
| ITaskManager | Task lifecycle (create→bid→execute→settle) |
| ISettlementEngine | Payment settlement & slashing |
| IAtlasBridge | Cross-ecosystem messaging |
| IVerifier | Pluggable ZK proof verification (Groth16-ready) |

## Implemented Contracts

### `AgentRegistry` — agent identity & discovery

On-chain registry that every agent must join before participating.

- `register` / `updateAgent` / `deactivateAgent` — owner-controlled lifecycle with
  capability declarations, metadata URI, execution wallet, and minimum fee
- Discovery queries: `searchByCapability`, `getAgentByOwner`, `getAgentCount`
- Reputation counters (`totalTasks` / `successfulTasks`) are mutated **only** by the
  TaskManager (`setTaskManager` wiring, admin-gated via `REGISTRY_ADMIN_ROLE`)
- Access control: OpenZeppelin `AccessControl`

### `TaskManager` — task lifecycle state machine

Owns the create → bid → accept → complete → verify → dispute → settle lifecycle.
Holds **no funds**: budgets and bonds are forwarded to the SettlementEngine.

- `createTask` escrows the budget with the engine; agents bid; the creator accepts
- `completeTask` records the result **and the ZK proof blob** (exposed via `getProof`)
- Guardian dispute window (3 days) after verification, then settlement — both the
  direct and dispute-resolved settle paths forward the stored proof
- Governance: governor-gated admin functions (forfeited-task settlement)

### `SettlementEngine` — escrow custodian & settlement

The protocol treasury. All value flows through it; TaskManager keeps only lifecycle
authority. Follows checks-effects-interactions throughout.

- **Escrow**: `depositEscrow` / `getEscrow` / `refundCreator` (full refund on
  failed tasks and lost disputes)
- **Settlement**: `settle` pays the agent the accepted-bid fee minus the protocol
  cut; the cut splits between the governor treasury and an optional guardian
  treasury (`guardianShareBps`); unspent budget returns to the creator
- **Bonds**: `postBond` / `withdrawBond` with auto-release on successful settlement,
  plus a claim path for bonds on never-created task ids (nothing traps)
- **Slashing**: governor `slash` converts an agent's bond into failure compensation
- **ZK verification**: when a verifier is configured (`setVerifier`, governor-gated),
  `settle` decodes `verification = abi.encode(proof, publicInputs)`, requires
  `publicInputs[0] == uint256(taskId)` (structural anti-replay), and reverts on
  invalid proofs. The verifier is invoked via STATICCALL — a malicious verifier
  cannot mutate engine state. No verifier set = governor-trust mode (V1 default).

### `AtlasBridge` — cross-ecosystem message bus

One bridge instance per ecosystem (`robinhood-chain` | `evm` | `virtuals`), deployed
with its local ecosystem binding. Attested security, permissionless relaying.

- **Outbox**: `sendMessage(targetEcosystem, payload)` mints the deterministic id
  `keccak256(sourceEcosystem, targetEcosystem, payload, sender, sourceChainId, outboxNonce)`
- **Inbox**: any relayer calls `deliverMessage(id, payload, proof)` where
  `proof = abi.encode(sourceEcosystem, sender, sourceChainId, sourceNonce)` — every
  field is bound into the id, so tampering or wrong-target delivery reverts
- **Guardian quorum**: `verifyMessage(id, valid)` gated on the chain's AtlasCore
  guardian set (2-of-5 quorum; governor counts as one attester). Duplicate/flip
  votes are idempotently ignored; explicit rejections are recorded but do not block
  delivery (soft-fail design). Pre-delivery attestation is open, post-delivery closed.

### `AtlasCore` — governance & guardian registry

Protocol entry: guardian registration (min stake enforced), pause/unpause, and
guardian slashing — all governance functions governor-gated.

### `AtlasAgentVault` — ERC-4626 agent-managed vault (upstream, compile-fixed)

## Wiring Model

Circular dependencies are resolved post-deploy, mirroring the deploy script
(`scripts/deploy/DeployAtlas.s.sol`, ecosystem selected via `ATLAS_ECOSYSTEM` env):

```
SettlementEngine.setTaskManager(TaskManager)   // engine accepts only TaskManager calls
TaskManager.setSettlementEngine(engine)        // TaskManager forwards all value
AtlasBridge.setCore(AtlasCore)                 // bridge reads the guardian set
```

## Security Invariants

- Funds are custodied **only** by SettlementEngine; TaskManager is state-machine-only
- SettlementEngine transfers use CEI order; TaskManager↔Engine calls are authenticated
- ZK proofs are bound to the task id in public inputs — a proof accepted for one task
  can never settle another, independent of the circuit
- Bridge message ids bind source ecosystem, sender, chain id, and nonce — replay
  across instances or chains is structurally impossible
- Governance surface (pause, slash, fees, verifier, bridge core) is governor-gated

## Known Deltas vs. README Vision

| README claim | Current implementation |
|--------------|------------------------|
| 24h dispute window | 3-day dispute window (V1) |
| Randomly selected guardian committees | Fixed guardian set, 2-of-5 quorum |
| Reputation scoring engine | Success/failure counters per agent |
| Groth16 Circom verifier contract | Pluggable `IVerifier`; concrete Groth16 verifier pending |
| Runtime, SDK, CLI, API | Not yet in this repo |
