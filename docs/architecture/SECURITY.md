# Atlas Protocol Security Model

## Multi-Layer Security

1. **Guardian Network** — guardians attest cross-ecosystem bridge messages;
   delivery requires a 2-of-5 committee quorum (`AtlasBridge.GUARDIAN_QUORUM`)
2. **ZK Proofs** — `IVerifier` hook in the settlement path for agent-execution
   proofs (concrete circuit + verifier contract pending)
3. **Economic Bonds** — per-task agent bonds held by the `SettlementEngine`
4. **Ecosystem Security** — RH Chain (FINRA), EVM (L1), Virtuals (native)

## Implementation Status

| Layer | Claimed | Actually implemented |
|---|---|---|
| Guardian attestations | 2-of-5 quorum on bridge delivery | ✅ enforced on-chain |
| Guardian stake custody | 10,000 ATLAS locked | ⚠️ stake is recorded, **not token-locked**; slashing is accounting-only |
| ZK verification | Groth16 proof of execution | ⚠️ interface hook only — settlement is governor-trust until a circuit + verifier land |
| Task bonds | 5% bond | ✅ posted/released via `SettlementEngine` |
| Dispute window | 24h time lock | ❌ not implemented — disputes resolve via governor calls |
| Bridge message integrity | tamper-evident ids | ✅ id binds (source, target, payload, sender, chainId, nonce) |

## Bridge Relayer Trust Model

The relayer (`runtime/relayer/`) is a **courier, not a trust root**:

- It observes `MessageSent` events and fetches the outbox record via
  `getOutboxMessage`; it then **re-derives the canonical message id** from the
  record. A mismatch quarantines the message instead of delivering it.
- Delivery on the target chain is accepted by `AtlasBridge.deliverMessage` only
  after `GUARDIAN_QUORUM` (2-of-5) guardian attestations — a malicious or
  compromised relayer cannot deliver unattested messages.
- The relayer may hold a guardian key to contribute its own `verifyMessage`
  vote; it still cannot reach quorum alone.
- Retry semantics: `deliverMessage` returning `false` (quorum unmet) is
  retried on a backoff, up to `delivery_max_attempts`, then marked `FAILED`.
