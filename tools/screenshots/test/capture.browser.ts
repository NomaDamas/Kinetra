// Needs the Playwright browser and the resource guard locally (`pnpm --filter @kinetra/screenshots test:browser`).
// Fails, not skips, when the browser is missing.
import "./require-guard.ts"; // first: refuses to run outside the resource guard
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { chromium } from "playwright-core";
import { PNG } from "pngjs";
import { captureAll, validateConfig } from "../capture.ts";
import { runAll, runWebgl, FLAG_SETS, WEBGL_FLAGS } from "../webgl-check.ts";

test("captureAll: captures an existing page at the viewport size, skips a missing one with a reason, writes the manifest", async () => {
  const root = mkdtempSync(join(tmpdir(), "kin-shot-"));
  const out = join(root, "out");
  try {
    mkdirSync(join(root, "d"));
    writeFileSync(join(root, "d", "a.html"), '<body style="margin:0;background:#0a0"><div id="x" style="width:50px;height:30px;background:#00f"></div></body>');
    const cfg = validateConfig({
      viewport: { width: 320, height: 200 },
      screens: [
        { name: "page", path: "d/a.html" },
        { name: "el", path: "d/a.html", selector: "#x" },
        { name: "gone", path: "d/missing.html" },
      ],
    });
    const browser = await chromium.launch();
    try {
      const o = await captureAll(cfg, out, browser, root);
      assert.deepEqual(o.map((x) => x.status), ["captured", "captured", "skipped"]);
      assert.equal(o[2]!.reason, "path not found");
      const page = PNG.sync.read(readFileSync(join(out, "page.png")));
      assert.deepEqual([page.width, page.height], [320, 200]);
      const at = (x: number, y: number) => [...page.data.subarray((y * page.width + x) * 4, (y * page.width + x) * 4 + 3)];
      assert.deepEqual(at(0, 0), [0, 0, 255]); // the 50x30 div sits at the page origin
      assert.deepEqual(at(200, 120), [0, 170, 0]); // outside it: page background #0a0
      const el = PNG.sync.read(readFileSync(join(out, "el.png")));
      assert.deepEqual([el.width, el.height], [50, 30]);
      assert.deepEqual([...el.data.subarray(0, 3)], [0, 0, 255]);
      const m = JSON.parse(readFileSync(join(out, "manifest.json"), "utf8"));
      assert.equal(m.screens.length, 3);
      assert.match(m.screens[0].sha256, /^[0-9a-f]{64}$/);
    } finally {
      await browser.close();
    }
  } finally {
    rmSync(root, { recursive: true });
  }
});

test("captureAll: external requests are blocked and recorded; none reaches a server on another local port", async () => {
  const hits: string[] = [];
  const server = createServer((req, res) => { hits.push(req.url ?? ""); res.writeHead(200, { "content-type": "image/png" }).end(); });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as AddressInfo).port;
  const root = mkdtempSync(join(tmpdir(), "kin-shot-"));
  try {
    writeFileSync(join(root, "n.html"), `<body><img src="http://127.0.0.1:${port}/img.png" width="10" height="10"><script src="http://localhost:${port}/s.js"></script><script>fetch("http://127.0.0.1:${port}/f").catch(()=>{});try{new WebSocket("ws://127.0.0.1:${port}/ws")}catch(e){}</script><p id="ok">ok</p></body>`);
    const browser = await chromium.launch();
    try {
      const [o] = await captureAll(validateConfig({ viewport: { width: 200, height: 100 }, screens: [{ name: "n", path: "n.html" }] }), join(root, "out"), browser, root);
      assert.equal(o!.status, "captured"); // the page still rendered
      assert.ok((o!.blocked_requests?.length ?? 0) >= 3, `blocked: ${JSON.stringify(o!.blocked_requests)}`); // img, script, fetch (+ websocket)
      assert.ok(o!.blocked_requests!.some((u) => u.includes("/img.png")));
      assert.deepEqual(hits, [], "a request reached the local probe server");
      const m = JSON.parse(readFileSync(join(root, "out", "manifest.json"), "utf8"));
      assert.ok(m.screens[0].blocked_requests.length >= 3); // recorded in the artifact manifest too
    } finally {
      await browser.close();
    }
  } finally {
    await new Promise((r) => server.close(r));
    rmSync(root, { recursive: true });
  }
});

test("control: without the block the same page DOES reach the local server (the test above can fail)", async () => {
  const hits: string[] = [];
  const server = createServer((req, res) => { hits.push(req.url ?? ""); res.writeHead(200, { "content-type": "image/png" }).end(); });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as AddressInfo).port;
  const browser = await chromium.launch();
  try {
    const page = await (await browser.newContext()).newPage();
    await page.setContent(`<img src="http://127.0.0.1:${port}/img.png">`);
    await page.waitForLoadState("load");
    assert.ok(hits.includes("/img.png"), `hits: ${JSON.stringify(hits)}`);
  } finally {
    await browser.close();
    await new Promise((r) => server.close(r));
  }
});

test("WebGL renders headless with the chosen flags: clear color, triangle center and triangle area are the expected pixels", async () => {
  const r = await runWebgl(WEBGL_FLAGS);
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.deepEqual(r.measured!.center.slice(0, 3), [255, 0, 0]);
  assert.deepEqual(r.measured!.background.slice(0, 3), [26, 102, 204]);
});

test("WebGL probe: a flag set whose browser cannot launch is recorded as failed and the probe goes on", async () => {
  const names = Object.keys(FLAG_SETS);
  const results = await runAll(names, undefined, (options) =>
    // the second flag set gets a bogus executable: launch throws; every other set launches the real browser
    chromium.launch(options.args?.includes("--use-angle=swiftshader") && !options.args.includes("--enable-unsafe-swiftshader") ? { ...options, executablePath: "/nonexistent/chromium" } : options));
  assert.deepEqual(results.map((r) => r.flags), names);
  const bad = results.find((r) => r.flags === "swiftshader")!;
  assert.equal(bad.ok, false);
  assert.match(bad.error ?? "", /nonexistent|Executable|ENOENT|spawn/i);
  assert.equal(bad.gl, null);
  for (const r of results.filter((x) => x.flags !== "swiftshader")) assert.equal(r.ok, true, `${r.flags}: ${r.error}`);
});

test("WebGL probe: a launcher that always throws gives one failed result per flag set, never an exception", async () => {
  const results = await runAll(Object.keys(FLAG_SETS), undefined, async () => { throw new Error("boom: cannot launch"); });
  assert.equal(results.length, Object.keys(FLAG_SETS).length);
  assert.ok(results.every((r) => !r.ok && r.error === "boom: cannot launch"));
});
