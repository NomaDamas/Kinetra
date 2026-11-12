// Deterministic synthetic world: same (n, seed, tick, ctrlState) -> same poses. Math.* only, no clocks, no Math.random.
// Body 0 is the latency-probe marker (a big cube that jumps between two spots with control channel 0); bodies 1..n-1 are a
// grid of boxes bobbing and tumbling. Z is up (client-adapter.md G4). This is a load generator, not physics.
export const STRIDE = 14, HZ = 60;
const P = { rx: 0, ry: 1, rz: 2, amp: 3, phase: 4, w: 5, ax: 6, ay: 7, az: 8, spin: 9, sx: 10, sy: 11, sz: 12, hue: 13 };

export function mulberry32(a) {
  return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

export function makeWorld(n, seed) {
  if (!(n >= 2)) throw new Error("need n >= 2 (body 0 is the marker)");
  const cols = Math.ceil(Math.sqrt(n - 1)), spacing = 2.5, extent = cols * spacing;
  const p = new Float64Array(n * STRIDE);
  for (let i = 1; i < n; i++) {
    const r = mulberry32((seed * 0x9e3779b1) ^ (i * 0x85ebca6b)), o = i * STRIDE, k = i - 1;
    const ax = r() - 0.5, ay = r() - 0.5, az = r() - 0.5, l = Math.hypot(ax, ay, az) || 1;
    p.set([(k % cols - (cols - 1) / 2) * spacing, (Math.floor(k / cols) - (cols - 1) / 2) * spacing, 1 + r(), 0.3 + 0.5 * r(), 6.2832 * r(), 1 + 2 * r(),
      ax / l, ay / l, az / l, 0.5 + 2 * r(), 0.6 + 0.8 * r(), 0.6 + 0.8 * r(), 0.6 + 0.8 * r(), r()], o);
  }
  const size = Math.max(3, extent * 0.05);
  return { n, seed, p, extent, marker: { size, x0: -extent * 0.15, x1: extent * 0.15, y: 0, z: size * 2 } };
}

/** Writes n x 7 floats (x y z qx qy qz qw) for `tick` into `out`. */
export function fillPoses(w, tick, ctrlState, out) {
  const t = tick / HZ, p = w.p;
  out.set([ctrlState ? w.marker.x1 : w.marker.x0, w.marker.y, w.marker.z, 0, 0, 0, 1], 0);
  for (let i = 1; i < w.n; i++) {
    const o = i * STRIDE, a = p[o + P.w] * t + p[o + P.phase], ang = p[o + P.spin] * t + p[o + P.phase], s = Math.sin(ang / 2);
    out.set([p[o] + p[o + P.amp] * 0.3 * Math.cos(a), p[o + 1] + p[o + P.amp] * 0.3 * Math.sin(a), p[o + 2] + p[o + P.amp] * Math.sin(a * 1.7),
      p[o + P.ax] * s, p[o + P.ay] * s, p[o + P.az] * s, Math.cos(ang / 2)], i * 7);
  }
}
export const bodyScale = (w, i) => [w.p[i * STRIDE + P.sx], w.p[i * STRIDE + P.sy], w.p[i * STRIDE + P.sz]];
export const bodyHue = (w, i) => w.p[i * STRIDE + P.hue];
