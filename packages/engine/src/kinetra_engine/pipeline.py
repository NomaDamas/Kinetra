"""Kinetra agent pipeline: idea -> template -> research -> assumptions -> model -> screen -> search -> MC ->
robustify -> fix search -> BOM -> validated ``Verdict``.

The 'agent' steps are a deterministic tool pipeline (no LLM): routing is keyword rules (an optional ``router``
hook may replace it), research reads the curated offline catalog (``kinetra_engine.catalog``) and says so.
Every number in the Verdict comes from MuJoCo rollouts, the analytic screen, or the Monte-Carlo sampler.
Verdict asymmetry (docs/judgment-spec.md B):
  * a failed necessary check => INFEASIBLE_NECESSARY_CONDITION (strong), and can never be FEASIBLE_FOUND;
  * a witness (nominal rollout meeting all success criteria) => FEASIBLE_FOUND (strong), p_success from MC;
  * otherwise NOT_FOUND_IN_BUDGET (weak) worded as 'not found in N evaluations'.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as _md
import inspect
import json
import os
import pickle
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from physlab_core.schemas import (
    BindingConstraint, CostEstimate, Feasibility, Fixed, HumanReview, NecessaryCheck, ParamChange, PhysicalEquivalentEstimate,
    ReviewItem, Reproducibility, Sensitivity, SimCost, SpecSheet, SuggestedFix, Trajectory, Verdict, VerdictStatus,
)

from . import catalog as cat
from . import mc as mclib
from .base import Budget, McResult, SearchResult
from .templates import get as get_template

SIMPLIFIED = "simplified model, needs precise validation"
CACHE_DIR = Path(os.environ.get("KINETRA_CACHE", Path(__file__).resolve().parents[2] / ".cache"))
CPU_USD_PER_CORE_HOUR = 0.05   # default, unverified (judgment-spec E); editable

P_ROBUST = 0.9                 # below this the nominal optimum is robustified
P_FIX = 0.5                    # a suggested fix must be a MC-verified variant with p_success >= this


class UnsupportedIdea(ValueError):
    """No verified template matches the idea (tier-2 'custom' is not implemented)."""


# --------------------------------------------------------------------------- routing
ROUTES: dict[str, list[str]] = {
    "rocket_car": ["rocket", "thruster", "cold gas", "cold-gas", "roadster", "tesla", "flip", "aerial", "stunt", "car", "jet ", "ramp"],
    "humanoid_jump": ["humanoid", "robot", "unitree", "g1", "biped", "jump", "leap", "dunk", "hop", "land"],
}
_DISCRIMINATORS = {"rocket_car": ["roadster", "tesla", "rocket", "thruster", "car "], "humanoid_jump": ["humanoid", "unitree", "biped", "robot"]}


def route_idea(idea: str, template_id: str | None = None, router: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Keyword routing. ``router`` is an optional LLM hook (off by default); ``template_id`` forces a template."""
    text = " " + re.sub(r"\s+", " ", idea.lower()) + " "
    scores = {t: sorted({k for k in ks if k in text}) for t, ks in ROUTES.items()}
    if template_id:
        return dict(template_id=template_id, method="explicit", matched=scores.get(template_id, []), scores={t: len(v) for t, v in scores.items()})
    if router is not None:
        tid = router(idea)
        return dict(template_id=tid, method="llm_hook", matched=[], scores={t: len(v) for t, v in scores.items()})
    ranked = sorted(scores, key=lambda t: (-(len(scores[t]) + 2 * sum(1 for k in _DISCRIMINATORS[t] if k in text)), t))
    best = ranked[0]
    if not scores[best]:
        raise UnsupportedIdea(f"no verified template matches {idea!r} (templates: {sorted(ROUTES)}); tier-2 custom physics is not implemented")
    return dict(template_id=best, method="keyword_rules", matched=scores[best], scores={t: len(v) for t, v in scores.items()})


# --------------------------------------------------------------------------- bookkeeping
def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if np.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if hasattr(o, "model_dump"):
        return _jsonable(o.model_dump(mode="json"))
    return o


class Steps:
    """Timed log of agent steps in the exact shape of docs/demo-bundle.md."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def run(self, id: str, label: str, tool: str, fn: Callable[[], tuple[str, Any, Any]]) -> Any:
        t0 = time.perf_counter()
        summary, detail, result = fn()
        self.items.append(dict(id=id, label=label, tool=tool, status="done", wall_seconds=round(time.perf_counter() - t0, 4),
                               summary=summary, detail=_jsonable(detail)))
        return result

    def add(self, other: "Steps") -> None:
        self.items.extend(other.items)


# --------------------------------------------------------------------------- core (cacheable) stage
@dataclass
class Core:
    screen: list[NecessaryCheck]
    search: SearchResult
    mc: McResult | None
    mc_nominal: McResult | None
    robust: dict[str, Any] | None
    params: dict[str, float]            # witness (found) or best attempt
    found: bool
    trajectory: Trajectory
    n_evals: int
    wall_seconds: float
    steps: list[dict[str, Any]]
    sanity: bool = False                # search was a short sanity run because the screen failed
    budget: dict[str, float] = field(default_factory=dict)


def _code_version(tpl: Any) -> str:
    h = hashlib.sha256()
    for mod in (inspect.getmodule(tpl), mclib, inspect.getmodule(_code_version)):
        try:
            h.update(Path(inspect.getsourcefile(mod)).read_bytes())  # type: ignore[arg-type]
        except Exception:
            h.update(repr(mod).encode())
    return h.hexdigest()[:16]


def _cache_path(tpl: Any, spec: SpecSheet, seed: int, budget: Budget, robust: bool, search_seeds: int = 3, warm: dict[str, float] | None = None) -> Path:
    key = mclib.canonical_json(dict(v=_code_version(tpl), t=tpl.id, spec=spec.model_dump(mode="json"), seed=seed,
                                    b=[budget.max_evals, budget.max_seconds, budget.mc_samples], r=robust, ss=search_seeds, w=warm))
    return CACHE_DIR / f"core_{tpl.id}_{hashlib.sha256(key.encode()).hexdigest()[:20]}.pkl"


def _mc_evals(res: McResult | None) -> int:
    if res is None:
        return 0
    return res.n + sum(2 * int((s.get("detail") or {}).get("n", 0)) for s in res.sensitivities)


def _tightest_check(checks: list[NecessaryCheck]) -> tuple[NecessaryCheck, float, float]:
    """(check, signed margin, normalised margin); margin<0 iff the check failed (direction-agnostic)."""
    best = None
    for c in checks:
        gap = abs(c.limit - c.measured)
        m = gap if c.passed else -gap
        nm = m / max(abs(c.limit), 1e-9)
        if best is None or nm < best[2]:
            best = (c, m, nm)
    assert best is not None
    return best


def _core(tpl: Any, spec: SpecSheet, seed: int, budget: Budget, robust: bool, use_cache: bool, search_seeds: int = 3, warm: dict[str, float] | None = None) -> tuple[Core, bool]:
    path = _cache_path(tpl, spec, seed, budget, robust, search_seeds, warm)
    if use_cache and path.exists():
        try:
            return pickle.loads(path.read_bytes()), True
        except Exception:
            path.unlink(missing_ok=True)
    steps = Steps()
    t_all = time.perf_counter()
    S = lambda stage: mclib.derive_seed(seed, stage)

    # ---- necessary screen
    def f_screen():
        checks = tpl.necessary_screen(spec)
        failed = [c for c in checks if not c.passed]
        s = ("; ".join(f"{c.name}: {c.measured:g} vs limit {c.limit:g} {c.unit} -> {'PASS' if c.passed else 'FAIL'}" for c in checks))
        return (("Necessary condition violated at favorable assumption bounds — " if failed else "All necessary conditions pass (this proves nothing about feasibility) — ") + s,
                dict(checks=checks, failed=[c.name for c in failed]), checks)

    screen = steps.run("necessary_screen", "Necessary-condition screen", "analytic bounds (favorable assumption end) + MuJoCo inertia", f_screen)
    failed = [c for c in screen if not c.passed]

    # ---- search
    sb = budget
    sanity = bool(failed)
    if sanity:
        sb = Budget(max_evals=min(budget.max_evals, 3000), max_seconds=budget.max_seconds, mc_samples=budget.mc_samples)

    n_attempts = 1 if sanity else max(1, search_seeds)

    def f_search():
        r, tried = None, []
        for a in range(n_attempts):
            ra = tpl.search(spec, S("search") if a == 0 else S(f"search_retry_{a}"), sb)
            tried.append(dict(attempt=a, found=ra.found, n_evals=ra.n_evals, best_cost=round(ra.best_cost, 4)))
            if r is None:
                r = ra
            else:
                best = ra if (ra.found and not r.found) or (ra.found == r.found and ra.best_cost < r.best_cost) else r
                best.n_evals = r.n_evals + ra.n_evals
                best.wall_seconds = r.wall_seconds + ra.wall_seconds
                r = best
            if r.found:
                break
        txt = (f"Witness found after {r.n_evals} evaluations ({r.wall_seconds:.1f} s, {len(tried)} seed attempt(s))." if r.found else
               f"Not found in {r.n_evals} evaluations ({r.wall_seconds:.1f} s, {len(tried)} independent seed attempt(s)); best cost {r.best_cost:.3f}.")
        if sanity:
            txt = "Sanity run only (a necessary condition already failed): " + txt
        return txt, dict(found=r.found, n_evals=r.n_evals, best_cost=r.best_cost, sanity_run=sanity, attempts=tried,
                         **{k: v for k, v in r.detail.items() if k in ("restarts", "log", "failed_checks", "best_metrics", "stopped_by")}), r

    res = steps.run("search", "CMA-ES search", "cma-es + mujoco.rollout (parallel)", f_search)
    params, found = dict(res.best_params), bool(res.found)

    if warm is not None and not sanity:
        def f_warm():
            ok = bool(tpl.judge_nominal(spec, warm))
            if not ok:
                return "Warm-start schedule from a neighbouring variant does not satisfy the success criteria on this variant's nominal model; ignored.", dict(used=False, nominal_ok=False), None
            mw = tpl.monte_carlo(spec, warm, S("mc"), budget.mc_samples)
            if not found:
                return (f"Warm-start schedule from a neighbouring variant IS a nominal witness here (MC {mw.n_success}/{mw.n}); adopted since own search found none.",
                        dict(used=True, nominal_ok=True, mc_success=mw.n_success, n=mw.n, replaced_search_result=False), (warm, True))
            mo = tpl.monte_carlo(spec, params, S("mc"), budget.mc_samples)
            use = mw.n_success > mo.n_success
            return (f"Warm-start schedule from a neighbouring variant is a nominal witness (MC {mw.n_success}/{mw.n}) vs own search result {mo.n_success}/{mo.n}; "
                    + ("adopted." if use else "own result kept."), dict(used=use, nominal_ok=True, mc_success=mw.n_success, own_mc_success=mo.n_success, n=mw.n), (warm, True) if use else None)
        wr = steps.run("warm_start", "Warm start from neighbouring variant", "judge + Monte-Carlo comparison", f_warm)
        if wr is not None:
            params, found = dict(wr[0]), True

    mc_nom: McResult | None = None
    mc_fin: McResult | None = None
    rob_info: dict[str, Any] | None = None
    if found:
        def f_mc():
            r = tpl.monte_carlo(spec, params, S("mc"), budget.mc_samples)
            return (f"Nominal optimum succeeds in {r.n_success}/{r.n} sampled assumption sets; failures: {r.failure_counts or 'none'}.",
                    dict(n=r.n, n_success=r.n_success, failure_counts=r.failure_counts, sensitivities=r.sensitivities, binding=r.binding), r)
        mc_nom = steps.run("monte_carlo", "Monte-Carlo over assumptions", "sampled MuJoCo rollouts (shared mc.py)", f_mc)
        mc_fin = mc_nom
        p_nom = mc_nom.n_success / max(mc_nom.n, 1)
        if robust and hasattr(tpl, "robustify") and p_nom < P_ROBUST:
            def f_rob():
                xr, info = tpl.robustify(spec, params, S("robustify"), Budget(max_evals=budget.max_evals, max_seconds=budget.max_seconds, mc_samples=budget.mc_samples))
                still_ok = tpl.judge_nominal(spec, xr) if hasattr(tpl, "judge_nominal") else True
                r2 = tpl.monte_carlo(spec, xr, S("mc"), budget.mc_samples) if still_ok else None
                p2 = r2.n_success / r2.n if r2 else -1.0
                adopted = bool(r2 is not None and p2 > p_nom)
                info = dict(info, nominal_still_succeeds=bool(still_ok), mc_before=p_nom, mc_after=None if r2 is None else p2, adopted=adopted)
                txt = (f"Second CMA-ES stage on {info.get('train_samples', '?')} perturbed models ({info.get('evals', '?')} evals): held-out MC p "
                       f"{p_nom:.2f} -> {('n/a (robustified schedule no longer succeeds on the nominal model)' if r2 is None else format(p2, '.2f'))}; " + ("robustified schedule adopted." if adopted else "nominal optimum kept."))
                return txt, dict(info, failure_counts=None if r2 is None else r2.failure_counts), (xr, r2, adopted, info)
            xr, r2, adopted, rob_info = steps.run("robustify", "Robustify against assumption spread", "cma-es on perturbed models + held-out MC", f_rob)
            if adopted:
                params, mc_fin = xr, r2
        else:
            steps.run("robustify", "Robustify against assumption spread", "—", lambda: (
                f"Skipped — nominal Monte-Carlo p={p_nom:.2f} is already >= {P_ROBUST:g} or the template has no robustify stage.", dict(skipped=True), None))
    else:
        why = "a necessary condition failed" if failed else "no witness was found"
        steps.run("monte_carlo", "Monte-Carlo over assumptions", "—", lambda: (f"Skipped — {why}; p_success is not computed without a witness.", dict(skipped=True), None))
        steps.run("robustify", "Robustify against assumption spread", "—", lambda: (f"Skipped — {why}.", dict(skipped=True), None))

    def f_traj():
        t = tpl.rollout(spec, params, S("rollout"))
        return f"Replay rollout of the {'witness' if found else 'best attempt (NOT a solution)'}: {t.n_frames} frames.", dict(n_frames=t.n_frames, dt=t.dt), t
    traj = steps.run("rollout", "Export replay trajectory", "mj_step rollout -> Trajectory", f_traj)

    n_evals = res.n_evals + (rob_info or {}).get("evals", 0) + _mc_evals(mc_nom) + (_mc_evals(mc_fin) if mc_fin is not mc_nom else 0)
    core = Core(screen=screen, search=res, mc=mc_fin, mc_nominal=mc_nom, robust=rob_info, params=params, found=found, trajectory=traj,
                n_evals=int(n_evals), wall_seconds=time.perf_counter() - t_all, steps=steps.items, sanity=sanity,
                budget=dict(cma_evals=budget.max_evals, mc_samples=budget.mc_samples, max_seconds=budget.max_seconds))
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(core))
        tmp.replace(path)
    return core, False


# --------------------------------------------------------------------------- verdict construction
def _sensitivities_from_mc(mc: McResult) -> list[Sensitivity]:
    return [Sensitivity(assumption_key=s["assumption_key"], effect=float(s["effect"]), rank=int(s["rank"]), method=s.get("method", "one_at_a_time"))
            for s in mc.sensitivities]


def _screen_sensitivities(tpl: Any, spec: SpecSheet, target: str) -> list[Sensitivity]:
    """One-at-a-time effect of each random assumption (pinned at its 5th/95th percentile) on the normalised margin of the
    tightest necessary check ``target``. Positive effect = raising the assumption from q05 to q95 adds slack."""
    out = []
    for a in spec.assumptions:
        if not mclib.is_random(a):
            continue
        ms = []
        for q in (0.05, 0.95):
            s2 = spec.model_copy(deep=True)
            for b in s2.assumptions:
                if b.key == a.key:
                    b.value = mclib.quantile(a, q)
                    b.distribution = Fixed()
            chk = [c for c in tpl.necessary_screen(s2) if c.name == target]
            c = chk[0]
            gap = abs(c.limit - c.measured)
            ms.append((gap if c.passed else -gap) / max(abs(c.limit), 1e-9))
        out.append((a.key, ms[1] - ms[0]))
    out.sort(key=lambda t: -abs(t[1]))
    return [Sensitivity(assumption_key=k, effect=round(e, 5), rank=i + 1, method="one_at_a_time_screen_margin") for i, (k, e) in enumerate(out)]


def _fmt_p(v: float) -> str:
    return f"{100 * v:.0f}"


def _human_review(spec: SpecSheet, sens: list[Sensitivity], status: VerdictStatus, p_success: float | None = None) -> HumanReview:
    top = {s.assumption_key: s for s in sens[:3]}
    items: list[ReviewItem] = []
    for a in spec.assumptions:
        low = a.confidence.value == "low"
        unverified = a.source.startswith(("unverified", "llm_estimate", "default"))
        if low or a.key in top:
            bits = []
            if low:
                bits.append(f"Low-confidence assumption (source: {a.source[:90]})")
            elif unverified:
                bits.append("Assumed value, not sourced")
            if a.key in top:
                bits.append(f"top-{top[a.key].rank} sensitivity ({top[a.key].effect:+.3f}, {top[a.key].method})")
            items.append(ReviewItem(assumption_key=a.key, reason="; ".join(bits) + ".", severity="warn" if low else "info"))
    if status == VerdictStatus.FEASIBLE_FOUND and p_success is not None and p_success < 0.5:
        items.append(ReviewItem(assumption_key=sens[0].assumption_key if sens else None,
                                reason=f"fragile: p_success {_fmt_p(p_success)}% — a witness exists on the nominal model but works in fewer than half of the sampled assumption sets"
                                       + (f"; dominated by {sens[0].assumption_key}" if sens else "") + ".", severity="warn"))
    if status == VerdictStatus.NOT_FOUND_IN_BUDGET:
        items.append(ReviewItem(assumption_key=None, reason="Weak outcome: search budget, not physics, may be the limit; review assumptions or enlarge the budget.", severity="warn"))
    return HumanReview(required=any(i.severity == "warn" for i in items), items=items)


def _cost_estimate(tid: str, n_evals: int, wall: float, n_conditions: int) -> CostEstimate:
    """Sim cost measured. Physical-equivalent only from SOURCED unit prices (costs.json); unpriced items are omitted entirely."""
    costs = cat.costs()
    low = high = 0.0
    srcs: list[str] = []
    basis: list[str] = []
    for eq in costs["template_equivalents"].get(tid, []):
        it = costs["items"][eq["item"]]
        if it["unit_usd_low"] is None or it["unit_usd_high"] is None or not str(it["status"]).startswith("sourced"):
            continue
        q = int(np.ceil(n_conditions / eq["conditions_per_test"]))
        low += q * it["unit_usd_low"]
        high += q * it["unit_usd_high"]
        srcs.append(it["source_url"])
        basis.append(f"{q} x {eq['name']}")
    phys = None
    if srcs:
        phys = PhysicalEquivalentEstimate(is_estimate=True, low_usd=low, high_usd=high,
                                          basis="ESTIMATE — order of magnitude, not a quote: " + ", ".join(basis), sources=srcs)
    return CostEstimate(sim_cost=SimCost(n_evals=int(n_evals), wall_seconds=round(float(wall), 3)), physical_equivalent_estimate=phys)


def headline(v: Verdict, control_label: str = "", control_value: float | None = None, unit: str = "") -> str:
    """One-line headline generated from Verdict fields by code (never by an LLM)."""
    head = f"{control_label} {control_value:g} {unit}: ".replace("  ", " ") if control_value is not None else ""
    f = v.feasibility
    if v.status == VerdictStatus.FEASIBLE_FOUND:
        return head + f"FOUND — works in {_fmt_p(f.p_success)}% of sampled assumption sets (95% CI {_fmt_p(f.ci_low)}–{_fmt_p(f.ci_high)}%, n={f.n_samples})"
    if v.status == VerdictStatus.INFEASIBLE_NECESSARY_CONDITION:
        c = next(c for c in v.necessary_checks if not c.passed)
        return head + f"IMPOSSIBLE within assumptions — {c.name} needs {c.measured:g} {c.unit}, at most {c.limit:g} {c.unit} available"
    if v.status == VerdictStatus.NOT_FOUND_IN_BUDGET:
        return head + f"NOT FOUND in {v.cost_estimate.sim_cost.n_evals if v.cost_estimate else '?'} evaluations (weak evidence, not proof)"
    return head + "MODEL INVALID — no verdict"


def _search_failure_text(core: Core) -> str:
    d = core.search.detail
    fc = d.get("failed_checks") or []
    return ("; best attempt fails: " + ", ".join(fc)) if fc else ""


def make_verdict(tpl: Any, spec: SpecSheet, core: Core, seed: int, budget: Budget, fix: SuggestedFix | None, total_evals: int,
                 total_wall: float, bom: list) -> tuple[Verdict, str]:
    """Returns (Verdict, taxonomy failure class)."""
    failed = [c for c in core.screen if not c.passed]
    labels = list(dict.fromkeys([SIMPLIFIED] + list(getattr(tpl, "model_labels", []))))
    classes = getattr(tpl, "necessary_classes", {})
    phrase = getattr(tpl, "success_phrase", "the stated goal")
    sens: list[Sensitivity] = []
    binding: BindingConstraint | None = None
    best_params: dict[str, float] = {}
    n_cond = (core.mc.n if core.mc else 0) + core.n_evals // 10
    tight, tmargin, _ = _tightest_check(core.screen)
    p_info = dict(p_success=0.0, ci_low=0.0, ci_high=1.0, n_samples=0, ci_method="not_computed (no witness found)")

    if failed and core.found:
        status = VerdictStatus.MODEL_INVALID
        fclass = "MODEL_INVALID"
        summary = (f"The model gave inconsistent answers: the necessary check '{failed[0].name}' failed at favorable bounds, yet the search found a witness on the "
                   "nominal model. The simulation model was not valid, so no feasibility verdict is given. This is a tooling problem, not a physical finding.")
        best_params = {}
    elif failed:
        status = VerdictStatus.INFEASIBLE_NECESSARY_CONDITION
        c = max(failed, key=lambda c: (c.measured / c.limit) if c.limit else np.inf)
        fclass = classes.get(c.name, "ACTUATOR_SATURATION")
        ratio = c.measured / c.limit if c.limit else float("inf")
        summary = (f"Impossible within the stated assumptions: '{c.name}' requires {c.measured:g} {c.unit} but at most {c.limit:g} {c.unit} is available, even at the "
                   f"favorable end of the assumptions (shortfall factor {ratio:.2f}x). [{fclass}] {c.note.split(';')[0]}. {SIMPLIFIED.capitalize()}.")
        binding = BindingConstraint(name=c.name, margin=round(tmargin if tight.name == c.name else -abs(c.limit - c.measured), 5), unit=c.unit,
                                    sensitivities=_screen_sensitivities(tpl, spec, c.name))
        sens = binding.sensitivities
    elif core.found and core.mc is not None:
        status = VerdictStatus.FEASIBLE_FOUND
        pf = mclib.feasibility_fields(core.mc)
        p_info = pf
        fclass = "ASSUMPTION_FRAGILE" if pf["p_success"] < 0.5 else "NONE"
        best_params = dict(core.params)
        sens = _sensitivities_from_mc(core.mc)
        b = core.mc.binding or {}
        binding = BindingConstraint(name=str(b.get("name", "unknown")), margin=float(b.get("margin", 0.0)), unit=str(b.get("unit", "")), sensitivities=sens)
        summary = (f"A parameter set achieving {phrase} was found within the stated assumptions (nominal model, {core.search.n_evals} search evaluations); "
                   f"it succeeds in {_fmt_p(pf['p_success'])}% of sampled assumption sets (95% CI {_fmt_p(pf['ci_low'])}–{_fmt_p(pf['ci_high'])}%, n={pf['n_samples']}).")
        if fclass == "ASSUMPTION_FRAGILE":
            top = sens[0].assumption_key if sens else "the assumptions"
            summary += f" It works in fewer than half of the sampled cases; the outcome is dominated by {top}."
        if core.mc.failure_counts:
            summary += " Failures when it fails: " + ", ".join(f"{k} ({v})" for k, v in sorted(core.mc.failure_counts.items(), key=lambda kv: -kv[1])[:3]) + "."
        summary += f" Proved by simulation under assumptions only; {SIMPLIFIED}."
    else:
        status = VerdictStatus.NOT_FOUND_IN_BUDGET
        fclass = "SEARCH_BUDGET_EXHAUSTED"
        d = core.search.detail
        sens = _screen_sensitivities(tpl, spec, tight.name)
        b = d.get("binding") or dict(name=tight.name, margin=tmargin, unit=tight.unit)
        binding = BindingConstraint(name=str(b["name"]), margin=float(b["margin"]), unit=str(b.get("unit", "")), sensitivities=sens)
        summary = (f"Not found: no solution was found in {core.search.n_evals} evaluations, and no necessary condition was violated. This is weak evidence only, "
                   f"not proof; a larger search or a different control strategy might still succeed{_search_failure_text(core)}. [{fclass}]")

    spec_hash = mclib.spec_hash(spec)
    try:
        pv = _md.version("physlab-core")
    except Exception:
        pv = "0.1.0"
    versions = {"mujoco": __import__("mujoco").__version__, "cma": __import__("cma").__version__, "physlab_core": pv}
    v = Verdict(
        status=status, summary=summary, feasibility=Feasibility(**p_info), necessary_checks=core.screen, binding_constraint=binding,
        best_params=best_params, suggested_fix=fix, bom=bom,
        cost_estimate=_cost_estimate(spec.template_id.value, total_evals, total_wall, n_cond), model_labels=labels,
        human_review=_human_review(spec, sens, status, p_info['p_success'] if status == VerdictStatus.FEASIBLE_FOUND else None),
        reproducibility=Reproducibility(seed=int(seed), versions=versions,
                                        search_budget=dict(cma_evals=budget.max_evals, mc_samples=budget.mc_samples, max_seconds=budget.max_seconds),
                                        spec_hash=spec_hash),
    )
    return v, fclass


def build_fix(key: str, unit: str, cur: float, candidates: list[dict[str, Any]], threshold: float = P_FIX) -> SuggestedFix | None:
    """Smallest swept control value (ascending ``candidates`` of {value, found, p_success, n, n_evals}) whose Monte-Carlo-verified
    p_success >= ``threshold``. Produced by the sweep, never by an LLM; ``verified`` is true only because p_success was computed."""
    tested = sorted(float(c["value"]) for c in candidates)
    for c in sorted(candidates, key=lambda c: c["value"]):
        if c["value"] > cur and c.get("found") and c.get("p_success") is not None and c["p_success"] >= threshold:
            p = float(c["p_success"])
            return SuggestedFix(
                changes=[ParamChange(param=key, from_value=float(cur), to_value=float(c["value"]), unit=unit)],
                rationale=(f"Optimizer sweep of {key} over {tested} {unit} (ascending): the smallest tested value whose Monte-Carlo-verified p_success is >= {threshold:g} "
                           f"is {c['value']:g} {unit} (p_success {_fmt_p(p)}%, n={c.get('n', '?')}, {c.get('n_evals', '?')} evaluations): {cur:g} -> {c['value']:g} {unit}. "
                           "Found by search; not unique; the grid is coarse, so the true minimum may lie between tested values."),
                verified=True, verified_p_success=p)
    return None


# --------------------------------------------------------------------------- the run
@dataclass
class PipelineRun:
    idea: str
    template_id: str
    seed: int
    budget: Budget
    spec: SpecSheet
    verdict: Verdict
    trajectory: Trajectory
    agent_steps: list[dict[str, Any]]
    route: dict[str, Any]
    failure_class: str
    core: Core
    fix_candidates: list[dict[str, Any]] = field(default_factory=list)
    total_wall_seconds: float = 0.0
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(idea=self.idea, template_id=self.template_id, seed=self.seed, route=self.route, failure_class=self.failure_class,
                    spec=self.spec.model_dump(mode="json"), verdict=self.verdict.model_dump(mode="json"),
                    trajectory=self.trajectory.model_dump(mode="json"), agent_steps=self.agent_steps,
                    fix_candidates=self.fix_candidates, total_wall_seconds=self.total_wall_seconds)


def run(idea: str, template_id: str | None = None, overrides: dict[str, float] | None = None, seed: int | None = None,
        budget: Budget | None = None, *, fix: bool = True, fix_values: list[float] | None = None, robust: bool = True,
        use_cache: bool = False, search_seeds: int = 3, warm_params: dict[str, float] | None = None, router: Callable[[str], str] | None = None) -> PipelineRun:
    """Execute the pipeline. ``seed=None`` derives it from the default spec (judgment-spec R6)."""
    budget = budget or Budget()
    steps = Steps()
    t_run = time.perf_counter()

    route = steps.run("route", "Route idea to a physics template", "keyword rules (LLM hook: off)", lambda: (
        "", None, route_idea(idea, template_id, router)))
    tid = route["template_id"]
    steps.items[-1]["summary"] = (f"Template '{tid}' via {route['method']}" + (f" (matched: {', '.join(route['matched'])})" if route["matched"] else "") +
                                  f"; keyword scores {route['scores']}.")
    steps.items[-1]["detail"] = _jsonable(route)
    tpl = get_template(tid)

    def f_research():
        ents = cat.lookup(tid)
        rows = [e for e in ents.values() if e]
        nv = sum(1 for e in rows if e.get("verified"))
        meta = cat.catalog_meta(tid)
        return (f"{len(rows)} curated catalog entries ({nv} verified, {len(rows) - nv} unverified/unknown) from the offline catalog v{meta['catalog_version']}. "
                "This is a curated, cited catalog — NOT live web research.", dict(catalog=meta, entries=rows), rows)
    steps.run("research", "Research (curated catalog lookup)", "catalog.lookup (offline JSON, cited)", f_research)

    def f_assump():
        s = tpl.default_spec(idea, overrides)
        n_low = sum(1 for a in s.assumptions if a.confidence.value == "low")
        return (f"{len(s.assumptions)} assumptions ({n_low} low-confidence), {len(s.param_bounds)} search parameters, {len(s.success_criteria)} success criteria"
                + (f"; overrides {overrides}" if overrides else "") + ".",
                dict(assumptions=[dict(key=a.key, value=a.value, unit=a.unit, distribution=a.distribution.model_dump(), source=a.source,
                                       confidence=a.confidence.value) for a in s.assumptions], overrides=overrides or {}), s)
    spec = steps.run("assumptions", "Assumptions panel (SpecSheet)", "template.default_spec", f_assump)
    seed = int(seed if seed is not None else mclib.spec_seed(spec))

    def f_model():
        info = tpl.model_info(spec) if hasattr(tpl, "model_info") else {}
        return "MuJoCo model compiled" + (f": {info}" if info else "") + ".", info, info
    steps.run("build_model", "Build MuJoCo model", "mujoco.MjModel.from_xml", f_model)

    core, hit = _core(tpl, spec, seed, budget, robust, use_cache, search_seeds, warm_params)
    steps.add(_Steps(core.steps))

    # ---- fix search
    fix_obj: SuggestedFix | None = None
    fix_cands: list[dict[str, Any]] = []
    extra_evals, extra_wall = 0, 0.0
    status_now_found = core.found and not [c for c in core.screen if not c.passed] and core.mc is not None

    def f_fix():
        nonlocal fix_obj, extra_evals, extra_wall
        ctrl = tpl.fix_control(spec) if hasattr(tpl, "fix_control") else None
        if not fix or ctrl is None:
            return "Skipped — " + ("disabled." if not fix else "template has no user-facing fix control."), dict(skipped=True), None
        if status_now_found and core.mc is not None and core.mc.n_success / max(core.mc.n, 1) >= P_FIX:
            return "Skipped — a feasible configuration was already found; no fix needed.", dict(skipped=True), None
        key = ctrl["key"]
        cur = next(a.value for a in spec.assumptions if a.key == key)
        vals = sorted(v for v in (fix_values or ctrl["values"]) if v > cur)
        base_over = dict(overrides or {})
        prev = warm_params
        prev_v = cur
        for v in vals:
            sub_spec = tpl.default_spec(idea, {**base_over, key: v})
            w = tpl.rescale_params(prev, prev_v, v) if (prev is not None and hasattr(tpl, "rescale_params")) else None
            c2, hit2 = _core(tpl, sub_spec, seed, budget, robust, use_cache, search_seeds, w)
            ok = bool(c2.found and c2.mc is not None and all(c.passed for c in c2.screen))
            p = c2.mc.n_success / c2.mc.n if (ok and c2.mc and c2.mc.n) else None
            if ok:
                prev, prev_v = c2.params, v
            extra_evals += c2.n_evals
            extra_wall += c2.wall_seconds
            fix_cands.append(dict(value=v, found=ok, p_success=p, n=(c2.mc.n if ok and c2.mc else 0), n_evals=c2.n_evals,
                                  wall_seconds=round(c2.wall_seconds, 3), cache_hit=hit2, screen_failed=[c.name for c in c2.screen if not c.passed]))
            if p is not None and p >= P_FIX:
                break
        fix_obj = build_fix(key, ctrl["unit"], float(cur), fix_cands)
        if fix_obj is None:
            return (f"No tested {key} value in {[float(c['value']) for c in fix_cands]} {ctrl['unit']} gave a verified variant with p_success >= {P_FIX:g} "
                    "(weak: only these values and this budget were tried).", dict(candidates=fix_cands, threshold=P_FIX), None)
        return (f"Smallest tested {key} with MC-verified p_success >= {P_FIX:g}: {fix_obj.changes[0].to_value:g} {ctrl['unit']} "
                f"(p_success {_fmt_p(fix_obj.verified_p_success or 0)}%, after {len(fix_cands)} sweep variant(s)).", dict(candidates=fix_cands, threshold=P_FIX), None)
    steps.run("fix_search", "Optimizer-found fix (control sweep)", "sweep + cma-es + Monte-Carlo verification", f_fix)

    def f_bom():
        items = tpl.bom(spec, core.params) if core.params else []
        priced = [i for i in items if i.unit_cost_usd is not None]
        return (f"{len(items)} BOM lines ({len(priced)} priced; unpriced lines have no sourced cost).",
                dict(items=items, label="Costs are estimates, see cost_estimate methodology."), items)
    bom = steps.run("bom", "Bill of materials", "template.bom", f_bom)

    total_evals = core.n_evals + extra_evals
    total_wall = core.wall_seconds + extra_wall   # measured wall time of the compute (cached cores report their original time)
    verdict, fclass = make_verdict(tpl, spec, core, seed, budget, fix_obj, total_evals, total_wall, bom)
    return PipelineRun(idea=idea, template_id=tid, seed=seed, budget=budget, spec=spec, verdict=verdict, trajectory=core.trajectory,
                       agent_steps=steps.items, route=route, failure_class=fclass, core=core, fix_candidates=fix_cands,
                       total_wall_seconds=time.perf_counter() - t_run, cache_hit=hit)


class _Steps(Steps):
    def __init__(self, items: list[dict[str, Any]]):
        self.items = list(items)
