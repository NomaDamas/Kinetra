// Needs the Playwright browser (see docs/process/design-workflow.md). Fails, not skips, when it is missing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { compareScreen, loadScreens } from "../compare.ts";

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
    const side = { url: "design/exports/design-system/index.html", selector: "#valuebadges" };
    await assert.rejects(
      compareScreen("_no-reason", { pairs: [{ name: "x", approved: side, implemented: side, tolerance: { maxDiffRatio: 0.5 } }] }, out),
      /needs a "reason"/,
    );
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});
