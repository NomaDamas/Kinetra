import test from "node:test";
import assert from "node:assert/strict";
import zlib from "node:zlib";
import { resolveUrl, pickEncoding, startReplayServer } from "../src/replay-serve.mjs";

test("pickEncoding prefers br, then gzip, honours q=0", () => {
  assert.equal(pickEncoding("gzip, deflate, br, zstd"), "br");
  assert.equal(pickEncoding("gzip, deflate"), "gzip");
  assert.equal(pickEncoding("br;q=0, gzip"), "gzip");
  assert.equal(pickEncoding(""), "identity");
  assert.equal(pickEncoding(undefined), "identity");
});
test("resolveUrl: fixed mounts only, no escapes", () => {
  assert.ok(resolveUrl("/").endsWith("replay.html"));
  assert.ok(resolveUrl("/replay/poses.bin").endsWith("replay/poses.bin"));
  assert.equal(resolveUrl("/replay/../package.json"), null);
  assert.equal(resolveUrl("/replay/..%2fpackage.json"), null);
  assert.equal(resolveUrl("/src/replay-serve.mjs"), null);
});
test("server sends the committed bundle byte-exact in every encoding, logs wire bytes", async () => {
  const bundle = await (await import("node:fs/promises")).readFile(new URL("../replay/bundle.json", import.meta.url));
  for (const force of ["identity", "gzip", "br"]) {
    const s = await startReplayServer(0, "127.0.0.1", { force }), port = s.server.address().port;
    try {
      const r = await fetch(`http://127.0.0.1:${port}/replay/bundle.json`, { headers: { "accept-encoding": "identity" } });
      assert.equal(r.status, 200);
      const wire = s.log.at(-1);
      assert.equal(wire.encoding, force);
      const body = Buffer.from(await (await fetch(`http://127.0.0.1:${port}/replay/bundle.json`)).arrayBuffer()); // fetch decodes content-encoding
      assert.deepEqual(body, bundle);
      if (force !== "identity") assert.ok(wire.bytes < bundle.length);
    } finally { s.close(); }
  }
  assert.ok(zlib.gunzipSync(zlib.gzipSync(bundle)).equals(bundle));
});
test("unknown path is 404 and logged", async () => {
  const s = await startReplayServer(0), port = s.server.address().port;
  try { assert.equal((await fetch(`http://127.0.0.1:${port}/nope`)).status, 404); assert.equal(s.log.at(-1).status, 404); } finally { s.close(); }
});
test("a malformed request target is a 400 and the server keeps serving", async () => {
  const s = await startReplayServer(0, "127.0.0.1", { force: "identity" }), port = s.server.address().port;
  try {
    const net = await import("node:net");
    const raw = (target) => new Promise((res) => { const c = net.connect(port, "127.0.0.1", () => c.write(`GET ${target} HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n`)); let b = ""; c.on("data", (d) => (b += d)); c.on("close", () => res(b.split("\r\n")[0])); });
    assert.match(await raw("//"), /400/);
    assert.equal(s.log.at(-1).status, 400);
    assert.match(await raw("/nope"), /404/);
    assert.equal((await fetch(`http://127.0.0.1:${port}/replay/bundle.json`)).status, 200);
  } finally { s.close(); }
});
