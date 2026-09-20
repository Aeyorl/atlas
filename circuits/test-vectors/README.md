# Circuit test vectors

`input.json` is a deterministic witness for `nive-execution.circom` used by
`scripts/verify/setup-circuit.sh` step 6 (smoke test: prove + verify a sample
proof locally).

## Derivation (regenerate with these exact steps)

1. Choose the preimage: the ASCII bytes of `"nive-execution-v1-vector"` —
   24 bytes, zero-padded to the 32-byte circuit capacity.
   - Split into 32-bit little-endian limbs: limbs 0..5 carry the bytes,
     limbs 6..31 are zero. `preimageLen = 32` (circuit capacity; note the
     circuit hashes the full padded buffer — the digest below includes the
     trailing zeros).
2. `resultLo/Hi` = SHA-256 of that padded 32-byte buffer, split into
   (low 128 bits, high 128 bits) as decimal strings.
3. `taskIdLo/Hi` = the (lo, hi) 128-bit limbs of the keccak256 id
   `keccak256("nive-execution-v1-vector")`, as decimal strings.

IMPORTANT — bit-order check before production setup: circomlib's SHA-256
`out[i]` is LSB-first within each byte/word; confirm the digest split in the
circuit matches the derivation above by running the smoke test in
`setup-circuit.sh` and comparing `public.json` against this input. If the
digest halves are swapped, flip the `digestLo`/`digestHi` assembly in the
circuit.

These vectors are for local validation only; production requires a
multi-party trusted setup and an audited circuit.
