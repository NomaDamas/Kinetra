// Pure arithmetic of the assertion, kept out of the browser so it has its own offline tests.

/** Part position expected after the grab: start + the controller's displacement while the squeeze was held. */
export function expectedFinal(start, controllerFrom, controllerTo) {
  return start.map((s, i) => s + (controllerTo[i] - controllerFrom[i]));
}

/** Largest absolute per-axis difference between two 3-vectors, in metres. */
export function maxAxisError(actual, expected) {
  if (actual.length !== 3 || expected.length !== 3) throw new Error("expected two 3-vectors");
  return Math.max(...actual.map((a, i) => Math.abs(a - expected[i])));
}

/** Tolerance, in metres. IWER keeps poses in float32 matrices (about 1e-7 relative at 1 m); 1e-4 m = 0.1 mm leaves a wide margin. */
export const POSITION_TOLERANCE_M = 1e-4;

/** Frame-interval summary (ms) of an array of frame timestamps (ms): count, mean fps, p50/p99/max interval. */
export function summarizeFrames(timesMs) {
  if (timesMs.length < 2) throw new Error("need at least two frames");
  const dt = timesMs.slice(1).map((t, i) => t - timesMs[i]).sort((a, b) => a - b);
  const q = (p) => dt[Math.min(dt.length - 1, Math.floor(p * dt.length))];
  const mean = dt.reduce((s, x) => s + x, 0) / dt.length;
  return { frames: timesMs.length, mean_interval_ms: mean, fps: 1000 / mean, p50_interval_ms: q(0.5), p99_interval_ms: q(0.99), max_interval_ms: dt[dt.length - 1] };
}
