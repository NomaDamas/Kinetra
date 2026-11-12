import test from "node:test";
import assert from "node:assert/strict";
import { WebSocket } from "ws";
import { startServer, resolveUrl, guardPassedFromEnv } from "../src/serve.mjs";
import { buildFrame } from "../src/stream.mjs";
import { readHeader, poseView, frameBytes } from "../src/frame.js";
import { makeWorld, fillPoses } from "../src/poses.js";

test("buildFrame = header + fillPoses", () => {
  const w = makeWorld(50, 3), buf = buildFrame(w, 7, { state: 1, seq: 9 }, new ArrayBuffer(frameBytes(50)));
  assert.deepEqual(readHeader(buf), { tick: 7, n: 50, simTime: 7 / 60, ctrlState: 1, ctrlSeq: 9 });
  const ref = new Float32Array(350); fillPoses(w, 7, 1, ref);
  assert.deepEqual([...poseView(buf, 50)], [...ref]);
});
test("static server refuses path escapes and unknown paths", () => {
  assert.equal(resolveUrl("/src/../../../etc/passwd"), null);
  assert.equal(resolveUrl("/three/..%2f..%2fpackage.json"), null);
  assert.equal(resolveUrl("/nope"), null);
  assert.ok(resolveUrl("/src/frame.js").endsWith("src/frame.js"));
});
test("websocket streams contiguous frames (ticks 0,1,2,...) of the right size and applies a control message", async () => {
  const s = await startServer(0), port = s.server.address().port;
  try {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200&seed=0`, { origin: `http://127.0.0.1:${port}` });
    const got = []; let sent = false;
    await new Promise((res, rej) => {
      ws.on("error", rej);
      ws.on("message", (d, bin) => {
        assert.ok(bin); const ab = d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength); assert.equal(ab.byteLength, frameBytes(200));
        got.push(readHeader(ab));
        if (got.length === 5 && !sent) { sent = true; const m = Buffer.alloc(8); m.writeUInt32LE(5, 0); m.writeUInt32LE(1, 4); ws.send(m); }
        if (got.at(-1).ctrlSeq === 5) res();
        if (got.length > 120) rej(new Error("control never applied"));
      });
    });
    assert.deepEqual(got.map((h) => h.tick), got.map((_, i) => i)); // contiguous ticks from 0
    assert.equal(got.at(-1).ctrlState, 1);
    ws.close();
  } finally { s.close(); }
});
test("websocket rejects a bad body count", async () => {
  const s = await startServer(0), port = s.server.address().port;
  try {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/pose?n=1`, { origin: `http://127.0.0.1:${port}` });
    await new Promise((res) => { ws.on("error", res); ws.on("close", res); });
  } finally { s.close(); }
});
test("an oversized control message ends that stream only: the server keeps serving new connections", async () => {
  const s = await startServer(0, "127.0.0.1", { guardPassed: true }), port = s.server.address().port;
  try {
    const bad = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200`, { origin: `http://127.0.0.1:${port}` });
    await new Promise((res, rej) => { bad.on("open", () => bad.send(Buffer.alloc(4096))); bad.on("close", res); bad.on("error", () => {}); setTimeout(() => rej(new Error("bad connection not closed")), 3000); });
    assert.equal(s.streams[0].stats.socket_errors, 1);
    const good = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200`, { origin: `http://127.0.0.1:${port}` });
    const h = await new Promise((res, rej) => { good.on("message", (d) => res(readHeader(d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength)))); good.on("error", rej); });
    assert.equal(h.n, 200); good.close();
  } finally { s.close(); }
});
test("1,000+ bodies are refused outside the resource guard, 999 and guarded runs are served", async () => {
  assert.equal(guardPassedFromEnv({}), false);
  assert.equal(guardPassedFromEnv({ KINETRA_GUARD_PASSED: "1" }), true);
  assert.equal(guardPassedFromEnv({ CI: "true" }), true);
  const open = (port, n) => new Promise((res) => { const w = new WebSocket(`ws://127.0.0.1:${port}/pose?n=${n}`, { origin: `http://127.0.0.1:${port}` }); w.on("open", () => { w.close(); res("open"); }); w.on("error", () => res("refused")); w.on("unexpected-response", (_q, r) => res(`http ${r.statusCode}`)); });
  const u = await startServer(0, "127.0.0.1", { guardPassed: false });
  try { assert.equal(await open(u.server.address().port, 1000), "http 403"); assert.equal(await open(u.server.address().port, 5000), "http 403"); assert.equal(await open(u.server.address().port, 999), "open"); } finally { u.close(); }
  const g = await startServer(0, "127.0.0.1", { guardPassed: true });
  try { assert.equal(await open(g.server.address().port, 5000), "open"); } finally { g.close(); }
});
test("a malformed request target is a 400 and the server stays up", async () => {
  const s = await startServer(0, "127.0.0.1", { guardPassed: true }), port = s.server.address().port;
  try {
    const net = await import("node:net");
    const raw = (target) => new Promise((res) => { const c = net.connect(port, "127.0.0.1", () => c.write(`GET ${target} HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n`)); let b = ""; c.on("data", (d) => (b += d)); c.on("close", () => res(b.split("\r\n")[0])); });
    assert.match(await raw("//"), /400/);
    assert.match(await raw("/nope"), /404/);
    const r = await fetch(`http://127.0.0.1:${port}/`); assert.equal(r.status, 200);
  } finally { s.close(); }
});
test("WebSocket Origin: only the server's own origin is accepted, others and a missing Origin get 403", async () => {
  const s = await startServer(0, "127.0.0.1", { guardPassed: true }), port = s.server.address().port;
  try {
    const open = (origin) => new Promise((res) => {
      const w = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200`, origin === undefined ? {} : { origin });
      w.on("open", () => { w.close(); res("open"); }); w.on("error", () => {}); w.on("unexpected-response", (_q, r) => res(`http ${r.statusCode}`));
    });
    assert.equal(await open(`http://127.0.0.1:${port}`), "open");
    assert.equal(await open(`http://localhost:${port}`), "open");
    assert.equal(await open("https://evil.example"), "http 403");
    assert.equal(await open(`http://127.0.0.1:${port + 1}`), "http 403");   // same host, other port
    assert.equal(await open(`http://localhost.evil.example:${port}`), "http 403");
    assert.equal(await open("null"), "http 403");
    assert.equal(await open(undefined), "http 403");
    assert.equal(s.streams.length, 2, "rejected upgrades must not create streams");
  } finally { s.close(); }
});
