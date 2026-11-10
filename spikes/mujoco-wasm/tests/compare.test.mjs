import test from "node:test";
import assert from "node:assert/strict";
import { compareTrajectories, quatAngle, summarize } from "../src/compare.js";

const NQ = 11;
const ident = () => { const r = new Float64Array(NQ); r[3] = 1; return r; };
const traj = (rows) => { const t = new Float64Array(rows * NQ); for (let r = 0; r < rows; r++) t.set(ident(), r * NQ); return t; };

test("quatAngle: identical, sign-flipped and 90 deg about y", () => {
  const a = Float64Array.of(1, 0, 0, 0), neg = Float64Array.of(-1, 0, 0, 0);
  const s = Math.SQRT1_2, y90 = Float64Array.of(s, 0, s, 0);
  assert.equal(quatAngle(a, 0, a, 0), 0);
  assert.equal(quatAngle(a, 0, neg, 0), 0); // q and -q are the same rotation
  assert.ok(Math.abs(quatAngle(a, 0, y90, 0) - Math.PI / 2) < 1e-15);
});

test("compareTrajectories: identical -> bitwise, zero errors", () => {
  const a = traj(5), b = traj(5);
  const c = compareTrajectories(a, b, 5, NQ, -1);
  assert.equal(c.bitwise_identical, true);
  assert.equal(c.max_pos_err_m, 0);
  assert.equal(c.max_ang_err_rad, 0);
  assert.equal(c.post_touchdown, null);
});

test("compareTrajectories: position offset at one row is found, split at touchdown, thresholds report first exceed", () => {
  const a = traj(6), b = traj(6);
  b[3 * NQ + 0] = 3e-3; b[3 * NQ + 2] = 4e-3; // 5 mm at row 3
  const c = compareTrajectories(a, b, 6, NQ, 2);
  assert.ok(Math.abs(c.max_pos_err_m - 5e-3) < 1e-15);
  assert.equal(c.max_pos_err_step, 3);
  assert.equal(c.pre_touchdown.max_pos_err_m, 0);
  assert.ok(Math.abs(c.post_touchdown.max_pos_err_m - 5e-3) < 1e-15);
  assert.equal(c.bitwise_equal_prefix_rows, 3);
  assert.equal(c.first_step_pos_err_exceeds["0.001"], 3);
  assert.equal(c.first_step_pos_err_exceeds["0.01"], null);
});

test("compareTrajectories: orientation error is the rotation angle, wheel error is separate", () => {
  const a = traj(3), b = traj(3);
  const h = 0.05; // rotation of 0.1 rad about x
  b[2 * NQ + 3] = Math.cos(h); b[2 * NQ + 4] = Math.sin(h);
  b[2 * NQ + 8] = 0.25;
  const c = compareTrajectories(a, b, 3, NQ, -1);
  assert.ok(Math.abs(c.max_ang_err_rad - 0.1) < 1e-15);
  assert.equal(c.max_pos_err_m, 0);
  assert.equal(c.max_wheel_err_rad, 0.25);
});

test("compareTrajectories rejects a short buffer", () => {
  assert.throws(() => compareTrajectories(traj(2), traj(3), 3, NQ, -1));
});

test("summarize percentiles", () => {
  const s = summarize([5, 1, 3, 2, 4]);
  assert.equal(s.min, 1); assert.equal(s.median, 3); assert.equal(s.max, 5); assert.equal(s.mean, 3);
});
