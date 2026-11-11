// Prints the median-of-runs table for results/pose-<gl>-run*.json (the numbers REPORT.md quotes).
//   node summarize-pose.mjs swiftshader | metal | swiftshader-ack2 | metal-ack2   (A0-02a-f runs: results/pose-<gl>-ack<win>-run*.json)
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
  ["received tick gap p50 / p99 / max (1 = every tick; A0-02a-f)", (r) => r.net.recv_tick_gap ? `${r.net.recv_tick_gap.p50}/${r.net.recv_tick_gap.p99}/${r.net.recv_tick_gap.max}` : "-"],
  ["received tick gap > 1 (count)", (r) => r.net.recv_tick_gap_over_1 ?? "-"], ["frame age at draw p50 / p99 ms (draw time - receive time)", (r) => `${r.phase_a.frame_age_at_draw_ms.p50}/${r.phase_a.frame_age_at_draw_ms.p99}`],
  ["server window-skipped ticks (ack mode)", (r) => r.server.window_skipped ?? "-"], ["server acks applied / ignored", (r) => r.server.acks == null ? "-" : `${r.server.acks}/${r.server.acks_ignored}`],
  ["ack lag p50 / p99 ms (send -> ack arrives at the core)", (r) => r.server.ack_lag_ms?.p50 == null ? "-" : `${r.server.ack_lag_ms.p50}/${r.server.ack_lag_ms.p99}`], ["unacked frames at tick p50 / max", (r) => r.server.inflight_at_tick?.p50 == null ? "-" : `${r.server.inflight_at_tick.p50}/${r.server.inflight_at_tick.max}`],
  ["frames received / drawn-unique / replaced before draw", (r) => `${r.phase_a.frames_received}/${r.phase_a.distinct_ticks_drawn}/${r.phase_a.frames_overwritten_before_draw}`],
];
console.log(["", ...[200, 1000, 5000].filter((n) => runs.some((r) => r.runs.some((x) => x.config.n === n))).map((n) => `n=${n} (median [run1/run2/...])`)].join(" | "));
for (const [name, pick] of rows) console.log([name, ...[200, 1000, 5000].filter((n) => runs.some((r) => r.runs.some((x) => x.config.n === n))).map((n) => cell(n, pick))].join(" | "));
console.log("load avg 1m before/after per run:", runs.map((r) => `${r.machine_before.load_avg[0]}->${r.machine_after.load_avg[0]}`).join(", "));
