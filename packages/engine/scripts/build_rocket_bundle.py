"""Build apps/web/public/demo/roadster/{scenario.json, traj_<k>.json}: real seeded pipeline runs, one per thruster Fmax.

    packages/engine/.venv/bin/python packages/engine/scripts/build_rocket_bundle.py [--quick] [--no-cache]

Results of each (spec, seed, budget) core run are cached in packages/engine/.cache/ (gitignored), so re-runs are fast.
Rollouts use the multi-core mujoco.rollout thread pool (KINETRA_THREADS overrides the thread count).
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

from physlab_core.schemas import SpecSheet, Trajectory, Verdict, VerdictStatus  # noqa: E402

from kinetra_engine import pipeline  # noqa: E402
from kinetra_engine.base import Budget  # noqa: E402

OUT = REPO / "apps/web/public/demo/roadster"
IDEA = "Tesla Roadster does a rocket-thruster aerial flip off a ramp: a full 360-degree pitch flip and an upright landing"
VALUES = [300.0, 1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0]
SEED = 20260001
QUICK = "--quick" in sys.argv
BUDGET = Budget(max_evals=4000 if QUICK else 15000, max_seconds=400.0, mc_samples=100 if QUICK else 500)


def _write(path: Path, obj) -> int:
    s = json.dumps(obj, separators=(",", ":"), allow_nan=False)
    path.write_text(s)
    return len(s)


def main() -> None:
    use_cache = "--no-cache" not in sys.argv
    t_all = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    runs = {}
    for v in VALUES:
        t0 = time.perf_counter()
        r = pipeline.run(IDEA, "rocket_car", {"thruster_force_max": v}, SEED, BUDGET, fix=True, use_cache=use_cache)
        runs[v] = r
        f = r.verdict.feasibility
        print(f"Fmax={v:6.0f} N  {r.verdict.status.value:32s} p={f.p_success:.3f} CI[{f.ci_low:.3f},{f.ci_high:.3f}] n={f.n_samples:4d} "
              f"evals={r.core.n_evals:6d} core_wall={r.core.wall_seconds:6.1f}s run_wall={time.perf_counter() - t0:6.1f}s cache_hit={r.cache_hit}"
              f"  fix={'->' + format(r.verdict.suggested_fix.changes[0].to_value, 'g') if r.verdict.suggested_fix else '-'}", flush=True)

    statuses = {r.verdict.status for r in runs.values()}
    if VerdictStatus.FEASIBLE_FOUND not in statuses or not statuses - {VerdictStatus.FEASIBLE_FOUND}:
        raise SystemExit(f"bundle rule violated: need >=1 FEASIBLE_FOUND and >=1 other status, got {sorted(s.value for s in statuses)}")

    # ---- variants (every trajectory is a real rollout of that variant's witness / best attempt)
    variants = []
    sizes = {}
    for v in VALUES:
        r = runs[v]
        name = f"traj_{int(v)}.json"
        traj = Trajectory.model_validate(r.trajectory.model_dump(mode="json"))
        sizes[name] = _write(OUT / name, traj.model_dump(mode="json"))
        verdict = r.verdict.model_copy(update={"trajectory_ref": name})
        verdict = Verdict.model_validate(verdict.model_dump(mode="json"))
        variants.append(dict(value=v, verdict=verdict.model_dump(mode="json"), trajectory=name,
                             headline=pipeline.headline(verdict, "Max thrust per nozzle", v, "N")))

    # ---- agent steps: full pipeline log of the hero (feasible) run; its fix_search step is replaced by the real fix search
    # of the lowest-thrust variant that is NOT feasible, so the log shows the whole fail -> fix path.
    feas = [v for v in VALUES if runs[v].verdict.status == VerdictStatus.FEASIBLE_FOUND]
    failing_with_fix = [v for v in VALUES if runs[v].verdict.status != VerdictStatus.FEASIBLE_FOUND and runs[v].verdict.suggested_fix]
    hero_v = feas[len(feas) // 2] if len(feas) > 1 else feas[0]
    hero_v = 5000.0 if 5000.0 in feas else hero_v
    steps = [dict(s) for s in runs[hero_v].agent_steps]
    if failing_with_fix:
        fv = failing_with_fix[-1] if 3000.0 not in failing_with_fix else 3000.0
        fs = next(s for s in runs[fv].agent_steps if s["id"] == "fix_search")
        for i, s in enumerate(steps):
            if s["id"] == "fix_search":
                steps[i] = dict(fs, summary=f"(from the {fv:g} N variant run) " + fs["summary"])
    default_index = VALUES.index(failing_with_fix[len(failing_with_fix) // 2] if failing_with_fix else VALUES[0])   # open on a fail -> fix moment

    spec = SpecSheet.model_validate(runs[hero_v].spec.model_dump(mode="json"))
    scenario = dict(
        id="roadster", idea=IDEA, template="rocket_car",
        title="Rocket roadster flip", tagline="Can a 1.3 t car flip 360 deg on cold-gas thrusters and land upright?", tier=1, hero=True,
        agent_steps=steps, spec=spec.model_dump(mode="json"),
        control=dict(key="thruster_force_max", label="Max thrust per nozzle", unit="N", values=VALUES, default_index=default_index,
                     hint="Thrust each of the 10 cold-gas nozzles can deliver. No official figure exists for the real hardware, so this is the swept unknown; "
                          "each value is a separate seeded run (seed %d)." % SEED),
        variants=variants,
        build=dict(seed=SEED, budget=dict(cma_evals=BUDGET.max_evals, mc_samples=BUDGET.mc_samples, max_seconds=BUDGET.max_seconds), quick=QUICK,
                   hero_variant=hero_v, labels=runs[hero_v].verdict.model_labels, note="simplified model, needs precise validation"),
    )
    n = _write(OUT / "scenario.json", scenario)
    # validate round trip
    sc = json.loads((OUT / "scenario.json").read_text())
    SpecSheet.model_validate(sc["spec"])
    for var in sc["variants"]:
        Verdict.model_validate(var["verdict"])
        Trajectory.model_validate(json.loads((OUT / var["trajectory"]).read_text()))
    total = n + sum(sizes.values())
    subprocess.run([sys.executable, str(HERE / "build_index.py")], check=True)
    print(f"wrote {OUT} scenario.json={n/1e3:.0f} kB, trajectories={sum(sizes.values())/1e3:.0f} kB, total {total/1e6:.2f} MB; "
          f"total wall {time.perf_counter() - t_all:.1f} s")


if __name__ == "__main__":
    main()
