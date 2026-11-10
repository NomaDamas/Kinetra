// Pure math for the A0-01b comparison (no MuJoCo, no DOM). Unit-tested in tests/compare.test.mjs.
// qpos layout (rocket_car): [x y z qw qx qy qz, wheel_fl wheel_fr wheel_rl wheel_rr] -> nq = 11.

/** Geodesic angle [rad] between unit quaternions (w x y z): 2*atan2(|vec(a* b)|, |w(a* b)|). Sign-invariant. */
export function quatAngle(a, ai, b, bi) {
  const aw = a[ai], ax = -a[ai + 1], ay = -a[ai + 2], az = -a[ai + 3]; // conjugate of a
  const bw = b[bi], bx = b[bi + 1], by = b[bi + 2], bz = b[bi + 3];
  const w = aw * bw - ax * bx - ay * by - az * bz;
  const x = aw * bx + ax * bw + ay * bz - az * by;
  const y = aw * by - ax * bz + ay * bw + az * bx;
  const z = aw * bz + ax * by - ay * bx + az * bw;
  return 2 * Math.atan2(Math.hypot(x, y, z), Math.abs(w));
}

/**
 * Compare two trajectories of `rows` x `nq` row-major qpos (same step index = same sim time).
 * Returns the max root-position error [m] (Euclid, qpos[0..2]), max orientation error [rad] (root quaternion),
 * max |wheel angle| error [rad], the step of each maximum, errors at `touchdownStep` (first contact in the
 * reference) and at the last row, the number of leading rows that are bitwise equal, and the first row whose
 * root position error exceeds `thresholds` (null when never).
 */
export function compareTrajectories(a, b, rows, nq, touchdownStep, thresholds = [1e-9, 1e-6, 1e-3, 1e-2, 1e-1]) {
  if (a.length < rows * nq || b.length < rows * nq) throw new Error("trajectory shorter than rows*nq");
  // NaN/Infinity in either trajectory is a broken run, not a "small error": Math.max/hypot would silently skip or hide it.
  for (const [name, t] of [["first", a], ["second", b]]) {
    for (let i = 0; i < rows * nq; i++) {
      if (!Number.isFinite(t[i])) throw new Error(`non-finite value in ${name} trajectory at row ${Math.floor(i / nq)}, column ${i % nq}`);
    }
  }
  let maxPos = 0, maxPosStep = 0, maxAng = 0, maxAngStep = 0, maxWheel = 0, maxWheelStep = 0;
  let maxPosPre = 0, maxAngPre = 0, maxPosPost = 0, maxAngPost = 0;
  let bitwisePrefix = rows;
  const firstExceed = Object.fromEntries(thresholds.map((t) => [String(t), null]));
  const pos = new Float64Array(rows), ang = new Float64Array(rows);
  for (let r = 0; r < rows; r++) {
    const o = r * nq;
    if (bitwisePrefix === rows) {
      for (let j = 0; j < nq; j++) {
        if (!Object.is(a[o + j], b[o + j])) { bitwisePrefix = r; break; }
      }
    }
    const p = Math.hypot(a[o] - b[o], a[o + 1] - b[o + 1], a[o + 2] - b[o + 2]);
    const g = quatAngle(a, o + 3, b, o + 3);
    let w = 0;
    for (let j = 7; j < nq; j++) w = Math.max(w, Math.abs(a[o + j] - b[o + j]));
    pos[r] = p; ang[r] = g;
    if (p > maxPos) { maxPos = p; maxPosStep = r; }
    if (g > maxAng) { maxAng = g; maxAngStep = r; }
    if (w > maxWheel) { maxWheel = w; maxWheelStep = r; }
    const pre = touchdownStep < 0 || r < touchdownStep;
    if (pre) { maxPosPre = Math.max(maxPosPre, p); maxAngPre = Math.max(maxAngPre, g); }
    else { maxPosPost = Math.max(maxPosPost, p); maxAngPost = Math.max(maxAngPost, g); }
    for (const t of thresholds) if (firstExceed[String(t)] === null && p > t) firstExceed[String(t)] = r;
  }
  const last = rows - 1;
  const atTd = touchdownStep >= 0 && touchdownStep < rows ? { pos_m: pos[touchdownStep], ang_rad: ang[touchdownStep] } : null;
  return {
    max_pos_err_m: maxPos, max_pos_err_step: maxPosStep, max_ang_err_rad: maxAng, max_ang_err_step: maxAngStep,
    max_wheel_err_rad: maxWheel, max_wheel_err_step: maxWheelStep,
    pre_touchdown: { max_pos_err_m: maxPosPre, max_ang_err_rad: maxAngPre },
    post_touchdown: touchdownStep >= 0 ? { max_pos_err_m: maxPosPost, max_ang_err_rad: maxAngPost } : null,
    at_touchdown: atTd, final: { pos_m: pos[last], ang_rad: ang[last] },
    bitwise_equal_prefix_rows: bitwisePrefix, bitwise_identical: bitwisePrefix === rows,
    first_step_pos_err_exceeds: firstExceed,
  };
}

export function percentile(sortedAsc, p) {
  if (sortedAsc.length === 0) return NaN;
  const i = Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(p * sortedAsc.length) - 1));
  return sortedAsc[i];
}

export function summarize(values) {
  const s = Float64Array.from(values).sort();
  const sum = s.reduce((x, y) => x + y, 0);
  return { n: s.length, min: s[0], median: percentile(s, 0.5), p95: percentile(s, 0.95), p99: percentile(s, 0.99), max: s[s.length - 1], mean: sum / s.length };
}
