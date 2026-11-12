"""J-01a: Monte Carlo p_success and its 95% CI over the verdict's assumption table, recorded with the platform tag.

`uv run pytest packages/judge -q -k mc`. Every verdict here is the engine's (MuJoCo 4.0.0, `PreviewRun` of kind `verdict_sample`).

Hand calculation (the slide test). A block whose friction (1.0) is above every ground's rests on a ramp without a material, so the
pair's coefficient is the ramp's, the planet's ground friction (`terrain-props.md`); on Earth that is U(0.3443, 0.7813)
(`data/bodies/earth.json`). On a 30° ramp the block slides when mu < tan 30° = 0.5774 and holds when mu > tan 30° (W-05 measured
the slip angle within 1.6e-3 of atan(mu)). The goal is "the block's origin has moved 0.02 m downhill (in x) within 1 s". With the
seed below every drawn mu is at least 0.03 from tan 30°: a slide then accelerates at >= g cos 30° x 0.03 = 0.25 m/s², about
0.08 m along the slope by 1 s even after 0.2 s of settling; a hold creeps by at most 1.8e-3 m/s (W-05, 0.5° under the slip angle),
under 2 mm. So the met samples are exactly the drawn mu below tan 30°, and p_success = that count / n.

Platform (engine.md 5.4, A0-05). The seed reproduction asserted here is between runs of the same platform tag, in this
process (H6). No recorded p_success is committed to compare against: the reference platform (Linux x86-64 fixed image, H3) does
not exist yet (#478 open), and a value from any other platform would be a cross-platform reference number. So there is no
cross-tag tolerance test either; once #478 lands, a committed reference value is made there, with its tag.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from kinetra_core import Project, RunEnded, RunKind, load_body, verdict_assumption_table
from kinetra_engine.run import PreviewRun

from kinetra_judge import (
    Goal,
    SensitivityReport,
    Verdict,
    VerdictComparison,
    VerdictComparisonResult,
    assumptions_hash,
    compare_verdicts,
    goal_hash,
    monte_carlo,
    run_sensitivity,
    run_verdict,
    sample_assumptions,
    wilson_ci,
)
import kinetra_judge.mc as mc
from kinetra_judge.mc import CI_LABEL, ENGINE_APPLIED, PLATFORM_LABEL, VERDICT_LABEL, derive_seed

SRC = {"ref": "J-01a test fixture: value chosen by the test", "locator": "test_mc.py"}
THETA = math.radians(30.0)
SIDE, THICK, LENGTH = 0.1, 0.02, 3.0  # [m] a flat block (tips only past 78.7°) on a 3 m ramp
SEED, N = 17, 12  # every mu drawn by this seed is >= 0.03 away from tan 30° (asserted below)
MARGIN = 0.03
DOWNHILL = 0.02  # [m] how far the origin must move in -x
DURATION_S = 1.0


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def block_on_ramp(assumptions: list | None = None) -> Project:
    """The block resting on the middle of an Earth ramp of `THETA` without a material (the ground's friction)."""
    material = {"id": "grip", "name": "Test material", "density": q(1000.0, "kg/m^3"), "yield_strength": q(1.0e8, "Pa"),
                "elastic_modulus": q(1.0e9, "Pa"), "friction": q(1.0, "1")}
    part = {"id": "plate", "name": "plate", "parameters": [], "snap_points": [], "shape": {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "box", "size_x": ax(SIDE), "size_y": ax(SIDE), "size_z": ax(THICK)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}}
    centre = np.array([0.0, 0.0, LENGTH / 2 * math.tan(THETA)]) + np.array([-math.sin(THETA), 0.0, math.cos(THETA)]) * THICK / 2
    tilt = {"x": 0.0, "y": math.sin(-THETA / 2), "z": 0.0, "w": math.cos(-THETA / 2)}  # local z to the slope normal
    inst = {"id": "block1", "part": "plate", "material": "grip",
            "pose": {"badge": "declared", "source": SRC, "position": dict(zip("xyz", map(float, centre), strict=True)), "orientation": tilt}}
    ramp = {"id": "ramp1", "kind": "ramp", "material": None, "placement": {"badge": "declared", "source": SRC, "x": 0.0, "y": 0.0, "yaw": 0.0},
            "length": q(LENGTH, "m"), "width": q(1.0, "m"), "incline": q(THETA, "rad")}
    return Project.model_validate({"design": {"materials": [material], "parts": [part], "instances": [inst], "joints": []},
                                   "world": {"planet": "earth", "terrain_props": [ramp]},
                                   "assumptions": {"assumptions": assumptions or []}})


def slid_goal(project: Project) -> Goal:
    x0 = project.design.instances[0].pose.position.x
    return Goal.model_validate({"conditions": [{"kind": "reach", "id": "slid", "instance": "block1",
                                                "region": {"min": {"x": -10, "y": -10, "z": -10}, "max": {"x": x0 - DOWNHILL, "y": 10, "z": 10}}}]})


def drawn_mu(project: Project, n: int, seed: int) -> tuple[float, ...]:
    rows = verdict_assumption_table(project.assumptions, load_body("earth")).rows
    return sample_assumptions(rows, n, seed)["ground_friction"]


@pytest.fixture(scope="module")
def ramp_verdict() -> Verdict:
    project = block_on_ramp()
    return run_verdict(project, slid_goal(project), n=N, seed=SEED, duration_s=DURATION_S, project_id="ramp", revision=0)


# --- sampling and the interval (legacy port) ------------------------------------------------------------------------


def test_mc_samples_per_row_streams_reproducible_and_independent_of_other_rows():
    friction = load_body("earth").ground_friction
    mass = {"key": "vehicle_mass", "label": "Vehicle mass", "value": q(10.0, "kg"), "confidence": "med",
            "distribution": {"kind": "normal", "mean": 10.0, "std": 2.0, "clip_low": 9.0, "badge": "estimate", "source": SRC}}
    table = verdict_assumption_table(block_on_ramp([mass]).assumptions, load_body("earth"))
    both = sample_assumptions(table.rows, 200, SEED)
    assert both == sample_assumptions(table.rows, 200, SEED)  # same seed, same draws
    assert both["ground_friction"] == sample_assumptions([friction], 200, SEED)["ground_friction"]  # adding a row shifts nothing
    assert both["ground_friction"] != sample_assumptions([friction], 200, SEED + 1)["ground_friction"]
    # the legacy stream: default_rng(derive_seed(seed, "assumption", key)).uniform(low, high, n)
    d = friction.distribution
    legacy = np.random.default_rng(derive_seed(SEED, "assumption", "ground_friction")).uniform(d.low, d.high, 200)
    assert both["ground_friction"] == tuple(float(v) for v in legacy)
    assert all(d.low <= v <= d.high for v in both["ground_friction"])
    assert min(both["vehicle_mass"]) == 9.0  # clipped at clip_low
    fixed = {**mass, "key": "fixed_mass", "distribution": {"kind": "fixed"}}
    assert sample_assumptions(block_on_ramp([fixed]).assumptions.assumptions, 3, SEED)["fixed_mass"] == (10.0, 10.0, 10.0)


def test_mc_wilson_interval_matches_hand_calculation():
    # z = 1.959963984540054, z^2 = 3.841459; k = 0: high = z^2 / (n + z^2); k = n: low = n / (n + z^2)
    assert wilson_ci(0, 10) == (0.0, pytest.approx(3.841459 / 13.841459, abs=1e-6))
    assert wilson_ci(10, 10) == (pytest.approx(10 / 13.841459, abs=1e-6), 1.0)
    # k = 5, n = 10: centre 0.5, half = z sqrt(0.025 + z^2/400) / (1 + z^2/10) = 0.263406
    lo, hi = wilson_ci(5, 10)
    assert (lo, hi) == (pytest.approx(0.236594, abs=1e-6), pytest.approx(0.763406, abs=1e-6))
    with pytest.raises(ValueError):
        wilson_ci(0, 0)


# --- the verdict from the engine -------------------------------------------------------------------------------------


def test_mc_ramp_p_success_is_the_share_of_drawn_frictions_below_tan_theta(ramp_verdict):
    mu = drawn_mu(block_on_ramp(), N, SEED)
    assert min(abs(m - math.tan(THETA)) for m in mu) >= MARGIN  # the hand calculation's precondition
    below = sum(m < math.tan(THETA) for m in mu)
    assert 0 < below < N  # both outcomes occur
    v = ramp_verdict
    assert (v.n_samples, v.n_met, v.n_failed, v.n_undetermined) == (N, below, N - below, 0)
    assert v.p_success == below / N
    assert (v.ci_low, v.ci_high) == wilson_ci(below, N) and v.ci_low < v.p_success < v.ci_high
    assert v.ci_method == "wilson_95" and v.badge == "sim" and v.seed == SEED and v.planet == "earth"
    assert v.sampled == ("ground_friction",) and v.not_applied == ()
    assert v.labels == (VERDICT_LABEL, CI_LABEL, PLATFORM_LABEL)


def test_mc_verdict_is_recorded_with_its_platform_tag(ramp_verdict):
    project = block_on_ramp()
    tag = PreviewRun(project, run_id="tag", project_id="ramp", revision=0, duration_s=0.01).started.platform
    record = ramp_verdict.model_dump(mode="json")
    assert {"p_success", "ci_low", "ci_high", "n_samples", "platform"} <= record.keys()
    assert Verdict.model_validate(record) == ramp_verdict  # the record round-trips with its tag
    assert ramp_verdict.platform == tag  # the tag of the runs in this process (H1)
    del record["platform"]
    with pytest.raises(ValueError):
        Verdict.model_validate(record)  # a verdict without its tag is not a record


def test_mc_seed_reproduction_within_the_same_tag(ramp_verdict):
    project = block_on_ramp()
    again = run_verdict(project, slid_goal(project), n=N, seed=SEED, duration_s=DURATION_S, project_id="ramp", revision=0)
    assert again.platform == ramp_verdict.platform  # same tag: bit equality is asserted (H6)
    assert again == ramp_verdict
    assert compare_verdicts(again, ramp_verdict) == VerdictComparisonResult(status=VerdictComparison.MATCH, differs=())


def test_mc_verdicts_under_different_tags_are_not_called_the_same(ramp_verdict):
    record = ramp_verdict.model_dump(mode="json")
    other_cpu = {**record, "platform": {**record["platform"], "cpu": {**record["platform"]["cpu"], "model": "another cpu"}}}
    elsewhere = Verdict.model_validate(other_cpu)
    assert elsewhere.p_success == ramp_verdict.p_success
    assert compare_verdicts(elsewhere, ramp_verdict) == VerdictComparisonResult(status=VerdictComparison.NOT_COMPARABLE, differs=("platform",))
    k = ramp_verdict.n_met - 1
    fewer = Verdict.model_validate({**record, "n_met": k, "n_failed": N - k, "p_success": k / N,
                                    "ci_low": wilson_ci(k, N)[0], "ci_high": wilson_ci(k, N)[1]})
    assert compare_verdicts(fewer, ramp_verdict) == VerdictComparisonResult(  # same request, same tag, other numbers (H2)
        status=VerdictComparison.MISMATCH, differs=("n_met", "n_failed", "p_success", "ci_low", "ci_high"))


def test_mc_verdicts_of_different_requests_are_not_comparable(ramp_verdict):
    project = block_on_ramp()
    assert ramp_verdict.goal_hash == goal_hash(slid_goal(project))
    assert ramp_verdict.assumptions_hash == assumptions_hash(table_of(project))
    assert ramp_verdict.duration_s == DURATION_S and ramp_verdict.timestep_s == ramp_verdict.platform.compute.timestep_s
    mass = {"key": "vehicle_mass", "label": "Vehicle mass", "value": q(10.0, "kg"), "confidence": "med"}
    other_goal = Goal.model_validate({"conditions": [{"kind": "no_break", "id": "whole"}]})
    record = ramp_verdict.model_dump(mode="json")
    changes = {
        "definition_hash": "sha256:" + "0" * 64,
        "goal_hash": goal_hash(other_goal),
        "assumptions_hash": assumptions_hash(table_of(block_on_ramp([mass]))),
        "duration_s": 2.0,
        "timestep_s": 0.001,
        "seed": SEED + 1,
    }
    for field, value in changes.items():
        other = Verdict.model_validate({**record, field: value})
        assert compare_verdicts(other, ramp_verdict) == VerdictComparisonResult(status=VerdictComparison.NOT_COMPARABLE, differs=(field,))
    # another sample count, with its own consistent numbers: still a different request
    other_n = Verdict.model_validate({**record, "n_samples": N + 1, "n_failed": record["n_failed"] + 1,
                                      "sampled_values": {k: [*v, v[-1]] for k, v in record["sampled_values"].items()},
                                      "p_success": ramp_verdict.n_met / (N + 1),
                                      "ci_low": wilson_ci(ramp_verdict.n_met, N + 1)[0], "ci_high": wilson_ci(ramp_verdict.n_met, N + 1)[1]})
    assert compare_verdicts(other_n, ramp_verdict).differs == ("n_samples",)
    both = Verdict.model_validate({**other_cpu_record(record), "seed": SEED + 1})
    assert compare_verdicts(both, ramp_verdict) == VerdictComparisonResult(status=VerdictComparison.NOT_COMPARABLE, differs=("seed", "platform"))


def other_cpu_record(record: dict) -> dict:
    return {**record, "platform": {**record["platform"], "cpu": {**record["platform"]["cpu"], "model": "another cpu"}}}


def test_mc_verdict_refuses_inconsistent_numbers(ramp_verdict):
    record = ramp_verdict.model_dump(mode="json")
    for bad in ({"p_success": ramp_verdict.p_success + 0.01}, {"ci_low": 0.0}, {"n_met": ramp_verdict.n_met + 1}, {"p_success": None}):
        with pytest.raises(ValueError):
            Verdict.model_validate({**record, **bad})
    with pytest.raises(ValueError, match="sampled_values"):
        Verdict.model_validate({**record, "sampled_values": {"ground_friction": [0.5]}})


# --- what the verdict does not hide ----------------------------------------------------------------------------------


def engine_sample(project: Project, *, kind: RunKind = RunKind.VERDICT_SAMPLE, stopped: bool = False, duration_s: float = 0.1):
    """`run_sample` of one real engine run per sample. `stopped` ends it as the client's stop at its last tick: the run is
    deterministic, so a run stopped at tick k has the frames and the trajectory hash of a run that completed at tick k."""

    def run(i, values):
        r = PreviewRun(project, run_id=f"s{i}", project_id="ramp", revision=0, duration_s=duration_s, kind=kind, frame_every_ticks=1,
                       ground_friction=values["ground_friction"])
        stream = list(r)
        ended = stream[-1]
        if stopped:
            end = {"reason": "stopped", "trajectory": ended.end.trajectory.model_dump(mode="json")}
            ended = RunEnded.model_validate({"type": "run_ended", "run_id": ended.run_id, "last_tick": ended.last_tick, "end": end})
        return r.started, stream[:-1], ended

    return run


def table_of(project: Project):
    return verdict_assumption_table(project.assumptions, load_body(project.world.planet))


def test_mc_bound_material_friction_at_both_distribution_ends_changes_the_hand_computed_result(monkeypatch):
    """#571: the low endpoint slides and the high endpoint holds on the same 30° ramp as above.

    The ramp has its own material, so the contact pair is min(block 1.0, sampled ramp friction), not the planet row.
    The sampler is forced only to the declared distribution's two endpoints; every compile, engine step and goal check is real.
    """
    data = block_on_ramp().model_dump(mode="json")
    data["design"]["materials"].append({
        "id": "surface", "name": "Declared test surface", "density": q(1000.0, "kg/m^3"),
        "yield_strength": q(1.0e8, "Pa"), "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1"),
    })
    data["world"]["terrain_props"][0]["material"] = "surface"
    data["assumptions"]["assumptions"] = [{
        "key": "surface_friction", "label": "Surface friction", "value": q(0.5, "1"), "confidence": "med",
        "distribution": {"kind": "uniform", "low": 0.1, "high": 1.0, "badge": "estimate", "source": SRC},
        "binding": {"kind": "material_property", "material": "surface", "property": "friction"},
    }]
    project = Project.model_validate(data)
    real_samples = mc.sample_assumptions

    def endpoints(rows, n, seed):
        assert n == 2
        values = real_samples(rows, n, seed)  # all other rows retain their independent, seeded streams
        values["surface_friction"] = (0.1, 1.0)
        return values

    monkeypatch.setattr(mc, "sample_assumptions", endpoints)
    verdict = run_verdict(project, slid_goal(project), n=2, seed=SEED, duration_s=DURATION_S, project_id="ramp", revision=0)

    # mu=0.1: a = g(sin30° - 0.1cos30°) = 4.06 m/s², so it moves far beyond 0.02 m by 1 s.
    # mu=1.0 > tan30°: the block holds. The ground-friction draws cannot change either material-material contact.
    assert (verdict.n_met, verdict.n_failed, verdict.n_undetermined) == (1, 1, 0)
    assert verdict.sampled == ("ground_friction", "surface_friction") and verdict.not_applied == ()
    assert verdict.sampled_values["surface_friction"] == (0.1, 1.0)
    assert verdict.sampled_values["ground_friction"] == drawn_mu(project, 2, SEED)
    assert project.design.materials[1].friction.value == 0.5  # samples never mutate the project or its declared material


@pytest.mark.parametrize("declared_mass", [False, True])
def test_mc_only_consumed_bound_targets_are_sampled(declared_mass):
    data = block_on_ramp().model_dump(mode="json")
    part = data["design"]["parts"][0]
    part["parameters"] = [{"name": "mass", "unit": "kg", "default": q(1.0, "kg"),
                           "min": q(0.1, "kg"), "max": q(2.0, "kg")}]
    part["mass_parameter"] = "mass" if declared_mass else None
    part["specs"] = [{"name": "tread_friction_kinetic", **q(0.5, "1")}, {"name": "annotation", **q(1.0, "N")}]
    data["design"]["materials"].append({**data["design"]["materials"][0], "id": "unused"})

    def bound(key, value, unit, binding):
        return {"key": key, "label": key, "value": q(value, unit), "confidence": "med", "binding": binding,
                "distribution": {"kind": "uniform", "low": value * 0.9, "high": value * 1.1,
                                 "badge": "estimate", "source": SRC}}

    data["assumptions"]["assumptions"] = [
        bound("mass", 1.0, "kg", {"kind": "instance_parameter", "instance": "block1", "parameter": "mass"}),
        bound("density", 1000.0, "kg/m^3", {"kind": "material_property", "material": "grip", "property": "density"}),
        bound("strength", 1.0e8, "Pa", {"kind": "material_property", "material": "grip", "property": "yield_strength"}),
        bound("orphan", 1.0, "1", {"kind": "material_property", "material": "unused", "property": "friction"}),
        bound("overridden_friction", 1.0, "1", {"kind": "material_property", "material": "grip", "property": "friction"}),
        bound("tread", 0.5, "1", {"kind": "part_spec", "part": "plate", "spec": "tread_friction_kinetic"}),
        bound("annotation", 1.0, "N", {"kind": "part_spec", "part": "plate", "spec": "annotation"}),
    ]
    project = Project.model_validate(data)
    goal = Goal.model_validate({"conditions": [{"kind": "no_break", "id": "whole"}]})
    verdict = run_verdict(project, goal, n=2, seed=SEED, duration_s=0.01, project_id="used", revision=0)
    expected = {"ground_friction", "mass" if declared_mass else "density", "tread"}
    assert set(verdict.sampled) == expected and set(verdict.sampled_values) == expected
    assert set(verdict.not_applied) == {r["key"] for r in data["assumptions"]["assumptions"]} - expected


@pytest.mark.parametrize("active", [False, True])
def test_mc_inactive_thruster_spec_is_not_applied(active):
    data = block_on_ramp().model_dump(mode="json")
    part = data["design"]["parts"][0]
    part["role"] = "thruster"
    part["specs"] = [{"name": "rated_thrust", **q(1.0, "N")}, {"name": "propellant_flow", **q(0.1, "kg/s")}]
    part["curves"] = [{"name": "thrust", "curve": {"badge": "declared", "source": SRC,
        "x_unit": "s", "y_unit": "N", "points": [{"x": 0.0, "y": 1.0}, {"x": 1.0, "y": 1.0}]}}]
    part["snap_points"] = [{"id": "nozzle", "kind": "exhaust", "badge": "declared", "source": SRC,
        "position": {a: ax(0.0) for a in "xyz"}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}]
    data["design"]["actuators"] = [{"id": "engine", "kind": "thruster", "instance": "block1"}]
    if active:
        data["design"]["schedule"] = {"entries": [{"type": "actuate", "id": "on", "actuator": "engine",
            "start": 0.0, "end": 1.0, "command": 1.0, "badge": "declared", "source": SRC}]}
    data["assumptions"]["assumptions"] = [{"key": "thrust", "label": "Thrust", "value": q(1.0, "N"),
        "confidence": "med", "distribution": {"kind": "uniform", "low": 0.9, "high": 1.1, "badge": "estimate", "source": SRC},
        "binding": {"kind": "part_spec", "part": "plate", "spec": "rated_thrust"}}]
    project = Project.model_validate(data)
    goal = Goal.model_validate({"conditions": [{"kind": "no_break", "id": "whole"}]})
    verdict = run_verdict(project, goal, n=1, seed=SEED, duration_s=0.01, project_id="thrust", revision=0)
    assert ("thrust" in verdict.sampled) is active
    assert ("thrust" in verdict.not_applied) is not active


def test_mc_names_rows_the_model_does_not_read():
    mass = {"key": "vehicle_mass", "label": "Vehicle mass", "value": q(10.0, "kg"), "confidence": "med",
            "distribution": {"kind": "uniform", "low": 9.0, "high": 11.0, "badge": "estimate", "source": SRC}}
    project = block_on_ramp([mass])
    v = monte_carlo(table_of(project), slid_goal(project), n=2, seed=SEED, duration_s=0.1, applied=ENGINE_APPLIED, run_sample=engine_sample(project))
    assert v.sampled == ("ground_friction",) and v.not_applied == ("vehicle_mass",)
    assert set(v.sampled_values) == {"ground_friction"}
    assert "미적용: 가정 'vehicle_mass'의 분포는 모델이 읽지 않아 흔들지 않았다" in v.labels


def test_mc_undetermined_samples_are_counted_and_left_out_of_p():
    project = block_on_ramp()
    v = monte_carlo(table_of(project), slid_goal(project), n=3, seed=SEED, duration_s=0.02, applied=ENGINE_APPLIED,
                    run_sample=engine_sample(project, stopped=True, duration_s=0.02))
    assert (v.n_met, v.n_failed, v.n_undetermined) == (0, 0, 3)  # stopped at 0.02 s before anything slid 0.02 m
    assert (v.p_success, v.ci_low, v.ci_high) == (None, None, None)
    assert "판단 불가 3개 표본은 p_success와 신뢰구간의 분모에서 뺐다" in v.labels


def test_mc_counts_only_verdict_samples_of_one_tag():
    project = block_on_ramp()
    table, goal = table_of(project), slid_goal(project)
    with pytest.raises(ValueError, match="verdict_sample"):
        monte_carlo(table, goal, n=1, seed=SEED, duration_s=0.1, applied=ENGINE_APPLIED, run_sample=engine_sample(project, kind=RunKind.PREVIEW))
    real = engine_sample(project)

    def second_elsewhere(i, values):
        started, frames, ended = real(i, values)
        if i == 1:
            cpu = started.platform.cpu.model_copy(update={"model": "another cpu"})
            started = started.model_copy(update={"platform": started.platform.model_copy(update={"cpu": cpu})})
        return started, frames, ended

    with pytest.raises(ValueError, match="platform tag"):
        monte_carlo(table, goal, n=2, seed=SEED, duration_s=0.1, applied=ENGINE_APPLIED, run_sample=second_elsewhere)
    with pytest.raises(ValueError):
        monte_carlo(table, goal, n=0, seed=SEED, duration_s=0.1, applied=ENGINE_APPLIED, run_sample=real)


def test_mc_refuses_samples_that_did_not_run_the_requested_duration():
    project = block_on_ramp()
    table, goal = table_of(project), slid_goal(project)
    for run_sample in (
        engine_sample(project, duration_s=0.05),  # completed, but shorter than asked
        engine_sample(project, stopped=True, duration_s=0.05),  # stopped before the requested end
        engine_sample(project, duration_s=0.2),  # longer than asked
    ):
        with pytest.raises(ValueError, match="the request is 0.1 s, which ends at tick 50"):
            monte_carlo(table, goal, n=1, seed=SEED, duration_s=0.1, applied=ENGINE_APPLIED, run_sample=run_sample)
    v = monte_carlo(table, goal, n=1, seed=SEED, duration_s=0.1, applied=ENGINE_APPLIED, run_sample=engine_sample(project, duration_s=0.1))
    assert v.duration_s == 0.1 and v.n_samples == 1  # the run that ran 0.1 s (50 ticks of 0.002 s) is counted


# --- J-03: real one-at-a-time verdict sensitivity ---------------------------------------------------------------


def sensitivity_project() -> Project:
    """A material-friction switch, an irrelevant ground row, and two broad rows the model never consumes."""
    data = block_on_ramp().model_dump(mode="json")
    grip = data["design"]["materials"][0]
    data["design"]["materials"] += [
        {"id": "surface", "name": "Declared sensitivity surface", "density": q(1000.0, "kg/m^3"),
         "yield_strength": q(1.0e8, "Pa"), "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")},
        {**grip, "id": "unused"},
    ]
    data["world"]["terrain_props"][0]["material"] = "surface"

    def uniform(key, value, low, high, unit, binding=None):
        return {"key": key, "label": key, "value": q(value, unit), "confidence": "med", "binding": binding,
                "distribution": {"kind": "uniform", "low": low, "high": high, "badge": "estimate", "source": SRC}}

    data["assumptions"]["assumptions"] = [
        uniform("surface_friction", 0.5, 0.1, 1.0, "1",
                {"kind": "material_property", "material": "surface", "property": "friction"}),
        uniform("unbound_mass", 10.0, 0.1, 1000.0, "kg"),
        uniform("unused_friction", 0.5, 0.0, 2.0, "1",
                {"kind": "material_property", "material": "unused", "property": "friction"}),
        {"key": "fixed_note", "label": "fixed_note", "value": q(1.0, "1"), "confidence": "low"},
    ]
    return Project.model_validate(data)


@pytest.fixture(scope="module")
def sensitivity_case():
    project = sensitivity_project()
    before = project.model_dump(mode="json")
    # Three is deliberately odd: the baseline cannot be exactly 0.5, so the hand-computed crossing is unambiguous.
    report = run_sensitivity(project, slid_goal(project), n=3, seed=SEED, duration_s=DURATION_S,
                             project_id="sensitivity-ramp", revision=0)
    return project, before, report


def test_sensitivity_dominant_flip_is_the_real_consumed_friction(sensitivity_case):
    project, before, report = sensitivity_case
    assert project.model_dump(mode="json") == before  # counterfactual pins never mutate the project or its provenance
    assert report.badge == "sim" and report.method == "one_at_a_time_q05_q95"
    assert [r.assumption_key for r in report.rows] == ["surface_friction", "ground_friction"]
    dominant = report.rows[0]
    assert dominant.rank == 1 and dominant.effect == -1.0 and dominant.flips_verdict is True
    assert report.dominant_flip_assumption == "surface_friction"
    assert (dominant.low.quantile, dominant.low.value) == (0.05, pytest.approx(0.145))
    assert (dominant.high.quantile, dominant.high.value) == (0.95, pytest.approx(0.955))
    assert dominant.low.value_source == dominant.high.value_source == "original_assumption_distribution_quantile"
    # q05 < tan(30°): all three slide; q95 > tan(30°): all three hold. These are actual engine goal outcomes.
    assert (dominant.low.n_met, dominant.low.n_failed, dominant.low.n_undetermined) == (3, 0, 0)
    assert (dominant.high.n_met, dominant.high.n_failed, dominant.high.n_undetermined) == (0, 3, 0)
    assert dominant.low.p_success == 1.0 and dominant.high.p_success == 0.0
    assert dominant.low.assumptions_hash != dominant.high.assumptions_hash != report.baseline.assumptions_hash

    # The ground cannot affect this material-material ramp contact. Common random numbers keep the surface draws fixed,
    # so both ground pins reproduce the baseline verdict instead of inventing an effect.
    ground = report.rows[1]
    assert ground.effect == 0.0 and ground.flips_verdict is False
    assert ground.low.p_success == ground.high.p_success == report.baseline.p_success
    assert (ground.low.n_met, ground.low.n_failed) == (ground.high.n_met, ground.high.n_failed)
    assert (ground.low.n_met, ground.low.n_failed) == (report.baseline.n_met, report.baseline.n_failed)


def test_sensitivity_report_exposes_all_assumptions_method_limits_and_unmeasured_rows(sensitivity_case):
    _, _, report = sensitivity_case
    assert tuple(a.key for a in report.assumptions) == (
        "ground_friction", "surface_friction", "unbound_mass", "unused_friction", "fixed_note",
    )
    assert report.not_applied == ("unbound_mass", "unused_friction")
    assert report.fixed == ("fixed_note",)
    assert not {"unbound_mass", "unused_friction", "fixed_note"} & {r.assumption_key for r in report.rows}
    assert any("일변량 국소 비교" in label and "전역 민감도는 측정하지 않으며" in label for label in report.labels)
    assert any("같은 시드·표본 인덱스" in label for label in report.labels)
    assert any("0.5의 엄격히 반대편" in label for label in report.labels)
    assert all(f"미적용: 가정 '{key}'는 모델이 소비하지 않아 민감도를 측정하지 않았다" in report.labels
               for key in report.not_applied)


def test_sensitivity_seed_reproduction_and_json_consumer_round_trip(sensitivity_case):
    project, _, report = sensitivity_case
    again = run_sensitivity(project, slid_goal(project), n=3, seed=SEED, duration_s=DURATION_S,
                            project_id="sensitivity-ramp", revision=0)
    assert again == report
    record = report.model_dump(mode="json")
    assert [row["assumption_key"] for row in record["rows"]] == ["surface_friction", "ground_friction"]
    assert record["dominant_flip_assumption"] == "surface_friction"
    assert SensitivityReport.model_validate(record) == report
