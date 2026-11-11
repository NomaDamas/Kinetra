// Browser test (run through the resource guard): the fixtures load in three.js and the material slot arrives linear.
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { guardProblem, run, srgbToLinear } from "../capture.ts";

const problem = guardProblem();
if (problem) throw new Error(problem);

// sRGB values of the B-07 catalog and the neutral fallback (docs/architecture/materials.md).
const SRGB: Record<string, string> = { "mounting-plate-al6061": "#e8eaea", "drive-shaft-steel": "#c4c6c6", "sensor-mast-user-material": "#808080", "reflectance-ior": "#e8eaea" };
const hex = (s: string) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16) / 255);

test("three.js loads each fixture and its colour is the linear value of the slot's sRGB", async () => {
  const { page, drawn } = await run(mkdtempSync(join(tmpdir(), "gltf-check-")));
  assert.ok(drawn > 10000, `only ${drawn} pixels drawn`);
  for (const r of page.results) {
    const want = hex(SRGB[r.name]!).map(srgbToLinear);
    r.color_linear.forEach((c, k) => assert.ok(Math.abs(c - want[k]!) < 1e-5, `${r.name} channel ${k}: ${c} vs ${want[k]}`));
    assert.equal(r.materials, 1);
  }
  const by = Object.fromEntries(page.results.map((r) => [r.name, r]));
  assert.equal(by["sensor-mast-user-material"]!.metalness, 0);
  assert.equal(by["sensor-mast-user-material"]!.roughness, 0.5);
  assert.equal(by["mounting-plate-al6061"]!.metalness, 1);
  assert.ok(Math.abs(by["reflectance-ior"]!.ior! - 1.3256) < 1e-3);
});
