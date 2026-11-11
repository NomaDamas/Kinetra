import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { APT_OPTIONS, aptCommands, main, parseMissing, splitMissing } from "../playwright_deps.mjs";

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

test("fonts are best effort, libraries are required", () => {
  assert.deepEqual(splitMissing(["libnss3", "fonts-unifont", "xfonts-utils", "libasound2t64"]), {
    libs: ["libnss3", "libasound2t64"],
    fonts: ["fonts-unifont", "xfonts-utils"],
  });
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
