"""Live design: run the pipeline for (idea, overrides) at a small budget, then derive a DesignBrief (no CAD files, closed loop capped)."""
from __future__ import annotations

import datetime as _dt
from typing import Any

import mujoco

from physlab_core.schemas import VerdictStatus

from .. import pipeline
from ..base import Budget
from ..templates import get as get_template
from . import brief as B, closedloop as CL, humanoid as HD, rocket as RK

TEMPLATES = {
    "rocket_car": dict(design=RK.design, mass_key="vehicle_mass", control_key="thruster_force_max", control_label="Max thrust per nozzle", unit="N",
                       mass_note="vehicle mass assumption", risks=B.ROCKET_RISKS, tests=B.ROCKET_TESTS),
    "humanoid_jump": dict(design=HD.design, mass_key="robot_mass", control_key="torque_scale", control_label="Motor torque scale", unit="x G1 forcerange",
                          mass_note="robot mass assumption", risks=B.HUMANOID_RISKS, tests=B.HUMANOID_TESTS),
}


class NoWitness(ValueError):
    """The base run did not produce a FEASIBLE_FOUND witness, so no design can be derived."""


def design_for(idea: str, template_id: str, overrides: dict[str, float], seed: int | None, budget: Budget, scenario_id: str = "live",
               max_iter: int = 1, use_cache: bool = True) -> dict[str, Any]:
    cfg = TEMPLATES[template_id]
    tpl = get_template(template_id)
    r0 = pipeline.run(idea, template_id, overrides or None, seed, budget, fix=False, use_cache=use_cache)
    if r0.verdict.status != VerdictStatus.FEASIBLE_FOUND:
        raise NoWitness(f"base run is {r0.verdict.status.value}; a design is only derived from a FEASIBLE_FOUND witness. {r0.verdict.summary}")
    base_mass = float(next(a.value for a in r0.spec.assumptions if a.key == cfg["mass_key"]))
    ctrl = float(next(a.value for a in r0.spec.assumptions if a.key == cfg["control_key"]))
    witness = dict(r0.verdict.best_params)

    def designed(params, ov):
        return cfg["design"](tpl.default_spec(idea, ov), params, r0.seed, "live witness", None)

    d0 = designed(witness, dict(overrides))
    CL.MAX_ITER, old = max_iter, CL.MAX_ITER
    try:
        ls = CL.LoopSpec(idea=idea, template_id=template_id, seed=r0.seed, budget=budget, base_overrides=dict(overrides), mass_key=cfg["mass_key"], base_mass=base_mass,
                         mass_note=cfg["mass_note"], design_mass=lambda p, ov: designed(p, ov)["mass_added_kg"], use_cache=use_cache, log=lambda m: None)
        loop = CL.run_loop(ls, r0.verdict, witness)
    finally:
        CL.MAX_ITER = old
    n_ok = sum(1 for c in d0["components"] if c["ok"])
    hl = B.headline(template_id, ctrl, cfg["control_label"], cfg["unit"], loop["rows"], d0["mass_added_kg"], n_ok, len(d0["components"]), len(d0["custom_parts"]),
                    sum(1 for c in d0["components"] if c["needs_sourcing"]))
    repro = dict(seed=r0.seed, engine="kinetra_engine 0.1.0", mujoco=mujoco.__version__, generated_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                 budget=dict(cma_evals=budget.max_evals, mc_samples=budget.mc_samples, max_seconds=budget.max_seconds), base_spec_hash=r0.verdict.reproducibility.spec_hash)
    labels = list(dict.fromkeys(r0.verdict.model_labels + [B.common.SIMPLIFIED_FEA, f"Live design at a small budget ({budget.max_evals} search evals, {budget.mc_samples} MC samples); closed loop capped at {max_iter} iteration(s)."]))
    return B.build(scenario_id=scenario_id, template=template_id, base_variant=ctrl, headline_text=hl, derived=d0, closed_rows=loop["rows"], alternatives=[],
                   risks=cfg["risks"], tests=cfg["tests"], labels=labels, repro=repro)
