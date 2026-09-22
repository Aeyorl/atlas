#!/usr/bin/env bash
# Verifies a generated Groth16 proof using snarkjs against the circuit verification key.
#
# Usage:
#   ./scripts/verify/verify.sh [proof.json] [public.json] [vk.json]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$REPO_ROOT/circuits/build/nive-execution"

PROOF="${1:-$BUILD_DIR/proof.json}"
PUBLIC="${2:-$BUILD_DIR/public.json}"
VK="${3:-$BUILD_DIR/nive-execution-vk.json}"

if [ ! -f "$VK" ]; then
    echo "[-] Verification key not found at $VK"
    echo "    Run ./scripts/verify/setup-circuit.sh to compile circuit and export verification key."
    exit 1
fi

if [ ! -f "$PROOF" ] || [ ! -f "$PUBLIC" ]; then
    echo "[-] Proof or public inputs not found at $PROOF / $PUBLIC"
    echo "    Generate them with snarkjs groth16 prove or run the circuit test pipeline."
    exit 1
fi

echo "==> Verifying Groth16 execution proof with snarkjs..."
snarkjs groth16 verify "$VK" "$PUBLIC" "$PROOF"
echo "==> Proof successfully verified!"
