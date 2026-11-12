"""X-08: a separation schedule entry releases a separator's `face_b` joint during the run and pushes the two sides apart.

`uv run pytest packages/engine -q -k separation`

The scenes, values chosen by the test (`SRC`), not data:

- `pair`: two boxes and the library separator (`separator.json`) lying along +x on the ground: box `a` (0.2 x 0.1 x 0.1 m at
  1000 kg/m^3 = 2 kg) at the separator's `face_a`, box `b` (the same at 2000 kg/m^3 = 4 kg) at its `face_b`; the separator's
  mass is declared 0.5 kg and its impulse `J` 1 N*s. For the momentum test the planet's gravity is set to 0 (`zero_g`: the
  compiled planet constant is replaced in the test, and the run labels it) and the pair is lifted `LIFT` = 0.5 micrometre:
  inside the 1 micrometre placement tolerance, so the compiler counts it on the ground (X-01d `floating`), and above the
  ground's contact, so nothing touches it in zero g. With no force on them, a separation that gives the side of `face_a`
  (box `a` + separator, 2.5 kg) `+J x` and the side of `face_b` (box `b`, 4 kg) `-J x` must leave them at
  `v_a = J / 2.5 = +0.4 m/s` and `v_b = -J / 4 = -0.25 m/s`, total momentum 0 (hand calculation).
- `stages`: on the Moon, a booster cube on the ground, the separator turned over (its `face_b` up), an upper cube and the
  library thruster on its roof, nozzle up. The upper stage leaves; its thruster fires on its own entry after the separation.
"""

from __future__ import annotations

import dataclasses
import json
import math

import mujoco
import numpy as np
import pytest
from gltf_samples import catalog_material, library_part
from pydantic import ValidationError

from kinetra_core import (
    AddControlEntry,
    BreakEvent,
    CommandRejected,
    Frame,
    Project,
    RemoveInstance,
    RunCompleted,
    SeparateEntry,
    SeparationEvent,
    apply_command,
    check_run,
    decode_frame,
    encode_frame,
)
from kinetra_engine.compiler import (
    SEPARATION_LABEL,
    CompileError,
    CompileErrorCode,
    build_body_tree,
    compile_thrust,
    release,
    separator_joints,
    to_mjcf,
)
from kinetra_engine.compiler import bodytree
from kinetra_engine.parts import assembly_mass
from kinetra_engine.run import PreviewRun, compile_project

SRC = {"ref": "X-08 test fixture: value chosen by the test", "locator": "test_separation.py"}
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
S45 = math.sqrt(0.5)
TO_X = {"x": 0.0, "y": S45, "z": 0.0, "w": S45}  # +90 degrees about y: local +z is world +x
FLIP = {"x": 1.0, "y": 0.0, "z": 0.0, "w": 0.0}  # 180 degrees about x: local +z is world -z
SEPARATOR = library_part("separator")
THRUSTER = library_part("thruster-vacco-48003040")
J = 1.0  # N*s, declared
M_SEP = 0.5  # kg, declared
M_A, M_B = 2.0, 4.0  # kg: 0.2 x 0.1 x 0.1 m boxes at 1000 and 2000 kg/m^3
L = 0.04  # the separator's default length [m]
R = 0.05  # and radius


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def pos(x, y, z):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def snap(ident, kind, at, orientation=IDENT):
    return {"id": ident, "kind": kind, "accepts": [kind], "badge": "declared", "source": SRC, "position": pos(*at), "orientation": orientation}


def box(ident, size, snaps):
    sx, sy, sz = size
    return {
        "id": ident,
        "name": ident,
        "parameters": [],
        "snap_points": snaps,
        "shape": {
            "badge": "declared",
            "source": SRC,
            "components": [{"id": "b", "operation": "add", "primitive": {"kind": "box", "size_x": ax(sx), "size_y": ax(sy), "size_z": ax(sz)}, "position": pos(0, 0, 0)}],
        },
    }


def material(ident, density):
    return {"id": ident, "name": ident, "density": q(density, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"), "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


def instance(ident, part, at, orientation=IDENT, material=None, params=()):
    inst = {"id": ident, "part": part, "pose": {"badge": "declared", "source": SRC, "position": dict(zip("xyz", at)), "orientation": orientation}, "parameters": list(params)}
    if material is not None:
        inst["material"] = material
    return inst


def separator(ident, at, orientation, impulse=J):
    params = [{"name": "mass", **q(M_SEP, "kg")}, {"name": "separation_impulse", **q(impulse, "N*s")}]
    return instance(ident, "separator", at, orientation, params=params)


def fixed(ident, a, b):
    return {"id": ident, "kind": "fixed", "a": {"instance": a[0], "snap_point": a[1]}, "b": {"instance": b[0], "snap_point": b[1]}}


def separate(ident, sep, at):
    return {"type": "separate", "id": ident, "separator": sep, "at": at, "badge": "declared", "source": SRC}


def actuate(ident, actuator, start, end, command):
    return {"type": "actuate", "id": ident, "actuator": actuator, "start": start, "end": end, "command": command, "badge": "declared", "source": SRC}


SLAB = box("slab", (0.2, 0.1, 0.1), [snap("end-p", "surface", (0.1, 0.0, 0.0), TO_X), snap("end-n", "surface", (-0.1, 0.0, 0.0), TO_X)])


LIFT = 0.5e-6  # m: under `kinetra_core.validator.PLACEMENT_TOLERANCE` (1e-6 m), so still on the ground for the compiler


def pair(entries=(), impulse=J, planet="moon", lift=0.0) -> Project:
    """Box `b`, separator `sep`, box `a` along +x, resting on the ground (z = 0 under each, plus `lift`)."""
    return Project.model_validate(
        {
            "design": {
                "materials": [material("light", 1000.0), material("dense", 2000.0)],
                "parts": [SLAB, json.loads(SEPARATOR.model_dump_json())],
                "instances": [
                    instance("a", "slab", (0.02 + 0.1, 0.0, 0.05 + lift), material="light"),
                    instance("b", "slab", (-0.02 - 0.1, 0.0, 0.05 + lift), material="dense"),
                    separator("sep", (0.0, 0.0, R + lift), TO_X, impulse),
                ],
                "joints": [fixed("hold-a", ("sep", "face_a"), ("a", "end-n")), fixed("hold-b", ("b", "end-p"), ("sep", "face_b"))],
                "schedule": {"entries": list(entries)},
            },
            "world": {"planet": planet},
        }
    )


@pytest.fixture
def zero_g(monkeypatch):
    """The compiled planet with gravity 0: every model this run compiles (also after a separation) has no gravity."""
    real = bodytree.planet_physics

    def weightless(planet_id, directory=None):
        p = real(planet_id, directory)
        return dataclasses.replace(p, gravity=p.gravity.model_copy(update={"value": 0.0}))

    monkeypatch.setattr(bodytree, "planet_physics", weightless)


def run(project: Project, duration_s: float, manual: dict[int, str] | None = None) -> tuple[PreviewRun, list[Frame], RunCompleted]:
    """Run `project`; `manual` asks `PreviewRun.separate` right after the frame of that tick is read."""
    preview = PreviewRun(project, run_id="separation-run", project_id="p", revision=1, duration_s=duration_s, frame_every_ticks=1)
    items = []
    for item in preview:
        items.append(item)
        if manual and isinstance(item, Frame) and item.tick in manual:
            preview.separate(manual[item.tick])
    frames, ended = items[:-1], items[-1]
    check_run(preview.started, frames, ended)
    assert isinstance(ended.end, RunCompleted)
    return preview, frames, ended.end


def separations(frames: list[Frame]) -> list[SeparationEvent]:
    return [e for f in frames for e in f.events if isinstance(e, SeparationEvent)]


def position(frame: Frame, body: str) -> np.ndarray:
    p = next(p for p in frame.poses if p.body == body)
    return np.array([p.position.x, p.position.y, p.position.z])


def velocity(frames: list[Frame], body: str, tick: int) -> np.ndarray:
    """Mean velocity [m/s] of `body`'s frame over the step that ends at `tick` (one frame per tick)."""
    f0, f1 = next(f for f in frames if f.tick == tick - 1), next(f for f in frames if f.tick == tick)
    return (position(f1, body) - position(f0, body)) / (f1.sim_time_s - f0.sim_time_s)


# --- the schedule entry ------------------------------------------------------------------------------------------------


def test_separation_entry_is_on_the_one_schedule_with_a_type_tag():
    """The entry sits in `ControlSchedule.entries` with the actuate entries (no separate staging list); `type` tells them apart."""
    stages_burn = stages([separate("stage", "sep", 0.1), actuate("burn", "main", 0.2, 0.3, 1.0)]).design.schedule
    assert [type(e).__name__ for e in stages_burn.entries] == ["SeparateEntry", "ActuateEntry"]
    (entry,) = stages_burn.separations
    assert isinstance(entry, SeparateEntry) and (entry.type, entry.separator, entry.at) == ("separate", "sep", 0.1)
    assert [e.id for e in stages_burn.actuations] == ["burn"]
    with pytest.raises(ValidationError):
        SeparateEntry.model_validate({**separate("stage", "sep", 0.1), "type": "actuate"})


def test_separation_entry_must_name_a_separator_instance():
    with pytest.raises(ValidationError, match="unknown separator instance 'ghost'"):
        pair([separate("stage", "ghost", 0.1)])
    with pytest.raises(ValidationError, match="releases a separator, but instance 'a' is part 'slab' with no role"):
        pair([separate("stage", "a", 0.1)])
    with pytest.raises(ValidationError):
        pair([{**separate("stage", "sep", 0.1), "at": -1.0}])  # a time is not negative


def test_separation_entry_comes_and_goes_with_commands_and_its_separator():
    project = pair()
    added = apply_command(project, AddControlEntry(type="add_control_entry", entry=separate("stage", "sep", 0.1))).project
    assert added.design.schedule.separations[0].id == "stage"
    removed = apply_command(added, RemoveInstance(type="remove_instance", id="sep"))
    assert removed.project.design.schedule.entries == ()  # the separator's entry goes with it
    assert apply_command(removed.project, removed.inverse).project == added  # and comes back with the undo
    with pytest.raises(CommandRejected):
        apply_command(project, AddControlEntry(type="add_control_entry", entry=separate("stage", "a", 0.1)))


# --- compile errors: contradicting and repeated separations --------------------------------------------------------------


def compile_error(project: Project) -> CompileError:
    with pytest.raises(CompileError) as e:
        build_body_tree(project)
    return e.value


def test_separation_two_entries_at_one_time_are_a_compile_error():
    e = compile_error(pair([separate("go", "sep", 0.1), separate("stop", "sep", 0.1)]))
    assert e.code is CompileErrorCode.SEPARATION_CONFLICT
    assert e.instances == ("sep", "b") and e.parts == ("separator", "slab") and e.joints == ("hold-b",)
    assert "'go' and 'stop'" in str(e) and "at one time" in str(e)


def test_separation_a_second_separation_of_one_separator_is_a_compile_error():
    e = compile_error(pair([separate("later", "sep", 0.3), separate("first", "sep", 0.1)]))
    assert e.code is CompileErrorCode.SEPARATION_TWICE
    assert e.instances == ("sep", "b") and e.joints == ("hold-b",)
    assert "'first' and 'later'" in str(e) and "cannot be undone" in str(e)


def test_separation_of_a_separator_holding_nothing_at_face_b_is_a_compile_error():
    data = pair([separate("stage", "sep", 0.1)]).model_dump(mode="json")
    data["design"]["joints"] = [j for j in data["design"]["joints"] if j["id"] != "hold-b"]
    data["design"]["instances"] = [i for i in data["design"]["instances"] if i["id"] != "b"]
    e = compile_error(Project.model_validate(data))
    assert e.code is CompileErrorCode.SEPARATION_UNJOINED and e.instances == ("sep",) and e.parts == ("separator",)


# --- compile: the face_b joint keeps two bodies -------------------------------------------------------------------------


def test_separation_face_b_joint_is_held_without_a_degree_of_freedom_and_face_a_is_welded():
    """`hold-a` welds box `a` and the separator into one body; `hold-b` (at `face_b`, box `b` its `a` side, so `b` is the
    root) holds them as a second body without a degree of freedom, as a breakable fixed joint does (X-04b)."""
    tree = build_body_tree(pair())
    assert [b.instances for b in tree.bodies] == [("b",), ("a", "sep")]
    held = tree.body("a")
    assert held.parent == "b" and held.joint is not None and held.joint.id == "hold-b" and held.joint.axis == (0.0, 0.0, 0.0)
    assert list(separator_joints(tree.design)) == ["sep"]
    sj = separator_joints(tree.design)["sep"]
    assert (sj.joint, sj.held, sj.impulse) == ("hold-b", "b", J)
    assert compile_project(pair()).model.nq == 7  # one free root; the held body has no joint element


def test_separation_remaining_side_mass_and_centre_of_mass_are_the_sums_of_its_parts():
    """After the release the side that keeps the separator is box `a` + the separator: in the recompiled model its free body's
    subtree mass is 2.5 kg and its centre of mass the mass-weighted mean of the two instances' centres (both on the x axis at
    z = 0.05: (2 x 0.12 + 0.5 x 0) / 2.5 = 0.096 m); the side that left is box `b` alone, 4 kg at x = -0.12 m."""
    project = pair()
    tree = release(build_body_tree(project), ["hold-b"])
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    rows = {b: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b) for b in ("a", "b")}
    by_instance = {r.instance: r.mass for r in assembly_mass(project.design).instances}
    assert by_instance == pytest.approx({"a": M_A, "sep": M_SEP, "b": M_B}, rel=1e-12)
    assert model.body_subtreemass[rows["a"]] == pytest.approx(M_A + M_SEP, rel=1e-12)
    assert model.body_subtreemass[rows["b"]] == pytest.approx(M_B, rel=1e-12)
    assert data.subtree_com[rows["a"]] == pytest.approx(((M_A * 0.12 + M_SEP * 0.0) / (M_A + M_SEP), 0.0, 0.05), abs=1e-12)
    assert data.subtree_com[rows["b"]] == pytest.approx((-0.12, 0.0, 0.05), abs=1e-12)


# --- the run -----------------------------------------------------------------------------------------------------------


def test_separation_in_zero_g_matches_the_momentum_hand_calculation(zero_g):
    """`pair` without gravity, separated at 0.01 s (tick 6: the step from 0.010 s): before, nothing moves; after, box `a`
    goes +x at J / (m_a + m_sep) = 0.4 m/s and box `b` -x at J / m_b = 0.25 m/s, and the total momentum stays 0."""
    preview, frames, _ = run(pair([separate("stage", "sep", 0.01)], lift=LIFT), 0.05)
    (event,) = separations(frames)
    assert event.tick == 6 and (event.separator, event.joint, event.entry) == ("sep", "hold-b", "stage")
    assert event.impulse.value == J and event.impulse.unit == "N*s"
    assert any(label.startswith("미적용:") for label in preview.started.model_labels)  # the run says gravity is not the planet's
    still = [velocity(frames, b, k) for b in ("a", "b") for k in range(1, event.tick)]
    assert all(np.allclose(v, 0.0, atol=1e-12) for v in still)
    for k in range(event.tick, frames[-1].tick + 1):
        va, vb = velocity(frames, "a", k), velocity(frames, "b", k)
        assert va == pytest.approx((J / (M_A + M_SEP), 0.0, 0.0), abs=1e-9)
        assert vb == pytest.approx((-J / M_B, 0.0, 0.0), abs=1e-9)
        assert (M_A + M_SEP) * va + M_B * vb == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_separation_event_reason_is_intended_separation_and_is_never_a_break():
    preview, frames, _ = run(pair([separate("stage", "sep", 0.01)]), 0.03)
    (event,) = separations(frames)
    assert event.kind == "separation" and event.reason == "intended_separation"
    assert not [e for f in frames for e in f.events if isinstance(e, BreakEvent)]
    assert SEPARATION_LABEL in preview.started.model_labels
    carrier = next(f for f in frames if event in f.events)
    bodies = [b.id for b in preview.started.bodies]
    # The ground `end` belongs in the same frame; the wire preserves separation and contact events in stream order.
    assert decode_frame(encode_frame(carrier, bodies), preview.started.run_id, bodies).events == carrier.events


def test_separation_both_sides_stay_in_the_run_to_its_end():
    """Both sides are in every frame to the last tick (the body list of the run does not change, F8)."""
    preview, frames, _ = run(pair([separate("stage", "sep", 0.01)]), 0.1)
    assert [b.id for b in preview.started.bodies] == ["b", "a"]
    assert frames[-1].tick == preview.end_tick and {p.body for p in frames[-1].poses} == {"a", "b"}
    assert position(frames[-1], "a")[0] - position(frames[-1], "b")[0] > position(frames[0], "a")[0] - position(frames[0], "b")[0]


def test_separation_runs_are_deterministic():
    _, frames_a, end_a = run(pair([separate("stage", "sep", 0.01)]), 0.1)
    _, frames_b, end_b = run(pair([separate("stage", "sep", 0.01)]), 0.1)
    assert separations(frames_a) and frames_a == frames_b
    assert end_a.trajectory.hash == end_b.trajectory.hash
    _, _, end_c = run(pair([separate("stage", "sep", 0.02)]), 0.1)
    assert end_c.trajectory.hash != end_a.trajectory.hash  # the hash sees the separation's time


def test_separation_by_manual_control_takes_the_same_path(zero_g):
    """`PreviewRun.separate` after the frame of tick 5 separates at tick 6, like the entry at 0.01 s: the same frames, an event
    with no entry. A second request for the same separator is refused (a separation cannot be undone)."""
    _, scheduled, _ = run(pair([separate("stage", "sep", 0.01)], lift=LIFT), 0.03)
    preview, manual, _ = run(pair(lift=LIFT), 0.03, manual={5: "sep"})
    (event,) = separations(manual)
    assert event.tick == 6 and event.entry is None and event.reason == "intended_separation"
    assert [f.poses for f in manual] == [f.poses for f in scheduled]
    with pytest.raises(ValueError, match="cannot be undone"):
        preview.separate("sep")
    with pytest.raises(ValueError, match="not a separator"):
        preview.separate("a")
    assert preview.separators == ("sep",)


def test_separation_zero_impulse_releases_without_a_push(zero_g):
    _, frames, _ = run(pair([separate("stage", "sep", 0.01)], impulse=0.0, lift=LIFT), 0.03)
    (event,) = separations(frames)
    assert event.impulse.value == 0.0
    assert all(np.allclose(velocity(frames, b, k), 0.0, atol=1e-12) for b in ("a", "b") for k in range(1, frames[-1].tick + 1))


# --- the side that left keeps running on its own schedule -------------------------------------------------------------


MZ = 0.04729059031466532  # the thruster's mount sits at -MZ on its z axis (test_thrust.py)
CUBE = box(
    "cube",
    (0.2, 0.2, 0.2),
    [snap("top", "surface", (0.0, 0.0, 0.1)), snap("bottom", "surface", (0.0, 0.0, -0.1), FLIP), snap("roof", "face", (0.0, 0.0, 0.1))],
)
UPPER_Z = 0.2 + L + 0.1  # the upper cube's centre


def stages(entries) -> Project:
    """A 0.2 m booster cube on the ground, the separator turned over on it (`face_a` down, `face_b` up), an upper cube on the
    separator and the library thruster (catalog steel A36, as its part file is sized for) standing on the upper cube's roof,
    nozzle up: its thrust pushes down along the stack's axis, through the upper stage's centre of mass. The cubes are 100
    kg/m^3 (0.8 kg) and the impulse 1 N*s, so the upper stage (0.8 kg + the thruster) leaves upward at about 0.85 m/s."""
    thruster = json.loads(THRUSTER.model_dump_json())
    return Project.model_validate(
        {
            "design": {
                "materials": [material("foam", 100.0), json.loads(catalog_material("steel-a36").model_dump_json())],
                "parts": [CUBE, json.loads(SEPARATOR.model_dump_json()), thruster],
                "instances": [
                    instance("booster", "cube", (0.0, 0.0, 0.1), material="foam"),
                    separator("sep", (0.0, 0.0, 0.2 + 0.5 * L), FLIP),
                    instance("upper", "cube", (0.0, 0.0, UPPER_Z), material="foam"),
                    instance("jet", thruster["id"], (0.0, 0.0, UPPER_Z + 0.1 + MZ), material="steel-a36"),
                ],
                "joints": [
                    fixed("hold-booster", ("booster", "top"), ("sep", "face_a")),
                    fixed("hold-upper", ("sep", "face_b"), ("upper", "bottom")),
                    fixed("mount", ("upper", "roof"), ("jet", "mount")),
                ],
                "actuators": [{"id": "main", "kind": "thruster", "instance": "jet"}],
                "schedule": {"entries": list(entries)},
            },
            "world": {"planet": "moon"},
        }
    )


def test_separation_the_side_that_left_fires_its_thruster_on_its_own_schedule():
    """The upper stage (body `jet`: the thruster and the upper cube, welded) leaves at 0.05 s and its thruster burns from 0.1 s
    to 0.15 s. It flies the whole run in both cases (it never comes back down to the booster), so the only difference between
    the run with the burn and the one without is the thrust: the burn changes its vertical speed by the thrust impulse of that
    burn (`CompiledThruster.impulse`, the exact integral of the curve) over its mass, downward."""
    burn = [separate("stage", "sep", 0.05), actuate("burn", "main", 0.1, 0.15, 1.0)]
    preview, frames, _ = run(stages(burn), 0.25)
    assert [b.id for b in preview.started.bodies] == ["booster", "jet"]
    (event,) = separations(frames)
    assert (event.separator, event.joint) == ("sep", "hold-upper") and event.tick == 26
    _, coast, _ = run(stages(burn[:1]), 0.25)
    assert [f.poses for f in coast[:51]] == [f.poses for f in frames[:51]]  # the same until the burn's first step (tick 51)
    lowest = min(position(f, "jet")[2] for f in frames[26:])
    assert lowest > position(frames[0], "jet")[2]  # in the air after the separation: above where it started
    model = compile_thrust(stages(burn))
    (th,) = model.thrusters
    expected = -th.impulse(0.0, 0.25) / model.tree.body("jet").mass
    k = frames[-1].tick
    dv = velocity(frames, "jet", k) - velocity(coast, "jet", k)
    assert dv == pytest.approx((0.0, 0.0, expected), rel=1e-3, abs=1e-9)
