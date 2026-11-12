import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { makeWorld, fillPoses } from "../src/poses.js";

const hash = (f) => createHash("sha256").update(Buffer.from(f.buffer)).digest("hex");
const frame = (n, seed, tick, c) => { const f = new Float32Array(7 * n); fillPoses(makeWorld(n, seed), tick, c, f); return f; };

test("same (n, seed, tick, ctrl) gives bit-identical poses", () => {
  assert.equal(hash(frame(1000, 0, 600, 0)), hash(frame(1000, 0, 600, 0)));
});
test("seed and tick change the poses", () => {
  assert.notEqual(hash(frame(200, 0, 10, 0)), hash(frame(200, 1, 10, 0)));
  assert.notEqual(hash(frame(200, 0, 10, 0)), hash(frame(200, 0, 11, 0)));
});
test("quaternions are unit length and all values finite", () => {
  const f = frame(5000, 0, 1234, 1);
  for (let i = 0; i < 5000; i++) {
    const q = Math.hypot(f[i * 7 + 3], f[i * 7 + 4], f[i * 7 + 5], f[i * 7 + 6]);
    assert.ok(Math.abs(q - 1) < 1e-5, `body ${i}: |q|=${q}`);
  }
  assert.ok(f.every(Number.isFinite));
});
test("marker (body 0) jumps between two spots with the control state and ignores ticks", () => {
  const w = makeWorld(200, 0), a = frame(200, 0, 5, 0), b = frame(200, 0, 900, 0), c = frame(200, 0, 5, 1);
  assert.deepEqual([...a.slice(0, 7)], [...b.slice(0, 7)]);
  assert.equal(a[0], Math.fround(w.marker.x0)); assert.equal(c[0], Math.fround(w.marker.x1));
});
test("needs at least 2 bodies", () => assert.throws(() => makeWorld(1, 0)));
