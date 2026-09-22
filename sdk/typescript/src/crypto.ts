/**
 * Pure TypeScript cryptographic primitives & ZK limb encoding for Nive Protocol.
 * Zero external dependencies.
 */
import { createHash } from "node:crypto";

const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808an, 0x8000000080008000n,
  0x000000000000808bn, 0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n,
  0x000000000000008an, 0x0000000000000088n, 0x0000000080008009n, 0x000000008000000an,
  0x000000008000808bn, 0x800000000000008bn, 0x8000000000008089n, 0x8000000000008003n,
  0x8000000000008002n, 0x8000000000000080n, 0x000000000000800an, 0x800000008000000an,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
];

const ROT = [
  [0, 36, 3, 41, 18],
  [1, 44, 10, 45, 2],
  [62, 6, 43, 15, 61],
  [28, 55, 25, 21, 56],
  [27, 20, 39, 8, 14],
];

function rotl(x: bigint, n: number): bigint {
  const shift = BigInt(n % 64);
  return ((x << shift) | (x >> (64n - shift))) & 0xffffffffffffffffn;
}

/**
 * Pure JavaScript Keccak-256 (Ethereum variant).
 */
export function keccak256(data: Uint8Array | string): string {
  const buf = typeof data === "string" ? Buffer.from(data, "utf-8") : Buffer.from(data);
  const rate = 136;
  const padLen = (rate - ((buf.length + 1) % rate)) % rate;
  const padded = Buffer.concat([buf, Buffer.from([0x01]), Buffer.alloc(padLen)]);
  padded[padded.length - 1] |= 0x80;

  const lanes = new Array<bigint>(25).fill(0n);
  for (let b = 0; b < padded.length; b += rate) {
    for (let i = 0; i < rate / 8; i++) {
      lanes[i] ^= padded.readBigUInt64LE(b + i * 8);
    }
    for (let rnd = 0; rnd < 24; rnd++) {
      const c = new Array<bigint>(5);
      for (let x = 0; x < 5; x++) {
        c[x] = lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20];
      }
      const d = new Array<bigint>(5);
      for (let x = 0; x < 5; x++) {
        d[x] = c[(x + 4) % 5] ^ rotl(c[(x + 1) % 5], 1);
      }
      for (let x = 0; x < 5; x++) {
        for (let y = 0; y < 5; y++) {
          lanes[x + 5 * y] ^= d[x];
        }
      }
      const bArr = new Array<bigint>(25).fill(0n);
      for (let x = 0; x < 5; x++) {
        for (let y = 0; y < 5; y++) {
          bArr[y + 5 * ((2 * x + 3 * y) % 5)] = rotl(lanes[x + 5 * y], ROT[x][y]);
        }
      }
      for (let x = 0; x < 5; x++) {
        for (let y = 0; y < 5; y++) {
          lanes[x + 5 * y] =
            bArr[x + 5 * y] ^ (~bArr[(x + 1) % 5 + 5 * y] & bArr[(x + 2) % 5 + 5 * y]);
        }
      }
      lanes[0] ^= RC[rnd];
    }
  }

  const out = Buffer.alloc(32);
  for (let i = 0; i < 4; i++) {
    out.writeBigUInt64LE(lanes[i], i * 8);
  }
  return "0x" + out.toString("hex");
}

/**
 * Standard SHA-256 digest matching TaskManager on-chain precompile 0x02.
 */
export function sha256(data: Uint8Array | string): string {
  const buf = typeof data === "string" ? Buffer.from(data, "utf-8") : Buffer.from(data);
  return "0x" + createHash("sha256").update(buf).digest("hex");
}

/**
 * UTF-8 capability text as a 0x-prefixed 32-byte hex word (right-padded with zeros).
 */
export function capabilityWord(text: string): string {
  const buf = Buffer.from(text, "utf-8");
  if (buf.length > 32) {
    throw new Error(`capability text too long (max 32 bytes): ${text}`);
  }
  const padded = Buffer.alloc(32);
  buf.copy(padded, 0);
  return "0x" + padded.toString("hex");
}

/**
 * Deterministic bytes32 ID derived from a seed string.
 */
export function idFromSeed(seed: string): string {
  return keccak256(seed);
}

/**
 * Split a 256-bit word into canonical (lo_128, hi_128) BigInt limbs.
 * Satisfies on-chain condition: (hi << 128) | lo == word
 */
export function splitBytes32ToLimbs(hexOrBytes: string | Uint8Array): [bigint, bigint] {
  let hex: string;
  if (typeof hexOrBytes === "string") {
    hex = hexOrBytes.replace(/^0x/, "").padStart(64, "0");
  } else {
    hex = Buffer.from(hexOrBytes).toString("hex").padStart(64, "0");
  }
  const val = BigInt("0x" + hex);
  const mask128 = (1n << 128n) - 1n;
  const lo = val & mask128;
  const hi = val >> 128n;
  return [lo, hi];
}

/**
 * Compute canonical public input limbs: [taskIdLo, taskIdHi (, resultLo, resultHi)].
 */
export function computeVerificationLimbs(
  taskId: string | Uint8Array,
  resultHash?: string | Uint8Array,
): bigint[] {
  const [taskLo, taskHi] = splitBytes32ToLimbs(taskId);
  const limbs: bigint[] = [taskLo, taskHi];
  if (resultHash !== undefined) {
    const [resLo, resHi] = splitBytes32ToLimbs(resultHash);
    limbs.push(resLo, resHi);
  }
  return limbs;
}

/**
 * ABI encode (bytes proof, uint256[] publicInputs) matching SettlementEngine._verifyProof.
 */
export function encodeZkVerification(
  proof: Uint8Array | string,
  publicInputs: bigint[],
): string {
  const proofBuf = typeof proof === "string" ? Buffer.from(proof.replace(/^0x/, ""), "hex") : Buffer.from(proof);
  const proofPad = (32 - (proofBuf.length % 32)) % 32;
  const proofLenBuf = Buffer.alloc(32);
  proofLenBuf.writeBigUInt64BE(BigInt(proofBuf.length), 24);

  const encodedProof = Buffer.concat([
    proofLenBuf,
    proofBuf,
    Buffer.alloc(proofPad),
  ]);

  const offset0 = Buffer.alloc(32);
  offset0.writeBigUInt64BE(64n, 24);

  const offset1 = Buffer.alloc(32);
  offset1.writeBigUInt64BE(BigInt(64 + encodedProof.length), 24);

  const inputsCountBuf = Buffer.alloc(32);
  inputsCountBuf.writeBigUInt64BE(BigInt(publicInputs.length), 24);

  const inputWords = publicInputs.map((val) => {
    const word = Buffer.alloc(32);
    let rem = val;
    for (let i = 31; i >= 0; i--) {
      word[i] = Number(rem & 0xffn);
      rem >>= 8n;
    }
    return word;
  });

  const encodedInputs = Buffer.concat([inputsCountBuf, ...inputWords]);
  const finalBuf = Buffer.concat([offset0, offset1, encodedProof, encodedInputs]);
  return "0x" + finalBuf.toString("hex");
}
