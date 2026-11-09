"""Fast tests for the rocket_car template, shared MC and the pipeline's verdict-status rules."""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from physlab_core.schemas import NecessaryCheck, SpecSheet, Trajectory, Verdict, VerdictStatus

from kinetra_engine import mc as mclib
from kinetra_engine import pipeline
from kinetra_engine.base import Budget
from kinetra_engine.catalog import lookup
from kinetra_engine.templates import get as get_template
from kinetra_engine.templates import rocket_car as rc

IDEA = "Tesla Roadster rocket-thruster aerial roll and pitch rotation"
SMALL = Budget(max_evals=1500, max_seconds=30.0, mc_samples=24)


@pytest.fixture(scope="module")
def tpl():
    return get_template("rocket_car")


@pytest.fixture(scope="module")
def spec(tpl):
    return tpl.default_spec(IDEA)


# ------------------------------------------------------------------ MC
def test_wilson_ci_sanity():
    for k, n in [(0, 10), (10, 10), (3, 10), (83, 100), (1, 500)]:
        lo, hi = mclib.wilson_ci(k, n)
        assert 0 <= lo <= k / n <= hi <= 1
    lo, hi = mclib.wilson_ci(83, 100)
    assert 0.74 < lo < 0.76 and 0.88 < hi < 0.90      # spike REPORT: 0.74-0.89
    assert mclib.wilson_ci(0, 0) == (0.0, 1.0)
    # CP is wider than or equal to Wilson on the same data (conservative)
    wl, wh = mclib.wilson_ci(8, 40)
    cl, ch = mclib.clopper_pearson_ci(8, 40)
    assert cl <= wl + 1e-9 and ch >= wh - 1e-9
    assert mclib.clopper_pearson_ci(0, 20)[0] == 0.0 and mclib.clopper_pearson_ci(20, 20)[1] == 1.0


def test_sampler_deterministic_clipped_and_independent(spec):
    a = mclib.sample_assumptions(spec, 200, 11, rc.aux_jitter)
    b = mclib.sample_assumptions(spec, 200, 11, rc.aux_jitter)
    c = mclib.sample_assumptions(spec, 200, 12, rc.aux_jitter)
    assert all(np.array_equal(a[k], b[k]) for k in a)
    assert not np.array_equal(a["vehicle_mass"], c["vehicle_mass"])
    assert a["vehicle_mass"].min() >= 1235.0 and a["vehicle_mass"].max() <= 1365.0       # uniform +-5%
    assert np.all(a["thruster_force_max"] == 5000.0)                                       # fixed
    assert a["com_offset_x"].min() >= -0.15 and a["com_offset_x"].max() <= 0.15           # uniform
    # each assumption has its own stream: dropping another one does not move this one
    assert np.array_equal(mclib.sample_assumption(spec.assumptions[1], 200, 11), a["vehicle_mass"])


# ------------------------------------------------------------------ spec / registry / catalog
def test_spec_validates_and_overrides(tpl):
    s = tpl.default_spec(IDEA, {"thruster_force_max": 2000.0})
    SpecSheet.model_validate(s.model_dump(mode="json"))
    assert {a.key: a.value for a in s.assumptions}["thruster_force_max"] == 2000.0
    assert len(s.param_bounds) == 21
    with pytest.raises(ValueError):
        tpl.default_spec(IDEA, {"nope": 1.0})


def test_registry_lazy_import():
    from kinetra_engine import templates
    assert "rocket_car" in templates.available()
    with pytest.raises(KeyError):
        templates.get("does_not_exist")


def test_catalog_cited_and_flagged():
    ents = lookup("rocket_car")
    assert ents["isp_cold_gas_n2"]["verified"] is False
    assert all(e["source_url"] or e["verified"] is False for e in ents.values())
    assert lookup("rocket_car", ["missing_key"]) == {"missing_key": None}


# ------------------------------------------------------------------ routing
def test_routing():
    assert pipeline.route_idea("a humanoid robot jumps over a fence")["template_id"] == "humanoid_jump"
    assert pipeline.route_idea("Tesla Roadster does a flip with rocket thrusters")["template_id"] == "rocket_car"
    with pytest.raises(pipeline.UnsupportedIdea):
        pipeline.route_idea("bake a sourdough loaf")


# ------------------------------------------------------------------ verdict-status rules
def test_failed_necessary_check_never_feasible(tpl):
    r = pipeline.run(IDEA, "rocket_car", {"thruster_force_max": 300.0}, 5, SMALL, fix=False)
    v = r.verdict
    assert v.status == VerdictStatus.INFEASIBLE_NECESSARY_CONDITION
    assert any(not c.passed for c in v.necessary_checks)
    assert v.best_params == {} and v.suggested_fix is None
    Verdict.model_validate(v.model_dump(mode="json"))
    Trajectory.model_validate(r.trajectory.model_dump(mode="json"))
    ids = [s["id"] for s in r.agent_steps]
    assert ids[:5] == ["route", "research", "assumptions", "build_model", "necessary_screen"]
    assert {"search", "monte_carlo", "robustify", "fix_search", "bom"} <= set(ids)
    assert all(s["status"] == "done" and s["wall_seconds"] >= 0 for s in r.agent_steps)
    # the schema itself refuses FEASIBLE_FOUND with a failed check
    bad = v.model_dump(mode="json")
    bad["status"] = "FEASIBLE_FOUND"
    bad["best_params"] = {"x": 1.0}
    with pytest.raises(ValidationError):
        Verdict.model_validate(bad)


def test_not_found_wording_is_weak():
    r = pipeline.run(IDEA, "rocket_car", {"thruster_force_max": 3000.0}, 5, Budget(max_evals=400, max_seconds=20.0, mc_samples=16), fix=False)
    v = r.verdict
    assert v.status == VerdictStatus.NOT_FOUND_IN_BUDGET, v.summary
    low = v.summary.lower()
    assert "not found" in low and "weak evidence" in low and "evaluations" in low
    for banned in ("impossible", "cannot", "infeasible"):
        assert banned not in low
    assert v.feasibility.n_samples == 0 and v.best_params == {}
    assert pipeline.headline(v).startswith("NOT FOUND")


def test_feasible_found_pipeline_and_determinism():
    kw = dict(overrides={"thruster_force_max": 10000.0}, seed=20260001, budget=Budget(max_evals=20000, max_seconds=60.0, mc_samples=40), fix=False, robust=False)
    r1 = pipeline.run(IDEA, "rocket_car", **kw)
    r2 = pipeline.run(IDEA, "rocket_car", **kw)
    assert r1.verdict.status == VerdictStatus.FEASIBLE_FOUND, r1.verdict.summary
    assert r1.verdict.best_params == r2.verdict.best_params                      # same seed -> same params
    assert r1.verdict.feasibility == r2.verdict.feasibility
    assert r1.verdict.summary == r2.verdict.summary
    v = r1.verdict
    Verdict.model_validate(v.model_dump(mode="json"))
    SpecSheet.model_validate(r1.spec.model_dump(mode="json"))
    t = Trajectory.model_validate(r1.trajectory.model_dump(mode="json"))
    f = v.feasibility
    assert f.ci_low <= f.p_success <= f.ci_high and f.n_samples == 40
    assert all(c.passed for c in v.necessary_checks)
    assert v.binding_constraint is not None and v.binding_constraint.sensitivities
    assert "simplified model, needs precise validation" in v.model_labels
    assert v.cost_estimate and v.cost_estimate.sim_cost.n_evals > 0
    assert v.cost_estimate.physical_equivalent_estimate is None                  # no sourced per-test price -> omitted, not invented
    assert v.reproducibility.spec_hash == mclib.spec_hash(r1.spec)
    # replay convention (web): thr_<name> bodies parented to the chassis + thrust_<name> series
    names = [b.name for b in t.bodies]
    assert names[0] == "chassis" and "thr_nose_dn" in names
    assert {s.name for s in t.series} >= {"thrust_nose_dn", "pitch_deg"}
    pitch = next(x for x in t.series if x.name == "pitch_deg").values
    roll = next(x for x in t.series if x.name == "roll_deg").values
    assert max(abs(v) for v in pitch) >= 340 and max(abs(v) for v in roll) >= 340     # the witness really turns a full pitch AND a full roll
    assert "thr_side_fl_up" in names and "thrust_side_fl_up" in {s.name for s in t.series} and len(t.bodies) == 1 + 4 + rc.K
    assert t.dt == pytest.approx(0.02) and t.n_frames <= 60 * 4.6 + 1
    assert any(e.kind == "landing" for e in t.events)


def test_search_deterministic(tpl, spec):
    s2 = tpl.default_spec(IDEA, {"thruster_force_max": 10000.0})
    a = tpl.search(s2, 3, Budget(max_evals=300, max_seconds=30.0))
    b = tpl.search(s2, 3, Budget(max_evals=300, max_seconds=30.0))
    assert a.best_params == b.best_params and a.n_evals == b.n_evals


def test_necessary_screen_monotone(tpl):
    ok = lambda f: all(c.passed for c in tpl.necessary_screen(tpl.default_spec(IDEA, {"thruster_force_max": f})))
    assert not ok(300.0) and ok(3000.0) and ok(5000.0)


def test_criteria_require_both_rotations(tpl):
    names = {c.name for c in tpl.default_spec(IDEA).success_criteria}
    assert {"full_pitch_turn", "full_roll_turn", "upright_at_touchdown", "upright_settle", "touchdown_roll_rate"} <= names
    sim = tpl._sim(tpl.default_spec(IDEA))
    env = tpl._env_nom(tpl.default_spec(IDEA))
    m, _, _ = sim.evaluate_nominal(np.zeros((1, rc.NPARAM)), env)          # no burn at all: no rotation, so neither turn criterion holds
    assert not m["success"][0] and not m["ok"]["pitch_turn"][0] and not m["ok"]["roll_turn"][0]
    assert abs(m["pitch_turn"][0]) < 0.5 and abs(m["roll_turn"][0]) < 0.5


def test_roll_screen_proves_tiny_roll_authority_infeasible(tpl):
    spec = tpl.default_spec(IDEA, {"thruster_force_max": 5000.0})
    assert all(c.passed for c in tpl.necessary_screen(spec))
    lv = dict(rc._levers(1235.0))
    lv["tau_x"] = lv["tau_x"] * 0.003                                        # keep every pitch lever, shrink only the roll lever arm
    t_roll = rc._axis_time(lv, "x", 5000.0, {+1: float(rc.TURN_MIN), -1: float(rc.TURN_MIN)}, 3.0)["t_min"]
    t_pitch = rc._axis_time(lv, "y", 5000.0, {+1: float(rc.TURN_MIN), -1: float(rc.TURN_MIN)}, 3.0)["t_min"]
    t_ub = rc.screen_bounds(1235.0, 5000.0, 70.0, 60.0, 2.2, 22.0 * 1.05, np.deg2rad(25.0), 3.0, 3.0)["T_ub"]
    assert t_roll > t_ub > t_pitch                                          # only the roll check would fail
    # and with all nozzles tiny the real screen fails on the roll check by name
    weak = tpl.necessary_screen(tpl.default_spec(IDEA, {"thruster_force_max": 150.0}))
    assert not next(c for c in weak if c.name == "roll_time_vs_air_time").passed


def test_rollout_matches_judge_rotation_metrics(tpl):
    spec = tpl.default_spec(IDEA, {"thruster_force_max": 10000.0})
    r = tpl.search(spec, mclib.derive_seed(20260001, "search"), Budget(max_evals=20000, max_seconds=120.0))
    assert r.found
    sim, env = tpl._sim(spec), tpl._env_nom(spec)
    m, _, _ = sim.evaluate_nominal(rc.params_to_x(r.best_params)[None], env)
    t = tpl.rollout(spec, r.best_params, 1)
    ser = {s.name: s.values for s in t.series}
    itd = int(m["itd"][0])
    f = itd // 5
    assert abs(ser["pitch_deg"][f]) == pytest.approx(abs(np.degrees(m["pitch_turn"][0])), abs=8.0)
    assert abs(ser["roll_deg"][f]) == pytest.approx(abs(np.degrees(m["roll_turn"][0])), abs=8.0)
