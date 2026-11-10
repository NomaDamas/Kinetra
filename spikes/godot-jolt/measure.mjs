// A0-03b: load a Godot Web export in headless Chromium and record download sizes, time to the first physics step and the
// result of the in-page 200-body run. Measurement only. Refuses to start outside the P0-09 resource guard.
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/godot-jolt measure \
//     -- --dir /tmp/godot-web-out --name threads --isolated --out ../results/a0-03b-web-threads.json
// Chromium: reuses the Playwright chromium-headless-shell already in ~/Library/Caches/ms-playwright (no new download).
import { chromium } from "playwright-core";
import { gzipSync, brotliCompressSync } from "node:zlib";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { startServer } from "./serve.mjs";

if (process.env.KINETRA_GUARD_PASSED !== "1") {
  console.error("measure.mjs must run under tools/dev/resource_guard.py --profile heavy -- <cmd> (docs/process/dev-resources.md)");
  process.exit(2);
}
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const dir = resolve(arg("--dir", ""));
const name = arg("--name", "export");
const isolated = process.argv.includes("--isolated");
const out = arg("--out", null);
const timeoutMs = Number(arg("--timeout-ms", "120000"));

const files = readdirSync(dir).map((f) => {
  const buf = readFileSync(join(dir, f));
  return { file: f, bytes: statSync(join(dir, f)).size, gzip_bytes: gzipSync(buf, { level: 6 }).length, brotli_bytes: brotliCompressSync(buf).length };
});
const total = (k) => files.reduce((s, f) => s + f[k], 0);

const server = await startServer(dir, { crossOriginIsolated: isolated });
const url = `http://127.0.0.1:${server.address().port}/index.html`;
const browser = await chromium.launch({ headless: true });
const result = { name, cross_origin_isolated_headers: isolated, files, total_bytes: total("bytes"), total_gzip_bytes: total("gzip_bytes"), total_brotli_bytes: total("brotli_bytes"), browser: { name: "chromium-headless-shell (playwright-core 1.65.0)", version: browser.version() } };
try {
  const page = await browser.newPage();
  const logs = [];
  page.on("console", (m) => logs.push(m.text()));
  page.on("pageerror", (e) => logs.push("PAGEERROR " + e.message));
  const t0 = Date.now();
  await page.goto(url, { waitUntil: "load" });
  result.load_event_ms = Date.now() - t0;
  result.cross_origin_isolated = await page.evaluate(() => self.crossOriginIsolated);
  result.shared_array_buffer = await page.evaluate(() => typeof SharedArrayBuffer !== "undefined");
  const ok = await page.waitForFunction(() => window.__godot_result, null, { timeout: timeoutMs }).then(() => true, () => false);
  result.ran = ok;
  result.ms_to_result = Date.now() - t0;
  result.page_result = ok ? await page.evaluate(() => window.__godot_result) : null;
  result.console = logs.slice(-12);
  result.navigation_timing = await page.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0];
    return { dom_content_loaded_ms: Math.round(n.domContentLoadedEventEnd), load_event_ms: Math.round(n.loadEventEnd) };
  });
} finally {
  await browser.close();
  server.close();
}
const text = JSON.stringify(result, null, 1) + "\n";
if (out) writeFileSync(resolve(out), text); else process.stdout.write(text);
