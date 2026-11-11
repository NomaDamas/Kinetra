"""C-02a: `Command` and `apply_command`. The fixture is the committed four-wheel-car example (declared values,
not real part data) on the example World and assumption table."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from kinetra_core import (
    ActuateEntry,
    Command,
    CommandBatch,
    CommandRejected,
    Project,
    ReasonCode,
    Ref,
    RefKind,
    apply_command,
    check_world_references,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"
SRC = {"ref": "unit-test fixture", "locator": "test_commands.py"}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def project_data():
    return {
        "design": load("DesignSpec.four-wheel-car.json"),
        "world": load("World.ramp-and-step.json"),
        "assumptions": load("AssumptionTable.vehicle-mass.json"),
    }


@pytest.fixture
def project():
    return Project.model_validate(project_data())


def cmd(**d):
    return TypeAdapter(Command).validate_python(d)


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def pose(x=0.0, y=0.0, z=0.0):
    return {"position": {"x": x, "y": y, "z": z}, "orientation": IDENTITY, "badge": "declared", "source": SRC}


def entry(actuator, id, start, end, command):
    return {"type": "actuate", "id": id, "actuator": actuator, "start": start, "end": end, "command": command, "badge": "declared", "source": SRC}


def ref(kind, id):
    return Ref(kind=RefKind(kind), id=id)


def ids(items):
    return [i.id for i in items]


def roundtrip(project, command):
    """Apply, apply the inverse, expect the original; apply the inverse's inverse, expect the edit again."""
    done = apply_command(project, command)
    undone = apply_command(done.project, done.inverse)
    assert undone.project == project
    redone = apply_command(undone.project, undone.inverse)
    assert redone.project == done.project
    return done


def rejected(project, command, code):
    with pytest.raises(CommandRejected) as e:
        apply_command(project, command)
    assert e.value.reasons[0].code is code, e.value
    return e.value


# --- every command: apply, then the inverse gives the original --------------------------------------------


def new_wheel():
    wheel = copy.deepcopy(next(i for i in load("DesignSpec.four-wheel-car.json")["instances"] if i["id"] == "wheel-fl"))
    wheel["id"] = "spare"
    return wheel


COMMANDS = {
    "add_part_def": lambda: dict(
        type="add_part_def",
        index=1,
        part={"id": "plate", "name": "Plate", "snap_points": []},
    ),
    "remove_part_def": lambda: None,  # needs an unused part: see test below
    "add_material_def": lambda: dict(
        type="add_material_def",
        material={
            **load("Material.example.json"),
            "id": "second-material",
        },
    ),
    "add_instance": lambda: dict(type="add_instance", instance=new_wheel(), index=2),
    "move_instance": lambda: dict(type="move_instance", id="wheel-fl", pose=pose(0.2, 0.1, 0.05)),
    "set_parameter_new": lambda: dict(
        type="set_parameter", instance="wheel-rr", parameter={"name": "diameter", **q(0.12, "m")}
    ),
    "set_parameter_existing": lambda: dict(
        type="set_parameter", instance="wheel-rl", parameter={"name": "diameter", **q(0.15, "m")}
    ),
    "clear_parameter": lambda: dict(type="clear_parameter", instance="wheel-rl", name="diameter"),
    "set_instance_material": lambda: dict(type="set_instance_material", id="chassis-1", material=None),
    "remove_joint": lambda: dict(type="remove_joint", id="drive-l"),
    "remove_actuator": lambda: dict(type="remove_actuator", id="drive-motor-l"),
    "remove_instance": lambda: dict(type="remove_instance", id="motor-l"),
    "remove_control_entry": lambda: dict(type="remove_control_entry", id="run-l"),
    "replace_control_entry": lambda: dict(
        type="replace_control_entry", entry=entry("drive-motor-r", "run-r", 1.0, 2.0, -0.5)
    ),
    "add_control_entry": lambda: dict(
        type="add_control_entry", index=0, entry=entry("drive-motor-l", "run-late", 6.0, 7.0, 0.25)
    ),
    "replace_material_def": lambda: dict(
        type="replace_material_def",
        material={**load("Material.example.json"), "id": "example-material", "name": "Example, edited"},
    ),
    "replace_part_def": lambda: dict(
        type="replace_part_def",
        part={**next(p for p in load("DesignSpec.four-wheel-car.json")["parts"] if p["id"] == "motor"), "name": "Motor, edited"},
    ),
    "replace_joint": lambda: dict(
        type="replace_joint",
        joint={
            **next(j for j in load("DesignSpec.four-wheel-car.json")["joints"] if j["id"] == "drive-l"),
            "break_threshold": {"value": 50.0, "unit": "N", "badge": "declared", "source": SRC},
        },
    ),
    "set_assumption": lambda: dict(
        type="set_assumption",
        assumption={
            **project_data()["assumptions"]["assumptions"][0],
            "label": "Vehicle mass (edited)",
        },
    ),
    "remove_assumption": lambda: dict(type="remove_assumption", key="vehicle_mass"),
    "select_planet": lambda: dict(type="select_planet", planet="moon"),
}


@pytest.mark.parametrize("name", [n for n, f in COMMANDS.items() if f() is not None])
def test_apply_then_inverse_is_the_original(project, name):
    command = cmd(**COMMANDS[name]())
    done = roundtrip(project, command)
    assert done.project != project, "the command changed nothing"


def test_apply_remove_part_def_and_inverse(project):
    with_plate = apply_command(project, cmd(**COMMANDS["add_part_def"]())).project
    done = roundtrip(with_plate, cmd(type="remove_part_def", id="plate"))
    assert "plate" not in ids(done.project.design.parts)
    assert ids(with_plate.design.parts) == ["chassis", "plate", "motor", "wheel"]  # inserted at index 1


def test_apply_remove_material_def_and_inverse(project):
    two = apply_command(project, cmd(**COMMANDS["add_material_def"]())).project
    roundtrip(two, cmd(type="remove_material_def", id="second-material"))


def test_apply_add_assumption_and_inverse(project):
    first = project_data()["assumptions"]["assumptions"][0]
    second = {**first, "key": "wheel_friction", "label": "Wheel friction"}
    roundtrip(project, cmd(type="add_assumption", assumption=second))
    roundtrip(project, cmd(type="add_assumption", assumption=second, index=0))


def test_apply_add_joint_and_actuator_round_trip(project):
    spare = apply_command(project, cmd(type="add_instance", instance=new_wheel())).project
    joint = {
        "id": "spare-hub",
        "kind": "hinge",
        "a": {"instance": "chassis-1", "snap_point": "axle-fl"},
        "b": {"instance": "spare", "snap_point": "hub"},
    }
    # the front-left axle is taken by wheel-fl: rejected, nothing changes
    rejected(spare, cmd(type="add_joint", joint=joint), ReasonCode.INVALID_PROJECT)
    freed = apply_command(spare, cmd(type="remove_joint", id="axle-fl")).project
    with_joint = roundtrip(freed, cmd(type="add_joint", joint=joint, index=0))
    assert with_joint.project.design.joints[0].id == "spare-hub"
    actuator = {"id": "spare-motor", "kind": "motor", "instance": "chassis-1", "joint": "spare-hub"}
    roundtrip(with_joint.project, cmd(type="add_actuator", actuator=actuator, index=0))


def test_apply_does_not_change_its_input(project):
    before = project.model_dump_json()
    apply_command(project, cmd(type="remove_instance", id="chassis-1"))
    assert project.model_dump_json() == before


# --- removal takes what hangs on it, in one command (#476) -------------------------------------------------


def test_apply_remove_instance_takes_joints_actuators_and_schedule_entries(project):
    done = roundtrip(project, cmd(type="remove_instance", id="motor-l"))
    d = done.project.design
    assert "motor-l" not in ids(d.instances)
    assert ids(d.joints) == ["weld-mr", "drive-r", "axle-fl", "axle-fr"]  # weld-ml and drive-l went
    assert ids(d.actuators) == ["drive-motor-r"]
    assert [e.actuator for e in d.schedule.entries] == ["drive-motor-r"]
    # the wheel it drove is still there, no longer joined
    assert "wheel-rl" in ids(d.instances)


def test_apply_remove_instance_inverse_restores_original_order(project):
    done = apply_command(project, cmd(type="remove_instance", id="chassis-1"))
    d = done.project.design
    assert ids(d.joints) == ["drive-l", "drive-r"] and ids(d.actuators) == ["drive-motor-l", "drive-motor-r"]
    assert isinstance(done.inverse, CommandBatch)
    assert apply_command(done.project, done.inverse).project == project
    # a result with dangling state cannot be built, so these did not leak
    Project.model_validate(done.project.model_dump(mode="json"))


def test_apply_remove_instance_of_the_actuated_wheel_takes_its_motor_channel_only_with_the_joint(project):
    done = roundtrip(project, cmd(type="remove_instance", id="wheel-rr"))
    d = done.project.design
    assert "drive-r" not in ids(d.joints)
    assert ids(d.actuators) == ["drive-motor-l"]  # the motor on motor-r drove drive-r: it goes with it
    assert [e.actuator for e in d.schedule.entries] == ["drive-motor-l"]


def test_apply_remove_joint_takes_its_actuators_and_entries(project):
    done = roundtrip(project, cmd(type="remove_joint", id="drive-r"))
    d = done.project.design
    assert ids(d.actuators) == ["drive-motor-l"]
    assert [e.actuator for e in d.schedule.entries] == ["drive-motor-l"]
    assert "motor-r" in ids(d.instances)


def test_apply_remove_actuator_takes_its_entries(project):
    done = roundtrip(project, cmd(type="remove_actuator", id="drive-motor-l"))
    assert [e.actuator for e in done.project.design.schedule.entries] == ["drive-motor-r"]
    assert "drive-l" in ids(done.project.design.joints)


def test_apply_removals_leave_no_dangling_reference_whatever_is_removed(project):
    """Remove every instance, joint and actuator one by one: the result always validates and the inverse
    always brings the original back."""
    d = project.design
    for command in (
        *(cmd(type="remove_instance", id=i.id) for i in d.instances),
        *(cmd(type="remove_joint", id=j.id) for j in d.joints),
        *(cmd(type="remove_actuator", id=a.id) for a in d.actuators),
    ):
        done = roundtrip(project, command)
        Project.model_validate(done.project.model_dump(mode="json"))


# --- rejections: nothing changes, the reason says why ------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        dict(type="remove_instance", id="ghost"),
        dict(type="remove_joint", id="ghost"),
        dict(type="remove_actuator", id="ghost"),
        dict(type="remove_part_def", id="ghost"),
        dict(type="remove_material_def", id="ghost"),
        dict(type="move_instance", id="ghost", pose=pose()),
        dict(type="clear_parameter", instance="ghost", name="diameter"),
        dict(type="clear_parameter", instance="wheel-rr", name="diameter"),  # not set
        dict(type="set_instance_material", id="ghost", material=None),
        dict(type="remove_assumption", key="ghost"),
        dict(type="remove_control_entry", id="ghost"),
        dict(type="replace_control_entry", entry=entry("drive-motor-l", "ghost", 0.0, 1.0, 1.0)),
        dict(type="replace_joint", joint={"id": "ghost", "kind": "fixed", "a": {"instance": "chassis-1", "snap_point": "motor-l"}, "b": {"instance": "motor-l", "snap_point": "mount"}}),
        dict(type="replace_part_def", part={"id": "ghost", "name": "Ghost", "snap_points": []}),
        dict(type="replace_material_def", material={**load("Material.example.json"), "id": "ghost"}),
    ],
)
def test_apply_rejects_unknown_ids(project, command):
    err = rejected(project, cmd(**command), ReasonCode.UNKNOWN_ID)
    assert err.reasons[0].ids and all(isinstance(r, Ref) for r in err.reasons[0].ids)


def test_apply_rejects_duplicate_ids(project):
    wheel = new_wheel()
    wheel["id"] = "wheel-fl"
    rejected(project, cmd(type="add_instance", instance=wheel), ReasonCode.DUPLICATE_ID)
    rejected(project, cmd(type="add_assumption", assumption=project_data()["assumptions"]["assumptions"][0]), ReasonCode.DUPLICATE_ID)


def test_apply_rejects_removing_a_definition_that_is_in_use(project):
    err = rejected(project, cmd(type="remove_part_def", id="wheel"), ReasonCode.IN_USE)
    assert set(err.reasons[0].ids) >= {ref("part", "wheel"), ref("instance", "wheel-rl")}
    # example-material is used by chassis-1 and by both terrain props
    err = rejected(project, cmd(type="remove_material_def", id="example-material"), ReasonCode.IN_USE)
    assert set(err.reasons[0].ids) >= {ref("instance", "chassis-1"), ref("prop", "prop-a"), ref("prop", "prop-b")}


def test_apply_reason_refs_say_what_kind_an_id_is():
    """A part and an instance can share an id: the reason keeps them apart."""
    d = project_data()
    wheel_part = next(p for p in d["design"]["parts"] if p["id"] == "wheel")
    d["design"]["instances"].append({"id": "wheel", "part": "wheel", "pose": pose(0.0, 0.5, 0.05)})
    err = rejected(Project.model_validate(d), cmd(type="remove_part_def", id=wheel_part["id"]), ReasonCode.IN_USE)
    refs = err.reasons[0].ids
    assert ref("part", "wheel") in refs and ref("instance", "wheel") in refs
    assert len({(r.kind, r.id) for r in refs}) == len(refs)


def test_apply_rejects_a_result_that_is_not_a_valid_project_and_says_where(project):
    err = rejected(project, cmd(type="set_instance_material", id="chassis-1", material="unobtainium"), ReasonCode.INVALID_PROJECT)
    assert "unobtainium" in err.reasons[0].message
    too_wide = {"name": "diameter", **q(5.0, "m")}  # the wheel's range is 0.05 to 0.2 m
    err = rejected(project, cmd(type="set_parameter", instance="wheel-rl", parameter=too_wide), ReasonCode.INVALID_PROJECT)
    assert "outside" in err.reasons[0].message
    assert err.reasons[0].ids == (ref("parameter", "wheel-rl/diameter"),)
    overlap = entry("drive-motor-l", "run-x", 1.0, 2.0, 1.0)
    err = rejected(project, cmd(type="add_control_entry", entry=overlap), ReasonCode.INVALID_PROJECT)  # overlaps 0..5 s
    assert "overlapping" in err.reasons[0].message
    assert {ref("schedule_entry", "run-l"), ref("schedule_entry", "run-x")} <= set(err.reasons[0].ids)
    err = rejected(project, cmd(type="add_control_entry", entry=entry("nobody", "run-y", 9.0, 10.0, 1.0)), ReasonCode.INVALID_PROJECT)
    assert ref("actuator", "nobody") in err.reasons[0].ids


def test_apply_rejects_dangling_joint_actuator_and_part_references(project):
    bad_joint = {
        "id": "j-x",
        "kind": "fixed",
        "a": {"instance": "ghost", "snap_point": "hub"},
        "b": {"instance": "wheel-fl", "snap_point": "hub"},
    }
    err = rejected(project, cmd(type="add_joint", joint=bad_joint), ReasonCode.INVALID_PROJECT)
    assert ref("instance", "ghost") in err.reasons[0].ids  # the dangling id, not only the joint's own
    err = rejected(project, cmd(type="add_actuator", actuator={"id": "a-x", "kind": "thruster", "instance": "ghost"}), ReasonCode.INVALID_PROJECT)
    assert ref("instance", "ghost") in err.reasons[0].ids
    wheel = new_wheel()
    wheel["part"] = "ghost"
    err = rejected(project, cmd(type="add_instance", instance=wheel), ReasonCode.INVALID_PROJECT)
    assert ref("part", "ghost") in err.reasons[0].ids
    err = rejected(project, cmd(type="set_instance_material", id="chassis-1", material="unobtainium"), ReasonCode.INVALID_PROJECT)
    assert ref("material", "unobtainium") in err.reasons[0].ids


def test_apply_rejects_indexes_out_of_range(project):
    rejected(project, cmd(type="add_instance", instance=new_wheel(), index=99), ReasonCode.INDEX_OUT_OF_RANGE)
    rejected(project, cmd(type="add_control_entry", entry=entry("drive-motor-l", "run-z", 6.0, 7.0, 1.0), index=3), ReasonCode.INDEX_OUT_OF_RANGE)
    rejected(project, cmd(type="set_parameter", instance="wheel-rl", parameter={"name": "diameter", **q(0.1, "m")}, index=0), ReasonCode.INVALID_COMMAND)


def test_apply_rejects_selecting_a_planet_that_is_not_an_id(project):
    with pytest.raises(ValidationError):
        cmd(type="select_planet", planet="Mars!")


# --- batch: all or nothing ---------------------------------------------------------------------------------


def test_apply_batch_is_applied_in_order_and_undone_as_one(project):
    batch = cmd(
        type="batch",
        commands=[
            dict(type="add_instance", instance=new_wheel()),
            dict(type="move_instance", id="spare", pose=pose(1.0, 2.0, 0.05)),  # needs the add before it
            dict(type="select_planet", planet="moon"),
        ],
    )
    done = roundtrip(project, batch)
    assert done.project.design.instances[-1].pose.position.y == 2.0
    assert done.project.world.planet == "moon"
    assert isinstance(done.inverse, CommandBatch) and len(done.inverse.commands) == 3


def test_apply_batch_with_one_bad_command_changes_nothing_and_names_it(project):
    batch = cmd(
        type="batch",
        commands=[
            dict(type="select_planet", planet="moon"),
            dict(type="remove_instance", id="ghost"),
        ],
    )
    err = rejected(project, batch, ReasonCode.UNKNOWN_ID)
    assert err.reasons[0].message.startswith("commands[1] (remove_instance):")
    assert project.world.planet == "mars"


def test_apply_batch_cannot_nest_and_cannot_be_empty():
    inner = dict(type="batch", commands=[dict(type="select_planet", planet="moon")])
    with pytest.raises(ValidationError):
        cmd(type="batch", commands=[inner])
    with pytest.raises(ValidationError):
        cmd(type="batch", commands=[])


def test_apply_a_whole_session_and_back(project):
    """Add a part, move it, join it, drive it, then undo everything with the inverses in reverse order."""
    spare_joint = {
        "id": "spare-hub",
        "kind": "hinge",
        "a": {"instance": "chassis-1", "snap_point": "axle-fl"},
        "b": {"instance": "spare", "snap_point": "hub"},
    }
    steps = [
        cmd(type="remove_instance", id="wheel-fl"),
        cmd(type="add_instance", instance=new_wheel()),
        cmd(type="move_instance", id="spare", pose=pose(0.1, 0.1, 0.05)),
        cmd(type="add_joint", joint=spare_joint),
        cmd(type="add_actuator", actuator={"id": "spare-motor", "kind": "motor", "instance": "chassis-1", "joint": "spare-hub"}),
        cmd(type="add_control_entry", entry=entry("spare-motor", "spare-run", 0.0, 1.0, 1.0)),
    ]
    current, undo = project, []
    for step in steps:
        done = apply_command(current, step)
        current = done.project
        undo.append(done.inverse)
    assert current != project
    for inverse in reversed(undo):
        current = apply_command(current, inverse).project
    assert current == project


# --- commands are JSON ------------------------------------------------------------------------------------


def test_apply_commands_and_results_round_trip_through_json(project):
    adapter = TypeAdapter(Command)
    for name, make in COMMANDS.items():
        raw = make()
        if raw is None:
            continue
        command = adapter.validate_python(raw)
        assert adapter.validate_json(adapter.dump_json(command)) == command
        done = apply_command(project, command)
        assert adapter.validate_json(adapter.dump_json(done.inverse)) == done.inverse
        assert Project.model_validate_json(done.project.model_dump_json()) == done.project, name


def test_command_rejects_unknown_type_unknown_field_and_missing_tag():
    for bad in (
        dict(type="teleport", id="x"),
        dict(id="wheel-fl"),
        dict(type="remove_instance", id="wheel-fl", issuer="mouse"),
        dict(type="select_planet", planet="moon", gravity=1.62),  # no command carries a planet constant
    ):
        with pytest.raises(ValidationError):
            cmd(**bad)


def test_command_set_covers_the_dod_list():
    """부품 추가·삭제·이동, 파라미터·재질 설정, 결합·해제, 액추에이터·제어 설정, 가정 수정, 행성 선택."""
    tags = set(TypeAdapter(Command).json_schema()["discriminator"]["mapping"])
    assert {
        "add_instance", "remove_instance", "move_instance",
        "set_parameter", "set_instance_material", "add_material_def",
        "add_joint", "remove_joint",
        "add_actuator", "remove_actuator", "add_control_entry", "replace_control_entry",
        "set_assumption", "add_assumption", "select_planet", "batch",
    } <= tags  # fmt: skip


def test_project_rejects_a_terrain_prop_with_an_unknown_material():
    data = project_data()
    data["world"]["terrain_props"][0]["material"] = "unobtainium"
    with pytest.raises(ValidationError, match="unknown material 'unobtainium'"):
        Project.model_validate(data)


def test_actuate_entry_in_commands_is_the_designspec_one():
    entry = cmd(type="add_control_entry", entry=load("DesignSpec.four-wheel-car.json")["schedule"]["entries"][0]).entry
    assert isinstance(entry, ActuateEntry)


# --- schedule entries are named by id, never by position (review of #497, P1) ------------------------------


def two_entries_project(project):
    """drive-motor-l: run-l (0..5 s) and a later run-l2 (6..7 s); drive-motor-r: run-r."""
    return apply_command(project, cmd(type="add_control_entry", entry=entry("drive-motor-l", "run-l2", 6.0, 7.0, 0.5))).project


def test_apply_partial_accept_of_a_removal_batch_removes_the_entry_meant(project):
    """Plan: remove run-l, then remove run-r. Only the second is accepted: run-r goes, run-l stays."""
    accepted = cmd(type="remove_control_entry", id="run-r")
    result = apply_command(project, accepted).project
    assert [e.id for e in result.design.schedule.entries] == ["run-l"]
    # and the first one alone removes only run-l
    assert [e.id for e in apply_command(project, cmd(type="remove_control_entry", id="run-l")).project.design.schedule.entries] == ["run-r"]


def test_apply_stale_replace_does_not_overwrite_another_entry(project):
    """A replace made against revision N, applied after someone inserted an entry at the front: it still edits the
    entry it named (by id), or is rejected if that entry is gone; it never edits a different one."""
    replace = cmd(type="replace_control_entry", entry=entry("drive-motor-r", "run-r", 0.0, 2.0, -1.0))
    newer = apply_command(project, cmd(type="add_control_entry", index=0, entry=entry("drive-motor-l", "run-new", 6.0, 7.0, 1.0))).project
    result = apply_command(newer, replace).project
    by_id = {e.id: e for e in result.design.schedule.entries}
    assert by_id["run-r"].command == -1.0 and by_id["run-r"].end == 2.0
    assert by_id["run-new"].command == 1.0 and by_id["run-l"].command == 1.0  # untouched
    gone = apply_command(newer, cmd(type="remove_control_entry", id="run-r")).project
    rejected(gone, replace, ReasonCode.UNKNOWN_ID)


def test_apply_add_control_entry_index_is_only_a_position(project):
    done = roundtrip(project, cmd(type="add_control_entry", index=1, entry=entry("drive-motor-l", "run-mid", 6.0, 7.0, 0.1)))
    assert [e.id for e in done.project.design.schedule.entries] == ["run-l", "run-mid", "run-r"]
    assert done.inverse == cmd(type="remove_control_entry", id="run-mid")
    rejected(project, cmd(type="add_control_entry", entry=entry("drive-motor-l", "run-l", 6.0, 7.0, 0.1)), ReasonCode.DUPLICATE_ID)


def test_apply_remove_control_entry_inverse_restores_its_position(project):
    project = two_entries_project(project)
    done = roundtrip(project, cmd(type="remove_control_entry", id="run-l"))
    assert [e.id for e in done.project.design.schedule.entries] == ["run-r", "run-l2"]


# --- replace in place (review of #497, P2) -----------------------------------------------------------------


def test_apply_replace_material_def_in_place_while_in_use(project):
    done = roundtrip(project, cmd(**COMMANDS["replace_material_def"]()))
    assert done.project.design.materials[0].name == "Example, edited"
    # a material that instances and both terrain props use can be replaced, though it cannot be removed
    rejected(project, cmd(type="remove_material_def", id="example-material"), ReasonCode.IN_USE)
    assert [m.id for m in done.project.design.materials] == [m.id for m in project.design.materials]


def test_apply_replace_part_def_in_place_while_in_use(project):
    done = roundtrip(project, cmd(**COMMANDS["replace_part_def"]()))
    assert next(p for p in done.project.design.parts if p.id == "motor").name == "Motor, edited"
    assert [p.id for p in done.project.design.parts] == [p.id for p in project.design.parts]


def test_apply_replace_part_def_that_breaks_its_users_is_rejected_with_the_refs(project):
    wheel = next(p for p in load("DesignSpec.four-wheel-car.json")["parts"] if p["id"] == "wheel")
    no_parameters = {**wheel, "parameters": []}  # wheel-rl sets `diameter`
    err = rejected(project, cmd(type="replace_part_def", part=no_parameters), ReasonCode.INVALID_PROJECT)
    assert "no parameter 'diameter'" in err.reasons[0].message
    assert ref("parameter", "wheel-rl/diameter") in err.reasons[0].ids
    no_hub = {**wheel, "snap_points": []}  # four joints end on the hub
    err = rejected(project, cmd(type="replace_part_def", part=no_hub), ReasonCode.INVALID_PROJECT)
    assert any(r.kind is RefKind.SNAP_POINT for r in err.reasons[0].ids)
    narrow = {**wheel, "parameters": [{**wheel["parameters"][0], "max": q(0.09, "m"), "default": q(0.07, "m")}]}
    rejected(project, cmd(type="replace_part_def", part=narrow), ReasonCode.INVALID_PROJECT)  # wheel-rl sets 0.1


def test_apply_replace_joint_keeps_position_motor_and_schedule(project):
    done = roundtrip(project, cmd(**COMMANDS["replace_joint"]()))
    d = done.project.design
    assert ids(d.joints) == ids(project.design.joints)  # same place in the list
    assert d.joints[2].break_threshold.value == 50.0
    assert ids(d.actuators) == ids(project.design.actuators)  # the motor on drive-l is still there
    assert [e.id for e in d.schedule.entries] == ["run-l", "run-r"]


def test_apply_replace_joint_that_strands_its_motor_is_rejected(project):
    drive_l = next(j for j in load("DesignSpec.four-wheel-car.json")["joints"] if j["id"] == "drive-l")
    err = rejected(project, cmd(type="replace_joint", joint={**drive_l, "kind": "fixed"}), ReasonCode.INVALID_PROJECT)
    assert "fixed" in err.reasons[0].message
    assert {ref("joint", "drive-l"), ref("actuator", "drive-motor-l")} <= set(err.reasons[0].ids)


# --- assumptions that are not editable ---------------------------------------------------------------------


def locked_project(project):
    table = project_data()["assumptions"]["assumptions"][0]
    data = project_data()
    data["assumptions"]["assumptions"][0] = {**table, "editable": False}
    return Project.model_validate(data), data["assumptions"]["assumptions"][0]


def test_apply_refuses_to_change_or_remove_a_non_editable_assumption(project):
    locked, assumption = locked_project(project)
    rejected(locked, cmd(type="set_assumption", assumption={**assumption, "label": "x"}), ReasonCode.NOT_EDITABLE)
    rejected(locked, cmd(type="set_assumption", assumption={**assumption, "editable": True}), ReasonCode.NOT_EDITABLE)
    rejected(locked, cmd(type="remove_assumption", key=assumption["key"]), ReasonCode.NOT_EDITABLE)


def test_apply_refuses_to_flip_editable_or_add_a_non_editable_assumption(project):
    first = project_data()["assumptions"]["assumptions"][0]
    rejected(project, cmd(type="set_assumption", assumption={**first, "editable": False}), ReasonCode.NOT_EDITABLE)
    other = {**first, "key": "locked_one", "editable": False}
    rejected(project, cmd(type="add_assumption", assumption=other), ReasonCode.NOT_EDITABLE)


# --- batches: every intermediate state is valid; no-ops -----------------------------------------------------


def test_apply_batch_swapping_two_slots_is_rejected_at_the_first_command_and_a_reordered_one_works(project):
    project = two_entries_project(project)  # run-l 0..5 s and run-l2 6..7 s on drive-motor-l
    swap = cmd(
        type="batch",
        commands=[
            dict(type="replace_control_entry", entry=entry("drive-motor-l", "run-l", 6.0, 7.0, 1.0)),
            dict(type="replace_control_entry", entry=entry("drive-motor-l", "run-l2", 0.0, 5.0, 0.5)),
        ],
    )
    err = rejected(project, swap, ReasonCode.INVALID_PROJECT)
    assert err.reasons[0].message.startswith("commands[0] (replace_control_entry):") and "overlapping" in err.reasons[0].message
    ordered = cmd(
        type="batch",
        commands=[
            dict(type="remove_control_entry", id="run-l2"),
            dict(type="replace_control_entry", entry=entry("drive-motor-l", "run-l", 6.0, 7.0, 1.0)),
            dict(type="add_control_entry", entry=entry("drive-motor-l", "run-l2", 0.0, 5.0, 0.5)),
        ],
    )
    roundtrip(project, ordered)


def test_apply_a_command_that_sets_what_is_there_is_accepted_and_changes_nothing(project):
    done = apply_command(project, cmd(type="select_planet", planet=project.world.planet))
    assert done.project == project and done.inverse == cmd(type="select_planet", planet=project.world.planet)
    same = project.design.instances[1]
    done = apply_command(project, cmd(type="move_instance", id=same.id, pose=same.pose.model_dump(mode="json")))
    assert done.project == project


def test_apply_result_is_not_the_wire_message_name():
    import kinetra_core

    assert hasattr(kinetra_core, "ApplyResult") and not hasattr(kinetra_core, "Applied")


def test_project_is_compatible_with_check_world_references(project):
    """W-01's rule takes a `World` and the project's material ids; a `Project` that validates passes its material
    half, and the planet half (the planet has data) stays the validator's (C-02c)."""
    check_world_references(project.world, planets=["mars", "moon", "earth"], materials=[m.id for m in project.design.materials])
    with pytest.raises(ValueError, match="unknown planet"):
        check_world_references(project.world, planets=["moon"], materials=[m.id for m in project.design.materials])
