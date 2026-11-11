// Offline tests of the capture helpers (no browser).
import assert from "node:assert/strict";
import { test } from "node:test";
import { PNG } from "pngjs";
import { drawnPixels, guardProblem, srgbToLinear } from "../capture.ts";

test("srgbToLinear: standard values", () => {
  assert.equal(srgbToLinear(0), 0);
  assert.ok(Math.abs(srgbToLinear(1) - 1) < 1e-12);
  assert.ok(Math.abs(srgbToLinear(0.5) - 0.2140411404) < 1e-9);
  assert.ok(Math.abs(srgbToLinear(0.04045) - 0.04045 / 12.92) < 1e-12);
});

test("drawnPixels: counts only pixels that differ from the page background", () => {
  const png = new PNG({ width: 4, height: 1 });
  const px = [[0x14, 0x18, 0x1f], [0x14, 0x18, 0x1f], [200, 200, 200], [0x16, 0x18, 0x1f]];
  px.forEach((p, i) => { png.data[i * 4] = p[0]!; png.data[i * 4 + 1] = p[1]!; png.data[i * 4 + 2] = p[2]!; png.data[i * 4 + 3] = 255; });
  assert.equal(drawnPixels(png), 1);
});

test("a local browser run outside the resource guard is refused", () => {
  assert.match(guardProblem({}) ?? "", /resource guard/);
  assert.equal(guardProblem({ KINETRA_GUARD_PASSED: "1" }), null);
  assert.equal(guardProblem({ CI: "true" }), null);
});
