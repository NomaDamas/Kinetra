import test from "node:test";
import assert from "node:assert/strict";
import { checkModelHash, checkControlHash, sha256Bytes } from "../src/integrity.js";

const H = "83b4990f9e0cb742f41299886410132641f42f42ef8e1d13ea9bb49909932cd9";
const manifest = { model_sha256: H, legacy_model_hash: H };

test("matching model hash passes", () => {
  checkModelHash(H, manifest);
});

test("model hash differing from the file the native run used throws", () => {
  assert.throws(() => checkModelHash("0".repeat(64), manifest), /model integrity.*manifest\.model_sha256/);
});

test("model hash differing from the legacy model_hash throws even if the manifest was regenerated", () => {
  const regenerated = { model_sha256: "1".repeat(64), legacy_model_hash: H };
  assert.throws(() => checkModelHash("1".repeat(64), regenerated), /legacy model_hash/);
});

test("control hash: equal passes, different or missing throws", () => {
  checkControlHash("nominal", "ab", "ab");
  assert.throws(() => checkControlHash("nominal", "ab", "cd"), /control integrity: scenario nominal/);
  assert.throws(() => checkControlHash("nominal", "ab", undefined), /control integrity/);
});

test("sha256Bytes of the committed model is the legacy model_hash", async () => {
  const { readFile } = await import("node:fs/promises");
  const bytes = await readFile(new URL("../model/rocket_car.xml", import.meta.url));
  assert.equal(await sha256Bytes(bytes), H);
});
