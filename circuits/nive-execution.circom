pragma circom 2.1.6;

include "node_modules/circomlib/circuits/sha256/sha256.circom";
include "node_modules/circomlib/circuits/bitify.circom";
include "node_modules/circomlib/circuits/comparators.circom";

/// @title nive-execution — Nive execution-proof circuit (V1)
/// @notice Proves that the agent knows a secret execution preimage whose
///         SHA-256 digest equals the result commitment recorded on-chain —
///         without revealing the preimage (the private execution transcript).
///
/// @dev Public inputs — canonical limb binding, MUST match
///      SettlementEngine._verifyProof exactly:
///
///        taskIdLo  : low 128 bits of the on-chain task id
///        taskIdHi  : high 128 bits of the on-chain task id
///        resultLo  : low 128 bits of keccak256(result)
///        resultHi  : high 128 bits of keccak256(result)
///
///      All four are < 2^128 < r, so Groth16 scalar reduction never mangles
///      them. The task/result limbs become part of the proof statement via
///      the IC commitment, so a proof generated for one (task, result) pair
///      verifies against no other pair. Settlement additionally reconstructs
///      the exact 256-bit id/hash on-chain before accepting a proof.
///
///      Statement constrained in-circuit:
///        1. SHA-256(preimage) == (resultHi << 128) | resultLo
///        2. taskIdLo + taskIdHi != 0        (the zero id is invalid on-chain)
///        3. 0 < preimageLen < LIMBS * 4     (well-formed transcript length)
///
///      Note on what V1 does NOT prove: the preimage is not yet tied to the
///      task parameters inside the circuit — statement binding of task to
///      result happens through the IC commitment plus the on-chain limb
///      reconstruction. A future revision can add a parametersHash public
///      input constrained against the transcript for full in-circuit binding.
///
///      Private inputs:
///        preimageLen          : byte length of the transcript
///        preimage[LIMBS]      : transcript packed as 32-bit limbs (LIMBS * 4 bytes)
///                               (LSB-first bit order per circomlib)
template NiveExecution(LIMBS) {
    signal input taskIdLo;              // public
    signal input taskIdHi;              // public
    signal input resultLo;              // public
    signal input resultHi;              // public
    signal input preimageLen;
    signal input preimage[LIMBS];       // 32-bit limbs (LIMBS * 4 bytes capacity)

    // -- Constraint 1: task id nonzero --------------------------------
    signal taskSum;
    taskSum <== taskIdLo + taskIdHi;
    component taskNonzero = IsZero();
    taskNonzero.in <== taskSum;
    taskNonzero.out === 0;

    // -- Constraint 2: 0 < preimageLen < LIMBS * 4 --------------------
    component lenLtMax = LessThan(32);
    lenLtMax.in[0] <== preimageLen;
    lenLtMax.in[1] <== LIMBS * 4;
    lenLtMax.out === 1;

    component lenGtZero = LessThan(32);
    lenGtZero.in[0] <== 1;
    lenGtZero.in[1] <== preimageLen;
    lenGtZero.out === 1;

    // -- Constraint 3: SHA-256(preimage) == result commitment ---------
    // Unpack each 32-bit limb to bits (LSB-first per circomlib Num2Bits)
    // and concatenate into the message bitstream.
    signal msgBits[LIMBS * 4 * 8];
    component limbToBits[LIMBS];
    for (var i = 0; i < LIMBS; i++) {
        limbToBits[i] = Num2Bits(32);
        limbToBits[i].in <== preimage[i];
        for (var b = 0; b < 32; b++) {
            msgBits[i * 32 + b] <== limbToBits[i].out[b];
        }
    }

    // SHA256(n) hashes an n-BYTE message; the bitstream is the message.
    component sha = SHA256(LIMBS * 4);
    sha.in <== msgBits;

    // Digest halves. circomlib SHA256 emits the digest as 256 bits; split
    // into two 128-bit halves with Bits2Num and compare against the public
    // limbs. (Verify bit order against the reference test vector in
    // circuits/test-vectors/ before running a production trusted setup.)
    component digestLo = Bits2Num(128);
    component digestHi = Bits2Num(128);
    for (var b = 0; b < 128; b++) {
        digestLo.in[b] <== sha.out[b];
        digestHi.in[b] <== sha.out[b + 128];
    }
    digestLo.out === resultLo;
    digestHi.out === resultHi;
}

// 8 limbs x 4 bytes = 32-byte transcript capacity for V1.
// Increase LIMBS for longer transcripts (cost grows with the SHA-256
// permutation count: one block per 64 bytes of message).
component main {public [taskIdLo, taskIdHi, resultLo, resultHi]} = NiveExecution(8);
