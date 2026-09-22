#!/usr/bin/env node
/**
 * Generates valid circuit input.json for nive-execution.circom.
 *
 * Usage:
 *   node prepare-input.mjs <task-id-hex> <preimage-string-or-hex> [output-path]
 *
 * Example:
 *   node prepare-input.mjs 0x1234... "sample task output" ./input.json
 */
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";

function hexToBigInt(hex) {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  return BigInt("0x" + clean);
}

function splitBytes32ToLimbs(hex32) {
  const clean = hex32.startsWith("0x") ? hex32.slice(2) : hex32;
  const padded = clean.padStart(64, "0");
  const lowHex = padded.slice(0, 32);
  const highHex = padded.slice(32, 64);
  return {
    lo: BigInt("0x" + lowHex).toString(),
    hi: BigInt("0x" + highHex).toString(),
  };
}

function parsePreimage(raw) {
  if (raw.startsWith("0x")) {
    return Buffer.from(raw.slice(2), "hex");
  }
  return Buffer.from(raw, "utf-8");
}

function main() {
  const [,, taskIdArg, preimageArg, outPath] = process.argv;

  if (!taskIdArg || !preimageArg) {
    console.log("Usage: node prepare-input.mjs <taskIdHex> <preimageTextOrHex> [outPath]");
    process.exit(1);
  }

  const rawBytes = parsePreimage(preimageArg);
  const preimageLen = rawBytes.length;

  // Capacity is 32 bytes (8 limbs * 4 bytes)
  const capacity = 32;
  const padded = Buffer.alloc(capacity);
  rawBytes.copy(padded, 0, 0, Math.min(rawBytes.length, capacity));

  // Compute 8 32-bit limbs (LSB-first / little-endian uint32 per limb)
  const limbs = [];
  for (let i = 0; i < 8; i++) {
    const val = padded.readUInt32LE(i * 4);
    limbs.push(val.toString());
  }

  // SHA256 of padded buffer
  const hash = createHash("sha256").update(padded).digest("hex");
  const resultLimbs = splitBytes32ToLimbs(hash);
  const taskLimbs = splitBytes32ToLimbs(taskIdArg);

  const circuitInput = {
    taskIdLo: taskLimbs.lo,
    taskIdHi: taskLimbs.hi,
    resultLo: resultLimbs.lo,
    resultHi: resultLimbs.hi,
    preimageLen: preimageLen,
    preimage: limbs,
  };

  const formatted = JSON.stringify(circuitInput, null, 2) + "\n";
  if (outPath) {
    writeFileSync(outPath, formatted);
    console.log(`Saved circuit input to ${outPath}`);
  } else {
    console.log(formatted);
  }
}

main();
