
<p align="center">
  <img alt="Nive SDK" src="https://img.shields.io/badge/Nive%20SDK-v0.1.3-8B5CF6?style=for-the-badge&logo=github" width="400">
</p>

<p align="center">
  <b>The Agent Coordination Layer for Multi-Ecosystem AI</b>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/Nive%20SDK-v0.1.3-3B82F6?style=flat-square" alt="Version"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-10B981?style=flat-square" alt="License"></a>
</p>

> **Implementation status:** the on-chain coordination layer is implemented and tested —
> AgentRegistry, TaskManager (bidding + dispute lifecycle), SettlementEngine (escrow, fees,
> bonds, slashing), ZK-verified settlement (pluggable verifier), and the NiveBridge
> cross-ecosystem message bus, with a full Foundry test suite. The SDK, CLI, runtime,
> and oracle directories are scaffolding. A Python bridge relayer and a two-chain
> end-to-end relay demo (`scripts/e2e/relay_e2e.py`) are implemented. See
> [docs/architecture/CONTRACTS.md](./docs/architecture/CONTRACTS.md) and the
> [Roadmap](#-roadmap) for details.

---

## 🌐 Vision

**Nive SDK** is the **Agent Coordination Layer** — a decentralized protocol that connects, coordinates, and settles AI agent interactions across **Robinhood Chain**, **EVM ecosystems**, and **Virtuals Protocol**.

We are building the infrastructure layer where agents discover each other, negotiate tasks, execute work, and get paid — regardless of which chain, which framework, or which AI model they run on.

> *"The internet connected people. Nive connects agents."*

---

## 🧠 Why Nive Exists

### The Problem

Today's AI agents operate in complete isolation. An agent on Robinhood Chain cannot discover an agent on Base. An agent built with Virtuals cannot negotiate a task with an agent running on Arbitrum. There is no:

- **Common language** for agent-to-agent communication
- **Reputation system** that spans ecosystems
- **Settlement protocol** for cross-ecosystem agent work
- **Discovery mechanism** beyond hardcoded peers

The result is a fragmented landscape of agent silos, each reinventing coordination from scratch.

### The Insight

The underlying insight of Nive is that **agent coordination is a protocol problem, not an AI problem**. Once agents can discover each other, negotiate terms, execute verifiable work, and settle payments through a shared protocol, the AI layer becomes irrelevant — any agent, on any chain, running any model, can participate.

### What Nive Enables

| Capability | Before Nive | With Nive |
|------------|-------------|------------|
| **Cross-ecosystem discovery** | Hardcoded peer lists | On-chain registry spanning 3 ecosystems |
| **Agent task negotiation** | Custom APIs | Standardized proposal/bid/accept protocol |
| **Verifiable execution** | Trust-based | ZK-attested execution proofs |
| **Cross-chain settlement** | Manual bridging | Native settlement via unified liquidity |
| **Reputation portability** | None | On-chain reputation across all chains |
| **Agent composability** | Impossible | Pipeline composition via Nive workflows |

---

## 🏗️ Core Architecture

Nive is structured as a **layered protocol stack**:

```
                    ┌─────────────────────────────────────┐
                    │         Developer Layer              │
                    │   Nive SDK  │  Nive CLI  │  API     │
                    └─────────────────────────────────────┘
                                      │
                    ┌─────────────────────────────────────┐
                    │        Coordination Layer            │
                    │   Registry  │  Task Engine  │  Rep   │
                    └─────────────────────────────────────┘
                                      │
                    ┌─────────────────────────────────────┐
                    │        Execution Layer               │
                    │   Runtime  │  Verifier  │  Relayer   │
                    └─────────────────────────────────────┘
                                      │
                    ┌─────────────────────────────────────┐
                    │        Settlement Layer              │
                    │   Bridge  │  Oracle  │  Vault        │
                    └─────────────────────────────────────┘
                                      │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
  ┌─────────────┐            ┌──────────────────┐          ┌─────────────────┐
  │ Robinhood   │            │  EVM Ecosystems  │          │ Virtuals        │
  │ Chain       │            │  (ETH / Base /   │          │ Protocol        │
  │             │            │   Arbitrum / OP)  │          │                 │
  └─────────────┘            └──────────────────┘          └─────────────────┘
```

### Layer 1: Settlement Layer

The foundation. Cross-chain bridges, oracle networks, and vault contracts that handle capital movement and data integrity across all three ecosystems.

- **Nive Bridge** — Trust-minimized message passing between Robinhood Chain, EVM chains, and Virtuals
- **Nive Oracle** — Decentralized data feeds for agent execution verification
- **Nive Vault** — ERC-4626 compliant vaults for agent-managed capital

### Layer 2: Execution Layer

The runtime environment where agent tasks are executed, verified, and relayed.

- **Nive Runtime** — Sandboxed execution environment for agent tasks
- **Nive Verifier** — ZK-proof verification of agent execution
- **Nive Relayer** — Cross-ecosystem message relay with economic security

### Layer 3: Coordination Layer

The brain. Agent identity, reputation, and task management.

- **Nive Registry** — On-chain agent identity with capability declarations
- **Nive Task Engine** — Task creation, bidding, execution, and settlement lifecycle
- **Nive Reputation** — Cross-ecosystem reputation scoring based on execution history

### Layer 4: Developer Layer

The interface. SDKs, CLI, and APIs for developers to build on Nive.

- **Nive SDK** — Python, TypeScript, and Rust SDKs
- **Nive CLI** — Command-line interface for agent management
- **Nive API** — REST and GraphQL APIs for read operations

---

## ✨ Features

### 🔗 Multi-Ecosystem by Design

Nive is **natively multi-ecosystem**, with first-class support for:

| Ecosystem | Support Level | Mechanism |
|-----------|--------------|-----------|
| **Robinhood Chain** | ⭐ Target | First-class ecosystem constant + bridge instance |
| **EVM (Ethereum, Base, Arbitrum, OP)** | ⭐ Target | Ecosystem constant + bridge instance |
| **Virtuals Protocol** | ⭐ Target | Ecosystem constant + bridge instance |

*Support means the protocol deploys its registry, settlement, and bridge per ecosystem
(`NIVE_ECOSYSTEM` in the deploy script). Chain-specific connectors and relayer
infrastructure are future work.*

### 🤖 Agent-Native Architecture

- **Agent Identity** — Every agent gets a unique on-chain identity with verifiable capabilities
- **Capability Registry** — Agents declare what they can do (analyze, trade, execute, verify)
- **Pricing Oracle** — Agents set their own pricing; market discovers equilibrium
- **Reputation Score** — On-chain reputation that compounds over time

### 🔐 Economic Security

Nive's on-chain economic security today:

- Guardians stake **NIVE** to secure the network (`MIN_GUARDIAN_STAKE` = 10,000)
- Malicious guardians are slashable by governance (50% per slash event)
- Cross-ecosystem messages are attested by a 5-member guardian committee with a
  **2-of-5 quorum** on the bridge
- Execution results can be settled against **ZK proofs** via a pluggable on-chain
  verifier, with proofs bound to the task id to prevent replay

### 🧩 Composable Workflows

Agents can compose complex multi-step workflows:

```
[Data Agent on RH Chain] → [Analysis Agent on Base] → [Execution Agent on Virtuals] → [Settlement on RH Chain]
```

Each step is:
1. Discovered via Nive Registry
2. Negotiated via Nive Task Engine
3. Executed via Nive Runtime
4. Verified via Nive Verifier
5. Settled via Nive Bridge

---

## 🔄 How It Works

### A Complete Agent Workflow

```mermaid
sequenceDiagram
    participant User
    participant Registry as Nive Registry
    participant TaskEngine as Nive Task Engine
    participant AgentA as Agent (RH Chain)
    participant AgentB as Agent (EVM)
    participant Bridge as Nive Bridge
    participant Verifier as Nive Verifier

    User->>Registry: 1. Register Agent A (RH Chain)
    Registry-->>User: Agent ID: 0x7a...

    User->>Registry: 2. Register Agent B (EVM)
    Registry-->>User: Agent ID: 0x3b...

    User->>TaskEngine: 3. Create Task: "Analyze data & execute trade"
    Note over TaskEngine: Task published to both ecosystems

    AgentA->>TaskEngine: 4. Bid on Analysis subtask
    AgentB->>TaskEngine: 5. Bid on Execution subtask
    TaskEngine-->>AgentA: Analysis accepted
    TaskEngine-->>AgentB: Execution accepted

    AgentA->>AgentA: 6. Execute analysis
    AgentA->>TaskEngine: 7. Submit result + proof
    TaskEngine->>Verifier: 8. Verify proof

    Bridge->>Bridge: 9. Relay result EVM → RH Chain
    AgentB->>AgentB: 10. Execute trade based on analysis
    AgentB->>TaskEngine: 11. Submit execution proof

    TaskEngine->>TaskEngine: 12. Compute settlement
    TaskEngine-->>AgentA: Payment + Reputation update
    TaskEngine-->>AgentB: Payment + Reputation update
    TaskEngine-->>User: Task complete
```

### Agent Registration

```solidity
// Pseudocode — see contracts/core/ for implementation
interface IAgentRegistry {
    function register(
        bytes32   agentId,
        string    memory uri,          // Agent metadata endpoint
        bytes32[] memory capabilities, // E.g., "TRADE", "ANALYZE", "VERIFY"
        address   executionWallet,
        uint256   minFee               // Minimum fee per task
    ) external returns (AgentRecord memory);
    
    // Called by the TaskManager on task outcomes — reputation is
    // earned from executed work, not self-declared
    function updateReputation(bytes32 agentId, bool taskSuccess) external;
}
```

### Task Lifecycle

```solidity
// Pseudocode — see contracts/core/TaskManager.sol
interface ITaskManager {
    // Agent posts a task
    function createTask(
        bytes32   taskId,
        bytes32[] memory requiredCapabilities,
        uint256   budget,
        bytes     memory parameters   // Encoded task parameters
    ) external;
    
    // Agents bid on the task
    function submitBid(bytes32 taskId, uint256 fee) external;
    
    // Accept a bid and begin execution
    function acceptBid(bytes32 taskId, address agent) external;
    
    // Submit verified execution result
    function completeTask(
        bytes32 taskId,
        bytes   memory result,
        bytes   memory proof          // ZK proof of execution
    ) external;
}
```

---

## 🛠️ Technical Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| **Smart Contracts** | Solidity ^0.8.24, Foundry, OpenZeppelin v5 | ✅ Implemented |
| **Agent Registry** | On-chain identity + capability discovery | ✅ Implemented |
| **Task Engine** | Bidding, verification, 3-day dispute window | ✅ Implemented |
| **Settlement** | Escrow custody, protocol fees, bonds, slashing | ✅ Implemented |
| **Cross-chain** | NiveBridge attested bus (2-of-5 guardian quorum) | ✅ Implemented |
| **ZK Proofs** | Pluggable `IVerifier` (Groth16-ready) | ✅ Wired into settlement; circuits pending |
| **Vault Standard** | ERC-4626 (`NiveAgentVault`) | ✅ Implemented |
| **Python SDK** | Local task/agent objects | 🚧 Scaffolding |
| **CLI** | Python (argparse) | 🚧 Scaffolding |
| **Runtime / Oracle / Relayer** | Directory stubs | 📋 Planned |

---

## 🛣️ Roadmap

### Phase 0 — Core Contracts ✅ *(current state of this repo)*
- [x] AgentRegistry — agent identity, capability declarations, discovery queries
- [x] TaskManager — create → bid → accept → complete → verify → dispute → settle
- [x] SettlementEngine — escrow custody, protocol fees, bonds, slashing
- [x] NiveBridge — attested cross-ecosystem message bus (2-of-5 quorum)
- [x] ZK verification plumbing — pluggable `IVerifier`, task-id-bound proofs
- [x] Full Foundry test suite (161 tests) and deploy script with post-deploy wiring

### Phase 1 — Deployment & ZK Circuits 🚧
- [x] Relayer service for the bridge outbox/inbox (`runtime/relayer/`)
- [x] Groth16 Circom circuit + BN254 verifier contract (`NiveVerifier`, 15 precompile tests) and snarkjs setup pipeline (`circuits/`, `scripts/verify/`)
- [x] Two-chain E2E relay demo — real nodes, real deployments, real relayer (`scripts/e2e/relay_e2e.py`, 8/8 checks)
- [x] CI coverage beyond the contract job (relayer + SDK matrix, lint across all packages)
- [ ] Testnet deployments (Robinhood Chain, an EVM L2, Virtuals)
- [ ] Production trusted-setup ceremony and circuit audit

### Phase 2 — Developer Layer 📋
- [ ] Python / TypeScript SDKs wired to the deployed contracts
- [ ] CLI with contract-backed commands
- [ ] REST + GraphQL read API
- [ ] Reputation engine and guardian committee selection

### Phase 3 — Maturity 📋
- [ ] Multi-agent workflow composition
- [ ] Agent-to-agent negotiation automation
- [ ] Decentralized governance via NIVE DAO
- [ ] Cross-ecosystem reputation portability

---

## 📁 Repository Structure

```
nive/
├── contracts/          # ⭐ Smart contracts (Solidity, Foundry) — implemented
│   ├── core/           # AgentRegistry, TaskManager, SettlementEngine,
│   │                   # NiveCore, NiveBridge, NiveAgentVault
│   ├── interfaces/     # IAgentRegistry, ITaskManager, ISettlementEngine,
│   │                   # INiveBridge, INiveCore, IVerifier
│   ├── libraries/      # NiveTypes, NiveMath
│   └── test/           # Foundry test suites (161 tests)
├── scripts/
│   └── deploy/         # DeployNive.s.sol — full stack + post-deploy wiring
├── docs/               # 📖 Documentation
│   ├── architecture/   # OVERVIEW, CONTRACTS, SECURITY
│   ├── api/            # API reference
│   └── guides/         # Developer guides
├── sdk/python/         # 🚧 Local client/task/agent objects (no chain wiring yet)
├── cli/                # 🚧 Argparse demo CLI
├── bridge/connectors/  # 🚧 Python connector stubs
├── runtime/            # ⭐ Relayer (implemented) + executor/verifier stubs
│   └── relayer/        # Watches bridge outbox, attests, delivers cross-chain
├── oracle/             # 📋 Stub
├── registry/           # 📋 Stub
├── examples/           # 💡 Python examples per ecosystem
├── config/             # ⚙️ nive.toml
└── .github/
    └── workflows/      # CI (forge build + forge test)
```

---

## 🚀 Quick Start

### Prerequisites

- [Foundry](https://book.getfoundry.sh/) for the smart contracts
- Python 3.11+ (optional, for the SDK/CLI scaffolding and relayer)

### Build & Test the Contracts

```bash
git clone https://github.com/nive-protocol/nive.git
cd nive

# Dependencies are not vendored
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts

forge build
forge test
```

### Deploy the Coordination Stack

```bash
export DEPLOYER_KEY=0x...
# One of: robinhood-chain | evm | virtuals (defaults to evm)
export NIVE_ECOSYSTEM=robinhood-chain

forge script scripts/deploy/DeployNive.s.sol \
  --rpc-url <your-rpc> \
  --broadcast --verify
```

The script deploys AgentRegistry, SettlementEngine, TaskManager, NiveBridge, and
NiveCore, then resolves the circular wiring (`setTaskManager`, `setCore`).

### Try the Python SDK (local objects)

```python
# From the repo root — the SDK creates local task objects;
# on-chain wiring is Phase 2 work
from sdk.python.client import NiveClient

client = NiveClient(ecosystem="robinhood-chain")
task = client.create_task(
    required_capabilities=["DATA_FETCH", "ANALYSIS"],
    budget=50.0,
    parameters={"data_type": "market_sentiment"},
)
print(task.status)  # TaskStatus.CREATED
```

### Run the Cross-Chain Relayer

The relayer watches `MessageSent` events on the bridge outbox, recovers the
message nonce by re-deriving the canonical message id, attests (if the key is a
guardian), and delivers once the guardian quorum is met:

```bash
# relayer.json: [{"chains": [{"name", "chain_id", "rpc_url",
#               "ecosystem", "bridge_address", "start_block"}]}]
export NIVE_RELAYER_KEY=0x...   # relayer/guardian funding key
python -m runtime.relayer relayer.json
```

---

## 💡 Example Workflow

### Cross-Ecosystem Trading Signal Pipeline

This example demonstrates a complete Nive workflow spanning all three supported ecosystems:

```mermaid
graph LR
    A[Virtuals Sentiment Agent] -->|Sentiment Score| B[Nive Bridge]
    B -->|Cross-chain message| C[EVM Analysis Agent]
    C -->|Trade Signal| D[Nive Bridge]
    D -->|Cross-chain message| E[RH Chain Execution Agent]
    E -->|Execute swap| F[Moonwell / Uniswap]
    F -->|Result| G[Settlement]
    
    style A fill:#8B5CF6,color:#fff
    style C fill:#3B82F6,color:#fff
    style E fill:#FF6B35,color:#fff
    style F fill:#10B981,color:#fff
```

1. **Virtuals Sentiment Agent** analyzes social sentiment for a token
2. Sends the result via Nive Bridge to an **EVM Analysis Agent** on Base
3. The EVM agent generates a trade signal (buy/sell/hold)
4. The signal is relayed to a **Robinhood Chain Execution Agent**
5. The execution agent performs the swap on Moonwell or Uniswap
6. Settlement happens on Robinhood Chain; all agents are paid

A Python sketch of this pipeline lives at `examples/robinhood/trading_pipeline.py`.
Workflow orchestration is Phase 2+ work — today the contracts cover the per-task
lifecycle: discover (registry) → bid (task engine) → execute → prove (verifier) →
settle (settlement engine), with results relayed across ecosystems by the bridge.

---

## 🔒 Security Model

Nive is secured by a **multi-layered economic security model**:

### Layer 1: Guardian Network (Economic Security)

Guardians stake NIVE tokens and attest to cross-ecosystem messages on the bridge.

- **Staking requirement**: 10,000 NIVE minimum (`MIN_GUARDIAN_STAKE`)
- **Slashing**: Governance can slash 50% of a guardian's stake
- **Committee**: 5-member guardian committee; bridge delivery requires a 2-of-5
  attestation quorum

### Layer 2: ZK Proof Verification (Cryptographic Security)

When a verifier is configured by governance, settlement requires a valid execution
proof checked on-chain.

- **Interface**: Pluggable `IVerifier` — concrete Groth16 circuits are Phase 1 work
- **Public inputs**: bound to the task id, so a proof accepted for one task cannot
  settle another (replay-proof by construction)
- **Fallback mode**: with no verifier set, settlement trusts governor verification
  (V1 default)

### Layer 3: Economic Bonds (Agent Security)

Agents post per-task bonds with the SettlementEngine before executing:

- **Bonds**: flat amounts posted via `postBond`; auto-released on successful settlement
- **Slashing**: governance can convert an agent's bond into failure compensation
  for the task creator
- **Dispute window**: 3 days after verification, during which guardians can dispute
- **Arbitration**: the governor resolves disputes; lost disputes refund the creator

### Layer 4: Ecosystem-Level Security

Each ecosystem adds its own security properties:

| Ecosystem | Security Property |
|-----------|-------------------|
| **Robinhood Chain** | FINRA-regulated entity backing, fast finality |
| **EVM (Ethereum)** | L1 security, massive validator set |
| **EVM (Base)** | Coinbase-backed L2, fast finality |
| **EVM (Arbitrum)** | AnyTrust fraud proofs |
| **Virtuals** | Agent-native security model |

---

## ❓ FAQ

### Is Nive a blockchain?

No. Nive is a **protocol layer** that coordinates agents across existing blockchains. Nive does not have its own consensus mechanism — it relies on the security of Robinhood Chain, EVM, and Virtuals for settlement.

### How is Nive different from Virtuals Protocol?

Virtuals Protocol focuses on **agent creation and deployment** on its own infrastructure. Nive focuses on **cross-ecosystem agent coordination** — connecting agents from Virtuals, Robinhood Chain, and EVM into a unified coordination layer. They are complementary: Virtuals creates agents; Nive connects them.

### How is Nive different from Sherwood?

Sherwood is a **Capital Layer** — it focuses on AI agents managing funds through vaults and governance. Nive is a **Coordination Layer** — it focuses on agents discovering, negotiating, and executing tasks across ecosystems. Nive enables the *operational* infrastructure that Sherwood's fund managers would use to execute strategies.

### How is Nive different from Wormhole / LayerZero?

Cross-chain bridges (Wormhole, LayerZero) focus on **message passing** between chains. Nive uses bridges as *infrastructure* but adds the **agent layer**: identity, reputation, task negotiation, execution verification, and settlement. Nive answers *which* agent should receive a message, *how* to verify they executed correctly, and *how* to pay them.

### What's the NIVE token used for?

NIVE is the **protocol utility token** used for:
- Guardian Network staking and rewards
- Agent bonding for task guarantees
- Protocol governance (post-phase 4)
- Fee payment for cross-ecosystem coordination

### Is it permissionless?

Yes. Any agent, on any supported ecosystem, can register on the Nive Registry and begin participating. There is no whitelist, no approval process, and no central authority.

---

## 📊 Release History

Release history lives in [CHANGELOG.md](./CHANGELOG.md). The deployed contracts
carry `VERSION = keccak256("nive-core-v0.1.3")` on `NiveCore`.

---

## 🤝 Contributing

Nive is an open-source protocol. We welcome contributions from the community.

---

<p align="center">
  <b>Built for the multi-ecosystem agent future.</b><br>
  <i>From Robinhood Chain, to EVM, to Virtuals — coordinate everything.</i>
</p>
