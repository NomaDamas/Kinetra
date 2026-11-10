// Needs the Playwright browser (see docs/process/design-workflow.md). Fails, not skips, when it is missing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createServer as createHttp } from "node:http";
import { createServer as createTcp } from "node:net";
import type { AddressInfo } from "node:net";
import { writeFileSync } from "node:fs";
import { chromium } from "playwright-core";
import {
  allowedOrigins, applyNetworkPolicy, compareScreen, ConfigError, isAllowedRequest, isAllowedSocket, loadScreens, shoot, validateScreen,
} from "../compare.ts";

const COMPARE = fileURLToPath(new URL("../compare.ts", import.meta.url));
const SIDE = { url: "design/exports/design-system/index.html", selector: "#valuebadges" };

test("_trial: approved render vs an unmodified copy passes", async () => {
  const out = mkdtempSync(join(tmpdir(), "kin-compare-"));
  try {
    const screens = await loadScreens();
    const outcomes = await compareScreen("_trial", screens["_trial"]!, out);
    assert.ok(outcomes.length >= 2);
    for (const o of outcomes) {
      assert.equal(o.pass, true, `${o.pair}: ${o.reasons.join("; ")}`);
      assert.equal(o.diffPixels, 0, `${o.pair} must render identically twice`);
      assert.ok(existsSync(o.files.diff));
    }
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("_trial-shifted: a deliberately shifted copy fails and writes a diff image", async () => {
  const out = mkdtempSync(join(tmpdir(), "kin-compare-"));
  try {
    const screens = await loadScreens();
    const outcomes = await compareScreen("_trial-shifted", screens["_trial-shifted"]!, out);
    assert.ok(outcomes.length >= 1);
    for (const o of outcomes) {
      assert.equal(o.pass, false, `${o.pair} must fail`);
      assert.ok(o.diffPixels > 0);
      assert.ok(existsSync(o.files.diff));
    }
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("an exception without a reason is rejected before anything is rendered", async () => {
  const out = mkdtempSync(join(tmpdir(), "kin-compare-"));
  try {
    const side = SIDE;
    await assert.rejects(
      compareScreen("_no-reason", { pairs: [{ name: "x", approved: side, implemented: side, tolerance: { maxDiffRatio: 0.5 } }] }, out),
      (e) => e instanceof ConfigError && /needs a "reason"/.test(e.message),
    );
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("config errors are ConfigError: empty pairs, bad tolerance key, non-local url, duplicate name", () => {
  const bad = (screen: unknown, re: RegExp) =>
    assert.throws(() => validateScreen("s", screen as never), (e) => e instanceof ConfigError && re.test(e.message));
  bad({ pairs: [] }, /"pairs" is empty/);
  bad({}, /"pairs" must be an array/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: SIDE, reason: "r", tolerance: { maxIgnoredRatio: 1 } }] }, /unknown tolerance key/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: SIDE, reason: "r", tolerance: { maxDiffRatio: -1 } }] }, /finite number/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: { url: "https://example.com/" } }] }, /must be a local server/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: { url: "http://127.0.0.1.evil.com/" } }] }, /must be a local server/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: SIDE }, { name: "x", approved: SIDE, implemented: SIDE }] }, /duplicate/);
  validateScreen("s", { pairs: [{ name: "ok", approved: SIDE, implemented: { url: "http://localhost:5173/" } }] });
});

test("an empty screen exits compareScreen with ConfigError before any browser starts", async () => {
  await assert.rejects(compareScreen("e", { pairs: [] }, tmpdir()), ConfigError);
});

test("CLI: usage errors, unknown screen exit 2", () => {
  const run = (...args: string[]) => spawnSync(process.execPath, [COMPARE, ...args], { encoding: "utf8" });
  assert.equal(run().status, 2);
  assert.equal(run("--bogus").status, 2);
  const r = run("--screen", "no-such-screen");
  assert.equal(r.status, 2);
  assert.match(r.stderr, /not in tools\/design\/screens\.json/);
});

test("request allow-list uses the parsed origin, not a string prefix", () => {
  const origins = allowedOrigins("http://127.0.0.1:5173/app");
  assert.equal(isAllowedRequest("http://127.0.0.1:5173/assets/a.js", origins), true);
  assert.equal(isAllowedRequest("file:///tmp/x.html", origins), true);
  assert.equal(isAllowedRequest("http://127.0.0.1:5173.evil.com/a.js", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1:5173@evil.com/a.js", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1.evil.com/a.js", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1:5174/a.js", origins), false);
  assert.equal(isAllowedRequest("https://127.0.0.1:5173/a.js", origins), false);
  assert.equal(isAllowedRequest("https://fonts.googleapis.com/css2", origins), false);
  assert.equal(isAllowedRequest("not a url", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1:5173/a.js", allowedOrigins("design/exports/x/index.html")), false);
});

test("ws(s) urls use the same parsed-origin allow-list", () => {
  const origins = allowedOrigins("http://127.0.0.1:5173/");
  assert.equal(isAllowedSocket("ws://127.0.0.1:5173/hmr", origins), true);
  assert.equal(isAllowedSocket("wss://127.0.0.1:5173/hmr", origins), false);
  assert.equal(isAllowedSocket("ws://127.0.0.1:5174/hmr", origins), false);
  assert.equal(isAllowedSocket("ws://127.0.0.1:5173.evil.com/", origins), false);
  assert.equal(isAllowedSocket("ws://evil.com/", origins), false);
  assert.equal(isAllowedSocket("http://127.0.0.1:5173/", origins), false);
  assert.equal(isAllowedSocket("junk", origins), false);
});

test("an external ws:// from a page never reaches the network", async () => {
  // "External" = any origin other than the page's own. The probe is a raw TCP server on another port
  // that counts connections; the page tries to open a WebSocket to it.
  let hits = 0;
  const probe = createTcp((sock) => { hits++; sock.destroy(); });
  await new Promise<void>((ok) => probe.listen(0, "127.0.0.1", ok));
  const probePort = (probe.address() as AddressInfo).port;
  const web = createHttp((_req, res) => {
    res.setHeader("content-type", "text/html");
    res.end(`<!doctype html><body><script>
      window.result = new Promise((done) => {
        const ws = new WebSocket("ws://127.0.0.1:${probePort}/x");
        ws.onclose = (e) => done("closed:" + e.code);
        ws.onerror = () => done("error");
        setTimeout(() => done("timeout"), 4000);
      });
    </script></body>`);
  });
  await new Promise<void>((ok) => web.listen(0, "127.0.0.1", ok));
  const webPort = (web.address() as AddressInfo).port;
  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext();
    await applyNetworkPolicy(ctx, allowedOrigins(`http://127.0.0.1:${webPort}/`));
    const page = await ctx.newPage();
    await page.goto(`http://127.0.0.1:${webPort}/`);
    const outcome = await page.evaluate(() => (window as unknown as { result: Promise<string> }).result);
    assert.equal(outcome, "closed:1008");
    await new Promise((r) => setTimeout(r, 300));
    assert.equal(hits, 0, "the blocked socket must not connect to the other origin");
    await ctx.close();
  } finally {
    await browser.close();
    web.close();
    probe.close();
  }
});

test("animations are frozen before ignore rectangles are measured", async () => {
  const dir = mkdtempSync(join(tmpdir(), "kin-anim-"));
  const file = join(dir, "page.html");
  // The animation holds the box 300px to the right forever. At rest it is at left 40px.
  writeFileSync(file, `<!doctype html><style>
    body{margin:0} #box{width:50px;height:20px;margin-left:40px;background:#123;animation:m 1s linear infinite}
    @keyframes m{from{margin-left:300px}to{margin-left:300px}}
  </style><div id="box"></div>`);
  const browser = await chromium.launch();
  try {
    const { ignore } = await shoot(browser, { url: file, selector: "html" }, { width: 800, height: 200 }, ["#box"]);
    assert.equal(ignore.length, 1);
    assert.equal(ignore[0]!.x, 40, "the rectangle must be at the resting position, not the animated one");
    assert.equal(ignore[0]!.width, 50);
  } finally {
    await browser.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
