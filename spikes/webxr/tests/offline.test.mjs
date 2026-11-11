// Offline tests (no browser, no emulator): run in CI via scripts/ci/run_spike_tests.py (`pnpm test`).
// They cover the parts of the spike that do not need Chromium: the grab logic with the real @pmndrs/handle and
// @pmndrs/pointer-events (a fake grip object instead of an XR space), the expected-position arithmetic, the server,
// the guard rule, and that the page bundle builds.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Object3D, PerspectiveCamera, Scene } from "three";
import { createGrabPointer, createRayPointer } from "@pmndrs/pointer-events";
import { PART, createPart, makeGrabbable } from "../src/scene.js";
import { POSITION_TOLERANCE_M, expectedFinal, maxAxisError, summarizeFrames } from "../src/expected.js";
import { guardProblem } from "../guard.mjs";
import { resolveUrl, startServer } from "../serve.mjs";
import { build } from "../build.mjs";
import { MOVE_LEGS } from "../driver.mjs";

/** A scene with the part, a fake grip object and a grab pointer on it; `step(pos)` moves the grip and runs one frame. */
function rig() {
  const scene = new Scene();
  const camera = new PerspectiveCamera();
  const part = createPart();
  scene.add(part);
  const changes = [];
  const { handle } = makeGrabbable(part, (s) => changes.push({ first: s.first, last: s.last }));
  const grip = new Object3D();
  scene.add(grip);
  const pointer = createGrabPointer(() => camera, { current: grip }, {});
  let t = 1;
  const ev = () => ({ timeStamp: t++, button: 0 });
  const step = (pos) => {
    if (pos) grip.position.set(...pos);
    scene.updateMatrixWorld(true);
    pointer.move(scene, ev());
    handle.update(t++);
  };
  return { scene, camera, part, handle, grip, pointer, ev, step, changes };
}

test("grab, move along MOVE_LEGS, release: part ends at start + controller displacement", () => {
  const r = rig();
  r.step(PART.start);
  r.pointer.down(r.ev());
  assert.ok(r.handle.getState(), "grab started");
  let pos = [...PART.start];
  for (const leg of MOVE_LEGS) {
    pos = pos.map((v, i) => v + leg[i]);
    r.step(pos);
  }
  const held = r.part.position.toArray();
  r.pointer.up(r.ev());
  assert.equal(r.handle.getState(), undefined, "grab ended");
  const expected = expectedFinal(PART.start, PART.start, pos);
  assert.ok(maxAxisError(r.part.position.toArray(), expected) < POSITION_TOLERANCE_M);
  assert.deepEqual(r.part.position.toArray(), held, "release does not jump the part");
  assert.equal(r.changes.filter((c) => c.first).length, 1);
  assert.equal(r.changes.filter((c) => c.last).length, 1);
  assert.ok(Math.hypot(...r.part.position.toArray().map((v, i) => v - PART.start[i])) > 0.3, "moved far enough to be a real move");
});

test("a grip that moves without a squeeze leaves the part where it was", () => {
  const r = rig();
  r.step(PART.start);
  r.step(PART.start.map((v, i) => v + [0.05, 0, 0][i]));
  r.step([1, 1, 1]);
  assert.deepEqual(r.part.position.toArray(), [...PART.start]);
  assert.equal(r.handle.getState(), undefined);
});

test("a grip far from the part cannot grab it", () => {
  const r = rig();
  r.step([2, 1.2, -0.4]); // 1.75 m away; grab sphere radius is 0.07 m
  r.pointer.down(r.ev());
  assert.equal(r.handle.getState(), undefined);
  r.step([2.3, 1.2, -0.4]);
  assert.deepEqual(r.part.position.toArray(), [...PART.start]);
});

test("rotation of the grip does not rotate or scale the part (translate only)", () => {
  const r = rig();
  r.step(PART.start);
  r.pointer.down(r.ev());
  r.grip.rotation.set(0.6, 0.9, -0.4);
  r.step([PART.start[0] + 0.1, PART.start[1], PART.start[2]]);
  r.pointer.up(r.ev());
  assert.deepEqual(r.part.quaternion.toArray(), [0, 0, 0, 1]);
  assert.deepEqual(r.part.scale.toArray(), [1, 1, 1]);
  assert.ok(Math.abs(r.part.position.x - (PART.start[0] + 0.1)) < POSITION_TOLERANCE_M);
});

test("the part only accepts grab pointers: a ray pointer cannot grab it", () => {
  const r = rig();
  assert.deepEqual(r.part.pointerEventsType, { allow: "grab" });
  const rayOrigin = new Object3D();
  r.scene.add(rayOrigin);
  rayOrigin.position.set(PART.start[0], PART.start[1], PART.start[2] + 1); // looking down -z at the part
  const ray = createRayPointer(() => r.camera, { current: rayOrigin }, {});
  let t = 1000;
  const ev = () => ({ timeStamp: t++, button: 0 });
  r.scene.updateMatrixWorld(true);
  ray.move(r.scene, ev());
  ray.down(ev());
  assert.equal(r.handle.getState(), undefined, "a ray pointer pressed on the part did not start a grab");
});

test("the second grab starts from the part's new position", () => {
  const r = rig();
  r.step(PART.start);
  r.pointer.down(r.ev());
  r.step(PART.start.map((v, i) => v + [0.2, 0, 0][i]));
  r.pointer.up(r.ev());
  const mid = r.part.position.toArray();
  r.step(mid);
  r.pointer.down(r.ev());
  r.step(mid.map((v, i) => v + [0, 0.1, 0][i]));
  r.pointer.up(r.ev());
  assert.ok(maxAxisError(r.part.position.toArray(), [PART.start[0] + 0.2, PART.start[1] + 0.1, PART.start[2]]) < POSITION_TOLERANCE_M);
});

test("expectedFinal, maxAxisError", () => {
  assert.deepEqual(expectedFinal([1, 2, 3], [0, 0, 0], [0.5, -1, 2]), [1.5, 1, 5]);
  assert.equal(maxAxisError([1, 2, 3], [1, 2.5, 2.9]), 0.5);
  assert.throws(() => maxAxisError([1, 2], [1, 2, 3]), /3-vectors/);
});

test("summarizeFrames: 90 Hz steady and one long frame", () => {
  const t = Array.from({ length: 101 }, (_, i) => i * (1000 / 90));
  const s = summarizeFrames(t);
  assert.equal(s.frames, 101);
  assert.ok(Math.abs(s.fps - 90) < 1e-9);
  assert.ok(Math.abs(s.p50_interval_ms - 1000 / 90) < 1e-9);
  const slow = [...t.slice(0, 50), ...t.slice(50).map((x) => x + 100)];
  assert.ok(Math.abs(summarizeFrames(slow).max_interval_ms - (1000 / 90 + 100)) < 1e-9);
  assert.throws(() => summarizeFrames([1]), /two frames/);
});

test("MOVE_LEGS is a real path: net displacement above the 0.3 m the assertion requires", () => {
  const net = MOVE_LEGS.reduce((a, l) => a.map((v, i) => v + l[i]), [0, 0, 0]);
  assert.ok(Math.hypot(...net) > 0.3, `net ${net}`);
});

test("guard: refuses outside the resource guard, accepts CI=true and KINETRA_GUARD_PASSED=1", () => {
  assert.match(guardProblem({}), /resource guard/);
  assert.match(guardProblem({ CI: "false", KINETRA_GUARD_PASSED: "0" }), /resource guard/);
  assert.equal(guardProblem({ CI: "true" }), null);
  assert.equal(guardProblem({ KINETRA_GUARD_PASSED: "1" }), null);
});

test("run-xr.mjs exits 3 without starting a browser when run outside the guard", async () => {
  const { spawnSync } = await import("node:child_process");
  const env = { ...process.env };
  delete env.CI;
  delete env.KINETRA_GUARD_PASSED;
  const r = spawnSync(process.execPath, [new URL("../run-xr.mjs", import.meta.url).pathname], { env, encoding: "utf8", timeout: 30_000 });
  assert.equal(r.status, 3);
  assert.match(r.stderr, /resource guard/);
});

test("resolveUrl stays inside its root", () => {
  assert.equal(resolveUrl("/r", "/"), "/r/index.html");
  assert.equal(resolveUrl("/r", "/app.js"), "/r/app.js");
  assert.equal(resolveUrl("/r", "/../etc/passwd"), null);
  assert.equal(resolveUrl("/r", "/a/../../x"), null);
});

test("server: dist and /profiles from separate roots, loopback only, 404 elsewhere and on escapes", async () => {
  const root = mkdtempSync(join(tmpdir(), "xr-serve-"));
  try {
    const dist = join(root, "dist");
    const profiles = join(root, "profiles");
    mkdirSync(dist);
    mkdirSync(profiles);
    writeFileSync(join(dist, "index.html"), "<html></html>");
    writeFileSync(join(dist, "app.js"), "1");
    writeFileSync(join(profiles, "profilesList.json"), "{}");
    writeFileSync(join(root, "secret.txt"), "no");
    const server = await startServer({ dist, profiles });
    try {
      assert.equal(server.address().address, "127.0.0.1");
      const base = `http://127.0.0.1:${server.address().port}`;
      assert.equal((await fetch(`${base}/`)).status, 200);
      assert.equal((await fetch(`${base}/app.js`)).headers.get("content-type"), "text/javascript; charset=utf-8");
      const p = await fetch(`${base}/profiles/profilesList.json`);
      assert.equal(p.status, 200);
      assert.equal(p.headers.get("content-type"), "application/json");
      assert.equal((await fetch(`${base}/nope`)).status, 404);
      assert.equal((await fetch(`${base}/profiles/../secret.txt`)).status, 404);
      assert.equal((await fetch(`${base}/%2e%2e/secret.txt`)).status, 404);
    } finally {
      server.close();
    }
  } finally {
    rmSync(root, { recursive: true });
  }
});

test("fixtures: the controller profile the emulator reports is present and matches the layout @pmndrs/xr reads", () => {
  const dir = new URL("../fixtures/profiles/", import.meta.url);
  const list = JSON.parse(readFileSync(new URL("profilesList.json", dir), "utf8"));
  assert.equal(list["meta-quest-touch-plus"].path, "meta-quest-touch-plus/profile.json");
  const profile = JSON.parse(readFileSync(new URL("meta-quest-touch-plus/profile.json", dir), "utf8"));
  assert.equal(profile.profileId, "meta-quest-touch-plus");
  for (const hand of ["left", "right"]) {
    const layout = profile.layouts[hand];
    assert.equal(layout.selectComponentId, "xr-standard-trigger");
    assert.equal(layout.components["xr-standard-squeeze"].gamepadIndices.button, 1, "squeeze is gamepad button 1 (what IWER's `squeeze` writes)");
  }
});

test("the page bundle builds: app.js + index.html + a lazy emulator chunk", async () => {
  const outdir = mkdtempSync(join(tmpdir(), "xr-build-"));
  try {
    const files = await build({ outdir });
    const names = files.map((f) => f.file);
    assert.ok(names.includes("index.html") && names.includes("app.js"), names.join());
    const app = readFileSync(join(outdir, "app.js"), "utf8");
    // @pmndrs/xr loads its emulator lazily, behind `emulate`; with emulate:false that chunk is never requested.
    const chunks = readdirSync(outdir).filter((f) => f.endsWith(".js") && f !== "app.js");
    assert.ok(chunks.length >= 1, "code splitting produced the lazy emulator chunk");
    assert.ok(/emulate:!1|emulate:false/.test(app), "page passes emulate:false");
  } finally {
    rmSync(outdir, { recursive: true });
  }
});
