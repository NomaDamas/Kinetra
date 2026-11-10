// Design compare (D0-04): Playwright screenshot of an implemented page vs a render of the approved
// export, pixel diff with tolerance, diff image out. Rules: docs/process/design-workflow.md.
//
//   pnpm design:compare --screen _trial [--out out/design-compare]
//
// Exit code: 0 all pairs within tolerance, 1 some pair outside tolerance, 2 bad usage or config,
// 3 the run itself failed (browser missing or crashed).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
import { comparePngs, DEFAULT_TOLERANCE, type DiffResult, type Rect, type Tolerance } from "./diff.ts";

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Bad usage or bad screens.json. The CLI exits 2. */
export class ConfigError extends Error {}

export interface Side {
  /** Repo-relative path of a local HTML file, or an http(s) URL on this machine (127.0.0.1, localhost, [::1]). */
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

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

function isHttp(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function target(url: string): string {
  if (isHttp(url)) return url;
  return pathToFileURL(isAbsolute(url) ? url : join(REPO_ROOT, url)).href;
}

/** Origins a page may load from: the local server of its own http(s) url. `file:` is always allowed. */
export function allowedOrigins(sideUrl: string): Set<string> {
  if (!isHttp(sideUrl)) return new Set();
  const u = new URL(sideUrl);
  return new Set([u.origin]);
}

/** Parsed-URL allow-list: `file:` or an exact allowed origin. Substring and prefix tricks do not pass. */
export function isAllowedRequest(requestUrl: string, origins: ReadonlySet<string>): boolean {
  let u: URL;
  try {
    u = new URL(requestUrl);
  } catch {
    return false;
  }
  if (u.protocol === "file:") return true;
  return (u.protocol === "http:" || u.protocol === "https:") && origins.has(u.origin);
}

const TOLERANCE_KEYS = new Set(Object.keys(DEFAULT_TOLERANCE));

export function validateScreen(name: string, screen: Screen | undefined): asserts screen is Screen {
  if (!screen || !Array.isArray(screen.pairs)) throw new ConfigError(`screen "${name}": "pairs" must be an array`);
  if (screen.pairs.length === 0) throw new ConfigError(`screen "${name}": "pairs" is empty, nothing would be compared`);
  const seen = new Set<string>();
  for (const pair of screen.pairs) {
    const where = `${name}/${pair?.name ?? "?"}`;
    if (!pair || typeof pair.name !== "string" || !/^[\w.-]+$/.test(pair.name)) throw new ConfigError(`${where}: "name" must match [\\w.-]+`);
    if (seen.has(pair.name)) throw new ConfigError(`${where}: duplicate pair name`);
    seen.add(pair.name);
    for (const side of ["approved", "implemented"] as const) {
      const url = pair[side]?.url;
      if (typeof url !== "string" || !url) throw new ConfigError(`${where}: "${side}.url" is required`);
      if (isHttp(url) && !LOOPBACK_HOSTS.has(new URL(url).hostname)) {
        throw new ConfigError(`${where}: "${side}.url" must be a local server (127.0.0.1, localhost, [::1]) or a repo path, got ${url}`);
      }
    }
    if ((pair.ignore?.length || pair.tolerance) && !pair.reason?.trim()) {
      throw new ConfigError(`${where}: "ignore" or "tolerance" needs a "reason" in screens.json (docs/process/design-workflow.md)`);
    }
    for (const [k, v] of Object.entries(pair.tolerance ?? {})) {
      if (!TOLERANCE_KEYS.has(k)) throw new ConfigError(`${where}: unknown tolerance key "${k}" (have: ${[...TOLERANCE_KEYS].join(", ")})`);
      if (typeof v !== "number" || !Number.isFinite(v) || v < 0) throw new ConfigError(`${where}: tolerance "${k}" must be a finite number >= 0`);
    }
  }
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
    const origins = allowedOrigins(side.url);
    await ctx.route(/^(https?|wss?|ftp):/i, (r) => (isAllowedRequest(r.request().url(), origins) ? r.continue() : r.abort()));
    const page = await ctx.newPage();
    await page.goto(target(side.url), { waitUntil: "load" });
    if (side.css) await page.addStyleTag({ content: side.css });
    await page.evaluate(() => document.fonts.ready);
    const el = side.selector ? page.locator(side.selector) : page.locator("html");
    const box = await el.boundingBox();
    if (!box) throw new ConfigError(`selector not found or not visible: ${side.selector ?? "html"} in ${side.url}`);
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
  validateScreen(name, screen);
  const viewport = screen.viewport ?? DEFAULT_VIEWPORT;
  const dir = join(outDir, name);
  await mkdir(dir, { recursive: true });
  const browser = await chromium.launch();
  try {
    const outcomes: PairOutcome[] = [];
    for (const pair of screen.pairs) {
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
  try {
    return JSON.parse(await readFile(file, "utf8")) as Record<string, Screen>;
  } catch (e) {
    throw new ConfigError(`cannot read ${file}: ${(e as Error).message}`);
  }
}

export function parseArgs(argv: string[]): { screen: string; out: string } {
  let screen = "";
  let out = join(REPO_ROOT, "out", "design-compare");
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--screen" && argv[i + 1]) screen = argv[++i]!;
    else if (v === "--out" && argv[i + 1]) out = resolve(argv[++i]!);
    else throw new ConfigError(`unknown argument: ${v}`);
  }
  if (!screen) throw new ConfigError("usage: pnpm design:compare --screen <name> [--out <dir>]");
  return { screen, out };
}

async function main(): Promise<number> {
  try {
    const args = parseArgs(process.argv.slice(2));
    const screens = await loadScreens();
    const screen = screens[args.screen];
    if (!screen) throw new ConfigError(`screen "${args.screen}" not in tools/design/screens.json (have: ${Object.keys(screens).join(", ")})`);
    const outcomes = await compareScreen(args.screen, screen, args.out);
    for (const o of outcomes) {
      const head = `${o.pass ? "PASS" : "FAIL"} ${o.screen}/${o.pair}`;
      console.log(`${head}  diff ${o.diffPixels}px of ${o.comparedPixels} (${(o.diffRatio * 100).toFixed(3)}%), worst window ${o.maxWindowDiff}px, ignored ${o.ignoredPixels}px`);
      for (const r of o.reasons) console.log(`  - ${r}`);
      if (!o.pass) console.log(`  diff image: ${o.files.diff}`);
    }
    return outcomes.every((o) => o.pass) ? 0 : 1;
  } catch (e) {
    console.error((e as Error).message);
    return e instanceof ConfigError ? 2 : 3;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exit(await main());
}
