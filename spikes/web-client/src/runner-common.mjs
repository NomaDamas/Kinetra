// Shared by measure-pose.mjs and measure-replay.mjs: guard check, machine facts, browser launch.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import os from "node:os";
import { join } from "node:path";

export function requireGuard(script, pkgScript) {
  if (process.env.KINETRA_GUARD_PASSED !== "1") {
    console.error(`${script} is a heavy run (docs/process/dev-resources.md). Start it through the guard:\n  uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/web-client ${pkgScript}`);
    process.exit(2);
  }
}
const sh = (cmd, args) => { try { return execFileSync(cmd, args, { encoding: "utf8" }).trim(); } catch { return null; } };
export function machine() {
  return { cpu: sh("sysctl", ["-n", "machdep.cpu.brand_string"]), ncpu: os.cpus().length, platform: `${os.type()} ${os.release()} ${os.arch()}`,
    load_avg: os.loadavg().map((x) => +x.toFixed(1)), swap: sh("sysctl", ["-n", "vm.swapusage"]), node: process.version };
}
/** Playwright's own Chromium Headless Shell from the shared cache (chromium_headless_shell-1254, never a second install). */
export function launch(extraArgs = []) {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH ?? join(os.homedir(), "Library", "Caches", "ms-playwright");
  const dir = existsSync(cache) ? readdirSync(cache).find((d) => d.startsWith("chromium_headless_shell-")) : null;
  if (!dir) throw new Error(`no chromium_headless_shell-* in ${cache}; install with: pnpm --dir spikes/web-client exec playwright-core install chromium-headless-shell`);
  return chromium.launch({ headless: true, args: extraArgs }); // playwright-core 1.65.0 resolves the same cached revision
}
