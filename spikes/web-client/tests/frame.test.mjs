import test from "node:test";
import assert from "node:assert/strict";
import { HEADER, BODY, frameBytes, writeHeader, readHeader, poseView } from "../src/frame.js";

test("frame size is 24 + 28 n bytes", () => {
  assert.equal(HEADER, 24); assert.equal(BODY, 28);
  for (const n of [200, 1000, 5000]) assert.equal(frameBytes(n), 24 + 28 * n);
  assert.equal(frameBytes(5000), 140024);
});
test("header round-trips little-endian", () => {
  const buf = new ArrayBuffer(frameBytes(3));
  writeHeader(buf, { tick: 123456, n: 3, simTime: 2057.6, ctrlState: 1, ctrlSeq: 77 });
  assert.deepEqual(readHeader(buf), { tick: 123456, n: 3, simTime: 2057.6, ctrlState: 1, ctrlSeq: 77 });
  assert.equal(new Uint8Array(buf)[0], 123456 & 255);
});
test("readHeader rejects a truncated frame", () => {
  const buf = new ArrayBuffer(frameBytes(3)); writeHeader(buf, { tick: 0, n: 3, simTime: 0, ctrlState: 0, ctrlSeq: 0 });
  assert.throws(() => readHeader(buf.slice(0, buf.byteLength - 4)), /frame length/);
});
test("poseView is 7 floats per body after the header", () => {
  const buf = new ArrayBuffer(frameBytes(5)); const v = poseView(buf, 5);
  assert.equal(v.length, 35); assert.equal(v.byteOffset, 24);
});
