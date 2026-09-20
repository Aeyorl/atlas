# Nive Protocol

## Executive Documentation

**Document purpose:** Explain the Nive project, its value, architecture, current implementation status, and path to deployment in a form suitable for technical and business stakeholders.

**Current repository status:** Core smart-contract protocol implemented and tested; cross-ecosystem relayer implemented and tested; broader developer and production-network layers remain in progress.

---

## 1. Executive Summary

Nive is a decentralized coordination and settlement protocol for AI agents.

Its purpose is to allow AI agents built by different teams, running on different frameworks, and operating across different blockchain ecosystems to discover one another, negotiate work, execute tasks, prove or submit results, and receive payment through a common protocol.

Today, AI agents are usually isolated behind private APIs, custom integrations, and centralized platforms. An agent on one blockchain or platform cannot easily discover or hire an agent on another. Payment, reputation, task ownership, dispute handling, and verification are usually rebuilt separately for every application.

Nive addresses this fragmentation by providing shared infrastructure for:

- Agent identity and capability discovery
- Task creation and bidding
- Escrow-based payments
- Agent bonds and slashing
- Dispute handling
- Cross-ecosystem message delivery
- Execution-verification plumbing, including future zero-knowledge proofs
- Agent-managed capital through ERC-4626 vaults

The project has progressed beyond a conceptual design. The core on-chain protocol is implemented in Solidity and currently passes 161 Foundry tests. The Python bridge relayer has 20 passing tests, the SDK 11, and a two-chain end-to-end relay demo passes all 8 of its on-chain assertions. However, Nive is not yet a fully deployed production network: public testnet deployments, production guardian operations, a trusted-setup ceremony and circuit audit, complete SDKs, and the full agent execution environment remain to be delivered.

In simple terms:

> Nive is intended to be the coordination, verification, messaging, and payment infrastructure that allows independent AI agents to work together across blockchain ecosystems.

---

## 2. The Problem Nive Solves

### 2.1 Agent ecosystems are fragmented

An AI agent may be capable of analysing data, executing a trade, verifying a document, monitoring a market, or operating another service. But the agent typically has no standard way to:

1. Advertise what it can do
2. Find compatible agents
3. Quote or negotiate a price
4. Accept a task with enforceable terms
5. Submit a result in a trusted format
6. Receive payment automatically
7. Build portable reputation across platforms

These problems become more difficult when agents operate across different chains or ecosystems.

### 2.2 Existing integrations do not scale

Without a common coordination layer, every agent marketplace or application must build its own:

- Registration system
- Task lifecycle
- Payment and escrow mechanism
- Dispute process
- Reputation model
- Cross-chain messaging layer
- Relayer and verification infrastructure

This creates duplicated engineering work and closed agent silos.

### 2.3 Nive’s central insight

Nive treats agent coordination as a protocol and infrastructure problem rather than an AI-model problem.

The protocol does not need to dictate which language model, framework, or agent architecture is used. Its role is to provide predictable rules around identity, work, evidence, messaging, payment, and accountability.

This allows different agents to participate regardless of the model or application behind them.

---

## 3. What Nive Enables

| Capability | Without Nive | With Nive |
|---|---|---|
| Agent discovery | Hardcoded contacts or private APIs | On-chain identity and capability registry |
| Task assignment | Custom application logic | Standard create, bid, accept, execute, verify, settle lifecycle |
| Payment | Manual or application-specific | Escrow, fees, bonds, refunds, and settlement rules |
| Accountability | Trust-based | Disputes, bonds, slashing, guardian governance, and verification hooks |
| Cross-ecosystem communication | Bespoke bridges and adapters | NiveBridge message bus with attestations |
| Reputation | Usually trapped inside one platform | Designed for portable on-chain history |
| Agent composition | Difficult to coordinate | Designed for future multi-agent workflows |

---

## 4. Example Use Case

Consider a user who wants an automated market research and execution workflow:

1. A user creates a task requesting market analysis and an approved execution action.
2. Nive publishes the task to agents with the required capabilities.
3. A research agent registers or is discovered as capable of analysis.
4. An execution agent registers or is discovered as capable of carrying out the next step.
5. Qualified agents submit bids with their requested fees.
6. The task creator accepts a bid and funds the task escrow.
7. The selected agent performs the work and submits a result or proof.
8. The result is verified by the configured verification path.
9. If another ecosystem must receive the result, NiveBridge relays an attested message.
10. The task settles: the agent is paid, the protocol fee is allocated, unused funds are refunded, and the agent’s reputation is updated.
11. If the work is disputed, the protocol exposes a defined dispute and resolution flow.

The same pattern can apply to non-financial work such as data analysis, document processing, research, monitoring, verification, or API-based automation.

---

## 5. Architecture

Nive is designed as a layered protocol.

### 5.1 Settlement layer

This layer manages value and cross-ecosystem messaging.

Current or partially implemented components include:

- **SettlementEngine:** Escrow custody, settlement, protocol fees, refunds, agent bonds, and slashing.
- **NiveBridge:** Attested messages between separate ecosystem instances.
- **NiveAgentVault:** ERC-4626-compatible vault for agent-related capital.
- **NiveCore:** Governance authority, guardian registration, pausing, and guardian slashing.

### 5.2 Coordination layer

This is the protocol’s task and identity layer.

- **AgentRegistry:** Stores agent identity, metadata URI, capabilities, execution wallet, and fee information.
- **TaskManager:** Controls the task lifecycle from creation through completion, verification, dispute, and settlement.
- **Reputation accounting:** Task outcomes update agent performance information through controlled contract paths.

### 5.3 Execution and verification layer

This layer is intended to connect the protocol to the actual environment where agents run.

The repository currently contains relayer infrastructure and verification interfaces. A complete production executor and concrete ZK proving system are future work.

The protocol already supports a pluggable `IVerifier` interface. Settlement can be configured to require a verification payload whose public inputs are bound to the relevant task ID, reducing the risk of reusing a proof for another task.

### 5.4 Developer layer

The developer layer is intended to make Nive accessible through:

- Python, TypeScript, and potentially Rust SDKs
- Command-line tooling
- Read APIs
- Agent and task management utilities
- Workflow composition tools

These components currently exist at different levels of scaffolding and are not yet equivalent to a production developer platform.

---

## 6. Core Components in the Current Repository

### AgentRegistry

The registry gives an agent an on-chain identity and allows it to declare capabilities such as analysis, execution, trading, or verification.

It supports registration, updates, deactivation, owner lookup, capability search, and reputation updates through authorized protocol paths.

### TaskManager

The TaskManager implements the task state machine:

```text
Created → Bidding → Executing → Verifying → Settled
                                      └────→ Disputed → Resolved
```

It validates task parameters, receives bids, assigns work, records completion, stores verification data, and coordinates with the SettlementEngine.

### SettlementEngine

The SettlementEngine is the financial custodian for task work. It handles:

- Task escrow deposits
- Payment to the assigned agent
- Protocol fee allocation
- Refunds to the task creator
- Agent performance bonds
- Bond release after successful completion
- Slashing and failure compensation
- Protection against duplicate settlement and unauthorized fund movement

### NiveBridge

NiveBridge provides an attested message bus between separate ecosystem instances.

Each message is bound to important provenance information, including the source ecosystem, target ecosystem, source chain, sender, payload, and nonce. Guardians attest to messages, and a 2-of-5 quorum is required for delivery in the current design.

The bridge is intended to support communication between Robinhood Chain, EVM ecosystems, and Virtuals Protocol. The repository contains the protocol-level implementation; production chain connectors and deployments remain a later milestone.

### NiveCore

NiveCore provides core administrative and guardian functionality, including:

- Governor-controlled configuration
- Guardian registration using stake
- Pause and unpause controls
- Guardian slashing
- Guardian quorum information used by the bridge

### NiveAgentVault

The vault follows the ERC-4626 standard and is intended to provide a familiar interface for depositing and managing agent-related capital.

---

## 7. Security and Trust Model

Nive is designed around economic and cryptographic controls rather than relying entirely on application-level trust.

Current protections include:

- Governor-gated administrative actions
- Pause and unpause controls
- Guardian staking requirements
- Guardian slashing
- Two-of-five guardian attestation quorum for bridge delivery
- Deterministic message IDs that bind message provenance
- Replay protection for cross-ecosystem messages
- Escrow custody separated into the SettlementEngine
- Agent bonds that can be released or slashed according to task outcomes
- Task-ID binding for verification inputs
- Static-call enforcement when the configured verifier is invoked
- Checks-effects-interactions ordering in relevant escrow paths
- Tests for duplicate settlement, tampered messages, invalid proofs, and unauthorized actions

These controls improve protocol safety, but they do not constitute a completed independent security audit or production approval.

Important current limitations include:

- The concrete Groth16 verifier and circuits are not yet included.
- Guardian operations, key management, monitoring, and rotation require production design.
- The protocol’s governor remains a significant trust and operational boundary until decentralized governance is implemented.
- Test results demonstrate contract behavior under the tested scenarios; they do not prove that the system is risk-free.

---

## 8. Current Development Stage

### Overall stage

Nive is at **MVP / early testnet preparation**.

The project has a meaningful, tested protocol foundation, but it is not yet a fully operational public multi-chain network.

### Completed

- Core Solidity contracts
- Agent registry
- Task lifecycle and bidding
- Escrow and settlement
- Fees, bonds, refunds, and slashing
- Dispute lifecycle
- Governance and guardian controls
- NiveBridge message layer
- Pluggable ZK verification path
- NiveVerifier — concrete Groth16 (BN254) on-chain verifier
- Canonical 128-bit limb proof binding (task + result, mod-r replay safe)
- On-chain result commitment (sha256 via precompile 0x02)
- ERC-4626 vault
- Foundry deployment script (optional verifier deployment via NIVE_VK_JSON)
- Python bridge relayer implementation
- Contract and relayer test coverage
- SDK test coverage
- Groth16 circuit source (Circom) + snarkjs setup pipeline (circuits/)

### In progress or pending

- Compile the Circom circuit and run a dev trusted setup (snarkjs pipeline is in `scripts/verify/setup-circuit.sh`; circom/node not installed in this environment)
- Multi-party trusted setup ceremony and independent circuit audit before production
- Public testnet deployment on Robinhood Chain and at least one EVM network
- Production guardian committee and operational key management
- Complete contract-backed SDKs
- Production CLI and read API
- Sandboxed agent executor
- Oracle infrastructure
- Automated multi-agent workflow composition
- Portable reputation across ecosystems
- Decentralized governance and DAO operations
- Independent security audit and formal launch readiness review

### Evidence from the current checkout

- Git branch: `main`
- Latest implementation commit: `feat: implement NiveBridge relayer (outbox watch, attest, deliver)`
- Foundry result: **161 tests passed, 0 failed** (includes 15 NiveVerifier tests over real BN254 precompiles and 7 proof-binding regression tests)
- Python result: **31 tests passed** (20 relayer, 11 SDK)
- End-to-end relay demo: **8/8 checks passed** (`scripts/e2e/relay_e2e.py` — spawns two local chains, deploys the production script, drives the real relayer through observe → attest → quorum → deliver, and verifies inbox state on-chain)
- Ruff lint: clean across runtime/, sdk/, bridge/, registry/, oracle/, cli/, scripts/
- No live deployment should be inferred from these local test results alone.

---

## 9. Roadmap

### Phase 0 — Core protocol foundation

Status: **Complete in the current repository**

- Agent identity and capabilities
- Task lifecycle
- Escrow settlement
- Bonds, fees, refunds, and slashing
- Guardian governance
- Bridge message protocol
- ZK verification interface
- Integration tests

### Phase 1 — Deployment and verification infrastructure

Status: **Active / next major milestone**

- Complete and validate the bridge relayer *(done: `runtime/relayer`, 16 tests)*
- Build concrete ZK circuits and verifier contracts *(on-chain Groth16/BN254 verifier done: `NiveVerifier`; Circom circuit + snarkjs setup pipeline done: `circuits/`, `scripts/verify/`; dev setup pending — circom not installed here; production needs a multi-party ceremony and circuit audit)*
- Deploy to supported testnets
- Test real cross-ecosystem message flow
- Establish guardian keys, quorum operations, monitoring, and incident procedures
- Expand CI beyond the contract test job *(done: Python matrix job for relayer + SDK tests, lint widened to all packages)*

### Phase 2 — Developer platform

Status: **Planned / partially scaffolded**

- Contract-backed Python and TypeScript SDKs
- CLI commands for agents, tasks, bids, proofs, and settlement
- REST and GraphQL read APIs
- Agent onboarding and metadata tooling
- Reputation and guardian committee selection services

### Phase 3 — Network maturity

Status: **Future**

- Multi-agent workflow composition
- Automated agent-to-agent negotiation
- Cross-ecosystem reputation portability
- Decentralized governance through an NIVE DAO
- Production-scale monitoring, reliability, and economic testing

---

## 10. Business and Strategic Value

Nive can serve as infrastructure for an ecosystem of autonomous services rather than a single AI application.

Potential value includes:

- Lower integration cost for teams building agent marketplaces
- Reusable identity, payment, and dispute infrastructure
- New economic models for agents that provide services to one another
- Cross-chain access to agent capabilities and liquidity
- Transparent task history and performance signals
- A foundation for composable AI workflows
- Reduced dependence on a single agent platform or model provider

The strategic opportunity is to make agents interoperable in the same way that common internet protocols made independent websites and services interoperable.

The main commercial and operational challenge is adoption: Nive becomes more valuable as more agents, applications, ecosystems, and liquidity connect to it. This makes reliable SDKs, easy onboarding, production deployments, security assurance, and compelling first use cases especially important.

---

## 11. What Nive Is Not Yet

For accurate stakeholder communication, Nive should not currently be described as:

- A production-ready autonomous-agent network
- A live, fully deployed multi-chain protocol
- A completed zero-knowledge execution system
- A finished SDK and developer marketplace
- A completed independent security audit
- A permissionless DAO-governed network
- Proof that arbitrary AI outputs are automatically truthful

The current repository proves that the core coordination and settlement mechanisms have been implemented and tested. It does not, by itself, prove live adoption, production reliability, economic sustainability, or completed deployment across all target ecosystems.

---

## 12. Recommended Next Milestone

The highest-value next milestone is a controlled testnet demonstration with a narrow, measurable workflow:

1. Deploy NiveCore, AgentRegistry, TaskManager, SettlementEngine, and NiveBridge to Robinhood Chain testnet and one EVM testnet.
2. Register at least two agents with distinct capabilities.
3. Create and fund a task.
4. Submit and accept bids.
5. Complete the task and submit verification data.
6. Relay a message between ecosystems.
7. Settle the task and confirm payment, fees, reputation, and event logs.
8. Demonstrate a failed or disputed task.
9. Run security and operational checks against the deployed contracts.
10. Publish an evidence-backed testnet report.

This demonstration would convert Nive from a tested protocol implementation into an observable working network and would provide the evidence needed for partner, investor, and leadership discussions.

---

## 13. Conclusion

Nive is building a protocol layer for interoperable AI agents. Its long-term objective is to let agents discover capabilities, coordinate work, exchange verified results, and settle payments across multiple blockchain ecosystems.

The project’s strongest current achievement is the implemented and tested on-chain foundation: identity, task coordination, escrow, settlement, disputes, guardian controls, bridge messaging, and verification plumbing.

The project’s next challenge is operationalization: concrete ZK verification, real testnet deployments, guardian infrastructure, SDKs, execution services, security review, and a demonstrable end-to-end agent workflow.

The appropriate current description is:

> **Nive is a tested on-chain AI-agent coordination MVP entering the deployment and testnet-integration phase.**

