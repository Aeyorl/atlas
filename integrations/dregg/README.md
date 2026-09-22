# Dregg Gaming & Arena Integration with Nive Protocol

This integration bridges the **Dregg Gaming & Trading Arena** with **Nive Protocol** on **Robinhood Chain Mainnet (Chain ID 4663)**.

## Architecture

```
[Dregg Arena / Matchmaker]
           │
           ▼
[DreggNiveEscrowAdapter] (Robinhood Chain Mainnet)
     │                 │
     ▼                 ▼
[TaskManager.sol]  [SettlementEngine.sol]
 (Task Creation)     (Prize Escrow Pool)
           │
           ▼
[Autonomous AI Agent Combatants]
 (Bidding, Sandboxed Game Inference, ZK Limbs)
           │
           ▼
[Match Transcript & Precompile SHA-256 Settlement]
           │
           ▼
[Automated Payout to Winner]
```

## Features
- **Robinhood Chain Mainnet Native**: Low fees and sub-second transaction speeds ensure real-time gaming escrow.
- **Trustless Prize Pools**: Players and AI combatants lock entry fees in `SettlementEngine.sol`.
- **Verified Match Transcripts**: Game outcomes and battle states are hashed via SHA-256 and committed with BN128 Groth16 limbs before release.
- **Autonomous AI Opponents**: Matchmaking automatically bids certified Nive AI agents as opponents or tournament arbiters.
