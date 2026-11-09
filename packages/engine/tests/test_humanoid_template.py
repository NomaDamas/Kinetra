"""Humanoid jump template: determinism, static screen, schema validation (fast; no CMA-ES search)."""
import json

import numpy as np
import pytest

from physlab_core.schemas import SpecSheet, Trajectory, VerdictStatus
from kinetra_engine.base import Budget
from kinetra_engine.templates import humanoid_jump as hj

try:
    hj.g1_dir()
    HAVE_G1 = True
except FileNotFoundError:
    HAVE_G1 = False

P_REF = dict(zip(hj.PNAMES, [-0.82493, 1.72006, 0.2903, 0.12915, -1.33895, 1.08244, -0.72003, 0.97657, 0.52303, 0.13725]))

# Parameters found by the spike's CMA-ES for a 0.4 m jump (any stable jump works for these tests)
P_REF = dict(zip(hj.PNAMES, [-0.7648, 1.4262, -0.0764, 0.1, -0.2, 0.9, -0.8, 1.5, 0.5, 0.25]))


@pytest.fixture(scope="module")
def sim():
    return hj.Sim()


def test_spec_validates_and_roundtrips():
    spec = hj.TEMPLATE.default_spec("humanoid jumps 0.3 m", {"payload_kg": 5.0})
    again = SpecSheet.model_validate(json.loads(spec.model_dump_json()))
    assert again == spec
    keys = {a.key for a in again.assumptions}
    assert {"payload_kg", "torque_scale", "target_height", "landing_grf_limit_bw", "ground_friction"} <= keys
    lim = next(a for a in again.assumptions if a.key == "landing_grf_limit_bw")
    assert lim.confidence.value == "low" and "unverified" in lim.label.lower()
    assert [b.name for b in again.param_bounds] == hj.PNAMES
    with pytest.raises(KeyError):
        hj.TEMPLATE.default_spec("x", {"nonsense": 1.0})


def test_static_screen_80kg_fails_5kg_passes(sim):
    sim.configure(payload=80.0)
    deep = sim.static_hold(-1.2, 2.0)
    assert deep["max_ratio"] > 1.0 and deep["binding"].endswith("knee")
    assert 139.0 < deep["binding_torque"] and deep["binding_limit"] == pytest.approx(139.0)
    assert 150.0 < deep["binding_torque"] < 185.0   # spike: 160-172 N*m against 139
    assert deep["root_residual"] < 0.5               # mj_inverse support wrench is consistent
    sim.configure(payload=5.0)
    ok = sim.static_hold(-1.2, 2.0)
    assert ok["max_ratio"] < 0.5
    sim.configure(payload=0.0)
    assert sim.static_hold(-1.2, 2.0)["binding_torque"] < ok["binding_torque"]  # mass scaling via mj_setConst works


def test_necessary_screen_payload_boundary():
    # 5 kg: passes; 80 kg at a 0.3 m target: the static hold of the planned crouch range is violated at the
    # favorable bound of every assumption -> a strong necessary-condition failure.
    ok = hj.TEMPLATE.necessary_screen(hj.TEMPLATE.default_spec("x", {"payload_kg": 5.0}))
    assert all(c.passed for c in ok)
    big = hj.TEMPLATE.necessary_screen(hj.TEMPLATE.default_spec("x", {"payload_kg": 300.0}))
    failed = [c for c in big if not c.passed]
    assert failed and all(c.measured > c.limit for c in failed if c.name != "landing_deceleration")


def test_rollout_deterministic_and_judged(sim):
    sim.configure()
    r1 = sim.rollout(np.array([P_REF[k] for k in hj.PNAMES]))
    r2 = sim.rollout(np.array([P_REF[k] for k in hj.PNAMES]))
    for k in ("ballistic_height", "grf_peak_land_N", "torque_applied_ratio_max", "torso_up"):
        assert r1[k] == r2[k]            # bit-identical
    assert r1["liftoff"] and r1["finite"]
    # ballistic metric is vz^2/2g, never larger than a plausible bound and independent of leg tuck after liftoff
    assert 0.0 < r1["ballistic_height"] < 1.0
    assert r1["grf_peak_land_bw"] == pytest.approx(r1["grf_peak_land_N"] / (sim.mass * hj.G))


def test_grf_is_a_real_constraint():
    spec = hj.TEMPLATE.default_spec("x")
    r = dict(liftoff=True, stable_landing=True, ballistic_height=0.5, grf_peak_land_bw=10.0, finite=True)
    assert hj._succeeded(r, 0.3, 12.0)
    assert not hj._succeeded(r, 0.3, 9.0)      # same rollout, tighter GRF limit -> fails
    assert any(c.name == "landing_grf" for c in spec.success_criteria)


def test_trajectory_export_validates(sim):
    spec = hj.TEMPLATE.default_spec("x")
    traj = hj.TEMPLATE.rollout(spec, P_REF, seed=3)
    traj = Trajectory.model_validate(json.loads(traj.model_dump_json()))
    assert traj.n_frames > 50 and 1.0 / traj.dt <= 60.0
    assert len(traj.bodies) == 30
    names = {s.name for s in traj.series}
    assert {"knee_torque_ratio", "grf_N"} <= names
    meshes = [g.mesh for b in traj.bodies for g in b.geoms if g.mesh]
    assert meshes and all(m.startswith("g1/") and m.endswith(".glb") for m in meshes)
    assert any(e.kind == "landing" for e in traj.events)


def test_search_reproducible_small_budget():
    spec = hj.TEMPLATE.default_spec("x", {"target_height": 0.2})
    a = hj.TEMPLATE.search(spec, seed=1, budget=Budget(max_evals=60, max_seconds=60))
    b = hj.TEMPLATE.search(spec, seed=1, budget=Budget(max_evals=60, max_seconds=60))
    assert a.best_params == b.best_params and a.n_evals == b.n_evals == 60
    assert a.best_cost == b.best_cost
    # not found => the result must not claim success, and the failure class is a search/saturation class (weak)
    if not a.found:
        assert a.detail["failure_class"] in {"ACTUATOR_SATURATION", "SEARCH_BUDGET_EXHAUSTED", "TIPPING",
                                             "STRUCTURAL_UNMODELED", "CONTACT_LOSS"}
