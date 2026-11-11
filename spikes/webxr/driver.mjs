// Playwright side of the A0-02b spike: build the page, serve it, open it in Playwright's own headless Chromium, enter
// an immersive-vr session on the IWER-emulated Meta Quest 3, and drive the right controller by script:
//   put the controller on the part -> squeeze (grab) -> move it -> release -> read where the part ended up.
// The controller is the emulator's (iwer XRController.position / updateButtonValue); the pointer events, the grab and the
// part's movement are @pmndrs/xr + @pmndrs/pointer-events + @pmndrs/handle running in the page.
import { chromium } from "playwright-core";
import { build } from "./build.mjs";
import { startServer } from "./serve.mjs";
import { PART } from "./src/scene.js";
import { waitForFrames } from "./src/waitframes.js";
import { POSITION_TOLERANCE_M, expectedFinal, maxAxisError, summarizeFrames } from "./src/expected.js";

/** Controller path after the grab, in metres relative to where it grabbed. Each leg is applied in STEPS frames. */
export const MOVE_LEGS = Object.freeze([[0.3, 0.15, -0.1], [0.0, 0.1, -0.2], [-0.1, -0.05, 0.05]]);
const STEPS_PER_LEG = 6;
const FRAME_SAMPLE = 120;

const FRAME_WAIT_TIMEOUT_MS = 15_000;
/** Wait for n more XR frames in the page; rejects on a page error or after FRAME_WAIT_TIMEOUT_MS (see src/waitframes.js). */
const frames = (page, n, timeoutMs = FRAME_WAIT_TIMEOUT_MS) => page.evaluate(
  `(${waitForFrames.toString()})(window, ${n}, ${timeoutMs}, (f) => requestAnimationFrame(f), (f, ms) => setTimeout(f, ms), (t) => clearTimeout(t))`,
);

const setController = (page, [x, y, z]) => page.evaluate(([x, y, z]) => window.__xrObjects.device.controllers.right.position.set(x, y, z), [x, y, z]);
const setSqueeze = (page, v) => page.evaluate((v) => window.__xrObjects.device.controllers.right.updateButtonValue("squeeze", v), v);
const partPosition = (page) => page.evaluate(() => window.__xrObjects.part.position.toArray());

/**
 * Runs the scenario and returns `{ result, checks }`. `result` is JSON-serialisable evidence; `checks` maps each DoD-level
 * assertion to a boolean so the caller (CLI or node:test) can fail with the name of the one that broke.
 */
export async function runXr({ chromiumArgs = [], executablePath, timeoutMs = 60_000 } = {}) {
  await build();
  const server = await startServer();
  let browser;
  const logs = [];
  try {
    browser = await chromium.launch({ headless: true, args: chromiumArgs, executablePath });
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
    page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
    const requested = [];
    page.on("request", (r) => { if (/^https?:/.test(r.url())) requested.push(r.url()); });
    const origin = `http://127.0.0.1:${server.address().port}`;
    await page.goto(`${origin}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__xr?.ready === true || window.__xr?.error, null, { timeout: timeoutMs });
    const pageErrorBeforeSession = await page.evaluate(() => window.__xr.error);
    const nativeXrBeforeInstall = await page.evaluate(() => window.__xr.nativeXrBeforeInstall);
    const emulatorIsInstalled = await page.evaluate(() => navigator.xr instanceof XRSystem && navigator.userAgent.includes("Quest 3"));

    // Enter VR with a real click (user gesture), then wait until both controllers are known to @pmndrs/xr.
    await page.click("#enter");
    await page.waitForFunction(() => window.__xr.sessionActive || window.__xr.error, null, { timeout: timeoutMs });
    await page.waitForFunction(() => {
      const s = window.__xrObjects.store.getState();
      return s.inputSourceStates.filter((i) => i.type === "controller").length === 2 && window.__xr.gripWorld;
    }, null, { timeout: timeoutMs });
    const session = await page.evaluate(() => {
      const s = window.__xrObjects.store.getState();
      return { mode: s.mode, controllers: s.inputSourceStates.filter((i) => i.type === "controller").map((i) => i.inputSource.handedness).sort(), profiles: s.inputSourceStates.find((i) => i.type === "controller").inputSource.profiles };
    });

    const shots = {};
    // 1. Put the right controller on the part (its grab sphere, radius 0.07 m, then overlaps the 0.2 m cube).
    await setController(page, PART.start);
    await frames(page, 4);
    const partBefore = await partPosition(page);
    shots.before_grab = await page.screenshot({ type: "png" });
    // 2. A controller moved WITHOUT squeezing must not move the part.
    await setController(page, PART.start.map((v, i) => v + [0.05, 0, 0][i]));
    await frames(page, 4);
    const partAfterFreeMove = await partPosition(page);
    await setController(page, PART.start);
    await frames(page, 4);

    // 3. Squeeze: the grab starts.
    await setSqueeze(page, 1);
    await page.waitForFunction(() => window.__xr.grabStarts >= 1, null, { timeout: timeoutMs });
    const gripAtGrab = await page.evaluate(() => window.__xr.gripAtGrab);

    // 4. Move the controller along MOVE_LEGS in small steps (a frame between steps), still squeezing.
    let pos = [...PART.start];
    for (const leg of MOVE_LEGS) {
      for (let k = 1; k <= STEPS_PER_LEG; k++) {
        await setController(page, pos.map((v, i) => v + (leg[i] * k) / STEPS_PER_LEG));
        await frames(page, 1);
      }
      pos = pos.map((v, i) => v + leg[i]);
    }
    await frames(page, 4); // let the last pose reach the handle
    const gripBeforeRelease = await page.evaluate(() => window.__xr.gripWorld);
    const partWhileHeld = await partPosition(page);

    // 5. Release; the part stays where it was dropped even if the controller keeps moving.
    await setSqueeze(page, 0);
    await page.waitForFunction(() => window.__xr.grabEnds >= 1, null, { timeout: timeoutMs });
    const partAfterRelease = await partPosition(page);
    await frames(page, 2);
    shots.after_release = await page.screenshot({ type: "png" });
    await setController(page, pos.map((v) => v + 0.2));
    await frames(page, 4);
    const partAfterReleaseAndMove = await partPosition(page);

    // 6. Frame pacing of the emulated session in this headless software-rendered run (NOT a headset frame rate).
    const sampleFrom = await page.evaluate(() => window.__xr.frameTimesMs.length);
    await frames(page, FRAME_SAMPLE);
    const times = await page.evaluate((from) => window.__xr.frameTimesMs.slice(from), sampleFrom);
    const pacing = summarizeFrames(times);
    const finalState = await page.evaluate(() => ({ frames: window.__xr.frames, grabStarts: window.__xr.grabStarts, grabEnds: window.__xr.grabEnds, error: window.__xr.error, nominalFrameRate: window.__xrObjects.store.getState().session?.frameRate ?? null }));

    const commanded = MOVE_LEGS.reduce((acc, leg) => acc.map((v, i) => v + leg[i]), [0, 0, 0]);
    const gripDisplacement = gripBeforeRelease.map((v, i) => v - gripAtGrab[i]);
    const expected = expectedFinal(PART.start, gripAtGrab, gripBeforeRelease);
    const commandedExpected = PART.start.map((v, i) => v + commanded[i]);
    const err = maxAxisError(partAfterRelease, expected);
    const errVsCommand = maxAxisError(partAfterRelease, commandedExpected);
    const travelled = Math.hypot(...partAfterRelease.map((v, i) => v - PART.start[i]));

    const result = {
      browser: { name: "chromium-headless-shell (playwright-core 1.65.0)", version: browser.version() },
      emulator: { name: "IWER (Immersive Web Emulation Runtime)", device: "Meta Quest 3", native_navigator_xr_before_install: nativeXrBeforeInstall, emulator_installed: emulatorIsInstalled },
      session,
      part: { start: [...PART.start], before_grab: partBefore, after_free_controller_move: partAfterFreeMove, while_held: partWhileHeld, after_release: partAfterRelease, after_release_and_controller_move: partAfterReleaseAndMove },
      controller: { grip_at_grab: gripAtGrab, grip_before_release: gripBeforeRelease, grip_displacement: gripDisplacement, commanded_displacement: commanded },
      assertion: { expected_final: expected, expected_final_from_commanded: commandedExpected, tolerance_m: POSITION_TOLERANCE_M, max_axis_error_m: err, max_axis_error_vs_commanded_m: errVsCommand, travelled_m: travelled },
      grab: { starts: finalState.grabStarts, ends: finalState.grabEnds },
      headless_frame_pacing: { ...pacing, note: "software-rendered headless Chromium, not a headset", emulated_nominal_frame_rate_hz: finalState.nominalFrameRate },
      requested_origins: [...new Set(requested.map((u) => new URL(u).origin))],
      requested_paths: [...new Set(requested.map((u) => new URL(u).pathname))].sort(),
      page_errors: [pageErrorBeforeSession, finalState.error].filter(Boolean),
      console_tail: logs.slice(-8),
    };
    const checks = {
      "emulator replaced the native navigator.xr": emulatorIsInstalled,
      "immersive-vr session entered": session.mode === "immersive-vr",
      "both controllers visible to @pmndrs/xr": session.controllers.join() === "left,right",
      "part unmoved before grab": maxAxisError(partBefore, PART.start) === 0,
      "part unmoved by an un-squeezed controller": maxAxisError(partAfterFreeMove, PART.start) === 0,
      "exactly one grab started and ended": finalState.grabStarts === 1 && finalState.grabEnds === 1,
      "controller displacement equals the commanded displacement": maxAxisError(gripDisplacement, commanded) < POSITION_TOLERANCE_M,
      "part moved by more than 0.3 m": travelled > 0.3,
      "part final position equals start + controller displacement": err < POSITION_TOLERANCE_M,
      "part final position equals start + commanded displacement": errVsCommand < POSITION_TOLERANCE_M,
      "part stays put after release": maxAxisError(partAfterReleaseAndMove, partAfterRelease) === 0,
      "no page errors": !pageErrorBeforeSession && !finalState.error,
      "no request left loopback": requested.every((u) => new URL(u).hostname === "127.0.0.1"),
    };
    return { result, checks, screenshots: shots };
  } finally {
    await browser?.close();
    server.close();
  }
}
