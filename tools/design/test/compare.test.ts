// Needs the Playwright browser (see docs/process/design-workflow.md). Fails, not skips, when it is missing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { allowedOrigins, compareScreen, ConfigError, isAllowedRequest, loadScreens, validateScreen } from "../compare.ts";

const COMPARE = fileURLToPath(new URL("../compare.ts", import.meta.url));
const SIDE = { url: "design/exports/design-system/index.html", selector: "#valuebadges" };

test("_trial: approved render vs an unmodified copy passes", async () => {
  const out = mkdtempSync(join(tmpdir(), "kin-compare-"));
  try {
    const screens = await loadScreens();
    const outcomes = await compareScreen("_trial", screens["_trial"]!, out);
    assert.ok(outcomes.length >= 2);
    for (const o of outcomes) {
      assert.equal(o.pass, true, `${o.pair}: ${o.reasons.join("; ")}`);
      assert.equal(o.diffPixels, 0, `${o.pair} must render identically twice`);
      assert.ok(existsSync(o.files.diff));
    }
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("_trial-shifted: a deliberately shifted copy fails and writes a diff image", async () => {
  const out = mkdtempSync(join(tmpdir(), "kin-compare-"));
  try {
    const screens = await loadScreens();
    const outcomes = await compareScreen("_trial-shifted", screens["_trial-shifted"]!, out);
    assert.ok(outcomes.length >= 1);
    for (const o of outcomes) {
      assert.equal(o.pass, false, `${o.pair} must fail`);
      assert.ok(o.diffPixels > 0);
      assert.ok(existsSync(o.files.diff));
    }
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("an exception without a reason is rejected before anything is rendered", async () => {
  const out = mkdtempSync(join(tmpdir(), "kin-compare-"));
  try {
    const side = SIDE;
    await assert.rejects(
      compareScreen("_no-reason", { pairs: [{ name: "x", approved: side, implemented: side, tolerance: { maxDiffRatio: 0.5 } }] }, out),
      (e) => e instanceof ConfigError && /needs a "reason"/.test(e.message),
    );
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("config errors are ConfigError: empty pairs, bad tolerance key, non-local url, duplicate name", () => {
  const bad = (screen: unknown, re: RegExp) =>
    assert.throws(() => validateScreen("s", screen as never), (e) => e instanceof ConfigError && re.test(e.message));
  bad({ pairs: [] }, /"pairs" is empty/);
  bad({}, /"pairs" must be an array/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: SIDE, reason: "r", tolerance: { maxIgnoredRatio: 1 } }] }, /unknown tolerance key/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: SIDE, reason: "r", tolerance: { maxDiffRatio: -1 } }] }, /finite number/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: { url: "https://example.com/" } }] }, /must be a local server/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: { url: "http://127.0.0.1.evil.com/" } }] }, /must be a local server/);
  bad({ pairs: [{ name: "x", approved: SIDE, implemented: SIDE }, { name: "x", approved: SIDE, implemented: SIDE }] }, /duplicate/);
  validateScreen("s", { pairs: [{ name: "ok", approved: SIDE, implemented: { url: "http://localhost:5173/" } }] });
});

test("an empty screen exits compareScreen with ConfigError before any browser starts", async () => {
  await assert.rejects(compareScreen("e", { pairs: [] }, tmpdir()), ConfigError);
});

test("CLI: usage errors, unknown screen exit 2", () => {
  const run = (...args: string[]) => spawnSync(process.execPath, [COMPARE, ...args], { encoding: "utf8" });
  assert.equal(run().status, 2);
  assert.equal(run("--bogus").status, 2);
  const r = run("--screen", "no-such-screen");
  assert.equal(r.status, 2);
  assert.match(r.stderr, /not in tools\/design\/screens\.json/);
});

test("request allow-list uses the parsed origin, not a string prefix", () => {
  const origins = allowedOrigins("http://127.0.0.1:5173/app");
  assert.equal(isAllowedRequest("http://127.0.0.1:5173/assets/a.js", origins), true);
  assert.equal(isAllowedRequest("file:///tmp/x.html", origins), true);
  assert.equal(isAllowedRequest("http://127.0.0.1:5173.evil.com/a.js", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1:5173@evil.com/a.js", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1.evil.com/a.js", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1:5174/a.js", origins), false);
  assert.equal(isAllowedRequest("https://127.0.0.1:5173/a.js", origins), false);
  assert.equal(isAllowedRequest("https://fonts.googleapis.com/css2", origins), false);
  assert.equal(isAllowedRequest("not a url", origins), false);
  assert.equal(isAllowedRequest("http://127.0.0.1:5173/a.js", allowedOrigins("design/exports/x/index.html")), false);
});
