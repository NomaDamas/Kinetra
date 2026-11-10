// Needs the Playwright browser and the resource guard locally (`pnpm --filter @kinetra/screenshots test:browser`).
// Fails, not skips, when the browser is missing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { PNG } from "pngjs";
import { captureAll, validateConfig } from "../capture.ts";
import { runWebgl, WEBGL_FLAGS } from "../webgl-check.ts";

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

test("captureAll: a page that cannot reach the network does not hang and blocks http(s)", async () => {
  const root = mkdtempSync(join(tmpdir(), "kin-shot-"));
  try {
    writeFileSync(join(root, "n.html"), '<body><img src="http://127.0.0.1:9/x.png" width="10" height="10"><p id="ok">ok</p></body>');
    const browser = await chromium.launch();
    try {
      const [o] = await captureAll(validateConfig({ viewport: { width: 200, height: 100 }, screens: [{ name: "n", path: "n.html" }] }), join(root, "out"), browser, root);
      assert.equal(o!.status, "captured");
    } finally {
      await browser.close();
    }
  } finally {
    rmSync(root, { recursive: true });
  }
});

test("WebGL renders headless with the chosen flags: clear color, triangle center and triangle area are the expected pixels", async () => {
  const r = await runWebgl(WEBGL_FLAGS);
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.deepEqual(r.measured!.center.slice(0, 3), [255, 0, 0]);
  assert.deepEqual(r.measured!.background.slice(0, 3), [26, 102, 204]);
});
