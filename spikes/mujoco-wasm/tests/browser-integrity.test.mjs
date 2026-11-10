// Real-browser failure path: with a tampered model or tampered control schedule the page must report an error and
// produce no result. Needs Playwright's Chromium (`playwright install chromium-headless-shell`); run it through the
// resource guard like measure.mjs:  uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/mujoco-wasm test:browser
import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { startServer } from "../serve.mjs";

async function run(route) {
  const server = await startServer(0);
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    if (route) await page.route(route.pattern, route.handler);
    await page.goto(`http://127.0.0.1:${server.address().port}/?bare=1&loops=1`);
    await page.waitForFunction(() => window.__A0_01B_RESULT || window.__A0_01B_ERROR, null, { timeout: 120_000 });
    return { result: await page.evaluate(() => window.__A0_01B_RESULT), error: await page.evaluate(() => window.__A0_01B_ERROR) };
  } finally {
    await browser.close();
    server.close();
  }
}

test("untouched inputs: the page produces a result and no error", async () => {
  const r = await run(null);
  assert.equal(r.error, undefined);
  assert.equal(r.result.integrity.model_hash_ok, true);
  assert.equal(r.result.integrity.control_hash_ok_scenarios, 21);
});

test("tampered model: error mentions model integrity, no result", async () => {
  const r = await run({ pattern: "**/model/rocket_car.xml", handler: async (route) => {
    const resp = await route.fetch();
    await route.fulfill({ response: resp, body: (await resp.text()).replace('timestep="0.004"', 'timestep="0.005"') });
  } });
  assert.match(r.error, /model integrity/);
  assert.equal(r.result, undefined);
});

test("tampered controls (manifest window throttle changed): error mentions control integrity, no result", async () => {
  const r = await run({ pattern: "**/reference/manifest.json", handler: async (route) => {
    const resp = await route.fetch();
    const m = await resp.json();
    m.scenarios[0].windows[0].mag *= 0.5;
    await route.fulfill({ response: resp, json: m });
  } });
  assert.match(r.error, /control integrity/);
  assert.equal(r.result, undefined);
});
