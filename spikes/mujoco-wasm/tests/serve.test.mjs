import test from "node:test";
import assert from "node:assert/strict";
import { resolveUrl, startServer } from "../serve.mjs";

test("resolveUrl maps only the mounted directories and rejects path escapes", () => {
  assert.match(resolveUrl("/"), /index\.html$/);
  assert.match(resolveUrl("/vendor/mujoco/mujoco.wasm"), /@mujoco[\\/]mujoco[\\/]mujoco\.wasm$/);
  assert.match(resolveUrl("/reference/manifest.json"), /reference[\\/]manifest\.json$/);
  assert.equal(resolveUrl("/vendor/mujoco/../../../package.json"), null);
  assert.equal(resolveUrl("/src/../serve.mjs"), null);
  assert.equal(resolveUrl("/package.json"), null);
  assert.equal(resolveUrl("/etc/passwd"), null);
});

test("server serves the page and the wasm with the right types, 404 elsewhere, loopback only", async () => {
  const server = await startServer(0);
  try {
    const base = `http://127.0.0.1:${server.address().port}`;
    assert.equal(server.address().address, "127.0.0.1");
    const page = await fetch(`${base}/`);
    assert.equal(page.status, 200);
    assert.match(await page.text(), /A0-01b/);
    const wasm = await fetch(`${base}/vendor/mujoco/mujoco.wasm`);
    assert.equal(wasm.headers.get("content-type"), "application/wasm");
    assert.equal((await fetch(`${base}/package.json`)).status, 404);
    assert.equal((await fetch(`${base}/vendor/mujoco/nope.js`)).status, 404);
  } finally {
    server.close();
  }
});
