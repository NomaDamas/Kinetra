#!/usr/bin/env node
// P0-08: install the OS libraries Playwright's headless Chromium needs WITHOUT depending on the apt mirrors being up.
// `playwright install --with-deps` always runs `apt-get update` + `apt-get install` with no retry and no timeout, so a
// `Temporary failure resolving 'security.ubuntu.com'` fails the job and a hung mirror eats the whole job limit.
// Here: (1) `install-deps --dry-run` (a local `apt-get install -s`, needs no network) lists what is really missing;
// (2) nothing missing -> apt is never contacted; (3) otherwise apt-get runs with retries + a per-connection timeout and
// a hard wall-clock limit, and the failure says which packages and which mirror step failed. Font packages are best effort.
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

// Browser libraries are required; font packages (fonts-*, xfonts-*) are not: the browser starts without them.
export function splitMissing(pkgs) {
  const isFont = (p) => /^(fonts|xfonts)-/.test(p);
  return { libs: pkgs.filter((p) => !isFont(p)), fonts: pkgs.filter(isFont) };
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
  const { libs, fonts } = splitMissing(missing);
  if (libs.length > 0) {
    console.log(`Installing ${libs.length} missing library package(s) with apt retries: ${libs.join(" ")}`);
    const cmds = aptCommands(libs);
    // First try the package index baked into the runner image; on failure refresh it and retry once.
    const ok = run(cmds.install, { timeout: APT_STEP_TIMEOUT_MS }) ||
      (console.log("apt-get install failed; refreshing the package index and retrying once."),
      run(cmds.update, { timeout: APT_STEP_TIMEOUT_MS }) && run(cmds.install, { timeout: APT_STEP_TIMEOUT_MS }));
    if (!ok) {
      console.error(`::error::Playwright OS library install failed after apt retries (Acquire::Retries=5, http timeout 20s). Missing: ${libs.join(" ")}. This is an apt mirror/network problem, not a test failure: re-run the job.`);
      return 1;
    }
  }
  if (fonts.length > 0) {
    console.log(`Installing ${fonts.length} missing font package(s) (best effort): ${fonts.join(" ")}`);
    if (!run(aptCommands(fonts).install, { timeout: APT_STEP_TIMEOUT_MS })) {
      // Fonts only change which glyphs the headless browser draws; they never stop it from starting. A dead mirror must not fail the job.
      console.log(`::warning::Playwright font packages not installed (apt mirror unreachable): ${fonts.join(" ")}. Pages render with the runner's system fonts.`);
    }
  }
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
