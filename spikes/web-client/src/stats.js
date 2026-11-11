/** Nearest-rank percentiles over the finite values only. Missing values (null, undefined, NaN, Infinity) are counted in
 *  n_missing and never enter the percentiles; n_valid is the sample count the percentiles are about. Values are rounded to
 *  3 decimals so the JSON stays readable. */
export function summarize(a) {
  const v = a.filter((x) => typeof x === "number" && Number.isFinite(x)), n_missing = a.length - v.length;
  if (!v.length) return { n_valid: 0, n_missing };
  const s = Float64Array.from(v).sort(), q = (f) => s[Math.min(s.length - 1, Math.max(0, Math.ceil(f * s.length) - 1))];
  const r = (x) => Math.round(x * 1000) / 1000;
  return { n_valid: s.length, n_missing, mean: r(s.reduce((x, y) => x + y, 0) / s.length), min: r(s[0]), p50: r(q(0.5)), p95: r(q(0.95)), p99: r(q(0.99)), max: r(s[s.length - 1]) };
}
