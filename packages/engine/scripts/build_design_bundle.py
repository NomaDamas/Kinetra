"""Build apps/web/public/demo/<id>/{design.json, cad/*, export/*} for the roadster and humanoid scenarios.

    packages/engine/.venv/bin/python packages/engine/scripts/build_design_bundle.py [roadster] [humanoid] [--no-cache] [--quick]

Reads the recorded scenario bundles (scenario.json + traj_*.json written by build_rocket_bundle.py / build_humanoid_bundle.py), derives
requirements from REAL rollouts of the base variant's witness, selects catalog components / sizes custom parts (CAD), then runs the
closed loop (designed mass -> full pipeline re-run) and the alternatives through the same pipeline. Pipeline core runs are cached in
packages/engine/.cache like the bundle builders (same budget => cache hits for already-computed runs).
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "src"))

import mujoco  # noqa: E402

from physlab_core.schemas import SpecSheet, Verdict, VerdictStatus  # noqa: E402

from kinetra_engine.base import Budget  # noqa: E402
from kinetra_engine.design import brief as B, closedloop as CL, humanoid as HD, rocket as RK  # noqa: E402
from kinetra_engine.templates import get as get_template  # noqa: E402

DEMO = REPO / "apps/web/public/demo"
QUICK = "--quick" in sys.argv
USE_CACHE = "--no-cache" not in sys.argv
ENGINE = "kinetra_engine 0.1.0"


def log(msg: str) -> None:
    print(msg, flush=True)


CONFIGS = {
    "roadster": dict(
        template="rocket_car", design=RK.design, mass_key="vehicle_mass", control_key="thruster_force_max", control_label="Max thrust per nozzle", unit="N",
        alt_values=[4000.0, 5000.0, 6000.0], risks=B.ROCKET_RISKS, tests=B.ROCKET_TESTS,
        alt_label=lambda v: f"10 x {v / 1000:g} kN nozzles",
        mass_note="vehicle mass assumption (incl. wheels, occupant, gas)",
        mass_caveat=("The template's BOM says nozzle/tank mass is nominally inside the 1300 kg vehicle_mass; the closed loop conservatively adds the designed "
                     "hardware ON TOP of it (upper bound on the mass effect). Nozzle count (10) is fixed by the template, so alternatives vary thrust per nozzle."),
        extra_labels=["Aerodynamics not simulated; thermal/blow-down not modelled; ideal constant-Isp thrust (see verdict labels)."]),
    "humanoid": dict(
        template="humanoid_jump", design=HD.design, mass_key="robot_mass", control_key="torque_scale", control_label="Motor torque scale", unit="x G1 forcerange",
        alt_values=[0.6, 1.0], risks=B.HUMANOID_RISKS, tests=B.HUMANOID_TESTS,
        alt_label=lambda v: f"actuators sized for torque scale x{v:g}",
        mass_note="robot mass assumption (Menagerie G1 link masses)",
        mass_caveat=("The G1 model's own link masses already include its motors; the sourced catalog gives no per-joint G1 actuator mass to subtract, so the designed "
                     "actuators/links are added ON TOP of robot_mass (upper bound on the mass effect)."),
        extra_labels=["Joint speed compared with vendor no-load speed (optimistic at peak torque); no torque-speed curves."]),
}


def load_scenario(sid: str) -> dict:
    p = DEMO / sid / "scenario.json"
    return json.loads(p.read_text())


def build_one(sid: str) -> dict:
    cfg = CONFIGS[sid]
    t_all = time.perf_counter()
    sc = load_scenario(sid)
    tpl = get_template(cfg["template"])
    b = sc["build"]
    seed = int(b["seed"])
    budget = Budget(max_evals=int(b["budget"]["cma_evals"]), max_seconds=float(b["budget"]["max_seconds"]), mc_samples=int(b["budget"]["mc_samples"]))
    if QUICK:
        budget = Budget(max_evals=min(budget.max_evals, 3000), max_seconds=min(budget.max_seconds, 60.0), mc_samples=min(budget.mc_samples, 100))
    variants = {float(v["value"]): v for v in sc["variants"]}
    hero = float(b["hero_variant"])
    base_over = {cfg["control_key"]: hero}
    if sid == "humanoid":
        base_over["target_height"] = float(b["target_height_m"])
    base_v = variants[hero]
    base_verdict = Verdict.model_validate(base_v["verdict"])
    if base_verdict.status != VerdictStatus.FEASIBLE_FOUND:
        raise SystemExit(f"{sid}: hero variant {hero} is not FEASIBLE_FOUND")
    spec0 = SpecSheet.model_validate(sc["spec"])
    base_mass = float(next(a.value for a in spec0.assumptions if a.key == cfg["mass_key"]))
    cad_dir = DEMO / sid / "cad"
    if cad_dir.exists():
        shutil.rmtree(cad_dir)

    memo: dict[str, dict] = {}

    def designed(params, overrides, cad=None):
        key = json.dumps([params, sorted(overrides.items()), cad is not None], sort_keys=True)
        if key not in memo:
            memo[key] = cfg["design"](tpl.default_spec(sc["idea"], overrides), params, seed, base_v["trajectory"], cad)
        return memo[key]

    def design_mass(params, overrides):
        # the design depends on the witness; overrides only matter through assumptions the requirements read (isp, mass)
        return designed(params, overrides)["mass_added_kg"]

    log(f"[{sid}] deriving requirements from the {hero:g} variant's witness ({base_v['trajectory']})")
    t0 = time.perf_counter()
    d0 = designed(base_v["verdict"]["best_params"], base_over, cad_dir)
    t_design = time.perf_counter() - t0
    log(f"[{sid}] design done in {t_design:.1f} s: +{d0['mass_added_kg']:.2f} kg ({d0['mass_estimated_kg']:.2f} kg estimated), "
        f"{sum(1 for c in d0['components'] if c['ok'])}/{len(d0['components'])} lines catalog-ok")

    ls = CL.LoopSpec(idea=sc["idea"], template_id=cfg["template"], seed=seed, budget=budget, base_overrides=base_over, mass_key=cfg["mass_key"], base_mass=base_mass,
                     mass_note=cfg["mass_note"], design_mass=design_mass, use_cache=USE_CACHE, log=log)
    t0 = time.perf_counter()
    loop = CL.run_loop(ls, base_verdict, base_v["verdict"]["best_params"])
    t_loop = time.perf_counter() - t0
    log(f"[{sid}] closed loop: {loop['stop_reason']} ({t_loop:.0f} s)")

    # ---- alternatives (each: design from that variant's own witness, add its mass, re-run the pipeline once)
    alts = []
    t0 = time.perf_counter()
    for v in cfg["alt_values"]:
        var = variants.get(v)
        if var is None or var["verdict"]["status"] != VerdictStatus.FEASIBLE_FOUND.value:
            log(f"[{sid}] alternative {v:g}: no FEASIBLE_FOUND recorded variant; skipped")
            continue
        ov = {**base_over, cfg["control_key"]: v}
        dv = designed(var["verdict"]["best_params"], ov)
        lsv = CL.LoopSpec(**{**ls.__dict__, "base_overrides": ov, "log": log})
        step = CL.run_alternative_point(lsv, var["verdict"]["best_params"])
        r = step["run"]
        f = r.verdict.feasibility
        rec = dict(id="", label=cfg["alt_label"](v), changes={cfg["control_key"]: v}, status=r.verdict.status.value, p_success=float(f.p_success),
                   ci=[float(f.ci_low), float(f.ci_high)], n=int(f.n_samples), mass_kg=float(step["mass"]), mass_added_kg=float(step["added"]), cost_usd=None,
                   unpriced_lines=B.common.count_unpriced(dv["components"]), recommended=False,
                   note=(f"recorded variant without hardware mass: p_success {100 * var['verdict']['feasibility']['p_success']:.0f}%; "
                         f"with designed hardware ({step['added']:.1f} kg added) re-run: {r.verdict.status.value}, p_success {100 * f.p_success:.1f}%"))
        alts.append(rec)
        log(f"[{sid}] alternative {rec['label']}: {rec['status']} p={rec['p_success']:.3f} (+{rec['mass_added_kg']:.1f} kg)")
    t_alts = time.perf_counter() - t0
    feas = [a for a in alts if a["status"] == "FEASIBLE_FOUND"]
    if feas:
        best = max(feas, key=lambda a: (round(a["p_success"], 6), -a["mass_added_kg"]))
        best["recommended"] = True
        best["note"] += "; recommended: highest p_success, then lowest added mass"
    for i, a in enumerate(alts):
        a["id"] = "ABCDEFGH"[i]

    n_ok = sum(1 for c in d0["components"] if c["ok"])
    n_src = sum(1 for c in d0["components"] if c["needs_sourcing"])
    hl = B.headline(cfg["template"], hero, cfg["control_label"], cfg["unit"], loop["rows"], d0["mass_added_kg"], n_ok, len(d0["components"]), len(d0["custom_parts"]), n_src)
    labels = list(dict.fromkeys(b["labels"] + [B.common.SIMPLIFIED_FEA, cfg["mass_caveat"], *cfg["extra_labels"],
                                               "Closed-loop re-runs use the recorded bundle's search/Monte-Carlo budget and seed; each re-run is one seeded sample (finite-budget search noise applies)."]))
    repro = dict(seed=seed, engine=ENGINE, mujoco=mujoco.__version__, generated_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                 budget=dict(cma_evals=budget.max_evals, mc_samples=budget.mc_samples, max_seconds=budget.max_seconds),
                 base_spec_hash=base_verdict.reproducibility.spec_hash)
    brief = B.build(scenario_id=sid, template=cfg["template"], base_variant=hero, headline_text=hl, derived=d0, closed_rows=loop["rows"], alternatives=alts,
                    risks=cfg["risks"], tests=cfg["tests"], labels=labels, repro=repro)
    brief["closed_loop"][-1]["note"] += f" | {loop['stop_reason']}"
    out = DEMO / sid
    (out / "export").mkdir(parents=True, exist_ok=True)
    (out / "design.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    (out / "export" / "design-brief.md").write_text(B.brief_md(brief))
    (out / "export" / "bom.csv").write_text(B.bom_csv(brief))
    for p in cad_dir.glob("*.stl"):
        assert p.stat().st_size <= 2_000_000, p
    wall = time.perf_counter() - t_all
    log(f"[{sid}] wrote design.json, export/, cad/ ({', '.join(p.name for p in sorted(cad_dir.iterdir()))}); wall design={t_design:.1f}s loop={t_loop:.0f}s alts={t_alts:.0f}s total={wall:.0f}s")
    return dict(sid=sid, brief=brief, wall=wall, t_design=t_design, t_loop=t_loop, t_alts=t_alts, loop=loop)


def main() -> None:
    sids = [a for a in sys.argv[1:] if a in CONFIGS] or list(CONFIGS)
    for sid in sids:
        build_one(sid)
        subprocess.run([sys.executable, str(HERE / "build_index.py")], check=True)


if __name__ == "__main__":
    main()
