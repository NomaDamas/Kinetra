#!/usr/bin/env node
// P0-08: install the OS libraries Playwright's headless Chromium needs WITHOUT depending on the apt mirrors being up.
// `playwright install --with-deps` always runs `apt-get update` + `apt-get install` with no retry and no timeout, so a
// `Temporary failure resolving 'security.ubuntu.com'` fails the job and a hung mirror eats the whole job limit.
// Here: (1) `install-deps --dry-run` (a local `apt-get install -s`, needs no network) says what is missing;
// (2) ONLY the known "All system dependencies are installed." answer skips apt; (3) anything else installs, through apt
// with retries + a per-connection timeout + a wall-clock limit per call, switching to independent mirrors when the
// runner's default hosts (azure/archive/security/ports.ubuntu.com) do not answer; (4) failure says what and why.
// Usage: node scripts/ci/playwright_deps.mjs <pnpm-package-filter> [browser]   (default browser: chromium-headless-shell)
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const APT_OPTIONS = ["-o", "Acquire::Retries=5", "-o", "Acquire::http::Timeout=20"];
export const APT_STEP_TIMEOUT_MS = 60 * 1000;
export const ALL_PRESENT = "All system dependencies are installed.";
export const APT_CONF_PATH = "/etc/apt/apt.conf.d/99kinetra-ci";
const APT_CONF = 'Acquire::Retries "5";\nAcquire::http::Timeout "20";\n';

// Playwright prints `Missing system dependencies (N):` followed by `  <pkg>` lines. Returns the package names, [] if none listed.
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

// "present" only when the dry run succeeded AND printed exactly the known no-op line and no missing list.
export function allPresent(status, stdout) {
  return status === 0 && stdout.split(/\r?\n/).some((l) => l.trim() === ALL_PRESENT) && parseMissing(stdout).length === 0;
}

// Independent of Canonical's own hosts: on 2026-11-11 both azure.archive.ubuntu.com and archive.ubuntu.com were unreachable.
// `ports` is the arm64 archive (ubuntu-ports); null where the mirror does not carry it (checked by curl on 2026-11-11).
export const FALLBACK_MIRRORS = [
  { archive: "https://mirrors.edge.kernel.org/ubuntu/", ports: null },
  { archive: "https://mirrors.xtom.com/ubuntu/", ports: null },
  { archive: "https://mirror.us.leaseweb.net/ubuntu/", ports: "https://mirror.us.leaseweb.net/ubuntu-ports/" },
];
const esc = (u) => u.replace(/[.+]/g, "\\$&");
// Hosts the runner image may use, in both sources.list (`deb URL suite ...`) and deb822 .sources (`URIs: URL`) form.
// Fallback URLs always end in `/ubuntu/` or `/ubuntu-ports/` so the archive pattern never matches the ports URL.
const DEFAULT_ARCHIVE_RE = "mirror\\+file:/etc/apt/apt-mirrors\\.txt|https?://((azure\\.)?archive|security)\\.ubuntu\\.com/ubuntu/?";
const DEFAULT_PORTS_RE = "https?://ports\\.ubuntu\\.com/ubuntu-ports/?";

export function fallbackMirrorsFor(arch) {
  return /arm|aarch/.test(arch) ? FALLBACK_MIRRORS.filter((m) => m.ports) : FALLBACK_MIRRORS;
}

// Rewrites every apt source (archive, security, ports; sources.list and deb822) to `mirror`. Running it for the next fallback also
// moves sources that an earlier fallback pointed at. The runner is ephemeral, so this is a throwaway edit.
export function mirrorFallbackCommand(mirror, { sudo = process.getuid?.() !== 0, files = "/etc/apt/sources.list /etc/apt/sources.list.d/*" } = {}) {
  const archiveRe = [DEFAULT_ARCHIVE_RE, ...FALLBACK_MIRRORS.map((m) => esc(m.archive))].join("|");
  const portsRe = [DEFAULT_PORTS_RE, ...FALLBACK_MIRRORS.filter((m) => m.ports).map((m) => esc(m.ports))].join("|");
  const exprs = [`-e 's#(${archiveRe})#${mirror.archive}#g'`];
  if (mirror.ports) exprs.push(`-e 's#(${portsRe})#${mirror.ports}#g'`);
  // write-then-mv instead of `sed -i`: BSD and GNU sed disagree on -i, so the same script runs in tests anywhere.
  const script = `for f in ${files}; do [ -f "$f" ] && sed -E ${exprs.join(" ")} "$f" > "$f.new" && mv "$f.new" "$f"; done; true`;
  return [...(sudo ? ["sudo"] : []), "bash", "-c", script];
}

export function aptCommands(pkgs, { sudo = process.getuid?.() !== 0 } = {}) {
  const s = sudo ? ["sudo"] : [];
  return {
    update: [...s, "apt-get", ...APT_OPTIONS, "update"],
    install: [...s, "apt-get", ...APT_OPTIONS, "install", "-y", "--no-install-recommends", ...pkgs],
  };
}

// Decision flow with every side effect behind `exec(cmd, { timeout, capture }) -> { status, stdout?, timedOut? }`, so tests inject
// the dry-run answer and the apt outcome per mirror. Returns the process exit code.
export function ensureDeps({ filter, browser = "chromium-headless-shell", exec, arch = "x64", sudo = false, log = console.log, error = console.error }) {
  const probeCmd = ["pnpm", "--filter", filter, "exec", "playwright-core", "install-deps", "--dry-run", browser];
  const probe = exec(probeCmd, { capture: true });
  const out = probe.stdout ?? "";
  if (allPresent(probe.status, out)) {
    log("Playwright OS dependencies already present: apt is not contacted.");
    return 0;
  }
  const missing = parseMissing(out);
  const step = (cmd) => {
    const r = exec(cmd, { timeout: APT_STEP_TIMEOUT_MS });
    if (r.timedOut) error(`::error::'${cmd.slice(0, 4).join(" ")} ...' exceeded ${APT_STEP_TIMEOUT_MS / 1000}s: the apt mirror is not answering.`);
    return r.status === 0;
  };
  let cmds;
  if (missing.length > 0) {
    log(`Installing ${missing.length} missing package(s) with apt retries: ${missing.join(" ")}`);
    cmds = aptCommands(missing, { sudo });
  } else {
    // Unknown dry-run output (exit ${probe.status}): do not assume anything is present. Let Playwright install what it needs, with the
    // same retries/timeouts forced through an apt.conf.d snippet since we cannot pass -o to its apt calls.
    log(`'install-deps --dry-run' gave no known answer (exit ${probe.status}); installing through 'playwright-core install-deps'.`);
    const s = sudo ? ["sudo"] : [];
    step([...s, "bash", "-c", `printf '${APT_CONF.replace(/\n/g, "\\n")}' > ${APT_CONF_PATH}`]);
    cmds = {
      update: aptCommands([], { sudo }).update,
      install: ["pnpm", "--filter", filter, "exec", "playwright-core", "install-deps", browser],
    };
  }
  // 1) default mirror, using the package index baked into the runner image (no `update` round trip).
  if (step(cmds.install)) return 0;
  // 2) the default mirror can be the thing that is down: independent mirrors, one after another.
  //    Worst case 60s + 3 x (60s update + 60s install) = 7 min, inside the step's timeout-minutes: 8.
  for (const mirror of fallbackMirrorsFor(arch)) {
    log(`default Ubuntu mirror unreachable; retrying through ${mirror.archive}.`);
    if (step(mirrorFallbackCommand(mirror, { sudo })) && step(cmds.update) && step(cmds.install)) return 0;
  }
  // The fonts matter too: tools/design's pixel comparison fails (a shifted copy no longer differs) when they are missing.
  error(
    `::error::Playwright OS dependency install failed after apt retries on the default and every fallback mirror (Acquire::Retries=5, http timeout 20s).` +
      (missing.length ? ` Missing: ${missing.join(" ")}.` : "") +
      ` This is an apt mirror/network problem, not a test failure: re-run the job.`,
  );
  return 1;
}

function realExec(cmd, { timeout, capture } = {}) {
  log_(`$ ${cmd.join(" ")}`);
  const r = spawnSync(cmd[0], cmd.slice(1), { stdio: capture ? ["inherit", "pipe", "inherit"] : "inherit", timeout, encoding: "utf8" });
  if (capture) process.stdout.write(r.stdout ?? "");
  return { status: r.status ?? 1, stdout: r.stdout ?? "", timedOut: r.error?.code === "ETIMEDOUT" };
}
const log_ = (m) => console.log(m);

export function main(argv) {
  const [filter, browser] = argv;
  if (!filter) {
    console.error("usage: playwright_deps.mjs <pnpm-package-filter> [browser]");
    return 2;
  }
  return ensureDeps({ filter, browser, exec: realExec, arch: process.arch, sudo: process.getuid?.() !== 0 });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
