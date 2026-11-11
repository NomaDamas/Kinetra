// A0-02c runner: cold-load the share page in headless Chromium under CDP network throttling and record link-open -> first frame.
//   node build-replay.mjs   (once, produces out/replay.js)
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/web-client measure:replay
// Env: REPEAT=5  ENCODINGS=identity,gzip,br  PROFILES=none,fast4g,slow4g,slow3g  GL=swiftshader|metal  RESULT_NAME=replay.json
import { mkdirSync, writeFileSync, statSync, readFileSync } from "node:fs";
import os from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";
import { buildReplay } from "./build-replay.mjs";
import { startReplayServer, compress } from "./src/replay-serve.mjs";
import { launch, machine, requireGuard } from "./src/runner-common.mjs";
import { summarize } from "./src/stats.js";

requireGuard("measure-replay.mjs", "measure:replay");
const HERE = dirname(fileURLToPath(import.meta.url)), OUT = join(HERE, "results");
mkdirSync(OUT, { recursive: true });
// Chrome DevTools presets, values from devtools-frontend front_end/core/sdk/NetworkManager.ts (download/upload in bytes/s, latency in ms).
export const PROFILES = {
  none: null,
  fast4g: { name: "Fast 4G", latency: 60 * 2.75, down: (9e6 / 8) * 0.9, up: (1.5e6 / 8) * 0.9 },
  slow4g: { name: "Slow 4G (listed as 'Fast 3G' in older DevTools)", latency: 150 * 3.75, down: (1.6e6 / 8) * 0.9, up: (0.75e6 / 8) * 0.9 },
  slow3g: { name: "Slow 3G", latency: 400 * 5, down: (0.5e6 / 8) * 0.8, up: (0.5e6 / 8) * 0.8 },
};
const repeat = Number(process.env.REPEAT ?? 5);
const encodings = (process.env.ENCODINGS ?? "identity,gzip,br").split(",");
const profiles = (process.env.PROFILES ?? "none,fast4g,slow4g,slow3g").split(",");
const GL = process.env.GL ?? "swiftshader", GL_ARGS = { swiftshader: [], metal: ["--use-angle=metal"] }[GL];
if (!GL_ARGS) { console.error(`GL must be swiftshader or metal, got ${GL}`); process.exit(2); }

const built = await buildReplay();
const files = { "out/replay.js": "out/replay.js", "replay.html": "replay.html", "replay/bundle.json": "replay/bundle.json", "replay/poses.bin": "replay/poses.bin" };
const sizes = Object.fromEntries(Object.entries(files).map(([k, rel]) => {
  const b = readFileSync(join(HERE, rel));
  return [k, { identity: b.length, gzip9: compress.gzip(b).length, brotli11: compress.br(b).length }];
}));
const total = (key) => Object.values(sizes).reduce((s, v) => s + v[key], 0);
const result = { issue: "A0-02c #49", gl_backend: GL, launch_args: GL_ARGS, repeat, build: { ...built, minified: true, outfile: "out/replay.js" }, file_sizes_bytes: sizes,
  totals_bytes: { identity: total("identity"), gzip9: total("gzip9"), brotli11: total("brotli11") },
  profiles: Object.fromEntries(Object.entries(PROFILES).map(([k, v]) => [k, v && { ...v, down_kbit_s: +(v.down * 8 / 1000).toFixed(1), up_kbit_s: +(v.up * 8 / 1000).toFixed(1) }])),
  machine_before: machine(), runs: [] };
const browser = await launch(GL_ARGS);
result.browser = { name: "chromium-headless-shell (playwright-core 1.65.0)", version: browser.version() };
try {
  for (const enc of encodings) {
    const srv = await startReplayServer(0, "127.0.0.1", { force: enc });
    const url = `http://127.0.0.1:${srv.server.address().port}/`;
    for (const prof of profiles) {
      const cond = PROFILES[prof], rows = [];
      for (let i = 0; i < repeat; i++) {
        const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, serviceWorkers: "block" }); // new context = empty HTTP cache
        const page = await ctx.newPage(), cdp = await ctx.newCDPSession(page), logs = [];
        page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`)); page.on("console", (m) => m.type() === "error" && logs.push(m.text()));
        await cdp.send("Network.enable"); await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
        await cdp.send("Network.emulateNetworkConditions", cond ? { offline: false, latency: cond.latency, downloadThroughput: cond.down, uploadThroughput: cond.up } : { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
        srv.log.length = 0;
        const t0 = performance.now(), load = os.loadavg()[0];
        await page.goto(url, { waitUntil: "commit" });
        await page.waitForFunction(() => window.__A0_02C_RESULT || window.__A0_02C_ERROR, null, { timeout: 170_000, polling: 25 });
        const wall = performance.now() - t0, err = await page.evaluate(() => window.__A0_02C_ERROR);
        if (err) { console.error(enc, prof, err, logs); process.exitCode = 1; await ctx.close(); continue; }
        const r = await page.evaluate(() => window.__A0_02C_RESULT);
        if (!r.first_frame_pixel_ok) { console.error(enc, prof, "first frame pixel check failed", r.first_frame_pixel); process.exitCode = 1; }
        if (i === 0 && prof === profiles[0] && enc === encodings.at(-1)) await page.screenshot({ path: join(OUT, `replay-${GL}.png`) }); // evidence for DoD 3: what the first frames look like
        const m = r.marks, wire = srv.log.reduce((s, e) => s + e.bytes, 0);
        rows.push({ first_frame_ms: m.first_frame, script_start_ms: m.script_start, fetched_ms: m.fetched, verified_ms: m.verified, scene_built_ms: m.scene_built, runner_wall_ms: wall,
          html_response_start_ms: r.navigation.response_start, load_event_end_ms: r.navigation.load_event_end, wire_bytes_server_log: wire, requests: srv.log.length, pixel_ok: r.first_frame_pixel_ok, first_frame_check: r.first_frame_check, load_avg_1m: +load.toFixed(1), console_errors: logs,
          resources: r.resources.map((x) => ({ url: x.url, start: +x.start.toFixed(1), response_end: +x.response_end.toFixed(1), transfer_size: x.transfer_size, decoded: x.decoded_body_size })), webgl_renderer: r.webgl_renderer });
        await ctx.close();
      }
      const ff = rows.map((r) => r.first_frame_ms);
      result.runs.push({ encoding: enc, profile: prof, n: rows.length, first_frame_ms: summarize(ff), wire_bytes: rows[0]?.wire_bytes_server_log, rows });
      console.log(`${enc.padEnd(8)} ${prof.padEnd(7)} first frame p50 ${summarize(ff).p50} ms (min ${summarize(ff).min}, max ${summarize(ff).max}), wire ${rows[0]?.wire_bytes_server_log} B, n=${rows.length}`);
    }
    srv.close();
  }
} finally {
  result.machine_after = machine();
  await browser.close();
  writeFileSync(join(OUT, process.env.RESULT_NAME ?? "replay.json"), JSON.stringify(result, null, 1) + "\n");
}
