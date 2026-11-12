"""X-10: a breakable joint's load is its force averaged over a fixed window of simulated time, and the joints that break do not
depend on the time step.

`uv run pytest packages/engine -q -k break_timestep`

Three reference scenes run at the largest time step a run may take (`MAX_TIMESTEP_S`, 0.002 s), half and a quarter of it. Values
are chosen by the tests (`SRC`), not data; the measured numbers quoted are in `docs/research/engine/break-timestep.md`.

- **drop** (낙하): the X-04b swinging arm (`test_break_runtime.swing`) with `pin` at 1.5 x the hanging weight: the arm swings
  down, `pin` breaks, the arm and both blocks fly off and hit the ground, where `weld-tip` (2 m g) and `weld-mid` (6 m g) break.
- **ramp** (경사로 충돌): a cart on an inclined rail (a slider 30 degrees down from the horizontal, `rig`) slides 0.5 m from rest
  and hits the rail's end stop (the slider's upper limit); a 1 kg block is welded on the cart (`seat`, 5 m g).
- **thrust** (추력기 과하중): the X-01c rocket (`test_thrust.rocket`, tank welded on the 2 lbf thruster by `w`, 6.5 N) on the Moon,
  lit at 0.1 s: the jet pushes the tank harder than its weight (4.9 N) and `w` breaks.

In the original scenes themselves, every joint that breaks breaks at all three time steps. The thrust scene meets the proposed
10 % break-event load spread; the original drop and ramp do not (45.9 % on `weld-tip`, 19.8 % on `seat`). Those two strict
xfails keep the unmet DoD visible instead of tuning thresholds to make it pass. A break load more than 10 % over its threshold
adds the weak-evidence run label: if every compared break stays within that bound, pairwise spread is necessarily at most 10 %.
Each scene also runs with the joints whose loads are compared made unbreakable (`measure`): their largest window loads agree
within 10 %. The speed, mass-ratio and spring bounds are checked by sweeps that step the engine directly (`BreakWatch`).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

from kinetra_core import (
    BREAK_LOAD_WINDOW,
    BREAK_LOAD_WINDOW_KEY,
    MAX_TIMESTEP_S,
    AssumptionTable,
    Badge,
    BreakEvent,
    Joint,
    JointKind,
    Project,
    RunCompleted,
    VerdictAssumptionTable,
    check_run,
    load_body,
    verdict_assumption_table,
)
from kinetra_core.assumption import Assumption
from kinetra_engine.compiler import (
    BREAK_LABEL,
    BREAK_LOAD_SPREAD_LIMIT,
    MASS_RATIO_LIMIT,
    SPEED_LIMIT_M_S,
    SPRING_LIMIT,
    TIMESTEP_SENSITIVE_LABEL,
    BreakWatch,
    OverThreshold,
    TimestepSensitivity,
)
from kinetra_engine.parts import mass_properties
from kinetra_engine.run import PreviewRun, compile_project
from kinetra_engine.run import preview as preview_module
from pydantic import ValidationError
from test_break_runtime import BOB_KG, FLIP, G_EARTH, G_MOON, HANGING_KG, SRC, TOP_KG, _actuate, _with, box, breakable_tower, instance, q, snap, swing
from test_thrust import rocket

WINDOW = BREAK_LOAD_WINDOW.value.value
TIMESTEPS = (MAX_TIMESTEP_S, MAX_TIMESTEP_S / 2, MAX_TIMESTEP_S / 4)
ROOT = Path(__file__).resolve().parents[3]


def spread(values) -> float:
    return (max(values) - min(values)) / min(values)


def material(ident, density):
    return {"id": ident, "name": ident, "density": q(density, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"), "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


def rig(*, travel=0.5, theta_deg=30.0, load_density=8000.0, threshold: float | None = 1.0e9) -> Project:
    """A 720 kg pillar (0.3 x 0.3 x 1 m) on the ground; a 1 kg cart (0.2 x 0.1 x 0.05 m) on a slider `rail` from its side at
    0.9 m, `theta_deg` down from the horizontal, free for `travel` m (then the slider's limit stops it); a 0.05 m cube of
    `load_density` (8000: 1 kg) welded on the cart by `seat` (`threshold` N, `None`: never breaks)."""
    t = math.radians(theta_deg)
    parts = [
        box("base", (0.3, 0.3, 1.0), (0.0, 0.0, 0.5), [snap("rail", (0.15, 0.0, 0.9))]),
        box("cart", (0.2, 0.1, 0.05), (0.0, 0.0, 0.0), [snap("rail", (-0.2, 0.0, 0.0)), snap("deck", (0.0, 0.0, 0.025))]),
        box("load", (0.05, 0.05, 0.05), (0.0, 0.0, 0.0), [snap("seat", (0.0, 0.0, -0.025), FLIP)]),
    ]
    rail = {"id": "rail", "kind": "slider", "a": {"instance": "base", "snap_point": "rail"}, "b": {"instance": "cart", "snap_point": "rail"},
            "axis": {"x": math.cos(t), "y": 0.0, "z": -math.sin(t), "badge": "declared", "source": SRC},
            "limits": {"lower": q(-0.05, "m"), "upper": q(travel, "m")}}
    seat = {"id": "seat", "kind": "fixed", "a": {"instance": "cart", "snap_point": "deck"}, "b": {"instance": "load", "snap_point": "seat"}}
    if threshold is not None:
        seat["break_threshold"] = q(threshold, "N")
    return Project.model_validate({
        "design": {
            "materials": [material("heavy", 8000.0), material("light", 1000.0), material("load", load_density)],
            "parts": parts,
            "instances": [instance("base", "base", "heavy", (0.0, 0.0, 0.0)), instance("cart", "cart", "light", (0.35, 0.0, 0.9)),
                          instance("load", "load", "load", (0.35, 0.0, 0.95))],
            "joints": [rail, seat],
        },
        "world": {"planet": "earth"},
    })


def drop(top_density=8000.0) -> Project:
    """A 2 kg slab (0.2 x 0.2 x 0.05 m) on the ground with a 0.05 m cube of `top_density` (8000: 1 kg) welded on it by `seat`.
    The sweeps start it moving down (the ground stops it at once)."""
    parts = [
        box("slab", (0.2, 0.2, 0.05), (0.0, 0.0, 0.025), [snap("deck", (0.0, 0.0, 0.05))]),
        box("load", (0.05, 0.05, 0.05), (0.0, 0.0, 0.0), [snap("seat", (0.0, 0.0, -0.025), FLIP)]),
    ]
    seat = {"id": "seat", "kind": "fixed", "a": {"instance": "slab", "snap_point": "deck"}, "b": {"instance": "load", "snap_point": "seat"},
            "break_threshold": q(1.0e12, "N")}
    return Project.model_validate({
        "design": {"materials": [material("light", 1000.0), material("load", top_density)], "parts": parts,
                   "instances": [instance("slab", "slab", "light", (0.0, 0.0, 0.0)), instance("load", "load", "load", (0.0, 0.0, 0.075))],
                   "joints": [seat]},
        "world": {"planet": "earth"},
    })


def thrust(threshold: float) -> Project:
    return _with(rocket([]), joint="w", threshold=threshold, entries=[_actuate("burn", "main", 0.1, 0.5, 1.0)], planet="moon")


SCENES = {
    # name: (breaking variant, expected breaks, measure variant, joints whose window loads are compared, duration [s])
    # Keep the original adverse impact thresholds: raising them to the measured peaks hid the 45.9 % / 19.8 % event-load spread.
    "drop": (swing(2 * BOB_KG * G_EARTH, 6 * BOB_KG * G_EARTH, 1.5 * HANGING_KG * G_EARTH), {"pin", "weld-tip", "weld-mid"},
             swing(1.0e9, 1.0e9, 1.5 * HANGING_KG * G_EARTH), ("weld-tip", "weld-mid"), 0.5),
    "ramp": (rig(threshold=5 * 1.0 * G_EARTH), {"seat"}, rig(), ("seat",), 0.6),
    "thrust": (thrust(6.5), {"w"}, thrust(1.0e9), ("w",), 0.3),
}

# Measured on the original scenes (break-timestep.md 2.1): every drop step and the coarse ramp have >10 % threshold overshoot.
OVERSHOOT_SENSITIVE = {"drop": set(TIMESTEPS), "ramp": {MAX_TIMESTEP_S}, "thrust": set()}


@pytest.fixture
def peaks(monkeypatch):
    """The largest window load [N] of every watched joint over the last run, by joint id (`BreakWatch.loads` after each step)."""
    seen: dict[str, float] = {}

    class Watch(preview_module.BreakWatch):
        def over(self, model, data):
            out = super().over(model, data)
            for joint, load in self.loads.items():
                seen[joint] = max(seen.get(joint, 0.0), load)
            return out

    monkeypatch.setattr(preview_module, "BreakWatch", Watch)
    return seen


def run(project: Project, duration_s: float, timestep_s: float):
    preview = PreviewRun(project, run_id="x10", project_id="p", revision=1, duration_s=duration_s, timestep_s=timestep_s)
    items = list(preview)
    frames, ended = items[:-1], items[-1]
    check_run(preview.started, frames, ended)
    assert isinstance(ended.end, RunCompleted)
    return preview, frames, ended


def broken(frames) -> list[BreakEvent]:
    return [e for f in frames for e in f.events if isinstance(e, BreakEvent)]


# --- the window -------------------------------------------------------------------------------------------------------


def test_break_timestep_window_is_a_default_badged_row_longer_than_the_largest_time_step():
    w = BREAK_LOAD_WINDOW
    assert w.key == BREAK_LOAD_WINDOW_KEY and w.value.unit == "s" and w.value.badge is Badge.DEFAULT and not w.editable
    assert w.value.value > MAX_TIMESTEP_S
    assert all(w.value.value > dt for dt in TIMESTEPS)
    breakable, plain = rig(), rig(threshold=None)
    table = verdict_assumption_table(AssumptionTable(), load_body("earth"), breakable.design)
    assert [a.key for a in table.rows] == ["ground_friction", BREAK_LOAD_WINDOW_KEY]
    assert table.row(BREAK_LOAD_WINDOW_KEY) == w
    assert verdict_assumption_table(AssumptionTable(), load_body("earth"), plain.design).engine_rows == ()


def test_break_timestep_window_row_belongs_to_the_engine_not_the_project():
    with pytest.raises(ValidationError, match="fixed by the engine"):
        AssumptionTable(assumptions=(BREAK_LOAD_WINDOW,))
    friction = load_body("earth").ground_friction
    with pytest.raises(ValidationError, match="read-only"):
        VerdictAssumptionTable(planet="earth", planet_rows=(friction,), engine_rows=(BREAK_LOAD_WINDOW.model_copy(update={"editable": True}),),
                               project=AssumptionTable())
    with pytest.raises(ValidationError, match="not a constant the engine fixes"):
        VerdictAssumptionTable(planet="earth", planet_rows=(friction,), engine_rows=(Assumption.model_validate({**BREAK_LOAD_WINDOW.model_dump(), "key": "other"}),),
                               project=AssumptionTable())


def test_break_timestep_window_must_be_longer_than_the_step():
    compiled = compile_project(rig())
    with pytest.raises(ValueError, match="longer than the time step"):
        BreakWatch(compiled.tree, compiled.model, MAX_TIMESTEP_S)


@pytest.mark.parametrize("timestep", [*TIMESTEPS, 0.0015])  # 0.02 / 0.0015 = 13.3 steps: the window takes a third of one more
def test_break_timestep_window_mean_of_a_steady_force_is_that_force(timestep):
    """With the rail's travel 0 the cart rests on its end stop from the start; after 1 s the weld carries the block's weight
    m g (1 kg, g from data/bodies), and the window mean is m g at every time step, also one that does not divide the window."""
    compiled = compile_project(rig(travel=0.0), timestep_s=timestep)
    model, data = compiled.model, mujoco.MjData(compiled.model)
    watch = BreakWatch(compiled.tree, model, WINDOW)
    for _ in range(round(1.0 / timestep)):
        mujoco.mj_step(model, data)
        watch.over(model, data)
    g = load_body("earth").gravity.value
    assert watch.loads["seat"] == pytest.approx(1.0 * g, rel=1e-6)


def test_break_timestep_a_one_step_spike_over_the_threshold_does_not_break_a_sustained_force_does():
    """The X-04b tower on the Moon at rest (weld load m g = 6.48 N), threshold m g + 50 N. A 100 N push down on the top block for
    one step: that step's force is about m g + 100 N, over the threshold, but the window mean is m g + 100 N x 0.002 / 0.02
    (about 16.5 N) and nothing breaks, then or after. The same push held: the window mean rises by about 10 N a step and the
    weld breaks at the first step where it is over the threshold, the 6th (m g + 60 N by hand; 65.8 N measured)."""
    force = 100.0
    threshold = TOP_KG * G_MOON + 0.5 * force
    compiled = compile_project(breakable_tower(threshold))
    model, data = compiled.model, mujoco.MjData(compiled.model)
    watch = BreakWatch(compiled.tree, model, WINDOW)
    top = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "top")
    for _ in range(500):  # 1 s: settled, the window holds m g
        mujoco.mj_step(model, data)
        assert watch.over(model, data) == ()
    data.xfrc_applied[top, 2] = -force
    mujoco.mj_step(model, data)
    assert watch.over(model, data) == ()
    instantaneous = float(np.linalg.norm(data.cfrc_int[top, 3:6]))
    assert instantaneous > threshold  # X-04b's one-step load would have broken here
    assert watch.loads["weld"] == pytest.approx(TOP_KG * G_MOON + force * MAX_TIMESTEP_S / WINDOW, rel=0.05)
    data.xfrc_applied[top] = 0.0
    for _ in range(round(WINDOW / MAX_TIMESTEP_S) * 3):
        mujoco.mj_step(model, data)
        assert watch.over(model, data) == ()
    loads = []
    for step in range(1, 11):
        data.xfrc_applied[top, 2] = -force
        mujoco.mj_step(model, data)
        over = watch.over(model, data)
        loads.append(watch.loads["weld"])
        if over:
            break
    assert step == 6 and [o.joint for o in over] == ["weld"] and over[0].load == loads[-1]
    assert loads[-2] <= threshold < loads[-1]
    assert all(b > a for a, b in zip(loads, loads[1:]))


# --- the time step of a run --------------------------------------------------------------------------------------------


def test_break_timestep_a_run_takes_a_smaller_time_step_never_a_larger_one():
    default = compile_project(rig())
    assert default.model.opt.timestep == MAX_TIMESTEP_S and "timestep=" not in default.mjcf
    half = compile_project(rig(), timestep_s=MAX_TIMESTEP_S / 2)
    assert half.model.opt.timestep == MAX_TIMESTEP_S / 2 and 'timestep="0.001"' in half.mjcf
    for bad in (2 * MAX_TIMESTEP_S, 0.0, -MAX_TIMESTEP_S):
        with pytest.raises(ValueError, match="at most"):
            compile_project(rig(), timestep_s=bad)
    preview = PreviewRun(rig(), run_id="x10", project_id="p", revision=1, duration_s=0.01, timestep_s=MAX_TIMESTEP_S / 4)
    assert preview.started.timestep_s == preview.started.platform.compute.timestep_s == MAX_TIMESTEP_S / 4
    assert BREAK_LABEL in preview.started.model_labels


# --- the three scenes ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scene", SCENES)
def test_break_timestep_scenes_break_the_same_joints_at_every_time_step(scene, peaks):
    project, expected, _, _, duration = SCENES[scene]
    for dt in TIMESTEPS:
        _, frames, ended = run(project, duration, dt)
        events = broken(frames)
        assert {e.joint for e in events} == expected, dt
        assert len(events) == len(expected)
        assert all(e.load.value > e.threshold.value for e in events)
        if dt in OVERSHOOT_SENSITIVE[scene]:
            (label,) = ended.labels
            assert label.startswith(TIMESTEP_SENSITIVE_LABEL) and "파단 하중 초과" in label
        else:
            assert ended.labels == ()


@pytest.mark.parametrize(
    "scene",
    [
        pytest.param("drop", marks=pytest.mark.xfail(strict=True, reason="#453 unmet: original weld-tip break loads differ by 45.9 %")),
        pytest.param("ramp", marks=pytest.mark.xfail(strict=True, reason="#453 unmet: original seat break loads differ by 19.8 %")),
        "thrust",
    ],
)
def test_break_timestep_scenes_break_loads_agree_within_ten_percent(scene):
    """The scene as it is, every joint breaking: the load each `break` event carries agrees within 10 % across the three steps."""
    project, expected, _, _, duration = SCENES[scene]
    loads: dict[str, list[float]] = {j: [] for j in expected}
    for dt in TIMESTEPS:
        _, frames, _ = run(project, duration, dt)
        for e in broken(frames):
            loads[e.joint].append(e.load.value)
    adverse = {"drop": ("weld-tip", 0.459), "ramp": ("seat", 0.198)}.get(scene)
    if adverse is not None:
        joint, measured = adverse
        assert spread(loads[joint]) == pytest.approx(measured, abs=0.001), loads[joint]
    for j, values in loads.items():
        assert len(values) == len(TIMESTEPS), (j, values)
        assert spread(values) <= BREAK_LOAD_SPREAD_LIMIT, (j, values)


def test_break_timestep_ten_percent_overshoot_is_the_cross_run_spread_bound():
    """Loads in `[threshold, 1.1 * threshold]` have at most 10 % spread. The run labels only an overshoot strictly over that."""
    sensitivity = TimestepSensitivity(compile_project(rig()).model)
    threshold = 100.0
    at_bound = threshold * (1 + BREAK_LOAD_SPREAD_LIMIT)
    assert spread([threshold, at_bound]) == pytest.approx(BREAK_LOAD_SPREAD_LIMIT)
    sensitivity.observe_breaks([OverThreshold("seat", "load", at_bound, threshold)])
    assert sensitivity.reasons == []
    sensitivity.observe_breaks([OverThreshold("seat", "load", at_bound + 0.001, threshold)])
    label = sensitivity.label()
    assert label is not None and label.startswith(TIMESTEP_SENSITIVE_LABEL) and "파단 하중 초과 seat" in label


@pytest.mark.parametrize("scene", SCENES)
def test_break_timestep_scenes_window_loads_agree_within_ten_percent(scene, peaks):
    _, _, project, compared, duration = SCENES[scene]
    found: dict[str, list[float]] = {j: [] for j in compared}
    for dt in TIMESTEPS:
        peaks.clear()
        run(project, duration, dt)
        for j in compared:
            found[j].append(peaks[j])
    for j, values in found.items():
        assert spread(values) <= BREAK_LOAD_SPREAD_LIMIT, (j, values)


@pytest.mark.parametrize("scene", SCENES)
@pytest.mark.parametrize("dt", TIMESTEPS)
def test_break_timestep_scenes_repeat_bit_for_bit(scene, dt):
    project, _, _, _, duration = SCENES[scene]
    _, frames_a, ended_a = run(project, duration, dt)
    _, frames_b, ended_b = run(project, duration, dt)
    assert broken(frames_a) and frames_a == frames_b
    assert ended_a.end.trajectory.hash == ended_b.end.trajectory.hash


# --- where it stops holding (docs/research/engine/break-timestep.md) -----------------------------------------------------


def _peak_after_push(project: Project, joint: str, speed: float, dt: float, seconds: float, coordinate: str | None) -> float:
    """Step `project` for `seconds` at `dt` from `speed` [m/s] down (`coordinate` None: the root's free joint, -z) or along
    slider `coordinate`; the largest window load of `joint`."""
    compiled = compile_project(project, timestep_s=dt)
    model, data = compiled.model, mujoco.MjData(compiled.model)
    watch = BreakWatch(compiled.tree, model, WINDOW)
    if coordinate is None:
        data.qvel[2] = -speed
    else:
        data.qvel[model.jnt_dofadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, coordinate)]] = speed
    best = 0.0
    for _ in range(round(seconds / dt)):
        mujoco.mj_step(model, data)
        watch.over(model, data)
        best = max(best, watch.loads[joint])
    return best


@pytest.mark.parametrize(("speed", "holds"), [(256.0, True), (SPEED_LIMIT_M_S, True), (2 * SPEED_LIMIT_M_S, False)])
def test_break_timestep_speed_bound(speed, holds):
    """The block hits the ground at `speed`: the window load agrees within 10 % up to 512 m/s, not at 1024 m/s; the run's check
    calls a body over `SPEED_LIMIT_M_S` time-step sensitive."""
    values = [_peak_after_push(drop(), "seat", speed, dt, 0.05, None) for dt in TIMESTEPS]
    assert (spread(values) <= BREAK_LOAD_SPREAD_LIMIT) is holds, values
    compiled = compile_project(drop())
    model, data = compiled.model, mujoco.MjData(compiled.model)
    data.qvel[2] = -speed
    sensitivity = TimestepSensitivity(model)
    mujoco.mj_step(model, data)
    sensitivity.observe(model, data)
    assert bool(sensitivity.reasons) is (speed > SPEED_LIMIT_M_S)


@pytest.mark.parametrize(("ratio", "holds"), [(4096.0, True), (32768.0, False)])
def test_break_timestep_mass_ratio_bound(ratio, holds):
    """The block on the cart weighs `ratio` x the 1 kg cart and the cart hits the rail's end at 2 m/s: the window load agrees
    within 10 % at 4096, not at 32768; the run's check calls a heaviest-to-lightest ratio over `MASS_RATIO_LIMIT` sensitive."""
    project = rig(travel=0.2, load_density=ratio / 0.05**3)
    values = [_peak_after_push(project, "seat", 2.0, dt, 0.2, "rail") for dt in TIMESTEPS]
    assert (spread(values) <= BREAK_LOAD_SPREAD_LIMIT) is holds, values
    assert bool(TimestepSensitivity(compile_project(project).model).reasons) is (ratio > MASS_RATIO_LIMIT)


@pytest.mark.parametrize(("stiffness", "holds"), [(3.0e5, True), (4.0e5, False)])
def test_break_timestep_spring_bound(stiffness, holds):
    """A spring of `stiffness` [N/m] on the rail (no end stop), the 2 kg cart and block pushed at 1 m/s: omega * dt = 0.776 holds
    within 10 %, 0.896 does not; the run's check calls a slider spring over `SPRING_LIMIT` sensitive."""
    values = []
    for dt in TIMESTEPS:
        compiled = compile_project(rig(travel=0.2), timestep_s=dt)
        model, data = compiled.model, mujoco.MjData(compiled.model)
        j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "rail")
        model.jnt_stiffness[j] = stiffness  # what `to_mjcf` writes for a spring-damper part on a slider (X-01b)
        model.jnt_range[j] = (-10.0, 10.0)
        if dt == MAX_TIMESTEP_S:
            reduced = 2.0 * 720.0 / 722.0
            assert math.sqrt(stiffness / reduced) * dt == pytest.approx(0.776 if holds else 0.896, abs=1e-3)
            assert bool(TimestepSensitivity(model).reasons) is (math.sqrt(stiffness / reduced) * dt > SPRING_LIMIT)
        watch = BreakWatch(compiled.tree, model, WINDOW)
        data.qvel[model.jnt_dofadr[j]] = 1.0
        best = 0.0
        for _ in range(round(0.3 / dt)):
            mujoco.mj_step(model, data)
            watch.over(model, data)
            best = max(best, watch.loads["seat"])
        values.append(best)
    assert (spread(values) <= BREAK_LOAD_SPREAD_LIMIT) is holds, values


def test_break_timestep_a_run_out_of_range_says_its_breaks_are_weak_evidence():
    """A 32768 kg block on the 1 kg cart (mass ratio over `MASS_RATIO_LIMIT`): `run_ended.labels` carries the sentence with the
    reason. The same design with no breakable joint has nothing to say about breaks."""
    heavy = 32768.0 / 0.05**3
    _, _, ended = run(rig(travel=0.2, load_density=heavy), 0.05, MAX_TIMESTEP_S)
    (label,) = ended.labels
    assert label.startswith(TIMESTEP_SENSITIVE_LABEL) and "질량비" in label and "break-timestep.md" in label
    _, _, ended = run(rig(travel=0.2, load_density=heavy, threshold=None), 0.05, MAX_TIMESTEP_S)
    assert ended.labels == ()


def test_break_timestep_out_of_range_after_a_recompile_is_caught_mid_run(monkeypatch):
    """The sensitivity is read again on every step from the model the run is on, so a model compiled again after a break is
    checked too. The drop scene starts in range; here the model compiled after `pin` breaks makes the 1 kg tip block 5000 times
    heavier (mass and inertia, so 5000 kg against the 0.48 kg arm: heaviest / lightest over `MASS_RATIO_LIMIT`), and the run
    ends with the label. A break itself does not change a
    body's mass (the bodies are the same before and after, F8), so the test changes the recompiled model to stand for any
    out-of-range model a recompile could bring (a separation, X-08)."""
    project, _, _, _, duration = SCENES["drop"]
    assert TimestepSensitivity(compile_project(project).model).reasons == []
    real = preview_module.carry_state

    def heavier(old_model, old_data, new_model):
        row = mujoco.mj_name2id(new_model, mujoco.mjtObj.mjOBJ_BODY, "bob-tip")
        new_model.body_mass[row] *= 5000.0
        new_model.body_inertia[row] *= 5000.0
        return real(old_model, old_data, new_model)

    monkeypatch.setattr(preview_module, "carry_state", heavier)
    _, frames, ended = run(project, duration, MAX_TIMESTEP_S)
    assert broken(frames)[0].joint == "pin"
    (label,) = ended.labels
    assert label.startswith(TIMESTEP_SENSITIVE_LABEL) and "질량비" in label


# --- bracing is a part with mass ----------------------------------------------------------------------------------------


def test_break_timestep_no_massless_bracing_in_the_schema():
    """KSP's struts and autostruts (benchmark B2, B3) are links of unknown model and mass. A joint here is one of three kinds
    between two snap points of two instances, every instance has a part and a material, so its mass is counted."""
    assert {k.value for k in JointKind} == {"fixed", "hinge", "slider"}
    assert set(Joint.model_fields) == {"id", "kind", "a", "b", "axis", "limits", "break_threshold"}
    assert json.loads((ROOT / "schemas" / "JointKind.schema.json").read_text(encoding="utf-8"))["enum"] == ["fixed", "hinge", "slider"]
    for path in sorted((ROOT / "schemas").glob("*.json")) + [ROOT / "schemas" / "types.ts"]:
        assert "strut" not in path.read_text(encoding="utf-8").lower(), path


def test_break_timestep_a_beam_adds_its_own_mass():
    """Bracing a block with the library `beam` (B-02a, al6061-t6) adds the beam's mass to the compiled model, no more, no less."""
    from gltf_samples import catalog_material
    from test_beam_plate import load

    beam = load("beam")
    al = catalog_material("al6061-t6")
    block = box("block", (0.2, 0.2, 0.1), (0.0, 0.0, 0.05), [])
    block["snap_points"] = [{"id": "top", "kind": "face", "accepts": ["face"], "badge": "declared", "source": SRC,
                             "position": {"x": {"offset": 0.0, "terms": []}, "y": {"offset": 0.0, "terms": []}, "z": {"offset": 0.1, "terms": []}},
                             "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}]

    def design(with_beam: bool) -> Project:
        instances = [instance("block", "block", al.id, (0.0, 0.0, 0.0))]
        joints = []
        if with_beam:
            instances.append(instance("brace", "beam", al.id, (0.0, 0.0, 0.13)))
            joints.append({"id": "bolt", "kind": "fixed", "a": {"instance": "block", "snap_point": "top"}, "b": {"instance": "brace", "snap_point": "bottom"}})
        return Project.model_validate({"design": {"materials": [al.model_dump(mode="json")], "parts": [block, beam.model_dump(mode="json")],
                                                  "instances": instances, "joints": joints}, "world": {"planet": "earth"}})

    def total(project: Project) -> float:
        return float(compile_project(project).model.body_mass[1:].sum())

    added = total(design(True)) - total(design(False))
    assert added == pytest.approx(mass_properties(beam, al).mass.value, rel=1e-9)
    assert added == pytest.approx(0.7128, rel=1e-9)  # test_beam_plate: the default beam by hand
