"""Closed loop: designed hardware mass -> mass assumption -> full pipeline re-run (search + Monte-Carlo) -> redesign from the new witness.

Every iteration is a REAL ``pipeline.run`` (cache reused when the same (spec, seed, budget, warm start) was already computed).
A p_success drop is recorded as is. Stops when the re-derived design mass changes the total mass by < TOL (1 %), at MAX_ITER
iterations, or when an iteration has no witness (then no new design can be derived).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import pipeline
from ..base import Budget
from physlab_core.schemas import VerdictStatus

TOL = 0.01
MAX_ITER = 3


@dataclass
class LoopSpec:
    idea: str
    template_id: str
    seed: int
    budget: Budget
    base_overrides: dict[str, float]          # includes the control (e.g. thruster_force_max) but NOT the mass key
    mass_key: str                             # assumption key carrying the mass that the design adds to
    base_mass: float
    mass_note: str                            # what 'mass' means for this template
    design_mass: Callable[[dict[str, float], dict[str, float]], float]   # (witness params, assumption overrides it was found under) -> designed hardware mass [kg]
    search_seeds: int = 3
    use_cache: bool = True
    log: Callable[[str], None] = field(default=print)


def _row(it: int, mass: float, run: "pipeline.PipelineRun | None", note: str, overrides: dict[str, float], v=None) -> dict[str, Any]:
    verdict = v if v is not None else run.verdict
    f = verdict.feasibility
    ce = verdict.cost_estimate
    return dict(iteration=it, mass_kg=float(mass), status=verdict.status.value, p_success=float(f.p_success),
                ci=[float(f.ci_low), float(f.ci_high)], n=int(f.n_samples), note=note,
                n_evals=int(ce.sim_cost.n_evals) if ce else 0, wall_seconds=float(ce.sim_cost.wall_seconds) if ce else 0.0,
                assumption_overrides=dict(overrides))


def run_alternative_point(ls: LoopSpec, witness: dict[str, float], prev_ov: dict[str, float] | None = None) -> dict[str, Any]:
    """One closed-loop step: add the mass designed from ``witness``, re-run the pipeline. Returns the iteration-1 result + run."""
    added = ls.design_mass(witness, ls.base_overrides if prev_ov is None else prev_ov)
    mass = ls.base_mass + added
    ov = {**ls.base_overrides, ls.mass_key: mass}
    t0 = time.perf_counter()
    r = pipeline.run(ls.idea, ls.template_id, ov, ls.seed, ls.budget, fix=False, use_cache=ls.use_cache, search_seeds=ls.search_seeds, warm_params=witness)
    return dict(added=added, mass=mass, overrides=ov, run=r, wall=time.perf_counter() - t0)


def run_loop(ls: LoopSpec, base_verdict, base_witness: dict[str, float]) -> dict[str, Any]:
    """``base_verdict`` / ``base_witness``: the existing (bundle) FEASIBLE_FOUND run at base mass = iteration 0."""
    rows = [_row(0, ls.base_mass, None, "before design (the recorded run this design is derived from)", ls.base_overrides, v=base_verdict)]
    witness, prev_ov = dict(base_witness), None
    runs: list[Any] = []
    converged, stop = False, ""
    for it in range(1, MAX_ITER + 1):
        step = run_alternative_point(ls, witness, prev_ov)
        r, added, mass = step["run"], step["added"], step["mass"]
        prev_mass = rows[-1]["mass_kg"]
        note = (f"{ls.mass_note}: base {ls.base_mass:g} kg + designed hardware {added:.2f} kg"
                + ("" if it == 1 else f" (re-derived from iteration {it - 1}'s witness)") + f"; cache_hit={r.cache_hit}")
        rows.append(_row(it, mass, r, note, step["overrides"]))
        runs.append(r)
        ls.log(f"  closed loop it={it} mass={mass:.2f} kg -> {r.verdict.status.value} p={r.verdict.feasibility.p_success:.3f} wall={step['wall']:.0f}s")
        if r.verdict.status != VerdictStatus.FEASIBLE_FOUND:
            weak = " (WEAK: not found within the search budget is not proof it is impossible)" if r.verdict.status == VerdictStatus.NOT_FOUND_IN_BUDGET else ""
            stop = f"iteration {it}: {r.verdict.status.value}{weak} — no witness at the designed mass, so no new design can be derived; loop stopped"
            break
        witness = dict(r.verdict.best_params)
        added2 = ls.design_mass(witness, step['overrides'])
        mass2 = ls.base_mass + added2
        rel = abs(mass2 - mass) / mass
        rows[-1]["note"] += f"; redesign from this witness would weigh {added2:.2f} kg ({100 * rel:.2f} % of vehicle mass change)"
        if rel < TOL:
            converged, stop = True, f"converged after {it} iteration(s): re-derived design changes mass by {100 * rel:.2f} % < {100 * TOL:g} %"
            break
        prev_ov = step['overrides']
    else:
        stop = f"stopped at the {MAX_ITER}-iteration limit without reaching < {100 * TOL:g} % mass change"
    return dict(rows=rows, runs=runs, converged=converged, stop_reason=stop)
