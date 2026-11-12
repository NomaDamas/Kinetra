// P0-04d: proves WebGL renders in headless Chromium. Loads webgl-empty/index.html (raw WebGL, no library: clear color
// rgb(26,102,204) + one red triangle), screenshots the canvas and asserts PIXELS: background, triangle center, triangle
// area, and a pixel outside the triangle. Not "a context was created": the pixels must be what the GPU path drew.
//
//   pnpm --filter @kinetra/screenshots webgl [--out out/webgl] [--probe]
//
// `--probe` tries every launch-flag set in FLAG_SETS and prints which ones render (evidence for the chosen flags).
// Without it, only the chosen set (WEBGL_FLAGS below) is run and must pass. Exit code: 0 pass, 1 fail, 3 outside the resource guard.
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
import type { Browser, LaunchOptions } from "playwright-core";
import { PNG } from "pngjs";
import { guardProblem } from "./capture.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
export const PAGE = join(HERE, "webgl-empty", "index.html");
export const CLEAR = [26, 102, 204] as const;
export const RED = [255, 0, 0] as const;
export const SIZE = 256;

export const FLAG_SETS: Record<string, string[]> = {
  default: [],
  "swiftshader": ["--use-angle=swiftshader"],
  "swiftshader+unsafe": ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  "angle-gl+swiftshader": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
};
/** The set the workflow relies on. Chosen from the probe evidence recorded in docs/process/screenshots.md. */
export const WEBGL_FLAGS = "default";

export interface WebglResult {
  flags: string;
  args: string[];
  ok: boolean;
  gl: { ok: boolean; error: string | null; renderer: string | null; vendor: string | null; version: string | null } | null;
  checks: Record<string, boolean>;
  measured: { background: number[]; center: number[]; outside: number[]; red_pixels: number; expected_red_pixels: number } | null;
  error?: string;
}

const near = (a: ArrayLike<number>, b: ArrayLike<number>, tol: number) => [0, 1, 2].every((i) => Math.abs(a[i]! - b[i]!) <= tol);

/** Pure pixel check of a decoded canvas screenshot (RGBA, SIZE x SIZE). */
export function checkPixels(rgba: Uint8Array | Buffer, width: number, height: number): { checks: Record<string, boolean>; measured: NonNullable<WebglResult["measured"]> } {
  const px = (x: number, y: number) => [0, 1, 2, 3].map((i) => rgba[(y * width + x) * 4 + i]!);
  const background = px(4, 4); // top-left corner: outside the triangle (apex at the top center)
  const outside = px(width - 5, 8); // top-right corner
  const center = px(width / 2, Math.round(height * 0.62)); // inside: triangle spans y from 10% to 90% (clip +-0.8), wide at the bottom
  let red = 0;
  for (let i = 0; i < width * height; i++) {
    if (rgba[i * 4]! > 200 && rgba[i * 4 + 1]! < 60 && rgba[i * 4 + 2]! < 60) red++;
  }
  // clip-space triangle (-0.8,-0.8) (0.8,-0.8) (0,0.8): base 0.8*SIZE, height 0.8*SIZE -> area = 0.5 * (0.8*SIZE)^2
  const expected = 0.5 * (0.8 * width) * (0.8 * height);
  const checks = {
    dimensions: width === SIZE && height === SIZE,
    clear_color_background: near(background, CLEAR, 2) && background[3] === 255,
    clear_color_outside_triangle: near(outside, CLEAR, 2),
    triangle_center_is_red: near(center, RED, 2),
    triangle_area_within_3pct: Math.abs(red - expected) / expected < 0.03,
  };
  return { checks, measured: { background, center, outside, red_pixels: red, expected_red_pixels: Math.round(expected) } };
}

/** How a browser is started. Injected by tests to make a launch fail; the default is the real one. */
export type Launcher = (options: LaunchOptions) => Promise<Browser>;
const realLauncher: Launcher = (options) => chromium.launch(options);

/** Never throws for a browser problem: a failed launch is a recorded `ok: false` result with the reason, so a probe goes on to the next flag set. */
export async function runWebgl(flags: string, outDir?: string, launch: Launcher = realLauncher): Promise<WebglResult> {
  const args = FLAG_SETS[flags];
  if (!args) throw new Error(`unknown flag set ${flags} (have: ${Object.keys(FLAG_SETS).join(", ")})`);
  const result: WebglResult = { flags, args, ok: false, gl: null, checks: {}, measured: null };
  let browser: Browser | undefined;
  try {
    browser = await launch({ args });
    const ctx = await browser.newContext({ viewport: { width: 400, height: 400 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await page.goto(pathToFileURL(PAGE).href, { waitUntil: "load" });
    result.gl = await page.evaluate(() => (window as unknown as { __webgl: WebglResult["gl"] }).__webgl);
    if (!result.gl?.ok) {
      result.error = `WebGL did not initialise: ${result.gl?.error ?? "no result object"}`;
      return result;
    }
    const png = PNG.sync.read(await page.locator("#c").screenshot());
    const { checks, measured } = checkPixels(png.data, png.width, png.height);
    result.checks = checks;
    result.measured = measured;
    result.ok = Object.values(checks).every(Boolean);
    if (outDir) {
      await mkdir(outDir, { recursive: true });
      await writeFile(join(outDir, `webgl-${flags.replace(/\W+/g, "_")}.png`), PNG.sync.write(png));
    }
    return result;
  } catch (e) {
    result.error = (e as Error).message.split("\n")[0]!;
    return result;
  } finally {
    await browser?.close().catch(() => {});
  }
}

/** One result per flag set, in order. A flag set that fails to launch or render is recorded and the next one still runs. */
export async function runAll(names: string[], outDir?: string, launch: Launcher = realLauncher): Promise<WebglResult[]> {
  const results: WebglResult[] = [];
  for (const n of names) results.push(await runWebgl(n, outDir, launch));
  return results;
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const probe = argv.includes("--probe");
  const oi = argv.indexOf("--out");
  const out = oi >= 0 && argv[oi + 1] ? resolve(argv[oi + 1]!) : resolve(HERE, "..", "..", "out", "webgl");
  const problem = guardProblem();
  if (problem) {
    console.error(problem);
    return 3;
  }
  await mkdir(out, { recursive: true });
  const names = probe ? Object.keys(FLAG_SETS) : [WEBGL_FLAGS];
  const results = await runAll(names, out);
  for (const r of results) {
    const n = r.flags;
    console.log(`${r.ok ? "PASS" : "FAIL"} flags=${n} [${r.args.join(" ") || "(none)"}] renderer=${r.gl?.renderer ?? "?"} ${r.error ?? ""}`);
    if (r.measured) console.log(`     red_pixels=${r.measured.red_pixels} (expected ${r.measured.expected_red_pixels}) center=${r.measured.center} background=${r.measured.background}`);
    for (const [k, v] of Object.entries(r.checks)) if (!v) console.log(`     check failed: ${k}`);
  }
  await writeFile(join(out, "webgl-result.json"), JSON.stringify({ probe, chosen: WEBGL_FLAGS, results }, null, 2) + "\n");
  return probe ? 0 : results[0]!.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
