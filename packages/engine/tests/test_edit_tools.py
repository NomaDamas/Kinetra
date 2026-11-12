"""G-02a: the agent's edit tools. Every call becomes a `Command` that `validate_command` (C-02c) judges; a call that breaks a tool's
schema is refused before anything is built.

    uv run pytest packages/engine -q -k edit_tools

Expected poses below are worked by hand from the part definitions (heights and snap offsets are in the comments), and the four-wheel
car is compared with the poses of `schemas/examples/DesignSpec.four-wheel-car.json`, which was written by hand.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

import kinetra_engine.agent.edit_tools as edit_tools_module
from kinetra_core import (
    Badge,
    CommandBatch,
    DesignSpec,
    Origin,
    PartDef,
    Project,
    ReasonCode,
    apply_command,
    check_placement,
    missing_definitions,
)
from kinetra_engine.agent import TOOL_NAMES, EditTools, HubEditTools, load_library, specs
from kinetra_engine.protocol import Hub

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "schemas" / "examples"
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def empty(planet="earth"):
    return Project.model_validate({"world": {"planet": planet}})


@pytest.fixture(scope="module")
def tools():
    return EditTools(clock=lambda: NOW)


def run(tools, project, tool, args):
    return tools.run(project, tool, json.dumps(args))


def ok(tools, project, tool, args):
    r = run(tools, project, tool, args)
    assert r.ok, r.reasons
    return r


def codes(result):
    return [r.code for r in result.reasons]


def pos(project, ident):
    p = next(i for i in project.design.instances if i.id == ident).pose.position
    return (p.x, p.y, p.z)


def near(a, b, tol=1e-9):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


GROUND = {"type": "on_ground"}


def snap(point, instance, target_point, facing="opposed", **more):
    return {"type": "snap_to", "snap_point": point, "target": {"instance": instance, "snap_point": target_point}, "facing": facing, **more}


@pytest.fixture
def tower(tools):
    """plate on the ground, a beam standing on it (beam length 0.1 m so it fits the 0.3 x 0.2 m plate)."""
    p = ok(tools, empty(), "add_part", {"part": "plate", "place": GROUND, "material": "al6061-t6"}).project
    return ok(
        tools, p, "add_part", {"part": "beam", "parameters": {"length": 0.1}, "place": snap("bottom", "plate-1", "top"), "material": "steel-a36"}
    ).project


# --- the tools and their schemas ---------------------------------------------------------------------------------


def test_edit_tools_specs_are_function_tools_for_the_gateway():
    s = specs()
    assert [t["function"]["name"] for t in s] == list(TOOL_NAMES) and len(s) == 13
    for t in s:
        assert t["type"] == "function" and t["function"]["description"]
        params = t["function"]["parameters"]
        assert params["type"] == "object" and params.get("additionalProperties") is False
    json.dumps(s)  # what Gateway.chat puts in the request body


def test_edit_tools_no_schema_has_a_field_for_a_planet_constant_or_a_verdict():
    from kinetra_core import PLANET_CONSTANT_NAMES
    from kinetra_core.validator import VERDICT_FIELD_NAMES

    def names(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    yield from value
                yield from names(value)
        elif isinstance(node, list):
            for item in node:
                yield from names(item)

    forbidden = set(PLANET_CONSTANT_NAMES) | set(VERDICT_FIELD_NAMES)
    assert not forbidden & set(names(specs()))


def _property_names(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties":
                yield from value
            yield from _property_names(value)
    elif isinstance(node, list):
        for item in node:
            yield from _property_names(item)


def test_edit_tools_the_only_coordinates_are_a_ground_spot_and_no_tool_takes_a_pose():
    """Position is a snap point: no field is a pose, an orientation, a quaternion or a position. The one numeric place is `on_ground`
    (x and y only: z is computed from the shape), the spot where nothing exists yet to snap to."""
    names = set(_property_names(specs()))
    assert not names & {"pose", "orientation", "quaternion", "position", "w", "rotation", "yaw"}
    on_ground = [t for t in specs() if t["function"]["name"] == "add_part"][0]["function"]["parameters"]["$defs"]["OnGround"]
    assert set(on_ground["properties"]) == {"type", "x", "y"}


# --- schema violations are refused ---------------------------------------------------------------------------------

BAD_CALLS = [
    ("no_such_tool", {}, "unknown tool"),
    ("add_part", "not json {", "not JSON"),
    ("add_part", "[1, 2]", "JSON object"),
    ("add_part", {"part": "plate"}, "place"),  # missing field
    ("add_part", {"part": "plate", "place": GROUND, "pose": {"x": 1}}, "pose"),  # no coordinates for a part
    ("add_part", {"part": "plate", "place": {"type": "teleport"}}, "place"),
    ("add_part", {"part": "Plate!", "place": GROUND}, "part"),  # not an id
    ("add_part", {"part": "plate", "place": {"type": "on_ground", "x": "1"}}, "x"),  # a string for a number
    ("add_part", {"part": "plate", "place": {"type": "on_ground", "x": True}}, "x"),  # a boolean for a number
    ("add_part", {"part": "plate", "place": {"type": "on_ground", "x": float("nan")}}, "x"),
    ("add_part", {"part": "plate", "place": GROUND, "parameters": {"length": "0.3"}}, "length"),
    ("add_part", {"part": "plate", "place": GROUND, "parameters": {"Length": 0.3}}, "Length"),
    ("add_part", {"part": "plate", "place": snap("top", "plate-1", "top", "sideways")}, "facing"),
    ("add_part", {"part": "plate", "place": snap("top", "plate-1", "top", roll_quarter_turns=4)}, "roll_quarter_turns"),
    ("add_part", {"part": "plate", "place": snap("top", "plate-1", "top", roll_quarter_turns=1.5)}, "roll_quarter_turns"),
    ("add_part", {"part": "plate", "place": snap("top", "plate-1", "top", joint={"kind": "ball"})}, "kind"),
    ("add_part", {"part": "plate", "place": snap("top", "plate-1", "top", joint={"break_threshold": -5})}, "break_threshold"),
    ("remove_part", {}, "instance"),
    ("remove_part", {"instance": "x", "force": True}, "force"),
    ("set_parameter", {"instance": "a", "name": "length"}, "value"),
    ("set_parameter", {"instance": "a", "name": "length", "value": None}, "value"),
    ("set_parameter", {"instance": "a", "name": "length", "value": "long"}, "value"),
    ("set_material", {"instance": "a"}, "material"),
    ("connect", {"a": {"instance": "a"}, "b": {"instance": "b", "snap_point": "x"}, "facing": "opposed"}, "snap_point"),
    ("set_joint", {"joint": "j", "clear": ["pose"]}, "clear"),
    ("add_actuator", {"kind": "rocket", "instance": "a"}, "kind"),
    ("schedule_command", {"actuator": "a", "start": 0, "end": 1, "command": 2}, "command"),  # outside [-1, 1]
    ("schedule_command", {"actuator": "a", "start": -1, "end": 1, "command": 1}, "start"),
    ("schedule_command", {"actuator": "a", "start": "0", "end": 1, "command": 1}, "start"),
    ("change_command", {"entry": "e", "command": float("inf")}, "command"),
]


@pytest.mark.parametrize("tool,arguments,fragment", BAD_CALLS)
def test_edit_tools_a_schema_violation_is_refused_and_builds_nothing(tools, monkeypatch, tool, arguments, fragment):
    seen = []
    monkeypatch.setattr(edit_tools_module, "validate_command", lambda *a, **k: seen.append(a))  # must never be reached
    project = empty()
    text = arguments if isinstance(arguments, str) else json.dumps(arguments, allow_nan=True)
    r = tools.run(project, tool, text)
    assert not r.ok and r.command is None and r.project is None and not seen
    assert r.reasons and all(x.code is ReasonCode.INVALID_COMMAND for x in r.reasons)
    assert any(fragment in x.message for x in r.reasons)
    assert r.to_json()["ok"] is False and r.to_json()["reasons"]


def test_edit_tools_a_dict_of_arguments_is_checked_like_json_text(tools):
    assert not tools.run(empty(), "add_part", {"part": "plate", "place": GROUND, "gravity": 1}).ok
    assert tools.run(empty(), "add_part", {"part": "plate", "place": GROUND}).ok


def test_edit_tools_every_problem_of_a_call_is_one_reason(tools):
    r = run(tools, empty(), "schedule_command", {"actuator": "BAD", "start": -1, "end": "x", "command": 5})
    assert len(r.reasons) == 4


# --- every call is a Command through the validator -------------------------------------------------------------------


def test_edit_tools_every_accepted_call_goes_through_validate_command_and_is_the_command_it_returns(tools, monkeypatch):
    calls = []
    real = edit_tools_module.validate_command
    monkeypatch.setattr(edit_tools_module, "validate_command", lambda project, command: calls.append((project, command)) or real(project, command))
    p0 = empty()
    r = ok(tools, p0, "add_part", {"part": "plate", "place": GROUND, "material": "al6061-t6"})
    assert calls == [(p0, r.command)]
    assert isinstance(r.command, CommandBatch)  # the part definition, the material, the instance: one batch
    assert [c.type for c in r.command.commands] == ["add_part_def", "add_material_def", "add_instance"]
    assert apply_command(p0, r.command).project == r.project  # the command is the whole truth of the change
    assert p0 == empty()  # the input is untouched


def test_edit_tools_a_refusal_is_the_validators_and_changes_nothing(tools):
    p = ok(tools, empty(), "add_part", {"part": "plate", "place": GROUND}).project
    r = run(tools, p, "add_part", {"part": "plate", "place": GROUND})  # the same spot: the plates interpenetrate
    assert not r.ok and r.project is None and r.command is None
    (reason,) = r.reasons
    assert reason.code is ReasonCode.OVERLAP and {x.id for x in reason.ids} == {"plate-1", "plate-2"}
    assert [i.id for i in p.design.instances] == ["plate-1"]


def test_edit_tools_the_validators_checks_apply_floating_invalid_snap_and_overlap(tools, tower):
    # floating: a thruster joined to a beam whose own join to the ground is then cut loose
    p = ok(tools, tower, "add_part", {"part": "thruster-vacco-48003040", "place": snap("mount", "beam-1", "top")}).project
    r = run(tools, p, "remove_part", {"instance": "plate-1"})
    assert not r.ok and codes(r) == [ReasonCode.FLOATING]
    # a snap point holds one joint: a second beam on the same snap point is refused with the snap point named
    r = run(tools, tower, "add_part", {"part": "beam", "parameters": {"length": 0.1}, "place": snap("bottom", "plate-1", "top")})
    assert codes(r) == [ReasonCode.INVALID_PROJECT] and "plate-1/top" in {x.id for x in r.reasons[0].ids}
    # overlap: a second beam on the other plate edge snap is fine, but one the same size as the plate dropped on the ground is not
    r = run(tools, tower, "add_part", {"part": "plate", "place": {"type": "on_ground", "x": 0.1}})
    assert set(codes(r)) == {ReasonCode.OVERLAP} and {x.id for reason in r.reasons for x in reason.ids} == {"plate-1", "plate-2", "beam-1"}
    # invalid snap: snap kinds that do not accept each other (a motor mount meets a face)
    r = run(tools, tower, "add_part", {"part": "motor-37d-12v-50-1", "place": snap("mount", "beam-1", "top", joint={"kind": "fixed"})})
    assert not r.ok and ReasonCode.INVALID_SNAP in codes(r)


# --- placement by snap point -----------------------------------------------------------------------------------------


def test_edit_tools_a_plate_rests_on_the_ground_by_its_lowest_point(tools):
    r = ok(tools, empty(), "add_part", {"part": "plate", "parameters": {"thickness": 0.01}, "place": {"type": "on_ground", "x": 1.0, "y": -2.0}})
    inst = r.project.design.instances[0]
    assert near(pos(r.project, "plate-1"), (1.0, -2.0, 0.005))  # the slab is thickness/2 above its centre... lowest point z = 0
    # (x, y) are the call's number, so the pose is declared with the call's source; z is computed and the source says so
    assert inst.pose.badge is Badge.DECLARED and inst.pose.source.declared_by == "agent edit tools (G-02a)" and "z computed" in inst.pose.source.ref
    r2 = ok(tools, empty(), "add_part", {"part": "plate", "place": {"type": "on_ground", "x": 1.0}, "source": "the user said: put it one metre to the right"})
    assert r2.project.design.instances[0].pose.source.ref.startswith("the user said: put it one metre to the right;")
    assert inst.parameters[0].badge is Badge.DECLARED and inst.parameters[0].source.declared_by == "agent edit tools (G-02a)"
    assert inst.parameters[0].source.declared_at == NOW


def test_edit_tools_a_part_snapped_on_another_stands_where_the_snap_frames_meet(tools, tower):
    # plate top snap: z = 0.0025 (plate centre) + thickness/2 = 0.005. beam `bottom` snap: z = -height/2 = -0.03 in the beam frame,
    # frame turned by pi about x (opposed) so the beam's centre is 0.03 above the contact: 0.005 + 0.03 = 0.035.
    assert near(pos(tower, "beam-1"), (0.0, 0.0, 0.035))
    beam = next(i for i in tower.design.instances if i.id == "beam-1")
    assert beam.pose.orientation.model_dump() == {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}  # bottom frame is Rx(pi); opposed adds Rx(pi)
    (joint,) = tower.design.joints
    assert (joint.kind.value, joint.a.instance, joint.a.snap_point, joint.b.instance, joint.b.snap_point) == ("fixed", "plate-1", "top", "beam-1", "bottom")
    assert check_placement(tower) == ()
    assert [m.id for m in tower.design.materials] == ["al6061-t6", "steel-a36"]  # the catalog's exact entries


def test_edit_tools_roll_turns_about_the_joining_axis_by_quarter_turns(tools, tower):
    p = ok(tools, tower, "add_part", {"part": "plate", "parameters": {"length": 0.1, "width": 0.1},
                                      "place": snap("bottom", "beam-1", "top", roll_quarter_turns=1)}).project
    q = next(i for i in p.design.instances if i.id == "plate-2").pose.orientation
    assert math.isclose(abs(q.z), math.sqrt(0.5), abs_tol=1e-9) and math.isclose(abs(q.w), math.sqrt(0.5), abs_tol=1e-9) and abs(q.x) < 1e-9 and abs(q.y) < 1e-9
    assert near(pos(p, "plate-2")[:2], (0.0, 0.0))
    assert check_placement(p) == ()


def test_edit_tools_aligned_and_opposed_differ_by_a_flip(tools):
    p = ok(tools, empty(), "add_part", {"part": "plate", "place": GROUND}).project
    opposed = ok(tools, p, "add_part", {"part": "plate", "parameters": {"length": 0.1, "width": 0.1}, "place": snap("bottom", "plate-1", "top", "opposed")}).project
    aligned = run(tools, p, "add_part", {"part": "plate", "parameters": {"length": 0.1, "width": 0.1}, "place": snap("bottom", "plate-1", "top", "aligned")})
    q = next(i for i in opposed.design.instances if i.id == "plate-2").pose.orientation
    assert (q.x, q.y, q.z, q.w) == (0.0, 0.0, 0.0, 1.0)
    assert not aligned.ok and ReasonCode.OVERLAP in codes(aligned)  # flipped over: it dives into the plate


def test_edit_tools_build_a_four_wheel_car_from_the_shell_and_four_wheels(tools):
    # #541: the call sequence an agent can send. The shell's axle points sit only ~2 cm above its floor and a wheel is 0.1 m across, so the
    # car stands on its wheels: a wheel goes on the ground first, the shell's `axle-fl` meets that wheel's `mount` (the inner face of its
    # hub, part y = -0.86 width) and the other three wheels' `mount`s meet the other three `axle-*`. Every step is one the validator accepts.
    hinge = {"kind": "hinge"}
    p = ok(tools, empty(), "add_part", {"part": "wheel", "instance_id": "wheel-fl", "material": "pom-delrin-150", "place": GROUND}).project
    p = ok(tools, p, "add_part", {"part": "shell", "instance_id": "body", "material": "al6061-t6", "place": snap("axle-fl", "wheel-fl", "mount", joint=hinge)}).project
    for side in ("fr", "rl", "rr"):
        p = ok(tools, p, "add_part", {"part": "wheel", "instance_id": f"wheel-{side}", "material": "pom-delrin-150", "place": snap("mount", "body", f"axle-{side}", joint=hinge)}).project
    assert check_placement(p) == ()
    assert sorted(i.part for i in p.design.instances) == ["shell", "wheel", "wheel", "wheel", "wheel"]
    joints = {j.b.instance: (j.a.instance, j.a.snap_point, j.b.snap_point, j.kind.value) for j in p.design.joints}
    assert joints == {
        "body": ("wheel-fl", "mount", "axle-fl", "hinge"),
        "wheel-fr": ("body", "axle-fr", "mount", "hinge"),
        "wheel-rl": ("body", "axle-rl", "mount", "hinge"),
        "wheel-rr": ("body", "axle-rr", "mount", "hinge"),
    }
    # hand calculation, default sizes (shell L 0.4, W 0.2, H 0.12, t 0.004; wheel D 0.1, width 0.04): wheel centres at z = D/2 = 0.05;
    # shell centre at 0.05 + 3H/8 - 3t/4 = 0.092 (floor 0.032 above the ground); the axle points are 0.64 L = 0.256 apart in x and the
    # wheel centres 0.86 * 0.04 = 0.0344 outside y = +-W/2, so the left and right centres are W + 2 * 0.0344 = 0.2688 apart in y
    assert near(pos(p, "wheel-fl"), (0.0, 0.0, 0.05))
    assert near(pos(p, "body"), (-0.128, -0.1344, 0.092))
    assert near(pos(p, "wheel-fr"), (0.0, -0.2688, 0.05)) and near(pos(p, "wheel-rl"), (-0.256, 0.0, 0.05)) and near(pos(p, "wheel-rr"), (-0.256, -0.2688, 0.05))
    body = next(i for i in p.design.instances if i.id == "body").pose.orientation
    assert (body.x, body.y, body.z, body.w) == (0.0, 0.0, 0.0, 1.0)  # upright
    # the hub snap is the wheel's centre: on the shell's axle point the wheel passes through the body and below the ground (the G-06 failure)
    q = ok(tools, empty(), "add_part", {"part": "shell", "instance_id": "body", "place": GROUND}).project
    r = run(tools, q, "add_part", {"part": "wheel", "place": snap("hub", "body", "axle-fl", "aligned")})
    assert not r.ok and ReasonCode.OVERLAP in codes(r)


def test_edit_tools_a_post_stands_on_a_plate_by_a_beam_end_on_the_plate_top(tools):
    # #541: a beam `end` and a plate or beam `face` accept each other, so a beam end butts onto the plate top and the beam stands upright
    p = ok(tools, empty(), "add_part", {"part": "plate", "material": "al6061-t6", "place": GROUND}).project
    p = ok(tools, p, "add_part", {"part": "beam", "parameters": {"length": 0.1}, "material": "steel-a36", "place": snap("end-a", "plate-1", "top")}).project
    assert check_placement(p) == ()
    # plate top z = 0.005; the beam's end-a is L/2 = 0.05 from its centre along its -x, turned to point down: centre z = 0.055
    assert near(pos(p, "beam-1"), (0.0, 0.0, 0.055))
    # beam-to-world rotation: its local x (the length) points along world z, so the post stands upright from z = 0.005 to 0.105
    q = next(i for i in p.design.instances if i.id == "beam-1").pose.orientation
    assert math.isclose(abs(2.0 * (q.x * q.z - q.w * q.y)), 1.0, abs_tol=1e-9)


def test_edit_tools_an_unknown_snap_point_or_target_is_unknown_id(tools, tower):
    r = run(tools, tower, "add_part", {"part": "plate", "place": snap("nowhere", "plate-1", "top")})
    assert codes(r) == [ReasonCode.UNKNOWN_ID] and r.reasons[0].ids[0].kind.value == "snap_point"
    r = run(tools, tower, "add_part", {"part": "plate", "place": snap("top", "plate-1", "nowhere")})
    assert codes(r) == [ReasonCode.UNKNOWN_ID]
    r = run(tools, tower, "add_part", {"part": "plate", "place": snap("top", "ghost", "top")})
    assert codes(r) == [ReasonCode.UNKNOWN_ID] and r.reasons[0].ids[0].id == "ghost"
    r = run(tools, tower, "add_part", {"part": "sprocket", "place": GROUND})
    assert codes(r) == [ReasonCode.UNKNOWN_ID] and "plate" in r.reasons[0].message  # lists what the library has
    r = run(tools, tower, "add_part", {"part": "plate", "parameters": {"radius": 1.0}, "place": GROUND})
    assert codes(r) == [ReasonCode.UNKNOWN_ID]


def test_edit_tools_a_part_without_a_shape_cannot_be_put_on_the_ground_and_there_is_no_free_height(tools):
    shapeless = PartDef.model_validate(
        {"id": "marker", "name": "marker", "snap_points": [{"id": "p", "kind": "k", "accepts": ["k"], "position": {"x": {"offset": 0}, "y": {"offset": 0}, "z": {"offset": 0}},
                                                           "orientation": {"x": 0, "y": 0, "z": 0, "w": 1}, "badge": "declared", "source": {"ref": "unit test"}}]}
    )
    t = EditTools(library={**load_library(), "marker": shapeless}, clock=lambda: NOW)
    r = run(t, empty(), "add_part", {"part": "marker", "place": GROUND})
    assert codes(r) == [ReasonCode.INVALID_COMMAND] and "shape recipe" in r.reasons[0].message and r.reasons[0].ids[0].id == "marker"
    r = run(t, empty(), "add_part", {"part": "marker", "place": {"type": "on_ground", "z": 0.25}})  # a height has no field
    assert codes(r) == [ReasonCode.INVALID_COMMAND] and "z" in r.reasons[0].message
    r = run(t, empty(), "add_part", {"part": "plate", "place": {"type": "on_ground", "z": 0.25}})
    assert codes(r) == [ReasonCode.INVALID_COMMAND]
    # it can still be put at a snap point of a shaped part (the validator then checks the geometry that exists)
    p = ok(t, empty(), "add_part", {"part": "plate", "place": GROUND}).project
    r = run(t, p, "add_part", {"part": "marker", "place": snap("p", "plate-1", "top", "aligned")})
    assert codes(r) == [ReasonCode.INVALID_SNAP]  # the kinds do not accept each other: the validator, not the tool, decides


def test_edit_tools_ids_are_made_deterministically_and_can_be_given(tools, tower):
    p = ok(tools, tower, "add_part", {"part": "plate", "instance_id": "deck", "parameters": {"length": 0.1, "width": 0.1}, "place": snap("bottom", "beam-1", "top", joint={"id": "deck-weld"})}).project
    assert {i.id for i in p.design.instances} == {"plate-1", "beam-1", "deck"} and {j.id for j in p.design.joints} == {"joint-1", "deck-weld"}
    r = run(tools, p, "add_part", {"part": "plate", "instance_id": "deck", "place": {"type": "on_ground", "x": 5}})
    assert codes(r) == [ReasonCode.DUPLICATE_ID]


# --- parameters, material, removal ------------------------------------------------------------------------------------


def test_edit_tools_set_parameter_keeps_the_stack_meeting(tools, tower):
    # the plate gets thicker by 0.005: it is lifted to stay on the ground, and the beam (joined on top of it) is carried up with it
    r = ok(tools, tower, "set_parameter", {"instance": "plate-1", "name": "thickness", "value": 0.01})
    assert near(pos(r.project, "plate-1"), (0, 0, 0.005)) and near(pos(r.project, "beam-1"), (0, 0, 0.040))
    assert check_placement(r.project) == ()
    value = next(i for i in r.project.design.instances if i.id == "plate-1").parameters[0]
    assert (value.name, value.value, value.unit.value, value.badge) == ("thickness", 0.01, "m", Badge.DECLARED)
    # the beam gets taller by 0.04: only the beam moves up by half of it
    r2 = ok(tools, tower, "set_parameter", {"instance": "beam-1", "name": "height", "value": 0.1})
    assert near(pos(r2.project, "beam-1"), (0, 0, 0.005 + 0.05)) and near(pos(r2.project, "plate-1"), (0, 0, 0.0025))


def test_edit_tools_set_parameter_without_resnap_lets_the_validator_say_the_joint_no_longer_meets(tools, tower):
    r = run(tools, tower, "set_parameter", {"instance": "beam-1", "name": "height", "value": 0.1, "resnap": False})
    assert not r.ok and ReasonCode.INVALID_SNAP in codes(r)


def test_edit_tools_a_parameter_outside_the_range_or_of_another_part_is_refused(tools, tower):
    r = run(tools, tower, "set_parameter", {"instance": "plate-1", "name": "thickness", "value": 5.0})
    assert codes(r) == [ReasonCode.INVALID_PROJECT] and r.reasons[0].ids[0].id == "plate-1/thickness"
    r = run(tools, tower, "set_parameter", {"instance": "plate-1", "name": "diameter", "value": 0.1})
    assert codes(r) == [ReasonCode.UNKNOWN_ID]
    r = run(tools, tower, "set_parameter", {"instance": "ghost", "name": "length", "value": 0.1})
    assert codes(r) == [ReasonCode.UNKNOWN_ID]


@pytest.mark.parametrize("tool,base", [("set_parameter", {"name": "thickness", "value": 0.01}), ("clear_parameter", {"name": "thickness"})])
@pytest.mark.parametrize("bad", ["true", "false", 1, 0, None, "yes"])
def test_edit_tools_resnap_is_a_strict_boolean(tools, tower, tool, base, bad):
    tower = ok(tools, tower, "set_parameter", {"instance": "plate-1", "name": "thickness", "value": 0.008}).project  # so both tools have a value to act on
    r = run(tools, tower, tool, {"instance": "plate-1", "resnap": bad, **base})
    assert not r.ok and codes(r) == [ReasonCode.INVALID_COMMAND] and any("resnap" in x.message for x in r.reasons)
    assert run(tools, tower, tool, {"instance": "plate-1", "resnap": True, **base}).ok


def test_edit_tools_clear_parameter_takes_the_default_again(tools, tower):
    p = ok(tools, tower, "set_parameter", {"instance": "plate-1", "name": "thickness", "value": 0.01}).project
    r = ok(tools, p, "clear_parameter", {"instance": "plate-1", "name": "thickness"})
    assert near(pos(r.project, "plate-1"), (0, 0, 0.0025)) and near(pos(r.project, "beam-1"), (0, 0, 0.035))
    assert next(i for i in r.project.design.instances if i.id == "plate-1").parameters == ()  # the default applies again


def test_edit_tools_set_material_takes_a_project_or_catalog_material_never_a_new_one(tools, tower):
    r = ok(tools, tower, "set_material", {"instance": "beam-1", "material": "ti-6al-4v"})
    assert next(i for i in r.project.design.instances if i.id == "beam-1").material == "ti-6al-4v"
    assert "ti-6al-4v" in [m.id for m in r.project.design.materials]
    assert ok(tools, tower, "set_material", {"instance": "beam-1", "material": None}).project.design.instances[1].material is None
    r = run(tools, tower, "set_material", {"instance": "beam-1", "material": "unobtainium"})
    assert codes(r) == [ReasonCode.UNKNOWN_ID]
    assert "density" not in json.dumps([t for t in specs() if t["function"]["name"] == "set_material"])


def test_edit_tools_remove_part_takes_what_hangs_on_it(tools, tower):
    p = ok(tools, tower, "add_part", {"part": "thruster-vacco-48003040", "place": snap("mount", "beam-1", "top")}).project
    p = ok(tools, p, "add_actuator", {"kind": "thruster", "instance": "thruster-vacco-48003040-1"}).project
    p = ok(tools, p, "schedule_command", {"actuator": "actuator-1", "start": 0, "end": 1, "command": 1}).project
    r = ok(tools, p, "remove_part", {"instance": "thruster-vacco-48003040-1"})
    assert not r.project.design.actuators and not r.project.design.schedule.entries and len(r.project.design.joints) == 1
    assert r.effects["removed"]["actuators"] == ["actuator-1"] and r.effects["removed"]["instances"] == ["thruster-vacco-48003040-1"]
    assert codes(run(tools, p, "remove_part", {"instance": "ghost"})) == [ReasonCode.UNKNOWN_ID]


# --- joints, actuators and control -------------------------------------------------------------------------------------


def car_tools():
    example = json.loads((EXAMPLES / "DesignSpec.four-wheel-car.json").read_text(encoding="utf-8"))
    # The hand-written car has no shapes. Its chassis gets a 0.1 m cube so that it can rest on the ground (its lowest point at z = 0
    # puts the centre at z = 0.05, the hand-written pose); the other parts are as written.
    cube = {"badge": "declared", "source": {"ref": "unit test: a 0.1 m cube"}, "components": [
        {"id": "body", "operation": "add", "position": {"x": {"offset": 0.0}, "y": {"offset": 0.0}, "z": {"offset": 0.0}},
         "primitive": {"kind": "box", "size_x": {"offset": 0.1}, "size_y": {"offset": 0.1}, "size_z": {"offset": 0.1}}}]}
    library = {p["id"]: PartDef.model_validate({**p, "shape": cube} if p["id"] == "chassis" else p) for p in example["parts"]}
    project = Project.model_validate({"world": {"planet": "earth"}, "design": {"materials": example["materials"]}})
    return EditTools(library=library, clock=lambda: NOW), project, DesignSpec.model_validate(example)


def test_edit_tools_the_four_wheel_car_is_built_from_snap_points_alone_and_matches_the_hand_written_one():
    t, p, example = car_tools()
    p = ok(t, p, "add_part", {"part": "chassis", "instance_id": "chassis-1", "place": GROUND, "material": "example-material"}).project

    def add(part, ident, own, target_inst, target_snap, **more):
        nonlocal p
        place = snap(own, target_inst, target_snap, "aligned", **more)
        p = ok(t, p, "add_part", {"part": part, "instance_id": ident, "place": place}).project

    add("motor", "motor-l", "mount", "chassis-1", "motor-l", joint={"id": "weld-ml", "kind": "fixed"})
    add("motor", "motor-r", "mount", "chassis-1", "motor-r", roll_quarter_turns=2, joint={"id": "weld-mr", "kind": "fixed"})
    add("wheel", "wheel-rl", "hub", "motor-l", "shaft", joint={"id": "drive-l", "kind": "hinge"})
    add("wheel", "wheel-rr", "hub", "motor-r", "shaft", joint={"id": "drive-r", "kind": "hinge"})
    add("wheel", "wheel-fl", "hub", "chassis-1", "axle-fl", joint={"id": "axle-fl", "kind": "hinge"})
    add("wheel", "wheel-fr", "hub", "chassis-1", "axle-fr", joint={"id": "axle-fr", "kind": "hinge"})
    for motor, joint in (("motor-l", "drive-l"), ("motor-r", "drive-r")):
        p = ok(t, p, "add_actuator", {"kind": "motor", "instance": motor, "joint": joint, "id": f"drive-{motor}"}).project
    p = ok(t, p, "schedule_command", {"actuator": "drive-motor-l", "start": 0, "end": 5, "command": 1, "id": "run-l", "source": "the user asked for 5 s at full command"}).project
    p = ok(t, p, "schedule_command", {"actuator": "drive-motor-r", "start": 0, "end": 5, "command": 1, "id": "run-r"}).project

    mine = {i.id: i for i in p.design.instances}
    for hand in example.instances:
        got = mine[hand.id]
        assert near((got.pose.position.x, got.pose.position.y, got.pose.position.z), (hand.pose.position.x, hand.pose.position.y, hand.pose.position.z)), hand.id
        if hand.id == "wheel-rr":
            continue  # the hand-written car leaves this wheel unturned; a hub aligned to the turned motor's shaft frame is turned with it
        a, b = got.pose.orientation, hand.pose.orientation
        assert math.isclose(abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w), 1.0, abs_tol=1e-9), hand.id  # the same rotation (q = -q)
    assert {(j.id, j.kind, j.a, j.b) for j in p.design.joints} == {(j.id, j.kind, j.a, j.b) for j in example.joints}
    assert {(a.id, a.kind, a.instance, a.joint) for a in p.design.actuators} == {(a.id, a.kind, a.instance, a.joint) for a in example.actuators}
    assert {(e.id, e.actuator, e.start, e.end, e.command) for e in p.design.schedule.entries} == {
        (e.id, e.actuator, e.start, e.end, e.command) for e in example.schedule.entries
    }
    by_id = {e.id: e for e in p.design.schedule.entries}
    assert by_id["run-l"].badge is Badge.DECLARED and by_id["run-l"].source.ref == "the user asked for 5 s at full command"
    assert by_id["run-r"].source.ref == edit_tools_module.DEFAULT_SOURCE
    assert check_placement(p) == ()


def test_edit_tools_connect_moves_the_second_assembly_to_meet_the_first(tools):
    t, p, _ = car_tools()
    p = ok(t, p, "add_part", {"part": "chassis", "place": GROUND}).project
    p = ok(t, p, "add_part", {"part": "chassis", "place": {"type": "on_ground", "x": 1.0, "y": 1.0}}).project
    assert near(pos(p, "chassis-2"), (1.0, 1.0, 0.05))
    r = ok(t, p, "connect", {"a": {"instance": "chassis-1", "snap_point": "motor-l"}, "b": {"instance": "chassis-2", "snap_point": "motor-r"}, "facing": "aligned", "joint": {"kind": "fixed", "id": "bridge"}})
    assert near(pos(r.project, "chassis-2"), (0.0, 0.2, 0.05))  # motor-l of chassis-1 is at (-0.1, 0.1); motor-r sits at (-0.1, -0.1) from chassis-2's centre
    assert r.command.commands[-1].type == "add_joint" and r.command.commands[0].type == "move_instance"
    # `none` joins where they are: they are about 1.3 m apart, so the validator refuses
    r = run(t, p, "connect", {"a": {"instance": "chassis-1", "snap_point": "motor-l"}, "b": {"instance": "chassis-2", "snap_point": "motor-r"}, "facing": "aligned", "move": "none"})
    assert ReasonCode.INVALID_SNAP in codes(r)
    assert codes(run(t, p, "connect", {"a": {"instance": "chassis-1", "snap_point": "axle-fl"}, "b": {"instance": "chassis-1", "snap_point": "axle-fr"}, "facing": "aligned"})) == [ReasonCode.INVALID_COMMAND]


def test_edit_tools_connect_carries_everything_joined_to_the_moved_part_and_refuses_a_loop():
    t, p, _ = car_tools()
    p = ok(t, p, "add_part", {"part": "chassis", "place": GROUND}).project
    p = ok(t, p, "add_part", {"part": "chassis", "place": {"type": "on_ground", "x": 5.0}}).project
    p = ok(t, p, "add_part", {"part": "motor", "place": snap("mount", "chassis-2", "motor-l", "aligned")}).project
    assert near(pos(p, "motor-1"), (4.9, 0.1, 0.05))
    r = ok(t, p, "connect", {"a": {"instance": "chassis-1", "snap_point": "motor-l"}, "b": {"instance": "chassis-2", "snap_point": "motor-r"}, "facing": "aligned"})
    assert near(pos(r.project, "chassis-2"), (0.0, 0.2, 0.05))  # motor-l of chassis-1 is at (-0.1, 0.1); motor-r sits at (-0.1, -0.1) from chassis-2's centre
    assert near(pos(r.project, "motor-1"), (-0.1, 0.3, 0.05))  # carried by the same move: it hung at (-0.1, +0.1) from chassis-2's centre
    r2 = run(t, r.project, "connect", {"a": {"instance": "chassis-1", "snap_point": "motor-r"}, "b": {"instance": "motor-1", "snap_point": "shaft"}, "facing": "aligned"})
    assert not r2.ok and "loop" in r2.reasons[0].message


def test_edit_tools_set_joint_changes_kind_limits_and_threshold_with_declared_numbers():
    t, p, _ = car_tools()
    p = ok(t, p, "add_part", {"part": "chassis", "place": GROUND}).project
    p = ok(t, p, "add_part", {"part": "wheel", "place": snap("hub", "chassis-1", "axle-fl", "aligned", joint={"kind": "hinge", "id": "axle"})}).project
    r = ok(t, p, "set_joint", {"joint": "axle", "limits": {"lower": -1.0, "upper": 1.0}, "break_threshold": 250.0, "source": "user asked for a stop at one radian"})
    (joint,) = r.project.design.joints
    assert (joint.limits.lower.value, joint.limits.upper.value, joint.limits.lower.unit.value) == (-1.0, 1.0, "rad")
    assert joint.break_threshold.value == 250.0 and joint.break_threshold.badge is Badge.DECLARED and joint.limits.upper.source.ref == "user asked for a stop at one radian"
    r2 = ok(t, r.project, "set_joint", {"joint": "axle", "kind": "slider", "limits": {"lower": 0.0, "upper": 0.1}, "clear": ["break_threshold"]})
    (joint,) = r2.project.design.joints
    assert joint.kind.value == "slider" and joint.limits.upper.unit.value == "m" and joint.break_threshold is None
    assert codes(run(t, r.project, "set_joint", {"joint": "axle", "kind": "fixed"})) == [ReasonCode.INVALID_COMMAND]  # a fixed joint has no limits
    assert codes(run(t, p, "set_joint", {"joint": "ghost"})) == [ReasonCode.UNKNOWN_ID]
    assert codes(run(t, p, "remove_joint", {"joint": "ghost"})) == [ReasonCode.UNKNOWN_ID]
    assert not ok(t, p, "remove_joint", {"joint": "axle"}).project.design.joints


def test_edit_tools_actuator_and_schedule_rules_come_from_the_core(tools, tower):
    p = ok(tools, tower, "add_part", {"part": "thruster-vacco-48003040", "place": snap("mount", "beam-1", "top")}).project
    assert codes(run(tools, p, "add_actuator", {"kind": "motor", "instance": "thruster-vacco-48003040-1"})) == [ReasonCode.INVALID_COMMAND]  # a motor needs a joint
    assert codes(run(tools, p, "add_actuator", {"kind": "thruster", "instance": "ghost"})) == [ReasonCode.UNKNOWN_ID]
    p = ok(tools, p, "add_actuator", {"kind": "thruster", "instance": "thruster-vacco-48003040-1"}).project
    assert codes(run(tools, p, "add_actuator", {"kind": "thruster", "instance": "thruster-vacco-48003040-1"})) == [ReasonCode.INVALID_PROJECT]  # the same drive twice
    p = ok(tools, p, "schedule_command", {"actuator": "actuator-1", "start": 0, "end": 2, "command": 1}).project
    assert codes(run(tools, p, "schedule_command", {"actuator": "actuator-1", "start": 1, "end": 3, "command": 1})) == [ReasonCode.INVALID_PROJECT]  # overlap
    assert codes(run(tools, p, "schedule_command", {"actuator": "actuator-1", "start": 2, "end": 3, "command": -0.5})) == [ReasonCode.INVALID_PROJECT]  # a thruster does not reverse
    assert codes(run(tools, p, "schedule_command", {"actuator": "actuator-1", "start": 3, "end": 2, "command": 1})) == [ReasonCode.INVALID_COMMAND]  # start < end
    r = ok(tools, p, "change_command", {"entry": "step-1", "end": 4, "command": 0.5})
    (entry,) = r.project.design.schedule.entries
    assert (entry.start, entry.end, entry.command, entry.badge) == (0.0, 4.0, 0.5, Badge.DECLARED)
    assert codes(run(tools, p, "change_command", {"entry": "ghost", "end": 4})) == [ReasonCode.UNKNOWN_ID]
    assert not ok(tools, p, "remove_command", {"entry": "step-1"}).project.design.schedule.entries
    assert codes(run(tools, p, "remove_command", {"entry": "ghost"})) == [ReasonCode.UNKNOWN_ID]
    assert not ok(tools, p, "remove_actuator", {"actuator": "actuator-1"}).project.design.actuators
    assert codes(run(tools, p, "remove_actuator", {"actuator": "ghost"})) == [ReasonCode.UNKNOWN_ID]


def test_edit_tools_nothing_the_tools_write_is_cited(tools, tower):
    p = ok(tools, tower, "set_parameter", {"instance": "beam-1", "name": "height", "value": 0.07}).project
    blob = json.loads(p.model_dump_json())
    badges = {i["pose"]["badge"] for i in blob["design"]["instances"]} | {x["badge"] for i in blob["design"]["instances"] for x in i["parameters"]}
    assert badges <= {"sim", "declared"}


# --- through the Hub (C-05a) ----------------------------------------------------------------------------------------------


def test_edit_tools_through_the_hub_publish_as_the_agent_and_undo_takes_the_whole_call_back(tools):
    hub = Hub({"desk": empty()})
    agent = HubEditTools(hub, "desk", tools=tools)
    r = agent.call("add_part", {"part": "plate", "place": GROUND, "material": "al6061-t6"})
    assert r.ok and r.revision == 1
    doc = hub.documents["desk"]
    assert doc.revision == 1 and doc.project == r.project and doc.history.entries[0].origin is Origin.AGENT
    assert isinstance(doc.history.entries[0].command, CommandBatch)  # def + material + instance: one undo step
    bad = agent.call("add_part", {"part": "plate", "place": GROUND})  # overlap: refused before the document hears of it
    assert not bad.ok and doc.revision == 1
    assert not agent.call("add_part", {"part": "plate", "place": GROUND, "gravity": 3.7}).ok and doc.revision == 1
    from kinetra_core import Request

    hub.publish("desk", Request.model_validate({"type": "request", "id": "u1", "action": "undo", "origin": "mouse"}))
    assert doc.project == empty()


def test_edit_tools_the_hub_wrapper_needs_a_project_of_the_hub():
    with pytest.raises(KeyError):
        HubEditTools(Hub({"desk": empty()}), "nope")


def test_edit_tools_the_library_is_the_packaged_parts_and_a_call_cannot_define_a_part(tools):
    lib = load_library()
    assert {"plate", "beam", "wheel", "payload"} <= set(lib)
    r = run(tools, empty(), "add_part", {"part": {"id": "mine", "name": "mine"}, "place": GROUND})
    assert not r.ok and codes(r) == [ReasonCode.FORBIDDEN]  # G-04: a definition in place of an id is an attempt, not a typo
    p = ok(tools, empty(), "add_part", {"part": "plate", "place": GROUND}).project
    assert p.design.parts[0] == lib["plate"]  # the library's definition, exactly


# --- placeholders (C-06) -----------------------------------------------------------------------------------------------


@pytest.fixture
def opened_with_a_missing_part(tower):
    """The tower as a file that left the beam's definition out would open: the beam instance and its joint stay, as a placeholder."""
    blob = json.loads(tower.model_dump_json())
    blob["design"]["parts"] = [p for p in blob["design"]["parts"] if p["id"] != "beam"]
    return Project.model_validate(blob)


def test_edit_tools_a_tool_that_needs_a_missing_definition_surfaces_missing_definition(tools, opened_with_a_missing_part):
    p = opened_with_a_missing_part
    assert [m.id for m in missing_definitions(p)] == ["beam"]
    for tool, args in (
        ("set_parameter", {"instance": "beam-1", "name": "height", "value": 0.05}),
        ("clear_parameter", {"instance": "beam-1", "name": "height"}),
        ("add_part", {"part": "plate", "parameters": {"length": 0.1, "width": 0.1}, "place": snap("bottom", "beam-1", "top")}),
        ("connect", {"a": {"instance": "plate-1", "snap_point": "edge-xp"}, "b": {"instance": "beam-1", "snap_point": "end-a"}, "facing": "opposed"}),
    ):
        r = run(tools, p, tool, args)
        assert not r.ok and codes(r) == [ReasonCode.MISSING_DEFINITION], tool
        assert [(x.kind.value, x.id) for x in r.reasons[0].ids] == [("part", "beam"), ("instance", "beam-1")]


def test_edit_tools_a_tool_does_not_relink_placeholders_by_adding_a_library_definition(tools, opened_with_a_missing_part):
    r = run(tools, opened_with_a_missing_part, "add_part", {"part": "beam", "parameters": {"length": 0.1}, "place": GROUND})
    assert codes(r) == [ReasonCode.MISSING_DEFINITION]  # `beam` is in the library, but the user did not choose it for beam-1
    blob = json.loads(opened_with_a_missing_part.model_dump_json())
    blob["design"]["instances"][1]["material"] = "gone-material"
    p = Project.model_validate(blob)
    r = run(tools, p, "set_material", {"instance": "plate-1", "material": "gone-material"})
    assert codes(r) == [ReasonCode.MISSING_DEFINITION]  # a placeholder already uses that id, and the catalog does not have it
    blob["design"]["instances"][1]["material"] = "ti-6al-4v"
    p = Project.model_validate(blob)
    r = run(tools, p, "set_material", {"instance": "plate-1", "material": "ti-6al-4v"})
    assert codes(r) == [ReasonCode.MISSING_DEFINITION]


def test_edit_tools_a_placeholder_can_still_be_removed_and_the_rest_edited(tools, opened_with_a_missing_part):
    p = opened_with_a_missing_part
    r = ok(tools, p, "set_parameter", {"instance": "plate-1", "name": "thickness", "value": 0.004, "resnap": False})  # elsewhere: allowed
    assert [m.id for m in missing_definitions(r.project)] == ["beam"]  # still missing, not more
    gone = ok(tools, p, "remove_part", {"instance": "beam-1"})
    assert missing_definitions(gone.project) == ()


def test_edit_tools_no_accepted_call_leaves_a_placeholder(tools, tower):
    p = tower
    for tool, args in (
        ("add_part", {"part": "thruster-vacco-48003040", "place": snap("mount", "beam-1", "top")}),
        ("set_material", {"instance": "beam-1", "material": "ti-6al-4v"}),
        ("set_parameter", {"instance": "beam-1", "name": "height", "value": 0.05}),
        ("remove_part", {"instance": "thruster-vacco-48003040-1"}),
    ):
        p = ok(tools, p, tool, args).project
        assert missing_definitions(p) == (), tool
