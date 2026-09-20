#!/usr/bin/env node
// Converts snarkjs vk.json to the flat decimal word array expected by
// scripts/deploy/DeployNive.s.sol (NIVE_VK_JSON).
//
// Output shape:
//   { "vk": [alpha_x, alpha_y,
//            beta_im_x, beta_re_x, beta_im_y, beta_re_y,
//            gamma_im_x, gamma_re_x, gamma_im_y, gamma_re_y,
//            delta_im_x, delta_re_x, delta_im_y, delta_re_y,
//            ic0_x, ic0_y, ic1_x, ic1_y, ...] }
//
// snarkjs serializes G2 as (real, imaginary); EIP-197 precompiles expect
// (imaginary, real) — the swap happens HERE so the NiveVerifier and the
// deploy script receive canonical EIP-197 order.
//
// Usage: node export-vk.mjs <snarkjs-vk.json> <output-nive-vk.json>
import { readFileSync, writeFileSync } from "node:fs";

const [,, inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error("usage: node export-vk.mjs <snarkjs-vk.json> <output.json>");
  process.exit(1);
}

const vk = JSON.parse(readFileSync(inPath, "utf8"));

// G1: [x, y] as-is. G2: snarkjs [[re_x, im_x], [re_y, im_y]] ->
// EIP-197 (im, re) per coordinate.
const g1 = (p) => [String(p[0]), String(p[1])];
const g2 = (p) => [String(p[0][1]), String(p[0][0]), String(p[1][1]), String(p[1][0])];

const flat = [
  ...g1(vk.vk_alpha_1),
  ...g2(vk.vk_beta_2),
  ...g2(vk.vk_gamma_2),
  ...g2(vk.vk_delta_2),
  ...vk.IC.flatMap(g1),
];

writeFileSync(outPath, JSON.stringify({ vk: flat }, null, 2) + "\n");
console.log(`exported ${flat.length} words (${vk.IC.length} IC points incl. constant) -> ${outPath}`);
