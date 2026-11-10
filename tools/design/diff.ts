// Pixel diff of two PNGs with tolerance (D0-04). Pure: no browser, no filesystem.
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

export interface Tolerance {
  /** pixelmatch per-pixel colour distance, 0..1. Anti-aliasing pixels are ignored by pixelmatch. */
  threshold: number;
  /** Largest share of differing pixels (of the compared area), 0..1. Catches layout drift. */
  maxDiffRatio: number;
  /** Side of the square window for the local check, in px. */
  windowSize: number;
  /** Most differing pixels allowed inside any one window. Catches a small local defect the ratio hides. */
  maxWindowDiffPixels: number;
  /** Largest allowed difference in width or height between the two images, in px. */
  maxSizeDeltaPx: number;
}

export const DEFAULT_TOLERANCE: Tolerance = {
  threshold: 0.1,
  maxDiffRatio: 0.002,
  windowSize: 32,
  maxWindowDiffPixels: 100,
  maxSizeDeltaPx: 0,
};

/** Largest share of the image that ignore rectangles may cover. Not a Tolerance field: a pair cannot lift it. */
export const MAX_IGNORED_RATIO = 0.25;

/** Rectangle in image pixels, origin top-left. */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DiffResult {
  pass: boolean;
  reasons: string[];
  approvedSize: [number, number];
  implementedSize: [number, number];
  comparedPixels: number;
  ignoredPixels: number;
  diffPixels: number;
  diffRatio: number;
  maxWindowDiff: number;
  diffPng: Buffer;
}

const PAD = [255, 0, 255, 255]; // magenta: area that exists in only one image

function clamp(v: number, lo: number, hi: number): number {
  return Number.isNaN(v) ? lo : Math.min(hi, Math.max(lo, v));
}

function padded(img: PNG, width: number, height: number): Uint8Array {
  if (img.width === width && img.height === height) return img.data;
  const out = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) out.set(PAD, i * 4);
  for (let y = 0; y < img.height; y++) {
    out.set(img.data.subarray(y * img.width * 4, (y + 1) * img.width * 4), y * width * 4);
  }
  return out;
}

export function comparePngs(
  approvedPng: Buffer,
  implementedPng: Buffer,
  tolerance: Tolerance = DEFAULT_TOLERANCE,
  ignore: readonly Rect[] = [],
): DiffResult {
  const a = PNG.sync.read(approvedPng);
  const b = PNG.sync.read(implementedPng);
  const width = Math.max(a.width, b.width);
  const height = Math.max(a.height, b.height);

  const mask = new Uint8Array(width * height);
  for (const r of ignore) {
    // Clip to the image first. fill() reads a negative end as "from the array end", so an unclipped
    // rectangle that lies left of or above the image could mask unrelated pixels.
    const x0 = clamp(Math.floor(r.x), 0, width), x1 = clamp(Math.ceil(r.x + r.width), 0, width);
    const y0 = clamp(Math.floor(r.y), 0, height), y1 = clamp(Math.ceil(r.y + r.height), 0, height);
    if (!(x1 > x0 && y1 > y0)) continue; // empty after clipping (also NaN)
    for (let y = y0; y < y1; y++) mask.fill(1, y * width + x0, y * width + x1);
  }
  const ignoredPixels = mask.reduce((n, v) => n + v, 0);
  const comparedPixels = width * height - ignoredPixels;

  const imgA = padded(a, width, height);
  const imgB = padded(b, width, height);
  const diff = new PNG({ width, height });
  const opts = { threshold: tolerance.threshold, ignoreMask: mask };
  const diffPixels = pixelmatch(imgA, imgB, diff.data, width, height, opts);
  const maxWindowDiff = pixelmatch(imgA, imgB, null, width, height, { ...opts, windowSize: tolerance.windowSize });
  const diffRatio = comparedPixels === 0 ? 0 : diffPixels / comparedPixels;

  const reasons: string[] = [];
  const dw = Math.abs(a.width - b.width), dh = Math.abs(a.height - b.height);
  if (dw > tolerance.maxSizeDeltaPx || dh > tolerance.maxSizeDeltaPx) {
    reasons.push(`size ${a.width}x${a.height} (approved) vs ${b.width}x${b.height} (implemented), allowed delta ${tolerance.maxSizeDeltaPx}px`);
  }
  if (ignoredPixels / (width * height) > MAX_IGNORED_RATIO) {
    reasons.push(`ignored area ${((ignoredPixels / (width * height)) * 100).toFixed(1)}% > ${(MAX_IGNORED_RATIO * 100).toFixed(1)}%`);
  }
  if (diffRatio > tolerance.maxDiffRatio) {
    reasons.push(`diff ratio ${(diffRatio * 100).toFixed(3)}% > ${(tolerance.maxDiffRatio * 100).toFixed(3)}%`);
  }
  if (maxWindowDiff > tolerance.maxWindowDiffPixels) {
    reasons.push(`${maxWindowDiff} diff px in one ${tolerance.windowSize}x${tolerance.windowSize} window > ${tolerance.maxWindowDiffPixels}`);
  }
  return {
    pass: reasons.length === 0,
    reasons,
    approvedSize: [a.width, a.height],
    implementedSize: [b.width, b.height],
    comparedPixels,
    ignoredPixels,
    diffPixels,
    diffRatio,
    maxWindowDiff,
    diffPng: PNG.sync.write(diff),
  };
}
