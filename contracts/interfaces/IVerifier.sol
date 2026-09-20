// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IVerifier
/// @notice Generic ZK proof verification interface for the Nive Verifier.
/// @dev Implementations wrap a concrete proof system — Groth16 (Circom) per
///      the architecture docs, with PLONK/STARK wrappers possible later.
///      The {SettlementEngine} calls this through `staticcall`, so compliant
///      implementations must be side-effect free.
interface IVerifier {
    /// @notice Verify a proof against its public inputs.
    /// @param proof         Proof-system-specific witness data (opaque here).
    /// @param publicInputs  Public inputs the statement commits to.
    ///      Convention: `publicInputs[0]` is the task id the proof was
    ///      generated for — the settlement engine uses it to bind proofs to
    ///      tasks so a proof can never be replayed across tasks.
    /// @return valid True when the proof verifies.
    function verifyProof(bytes calldata proof, uint256[] calldata publicInputs)
        external
        view
        returns (bool valid);
}
