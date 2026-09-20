#!/usr/bin/env bash
# Groth16 setup pipeline for the Nive execution-proof circuit.
#
# Prerequisites:
#   node >= 18
#   circom 2.1.x  (https://docs.circom.io/getting-started/installation/)
#   circomlib     -> cd circuits && npm i circomlib
#
# Usage:
#   ./scripts/verify/setup-circuit.sh [log2-powers-of-tau]
#
# Default: 12 (2^12 = 4096 constraint slots; NiveExecution(8) fits well
# within this). For larger LIMBS, bump the size accordingly.
set -euo pipefail

PTAU_LOG2="${1:-12}"
CIRCUITS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../circuits" && pwd)"
BUILD_DIR="$CIRCUITS_DIR/build/nive-execution"
CIRCUIT="$CIRCUITS_DIR/nive-execution.circom"
SEED="${NIVE_PTAU_SEED:-nive-v1-deterministic-seed}"

echo "==> [1/6] Compiling circuit"
mkdir -p "$BUILD_DIR"
circom "$CIRCUIT" --wasm --r1cs -o "$BUILD_DIR"

echo "==> [2/6] Downloading powers-of-tau ceremony file (2^$PTAU_LOG2)"
PTAU="$BUILD_DIR/pot${PTAU_LOG2}_0000.ptau"
if [ ! -f "$PTAU" ]; then
  snarkjs powersoftau new bn128 "$PTAU_LOG2" "$PTAU" -v
  echo "    Contributing entropy (deterministic dev seed: '$SEED')"
  echo "    *** PRODUCTION: use a MULTI-PARTY ceremony instead of this step ***"
  echo "$SEED" | snarkjs powersoftau contribute bn128 "$PTAU" "$PTAU" --name="nive-v1 dev contribution" -v
  snarkjs powersoftau prepare phase2 "$PTAU" "$PTAU" -v
fi

echo "==> [3/6] Groth16 setup (zkey)"
ZKEY="$BUILD_DIR/nive-execution.zkey"
snarkjs groth16 setup "$BUILD_DIR/nive-execution.r1cs" "$PTAU" "$ZKEY"

echo "==> [4/6] Contributing to the zkey (dev contribution)"
ZKEY_FINAL="$BUILD_DIR/nive-execution-final.zkey"
echo "$SEED" | snarkjs zkey contribute "$ZKEY" "$ZKEY_FINAL" --name="nive-v1 dev" -v
snarkjs zkey verify "$BUILD_DIR/nive-execution.r1cs" "$PTAU" "$ZKEY_FINAL"

echo "==> [5/6] Exporting verification key (JSON + Nive flat format)"
VK_JSON="$BUILD_DIR/nive-execution-vk.json"
snarkjs zkey export verificationkey "$ZKEY_FINAL" "$VK_JSON"

node "$CIRCUITS_DIR/export-vk.mjs" "$VK_JSON" "$BUILD_DIR/nive-execution-vk-nive.json"
echo "    Nive VK:      $BUILD_DIR/nive-execution-vk-nive.json"
echo "    Feed to deploy: NIVE_VK_JSON=$BUILD_DIR/nive-execution-vk-nive.json"

echo "==> [6/6] Generating a sample proof (smoke test)"
if [ -f "$CIRCUITS_DIR/test-vectors/input.json" ]; then
  (cd "$BUILD_DIR" && node nive-execution_js/generate_witness.js \
    nive-execution_js/nive-execution.wasm \
    "$CIRCUITS_DIR/test-vectors/input.json" \
    "$BUILD_DIR/witness.wtns")
  snarkjs groth16 prove "$ZKEY_FINAL" "$BUILD_DIR/witness.wtns" \
    "$BUILD_DIR/proof.json" "$BUILD_DIR/public.json"
  snarkjs groth16 verify "$VK_JSON" "$BUILD_DIR/public.json" "$BUILD_DIR/proof.json" \
    && echo "    Sample proof VERIFIED" \
    || { echo "    Sample proof FAILED"; exit 1; }
else
  echo "    (skipped: circuits/test-vectors/input.json not present)"
fi

echo "==> Done. Circuit artifacts in $BUILD_DIR"
