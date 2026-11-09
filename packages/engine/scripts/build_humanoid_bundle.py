"""Build apps/web/public/demo/humanoid/{scenario.json, traj_<k>.json}: real seeded pipeline runs, one per motor-torque scale.

    packages/engine/.venv/bin/python packages/engine/scripts/build_humanoid_bundle.py [--quick] [--no-cache] [--assets]

Control = motor torque scale (multiplier on the Menagerie G1 forceranges). Measured story at a 0.30 m ballistic jump target:
too little torque -> a necessary condition (takeoff energy) is violated (strong impossible); a bit more -> CMA-ES finds
nothing in budget (weak, 'not found'); enough -> a stable jump is found and Monte-Carlo gives a real p_success.
Core runs are cached in packages/engine/.cache/ (gitignored). G1 GLBs are written to apps/web/public/assets/g1/ with
--assets or when missing. Env: KINETRA_MENAGERIE (model checkout), KINETRA_PROCS (worker processes).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from physlab_core.schemas import SpecSheet, Trajectory, Verdict, VerdictStatus  # noqa: E402

from kinetra_engine import pipeline  # noqa: E402
from kinetra_engine.base import Budget  # noqa: E402

OUT = REPO / "apps/web/public/demo/humanoid"
ASSETS = REPO / "apps/web/public/assets/g1"
IDEA = "A Unitree G1 humanoid robot jumps 0.30 m straight up and lands on its feet without falling"
TARGET = 0.30
VALUES = [0.2, 0.35, 0.5, 0.65, 0.8, 1.0]
HERO = 1.0
SEED = 20260002
QUICK = "--quick" in sys.argv
BUDGET = Budget(max_evals=1500 if QUICK else 4000, max_seconds=90.0 if QUICK else 150.0, mc_samples=100 if QUICK else 300)


def _write(path: Path, obj) -> int:
    s = json.dumps(obj, separators=(",", ":"), allow_nan=False)
    path.write_text(s)
    return len(s)


def main() -> None:
    use_cache = "--no-cache" not in sys.argv
    t_all = time.perf_counter()
    if "--assets" in sys.argv or not (ASSETS / "pelvis.glb").exists():
        import g1_assets
        r = g1_assets.convert(ASSETS)
        print(f"G1 assets: {r['n_meshes']} GLB, {r['total_bytes'] / 1e6:.2f} MB -> {ASSETS}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)

    runs = {}
    for v in VALUES:
        t0 = time.perf_counter()
        r = pipeline.run(IDEA, "humanoid_jump", {"target_height": TARGET, "torque_scale": v}, SEED, BUDGET, fix=True,
                         use_cache=use_cache)
        runs[v] = r
        f = r.verdict.feasibility
        m = r.core.search.detail.get("metrics", {})
        print(f"torque x{v:4.2f}  {r.verdict.status.value:32s} p={f.p_success:.3f} CI[{f.ci_low:.3f},{f.ci_high:.3f}] n={f.n_samples:4d} "
              f"evals={r.core.n_evals:6d} core_wall={r.core.wall_seconds:6.1f}s run_wall={time.perf_counter() - t0:6.1f}s hit={r.cache_hit} "
              f"h={m.get('ballistic_height', float('nan')):.3f} grf={m.get('grf_peak_land_bw', float('nan')):.2f}BW "
              f"class={r.failure_class} fix={'->' + format(r.verdict.suggested_fix.changes[0].to_value, 'g') if r.verdict.suggested_fix else '-'}",
              flush=True)

    statuses = {r.verdict.status for r in runs.values()}
    if VerdictStatus.FEASIBLE_FOUND not in statuses or not statuses - {VerdictStatus.FEASIBLE_FOUND}:
        raise SystemExit(f"bundle rule violated: need >=1 FEASIBLE_FOUND and >=1 other status, got {sorted(s.value for s in statuses)}")

    variants, sizes = [], {}
    for v in VALUES:
        r = runs[v]
        name = f"traj_{int(round(v * 100))}.json"
        traj = Trajectory.model_validate(r.trajectory.model_dump(mode="json"))
        sizes[name] = _write(OUT / name, traj.model_dump(mode="json"))
        verdict = Verdict.model_validate(r.verdict.model_copy(update={"trajectory_ref": name}).model_dump(mode="json"))
        variants.append(dict(value=v, verdict=verdict.model_dump(mode="json"), trajectory=name,
                             headline=pipeline.headline(verdict, "Motor torque scale", v, "x")))

    # agent steps = full log of the hero (feasible) run; its fix_search step is replaced by the real fix search of the
    # highest-torque variant that is NOT feasible (shows the whole fail -> fix path).
    steps = [dict(s) for s in runs[HERO].agent_steps]
    failing_with_fix = [v for v in VALUES if runs[v].verdict.status != VerdictStatus.FEASIBLE_FOUND and runs[v].verdict.suggested_fix]
    if failing_with_fix:
        fv = failing_with_fix[-1]
        fs = next(s for s in runs[fv].agent_steps if s["id"] == "fix_search")
        for i, s in enumerate(steps):
            if s["id"] == "fix_search":
                steps[i] = dict(fs, summary=f"(from the x{fv:g} torque variant run) " + fs["summary"])
    default_index = VALUES.index(next((v for v in VALUES if runs[v].verdict.status == VerdictStatus.NOT_FOUND_IN_BUDGET), VALUES[0]))

    spec = SpecSheet.model_validate(runs[HERO].spec.model_dump(mode="json"))
    scenario = dict(
        id="humanoid", idea=IDEA, template="humanoid_jump",
        title="Humanoid jump", tagline="Can a Unitree G1 jump 0.30 m and land without falling? Turn the motor torque down and watch the verdict change.",
        tier=1, hero=False,
        agent_steps=steps, spec=spec.model_dump(mode="json"),
        control=dict(key="torque_scale", label="Motor torque scale", unit="x G1 forcerange", values=VALUES, default_index=default_index,
                     hint="Multiplier on the Unitree G1 actuator torque limits in the MuJoCo Menagerie model (knee 139, hip 88-139, ankle 50 N*m at x1.0). "
                          "Low values violate a necessary condition (takeoff energy) = strong 'impossible'; mid values: the search finds no jump in budget "
                          "= WEAK 'not found'; high values: a stable jump is found. Each value is a separate seeded run (seed %d); "
                          "the landing peak-force limit (9 BW) is an unverified default." % SEED),
        variants=variants,
        build=dict(seed=SEED, budget=dict(cma_evals=BUDGET.max_evals, mc_samples=BUDGET.mc_samples, max_seconds=BUDGET.max_seconds), quick=QUICK,
                   hero_variant=HERO, target_height_m=TARGET, labels=runs[HERO].verdict.model_labels,
                   assets="/assets/g1/*.glb (MuJoCo Menagerie unitree_g1, BSD-3-Clause)", note="simplified model, needs precise validation"),
    )
    n = _write(OUT / "scenario.json", scenario)
    sc = json.loads((OUT / "scenario.json").read_text())
    SpecSheet.model_validate(sc["spec"])
    for var in sc["variants"]:
        Verdict.model_validate(var["verdict"])
        Trajectory.model_validate(json.loads((OUT / var["trajectory"]).read_text()))
    total = n + sum(sizes.values())
    subprocess.run([sys.executable, str(HERE / "build_index.py")], check=True)
    print(f"wrote {OUT} scenario.json={n / 1e3:.0f} kB, trajectories={sum(sizes.values()) / 1e3:.0f} kB, total {total / 1e6:.2f} MB; "
          f"total wall {time.perf_counter() - t_all:.1f} s")


if __name__ == "__main__":
    main()
