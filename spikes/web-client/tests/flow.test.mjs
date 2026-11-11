import test from "node:test";
import assert from "node:assert/strict";
import { AckWindow, AckSender, MAX_WINDOW, FLOWS } from "../src/flow.js";
import { writeControl, writeAck, readClientMessage, CONTROL_BYTES, ACK_BYTES } from "../src/frame.js";

test("AckWindow: opens until `win` frames are unacked, a cumulative ack frees every older slot", () => {
  const w = new AckWindow(3);
  assert.ok(w.open());
  w.sent(0, 0); w.sent(1, 16); w.sent(2, 33);
  assert.ok(!w.open()); assert.equal(w.inflight, 3);
  assert.equal(w.ack(1, 50), 50 - 16); // lag = ack time - send time of the acked tick
  assert.equal(w.inflight, 1); assert.ok(w.open());
  assert.equal(w.max_inflight, 3);
});
test("AckWindow: an ack for a skipped tick between two sent ticks acks the older sent ones", () => {
  const w = new AckWindow(4);
  w.sent(0, 0); w.sent(5, 80); w.sent(9, 150); // ticks 1..4, 6..8 were skipped by the core
  assert.equal(w.ack(5, 200), 120);
  assert.equal(w.inflight, 1);
});
test("AckWindow: invalid acks are ignored and change nothing", () => {
  const w = new AckWindow(2);
  w.sent(0, 0); w.sent(1, 10);
  for (const bad of [2, 99, -1, 1.5, NaN, "1", null]) assert.equal(w.ack(bad, 20), null, String(bad));
  assert.equal(w.inflight, 2);
  assert.equal(w.ack(1, 20), 10);
  assert.equal(w.ack(1, 30), null); // repeat
  assert.equal(w.ack(0, 30), null); // older than the last acked
  assert.equal(new AckWindow(2).ack(0, 1), null); // nothing sent yet
});
test("AckWindow: sent ticks must increase; window must be an integer in 1..MAX_WINDOW", () => {
  const w = new AckWindow(2); w.sent(4, 0);
  assert.throws(() => w.sent(4, 1), RangeError); assert.throws(() => w.sent(3, 1), RangeError);
  for (const bad of [0, -1, 1.5, MAX_WINDOW + 1, NaN, undefined]) assert.throws(() => new AckWindow(bad), RangeError, String(bad));
  assert.doesNotThrow(() => new AckWindow(MAX_WINDOW));
  assert.deepEqual(FLOWS, ["none", "ack"]);
});
test("AckSender: acks each newly drawn tick once, never a repeat or an older tick", () => {
  const a = new AckSender();
  assert.equal(a.onDraw(0), 0); assert.equal(a.onDraw(0), null); assert.equal(a.onDraw(5), 5); assert.equal(a.onDraw(3), null); assert.equal(a.onDraw(6), 6);
  assert.equal(a.count, 3);
});
test("client messages: control 12 B and ack 8 B round-trip little-endian; anything else is null", () => {
  const c = writeControl(77, 1), k = writeAck(123456);
  assert.equal(c.byteLength, CONTROL_BYTES); assert.equal(k.byteLength, ACK_BYTES);
  assert.deepEqual(readClientMessage(new Uint8Array(c)), { kind: "control", seq: 77, state: 1 });
  assert.deepEqual(readClientMessage(new Uint8Array(k)), { kind: "ack", tick: 123456 });
  assert.equal(new Uint8Array(k)[4], 123456 & 255);
  assert.equal(readClientMessage(new Uint8Array(8)), null); // kind 0
  assert.equal(readClientMessage(new Uint8Array(c, 0, 8)), null); // control kind with ack length
  assert.equal(readClientMessage(new Uint8Array(0)), null);
  const buf = Buffer.concat([Buffer.alloc(3), Buffer.from(k)]); // a Buffer slice with a non-zero byteOffset, as ws delivers
  assert.deepEqual(readClientMessage(buf.subarray(3)), { kind: "ack", tick: 123456 });
});
