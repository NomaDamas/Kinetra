// Offline tests (no browser): config validation, path resolution, guard.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ConfigError, guardProblem, loadConfig, parseArgs, resolveInside, validateConfig, DEFAULT_CONFIG } from "../capture.ts";

const VP = { width: 1280, height: 800 };
const ok = (screens: unknown[]) => validateConfig({ viewport: VP, screens });

test("the committed .github/screenshots.json is valid and lists the design system", async () => {
  const c = await loadConfig(DEFAULT_CONFIG);
  assert.ok(c.screens.some((s) => s.path === "design/exports/design-system/index.html"));
});

test("valid config passes", () => {
  assert.equal(ok([{ name: "a", path: "x/y.html", fullPage: true }]).screens.length, 1);
});

test("bad shapes are ConfigErrors", () => {
  const bad: unknown[] = [
    null, {}, { viewport: VP }, { viewport: VP, screens: [] }, { viewport: { width: 10, height: 10 }, screens: [{ name: "a", path: "a.html" }] },
  ];
  for (const b of bad) assert.throws(() => validateConfig(b), ConfigError);
  const screens: [string, unknown][] = [
    ["bad name", { name: "../a", path: "a.html" }], ["empty name", { name: "", path: "a.html" }], ["absolute", { name: "a", path: "/etc/x.html" }],
    ["dotdot", { name: "a", path: "x/../../y.html" }], ["backslash", { name: "a", path: "x\\y.html" }], ["not html", { name: "a", path: "a.png" }],
    ["empty selector", { name: "a", path: "a.html", selector: "" }], ["selector+fullPage", { name: "a", path: "a.html", selector: "#x", fullPage: true }],
    ["fullPage type", { name: "a", path: "a.html", fullPage: "yes" }],
  ];
  for (const [why, s] of screens) assert.throws(() => ok([s]), ConfigError, why);
  assert.throws(() => ok([{ name: "a", path: "a.html" }, { name: "a", path: "b.html" }]), /duplicate/);
});

test("resolveInside: existing file ok, missing null, symlink escape null", () => {
  const root = mkdtempSync(join(tmpdir(), "kin-shot-root-"));
  const outside = mkdtempSync(join(tmpdir(), "kin-shot-out-"));
  try {
    mkdirSync(join(root, "d"));
    writeFileSync(join(root, "d", "a.html"), "<p>a</p>");
    writeFileSync(join(outside, "secret.html"), "<p>s</p>");
    symlinkSync(join(outside, "secret.html"), join(root, "d", "link.html"));
    assert.ok(resolveInside(root, "d/a.html"));
    assert.equal(resolveInside(root, "d/missing.html"), null);
    assert.equal(resolveInside(root, "d/link.html"), null);
  } finally {
    rmSync(root, { recursive: true });
    rmSync(outside, { recursive: true });
  }
});

test("guardProblem: CI or a passed guard allows; a bare local run is refused", () => {
  assert.equal(guardProblem({ CI: "true" }), null);
  assert.equal(guardProblem({ KINETRA_GUARD_PASSED: "1" }), null);
  assert.match(guardProblem({})!, /resource guard/);
  assert.match(guardProblem({ CI: "false" })!, /resource guard/);
});

test("parseArgs", () => {
  assert.equal(parseArgs(["--out", "/tmp/x"]).out, "/tmp/x");
  assert.throws(() => parseArgs(["--nope"]), ConfigError);
});
