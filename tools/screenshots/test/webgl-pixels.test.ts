// Offline: the pixel assertion itself, on synthetic images (no browser). A blank or wrong-color canvas must fail it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { checkPixels, CLEAR, RED, SIZE } from "../webgl-check.ts";

/** Same geometry as the page: clear color everywhere, red triangle (-0.8,-0.8) (0.8,-0.8) (0,0.8) in clip space (y up). */
function render(clear: readonly number[], tri: readonly number[] | null): Buffer {
  const b = Buffer.alloc(SIZE * SIZE * 4);
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      const cx = ((x + 0.5) / SIZE) * 2 - 1, cy = 1 - ((y + 0.5) / SIZE) * 2;
      const inside = cy >= -0.8 && cy <= 0.8 && Math.abs(cx) <= 0.8 * (0.8 - cy) / 1.6;
      const c = tri && inside ? tri : clear;
      b.set([c[0]!, c[1]!, c[2]!, 255], (y * SIZE + x) * 4);
    }
  }
  return b;
}

test("the expected image passes every check", () => {
  const { checks, measured } = checkPixels(render(CLEAR, RED), SIZE, SIZE);
  assert.deepEqual(Object.values(checks), [true, true, true, true, true], JSON.stringify({ checks, measured }));
});

test("blank white / black / transparent canvases fail", () => {
  for (const c of [[255, 255, 255], [0, 0, 0]]) {
    const { checks } = checkPixels(render(c, null), SIZE, SIZE);
    assert.equal(Object.values(checks).every(Boolean), false);
  }
  assert.equal(Object.values(checkPixels(Buffer.alloc(SIZE * SIZE * 4), SIZE, SIZE).checks).every(Boolean), false);
});

test("clear color without the triangle fails the triangle checks only", () => {
  const { checks } = checkPixels(render(CLEAR, null), SIZE, SIZE);
  assert.equal(checks.clear_color_background, true);
  assert.equal(checks.triangle_center_is_red, false);
  assert.equal(checks.triangle_area_within_3pct, false);
});

test("a triangle of the wrong color or half the size fails", () => {
  assert.equal(checkPixels(render(CLEAR, [0, 255, 0]), SIZE, SIZE).checks.triangle_center_is_red, false);
  const half = render(CLEAR, RED);
  for (let y = SIZE / 2; y < SIZE; y++) for (let x = 0; x < SIZE; x++) half.set([CLEAR[0], CLEAR[1], CLEAR[2], 255], (y * SIZE + x) * 4);
  assert.equal(checkPixels(half, SIZE, SIZE).checks.triangle_area_within_3pct, false);
});
