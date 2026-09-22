import test from "node:test";
import assert from "node:assert/strict";
import {
  keccak256,
  sha256,
  capabilityWord,
  idFromSeed,
  splitBytes32ToLimbs,
  computeVerificationLimbs,
  encodeZkVerification,
} from "../src/crypto.ts";
import { ChainClient } from "../src/chain.ts";

test("keccak256 computes standard Ethereum hash", () => {
  assert.equal(
    keccak256(""),
    "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
  );
  assert.equal(
    keccak256("TRADE"),
    "0xb9944e59ddc84a600b23d5b4175b22c79a7c9af66c0b2317ffb51bf4c8f60219"
  );
});

test("capabilityWord right-pads to 32 bytes hex", () => {
  const word = capabilityWord("TRADE");
  assert.equal(word.length, 66);
  assert.ok(word.startsWith("0x5452414445"));
  assert.throws(() => capabilityWord("x".repeat(33)), /too long/);
});

test("idFromSeed produces deterministic bytes32", () => {
  const id1 = idFromSeed("seed-1");
  const id2 = idFromSeed("seed-1");
  const id3 = idFromSeed("seed-2");
  assert.equal(id1, id2);
  assert.notEqual(id1, id3);
  assert.equal(id1.length, 66);
});

test("splitBytes32ToLimbs satisfies canonical on-chain reconstruction", () => {
  const word = "0x" + "11223344556677889900aabbccddeeff".repeat(2);
  const [lo, hi] = splitBytes32ToLimbs(word);

  const mask128 = (1n << 128n) - 1n;
  assert.ok(lo <= mask128, "lo exceeds uint128");
  assert.ok(hi <= mask128, "hi exceeds uint128");

  const reconstructed = (hi << 128n) | lo;
  assert.equal(reconstructed, BigInt(word));
});

test("computeVerificationLimbs creates 2 or 4 limbs", () => {
  const taskId = idFromSeed("task-1");
  const resHash = sha256("output-result");

  const limbs2 = computeVerificationLimbs(taskId);
  assert.equal(limbs2.length, 2);
  assert.equal((limbs2[1] << 128n) | limbs2[0], BigInt(taskId));

  const limbs4 = computeVerificationLimbs(taskId, resHash);
  assert.equal(limbs4.length, 4);
  assert.equal((limbs4[1] << 128n) | limbs4[0], BigInt(taskId));
  assert.equal((limbs4[3] << 128n) | limbs4[2], BigInt(resHash));
});

test("encodeZkVerification generates correct EVM ABI layout", () => {
  const proof = "0x12345678";
  const inputs = [100n, 200n, 300n, 400n];
  const encoded = encodeZkVerification(proof, inputs);

  assert.ok(encoded.startsWith("0x"));
  const raw = Buffer.from(encoded.slice(2), "hex");

  // Offset 0 = 64
  assert.equal(raw.readBigUInt64BE(24), 64n);
  // Offset 1 = 64 + proofLen(32) + proofPadded(32) = 128
  assert.equal(raw.readBigUInt64BE(56), 128n);

  // Proof length at offset 64 = 4 bytes
  assert.equal(raw.readBigUInt64BE(64 + 24), 4n);

  // Inputs length at offset 128 = 4 items
  assert.equal(raw.readBigUInt64BE(128 + 24), 4n);
});

test("ChainClient reads from mocked RPC transport", async () => {
  const client = new ChainClient({
    rpcUrl: "http://mock-rpc",
    contracts: {
      registry: "0x" + "11".repeat(20),
      taskManager: "0x" + "22".repeat(20),
      settlement: "0x" + "33".repeat(20),
    },
  });

  // Mock ethCall
  client.ethCall = async (to, data) => {
    // getEscrow selector: 0x4da9ca7d
    if (data.startsWith(client["selector"]("getEscrow(bytes32)"))) {
      return "0x" + (10n ** 18n).toString(16).padStart(64, "0");
    }
    // getAgentCount selector: 0x3eec4b29
    if (data.startsWith(client["selector"]("getAgentCount()"))) {
      return "0x" + (5n).toString(16).padStart(64, "0");
    }
    // getSettlement selector: 0xbdfbcad4
    if (data.startsWith(client["selector"]("getSettlement(bytes32)"))) {
      const taskId = "aa".repeat(32);
      const agent = "bb".repeat(20).padStart(64, "0");
      const creator = "cc".repeat(20).padStart(64, "0");
      const fee = (8n * 10n ** 17n).toString(16).padStart(64, "0");
      const guard = (0n).toString(16).padStart(64, "0");
      const proto = (2n * 10n ** 16n).toString(16).padStart(64, "0");
      const settled = (1n).toString(16).padStart(64, "0");
      return "0x" + taskId + agent + creator + fee + guard + proto + settled;
    }
    return "0x0";
  };

  const escrow = await client.getEscrow("0x" + "11".repeat(32));
  assert.equal(escrow, 10n ** 18n);

  const count = await client.getAgentCount();
  assert.equal(count, 5);

  const settlement = await client.getSettlement("0x" + "11".repeat(32));
  assert.equal(settlement.settled, true);
  assert.equal(settlement.agentFeeWei, 8n * 10n ** 17n);
});
