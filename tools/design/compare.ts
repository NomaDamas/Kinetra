// Design compare (D0-04): Playwright screenshot of an implemented page vs a render of the approved
// export, pixel diff with tolerance, diff image out. Rules: docs/process/design-workflow.md.
//
//   pnpm design:compare --screen _trial [--out out/design-compare]
//
// Exit code: 0 all pairs within tolerance, 1 some pair outside tolerance, 2 bad usage or config.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
import { comparePngs, DEFAULT_TOLERANCE, type DiffResult, type Rect, type Tolerance } from "./diff.ts";

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export interface Side {
  /** Repo-relative path of a local HTML file, or an http(s) URL. */
  url: string;
  /** CSS selector of the element to capture. Omitted: the whole page. */
  selector?: string;
  /** Extra CSS injected before the capture. Used by trials to make a deliberately modified copy. */
  css?: string;
}

export interface Pair {
  name: string;
  approved: Side;
  implemented: Side;
  /** Selectors of elements to exclude from the diff (exception rule 1 in the workflow doc). */
  ignore?: string[];
  tolerance?: Partial<Tolerance>;
  /** Required whenever `ignore` or `tolerance` is set: why the exception is legitimate (exception rule 3). */
  reason?: string;
}

export interface Screen {
  viewport?: { width: number; height: number };
  pairs: Pair[];
}

export interface PairOutcome extends Omit<DiffResult, "diffPng"> {
  screen: string;
  pair: string;
  files: { approved: string; implemented: string; diff: string };
}

const DEFAULT_VIEWPORT = { width: 1440, height: 900 };

function target(url: string): string {
  if (/^https?:\/\//.test(url)) return url;
  return pathToFileURL(isAbsolute(url) ? url : join(REPO_ROOT, url)).href;
}

async function shoot(
  browser: import("playwright-core").Browser,
  side: Side,
  viewport: { width: number; height: number },
  ignore: string[],
): Promise<{ png: Buffer; ignore: Rect[] }> {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: "reduce" });
  try {
    // Same input every run: nothing leaves the machine, so web fonts fall back to the system fonts
    // on both sides. Both sides are always rendered in the same run, by the same browser.
    await ctx.route(/^https?:/, (r) => (r.request().url().startsWith("http://127.0.0.1") ? r.continue() : r.abort()));
    const page = await ctx.newPage();
    await page.goto(target(side.url), { waitUntil: "load" });
    if (side.css) await page.addStyleTag({ content: side.css });
    await page.evaluate(() => document.fonts.ready);
    const el = side.selector ? page.locator(side.selector) : page.locator("html");
    const box = await el.boundingBox();
    if (!box) throw new Error(`selector not found or not visible: ${side.selector ?? "html"} in ${side.url}`);
    const rects: Rect[] = [];
    for (const sel of ignore) {
      for (const h of await page.locator(sel).all()) {
        const b = await h.boundingBox();
        if (b) rects.push({ x: b.x - box.x, y: b.y - box.y, width: b.width, height: b.height });
      }
    }
    const png = side.selector
      ? await el.screenshot({ animations: "disabled", caret: "hide" })
      : await page.screenshot({ fullPage: true, animations: "disabled", caret: "hide" });
    return { png, ignore: rects };
  } finally {
    await ctx.close();
  }
}

export async function compareScreen(name: string, screen: Screen, outDir: string): Promise<PairOutcome[]> {
  const viewport = screen.viewport ?? DEFAULT_VIEWPORT;
  const dir = join(outDir, name);
  await mkdir(dir, { recursive: true });
  const browser = await chromium.launch();
  try {
    const outcomes: PairOutcome[] = [];
    for (const pair of screen.pairs) {
      if ((pair.ignore?.length || pair.tolerance) && !pair.reason?.trim()) {
        throw new Error(`${name}/${pair.name}: "ignore" or "tolerance" needs a "reason" in screens.json (docs/process/design-workflow.md)`);
      }
      const ignore = pair.ignore ?? [];
      // Ignored regions come from the approved side's layout; the implemented side must match it.
      const a = await shoot(browser, pair.approved, viewport, ignore);
      const b = await shoot(browser, pair.implemented, viewport, []);
      const tol: Tolerance = { ...DEFAULT_TOLERANCE, ...pair.tolerance };
      const { diffPng, ...result } = comparePngs(a.png, b.png, tol, a.ignore);
      const files = {
        approved: join(dir, `${pair.name}.approved.png`),
        implemented: join(dir, `${pair.name}.implemented.png`),
        diff: join(dir, `${pair.name}.diff.png`),
      };
      await Promise.all([writeFile(files.approved, a.png), writeFile(files.implemented, b.png), writeFile(files.diff, diffPng)]);
      outcomes.push({ screen: name, pair: pair.name, ...result, files });
    }
    await writeFile(join(dir, "result.json"), JSON.stringify(outcomes, null, 2) + "\n");
    return outcomes;
  } finally {
    await browser.close();
  }
}

export async function loadScreens(file = join(REPO_ROOT, "tools", "design", "screens.json")): Promise<Record<string, Screen>> {
  return JSON.parse(await readFile(file, "utf8")) as Record<string, Screen>;
}

export function parseArgs(argv: string[]): { screen: string; out: string } {
  let screen = "";
  let out = join(REPO_ROOT, "out", "design-compare");
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--screen" && argv[i + 1]) screen = argv[++i]!;
    else if (v === "--out" && argv[i + 1]) out = resolve(argv[++i]!);
    else throw new Error(`unknown argument: ${v}`);
  }
  if (!screen) throw new Error("usage: pnpm design:compare --screen <name> [--out <dir>]");
  return { screen, out };
}

async function main(): Promise<number> {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error((e as Error).message);
    return 2;
  }
  const screens = await loadScreens();
  const screen = screens[args.screen];
  if (!screen) {
    console.error(`screen "${args.screen}" not in tools/design/screens.json (have: ${Object.keys(screens).join(", ")})`);
    return 2;
  }
  const outcomes = await compareScreen(args.screen, screen, args.out);
  for (const o of outcomes) {
    const head = `${o.pass ? "PASS" : "FAIL"} ${o.screen}/${o.pair}`;
    console.log(`${head}  diff ${o.diffPixels}px of ${o.comparedPixels} (${(o.diffRatio * 100).toFixed(3)}%), worst window ${o.maxWindowDiff}px, ignored ${o.ignoredPixels}px`);
    for (const r of o.reasons) console.log(`  - ${r}`);
    if (!o.pass) console.log(`  diff image: ${o.files.diff}`);
  }
  return outcomes.every((o) => o.pass) ? 0 : 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exit(await main());
}
