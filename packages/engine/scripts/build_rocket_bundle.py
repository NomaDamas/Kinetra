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
from kinetra_engine.templates import get as get_template  # noqa: E402

OUT = REPO / "apps/web/public/demo/roadster"
IDEA = "Tesla Roadster does a rocket-thruster aerial flip off a ramp: a full 360-degree pitch flip and an upright landing"
VALUES = [300.0, 1000.0, 2000.0, 2500.0, 3000.0, 3500.0, 4000.0, 5000.0, 6000.0]
TPL = get_template('rocket_car')
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

    def one(v, warm, tag):
        t0 = time.perf_counter()
        r = pipeline.run(IDEA, "rocket_car", {"thruster_force_max": v}, SEED, BUDGET, fix=False, use_cache=use_cache, warm_params=warm)
        f = r.verdict.feasibility
        print(f"[{tag}] Fmax={v:6.0f} N  {r.verdict.status.value:32s} p={f.p_success:.3f} CI[{f.ci_low:.3f},{f.ci_high:.3f}] n={f.n_samples:4d} "
              f"evals={r.core.n_evals:6d} core_wall={r.core.wall_seconds:6.1f}s run_wall={time.perf_counter() - t0:6.1f}s cache_hit={r.cache_hit} warm={'y' if warm else 'n'}", flush=True)
        return r

    def feasible(r):
        return r.verdict.status == VerdictStatus.FEASIBLE_FOUND

    # pass 1: ascending, warm start from the nearest lower feasible neighbour (throttle rescaled to keep commanded thrust)
    prev = None
    for v in VALUES:
        w = TPL.rescale_params(prev[1], prev[0], v) if prev else None
        runs[v] = one(v, w, "up")
        if feasible(runs[v]):
            prev = (v, runs[v].core.params)
    # pass 2: descending, warm start from a higher neighbour that did better (adopted only if it is a nominal witness with better MC)
    for i in range(len(VALUES) - 2, -1, -1):
        v, hi = VALUES[i], runs[VALUES[i + 1]]
        if feasible(hi) and hi.verdict.feasibility.p_success > runs[v].verdict.feasibility.p_success and v >= 1000.0:
            w = TPL.rescale_params(hi.core.params, VALUES[i + 1], v)
            r2 = one(v, w, "down")
            f1, f2 = runs[v].verdict.feasibility.p_success, r2.verdict.feasibility.p_success
            if feasible(r2) and (not feasible(runs[v]) or f2 > f1):
                runs[v] = r2

    # sweep-produced fix: smallest Fmax whose MC-verified p_success >= P_FIX
    cands = [dict(value=v, found=feasible(runs[v]), p_success=runs[v].verdict.feasibility.p_success if feasible(runs[v]) else None,
                  n=runs[v].verdict.feasibility.n_samples, n_evals=runs[v].core.n_evals) for v in VALUES]
    fixes = {v: pipeline.build_fix("thruster_force_max", "N", v, cands) for v in VALUES}

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
        fx = fixes[v] if (not feasible(r) or r.verdict.feasibility.p_success < pipeline.P_FIX) else None
        verdict = r.verdict.model_copy(update={"trajectory_ref": name, "suggested_fix": fx})
        verdict = Verdict.model_validate(verdict.model_dump(mode="json"))
        head = pipeline.headline(verdict, "Max thrust per nozzle", v, "N")
        lower = [runs[u].verdict.feasibility.p_success for u in VALUES if u < v and feasible(runs[u])]
        if feasible(r) and lower and r.verdict.feasibility.p_success < max(lower) - 0.10:
            head += " — below a lower-thrust variant: search noise (finite budget), not physics"
        variants.append(dict(value=v, verdict=verdict.model_dump(mode="json"), trajectory=name, headline=head))

    # ---- agent steps: full pipeline log of the hero (feasible) run; its fix_search step is replaced by the real fix search
    # of the lowest-thrust variant that is NOT feasible, so the log shows the whole fail -> fix path.
    feas = [v for v in VALUES if feasible(runs[v])]
    hero_v = 5000.0 if 5000.0 in feas else feas[-1]
    steps = [dict(s) for s in runs[hero_v].agent_steps]
    fx0 = next((fixes[v] for v in VALUES if not feasible(runs[v]) and fixes[v]), None)
    fs_txt = ("; ".join(f"{c['value']:g} N: " + ("not found" if not c["found"] else f"p={c['p_success']:.2f}") for c in cands))
    for i, st in enumerate(steps):
        if st["id"] == "fix_search":
            steps[i] = dict(st, wall_seconds=round(sum(runs[v].core.wall_seconds for v in VALUES), 2),
                            summary=("Sweep over thruster_force_max (warm-started from neighbouring variants): " + fs_txt + ". " +
                                     (f"Smallest value with MC-verified p_success >= {pipeline.P_FIX:g}: {fx0.changes[0].to_value:g} N (p={fx0.verified_p_success:.2f})." if fx0 else
                                      f"No tested value reached p_success >= {pipeline.P_FIX:g}.")),
                            detail=dict(candidates=cands, threshold=pipeline.P_FIX))
    failing_with_fix = [v for v in VALUES if not feasible(runs[v]) and fixes[v]]
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
