# Circuit test vectors

`input.json` is a deterministic witness for `nive-execution.circom` used by
`scripts/verify/setup-circuit.sh` step 6 (smoke test: prove + verify a sample
proof locally).

## Derivation (regenerate with these exact steps)

1. Choose the preimage: the ASCII bytes of `"nive-execution-v1-vector"` —
   24 bytes, zero-padded to the 32-byte circuit capacity (`preimageLen = 24`).
   - Split into 32-bit little-endian limbs (4 bytes per limb): limbs 0..5
     carry the 24 bytes, limbs 6..7 are zero (8 limbs total = 32 bytes).
2. `resultLo/Hi` = SHA-256 of that padded 32-byte buffer, split into
   (low 128 bits, high 128 bits) as decimal strings.
3. `taskIdLo/Hi` = the (lo, hi) 128-bit limbs of the keccak256 id
   `keccak256("nive-execution-v1-vector")`, as decimal strings.

Regenerate automatically using:
```bash
node circuits/prepare-input.mjs <taskIdHex> <preimage> circuits/test-vectors/input.json
```

IMPORTANT — bit-order check before production setup: circomlib's SHA-256
`out[i]` is LSB-first within each byte/word; confirm the digest split in the
circuit matches the derivation above by running the smoke test in
`setup-circuit.sh` and comparing `public.json` against this input. If the
digest halves are swapped, flip the `digestLo`/`digestHi` assembly in the
circuit.

These vectors are for local validation only; production requires a
multi-party trusted setup and an audited circuit.
