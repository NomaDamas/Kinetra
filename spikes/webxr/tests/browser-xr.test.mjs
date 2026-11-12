// Real-browser test: Playwright's headless Chromium + IWER (Meta Quest 3) + @pmndrs/xr grabbing and moving one part.
// A browser run is a heavy run: outside CI it must start through the resource guard (docs/process/dev-resources.md):
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/webxr test:browser
// Needs Playwright's Chromium (`pnpm exec playwright-core install chromium-headless-shell`, one time).
import test from "node:test";
import assert from "node:assert/strict";
import { guardProblem } from "../guard.mjs";

const problem = guardProblem();
if (problem) throw new Error(problem); // import-time refusal, like tools/screenshots/test/*.browser.ts

const { runXr } = await import("../driver.mjs");

test("pmndrs/xr grabs one part in the IWER emulator and Playwright moves it to the asserted position", { timeout: 180_000 }, async () => {
  const { result, checks } = await runXr();
  for (const [name, ok] of Object.entries(checks)) assert.equal(ok, true, `${name}\n${JSON.stringify(result, null, 1)}`);
  // The final position, spelled out: start + the controller's displacement, within the stated tolerance.
  assert.ok(result.assertion.max_axis_error_m < result.assertion.tolerance_m);
  assert.ok(result.assertion.travelled_m > 0.3);
});
