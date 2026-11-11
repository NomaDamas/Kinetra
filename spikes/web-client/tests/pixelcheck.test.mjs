import test from "node:test";
import assert from "node:assert/strict";
import { checkFirstFrame, isCarRed } from "../src/pixelcheck.js";

const fill = (n, rgba) => Uint8Array.from({ length: 4 * n }, (_, i) => rgba[i % 4]);
const CAR = [150, 20, 22, 255], GROUND = [140, 148, 158, 255], SKY = [20, 24, 31, 255];

test("car-body red passes when the corner is ground", () => assert.equal(checkFirstFrame(fill(25, CAR), GROUND).ok, true));
test("ground or sky at the car position fails (an empty or ground-only frame is not a car)", () => {
  assert.equal(checkFirstFrame(fill(25, GROUND), GROUND).ok, false);
  assert.equal(checkFirstFrame(fill(25, SKY), GROUND).ok, false);
});
test("a canvas painted all red fails (corner must not look like the car)", () => assert.equal(checkFirstFrame(fill(25, CAR), CAR).ok, false));
test("mostly-ground block with a few red pixels fails the fraction", () => {
  const b = fill(25, GROUND); b.set(CAR, 0); b.set(CAR, 4);
  const r = checkFirstFrame(b, GROUND); assert.equal(r.ok, false); assert.ok(r.red_fraction < 0.5);
});
test("isCarRed rejects grey and the wheels' colour", () => { assert.equal(isCarRed(...GROUND.slice(0, 3)), false); assert.equal(isCarRed(128, 128, 128), false); assert.equal(isCarRed(200, 30, 30), true); });
