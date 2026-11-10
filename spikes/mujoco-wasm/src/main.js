import { loadEngine, buildControls, makeSim, runRecorded, runBare, sha256Hex, NU } from "/src/sim.js";
import { compareTrajectories, summarize } from "/src/compare.js";
import { drawCar } from "/src/draw.js";
import { planFrame } from "/src/accumulator.js";
import { sha256Bytes, checkModelHash, checkControlHash } from "/src/integrity.js";

const params = new URLSearchParams(location.search);
const BARE_REPEATS = Number(params.get("bare") ?? 7);
const FRAME_LOOPS = Number(params.get("loops") ?? 3); // full 4.5 s scenarios played back-to-back in the rAF loop
const MAX_CATCHUP = 25; // steps per frame before the loop gives up catching up (100 ms of sim)
const $ = (id) => document.getElementById(id);
const status = (s) => { $("status").textContent = s; };

async function getJSON(u) { return (await fetch(u)).json(); }
async function getF64(u) { return new Float64Array(await (await fetch(u)).arrayBuffer()); }

function f64At(blob, i, rows, nq) { return blob.subarray(i * rows * nq, (i + 1) * rows * nq); }

async function parity(mj, xml, manifest, blob) {
  const { n_steps: n, nq } = manifest, rows = n + 1;
  const out = [];
  const byId = Object.fromEntries(manifest.scenarios.map((s, i) => [s.id, i]));
  for (const [i, sc] of manifest.scenarios.entries()) {
    const native = f64At(blob, i, rows, nq);
    if (sc.kind === "native-only-control") {
      // native vs native: how far the native trajectory itself moves for a 1e-12 / 1e-9 m initial-height nudge
      const nominal = f64At(blob, byId.nominal, rows, nq);
      out.push({ id: sc.id, kind: sc.kind, ref: "native nominal", first_contact_step: sc.first_contact_step, ...compareTrajectories(native, nominal, rows, nq, sc.first_contact_step) });
      continue;
    }
    const ctrl = buildControls(manifest, sc.windows);
    const ctrlHash = await sha256Hex(ctrl); // float64 bytes, nsteps x nu row-major: the same layout gen_reference.py hashes
    checkControlHash(sc.id, ctrlHash, sc.ctrl_sha256); // throws: no result is produced from different controls
    const runs = [];
    for (let rep = 0; rep < 2; rep++) {
      const sim = makeSim(mj, xml, manifest, sc);
      runs.push(runRecorded(mj, sim, ctrl, n, nq));
      sim.dispose();
    }
    const cmp = compareTrajectories(runs[0].qpos, native, rows, nq, sc.first_contact_step);
    const wasmFirst = runs[0].ncon.findIndex((c) => c > 0);
    out.push({
      id: sc.id, kind: sc.kind, ref: "native", ctrl_sha256_wasm: ctrlHash, ctrl_sha256_native: sc.ctrl_sha256, ctrl_equal: ctrlHash === sc.ctrl_sha256,
      first_contact_step_native: sc.first_contact_step, first_contact_step_wasm: wasmFirst,
      wasm_repeat_bitwise_equal: compareTrajectories(runs[0].qpos, runs[1].qpos, rows, nq, -1).bitwise_identical,
      wasm_qpos_sha256: await sha256Hex(runs[0].qpos), native_qpos_sha256: sc.qpos_sha256, ...cmp,
    });
  }
  return out;
}

async function bareThroughput(mj, xml, manifest) {
  const sc = manifest.scenarios[0], n = manifest.n_steps;
  const ctrl = buildControls(manifest, sc.windows);
  const reps = [];
  for (let r = 0; r < BARE_REPEATS; r++) {
    const sim = makeSim(mj, xml, manifest, sc);
    const t0 = performance.now();
    runBare(mj, sim, ctrl, n);
    const ms = performance.now() - t0;
    sim.dispose();
    reps.push(ms);
    await new Promise((r2) => setTimeout(r2, 0));
  }
  const s = summarize(reps);
  const sim_s = n * manifest.dt;
  return { what: "mj_step loop only (ctrl copy + mj_step), nominal scenario, fresh model/data per repeat, performance.now", repeats: BARE_REPEATS, steps: n, sim_seconds: sim_s,
    wall_ms: s, steps_per_s_median: n / (s.median / 1000), rtf_median: sim_s / (s.median / 1000), reps_ms: reps };
}

function frameLoop(mj, xml, manifest, cv) {
  const sc = manifest.scenarios[0], n = manifest.n_steps, dt = manifest.dt, nq = manifest.nq;
  const ctrl = buildControls(manifest, sc.windows);
  const ctx = cv.getContext("2d");
  const sim = makeSim(mj, xml, manifest, sc);
  const frameDt = [], work = [], stepsPer = [];
  let loops = 0, k = 0, acc = 0, prev = null, capped = 0, droppedS = 0, simSteps = 0, wallStart = null;
  const cr = sim.data.ctrl, qp = sim.data.qpos;
  return new Promise((resolve) => {
    function frame(ts) {
      if (prev === null) { prev = ts; wallStart = ts; requestAnimationFrame(frame); return; }
      const dtf = ts - prev; prev = ts; frameDt.push(dtf);
      const plan = planFrame(acc, dtf, dt, MAX_CATCHUP);
      acc = plan.acc;
      if (plan.capped) { capped++; droppedS += plan.droppedS; }
      const w0 = performance.now();
      const steps = plan.steps;
      for (let s = 0; s < steps; s++) {
        for (let i = 0; i < NU; i++) cr[i] = ctrl[k * NU + i];
        mj.mj_step(sim.model, sim.data);
        k++; simSteps++;
        if (k === n) { // scenario over: restart from the initial state, count a loop
          loops++; k = 0;
          mj.mj_resetData(sim.model, sim.data);
          sim.data.qpos.set(sc.qpos0); sim.data.qvel.set(sc.qvel0); mj.mj_forward(sim.model, sim.data);
        }
      }
      drawCar(ctx, cv.width, cv.height, qp, cr);
      work.push(performance.now() - w0); stepsPer.push(steps);
      if (loops >= FRAME_LOOPS) {
        const wall = ts - wallStart;
        sim.dispose();
        resolve({
          what: "requestAnimationFrame loop: accumulate real time, fixed 4 ms mj_step per accumulated 4 ms, canvas-2D draw each frame, scenario replayed back-to-back",
          loops: FRAME_LOOPS, frames: frameDt.length, wall_ms: wall, sim_steps: simSteps, sim_seconds: simSteps * dt,
          sim_over_wall: (simSteps * dt) / (wall / 1000), mean_fps: frameDt.length / (wall / 1000),
          frame_interval_ms: summarize(frameDt), work_ms_per_frame: summarize(work), steps_per_frame: summarize(stepsPer),
          frames_over_20ms: frameDt.filter((x) => x > 20).length, frames_over_33ms: frameDt.filter((x) => x > 33.4).length,
          catchup_capped_frames: capped, catchup_dropped_sim_s: droppedS, catchup_max_steps_per_frame: MAX_CATCHUP,
        });
        return;
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
}

/** Uncapped: the same per-frame work as the rAF loop (4 steps + canvas draw) back-to-back with no vsync wait. Max drawable frames/s. */
function uncappedLoop(mj, xml, manifest, cv) {
  const sc = manifest.scenarios[0], n = manifest.n_steps, nq = manifest.nq;
  const ctrl = buildControls(manifest, sc.windows);
  const ctx = cv.getContext("2d");
  const frameMs = [];
  const sim = makeSim(mj, xml, manifest, sc);
  const cr = sim.data.ctrl, qp = sim.data.qpos;
  const perFrame = 4; // 4 x 4 ms = one 60 Hz frame of sim time (16 ms)
  let frames = 0;
  const t0 = performance.now();
  for (let rep = 0; rep < FRAME_LOOPS; rep++) {
    mj.mj_resetData(sim.model, sim.data); sim.data.qpos.set(sc.qpos0); sim.data.qvel.set(sc.qvel0); mj.mj_forward(sim.model, sim.data);
    for (let k = 0; k + perFrame <= n; k += perFrame) {
      const f0 = performance.now();
      for (let j = 0; j < perFrame; j++) {
        for (let i = 0; i < NU; i++) cr[i] = ctrl[(k + j) * NU + i];
        mj.mj_step(sim.model, sim.data);
      }
      drawCar(ctx, cv.width, cv.height, qp, cr);
      frameMs.push(performance.now() - f0); frames++;
    }
  }
  const wall = performance.now() - t0;
  sim.dispose();
  return { what: "uncapped: 4 mj_step + canvas-2D draw per frame, back-to-back, no vsync wait (max frames/s the main thread can produce)", frames, wall_ms: wall, frames_per_s: frames / (wall / 1000), frame_ms: summarize(frameMs) };
}

function fmt(x) { return typeof x === "number" ? (Math.abs(x) >= 1e-3 && Math.abs(x) < 1e6 ? x.toPrecision(5) : x.toExponential(3)) : String(x); }

function render(res) {
  const rows = res.parity.map((p) => `<tr><td>${p.id}</td><td>${p.kind}</td><td>${fmt(p.max_pos_err_m)}</td><td>${fmt(p.max_ang_err_rad)}</td><td>${fmt(p.pre_touchdown.max_pos_err_m)}</td><td>${fmt(p.pre_touchdown.max_ang_err_rad)}</td><td>${fmt(p.final.pos_m)}</td><td>${p.bitwise_identical}</td><td>${p.bitwise_equal_prefix_rows}</td></tr>`).join("");
  $("out").innerHTML = `
  <h2>Engine</h2><p>${res.engine.version} (loaded in ${res.engine.load_ms.toFixed(0)} ms, single-thread build) in ${res.env.userAgent}</p>
  <h2>Trajectory difference vs native (max over 1126 rows; m, rad)</h2>
  <table><tr><th>scenario</th><th>kind</th><th>max pos</th><th>max ang</th><th>pre-contact pos</th><th>pre-contact ang</th><th>final pos</th><th>bitwise</th><th>bitwise rows</th></tr>${rows}</table>
  <h2>mj_step throughput</h2><p>${fmt(res.bare.steps_per_s_median)} steps/s median, real-time factor ${fmt(res.bare.rtf_median)} (${res.bare.repeats} repeats)</p>
  <h2>Uncapped frame loop</h2><p>${fmt(res.uncapped.frames_per_s)} frames/s (4 steps + draw each); frame p50/p99 ${fmt(res.uncapped.frame_ms.median)} / ${fmt(res.uncapped.frame_ms.p99)} ms</p>
  <h2>requestAnimationFrame loop</h2><p>${fmt(res.frames.mean_fps)} fps mean; frame interval p50/p95/p99 ${fmt(res.frames.frame_interval_ms.median)} / ${fmt(res.frames.frame_interval_ms.p95)} / ${fmt(res.frames.frame_interval_ms.p99)} ms; work per frame p50/p99 ${fmt(res.frames.work_ms_per_frame.median)} / ${fmt(res.frames.work_ms_per_frame.p99)} ms; sim/wall ${fmt(res.frames.sim_over_wall)}; catch-up capped frames ${res.frames.catchup_capped_frames}, dropped sim time ${fmt(res.frames.catchup_dropped_sim_s)} s</p>`;
}

async function main() {
  const cv = $("cv");
  status("loading engine");
  const engine = await loadEngine();
  const [manifest, xmlBytes, blob] = await Promise.all([getJSON("/reference/manifest.json"), fetch("/model/rocket_car.xml").then((r) => r.arrayBuffer()), getF64("/reference/native_qpos.f64")]);
  const modelSha256 = await sha256Bytes(xmlBytes);
  checkModelHash(modelSha256, manifest); // throws before anything is measured
  const xml = new TextDecoder().decode(xmlBytes);
  const expected = manifest.scenarios.length * (manifest.n_steps + 1) * manifest.nq;
  if (blob.length !== expected) throw new Error(`reference blob has ${blob.length} doubles, expected ${expected}`);
  status("parity");
  const par = await parity(engine.mj, xml, manifest, blob);
  status("mj_step throughput");
  const bare = await bareThroughput(engine.mj, xml, manifest);
  status("frame loop");
  const frames = await frameLoop(engine.mj, xml, manifest, cv);
  status("uncapped loop");
  const uncapped = uncappedLoop(engine.mj, xml, manifest, cv);
  const res = {
    engine: { version: engine.version, load_ms: engine.load_ms, package: "@mujoco/mujoco 4.0.0" },
    env: { userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, crossOriginIsolated, devicePixelRatio, visibility: document.visibilityState },
    manifest_summary: { native_version: manifest.mujoco_native_version, dt: manifest.dt, n_steps: manifest.n_steps, model_sha256: manifest.model_sha256, served_model_sha256: modelSha256, legacy_model_hash: manifest.legacy_model_hash, seed: manifest.seed },
    integrity: { model_hash_ok: true, control_hash_ok_scenarios: par.filter((p) => p.ctrl_equal).length },
    parity: par, bare, frames, uncapped,
  };
  render(res);
  window.__A0_01B_RESULT = res;
  status("done");
}

$("run").addEventListener("click", () => main().catch(fail));
function fail(e) { status("error: " + e.message); window.__A0_01B_ERROR = String(e.stack ?? e); }
if (!params.has("manual")) main().catch(fail);
