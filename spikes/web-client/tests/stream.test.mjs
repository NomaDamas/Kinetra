import test from "node:test";
import assert from "node:assert/strict";
import { WebSocket } from "ws";
import { startServer, resolveUrl, guardPassedFromEnv } from "../src/serve.mjs";
import { buildFrame } from "../src/stream.mjs";
import { readHeader, poseView, frameBytes, writeControl, writeAck } from "../src/frame.js";
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
        if (got.length === 5 && !sent) { sent = true; ws.send(writeControl(5, 1)); }
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

// --- A0-02a-f: ack-based flow control ---
const frameOf = (d) => readHeader(d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength));
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));
async function ackStream(win, query = "") {
  const s = await startServer(0), port = s.server.address().port;
  const ws = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200&flow=ack&win=${win}${query}`, { origin: `http://127.0.0.1:${port}` });
  const ticks = []; ws.on("message", (d) => ticks.push(frameOf(d).tick));
  await new Promise((res, rej) => { ws.on("open", res); ws.on("error", rej); });
  return { s, ws, ticks, st: () => s.streams[0].stats, done: () => { ws.close(); s.close(); } };
}
test("flow=ack: a client that never acks gets exactly `win` frames, then the core skips ticks instead of queueing them", async () => {
  const c = await ackStream(3);
  try {
    await sleepMs(400);
    assert.deepEqual(c.ticks, [0, 1, 2]);
    assert.equal(c.st().sent, 3);
    assert.ok(c.st().window_skipped >= 15, `skipped ${c.st().window_skipped}`); // ~24 ticks in 400 ms at 60 Hz
    assert.equal(c.st().backpressure_skipped, 0); // bufferedAmount is not the limiter in this mode
  } finally { c.done(); }
});
test("flow=ack: an ack frees slots and the next frame sent is the NEWEST tick, not the next one in line", async () => {
  const c = await ackStream(2);
  try {
    await sleepMs(300);
    assert.deepEqual(c.ticks, [0, 1]);
    c.ws.send(writeAck(1));
    await sleepMs(150);
    assert.equal(c.ticks.length, 4); // both slots freed by one cumulative ack
    assert.ok(c.ticks[2] >= 18, `frame after the ack is tick ${c.ticks[2]}, expected a fresh tick (>= 18 after 300 ms), not 2`);
    assert.ok(c.ticks[3] > c.ticks[2]);
    assert.equal(c.st().acks, 1);
    assert.ok(c.st().ack_lag_ms[0] > 100); // tick 1 was sent ~300 ms before it was acked
  } finally { c.done(); }
});
test("flow=ack: acks for unsent, repeated, or older ticks and bad messages change nothing", async () => {
  const c = await ackStream(2);
  try {
    await sleepMs(200);
    c.ws.send(writeAck(999)); // never sent
    await sleepMs(60);
    assert.equal(c.ticks.length, 2); assert.equal(c.st().acks, 0); assert.equal(c.st().acks_ignored, 1);
    c.ws.send(writeAck(0)); await sleepMs(60);
    assert.equal(c.st().acks, 1);
    c.ws.send(writeAck(0)); // repeat
    c.ws.send(Buffer.from("not a message")); // wrong size
    c.ws.send(Buffer.alloc(8)); // right size, kind 0
    await sleepMs(60);
    assert.equal(c.st().acks, 1); assert.equal(c.st().acks_ignored, 2); assert.equal(c.st().bad_messages, 2);
    assert.equal(c.st().socket_errors, 0);
  } finally { c.done(); }
});
test("flow=ack: a control message still reaches the frame while the window is full (input is not gated by acks)", async () => {
  const c = await ackStream(1);
  try {
    await sleepMs(150);
    c.ws.send(writeControl(7, 1)); // window of 1 is full (tick 0 unacked): this must still be received and applied ...
    await sleepMs(60);
    c.ws.send(writeAck(0)); // ... and ride the next frame that is sent
    const h = await new Promise((res) => { const l = (d) => { const f = frameOf(d); if (f.tick > 0) { c.ws.off("message", l); res(f); } }; c.ws.on("message", l); });
    assert.equal(h.ctrlSeq, 7); assert.equal(h.ctrlState, 1);
  } finally { c.done(); }
});
test("flow=none ignores acks (counted, not an error) and keeps the A0-02a skip rule", async () => {
  const s = await startServer(0), port = s.server.address().port;
  try {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200`, { origin: `http://127.0.0.1:${port}` }); // flow defaults to none
    await new Promise((res, rej) => { ws.on("open", res); ws.on("error", rej); });
    ws.send(writeAck(0)); await sleepMs(100);
    const st = s.streams[0].stats;
    assert.equal(st.flow, "none"); assert.equal(st.acks, 0); assert.equal(st.acks_ignored, 1); assert.equal(st.window_skipped, 0); assert.ok(st.sent >= 3);
    ws.close();
  } finally { s.close(); }
});
test("a bad flow or window is refused at the upgrade, the server keeps serving", async () => {
  const s = await startServer(0), port = s.server.address().port;
  try {
    const refused = (q) => new Promise((res) => { const w = new WebSocket(`ws://127.0.0.1:${port}/pose?n=200${q}`, { origin: `http://127.0.0.1:${port}` }); w.on("open", () => { w.close(); res("open"); }); w.on("error", () => res("refused")); });
    for (const q of ["&flow=nack", "&flow=ack&win=0", "&flow=ack&win=17", "&flow=ack&win=1.5", "&flow=ack&win=x"]) assert.equal(await refused(q), "refused", q);
    assert.equal(await refused("&flow=ack&win=16"), "open");
    assert.equal(await refused(""), "open");
  } finally { s.close(); }
});
test("flow=ack: an ack for a tick the core skipped (below the oldest unacked frame) is counted as ignored; the server and the stream keep going", async () => {
  const c = await ackStream(2);
  try {
    await sleepMs(250);
    assert.deepEqual(c.ticks, [0, 1]);
    c.ws.send(writeAck(1)); // frees both slots; the core then sends the newest ticks
    await sleepMs(150);
    assert.ok(c.ticks.length >= 4); const oldestUnacked = c.ticks[2];
    assert.ok(oldestUnacked > 5, `expected a fresh tick above 5, got ${oldestUnacked}`);
    c.ws.send(writeAck(5)); // 1 < 5 < oldest unacked: never sent
    await sleepMs(80);
    assert.equal(c.st().acks, 1); assert.equal(c.st().acks_ignored, 1); assert.equal(c.st().socket_errors, 0);
    const before = c.ticks.length;
    c.ws.send(writeAck(c.ticks.at(-1))); // a valid ack right after: the stream still serves it
    await sleepMs(150);
    assert.equal(c.st().acks, 2); assert.ok(c.ticks.length > before);
  } finally { c.done(); }
});
