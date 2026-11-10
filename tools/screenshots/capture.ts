// P0-04d: screenshots of the pages listed in .github/screenshots.json -> out/screenshots/<name>.png + manifest.json.
// The `screenshots` workflow uploads that folder as an Actions artifact on every PR.
//
//   pnpm --filter @kinetra/screenshots capture [--out out/screenshots] [--config .github/screenshots.json]
//
// Exit code: 0 at least one page captured (missing paths are skipped with a log line), 1 nothing captured or a page
// failed to load, 2 bad usage or bad config, 3 refused to start a local browser outside the resource guard.
// Rules and how to add a page: docs/process/screenshots.md.
import { createHash } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
import type { Browser } from "playwright-core";

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const DEFAULT_CONFIG = join(REPO_ROOT, ".github", "screenshots.json");
export const DEFAULT_OUT = join(REPO_ROOT, "out", "screenshots");

/** Bad usage or bad config. The CLI exits 2. */
export class ConfigError extends Error {}

export interface Screen {
  name: string;
  /** Repo-relative path of a local HTML file. */
  path: string;
  /** CSS selector of one element to capture. Omitted: the page (full page when `fullPage`). */
  selector?: string;
  fullPage?: boolean;
}
export interface Config {
  viewport: { width: number; height: number };
  screens: Screen[];
}
export interface Outcome {
  name: string;
  path: string;
  status: "captured" | "skipped" | "failed";
  reason?: string;
  file?: string;
  width?: number;
  height?: number;
  bytes?: number;
  sha256?: string;
  page_errors?: string[];
  /** External (http/https/ftp/ws) requests the page made and the tool aborted. */
  blocked_requests?: string[];
}

/** Validation only: no file is read. Names become file names, paths must stay inside the repo. */
export function validateConfig(raw: unknown): Config {
  const c = raw as Partial<Config> | null;
  if (!c || typeof c !== "object") throw new ConfigError("config must be a JSON object");
  const vp = c.viewport;
  if (!vp || !Number.isInteger(vp.width) || !Number.isInteger(vp.height) || vp.width < 100 || vp.height < 100 || vp.width > 4000 || vp.height > 4000) {
    throw new ConfigError('"viewport" must be {width, height}, integers in 100..4000');
  }
  if (!Array.isArray(c.screens) || c.screens.length === 0) throw new ConfigError('"screens" must be a non-empty array');
  const seen = new Set<string>();
  for (const s of c.screens) {
    if (!s || typeof s.name !== "string" || !/^[A-Za-z0-9][\w.-]*$/.test(s.name)) throw new ConfigError(`screen name must match [A-Za-z0-9][\\w.-]*: ${JSON.stringify(s?.name)}`);
    if (seen.has(s.name)) throw new ConfigError(`duplicate screen name: ${s.name}`);
    seen.add(s.name);
    if (typeof s.path !== "string" || !s.path || isAbsolute(s.path) || s.path.includes("\\") || s.path.split("/").some((p) => p === ".." || p === "" || p === ".")) {
      throw new ConfigError(`${s.name}: "path" must be a repo-relative path without "..": ${JSON.stringify(s.path)}`);
    }
    if (!/\.html?$/i.test(s.path)) throw new ConfigError(`${s.name}: "path" must be an .html file: ${s.path}`);
    if (s.selector !== undefined && (typeof s.selector !== "string" || !s.selector)) throw new ConfigError(`${s.name}: "selector" must be a non-empty string`);
    if (s.fullPage !== undefined && typeof s.fullPage !== "boolean") throw new ConfigError(`${s.name}: "fullPage" must be a boolean`);
    if (s.selector && s.fullPage) throw new ConfigError(`${s.name}: "selector" and "fullPage" are exclusive`);
  }
  return c as Config;
}

export async function loadConfig(file = DEFAULT_CONFIG): Promise<Config> {
  let text: string;
  try {
    text = await readFile(file, "utf8");
  } catch (e) {
    throw new ConfigError(`cannot read ${file}: ${(e as Error).message}`);
  }
  try {
    return validateConfig(JSON.parse(text));
  } catch (e) {
    if (e instanceof ConfigError) throw e;
    throw new ConfigError(`${file} is not valid JSON: ${(e as Error).message}`);
  }
}

/** Absolute path of an existing file that really lies inside `root` (symlinks resolved), else null. */
export function resolveInside(root: string, rel: string): string | null {
  const abs = join(root, rel);
  if (!existsSync(abs)) return null;
  const real = realpathSync(abs);
  const realRoot = realpathSync(root);
  return real === realRoot || real.startsWith(realRoot + sep) ? real : null;
}

/** Outside CI a local browser run must come through the P0-09 resource guard (docs/process/dev-resources.md). */
export function guardProblem(env: NodeJS.ProcessEnv = process.env): string | null {
  if (env.CI === "true" || env.KINETRA_GUARD_PASSED === "1") return null;
  return "a local browser run must start through the resource guard:\n  uv run python tools/dev/resource_guard.py --profile heavy -- <this command>";
}

/**
 * Blocks every http(s)/ftp request and WebSocket (pages render from local files only: one source of variation less, not a
 * guarantee of identical pixels, see docs/process/screenshots.md). Returns the list of blocked URLs, filled as the page runs.
 */
async function offline(ctx: import("playwright-core").BrowserContext): Promise<string[]> {
  const blocked: string[] = [];
  await ctx.route(/^(https?|ftp):/i, (r) => {
    blocked.push(r.request().url());
    return r.abort();
  });
  await ctx.routeWebSocket(/.*/, (ws) => {
    blocked.push(ws.url());
    void ws.close({ code: 1008, reason: "offline" });
  });
  return blocked;
}

export async function captureAll(config: Config, outDir: string, browser: Browser, root = REPO_ROOT): Promise<Outcome[]> {
  await mkdir(outDir, { recursive: true });
  const outcomes: Outcome[] = [];
  for (const s of config.screens) {
    const abs = resolveInside(root, s.path);
    if (!abs) {
      const reason = existsSync(join(root, s.path)) ? "resolves outside the repository" : "path not found";
      console.log(`SKIP ${s.name}: ${s.path} (${reason})`);
      outcomes.push({ name: s.name, path: s.path, status: "skipped", reason });
      continue;
    }
    const ctx = await browser.newContext({ viewport: config.viewport, deviceScaleFactor: 1, reducedMotion: "reduce" });
    try {
      const blocked = await offline(ctx);
      const page = await ctx.newPage();
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(pathToFileURL(abs).href, { waitUntil: "load" });
      await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}" });
      await page.evaluate(() => document.fonts.ready);
      const png = s.selector
        ? await page.locator(s.selector).screenshot({ animations: "disabled", caret: "hide", timeout: 15_000 })
        : await page.screenshot({ fullPage: s.fullPage ?? false, animations: "disabled", caret: "hide" });
      const file = join(outDir, `${s.name}.png`);
      await writeFile(file, png);
      const width = png.readUInt32BE(16), height = png.readUInt32BE(20); // IHDR
      outcomes.push({
        name: s.name, path: s.path, status: "captured", file: relative(root, file).split(sep).join("/"), width, height, bytes: png.length,
        sha256: createHash("sha256").update(png).digest("hex"), ...(errors.length ? { page_errors: errors } : {}),
        ...(blocked.length ? { blocked_requests: [...blocked] } : {}),
      });
      console.log(`OK   ${s.name}: ${s.path} -> ${width}x${height} (${png.length} bytes)${errors.length ? ` [${errors.length} page error(s)]` : ""}${blocked.length ? ` [${blocked.length} external request(s) blocked]` : ""}`);
    } catch (e) {
      const reason = (e as Error).message.split("\n")[0]!;
      console.log(`FAIL ${s.name}: ${s.path}: ${reason}`);
      outcomes.push({ name: s.name, path: s.path, status: "failed", reason });
    } finally {
      await ctx.close();
    }
  }
  await writeFile(join(outDir, "manifest.json"), JSON.stringify({ viewport: config.viewport, screens: outcomes }, null, 2) + "\n");
  return outcomes;
}

export function parseArgs(argv: string[]): { out: string; config: string } {
  let out = DEFAULT_OUT, config = DEFAULT_CONFIG;
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--out" && argv[i + 1]) out = resolve(argv[++i]!);
    else if (v === "--config" && argv[i + 1]) config = resolve(argv[++i]!);
    else throw new ConfigError(`unknown argument: ${v}`);
  }
  return { out, config };
}

async function main(): Promise<number> {
  try {
    const args = parseArgs(process.argv.slice(2));
    const config = await loadConfig(args.config);
    const problem = guardProblem();
    if (problem) {
      console.error(problem);
      return 3;
    }
    const browser = await chromium.launch();
    try {
      const outcomes = await captureAll(config, args.out, browser);
      const n = (k: Outcome["status"]) => outcomes.filter((o) => o.status === k).length;
      console.log(`captured=${n("captured")} skipped=${n("skipped")} failed=${n("failed")} -> ${args.out}`);
      if (n("captured") === 0) {
        console.error("nothing was captured: every listed path is missing or failed");
        return 1;
      }
      return n("failed") ? 1 : 0;
    } finally {
      await browser.close();
    }
  } catch (e) {
    if (e instanceof ConfigError) {
      console.error(e.message);
      return 2;
    }
    console.error(e);
    return 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
