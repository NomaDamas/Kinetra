import test from "node:test";
import assert from "node:assert/strict";
import { planFrame } from "../src/accumulator.js";

const DT = 0.004, MAX = 25;

test("a 16.7 ms frame runs 4 steps and drops nothing", () => {
  const r = planFrame(0, 16.7, DT, MAX);
  assert.equal(r.steps, 4);
  assert.equal(r.capped, false);
  assert.equal(r.droppedS, 0);
  assert.ok(Math.abs(r.acc - 0.0007) < 1e-12);
});

test("the remainder carries over so steps/frame average to real time", () => {
  let acc = 0, steps = 0;
  for (let i = 0; i < 600; i++) { const r = planFrame(acc, 1000 / 60, DT, MAX); acc = r.acc; steps += r.steps; }
  assert.ok(Math.abs(steps * DT - 10) < DT); // 600 frames of 1/60 s = 10 s of sim
});

test("a 300 ms stall: only MAX steps run, the clipped real time is counted as dropped", () => {
  const r = planFrame(0, 300, DT, MAX);
  // 0.1 s / 0.004 s is 24.999... in floating point, so the 25th step can be left in `acc` (not run, not dropped)
  assert.ok(r.steps === MAX || r.steps === MAX - 1);
  assert.equal(r.capped, true);
  assert.ok(Math.abs(r.droppedS + r.acc + r.steps * DT - 0.3) < 1e-12); // nothing vanishes
  assert.ok(r.droppedS >= 0.2 - 1e-12); // at least the 0.2 s clipped off the frame interval
});

test("owed time beyond the cap is discarded and counted", () => {
  // 90 ms frame is under the clip (100 ms) but with 30 ms already owed, 120 ms needs 30 steps > 25
  const r = planFrame(0.03, 90, DT, MAX);
  assert.equal(r.steps, MAX);
  assert.equal(r.capped, true);
  assert.ok(Math.abs(r.droppedS - (0.03 + 0.09 - MAX * DT)) < 1e-12);
  assert.equal(r.acc, 0);
});

test("sim time is conserved: simulated + dropped + carried = real time", () => {
  let acc = 0, sim = 0, dropped = 0, real = 0;
  for (const ms of [16.7, 16.7, 250, 16.7, 40, 16.7, 500, 16.7]) {
    const r = planFrame(acc, ms, DT, MAX);
    acc = r.acc; sim += r.steps * DT; dropped += r.droppedS; real += ms / 1000;
  }
  assert.ok(Math.abs(sim + dropped + acc - real) < 1e-12);
});
