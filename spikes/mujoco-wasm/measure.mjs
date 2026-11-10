// Headless Chromium (Playwright's own build, throwaway profile) runner for the A0-01b measurement page.
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/mujoco-wasm measure
// Writes results/wasm-chromium.json and results/page.png. Refuses to start outside the P0-09 resource guard.
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startServer } from "./serve.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
if (process.env.KINETRA_GUARD_PASSED !== "1") {
  console.error("measure.mjs is a heavy run (docs/process/dev-resources.md). Start it through the guard:\n  uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/mujoco-wasm measure");
  process.exit(2);
}
const sh = (cmd, args) => { try { return execFileSync(cmd, args, { encoding: "utf8" }).trim(); } catch { return null; } };
const query = process.argv[2] ?? ""; // e.g. "?bare=3&loops=1"
const server = await startServer(0);
const url = `http://127.0.0.1:${server.address().port}/${query}`;
mkdirSync(join(HERE, "results"), { recursive: true });
const loadBefore = os.loadavg();
const browser = await chromium.launch({ headless: true }); // fresh temporary user-data-dir, removed on close
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const logs = [];
  page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
  await page.goto(url);
  await page.waitForFunction(() => window.__A0_01B_RESULT || window.__A0_01B_ERROR, null, { timeout: 240_000 });
  const err = await page.evaluate(() => window.__A0_01B_ERROR);
  if (err) { console.error(err, logs); process.exitCode = 1; }
  else {
    const result = await page.evaluate(() => window.__A0_01B_RESULT);
    result.browser = { name: "chromium-headless-shell (playwright 1.65.0)", version: browser.version() };
    result.machine = {
      cpu: sh("sysctl", ["-n", "machdep.cpu.brand_string"]), ncpu: os.cpus().length, platform: `${os.type()} ${os.release()} ${os.arch()}`,
      load_avg_before: loadBefore, load_avg_after: os.loadavg(), swap: sh("sysctl", ["-n", "vm.swapusage"]), node: process.version,
    };
    result.query = query; result.console = logs;
    writeFileSync(join(HERE, "results", process.env.RESULT_NAME ?? "wasm-chromium.json"), JSON.stringify(result, null, 1) + "\n");
    await page.screenshot({ path: join(HERE, "results", "page.png"), fullPage: true });
    console.log(JSON.stringify({ parity: result.parity.map((p) => [p.id, p.max_pos_err_m, p.max_ang_err_rad]), bare: [result.bare.steps_per_s_median, result.bare.rtf_median], uncapped_fps: result.uncapped.frames_per_s, frames: [result.frames.mean_fps, result.frames.frame_interval_ms.p95, result.frames.work_ms_per_frame.median] }));
  }
} finally {
  await browser.close();
  server.close();
}
