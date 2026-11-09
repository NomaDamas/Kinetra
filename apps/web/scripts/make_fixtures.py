#!/usr/bin/env python
"""Generate DEV-ONLY fixture bundles for the web app from spike outputs.

Usage (repo root):  packages/engine/.venv/bin/python apps/web/scripts/make_fixtures.py
Writes apps/web/fixtures/demo/** (served at /fixtures/demo by the vite dev server, open the app with ?fixtures=1).

IMPORTANT: fixtures are NOT real engine bundles. Trajectories come from spike runs; variants whose trajectory is
not available reuse a spike trajectory and say so in the headline. Real bundles are written by
packages/engine/scripts/build_*_bundle.py into apps/web/public/demo/.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "apps/web/fixtures/demo"
SP = ROOT / "spikes"

try:
    from physlab_core.schemas import SpecSheet, Trajectory, Verdict
except Exception:  # pragma: no cover
    SpecSheet = Trajectory = Verdict = None


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return [w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2]


def qrot(q, v):
    w, x, y, z = q
    r = np.array([[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
                  [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
                  [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]])
    return r @ np.asarray(v, float)


def qinv(q):
    return [q[0], -q[1], -q[2], -q[3]]


def r5(x):
    return [round(float(v), 4) for v in x]


# ------------------------------------------------------------------ rocket car trajectory
def rocket_traj(src: dict, note: str) -> dict:
    body = src["body"]
    ch = body["chassis_half"]
    zoff = body["chassis_z_offset"]
    wr, wh = body["wheel_radius"], body["wheel_half_width"]
    thrusters = src["thrusters"]
    s = np.sqrt(0.5)
    bodies = [{"name": "chassis", "parent": None, "geoms": [
        {"type": "box", "size": ch, "pos": [0, 0, zoff], "quat": [1, 0, 0, 0], "rgba": [0.85, 0.15, 0.12, 1], "mesh": None}]}]
    for i in range(4):
        bodies.append({"name": f"wheel_{i}", "parent": "chassis", "geoms": [
            {"type": "cylinder", "size": [wr, wh], "pos": [0, 0, 0], "quat": [s, s, 0, 0], "rgba": [0.1, 0.1, 0.1, 1], "mesh": None}]})
    for t in thrusters:
        bodies.append({"name": f"thr_{t['name']}", "parent": "chassis", "geoms": []})
    pos, quat = [], []
    series = {t["name"]: [] for t in thrusters}
    pitch = []
    frames = src["frames"][::2]
    for f in frames:
        p = np.array(f["p"]); q = f["q"]
        fp, fq = [r5(p)], [r5(q)]
        for i, wl in enumerate(body["wheels_local"]):
            fp.append(r5(p + qrot(q, wl)))
            fq.append(r5(qmul(q, [math.cos(f["wheel_spin"][i] / 2), 0, math.sin(f["wheel_spin"][i] / 2), 0])))
        for t, thr in zip(thrusters, f["thr"]):
            fp.append(r5(p + qrot(q, t["pos_local"])))
            # local +Z must equal the force direction on the vehicle
            fd = t["force_dir_local"]
            fq.append(r5(qmul(q, [0, 1, 0, 0]) if fd[2] < 0 else q))
            series[t["name"]].append(round(float(thr) * t["fmax_N"], 1))
        pos.append(fp); quat.append(fq)
        pitch.append(round(math.degrees(2 * math.atan2(q[2], q[0])), 2))
    ser = [{"name": f"thrust_{k}", "unit": "N", "values": v} for k, v in series.items()]
    ev = [{"t": src["events"]["touchdown_t"], "kind": "landing", "body": "chassis", "other": None, "pos": None,
           "force": None, "magnitude": src["events"]["vz_touchdown"], "note": "touchdown (magnitude = vz m/s)"}]
    return {"schema_version": "0.1.0", "model_id": "rocket_car_v1", "model_hash": "fixture", "dt": round(src["dt"] * 2, 5),
            "bodies": bodies, "pos": pos, "quat": quat, "events": ev, "series": ser,
            "meta": {"seed": 0, "mujoco_version": "4.0.0", "template_id": "rocket_car", "params": {}, "note": note}}


# ------------------------------------------------------------------ humanoid trajectory (capsule skeleton)
def humanoid_traj(src: dict, note: str) -> dict:
    names = src["body_names"]
    f0 = src["frames"][0]
    # parent by nearest-in-index heuristics is unreliable: use name structure
    parent = {}
    for n in names[1:]:
        parent[n] = None
    chains = {
        "pelvis": None, "left_hip_pitch_link": "pelvis", "left_hip_roll_link": "left_hip_pitch_link",
        "left_hip_yaw_link": "left_hip_roll_link", "left_knee_link": "left_hip_yaw_link",
        "left_ankle_pitch_link": "left_knee_link", "left_ankle_roll_link": "left_ankle_pitch_link",
        "right_hip_pitch_link": "pelvis", "right_hip_roll_link": "right_hip_pitch_link",
        "right_hip_yaw_link": "right_hip_roll_link", "right_knee_link": "right_hip_yaw_link",
        "right_ankle_pitch_link": "right_knee_link", "right_ankle_roll_link": "right_ankle_pitch_link",
        "waist_yaw_link": "pelvis", "waist_roll_link": "waist_yaw_link", "torso_link": "waist_roll_link",
    }
    for side in ("left", "right"):
        chain = ["torso_link", f"{side}_shoulder_pitch_link", f"{side}_shoulder_roll_link", f"{side}_shoulder_yaw_link",
                 f"{side}_elbow_link", f"{side}_wrist_roll_link", f"{side}_wrist_pitch_link", f"{side}_wrist_yaw_link"]
        for a, b in zip(chain, chain[1:]):
            chains[b] = a
    idx = {n: i for i, n in enumerate(names)}
    kept = [n for n in names if n != "world"]
    bodies = []
    for n in kept:
        geoms = []
        kids = [c for c in kept if chains.get(c) == n]
        i = idx[n]
        q0 = f0["quat"][i]
        for k in kids:
            d = np.array(f0["pos"][idx[k]]) - np.array(f0["pos"][i])
            L = float(np.linalg.norm(d))
            if L < 0.01:
                continue
            dl = qrot(qinv(q0), d)
            # capsule axis (z) -> dl
            z = np.array([0, 0, 1.0]); u = dl / np.linalg.norm(dl)
            ax = np.cross(z, u); s = np.linalg.norm(ax); c = float(z @ u)
            if s < 1e-9:
                gq = [1, 0, 0, 0] if c > 0 else [0, 1, 0, 0]
            else:
                ang = math.atan2(s, c); ax /= s
                gq = [math.cos(ang / 2), *(ax * math.sin(ang / 2))]
            r = 0.045 if "knee" in k or "hip" in n else 0.035
            geoms.append({"type": "capsule", "size": [r, L / 2], "pos": r5(dl / 2), "quat": r5(gq),
                          "rgba": [0.78, 0.8, 0.85, 1], "mesh": None})
        if n == "torso_link":
            geoms.append({"type": "box", "size": [0.09, 0.14, 0.2], "pos": [0, 0, 0.18], "quat": [1, 0, 0, 0],
                          "rgba": [0.3, 0.35, 0.42, 1], "mesh": None})
        if n.endswith("ankle_roll_link"):
            geoms.append({"type": "box", "size": [0.1, 0.04, 0.012], "pos": [0.04, 0, -0.03], "quat": [1, 0, 0, 0],
                          "rgba": [0.12, 0.12, 0.14, 1], "mesh": None})
        bodies.append({"name": n, "parent": chains.get(n), "geoms": geoms})
    frames = src["frames"][::2]
    pos = [[r5(f["pos"][idx[n]]) for n in kept] for f in frames]
    quat = [[r5(f["quat"][idx[n]]) for n in kept] for f in frames]
    m = src["metrics"]
    ev = []
    if m.get("t_liftoff") is not None:
        ev.append({"t": round(m["t_liftoff"], 3), "kind": "custom", "body": "pelvis", "other": None, "pos": None,
                   "force": None, "magnitude": None, "note": "liftoff"})
    return {"schema_version": "0.1.0", "model_id": "unitree_g1_capsule_fixture", "model_hash": "fixture",
            "dt": round(src["dt"] * 2, 5), "bodies": bodies, "pos": pos, "quat": quat, "events": ev, "series": [],
            "meta": {"seed": 1, "mujoco_version": "4.0.0", "template_id": "humanoid_jump", "params": src["params"], "note": note}}


# ------------------------------------------------------------------ verdict helpers
def verdict(status, summary, p, ci, n, checks, binding, best, fix, labels, review, seed, budget, bom=None, cost=None, ref=None):
    return {"schema_version": "0.1.0", "status": status, "summary": summary,
            "feasibility": {"p_success": p, "ci_low": ci[0], "ci_high": ci[1], "n_samples": n, "ci_method": "wilson_95"},
            "necessary_checks": checks, "binding_constraint": binding, "best_params": best, "suggested_fix": fix,
            "bom": bom or [], "cost_estimate": cost, "model_labels": labels,
            "human_review": {"required": bool(review), "items": review},
            "reproducibility": {"seed": seed, "versions": {"mujoco": "4.0.0", "cma": "4.5.0"}, "search_budget": budget, "spec_hash": None},
            "trajectory_ref": ref}


FX = "FIXTURE (dev only, not a real engine run): "


def build_rocket():
    src = json.load(open(SP / "roadster/out/trajectory.json"))
    rep = json.load(open(SP / "roadster/out/report.json"))
    note = "FIXTURE: spike trajectory (ramp_5000N_nominal). Reused for all variants in dev fixtures."
    traj = rocket_traj(src, note)
    sched = {s["window"]: s for s in src["schedule"]}
    best = {f"{w}_{k}": round(v[k], 3) for w, v in sched.items() for k in ("t_start_s", "duration_s", "throttle")}
    labels = ["simplified rigid-body model, needs precise validation", "no aerodynamics / plume / structure"]
    review = [{"assumption_key": "fmax_N", "reason": "Thruster force is an LLM-estimated catalog value (unverified).", "severity": "warn"},
              {"assumption_key": "vehicle_mass", "reason": "Vehicle mass assumed from a spec-sheet class, not measured.", "severity": "info"}]
    cases = {c["name"]: c for c in rep["cases"]}
    mk = lambda ck: ck
    chk_fail = [{"name": "angular_impulse_time", "passed": False, "measured": 3.34, "limit": 2.43, "unit": "s",
                 "note": "min time to rotate 360 deg exceeds flight-time upper bound"}, 
                {"name": "propellant", "passed": True, "measured": 3.79, "limit": 25.0, "unit": "kg", "note": ""}]
    chk_ok = lambda t, ft: [{"name": "angular_impulse_time", "passed": True, "measured": t, "limit": ft, "unit": "s", "note": ""},
                            {"name": "propellant", "passed": True, "measured": 1.76, "limit": 25.0, "unit": "kg", "note": ""}]
    sens = [{"assumption_key": "fmax_N", "effect": 0.31, "rank": 1, "method": "one_at_a_time"},
            {"assumption_key": "vehicle_mass", "effect": -0.12, "rank": 2, "method": "one_at_a_time"}]
    fix = {"changes": [{"param": "fmax_N", "from_value": 3000, "to_value": 5000, "unit": "N"}],
           "rationale": "Smallest control value in the sweep whose Monte-Carlo p_success exceeds 0.5 (5000 N: p=0.848).",
           "verified": True, "verified_p_success": 0.848}
    cost = {"sim_cost": {"n_evals": 33504, "wall_seconds": 40.1},
            "physical_equivalent_estimate": {"is_estimate": True, "low_usd": 150000, "high_usd": 600000,
                                             "basis": "FIXTURE placeholder range for a rocket-assisted vehicle prototype", "sources": ["llm_estimate"]}}
    bom = [{"name": "Cold-gas thruster 5 kN class (x10)", "role": "thruster", "quantity": 10, "mass_kg": 12.0, "unit_cost_usd": None, "source": "llm_estimate"}]
    variants = []
    spec_vals = [300, 2000, 3000, 5000]
    base_budget = {"cma_evals": 33504, "mc_samples": 100}
    for f in spec_vals:
        ref = f"traj_{f}.json"
        if f == 300:
            v = verdict("INFEASIBLE_NECESSARY_CONDITION", "At 300 N the rotation cannot finish within the flight time bound (analytic, strong).", 0.0, (0.0, 0.0), 0,
                        chk_fail, {"name": "angular_impulse_time", "margin": -0.91, "unit": "s", "sensitivities": sens}, {}, fix | {"changes": [{"param": "fmax_N", "from_value": 300, "to_value": 5000, "unit": "N"}]},
                        labels, review, 1, {"cma_evals": 5712}, ref=ref)
            hd = f"[FIXTURE] fmax 300 N: necessary condition violated"
        elif f in (2000, 3000):
            v = verdict("NOT_FOUND_IN_BUDGET", f"Not found in 33504 evals at {f} N: weak evidence only, not proof of impossibility.", 0.0, (0.0, 0.037), 100,
                        chk_ok(1.4, 4.3), {"name": "impact_vz", "margin": -3.0, "unit": "m/s", "sensitivities": sens}, {},
                        fix, labels, review, 1, base_budget, ref=ref)
            hd = f"[FIXTURE] fmax {f} N: not found in budget"
        else:
            v = verdict("FEASIBLE_FOUND", "A 360-degree flip with controlled landing was found; Monte-Carlo p_success 0.848 (n=500).", 0.848, (0.8139, 0.8768), 500,
                        chk_ok(1.01, 4.51), {"name": "impact_vz", "margin": 0.55, "unit": "m/s", "sensitivities": sens}, best, None,
                        labels, review, 1, {"cma_evals": 3072, "mc_samples": 500}, bom=bom, cost=cost, ref=ref)
            hd = f"[FIXTURE] fmax 5000 N: feasible, p=0.848"
        variants.append({"value": f, "verdict": v, "trajectory": ref, "headline": hd})
        (OUT / "rocket_flip").mkdir(parents=True, exist_ok=True)
        json.dump(traj, open(OUT / "rocket_flip" / ref, "w"), separators=(",", ":"))
    spec = {"schema_version": "0.1.0", "idea": "A 1300 kg roadster does a 360-degree flip with rocket thrusters and lands upright.",
            "template_id": "rocket_car", "tier": 1,
            "assumptions": [
                {"key": "vehicle_mass", "label": "Vehicle mass", "value": 1300, "unit": "kg", "distribution": {"kind": "normal", "mean": 1300, "std": 65, "clip_low": None, "clip_high": None}, "source": "llm_estimate", "confidence": "low", "editable": True},
                {"key": "fmax_N", "label": "Max thrust per thruster", "value": 5000, "unit": "N", "distribution": {"kind": "uniform", "low": 4500, "high": 5500}, "source": "llm_estimate", "confidence": "low", "editable": True},
                {"key": "ramp_angle", "label": "Launch ramp angle", "value": 25, "unit": "deg", "distribution": {"kind": "fixed"}, "source": "user", "confidence": "high", "editable": True}],
            "parts": [], "param_bounds": [], "success_criteria": [
                {"name": "full_rotation", "metric": "rotation_deg", "comparator": ">=", "threshold": 360, "unit": "deg", "description": "full flip"}]}
    steps = [("research", "Research assumptions", "catalog.lookup", 0.02, "FIXTURE catalog read"),
             ("assumptions", "Assumptions panel", "spec.build", 0.01, "3 assumptions drafted"),
             ("build_model", "Build MuJoCo model", "template.rocket_car", 0.4, "Model compiled"),
             ("necessary_screen", "Necessary-condition screen", "screen.analytic", 0.01, "angular impulse / propellant"),
             ("search", "CMA-ES search", "cma.search", 3.35, "found at 3072 evals (5 kN)"),
             ("monte_carlo", "Monte-Carlo verdict", "mc.wilson", 0.7, "p=0.848 (500)"),
             ("robustify", "Robustify", "cma.robust", 25.7, "train success 0.958"),
             ("bom", "Bill of materials", "bom.build", 0.01, "1 line")]
    steps = [{"id": a, "label": b, "tool": c, "status": "done", "wall_seconds": d, "summary": "[FIXTURE] " + e, "detail": None} for a, b, c, d, e in steps]
    scen = {"id": "rocket_flip", "idea": spec["idea"], "template": "rocket_car", "agent_steps": steps, "spec": spec,
            "control": {"key": "fmax_N", "label": "Max thrust per thruster", "unit": "N", "values": spec_vals, "default_index": 1,
                        "hint": "Sweep the thruster force; each value is a separate seeded run."},
            "variants": variants}
    json.dump(scen, open(OUT / "rocket_flip" / "scenario.json", "w"), indent=1)
    return {"id": "rocket_flip", "title": "Rocket roadster flip", "idea": spec["idea"], "template": "rocket_car",
            "tagline": "Can a 1.3 t car flip 360 deg on thrusters and land?", "tier": 1, "hero": True}, spec, variants


def build_humanoid():
    note = "FIXTURE: capsule skeleton from spike G1 trajectory. Reused for failing variant."
    t02 = humanoid_traj(json.load(open(SP / "humanoid_jump/out/trajectory.json")), note)
    t04 = humanoid_traj(json.load(open(SP / "humanoid_jump/out/trajectory_0.4m.json")), note)
    d = OUT / "g1_jump"; d.mkdir(parents=True, exist_ok=True)
    labels = ["simplified rigid-body model with torque limits; no actuator thermal model"]
    review = [{"assumption_key": "torque_scale", "reason": "Actuator torque limits taken from a public spec (unverified).", "severity": "warn"}]
    checks_ok = [{"name": "static_torque_saturation", "passed": True, "measured": 0.08, "limit": 1.0, "unit": "ratio", "note": ""}]
    checks_bad = [{"name": "energy_budget", "passed": False, "measured": 380.0, "limit": 210.0, "unit": "J", "note": "FIXTURE numbers"}]
    sens = [{"assumption_key": "torque_scale", "effect": 0.4, "rank": 1, "method": "one_at_a_time"}]
    vs = []
    for h in (0.2, 0.4, 1.2):
        ref = f"traj_{h}.json"
        if h == 1.2:
            v = verdict("INFEASIBLE_NECESSARY_CONDITION", "A 1.2 m jump requires more takeoff energy than the actuators can deliver (FIXTURE numbers).", 0, (0, 0), 0, checks_bad,
                        {"name": "energy_budget", "margin": -170.0, "unit": "J", "sensitivities": sens}, {}, None, labels, review, 1, {}, ref=ref)
            hd = "[FIXTURE] target 1.2 m: necessary condition violated"
            json.dump(t04, open(d / ref, "w"), separators=(",", ":"))
        else:
            v = verdict("FEASIBLE_FOUND", f"Jump of {h} m found with stable landing (spike result).", 0.9, (0.8, 0.95), 40, checks_ok,
                        {"name": "torque_demand", "margin": 0.1, "unit": "ratio", "sensitivities": sens}, {"target": h}, None, labels, review, 1, {"cma_evals": 6000}, ref=ref)
            hd = f"[FIXTURE] target {h} m: feasible"
            json.dump(t02 if h == 0.2 else t04, open(d / ref, "w"), separators=(",", ":"))
        vs.append({"value": h, "verdict": v, "trajectory": ref, "headline": hd})
    spec = {"schema_version": "0.1.0", "idea": "A Unitree G1 humanoid jumps a given height and lands.", "template_id": "humanoid_jump", "tier": 1,
            "assumptions": [{"key": "torque_scale", "label": "Joint torque scale", "value": 1.0, "unit": "", "distribution": {"kind": "fixed"}, "source": "https://github.com/google-deepmind/mujoco_menagerie", "confidence": "med", "editable": True}],
            "parts": [], "param_bounds": [], "success_criteria": [{"name": "apex", "metric": "com_apex_rise", "comparator": ">=", "threshold": 0.2, "unit": "m", "description": ""}]}
    scen = {"id": "g1_jump", "idea": spec["idea"], "template": "humanoid_jump", "spec": spec,
            "agent_steps": [{"id": "search", "label": "CMA-ES search", "tool": "cma.search", "status": "done", "wall_seconds": 51.4, "summary": "[FIXTURE] 6000 evals", "detail": None}],
            "control": {"key": "target", "label": "Target jump height", "unit": "m", "values": [0.2, 0.4, 1.2], "default_index": 2, "hint": "FIXTURE"},
            "variants": vs}
    json.dump(scen, open(d / "scenario.json", "w"), indent=1)
    return {"id": "g1_jump", "title": "Humanoid jump", "idea": spec["idea"], "template": "humanoid_jump",
            "tagline": "How high can a G1 jump?", "tier": 1, "hero": False}, spec, vs


def build_autoresearch():
    ar = SP / "autoresearch"
    d = OUT / "autoresearch"; d.mkdir(parents=True, exist_ok=True)
    entries = [json.loads(l) for l in open(ar / "ledger.jsonl")]
    prev, ok = "", True
    for e in entries:
        ok &= e["prev_hash"] == prev; prev = e["entry_hash"]
    att = [e for e in entries if e["id"].startswith("att")]
    json.dump({"chain_verified": ok, "head_hash": prev, "metric_name": "mc_success_rate - 1e-4*fuel", "entries": att,
               "excitation_entries": [e for e in entries if e["id"].startswith("exc")],
               "calibration_entries": [e for e in entries if e["id"].startswith("cal")]}, open(d / "ledger.json", "w"))
    cal = json.load(open(ar / "calibration.json"))
    res = json.load(open(ar / "out/results.json"))
    cal["truth"] = {k: v["truth"] for k, v in res["calibration"]["coverage"].items()}
    cal["failure_case"] = json.load(open(ar / "calibration_failure_case.json"))
    json.dump(cal, open(d / "calibration.json", "w"))
    rows = []
    for r in res["verdict_rows"]:
        rows.append({**r, "stage": "before" if r["label"].startswith("before") else "after"})
    json.dump({"rows": rows, "note": "from spike results.json"}, open(d / "integration.json", "w"))
    json.dump({**res["excitation"], "unit": "nats"}, open(d / "excitation.json", "w"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scs, specs = [], []
    for fn in (build_rocket, build_humanoid):
        meta, spec, vs = fn()
        scs.append(meta)
        specs.append((meta["id"], spec, vs))
    build_autoresearch()
    json.dump({"scenarios": scs, "autoresearch": {"attitude_ledger": "autoresearch/ledger.json", "calibration": "autoresearch/calibration.json",
                                                   "integration": "autoresearch/integration.json", "excitation": "autoresearch/excitation.json"}},
              open(OUT / "index.json", "w"), indent=1)
    if Verdict is not None:
        for sid, spec, vs in specs:
            SpecSheet.model_validate(spec)
            for v in vs:
                Verdict.model_validate(v["verdict"])
                Trajectory.model_validate(json.load(open(OUT / sid / v["trajectory"])))
        print("schema validation OK")
    print("fixtures written to", OUT)


if __name__ == "__main__":
    sys.exit(main())
