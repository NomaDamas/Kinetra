// One-off, idempotent: results/pose-*.json were measured before the interval recorder started a clean window (the first interval
// of the 8 s window was measured from the last warm-up frame). This drops that first interval from `raf_dt_samples_ms` and
// recomputes raf_dt_ms / raf_dt_over_20ms / raf_dt_over_33ms from the raw samples. Nothing else is changed; no re-measurement.
//   node recompute-intervals.mjs
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { summarize } from "./src/stats.js";

const dir = join(dirname(fileURLToPath(import.meta.url)), "results");
for (const f of readdirSync(dir).filter((x) => /^pose-.*run\d+\.json$/.test(x))) {
  const j = JSON.parse(readFileSync(join(dir, f), "utf8"));
  for (const r of j.runs) {
    const a = r.phase_a;
    if (a.interval_window_reset) continue;
    const before = { n: a.raf_dt_samples_ms.length, p99: a.raf_dt_ms.p99, over_33: a.raf_dt_over_33ms };
    const dt = a.raf_dt_samples_ms.slice(1);
    a.raf_dt_samples_ms = dt; a.raf_dt_ms = summarize(dt);
    a.raf_dt_over_20ms = dt.filter((d) => d > 20).length; a.raf_dt_over_33ms = dt.filter((d) => d > 33.0).length;
    a.interval_window_reset = { note: "first interval (from the last warm-up frame) dropped from the raw samples and the stats recomputed; not re-measured", before };
  }
  writeFileSync(join(dir, f), JSON.stringify(j, null, 1) + "\n");
}
console.log("done");
