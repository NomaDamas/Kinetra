import test from "node:test";
import assert from "node:assert/strict";
import { LatencyTracker } from "../src/latency.js";
import { IntervalRecorder } from "../src/intervals.js";

const inp = (seq, state) => ({ seq, state });
const yes = () => true;

test("overlapping inputs 1,2,3 drawn together: only the echoed input 3 is a sample, 1 and 2 are superseded", () => {
  const t = new LatencyTracker(0);
  t.input(inp(1, 1)); t.input(inp(2, 0)); t.input(inp(3, 1));
  const s = t.onDraw({ ctrlSeq: 3, ctrlState: 1 }, yes, { screen: 9 });
  assert.equal(s.seq, 3);
  assert.deepEqual(t.counts(), { inputs: 3, measured: 1, superseded: 2, no_visible_change: 0, unverified_start: 0, unresolved: 0 });
});
test("input 2 undoes input 1 before anything was drawn: echoing seq 2 shows no change", () => {
  const t = new LatencyTracker(0);
  t.input(inp(1, 1)); t.input(inp(2, 0));
  assert.equal(t.onDraw({ ctrlSeq: 2, ctrlState: 0 }, yes, {}), null);
  assert.deepEqual(t.counts(), { inputs: 2, measured: 0, superseded: 1, no_visible_change: 1, unverified_start: 0, unresolved: 0 });
});
test("input 1 drawn, then input 2 (back to 0) drawn: both moved the marker, both are samples", () => {
  const t = new LatencyTracker(0);
  t.input(inp(1, 1)); t.input(inp(2, 0));
  assert.equal(t.onDraw({ ctrlSeq: 1, ctrlState: 1 }, yes, {}).seq, 1);
  assert.equal(t.counts().unresolved, 1); // input 2 still pending after frame 1
  assert.equal(t.onDraw({ ctrlSeq: 2, ctrlState: 0 }, yes, {}).seq, 2);
  assert.deepEqual(t.counts(), { inputs: 2, measured: 2, superseded: 0, no_visible_change: 0, unverified_start: 0, unresolved: 0 });
});
test("a frame that does not show the marker at the new spot leaves the input pending", () => {
  const t = new LatencyTracker(0);
  t.input(inp(1, 1));
  assert.equal(t.onDraw({ ctrlSeq: 1, ctrlState: 1 }, () => false, {}), null);
  assert.equal(t.counts().unresolved, 1);
});
test("unknown start state is never a sample", () => {
  const t = new LatencyTracker(null);
  t.input(inp(1, 1));
  assert.equal(t.onDraw({ ctrlSeq: 1, ctrlState: 1 }, yes, {}), null);
  assert.equal(t.counts().unverified_start, 1);
});
test("every input is accounted for exactly once: measured + superseded + no_visible_change + unverified + unresolved = inputs", () => {
  const t = new LatencyTracker(0);
  for (let i = 1; i <= 7; i++) t.input(inp(i, i % 2));
  t.onDraw({ ctrlSeq: 2, ctrlState: 0 }, yes, {}); t.onDraw({ ctrlSeq: 5, ctrlState: 1 }, yes, {});
  const c = t.counts();
  assert.equal(c.measured + c.superseded + c.no_visible_change + c.unverified_start + c.unresolved, c.inputs);
});
test("interval recorder: the first frame of the window only sets the reference (warm-up is not an interval)", () => {
  const r = new IntervalRecorder();
  r.frame(100); r.frame(116.7);                 // warm-up, not recording
  r.start(); r.frame(5000);                     // 4,883 ms after the last warm-up frame
  r.frame(5016.7); r.frame(5033.4);
  assert.deepEqual(r.dt.map((d) => Math.round(d * 10) / 10), [16.7, 16.7]);
  r.stop(); r.frame(9000); assert.equal(r.dt.length, 2);
  r.start(); r.frame(9100); assert.equal(r.dt.length, 2); // a second window also starts clean
});
