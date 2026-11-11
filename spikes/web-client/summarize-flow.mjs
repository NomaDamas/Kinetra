// A0-02a-f: per-run table of flow=none vs flow=ack, run by run, with the machine load of each run (the load differs a lot between runs).
//   node summarize-flow.mjs            -> markdown rows for results/pose-{swiftshader,metal}-{none,ack2}-run*.json
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const dir = join(dirname(fileURLToPath(import.meta.url)), "results");
const f = (x, d = 1) => (x == null || !Number.isFinite(x) ? "-" : String(Math.round(x * 10 ** d) / 10 ** d));
console.log("| GL | n | 모드 | 실행 | 부하 1분 (전→후) | rAF fps | 그린 틱 /s | 지연 p50 / p95 ms | 표본 측정/대체/변화없음/미해결 | 받은 틱 간격 p50/p99/max | 건너뛴 틱(코어) | ack 지연 p50/p99 ms | 안 받은 프레임 max |");
console.log("|---|---|---|---|---|---|---|---|---|---|---|---|---|");
for (const gl of ["swiftshader", "metal"]) for (const n of [1000, 5000]) for (const mode of ["none", "ack2"]) {
  const files = readdirSync(dir).filter((x) => x.startsWith(`pose-${gl}-${mode}-run`) && x.endsWith(".json")).sort();
  for (const file of files) {
    const r = JSON.parse(readFileSync(join(dir, file), "utf8")).runs.find((x) => x.config.n === n);
    const run = file.match(/run(\d+)/)[1];
    if (!r) continue; // this file has no run for this n (a crashed run keeps only the sizes that finished; a re-run covers one size)
    const a = r.phase_a, l = r.latency, t = l.summary.total, g = r.net.recv_tick_gap, s = r.server;
    console.log(`| ${gl} | ${n} | ${mode === "ack2" ? "ack W=2" : "none"} | ${run} | ${r.load_avg_1m[0]}→${r.load_avg_1m[1]} | ${f(a.raf_fps)} | ${f(a.distinct_ticks_per_s)} | ${t.n_valid ? `${f(t.p50)} / ${f(t.p95)}` : "-"} | ${l.measured}/${l.superseded}/${l.no_visible_change}/${l.unresolved} | ${g.n_valid ? `${g.p50}/${g.p99}/${g.max}` : "-"} | ${mode === "ack2" ? s.window_skipped : s.backpressure_skipped} | ${s.ack_lag_ms?.n_valid ? `${f(s.ack_lag_ms.p50)}/${f(s.ack_lag_ms.p99)}` : "-"} | ${s.inflight_at_tick?.n_valid ? s.inflight_at_tick.max : "-"} |`);
  }
}
