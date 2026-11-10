import { test } from "node:test";
import assert from "node:assert/strict";
import { PNG } from "pngjs";
import { comparePngs, DEFAULT_TOLERANCE } from "../diff.ts";

// A white 200x120 page with a dark 60x30 "button" at (x, y) and a grey text-like bar.
function page(buttonX: number, buttonY: number, width = 200, height = 120): Buffer {
  const png = new PNG({ width, height });
  png.data.fill(255);
  const rect = (x0: number, y0: number, w: number, h: number, rgb: [number, number, number]) => {
    for (let y = y0; y < y0 + h; y++) {
      for (let x = x0; x < x0 + w; x++) {
        const i = (y * width + x) * 4;
        png.data.set([...rgb, 255], i);
      }
    }
  };
  rect(buttonX, buttonY, 60, 30, [20, 40, 90]);
  rect(10, 90, 120, 8, [120, 120, 120]);
  return PNG.sync.write(png);
}

test("identical images pass with zero diff", () => {
  const r = comparePngs(page(20, 20), page(20, 20));
  assert.equal(r.pass, true);
  assert.equal(r.diffPixels, 0);
  assert.deepEqual(r.reasons, []);
});

test("a button shifted by 6px fails and the diff image is a PNG of the same size", () => {
  const r = comparePngs(page(20, 20), page(26, 20));
  assert.equal(r.pass, false);
  assert.ok(r.diffPixels > 0);
  assert.ok(r.reasons.length > 0);
  const diff = PNG.sync.read(r.diffPng);
  assert.equal(diff.width, 200);
  assert.equal(diff.height, 120);
});

test("a one-pixel-wide sub-tolerance colour change passes", () => {
  const a = PNG.sync.read(page(20, 20));
  a.data.set([21, 41, 91, 255], (20 * 200 + 20) * 4); // one pixel off by 1 per channel
  const r = comparePngs(page(20, 20), PNG.sync.write(a));
  assert.equal(r.pass, true);
});

test("a changed region inside an ignored rect passes, outside it fails", () => {
  const ignore = [{ x: 15, y: 15, width: 80, height: 40 }];
  assert.equal(comparePngs(page(20, 20), page(26, 20), DEFAULT_TOLERANCE, ignore).pass, true);
  assert.equal(comparePngs(page(20, 20), page(26, 20), DEFAULT_TOLERANCE, [{ x: 150, y: 0, width: 50, height: 50 }]).pass, false);
});

test("a size difference beyond the allowed delta fails, within it passes", () => {
  const a = page(20, 20, 200, 120);
  const b = page(20, 20, 200, 124);
  assert.equal(comparePngs(a, b).pass, false);
  assert.ok(comparePngs(a, b).reasons.some((r) => r.startsWith("size ")));
  const loose = { ...DEFAULT_TOLERANCE, maxSizeDeltaPx: 4, maxDiffRatio: 0.05, maxWindowDiffPixels: 2000 };
  assert.equal(comparePngs(a, b, loose).pass, true);
});

test("a small local defect is caught by the window check even when the global ratio is tiny", () => {
  const w = 1000, h = 1000;
  const base = new PNG({ width: w, height: h });
  base.data.fill(255);
  const bad = new PNG({ width: w, height: h });
  bad.data.fill(255);
  for (let y = 500; y < 520; y++) for (let x = 500; x < 520; x++) bad.data.set([0, 0, 0, 255], (y * w + x) * 4); // 400px
  const r = comparePngs(PNG.sync.write(base), PNG.sync.write(bad));
  assert.ok(r.diffRatio < DEFAULT_TOLERANCE.maxDiffRatio, `ratio ${r.diffRatio}`);
  assert.equal(r.pass, false);
  assert.ok(r.reasons.some((x) => x.includes("window")));
});

test("ignoring more than the allowed share of the image fails even with zero diff", () => {
  const r = comparePngs(page(20, 20), page(20, 20), DEFAULT_TOLERANCE, [{ x: 0, y: 0, width: 200, height: 60 }]);
  assert.equal(r.pass, false);
  assert.ok(r.reasons.some((x) => x.startsWith("ignored area")));
});
