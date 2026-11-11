#!/usr/bin/env node
// P0-08: install the OS libraries Playwright's headless Chromium needs WITHOUT depending on the apt mirrors being up.
// `playwright install --with-deps` always runs `apt-get update` + `apt-get install` with no retry and no timeout, so a
// `Temporary failure resolving 'security.ubuntu.com'` fails the job and a hung mirror eats the whole job limit.
// Here: (1) `install-deps --dry-run` (a local `apt-get install -s`, needs no network) lists what is really missing;
// (2) nothing missing -> apt is never contacted; (3) otherwise apt-get runs with retries + a per-connection timeout and
// a hard wall-clock limit, and the failure says which packages and which mirror step failed.
// Usage: node scripts/ci/playwright_deps.mjs <pnpm-package-filter> [browser]   (default browser: chromium-headless-shell)
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const APT_OPTIONS = ["-o", "Acquire::Retries=5", "-o", "Acquire::http::Timeout=20"];
export const APT_STEP_TIMEOUT_MS = 90 * 1000;

// Playwright prints `Missing system dependencies (N):` followed by `  <pkg>` lines; nothing missing prints
// `All system dependencies are installed.`. Returns the package names, [] when none are missing.
export function parseMissing(stdout) {
  const lines = stdout.split(/\r?\n/);
  const start = lines.findIndex((l) => /^Missing system dependencies \(\d+\):/.test(l));
  if (start === -1) return [];
  const pkgs = [];
  for (const l of lines.slice(start + 1)) {
    const m = l.match(/^ {2}(\S+)$/);
    if (!m) break;
    pkgs.push(m[1]);
  }
  return pkgs;
}

export const FALLBACK_MIRROR = "http://archive.ubuntu.com/ubuntu/";

// Points every apt source that uses the runner's default mirror at FALLBACK_MIRROR (the runner is ephemeral, so this is a throwaway edit).
export function mirrorFallbackCommand() {
  const sudo = process.getuid?.() === 0 ? [] : ["sudo"];
  const script =
    `for f in /etc/apt/sources.list /etc/apt/sources.list.d/*; do [ -f "$f" ] && ` +
    `sed -i -E 's#(mirror\\+file:/etc/apt/apt-mirrors\\.txt|https?://azure\\.archive\\.ubuntu\\.com/ubuntu/?)#${FALLBACK_MIRROR}#g' "$f"; done; true`;
  return [...sudo, "bash", "-c", script];
}

export function aptCommands(pkgs) {
  const sudo = process.getuid?.() === 0 ? [] : ["sudo"];
  return {
    update: [...sudo, "apt-get", ...APT_OPTIONS, "update"],
    install: [...sudo, "apt-get", ...APT_OPTIONS, "install", "-y", "--no-install-recommends", ...pkgs],
  };
}

function run(cmd, { timeout } = {}) {
  console.log(`$ ${cmd.join(" ")}`);
  const r = spawnSync(cmd[0], cmd.slice(1), { stdio: "inherit", timeout });
  if (r.error?.code === "ETIMEDOUT") {
    console.error(`::error::'${cmd.slice(0, 4).join(" ")} ...' exceeded ${timeout / 1000}s: the apt mirror is not answering.`);
  }
  return r.status === 0;
}

export function main(argv) {
  const [filter, browser = "chromium-headless-shell"] = argv;
  if (!filter) {
    console.error("usage: playwright_deps.mjs <pnpm-package-filter> [browser]");
    return 2;
  }
  const probe = spawnSync("pnpm", ["--filter", filter, "exec", "playwright-core", "install-deps", "--dry-run", browser], {
    encoding: "utf8",
  });
  process.stdout.write(probe.stdout ?? "");
  process.stderr.write(probe.stderr ?? "");
  const missing = parseMissing(probe.stdout ?? "");
  if (probe.status === 0 && missing.length === 0) {
    console.log("Playwright OS dependencies already present: apt is not contacted.");
    return 0;
  }
  if (missing.length === 0) {
    console.error(`::error::'playwright-core install-deps --dry-run' failed (exit ${probe.status}) without a missing-package list.`);
    return 1;
  }
  console.log(`Installing ${missing.length} missing package(s) with apt retries: ${missing.join(" ")}`);
  const cmds = aptCommands(missing);
  const step = (cmd) => run(cmd, { timeout: APT_STEP_TIMEOUT_MS });
  // 1) the package index baked into the runner image, no `update` round trip.
  if (step(cmds.install)) return 0;
  // 2) refresh the index and retry.
  console.log("apt-get install failed; refreshing the package index and retrying.");
  if (step(cmds.update) && step(cmds.install)) return 0;
  // 3) the runner's default mirror (azure.archive.ubuntu.com) can be the thing that is down: switch to the canonical one.
  console.log(`default Ubuntu mirror unreachable; retrying through ${FALLBACK_MIRROR}.`);
  if (step(mirrorFallbackCommand()) && step(cmds.update) && step(cmds.install)) return 0;
  // The fonts matter too: tools/design's pixel comparison fails (a shifted copy no longer differs) when they are missing.
  console.error(`::error::Playwright OS dependency install failed after apt retries on both Ubuntu mirrors (Acquire::Retries=5, http timeout 20s). Missing: ${missing.join(" ")}. This is an apt mirror/network problem, not a test failure: re-run the job.`);
  return 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
