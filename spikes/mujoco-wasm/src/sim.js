// MuJoCo WASM (@mujoco/mujoco 4.0.0, official google-deepmind/mujoco wasm/) rocket_car runner for A0-01b.
// Controls and initial state are rebuilt from the scenario windows in reference/manifest.json with the same
// rule as gen_reference.py; ctrl_sha256 in the manifest proves the byte-identical control array.
import loadMujoco from "/vendor/mujoco/mujoco.js";

export const NU = 18;

export async function loadEngine() {
  const t0 = performance.now();
  const mj = await loadMujoco();
  return { mj, load_ms: performance.now() - t0, version: mj.mj_versionString() };
}

export function buildControls(manifest, windows) {
  const { n_steps: n, dt, thruster_group: group } = manifest;
  const ctrl = new Float64Array(n * NU);
  for (const w of windows) {
    for (let k = 0; k < n; k++) {
      const t = k * dt;
      if (t >= w.ts && t < w.ts + w.dur) {
        for (let i = 0; i < NU; i++) if (group[i] === w.group) ctrl[k * NU + i] += w.mag;
      }
    }
  }
  return ctrl;
}

export function makeSim(mj, xml, manifest, scenario) {
  const model = mj.MjModel.from_xml_string(xml);
  const data = new mj.MjData(model);
  const gear = model.actuator_gear; // flat nu x 6 view into the wasm heap
  for (let i = 0; i < NU; i++) gear[i * 6 + 2] = manifest.fmax_N;
  mj.mj_setConst(model, data);
  data.qpos.set(scenario.qpos0);
  data.qvel.set(scenario.qvel0);
  mj.mj_forward(model, data);
  return { model, data, dispose() { data.delete(); model.delete(); } };
}

/** Full fixed-step run recording qpos before step 0 and after every step. Returns { qpos, ncon }. */
export function runRecorded(mj, sim, ctrl, nSteps, nq) {
  const q = new Float64Array((nSteps + 1) * nq);
  const ncon = new Int32Array(nSteps + 1);
  const { model, data } = sim;
  const qp = data.qpos, cr = data.ctrl; // live views
  q.set(qp, 0); ncon[0] = data.ncon;
  for (let k = 0; k < nSteps; k++) {
    for (let i = 0; i < NU; i++) cr[i] = ctrl[k * NU + i];
    mj.mj_step(model, data);
    q.set(qp, (k + 1) * nq); ncon[k + 1] = data.ncon;
  }
  return { qpos: q, ncon };
}

/** Same loop without recording: pure stepping cost (ctrl copy + mj_step). */
export function runBare(mj, sim, ctrl, nSteps) {
  const { model, data } = sim;
  const cr = data.ctrl;
  for (let k = 0; k < nSteps; k++) {
    for (let i = 0; i < NU; i++) cr[i] = ctrl[k * NU + i];
    mj.mj_step(model, data);
  }
}

export async function sha256Hex(f64) {
  const d = await crypto.subtle.digest("SHA-256", f64.buffer.slice(f64.byteOffset, f64.byteOffset + f64.byteLength));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
