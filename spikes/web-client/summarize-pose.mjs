// Prints the median-of-runs table for results/pose-<gl>-run*.json (the numbers REPORT.md quotes).
//   node summarize-pose.mjs swiftshader | metal
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const dir = join(dirname(fileURLToPath(import.meta.url)), "results"), gl = process.argv[2] ?? "swiftshader";
const files = readdirSync(dir).filter((f) => f.startsWith(`pose-${gl}-run`) && f.endsWith(".json")).sort();
const med = (a) => { const s = [...a].filter((x) => x != null && Number.isFinite(x)).sort((x, y) => x - y); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };
const runs = files.map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")));
console.log(`${gl}: ${files.length} runs (${files.join(", ")})`);
const cell = (n, pick) => { const v = runs.map((r) => r.runs.find((x) => x.config.n === n)).filter(Boolean).map(pick); return `${typeof v[0] === "string" ? "" : med(v) + " "}[${v.map((x) => x ?? "-").join(" / ")}]`; };
const rows = [
  ["rAF fps", (r) => r.phase_a.raf_fps], ["rAF dt p99 ms", (r) => r.phase_a.raf_dt_ms.p99], ["rAF intervals > 33.0 ms", (r) => r.phase_a.raf_dt_over_33ms],
  ["distinct ticks drawn /s", (r) => r.phase_a.distinct_ticks_per_s], ["ticks skipped between draws (gap>1)", (r) => r.phase_a.tick_gap_over_1],
  ["CPU per frame p50 ms (update+render call)", (r) => r.phase_a.cpu_ms.p50], ["CPU per frame p99 ms", (r) => r.phase_a.cpu_ms.p99], ["  of which pose->matrix p50 ms", (r) => r.phase_a.update_ms.p50],
  ["sync frame p50 ms (update+render+readPixels)", (r) => r.bench.total_ms.p50], ["sync frames/s", (r) => r.bench.frames_per_s_sync],
  ["payload Mbit/s received", (r) => r.net.payload_mbit_per_s], ["frames received /s", (r) => r.net.frames_per_s], ["server frames sent", (r) => r.server.frames_sent], ["server ticks skipped (backpressure)", (r) => r.server.backpressure_skipped],
  ["server tick lateness p99 ms", (r) => r.server.tick_lateness_ms.p99], ["latency total p50 ms", (r) => r.latency.summary.total.p50], ["latency total p95 ms", (r) => r.latency.summary.total?.p95],
  ["latency samples (measured / superseded / no-visible-change / unresolved of requested)", (r) => `${r.latency.measured}/${r.latency.superseded}/${r.latency.no_visible_change}/${r.latency.unresolved} of ${r.latency.requested}`],
  ["frames received / drawn-unique / replaced before draw", (r) => `${r.phase_a.frames_received}/${r.phase_a.distinct_ticks_drawn}/${r.phase_a.frames_overwritten_before_draw}`],
];
console.log(["", ...[200, 1000, 5000].map((n) => `n=${n} (median [run1/run2/...])`)].join(" | "));
for (const [name, pick] of rows) console.log([name, ...[200, 1000, 5000].map((n) => cell(n, pick))].join(" | "));
console.log("load avg 1m before/after per run:", runs.map((r) => `${r.machine_before.load_avg[0]}->${r.machine_after.load_avg[0]}`).join(", "));
