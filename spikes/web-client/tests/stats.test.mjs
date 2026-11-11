import test from "node:test";
import assert from "node:assert/strict";
import { summarize } from "../src/stats.js";

test("nearest-rank percentiles", () => {
  const s = summarize(Array.from({ length: 100 }, (_, i) => i + 1));
  assert.deepEqual([s.n_valid, s.min, s.p50, s.p95, s.p99, s.max, s.mean], [100, 1, 50, 95, 99, 100, 50.5]);
});
test("empty input", () => assert.deepEqual(summarize([]), { n_valid: 0, n_missing: 0 }));
test("single value", () => assert.equal(summarize([3]).p99, 3));
test("missing values are counted, never enter the percentiles", () => {
  const s = summarize([10, null, 20, undefined, NaN, 30, Infinity, 40]);
  assert.deepEqual([s.n_valid, s.n_missing, s.min, s.p50, s.max, s.mean], [4, 4, 10, 20, 40, 25]);
  assert.deepEqual(summarize([null, undefined]), { n_valid: 0, n_missing: 2 });
});
