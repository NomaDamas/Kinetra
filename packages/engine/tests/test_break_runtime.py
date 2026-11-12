"""X-04b: a joint whose load is over its `break_threshold` comes apart during the run, and the stream says so.

`uv run pytest packages/engine -q -k break_runtime`

Two designs, both standing on the compiled ground (X-01e), values chosen by the test (`SRC`), not data:

- `tower`: the two-block tower of `test_simulate_stream.py` on the moon, its weld made breakable. At rest the weld carries the
  top block's weight, `m g` (4 kg x 1.62 m/s^2 = 6.48 N; `g` read from `data/bodies`), which is how the load reading is checked.
- `swing`: a 96 kg base block on Earth with an arm on a hinge (`pin`, axis +y) at an overhang of its top, held horizontal at
  the saved pose, so it drops and swings down when the run starts. A 1 kg block is welded at the arm's tip (`weld-tip`) and
  another under its middle (`weld-mid`). A point mass on a massless pendulum of length L released from horizontal reaches the
  bottom with v^2 = 2 g L (energy), so the rod pulls m g + m v^2 / L = 3 m g there, and m g at rest; with no break the run
  reads 31.9 N (3.25 m g) on `weld-tip`. The thresholds are multiples of the blocks' weights away from the loads: `2 m g`
  breaks during the swing and not at rest, `6 m g` and `10 x` the hanging weight do not break (the peaks without breaks are
  checked in `test_break_runtime_without_breaks_the_swing_loads_stay_under_the_holding_thresholds`).
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest

from kinetra_core import BREAK_LOAD_WINDOW, BreakEvent, Frame, Project, RunCompleted, check_run, decode_frame, encode_frame
from kinetra_core.bodies import load_body
from kinetra_engine.compiler import (
    BREAK_LABEL,
    BreakWatch,
    CompileError,
    CompileErrorCode,
    breakable_joints,
    build_body_tree,
    carry_state,
    release,
    to_mjcf,
)
from kinetra_engine.run import PreviewRun, compile_project

from test_simulate_stream import tower

SRC = {"ref": "X-04b test fixture: value chosen by the test", "locator": "test_break_runtime.py"}
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
FLIP = {"x": 1.0, "y": 0.0, "z": 0.0, "w": 0.0}  # 180 degrees about x: a snap frame facing the other way
G_EARTH = load_body("earth").gravity.value
G_MOON = load_body("moon").gravity.value
BOB_KG = 1.0  # 0.05 m cube at 8000 kg/m^3
ARM_KG = 0.48  # 0.3 x 0.04 x 0.04 m at 1000 kg/m^3
HANGING_KG = ARM_KG + 2 * BOB_KG
TOP_KG = 4.0  # the tower's top block, 0.2 x 0.1 x 0.2 m at 1000 kg/m^3


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def pos(x, y, z):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def snap(ident, at, orientation=IDENT):
    return {"id": ident, "kind": "pin", "accepts": ["pin"], "badge": "declared", "source": SRC, "position": pos(*at), "orientation": orientation}


def box(ident, size, centre, snaps):
    sx, sy, sz = size
    return {
        "id": ident,
        "name": ident,
        "parameters": [],
        "snap_points": snaps,
        "shape": {
            "badge": "declared",
            "source": SRC,
            "components": [
                {"id": "b", "operation": "add", "primitive": {"kind": "box", "size_x": ax(sx), "size_y": ax(sy), "size_z": ax(sz)}, "position": pos(*centre)}
            ],
        },
    }


def material(ident, density):
    return {"id": ident, "name": ident, "density": q(density, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"), "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


def instance(ident, part, mat, at):
    return {"id": ident, "part": part, "material": mat, "pose": {"badge": "declared", "source": SRC, "position": dict(zip("xyz", at)), "orientation": IDENT}}


def joint(ident, kind, a, b, threshold):
    j = {"id": ident, "kind": kind, "a": {"instance": a[0], "snap_point": a[1]}, "b": {"instance": b[0], "snap_point": b[1]}}
    if kind == "hinge":
        j["axis"] = {"x": 0.0, "y": 1.0, "z": 0.0, "badge": "declared", "source": SRC}
    if threshold is not None:
        j["break_threshold"] = q(threshold, "N")
    return j


def swing(tip: float | None, mid: float | None, pin: float | None) -> Project:
    """The swinging arm (module docstring) with these break thresholds [N] (`None`: never breaks)."""
    parts = [
        box("base", (0.4, 0.4, 0.6), (0.0, 0.0, 0.3), [snap("pivot", (0.3, 0.0, 0.6))]),
        box("arm", (0.3, 0.04, 0.04), (0.15, 0.0, 0.0), [snap("pivot", (0.0, 0.0, 0.0), FLIP), snap("tip", (0.3, 0.0, 0.0)), snap("mid", (0.15, 0.0, -0.02))]),
        box("bob", (0.05, 0.05, 0.05), (0.0, 0.0, 0.0), [snap("face", (-0.025, 0.0, 0.0), FLIP), snap("top", (0.0, 0.0, 0.025), FLIP)]),
    ]
    return Project.model_validate(
        {
            "design": {
                "materials": [material("light", 1000.0), material("dense", 8000.0)],
                "parts": parts,
                "instances": [
                    instance("base", "base", "light", (0.0, 0.0, 0.0)),
                    instance("arm", "arm", "light", (0.3, 0.0, 0.6)),
                    instance("bob-tip", "bob", "dense", (0.625, 0.0, 0.6)),
                    instance("bob-mid", "bob", "dense", (0.45, 0.0, 0.555)),
                ],
                "joints": [
                    joint("pin", "hinge", ("base", "pivot"), ("arm", "pivot"), pin),
                    joint("weld-tip", "fixed", ("arm", "tip"), ("bob-tip", "face"), tip),
                    joint("weld-mid", "fixed", ("arm", "mid"), ("bob-mid", "top"), mid),
                ],
            },
            "world": {"planet": "earth"},
        }
    )


def breakable_tower(threshold: float) -> Project:
    data = tower().model_dump(mode="json")
    data["design"]["joints"][0]["break_threshold"] = q(threshold, "N")
    return Project.model_validate(data)


def run(project: Project, duration_s: float) -> tuple[PreviewRun, list[Frame], RunCompleted]:
    preview = PreviewRun(project, run_id="break-run", project_id="p", revision=1, duration_s=duration_s)
    items = list(preview)
    frames, ended = items[:-1], items[-1]
    check_run(preview.started, frames, ended)
    assert isinstance(ended.end, RunCompleted)
    return preview, frames, ended.end


def breaks(frames: list[Frame]) -> list[BreakEvent]:
    return [e for f in frames for e in f.events if isinstance(e, BreakEvent)]


def pose(frame: Frame, body: str) -> tuple[np.ndarray, np.ndarray]:
    p = next(p for p in frame.poses if p.body == body)
    return np.array([p.position.x, p.position.y, p.position.z]), np.array([p.orientation.w, p.orientation.x, p.orientation.y, p.orientation.z])


def relative(frame: Frame, parent: str, child: str) -> np.ndarray:
    """`child`'s position in `parent`'s frame."""
    (tp, qp), (tc, _) = pose(frame, parent), pose(frame, child)
    r = np.zeros(9)
    mujoco.mju_quat2Mat(r, qp)
    return r.reshape(3, 3).T @ (tc - tp)


# --- compile: a breakable fixed joint keeps two bodies ---------------------------------------------------------------


def test_break_runtime_breakable_fixed_joint_is_two_bodies_held_without_a_degree_of_freedom():
    welded, breakable = build_body_tree(tower()), build_body_tree(breakable_tower(100.0))
    assert [b.instances for b in welded.bodies] == [("base", "top")]
    assert [b.instances for b in breakable.bodies] == [("base",), ("top",)]
    top = breakable.body("top")
    assert top.parent == "base" and top.joint is not None and top.joint.id == "weld" and top.joint.axis == (0.0, 0.0, 0.0)
    model = compile_project(breakable_tower(100.0)).model
    assert model.nq == 7 and model.nbody == 3  # the root's free joint only: the top block has no joint element
    assert [(j.joint, j.body, j.threshold) for j in breakable_joints(breakable)] == [("weld", "top", 100.0)]


def test_break_runtime_breakable_fixed_joint_inside_a_welded_body_is_refused():
    """Two blocks welded by one fixed joint and also joined by a breakable one (a second pair of snaps at the same spots):
    the breakable joint could never come apart, so the compile refuses it."""
    data = tower().model_dump(mode="json")
    block = data["design"]["parts"][0]
    block["snap_points"] += [{**s, "id": s["id"] + "-2"} for s in block["snap_points"]]
    weld = data["design"]["joints"][0]
    data["design"]["joints"].append(
        {**weld, "id": "weld-2", "a": {"instance": "base", "snap_point": "top-2"}, "b": {"instance": "top", "snap_point": "bottom-2"}, "break_threshold": q(1.0, "N")}
    )
    with pytest.raises(CompileError) as error:
        build_body_tree(Project.model_validate(data))
    assert error.value.code is CompileErrorCode.WELDED_JOINT and error.value.joints == ("weld-2",)
    assert "could not break apart" in str(error.value)


# --- load ------------------------------------------------------------------------------------------------------------


def test_break_runtime_load_at_rest_is_the_weight_held():
    """The tower at rest on the ground: the weld holds the top block, so its load is m g (6.48 N on the moon): the step's
    force and, once the contact has settled for longer than the window, the window mean (X-10) too."""
    compiled = compile_project(breakable_tower(1.0e6))
    model, data = compiled.model, mujoco.MjData(compiled.model)
    watch = BreakWatch(compiled.tree, model, BREAK_LOAD_WINDOW.value.value)
    row = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "top")
    for _ in range(1000):  # 2 s: the contact has settled
        mujoco.mj_step(model, data)
        assert watch.over(model, data) == ()
    load = float(np.linalg.norm(data.cfrc_int[row, 3:6]))
    assert load == pytest.approx(TOP_KG * G_MOON, rel=1e-6)
    assert watch.loads["weld"] == pytest.approx(TOP_KG * G_MOON, rel=1e-6)


@pytest.mark.parametrize(("factor", "expect_break"), [(0.9, True), (1.5, False)])
def test_break_runtime_a_joint_breaks_when_its_load_is_over_the_threshold(factor, expect_break):
    """The tower's weld at 0.9 m g breaks (the weight it holds is over it); at 1.5 m g it holds. While the ground's contact
    settles one step's force reads up to 1.17 m g (measured at tick 2, then down to m g); the window mean (X-10) counts the
    force before the run's start as 0, so it rises to m g over the first 0.02 s."""
    threshold = factor * TOP_KG * G_MOON
    preview, frames, _ = run(breakable_tower(threshold), 1.0)
    events = breaks(frames)
    assert BREAK_LABEL in preview.started.model_labels
    if expect_break:
        assert [(e.joint, e.threshold.value) for e in events] == [("weld", threshold)]
        assert events[0].load.value > threshold and events[0].load.unit == "N"
    else:
        assert events == []


# --- the drop test ----------------------------------------------------------------------------------------------------


def test_break_runtime_drop_releases_only_the_expected_joint():
    """The arm drops: `weld-tip` (2 m g) breaks on the way down; `weld-mid` (6 m g) and `pin` (10 x hanging weight) hold."""
    tip, mid, pin = 2 * BOB_KG * G_EARTH, 6 * BOB_KG * G_EARTH, 10 * HANGING_KG * G_EARTH
    preview, frames, _ = run(swing(tip, mid, pin), 0.4)
    events = breaks(frames)
    assert [(e.joint, e.threshold.value) for e in events] == [("weld-tip", tip)]
    event = events[0]
    assert event.load.value > tip
    carrier = next(f for f in frames if event in f.events)
    previous = frames[frames.index(carrier) - 1]
    assert previous.tick < event.tick <= carrier.tick  # the next frame carries it
    assert 0 < event.tick < 200  # during the swing, not at the saved pose
    bodies = [b.id for b in preview.started.bodies]
    # C-05b contact transitions share the frame; the wire must preserve the break and every contact, in stream order.
    assert decode_frame(encode_frame(carrier, bodies), preview.started.run_id, bodies).events == carrier.events
    # before the break the tip block rides on the arm; after it, it falls away; the middle block stays where it was welded
    start = relative(frames[0], "arm", "bob-tip")
    before = [f for f in frames if f.tick < event.tick]
    assert all(np.allclose(relative(f, "arm", "bob-tip"), start, atol=1e-9) for f in before)
    assert np.linalg.norm(relative(frames[-1], "arm", "bob-tip") - start) > 0.05
    mid_start = relative(frames[0], "arm", "bob-mid")
    assert all(np.allclose(relative(f, "arm", "bob-mid"), mid_start, atol=1e-9) for f in frames)
    # the arm swung (the hinge holds it to the base: its pivot stays put)
    assert pose(frames[-1], "arm")[0] == pytest.approx(pose(frames[0], "arm")[0], abs=1e-3)


def test_break_runtime_without_breaks_the_swing_loads_stay_under_the_holding_thresholds():
    """The same drop with no joint able to break: the largest loads the run reads (window means, X-10) stay under the
    thresholds that hold above and over the one that breaks, so the selection does not sit on a knife edge."""
    compiled = compile_project(swing(1.0e9, 1.0e9, 1.0e9))
    model, data = compiled.model, mujoco.MjData(compiled.model)
    watch = BreakWatch(compiled.tree, model, BREAK_LOAD_WINDOW.value.value)
    peak = {j.joint: 0.0 for j in watch.joints}
    for _ in range(200):
        mujoco.mj_step(model, data)
        watch.over(model, data)
        for name, load in watch.loads.items():
            peak[name] = max(peak[name], load)
    assert peak["weld-tip"] > 3.0 * BOB_KG * G_EARTH  # a pendulum's bottom-of-swing pull, above 2 m g
    assert peak["weld-mid"] < 6 * BOB_KG * G_EARTH
    assert peak["pin"] < 10 * HANGING_KG * G_EARTH


def test_break_runtime_a_broken_hinge_releases_its_subtree_and_the_ground_breaks_the_rest():
    """`pin` at 1.5 x the hanging weight breaks during the swing: the arm and both blocks fly off as one piece (the welds
    hold it together) until it hits the ground, where the impact breaks both welds (the tip block lands first: `weld-tip`
    goes over its threshold a few ticks before `weld-mid`)."""
    tip, mid, pin = 2 * BOB_KG * G_EARTH, 6 * BOB_KG * G_EARTH, 1.5 * HANGING_KG * G_EARTH
    _, frames, _ = run(swing(tip, mid, pin), 0.4)
    events = breaks(frames)
    assert [e.joint for e in events] == ["pin", "weld-tip", "weld-mid"]
    first, *impact = events
    assert impact[1].tick > impact[0].tick > first.tick
    assert all(e.load.value > e.threshold.value for e in events)
    flying = [f for f in frames if first.tick < f.tick < impact[0].tick]
    assert flying
    for body in ("bob-tip", "bob-mid"):
        start = relative(frames[0], "arm", body)
        assert all(np.allclose(relative(f, "arm", body), start, atol=1e-9) for f in flying)
    pivot = pose(frames[0], "arm")[0]
    assert np.linalg.norm(pose(frames[-1], "arm")[0] - pivot) > 0.1  # the arm left the base


def test_break_runtime_is_deterministic():
    tip, mid, pin = 2 * BOB_KG * G_EARTH, 6 * BOB_KG * G_EARTH, 1.5 * HANGING_KG * G_EARTH
    _, frames_a, end_a = run(swing(tip, mid, pin), 0.4)
    _, frames_b, end_b = run(swing(tip, mid, pin), 0.4)
    assert breaks(frames_a) and frames_a == frames_b
    assert end_a.trajectory.hash == end_b.trajectory.hash


# --- release and carried state ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("broken", [["pin"], ["weld-tip"], ["pin", "weld-mid", "weld-tip"]])
def test_break_runtime_carry_state_keeps_every_pose_and_velocity(broken):
    """After 0.15 s of the swing, the model compiled without `broken` starts in the same state: every body's frame has the
    same world pose and the same 6-D velocity (the poses and speeds are carried, nothing jumps)."""
    compiled = compile_project(swing(1.0e9, 1.0e9, 1.0e9))
    model, data = compiled.model, mujoco.MjData(compiled.model)
    for _ in range(75):
        mujoco.mj_step(model, data)
    tree = release(compiled.tree, broken)
    held = {"pin": "arm", "weld-tip": "bob-tip", "weld-mid": "bob-mid"}
    assert [b.id for b in tree.roots] == [b.id for b in compiled.tree.bodies if b.id == "base" or b.id in {held[j] for j in broken}]
    new_model = mujoco.MjModel.from_xml_string(to_mjcf(tree, drives=compiled.drives.without_joints(broken)))
    assert new_model.nq == model.nq + 7 * len(broken) - sum(1 for j in broken if j == "pin")
    new_data = carry_state(model, data, new_model)
    for m, d in ((model, data), (new_model, new_data)):
        mujoco.mj_forward(m, d)
    for body in ("base", "arm", "bob-tip", "bob-mid"):
        a, b = (mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, body) for m in (model, new_model))
        assert np.allclose(data.xpos[a], new_data.xpos[b], rtol=0.0, atol=1e-12)
        assert np.allclose(data.xmat[a], new_data.xmat[b], rtol=0.0, atol=1e-12)
        va, vb = np.zeros(6), np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_XBODY, a, va, 0)
        mujoco.mj_objectVelocity(new_model, new_data, mujoco.mjtObj.mjOBJ_XBODY, b, vb, 0)
        assert np.allclose(va, vb, rtol=0.0, atol=1e-12)
    assert new_data.time == data.time


# --- what follows the new model after a break: motors, batteries, tanks, drag -------------------------------------------


def _actuate(ident, actuator, start, end, command):
    return {"type": "actuate", "id": ident, "actuator": actuator, "start": start, "end": end, "command": command, "badge": "declared", "source": SRC}


def _with(project: Project, *, joint: str, threshold: float, entries: list[dict], planet: str | None = None) -> Project:
    data = project.model_dump(mode="json")
    next(j for j in data["design"]["joints"] if j["id"] == joint)["break_threshold"] = q(threshold, "N")
    data["design"]["schedule"] = {"entries": entries}
    if planet is not None:
        data["world"]["planet"] = planet
    return Project.model_validate(data)


@pytest.fixture
def spied(monkeypatch):
    """Record, per step, what the run's motor, tank and drag runtimes hold: subclasses swapped into `run.preview`, so the
    run builds (and after a break rebinds) them exactly as it does unspied. Each record is keyed by the tick the step ends."""
    from kinetra_engine.run import preview

    log: dict[str, dict[int, tuple]] = {"drive": {}, "thrust": {}, "drag": {}}

    class Drive(preview.DriveRuntime):
        def apply(self, data, commands, dt):
            super().apply(data, commands, dt)
            tick = round(float(data.time) / dt) + 1
            log["drive"][tick] = (dict(self.supplies), dict(self.energy), [(m.actuator, float(data.ctrl[a]), float(data.qvel[d])) for m, a, d in self._rows])

    class Thrust(preview.ThrustRun):
        def end_step(self):
            super().end_step()
            tick = round(float(self._d.time) / float(self._m.opt.timestep))
            log["thrust"][tick] = ({i: s.remaining for i, s in self.supplies.items()}, {b: float(self._m.body_mass[r]) for b, r in self._row.items()}, self._m)

    class Drag(preview.DragRuntime):
        def apply(self, data):
            super().apply(data)
            tick = round(float(data.time) / float(self.model.opt.timestep)) + 1
            log["drag"][tick] = (len(self._saved), self.model)

    monkeypatch.setattr(preview, "DriveRuntime", Drive)
    monkeypatch.setattr(preview, "ThrustRun", Thrust)
    monkeypatch.setattr(preview, "DragRuntime", Drag)
    return log


def _one_break(project: Project) -> tuple[PreviewRun, int]:
    preview, frames, _ = run(project, 0.3)
    (event,) = breaks(frames)
    return preview, event.tick


def test_break_runtime_motor_battery_and_drag_follow_the_recompiled_model(spied):
    """The X-01b gearmotor rig on Earth (`test_actuator.motor_rig(supply=True)`: motor and wheel on hinge `axle`, bracket, battery
    `b1` on fixed `clip`). `drive` is 0 until 0.1 s, then 1: the start's reaction breaks `clip` (2 N; it holds the battery's
    0.48 N weight at rest, and its window load after the start reaches 4.45 N, measured with `clip` unbreakable). Across the
    break tick the motor keeps driving its hinge (ctrl still written, speed still rising), the
    battery is not reset (remaining + energy taken = the start charge at every step, remaining never rises) and drag is still
    applied to every body of the new model."""
    from test_actuator import motor_rig

    project = _with(motor_rig(supply=True), joint="clip", threshold=2.0, entries=[_actuate("spin", "drive", 0.1, 1.0, 1.0)])
    preview, tick = _one_break(project)
    assert 50 < tick < 60  # after the motor starts at 0.1 s (tick 50), not while the rig settles
    drive, drag = spied["drive"], spied["drag"]
    start = preview.compiled.drives.supplies[0][1].remaining
    remaining = [drive[k][0]["b1"].remaining for k in sorted(drive)]
    assert all(b <= a for a, b in zip(remaining, remaining[1:]))
    for k in sorted(drive):
        supplies, energy, _ = drive[k]
        assert supplies["b1"].remaining + energy["drive"] == pytest.approx(start, rel=0.0, abs=1e-9)
    change = next(k for k in sorted(drag) if k > 1 and drag[k][1] is not drag[k - 1][1])
    window = range(change - 1, change + 4)  # releasing internal step (old model) and four on the new model
    speeds = [drive[k][2][0][2] for k in window]
    assert all(drive[k][2][0][0] == "drive" and drive[k][2][0][1] > 0.0 for k in window)  # the motor still writes its torque
    assert all(b > a for a, b in zip(speeds, speeds[1:]))  # and its hinge keeps speeding up through the recompile
    assert drive[change][0]["b1"].remaining < drive[change - 1][0]["b1"].remaining  # the battery keeps paying for it
    before, after = drag[change - 1], drag[change]
    assert after[1] is not before[1] and after[1].nq == before[1].nq + 7  # bound to the recompiled model (b1 got a free joint)
    assert before[0] == after[0] == len(preview.started.bodies)  # every body still gets its drag


def test_break_runtime_tank_propellant_and_mass_follow_the_recompiled_model(spied):
    """`test_thrust.rocket` (tank on the 2 lbf thruster) on the Moon with its weld `w` breakable at 6.5 N: at rest the weld
    holds the tank's weight (3.01 kg x 1.62 = 4.9 N); the burn from 0.1 s pushes the jet into the tank and breaks it. Across
    the break the propellant left keeps falling by the burn's draw (no refill, no reset) and the tank body of the recompiled
    model carries it: its mass minus the propellant left is the tank's dry mass at every step, before and after."""
    from test_thrust import rocket

    project = _with(rocket([]), joint="w", threshold=6.5, entries=[_actuate("burn", "main", 0.1, 0.5, 1.0)], planet="moon")
    _, tick = _one_break(project)
    assert 50 < tick < 60  # during the ignition at 0.1 s (tick 50)
    thrust = spied["thrust"]
    left = {k: thrust[k][0]["tank"] for k in sorted(thrust)}
    dry = {k: thrust[k][1]["tank"] - left[k] for k in sorted(thrust)}
    change = next(k for k in sorted(thrust) if k > 1 and thrust[k][2] is not thrust[k - 1][2])
    assert thrust[change][2] is not thrust[change - 1][2]  # the step after the break ran on the recompiled model
    assert all(d == pytest.approx(dry[change - 1], rel=0.0, abs=1e-12) for d in dry.values())  # propellant on the new model too
    ks = sorted(left)
    burn_start = 800  # 0.1 s at the default public tick's 0.000125 s internal step
    assert all(left[b] < left[a] for a, b in zip(ks, ks[1:]) if b > burn_start)  # strictly falling, through the break
    draw = [left[k - 1] - left[k] for k in range(change - 1, change + 3)]
    assert all(d > 0.0 for d in draw) and max(draw) / min(draw) < 2.0  # the step's draw does not jump at the break


def test_break_runtime_release_refuses_a_joint_that_holds_nothing():
    tree = build_body_tree(swing(None, None, None))
    with pytest.raises(ValueError, match="held by joint"):
        release(tree, ["nope"])


def test_break_runtime_no_threshold_no_label_no_event():
    preview, frames, _ = run(tower(), 0.1)
    assert BREAK_LABEL not in preview.started.model_labels
    assert breaks(frames) == []
    assert math.isclose(frames[-1].sim_time_s, 0.1)
