# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""A0-01b: native MuJoCo reference trajectories for the browser (WASM) comparison.

Measurement only. Writes `reference/manifest.json` and `reference/native_qpos.f64` (little-endian float64,
scenario after scenario, each (n_steps+1) rows of nq values: the state before step 0 and after every step).

    uv run spikes/mujoco-wasm/gen_reference.py            # reference/ (deterministic: same file every run)
    uv run spikes/mujoco-wasm/gen_reference.py --bench    # also native steps/s into results/native-timing.json

The model is the legacy `rocket_car` MJCF (model/rocket_car.xml, see REPORT.md for provenance). The
controls are the 7 burn windows of the legacy hero run (legacy-v0 apps/web/public/demo/roadster/traj_8000.json,
8000 N per nozzle, ramp launch). Window -> thruster decoding is copied from legacy-v0
packages/engine/src/kinetra_engine/templates/rocket_car.py (WIN_GROUP, GROUP_OF, controls()).
Extra scenarios (seed 0): the same windows with start times +-20 ms and throttles +-5 % (my own variants,
not legacy results). Two more are the nominal run with the initial height nudged by 1e-12 / 1e-9 m on the
native side only: how fast the native trajectory itself separates under a tiny perturbation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_XML = HERE / "model" / "rocket_car.xml"
LEGACY_MODEL_SHA256 = "83b4990f9e0cb742f41299886410132641f42f42ef8e1d13ea9bb49909932cd9"  # traj_8000.json model_hash
SEED = 0
DT, T_SIM = 0.004, 4.5
NSTEP = int(round(T_SIM / DT))
G0 = 9.80665
WHEEL_R = 0.32
FMAX = 8000.0
RAMP_SPEED, RAMP_ANGLE_DEG, RAMP_HEIGHT = 22.0, 25.0, 2.2
T_START_MAX, DUR_MAX = 2.5, 2.0
N_VARIANTS = 20

# legacy rocket_car.py THRUSTERS order (name, group); sites/motors are in this order in the MJCF
THRUSTER_GROUP = [
    ("nose_dn", 0), ("tail_up", 0), ("nose_up", 1), ("tail_dn", 1),
    ("belly_fl", 2), ("belly_fr", 2), ("belly_rl", 2), ("belly_rr", 2),
    ("mid_dn", 3), ("mid_up", 3),
    ("side_fl_up", 4), ("side_fr_dn", 4), ("side_rl_up", 4), ("side_rr_dn", 4),
    ("side_fl_dn", 5), ("side_fr_up", 5), ("side_rl_dn", 5), ("side_rr_up", 5),
]
WIN_GROUP = [0, 1, 2, 3, 2, 4, 5]
WIN_NAMES = ["pitch_fwd_outer", "pitch_back_outer", "lift_main", "pitch_fwd_inner", "lift_landing", "roll_pos", "roll_neg"]
# legacy hero run: traj_8000.json meta.params (nominal-assumption rollout, legacy note says success=True)
LEGACY_PARAMS = {
    "pitch_fwd_outer": (1.35485, 0.38128, 0.96476), "pitch_back_outer": (0.63971, 0.48852, 0.95354),
    "lift_main": (0.01663, 0.00472, 1.0), "pitch_fwd_inner": (0.41109, 0.02384, 0.06801),
    "lift_landing": (1.68293, 0.40668, 0.6908), "roll_pos": (0.11184, 0.30573, 0.85709),
    "roll_neg": (0.49095, 0.30144, 0.8833),
}


def decode(params: dict[str, tuple[float, float, float]]) -> list[dict]:
    """(start, duration, throttle) per window -> decoded (ts, dur, mag) exactly as legacy params_to_x + decode."""
    out = []
    for name, g in zip(WIN_NAMES, WIN_GROUP):
        s, d, m = params[name]
        x = np.clip(np.array([s / T_START_MAX, d / DUR_MAX, m]), 0.0, 1.0)
        out.append({"name": name, "group": g, "ts": float(x[0] * T_START_MAX), "dur": float(x[1] * DUR_MAX), "mag": float(x[2])})
    return out


def controls(windows: list[dict]) -> np.ndarray:
    """(NSTEP, nu) throttle per step; same rule as legacy Rig.controls (window on at t >= ts and t < ts + dur)."""
    t = np.arange(NSTEP) * DT
    thr = np.zeros((NSTEP, len(THRUSTER_GROUP)))
    for w in windows:
        on = (t >= w["ts"]) & (t < w["ts"] + w["dur"])
        for i, (_, g) in enumerate(THRUSTER_GROUP):
            if g == w["group"]:
                thr[:, i] += on * w["mag"]
    return thr


def initial_state(dz: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    a = np.deg2rad(RAMP_ANGLE_DEG)
    th0 = -a
    qpos = np.zeros(11)
    qpos[:3] = [0.0, 0.0, RAMP_HEIGHT + dz]
    qpos[3:7] = [np.cos(th0 / 2), 0.0, np.sin(th0 / 2), 0.0]
    qvel = np.zeros(10)
    qvel[:3] = [RAMP_SPEED * np.cos(a), 0.0, RAMP_SPEED * np.sin(a)]
    qvel[6:10] = RAMP_SPEED / WHEEL_R
    return qpos, qvel


def make_model() -> tuple[mujoco.MjModel, mujoco.MjData]:
    m = mujoco.MjModel.from_xml_string(MODEL_XML.read_text())
    d = mujoco.MjData(m)
    m.actuator_gear[:, 2] = FMAX
    mujoco.mj_setConst(m, d)
    return m, d


def run(ctrl: np.ndarray, qpos0: np.ndarray, qvel0: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fresh model and data; returns qpos (NSTEP+1, nq) and ncon (NSTEP+1)."""
    m, d = make_model()
    d.qpos[:] = qpos0
    d.qvel[:] = qvel0
    mujoco.mj_forward(m, d)
    q = np.empty((NSTEP + 1, m.nq))
    nc = np.empty(NSTEP + 1, dtype=np.int32)
    q[0], nc[0] = d.qpos, d.ncon
    for k in range(NSTEP):
        d.ctrl[:] = ctrl[k]
        mujoco.mj_step(m, d)
        q[k + 1], nc[k + 1] = d.qpos, d.ncon
    return q, nc


def sha256_bytes(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype="<f8").tobytes()).hexdigest()


def scenarios() -> list[dict]:
    rng = np.random.default_rng(SEED)
    sc = [{"id": "nominal", "kind": "legacy-hero-8000N", "windows": decode(LEGACY_PARAMS), "dz": 0.0}]
    for i in range(N_VARIANTS):
        p = {}
        for name in WIN_NAMES:
            s, d, m = LEGACY_PARAMS[name]
            p[name] = (max(0.0, s + rng.uniform(-0.02, 0.02)), d, min(1.0, m * rng.uniform(0.95, 1.05)))
        sc.append({"id": f"var{i + 1}", "kind": "seeded-variant", "windows": decode(p), "dz": 0.0})
    return sc


def build() -> dict:
    sc_list = scenarios()
    nominal_windows = sc_list[0]["windows"]
    for dz, name in ((1e-12, "native-perturbed-1e-12"), (1e-9, "native-perturbed-1e-9")):
        sc_list.append({"id": name, "kind": "native-only-control", "windows": nominal_windows, "dz": dz})
    blobs, entries = [], []
    for sc in sc_list:
        ctrl = controls(sc["windows"])
        q0, v0 = initial_state(sc["dz"])
        q, nc = run(ctrl, q0, v0)
        q2, nc2 = run(ctrl, q0, v0)
        assert np.array_equal(q, q2) and np.array_equal(nc, nc2), "native run is not repeatable"
        first = int(np.argmax(nc > 0)) if (nc > 0).any() else -1
        entries.append({
            "id": sc["id"], "kind": sc["kind"], "windows": sc["windows"], "qpos0": q0.tolist(), "qvel0": v0.tolist(),
            "ctrl_sha256": sha256_bytes(ctrl), "qpos_sha256": sha256_bytes(q), "first_contact_step": first,
            "contact_steps": int((nc > 0).sum()), "native_repeat_bitwise_equal": True,
        })
        blobs.append(np.ascontiguousarray(q, dtype="<f8"))
    return {
        "mujoco_native_version": mujoco.__version__, "numpy_version": np.__version__, "python": platform.python_version(),
        "platform": platform.platform(), "seed": SEED, "dt": DT, "n_steps": NSTEP, "nq": 11, "nv": 10, "nu": len(THRUSTER_GROUP),
        "fmax_N": FMAX, "model_file": "model/rocket_car.xml", "model_sha256": hashlib.sha256(MODEL_XML.read_bytes()).hexdigest(),
        "integrator": "implicitfast (from the MJCF)", "thruster_group": [g for _, g in THRUSTER_GROUP],
        "rows_per_scenario": NSTEP + 1, "scenarios": entries,
    }, np.concatenate(blobs)


def bench(repeats: int = 5) -> dict:
    sc = scenarios()[0]
    ctrl = controls(sc["windows"])
    q0, v0 = initial_state()
    wall, cpu = [], []
    for _ in range(repeats):
        m, d = make_model()
        d.qpos[:], d.qvel[:] = q0, v0
        mujoco.mj_forward(m, d)
        w0, c0 = time.perf_counter(), time.process_time()
        for k in range(NSTEP):
            d.ctrl[:] = ctrl[k]
            mujoco.mj_step(m, d)
        wall.append(time.perf_counter() - w0)
        cpu.append(time.process_time() - c0)
    sim_s = NSTEP * DT

    def stat(x):
        return {"median": float(np.median(x)), "min": float(min(x)), "max": float(max(x))}

    load = os.getloadavg()
    return {
        "what": "native mujoco (PyPI wheel), nominal scenario, ctrl set + mj_step per step, no recording", "repeats": repeats,
        "steps": NSTEP, "sim_seconds": sim_s, "wall_s": stat(wall), "cpu_s": stat(cpu),
        "steps_per_s_wall_median": NSTEP / float(np.median(wall)), "rtf_wall_median": sim_s / float(np.median(wall)),
        "rtf_cpu_median": sim_s / float(np.median(cpu)), "mujoco": mujoco.__version__, "python": platform.python_version(),
        "load_avg": load, "swap": subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip(),
        "cpu": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip(),
        "platform": platform.platform(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", action="store_true", help="also time the native step loop into results/native-timing.json")
    args = ap.parse_args(argv)
    if hashlib.sha256(MODEL_XML.read_bytes()).hexdigest() != LEGACY_MODEL_SHA256:
        print("model/rocket_car.xml differs from the legacy-v0 model_hash", file=sys.stderr)
        return 1
    manifest, blob = build()
    (HERE / "reference").mkdir(exist_ok=True)
    (HERE / "reference" / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (HERE / "reference" / "native_qpos.f64").write_bytes(blob.tobytes())
    for e in manifest["scenarios"]:
        print(f"{e['id']:26s} first_contact_step={e['first_contact_step']:5d} contact_steps={e['contact_steps']:5d} qpos_sha256={e['qpos_sha256'][:16]}")
    if args.bench:
        (HERE / "results").mkdir(exist_ok=True)
        b = bench()
        (HERE / "results" / "native-timing.json").write_text(json.dumps(b, indent=1) + "\n")
        print(f"native: {b['steps_per_s_wall_median']:.0f} steps/s wall (rtf {b['rtf_wall_median']:.1f}), rtf_cpu {b['rtf_cpu_median']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
