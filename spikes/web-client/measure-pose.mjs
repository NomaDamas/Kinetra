// A0-02a runner: headless Chromium (Playwright's build, throwaway profile) x synthetic pose stream at 200 / 1000 / 5000 bodies.
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/web-client measure:pose
// Env: BODIES=200,1000,5000  PRESSES=40  RESULT_NAME=pose-run1.json  GL=swiftshader (default) | metal (--use-angle=metal: the M2 Pro GPU through ANGLE)
//      FLOW=none (default, A0-02a) | ack (A0-02a-f: the client acks drawn ticks, the core keeps at most WIN unacked frames)  WIN=2
//   Screenshots are named pose-<GL>[-ack<WIN>]-<n>.png so an ack run never overwrites the A0-02a ones.
import { mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startServer } from "./src/serve.mjs";
import { launch, machine, requireGuard, clientVersion } from "./src/runner-common.mjs";
import { summarize } from "./src/stats.js";
import { FLOWS, MAX_WINDOW } from "./src/flow.js";

requireGuard("measure-pose.mjs", "measure:pose");
const HERE = dirname(fileURLToPath(import.meta.url)), OUT = join(HERE, "results");
mkdirSync(OUT, { recursive: true });
const bodies = (process.env.BODIES ?? "200,1000,5000").split(",").map(Number), presses = Number(process.env.PRESSES ?? 40);
const srv = await startServer(0);
const base = `http://127.0.0.1:${srv.server.address().port}`;
const GL = process.env.GL ?? "swiftshader", GL_ARGS = { swiftshader: [], metal: ["--use-angle=metal"] }[GL];
if (!GL_ARGS) { console.error(`GL must be swiftshader or metal, got ${GL}`); process.exit(2); }
const FLOW = process.env.FLOW ?? "none", WIN = Number(process.env.WIN ?? 2);
if (!FLOWS.includes(FLOW) || !Number.isInteger(WIN) || WIN < 1 || WIN > MAX_WINDOW) { console.error(`FLOW must be one of ${FLOWS.join(", ")} and WIN an integer 1..${MAX_WINDOW}, got FLOW=${FLOW} WIN=${process.env.WIN}`); process.exit(2); }
const TAG = FLOW === "ack" ? `${GL}-ack${WIN}` : GL;
const browser = await launch(GL_ARGS);
const result = { issue: FLOW === "ack" ? "A0-02a-f #420" : "A0-02a #47", flow: FLOW, win: FLOW === "ack" ? WIN : null, client: clientVersion(), machine_before: machine(), gl_backend: GL, launch_args: GL_ARGS, browser: { name: "chromium-headless-shell (playwright-core 1.65.0)", version: browser.version() }, runs: [] };
try {
  for (const n of bodies) {
    const page = await browser.newPage({ viewport: { width: 960, height: 540 } });
    const logs = []; page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`)); page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
    const before = srv.streams.length, loadBefore = os.loadavg()[0];
    await page.goto(`${base}/?n=${n}&presses=${presses}&flow=${FLOW}&win=${WIN}`);
    await page.waitForFunction(() => window.__A0_02A_LATENCY_READY || window.__A0_02A_ERROR, null, { timeout: 180_000, polling: 100 });
    const err = await page.evaluate(() => window.__A0_02A_ERROR);
    if (err) { console.error(`n=${n}:`, err, logs); process.exitCode = 1; await page.close(); continue; }
    await page.screenshot({ path: join(OUT, `pose-${TAG}-${n}.png`) });
    for (let i = 0; i < presses; i++) { await page.keyboard.press("Space"); await new Promise((r) => setTimeout(r, 180 + ((i * 37) % 71))); } // varied gaps = varied phase vs the 60 Hz tick
    const r = await page.evaluate(() => window.__finish());
    const st = srv.streams[before]?.stats;
    r.server = st && { frames_sent: st.sent, backpressure_skipped: st.backpressure_skipped, window_skipped: st.window_skipped, acks: st.acks, acks_ignored: st.acks_ignored, ack_lag_ms: summarize(st.ack_lag_ms), inflight_at_tick: summarize(st.inflight_at_tick), clock_rebases: st.rebases, bytes: st.bytes, tick_lateness_ms: summarize(st.lateness_ms), frame_build_ms: summarize(st.build_ms), control_wait_for_tick_ms: summarize(st.ctrl_wait_ms) };
    r.load_avg_1m = [loadBefore, os.loadavg()[0]].map((x) => +x.toFixed(1)); r.console = logs;
    result.runs.push(r);
    const a = r.phase_a, b = r.bench, l = r.latency.summary.total;
    console.log(`n=${n} flow=${FLOW}: raf ${a.raf_fps} fps (dt p99 ${a.raf_dt_ms.p99} ms), cpu/frame p50 ${a.cpu_ms.p50} ms, bench ${b.frames_per_s_sync} fps sync, ticks/s ${a.distinct_ticks_per_s}, ${r.net.payload_mbit_per_s} Mbit/s, latency p50 ${l.p50} ms (${r.latency.measured}/${presses})`);
    await page.close();
  }
} finally {
  result.machine_after = machine();
  await browser.close(); srv.close();
  writeFileSync(join(OUT, process.env.RESULT_NAME ?? "pose.json"), JSON.stringify(result, null, 1) + "\n");
}
