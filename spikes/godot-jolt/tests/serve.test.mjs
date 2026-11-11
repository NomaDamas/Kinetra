import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveUrl, startServer } from "../serve.mjs";

test("resolveUrl stays inside the export directory", () => {
  assert.equal(resolveUrl("/r", "/"), "/r/index.html");
  assert.equal(resolveUrl("/r", "/index.wasm"), "/r/index.wasm");
  assert.equal(resolveUrl("/r", "/../etc/passwd"), null);
  assert.equal(resolveUrl("/r", "/a/../../x"), null);
});

test("server sets COOP/COEP only when asked, wasm type, 404 elsewhere, loopback only", async () => {
  const dir = mkdtempSync(join(tmpdir(), "godot-serve-"));
  writeFileSync(join(dir, "index.html"), "<html></html>");
  writeFileSync(join(dir, "index.wasm"), "\0asm");
  const on = await startServer(dir, { crossOriginIsolated: true });
  const off = await startServer(dir, { crossOriginIsolated: false });
  try {
    assert.equal(on.address().address, "127.0.0.1");
    const a = await fetch(`http://127.0.0.1:${on.address().port}/index.wasm`);
    assert.equal(a.headers.get("content-type"), "application/wasm");
    assert.equal(a.headers.get("cross-origin-opener-policy"), "same-origin");
    assert.equal(a.headers.get("cross-origin-embedder-policy"), "require-corp");
    const b = await fetch(`http://127.0.0.1:${off.address().port}/`);
    assert.equal(b.status, 200);
    assert.equal(b.headers.get("cross-origin-opener-policy"), null);
    assert.equal((await fetch(`http://127.0.0.1:${on.address().port}/nope`)).status, 404);
  } finally {
    on.close(); off.close(); rmSync(dir, { recursive: true });
  }
});
