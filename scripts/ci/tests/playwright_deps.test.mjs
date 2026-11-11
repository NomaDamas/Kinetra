import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ALL_PRESENT, APT_OPTIONS, aptCommands, allPresent, ensureDeps, fallbackMirrorsFor, main, parseMissing, FALLBACK_MIRRORS, mirrorFallbackCommand } from "../playwright_deps.mjs";

test("nothing missing -> no packages", () => {
  assert.deepEqual(parseMissing("All system dependencies are installed.\n"), []);
  assert.deepEqual(parseMissing(""), []);
});

test("missing list is parsed up to the first non-package line", () => {
  const out = "Missing system dependencies (2):\n  libasound2t64\n  libnss3\n\nother output\n  notapackage\n";
  assert.deepEqual(parseMissing(out), ["libasound2t64", "libnss3"]);
});

test("apt commands carry retries and a connection timeout, install is non-interactive and minimal", () => {
  const { update, install } = aptCommands(["libnss3"]);
  for (const cmd of [update, install]) {
    const i = cmd.indexOf("apt-get");
    assert.deepEqual(cmd.slice(i + 1, i + 1 + APT_OPTIONS.length), APT_OPTIONS);
  }
  assert.ok(APT_OPTIONS.includes("Acquire::Retries=5") && APT_OPTIONS.includes("Acquire::http::Timeout=20"));
  assert.ok(install.includes("-y") && install.includes("--no-install-recommends") && install.at(-1) === "libnss3");
});

// Real sed over fixture files, covering sources.list (`deb URL`) and deb822 (`URIs:`) for archive, security and ports.
function rewriteFixture(mirror, files) {
  const dir = mkdtempSync(join(tmpdir(), "kin-apt-"));
  try {
    const paths = Object.entries(files).map(([name, text]) => {
      writeFileSync(join(dir, name), text);
      return join(dir, name);
    });
    const cmd = mirrorFallbackCommand(mirror, { sudo: false, files: paths.join(" ") });
    assert.equal(spawnSync(cmd[0], cmd.slice(1)).status, 0);
    return Object.fromEntries(Object.keys(files).map((n) => [n, readFileSync(join(dir, n), "utf8")]));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
const UBUNTU_SOURCES = `Types: deb
URIs: http://azure.archive.ubuntu.com/ubuntu/
Suites: noble noble-updates
Components: main

Types: deb
URIs: http://security.ubuntu.com/ubuntu/
Suites: noble-security
Components: main
`;
const LEGACY = `deb http://archive.ubuntu.com/ubuntu noble main
deb http://security.ubuntu.com/ubuntu noble-security main
deb http://ports.ubuntu.com/ubuntu-ports noble main
deb mirror+file:/etc/apt/apt-mirrors.txt noble-updates main
deb https://packages.microsoft.com/ubuntu/24.04/prod noble main
`;

test("mirror rewrite covers azure/archive/security/mirrorlist in sources.list and deb822, leaves other repos alone", () => {
  const [m] = FALLBACK_MIRRORS;
  const r = rewriteFixture(m, { "ubuntu.sources": UBUNTU_SOURCES, "sources.list": LEGACY });
  assert.equal(r["ubuntu.sources"], UBUNTU_SOURCES.replaceAll("http://azure.archive.ubuntu.com/ubuntu/", m.archive).replaceAll("http://security.ubuntu.com/ubuntu/", m.archive));
  assert.match(r["sources.list"], new RegExp(`^deb ${m.archive.replace(/\./g, "\\.")} noble main$`, "m"));
  assert.match(r["sources.list"], new RegExp(`^deb ${m.archive.replace(/\./g, "\\.")} noble-security main$`, "m"));
  assert.match(r["sources.list"], /^deb http:\/\/ports\.ubuntu\.com\/ubuntu-ports noble main$/m, "a mirror without ports leaves ports alone");
  assert.match(r["sources.list"], /^deb https:\/\/packages\.microsoft\.com\/ubuntu\/24\.04\/prod noble main$/m);
  assert.ok(!/azure|security\.ubuntu|mirror\+file/.test(r["ubuntu.sources"] + r["sources.list"]));
});

test("mirror rewrite maps ports.ubuntu.com to the mirror's ubuntu-ports and moves a previous fallback", () => {
  const withPorts = FALLBACK_MIRRORS.find((m) => m.ports);
  const first = FALLBACK_MIRRORS[0];
  const r = rewriteFixture(withPorts, {
    "ubuntu.sources": `URIs: http://ports.ubuntu.com/ubuntu-ports/\nURIs: ${first.archive}\nURIs: http://security.ubuntu.com/ubuntu/\n`,
  });
  assert.equal(r["ubuntu.sources"], `URIs: ${withPorts.ports}\nURIs: ${withPorts.archive}\nURIs: ${withPorts.archive}\n`);
});

test("arm runners only fall back to mirrors that carry ubuntu-ports", () => {
  assert.ok(fallbackMirrorsFor("arm64").every((m) => m.ports));
  assert.equal(fallbackMirrorsFor("x64").length, FALLBACK_MIRRORS.length);
});

// ---- decision flow with an injected exec ----
const FILTER = "@kinetra/x";
const DRY = (c) => c.includes("--dry-run");
const isInstall = (c) => c.includes("install") && c.includes("apt-get");
const isUpdate = (c) => c.includes("apt-get") && c.includes("update");
const isRewrite = (c) => c[0] === "bash" || c.includes("bash");
const MISSING_OUT = "Missing system dependencies (2):\n  fonts-unifont\n  libnss3\n";

// exec fake: `dry` = {status, stdout}; `works(mirrorIndex)` says if apt works once the sources point at that mirror (-1 = default).
function fake(dry, works) {
  const calls = [];
  let mirror = -1;
  const exec = (cmd) => {
    calls.push(cmd);
    if (DRY(cmd)) return dry;
    if (isRewrite(cmd) && cmd.at(-1).includes("sed -E")) {
      const m = FALLBACK_MIRRORS.findIndex((x) => cmd.at(-1).includes(`#${x.archive}#`));
      mirror = m;
      return { status: 0 };
    }
    if (isInstall(cmd) || isUpdate(cmd) || cmd.includes("install-deps") || isRewrite(cmd)) {
      return works(mirror) ? { status: 0 } : { status: 100, timedOut: true };
    }
    return { status: 0 };
  };
  return { exec, calls };
}
const run = (dry, works, extra = {}) => {
  const f = fake(dry, works);
  const errors = [];
  const code = ensureDeps({ filter: FILTER, exec: f.exec, log: () => {}, error: (m) => errors.push(m), ...extra });
  return { code, calls: f.calls, errors };
};

test("flow: known 'all installed' answer skips apt entirely", () => {
  const r = run({ status: 0, stdout: `${ALL_PRESENT}\n` }, () => false);
  assert.equal(r.code, 0);
  assert.equal(r.calls.length, 1);
});

test("flow: missing packages and a working default mirror -> one apt install, no mirror switch", () => {
  const r = run({ status: 1, stdout: MISSING_OUT }, () => true);
  assert.equal(r.code, 0);
  assert.equal(r.calls.filter(isInstall).length, 1);
  assert.deepEqual(r.calls.find(isInstall).slice(-2), ["fonts-unifont", "libnss3"]);
  assert.ok(!r.calls.some((c) => c.at(-1).includes?.("sed -E")));
});

test("flow: default mirror fails -> fallback mirrors are tried in order until one works", () => {
  const r = run({ status: 1, stdout: MISSING_OUT }, (m) => m === 1);
  assert.equal(r.code, 0);
  const rewrites = r.calls.filter((c) => c.at(-1).includes?.("sed -E"));
  assert.equal(rewrites.length, 2);
  assert.ok(rewrites[0].at(-1).includes(`#${FALLBACK_MIRRORS[0].archive}#`));
  assert.ok(rewrites[1].at(-1).includes(`#${FALLBACK_MIRRORS[1].archive}#`));
});

test("flow: every mirror fails -> non-zero with a clear message naming the packages", () => {
  const r = run({ status: 1, stdout: MISSING_OUT }, () => false);
  assert.equal(r.code, 1);
  assert.equal(r.calls.filter((c) => c.at(-1).includes?.("sed -E")).length, FALLBACK_MIRRORS.length);
  assert.ok(r.errors.some((e) => e.includes("fonts-unifont libnss3") && e.includes("re-run the job")));
});

test("flow: unknown dry-run output (even exit 0) is NOT treated as present -> installs via playwright install-deps", () => {
  for (const dry of [{ status: 0, stdout: "something new\n" }, { status: 1, stdout: "" }, { status: 0, stdout: "" }]) {
    const r = run(dry, () => true);
    assert.equal(r.code, 0);
    assert.ok(r.calls.some((c) => c.includes("install-deps") && !c.includes("--dry-run")), JSON.stringify(dry));
    assert.ok(r.calls.some((c) => c.at(-1).includes?.("Acquire::Retries")), "apt retry config is written first");
  }
});

test("flow: unknown dry-run output with all mirrors failing -> non-zero", () => {
  assert.equal(run({ status: 1, stdout: "boom" }, () => false).code, 1);
});

test("allPresent needs exit 0 and the exact known line", () => {
  assert.equal(allPresent(0, `${ALL_PRESENT}\n`), true);
  assert.equal(allPresent(1, `${ALL_PRESENT}\n`), false);
  assert.equal(allPresent(0, ""), false);
  assert.equal(allPresent(0, `${ALL_PRESENT}\nMissing system dependencies (1):\n  libnss3\n`), false);
});

test("missing package filter argument is a usage error", () => {
  assert.equal(main([]), 2);
});

// Every workflow that installs a Playwright browser uses the resilient path: no `--with-deps` (apt without retry/timeout),
// and each install step has its own timeout-minutes so a hang fails fast.
const WORKFLOWS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", ".github", "workflows");
test("no workflow runs `playwright install --with-deps`; install steps are time-boxed", () => {
  for (const f of readdirSync(WORKFLOWS).filter((n) => n.endsWith(".yml"))) {
    const text = readFileSync(join(WORKFLOWS, f), "utf8");
    assert.ok(!/playwright(-core)?\s+install\b[^\n]*--with-deps/.test(text), `${f} uses --with-deps`);
    const steps = text.split(/\n(?=      - )/);
    for (const step of steps) {
      if (/playwright-core\s+install\s/.test(step) || /playwright_deps\.mjs/.test(step)) {
        assert.match(step, /timeout-minutes: \d+/, `${f}: Playwright install step without timeout-minutes:\n${step}`);
      }
    }
  }
});
