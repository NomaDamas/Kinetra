"""C-02c: the validator. Fixtures are declared by the test (`사용자 선언`): two 0.2 m cubes that stack, on Earth.

Every rejection is checked for its code, the refs it names and that the project is untouched; every acceptance for the
exact project it returns. The helpers build a project from plain dicts so a test shows what it changes.
"""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from kinetra_core import (
    CommandBatch,
    CommandRejected,
    Project,
    ReasonCode,
    Ref,
    RefKind,
    apply_command,
    check_placement,
    load_material_catalog,
    parse_command,
    validate_command,
)

SRC = {"ref": "unit-test fixture", "locator": "test_validator.py"}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"


def q(value, unit="m"):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(offset):
    return {"offset": offset, "terms": []}


def pos(x=0.0, y=0.0, z=0.0):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def snap(id, z, kind="stack", accepts=("stack",)):
    return {"id": id, "kind": kind, "accepts": list(accepts), "position": pos(z=z), "orientation": IDENTITY, "badge": "declared", "source": SRC}


def cube_part(id="cube", size=0.2, shape=True, snaps=None):
    part = {
        "id": id,
        "name": "Cube",
        "parameters": [{"name": "side", "unit": "m", "default": q(size), "min": q(0.05), "max": q(1.0)}],
        "snap_points": snaps if snaps is not None else [snap("top", size / 2), snap("bottom", -size / 2)],
    }
    if shape:
        side = {"offset": 0.0, "terms": [{"param": "side", "factor": 1.0}]}
        part["shape"] = {
            "badge": "declared",
            "source": SRC,
            "components": [{"id": "body", "operation": "add", "primitive": {"kind": "box", "size_x": side, "size_y": side, "size_z": side}, "position": pos()}],
        }
    return part


def pose(x=0.0, y=0.0, z=0.0, orientation=IDENTITY):
    return {"position": {"x": x, "y": y, "z": z}, "orientation": orientation, "badge": "declared", "source": SRC}


def instance(id, x=0.0, y=0.0, z=0.1, part="cube", **extra):
    return {"id": id, "part": part, "pose": pose(x, y, z), **extra}


def fixed(id, a, a_snap, b, b_snap):
    return {"id": id, "kind": "fixed", "a": {"instance": a, "snap_point": a_snap}, "b": {"instance": b, "snap_point": b_snap}}


def project_data(**design):
    return {
        "design": {"parts": [cube_part()], "instances": [instance("base")], **design},
        "world": {"planet": "earth"},
    }


def make(**design):
    return Project.model_validate(project_data(**design))


def stacked():
    """`base` on the ground (z 0 .. 0.2) with `top-cube` on it (0.2 .. 0.4), joined top to bottom."""
    return make(
        instances=[instance("base"), instance("top-cube", z=0.3)],
        joints=[fixed("weld", "base", "top", "top-cube", "bottom")],
    )


def loose_stack():
    """The same two cubes, not joined."""
    return make(instances=[instance("base"), instance("top-cube", z=0.3)])


def cmd(**d):
    return parse_command(d)


def move(id, x=0.0, y=0.0, z=0.1, orientation=IDENTITY):
    return cmd(type="move_instance", id=id, pose=pose(x, y, z, orientation))


def reject(project, command, code, *refs):
    """`validate_command` refuses with `code` first, names `refs` among its ids, and leaves the project alone."""
    before = project.model_dump_json()
    with pytest.raises(CommandRejected) as e:
        validate_command(project, command)
    assert project.model_dump_json() == before
    assert e.value.reasons[0].code is code, e.value
    named = {(r.kind, r.id) for reason in e.value.reasons for r in reason.ids}
    for r in refs:
        assert (r.kind, r.id) in named, (r, e.value)
    return e.value


def inst(i):
    return Ref(kind=RefKind.INSTANCE, id=i)


# --- what passes -------------------------------------------------------------------------------------------


def test_validator_accepts_a_stacked_assembly_and_returns_what_apply_returns():
    project = stacked()
    assert check_placement(project) == ()
    command = move("top-cube", 0.0, 0.0, 0.3)  # the same pose: nothing changes
    assert validate_command(project, command) == apply_command(project, command)


def test_validator_touching_faces_are_not_an_overlap():
    project = make(instances=[instance("base"), instance("next", x=0.2)])  # share the face x = 0.1
    assert check_placement(project) == ()


def test_validator_parts_without_shape_have_no_geometry_and_are_not_judged():
    """A limit, not a pass: nothing is known about such a part, so overlap and floating cannot be called."""
    project = make(parts=[cube_part(shape=False)], instances=[instance("a", z=5.0), instance("b", z=5.0)])
    assert check_placement(project) == ()


def test_validator_the_example_car_has_no_shapes_and_passes_the_snap_checks():
    design = json.loads((EXAMPLES / "DesignSpec.four-wheel-car.json").read_text(encoding="utf-8"))
    world = json.loads((EXAMPLES / "World.ramp-and-step.json").read_text(encoding="utf-8"))
    assumptions = json.loads((EXAMPLES / "AssumptionTable.vehicle-mass.json").read_text(encoding="utf-8"))
    project = Project.model_validate({"design": design, "world": world, "assumptions": assumptions})
    assert check_placement(project) == ()


def test_validator_takes_no_origin_so_every_source_gets_the_same_answer():
    """Mouse, agent, voice, XR and MCP are the history's record (C-02b); the gate has no parameter to treat them apart."""
    params = set(inspect.signature(validate_command).parameters)
    assert params == {"project", "command", "tolerance"}


def test_validator_a_batch_is_judged_on_its_end_state():
    """Moving a whole stack passes though the middle of the batch has a loose joint; the end state is whole."""
    project = stacked()
    batch = cmd(
        type="batch",
        commands=[
            dict(type="move_instance", id="base", pose=pose(1.0, 0.0, 0.1)),
            dict(type="move_instance", id="top-cube", pose=pose(1.0, 0.0, 0.3)),
        ],
    )
    result = validate_command(project, batch)
    assert check_placement(result.project) == ()
    assert result.project.design.instances[0].pose.position.x == 1.0


def test_validator_blames_a_command_only_for_what_it_introduces():
    """A project that already floats can still be edited elsewhere; a command that adds a new problem is refused."""
    project = make(instances=[instance("base"), instance("high", x=2.0, z=3.0)])  # `high` floats before any command
    assert [r.code for r in check_placement(project)] == [ReasonCode.FLOATING]
    result = validate_command(project, cmd(type="set_parameter", instance="base", parameter={"name": "side", **q(0.2)}))
    assert result.project.design.instances[0].parameters[0].value == 0.2
    reject(project, move("base", 0.0, 0.0, 2.0), ReasonCode.FLOATING, inst("base"))


# --- rejections: the six the DoD asks for ------------------------------------------------------------------


def test_validator_rejects_a_schema_violation_with_one_reason_per_problem():  # 1
    with pytest.raises(CommandRejected) as e:
        parse_command({"type": "move_instance", "id": "base", "pose": {"position": {"x": 0, "y": 0}}, "extra": 1})
    assert {r.code for r in e.value.reasons} == {ReasonCode.INVALID_COMMAND}
    assert len(e.value.reasons) >= 2
    with pytest.raises(CommandRejected) as e:
        parse_command({"type": "teleport_instance", "id": "base"})
    assert e.value.reasons[0].code is ReasonCode.INVALID_COMMAND


def test_validator_rejects_an_overlap_and_names_both_instances():  # 2
    project = loose_stack()
    err = reject(project, move("top-cube", 0.0, 0.0, 0.25), ReasonCode.OVERLAP, inst("base"), inst("top-cube"))
    assert "overlap" in err.reasons[0].message


def test_validator_rejects_a_part_below_the_ground():
    project = make()
    reject(project, move("base", 0.0, 0.0, 0.05), ReasonCode.OVERLAP, inst("base"))


def test_validator_rejects_a_floating_part_and_names_the_group():  # 3
    project = stacked()
    reject(project, move("base", 0.0, 0.0, 1.0), ReasonCode.INVALID_SNAP)  # alone it also tears the joint
    batch = cmd(
        type="batch",
        commands=[
            dict(type="move_instance", id="base", pose=pose(0.0, 0.0, 1.0)),
            dict(type="move_instance", id="top-cube", pose=pose(0.0, 0.0, 1.2)),
        ],
    )
    err = reject(project, batch, ReasonCode.FLOATING, inst("base"), inst("top-cube"))  # the whole stack hovers
    assert "float" in err.reasons[0].message


def test_validator_a_part_resting_on_a_terrain_prop_is_supported():
    step = {
        "kind": "step",
        "id": "kerb",
        "placement": {"x": 3.0, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC},
        "length": q(1.0),
        "width": q(1.0),
        "height": q(0.5),
    }
    project = Project.model_validate({**project_data(), "world": {"planet": "earth", "terrain_props": [step]}})
    on_step = move("base", 3.0, 0.0, 0.6)  # bottom at 0.5, the top of the step
    assert validate_command(project, on_step).project.design.instances[0].pose.position.z == 0.6
    reject(project, move("base", 3.0, 0.0, 0.8), ReasonCode.FLOATING, inst("base"))


def test_validator_rejects_snap_points_that_do_not_accept_each_other():  # 4
    parts = [cube_part(snaps=[snap("top", 0.1, kind="plug", accepts=("socket",)), snap("bottom", -0.1, kind="plug", accepts=("socket",))])]
    project = make(parts=parts, instances=[instance("base"), instance("top-cube", z=0.3)])
    bad = cmd(type="add_joint", joint=fixed("weld", "base", "top", "top-cube", "bottom"))
    err = reject(project, bad, ReasonCode.INVALID_SNAP, Ref(kind=RefKind.JOINT, id="weld"), Ref(kind=RefKind.SNAP_POINT, id="base/top"))
    assert "not compatible" in err.reasons[0].message


def test_validator_rejects_a_joint_whose_snap_points_do_not_meet():  # 5
    project = make(instances=[instance("base"), instance("top-cube", z=0.3)])
    far = cmd(type="move_instance", id="top-cube", pose=pose(0.0, 0.0, 0.3))
    assert validate_command(project, far).project == project
    joined = validate_command(project, cmd(type="add_joint", joint=fixed("weld", "base", "top", "top-cube", "bottom"))).project
    err = reject(joined, move("top-cube", 0.5, 0.0, 0.3), ReasonCode.INVALID_SNAP, Ref(kind=RefKind.JOINT, id="weld"))
    assert "0.5 m apart" in err.reasons[0].message


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "set_gravity", "value": 1.62},
        {"type": "select_planet", "planet": "moon", "gravity": q(1.62, "m/s^2")},
        {"type": "select_planet", "planet": "moon", "ground_friction": 0.2},
        {"type": "set_planet_constants", "planet": "mars", "air_density": q(0.02, "kg/m^3")},
        {"type": "set_verdict", "p_success": 0.99},
        {"type": "batch", "commands": [{"type": "select_planet", "planet": "mars", "insolation": 600}]},
    ],
)
def test_validator_rejects_commands_that_carry_a_planet_constant_or_a_verdict(payload):  # 6
    with pytest.raises(CommandRejected) as e:
        parse_command(payload)
    assert e.value.reasons[0].code is ReasonCode.FORBIDDEN
    assert "data/bodies" in e.value.reasons[0].message or "verdict" in e.value.reasons[0].message


def test_validator_rejects_an_assumption_named_like_a_planet_constant():
    project = make()
    assumption = {"key": "gravity", "label": "Gravity", "value": q(1.62, "m/s^2"), "confidence": "low", "editable": True}
    reject(project, cmd(type="add_assumption", assumption=assumption), ReasonCode.FORBIDDEN, Ref(kind=RefKind.ASSUMPTION, id="gravity"))


def test_validator_rejects_a_planet_that_has_no_data():  # C-01c carry-over (1)
    project = make()
    reject(project, cmd(type="select_planet", planet="venus"), ReasonCode.UNKNOWN_ID, Ref(kind=RefKind.PLANET, id="venus"))
    assert validate_command(project, cmd(type="select_planet", planet="mars")).project.world.planet == "mars"


def test_validator_a_project_already_on_an_unknown_planet_is_reported_by_check_placement():
    project = Project.model_validate({**project_data(), "world": {"planet": "venus"}})
    assert [r.code for r in check_placement(project)] == [ReasonCode.UNKNOWN_ID]


def test_validator_terrain_prop_material_must_be_a_project_material():  # C-01c carry-over (2)
    prop = {
        "kind": "ramp",
        "id": "ramp-1",
        "material": "oak",
        "placement": {"x": 2.0, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC},
        "length": q(2.0),
        "width": q(1.0),
        "incline": q(0.3, "rad"),
    }
    with pytest.raises(ValueError, match="unknown material 'oak'"):
        Project.model_validate({**project_data(), "world": {"planet": "earth", "terrain_props": [prop]}})
    catalog = load_material_catalog().entries[0].material
    project = make(materials=[catalog.model_dump(mode="json")])
    world_with_prop = {**project_data(materials=[catalog.model_dump(mode="json")]), "world": {"planet": "earth", "terrain_props": [{**prop, "material": catalog.id}]}}
    on_ramp = Project.model_validate(world_with_prop)
    # removing the material the prop stands on is refused by the project's own reference check
    reject(on_ramp, cmd(type="remove_material_def", id=catalog.id), ReasonCode.IN_USE)
    assert project.design.materials[0] == catalog


def test_validator_the_catalog_cannot_be_changed_by_a_command():
    entry = load_material_catalog().entries[0].material
    project = make(materials=[entry.model_dump(mode="json")])
    altered = copy.deepcopy(entry.model_dump(mode="json"))
    altered["density"]["value"] = altered["density"]["value"] * 2
    reject(project, cmd(type="replace_material_def", material=altered), ReasonCode.FORBIDDEN, Ref(kind=RefKind.MATERIAL, id=entry.id))
    # the catalog's own definition, unchanged, is fine; so is a material of the user's own with another id
    same = validate_command(make(), cmd(type="add_material_def", material=entry.model_dump(mode="json")))
    assert same.project.design.materials == (entry,)
    mine = {**altered, "id": "my-aluminium"}
    assert validate_command(make(), cmd(type="add_material_def", material=mine)).project.design.materials[0].id == "my-aluminium"


def test_validator_a_not_editable_assumption_stays_the_systems():  # editable: false (C-01c / C-02a carry-over)
    system = {"key": "vehicle_mass", "label": "Mass", "value": q(2.0, "kg"), "confidence": "med", "editable": False}
    project = Project.model_validate({**project_data(), "assumptions": {"assumptions": [system]}})
    reject(project, cmd(type="set_assumption", assumption={**system, "value": q(3.0, "kg")}), ReasonCode.NOT_EDITABLE)
    reject(project, cmd(type="remove_assumption", key="vehicle_mass"), ReasonCode.NOT_EDITABLE)
    reject(project, cmd(type="set_assumption", assumption={**system, "editable": True}), ReasonCode.NOT_EDITABLE)


def test_validator_a_refused_batch_names_the_command_and_changes_nothing():
    project = stacked()
    batch = cmd(
        type="batch",
        commands=[
            dict(type="move_instance", id="base", pose=pose(5.0, 0.0, 0.1)),  # the joint breaks: both moves are needed
        ],
    )
    err = reject(project, batch, ReasonCode.INVALID_SNAP, Ref(kind=RefKind.JOINT, id="weld"))
    assert len(err.reasons) == 1
    assert isinstance(batch, CommandBatch)


def test_validator_reasons_survive_a_json_round_trip():
    project = loose_stack()
    with pytest.raises(CommandRejected) as e:
        validate_command(project, move("top-cube", 0.0, 0.0, 0.25))
    for reason in e.value.reasons:
        assert type(reason).model_validate_json(reason.model_dump_json()) == reason


# --- terrain props are obstacles as well as supports ---------------------------------------------------------


def with_props(*props):
    return Project.model_validate({**project_data(), "world": {"planet": "earth", "terrain_props": list(props)}})


def step_prop(x=3.0, height=0.5):
    return {"kind": "step", "id": "kerb", "placement": {"x": x, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC}, "length": q(1.0), "width": q(1.0), "height": q(height)}


def ramp_prop(x=3.0):
    """Rises along +x from z = 0 at x = 2 to z = 1.0 at x = 4 (length 2 m, incline 0.4636 rad = atan(0.5))."""
    return {"kind": "ramp", "id": "slope", "placement": {"x": x, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC}, "length": q(2.0), "width": q(1.0), "incline": q(0.4636476090008061, "rad")}


def test_validator_a_part_inside_a_step_overlaps_it_and_is_not_supported_by_it():
    project = with_props(step_prop())
    err = reject(project, move("base", 3.0, 0.0, 0.4), ReasonCode.OVERLAP, inst("base"), Ref(kind=RefKind.PROP, id="kerb"))  # the cube spans z 0.3 .. 0.5, inside the step's 0 .. 0.5
    assert "penetrates terrain prop 'kerb'" in err.reasons[0].message
    assert [r.code for r in err.reasons] == [ReasonCode.OVERLAP]  # refused for the penetration, not also called floating


def test_validator_a_part_under_a_ramps_slope_overlaps_it_and_one_on_it_is_supported():
    project = with_props(ramp_prop())
    # cube side 0.2: at x = 2.5 the slope is 0.25 m high; centre z = 0.125 puts the cube's top corner inside the ramp
    reject(project, move("base", 2.5, 0.0, 0.125), ReasonCode.OVERLAP, inst("base"), Ref(kind=RefKind.PROP, id="slope"))
    # resting on the slope: the cube's lower uphill edge (x = 2.6) on the slope, which is 0.3 m high there: centre z = 0.4
    on_slope = validate_command(project, move("base", 2.5, 0.0, 0.4))
    assert on_slope.project.design.instances[0].pose.position.z == 0.4


def test_validator_beside_a_ramp_slope_floats():
    """The exact wedge, not a bounding box: a cube hovering over the empty corner above the slope has no support."""
    project = with_props(ramp_prop())
    reject(project, move("base", 3.9, 0.0, 1.5), ReasonCode.FLOATING, inst("base"))
    reject(project, move("base", 2.2, 0.0, 0.6), ReasonCode.FLOATING, inst("base"))  # above the low end of the slope


def test_validator_a_new_ground_penetration_is_not_masked_by_an_old_pair_overlap():
    """An instance may be called `ground`: its pair with `base` and `base`'s ground contact are different findings."""
    project = make(instances=[instance("base"), instance("ground", x=0.1, z=0.1)])  # base and ground overlap already
    assert [r.code for r in check_placement(project)] == [ReasonCode.OVERLAP]
    err = reject(project, move("base", 0.0, 0.0, 0.05), ReasonCode.OVERLAP, inst("base"))  # now also below z = 0
    assert any("below the ground" in r.message for r in err.reasons)


def test_validator_undo_is_not_a_placement_check():
    """Documented rule (project-model.md): the inverse of an accepted edit is applied by `apply_command` only."""
    from kinetra_core import History, Origin

    project = with_props(step_prop())
    done = validate_command(project, move("base", 3.0, 0.0, 0.6))
    history = History().execute(project, move("base", 3.0, 0.0, 0.6), Origin.MOUSE).history
    assert history.undo(done.project).project == project
