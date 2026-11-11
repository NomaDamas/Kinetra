"""C-06: a project whose part or material definitions are missing opens, keeps the instances as placeholders, refuses to
compile, run, judge or export, and can be repaired by commands. Fixture: the committed four-wheel-car example with
the `wheel` part (and, in one test, the material) taken out of the file."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from kinetra_core import (
    BlockedOperation,
    Command,
    CommandRejected,
    History,
    Origin,
    Project,
    ProjectIncomplete,
    ReasonCode,
    Ref,
    RefKind,
    apply_command,
    catalog_differences,
    check_placement,
    definition_hash,
    dump_project,
    load_material_catalog,
    material_catalog_hashes,
    missing_definitions,
    open_report,
    parse_project,
    project_file,
    require_complete,
    validate_command,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"
WHEELS = ["wheel-rl", "wheel-rr", "wheel-fl", "wheel-fr"]


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def car_data():
    return load("Project.four-wheel-car.json")


def cmd(**d):
    return TypeAdapter(Command).validate_python(d)


def without_part(data, part_id):
    data = copy.deepcopy(data)
    data["design"]["parts"] = [p for p in data["design"]["parts"] if p["id"] != part_id]
    return data


def wheel_def():
    return next(p for p in car_data()["design"]["parts"] if p["id"] == "wheel")


@pytest.fixture
def complete():
    return Project.model_validate(car_data())


@pytest.fixture
def broken():
    """The car with its `wheel` definition missing: four placeholder instances, four joints and two motors on them."""
    return Project.model_validate(without_part(car_data(), "wheel"))


def opened(project: Project) -> Project:
    """Through the file: save bytes, open them."""
    return parse_project(dump_project(project)).project


def reasons_of(project, command):
    with pytest.raises(CommandRejected) as e:
        validate_command(project, command)
    return e.value.reasons


# --- opening -------------------------------------------------------------------------------------------------


def test_missing_definition_project_opens_and_lists_what_is_missing(broken):
    (m,) = missing_definitions(broken)
    assert (m.kind, m.id, m.instances) == ("part", "wheel", tuple(WHEELS))
    assert missing_definitions(Project.model_validate(car_data())) == ()
    assert open_report(broken).complete is False


def test_missing_definition_placeholder_keeps_pose_parameters_and_joint_references(broken, complete):
    """The instance is the stored instance; its joints, and what hangs on them, are still there."""
    for wid in WHEELS:
        a = next(i for i in broken.design.instances if i.id == wid)
        b = next(i for i in complete.design.instances if i.id == wid)
        assert a == b  # pose, parameters, material, part id: nothing replaced, nothing made up
    assert broken.design.joints == complete.design.joints
    assert broken.design.actuators == complete.design.actuators
    assert [p.id for p in broken.design.parts] == ["chassis", "motor"]  # no stand-in definition was added


def test_missing_definition_file_opens_and_does_not_hash_what_it_does_not_carry(broken):
    file = parse_project(dump_project(broken))
    assert {(d.kind, d.id) for d in file.definitions} == {("material", "example-material"), ("part", "chassis"), ("part", "motor")}
    assert file.project == broken


def test_missing_definition_roundtrip_through_the_file_keeps_the_placeholders_byte_for_byte(broken, tmp_path):
    first = dump_project(broken)
    again = opened(broken)
    assert again == broken and dump_project(again) == first
    assert missing_definitions(again) == missing_definitions(broken)


def test_missing_definition_a_missing_material_is_listed_too():
    data = car_data()
    data["design"]["instances"][0]["material"] = "unobtainium"
    project = Project.model_validate(data)
    (m,) = missing_definitions(project)
    assert (m.kind, m.id, m.instances) == ("material", "unobtainium", ("chassis-1",))
    assert opened(project) == project


def test_missing_definition_a_terrain_prop_without_its_material_still_does_not_open():
    data = car_data()
    data["world"]["terrain_props"][0]["material"] = "unobtainium"
    with pytest.raises(ValueError, match="unobtainium"):
        Project.model_validate(data)


def test_missing_definition_what_is_not_a_definition_is_still_refused():
    data = without_part(car_data(), "wheel")
    data["design"]["joints"][0]["a"]["instance"] = "ghost"
    with pytest.raises(ValueError, match="unknown instance 'ghost'"):
        Project.model_validate(data)
    data = without_part(car_data(), "chassis")  # a snap point of a part that is there still has to exist
    data["design"]["joints"][-1]["a"]["snap_point"] = "no-such-point"
    Project.model_validate(data)  # its end sits on a placeholder or not: the checked ends are those with a definition
    data = car_data()
    data["design"]["joints"][-1]["a"]["snap_point"] = "no-such-point"
    with pytest.raises(ValueError, match="no snap point"):
        Project.model_validate(data)


def test_missing_definition_placement_checks_skip_a_placeholder_and_do_not_invent_geometry(broken, complete):
    assert check_placement(broken) == check_placement(complete) == ()


# --- refusing --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation", list(BlockedOperation))
def test_missing_definition_compile_run_verdict_and_export_are_refused_with_the_ids(broken, operation):
    with pytest.raises(ProjectIncomplete) as e:
        require_complete(broken, operation)
    err = e.value
    assert err.operation is operation
    assert [(m.kind, m.id) for m in err.missing] == [("part", "wheel")]
    assert "wheel" in str(err) and operation.value in str(err)
    (reason,) = err.reasons
    assert reason.code is ReasonCode.MISSING_DEFINITION
    assert reason.ids[0] == Ref(kind=RefKind.PART, id="wheel")
    assert {r.id for r in reason.ids[1:]} == set(WHEELS)


def test_missing_definition_a_complete_project_passes_the_gate(complete):
    for operation in BlockedOperation:
        require_complete(complete, operation)


def test_missing_definition_both_kinds_are_listed_in_one_refusal():
    data = without_part(car_data(), "wheel")
    data["design"]["instances"][0]["material"] = "unobtainium"
    with pytest.raises(ProjectIncomplete) as e:
        require_complete(Project.model_validate(data), BlockedOperation.RUN)
    assert [(m.kind, m.id) for m in e.value.missing] == [("part", "wheel"), ("material", "unobtainium")]
    assert len(e.value.reasons) == 2


# --- repairing: commands -----------------------------------------------------------------------------------------


def test_missing_definition_adding_the_definition_relinks_every_placeholder_and_undo_makes_them_again(broken):
    add = cmd(type="add_part_def", part=wheel_def(), index=2)
    done = validate_command(broken, add)
    require_complete(done.project, BlockedOperation.COMPILE)
    assert done.project.design.parts[2].id == "wheel"
    undone = apply_command(done.project, done.inverse)
    assert undone.project == broken
    assert apply_command(undone.project, undone.inverse).project == done.project


def test_missing_definition_relink_to_another_part_is_a_command_and_is_checked_against_the_joints(broken):
    reasons = reasons_of(broken, cmd(type="relink_instance", id="wheel-fl", part="chassis"))
    assert reasons[0].code is ReasonCode.INVALID_PROJECT  # chassis has no snap point 'hub'
    assert Ref(kind=RefKind.SNAP_POINT, id="wheel-fl/hub") in reasons[0].ids


def test_missing_definition_relink_to_a_carried_part_and_undo():
    """A project whose wheels name an old part id `wheel-v1`; the user relinks them to the `wheel` it carries."""
    data = car_data()
    for inst in data["design"]["instances"]:
        if inst["id"] in WHEELS:
            inst["part"] = "wheel-v1"
    project = Project.model_validate(data)
    assert [m.id for m in missing_definitions(project)] == ["wheel-v1"]
    history = History()
    for n, wid in enumerate(WHEELS):
        edit = history.execute(project, cmd(type="relink_instance", id=wid, part="wheel"), Origin.MOUSE)
        project, history = edit.project, edit.history
        assert [list(m.instances) for m in missing_definitions(project)] == ([WHEELS[n + 1 :]] if n < 3 else [])
    require_complete(project, BlockedOperation.RUN)
    assert project == Project.model_validate(car_data())
    for _ in WHEELS:
        edit = history.undo(project)
        project, history = edit.project, edit.history
    assert [m.id for m in missing_definitions(project)] == ["wheel-v1"]


def test_missing_definition_relink_to_a_part_that_is_not_carried_is_not_a_relink(broken):
    reasons = reasons_of(broken, cmd(type="relink_instance", id="wheel-fl", part="ghost"))
    assert reasons[0].code is ReasonCode.MISSING_DEFINITION
    assert Ref(kind=RefKind.PART, id="ghost") in reasons[0].ids


def test_missing_definition_deleting_the_placeholders_is_a_command_and_completes_the_project(broken):
    project = broken
    history = History()
    for wid in WHEELS:
        edit = history.execute(project, cmd(type="remove_instance", id=wid), Origin.MOUSE)
        project, history = edit.project, edit.history
    require_complete(project, BlockedOperation.EXPORT_HALO)
    assert {i.id for i in project.design.instances} == {"chassis-1", "motor-l", "motor-r"}
    for _ in WHEELS:
        edit = history.undo(project)
        project, history = edit.project, edit.history
    assert project == broken  # the placeholders are back, with their joints
    assert [m.id for m in missing_definitions(project)] == ["wheel"]


def test_missing_definition_a_material_is_repaired_by_set_instance_material_or_add_material_def():
    data = car_data()
    data["design"]["instances"][0]["material"] = "unobtainium"
    project = Project.model_validate(data)
    require_complete(validate_command(project, cmd(type="set_instance_material", id="chassis-1", material=None)).project, BlockedOperation.RUN)
    material = {**load("Material.example.json"), "id": "unobtainium"}
    done = validate_command(project, cmd(type="add_material_def", material=material))
    require_complete(done.project, BlockedOperation.RUN)
    assert apply_command(done.project, done.inverse).project == project


def test_missing_definition_removing_a_definition_that_is_in_use_is_still_in_use_and_no_command_makes_a_placeholder(complete):
    reasons = reasons_of(complete, cmd(type="remove_part_def", id="wheel"))
    assert reasons[0].code is ReasonCode.IN_USE
    # the escape hatch of an inverse is not available to a sender
    reasons = reasons_of(complete, cmd(type="remove_part_def", id="wheel", unlink=True))
    assert reasons[0].code is ReasonCode.MISSING_DEFINITION
    assert {r.id for r in reasons[0].ids} >= {"wheel", *WHEELS}
    reasons = reasons_of(complete, cmd(type="remove_material_def", id="example-material", unlink=True))
    assert reasons[0].code is ReasonCode.IN_USE  # terrain props use it too: unlink never releases a prop


def test_missing_definition_a_command_cannot_add_an_instance_of_a_part_that_is_not_there(complete):
    wheel = copy.deepcopy(next(i for i in car_data()["design"]["instances"] if i["id"] == "wheel-fl"))
    wheel.update(id="spare", part="ghost")
    reasons = reasons_of(complete, cmd(type="add_instance", instance=wheel))
    assert reasons[0].code is ReasonCode.MISSING_DEFINITION and reasons[0].ids[0] == Ref(kind=RefKind.PART, id="ghost")


def test_missing_definition_other_edits_of_a_broken_project_are_accepted(broken):
    """Moving a placeholder or a part that is there is allowed: what is missing now stays missing, nothing new is."""
    pose = next(i for i in broken.design.instances if i.id == "wheel-fl").pose.model_dump(mode="json")  # same pose: no change
    done = validate_command(broken, cmd(type="move_instance", id="wheel-fl", pose=pose))
    assert done.project == broken
    pose["position"]["x"] = 5.0
    done = validate_command(broken, cmd(type="move_instance", id="wheel-fl", pose=pose))
    assert [m.id for m in missing_definitions(done.project)] == ["wheel"]


# --- the catalog ------------------------------------------------------------------------------------------------


def catalog_project(density_scale=1.0):
    entry = load_material_catalog().entries[0].material.model_dump(mode="json")
    entry["density"]["value"] *= density_scale
    data = car_data()
    data["design"]["materials"] = [entry]
    data["design"]["instances"][0]["material"] = entry["id"]
    data["world"]["terrain_props"] = []
    return Project.model_validate(data), entry["id"]


def test_missing_definition_a_definition_equal_to_the_catalog_is_not_a_difference():
    project, _ = catalog_project()
    assert catalog_differences(project, material_catalog_hashes()) == ()
    assert open_report(project).differs_from_catalog == ()


def test_missing_definition_a_definition_that_differs_from_the_catalog_is_reported_and_the_projects_is_kept():
    project, ident = catalog_project(density_scale=1.01)
    opened_project = opened(project)  # a project file with a changed catalog material opens: the project's one is used
    report = open_report(opened_project)
    (diff,) = report.differs_from_catalog
    assert (diff.kind, diff.id) == ("material", ident)
    assert diff.project_hash == definition_hash(opened_project.design.materials[0])
    assert diff.catalog_hash == material_catalog_hashes()[("material", ident)] != diff.project_hash
    assert "카탈로그와 다름" in diff.message
    assert opened_project.design.materials[0].density.value == project.design.materials[0].density.value  # not swapped
    assert report.complete


def test_missing_definition_hash_in_the_file_is_the_hash_compared_with_the_catalog():
    project, ident = catalog_project(density_scale=1.01)
    file = project_file(project)
    stored = {(d.kind, d.id): d.hash for d in file.definitions}
    (diff,) = catalog_differences(project, material_catalog_hashes())
    assert stored[("material", ident)] == diff.project_hash


def test_missing_definition_parts_are_compared_by_a_catalog_given_by_the_caller(complete):
    chassis = next(p for p in complete.design.parts if p.id == "chassis")
    same = {("part", "chassis"): definition_hash(chassis)}
    other = {("part", "chassis"): "sha256:" + "0" * 64, ("part", "not-in-project"): "sha256:" + "1" * 64}
    assert catalog_differences(complete, same) == ()
    (diff,) = catalog_differences(complete, other)
    assert (diff.kind, diff.id) == ("part", "chassis")


# --- placement of a placeholder ---------------------------------------------------------------------------------
# A missing part has no geometry and is skipped; a missing material leaves the part, so its shape is checked as for
# any instance (placement reads the shape, never the material).

_SRC = {"ref": "unit-test fixture", "locator": "test_missing_definition.py"}
_ID = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _q(v):
    return {"value": v, "unit": "m", "badge": "declared", "source": _SRC}


def _cube():
    ax = lambda t: {"offset": 0.0, "terms": t}  # noqa: E731
    side = ax([{"param": "side", "factor": 1.0}])
    return {
        "id": "cube",
        "name": "Cube",
        "parameters": [{"name": "side", "unit": "m", "default": _q(0.2), "min": _q(0.05), "max": _q(1.0)}],
        "shape": {
            "badge": "declared",
            "source": _SRC,
            "components": [{"id": "body", "operation": "add", "primitive": {"kind": "box", "size_x": side, "size_y": side, "size_z": side}, "position": {"x": ax([]), "y": ax([]), "z": ax([])}}],
        },
    }


def _inst(id, z, part="cube", material=None):
    pose = {"position": {"x": 0.0, "y": 0.0, "z": z}, "orientation": _ID, "badge": "declared", "source": _SRC}
    return {"id": id, "part": part, "pose": pose, **({} if material is None else {"material": material})}


def _placed(*instances):
    return Project.model_validate({"design": {"parts": [_cube()], "instances": list(instances)}, "world": {"planet": "earth"}})


def test_missing_definition_a_placeholder_without_a_material_is_placed_by_its_shape():
    ok = _placed(_inst("base", 0.1, material="unobtainium"))
    assert [(m.kind, m.id) for m in missing_definitions(ok)] == [("material", "unobtainium")]
    assert check_placement(ok) == ()
    below = _placed(_inst("base", 0.05, material="unobtainium"))
    assert [r.code for r in check_placement(below)] == [ReasonCode.OVERLAP]  # under the ground: judged from the shape
    hover = _placed(_inst("base", 1.0, material="unobtainium"))
    assert [r.code for r in check_placement(hover)] == [ReasonCode.FLOATING]
    overlapping = _placed(_inst("a", 0.1, material="unobtainium"), _inst("b", 0.2))
    assert [r.code for r in check_placement(overlapping)] == [ReasonCode.OVERLAP]
    # the run is refused all the same
    with pytest.raises(ProjectIncomplete):
        require_complete(ok, BlockedOperation.RUN)


def test_missing_definition_a_placeholder_without_a_part_has_no_geometry_and_is_skipped():
    for z in (0.1, 0.05, 1.0):  # on the ground, under it, in the air: nothing is known, nothing is judged
        project = _placed(_inst("ghost", z, part="no-such-part"))
        assert [m.id for m in missing_definitions(project)] == ["no-such-part"]
        assert check_placement(project) == ()
    # and it does not hide or invent a finding for the instances that have a shape
    mixed = _placed(_inst("ghost", 0.1, part="no-such-part"), _inst("hover", 1.0))
    assert [r.code for r in check_placement(mixed)] == [ReasonCode.FLOATING]
    assert check_placement(mixed)[0].ids == (Ref(kind=RefKind.INSTANCE, id="hover"),)


def test_missing_definition_an_actuator_supply_on_a_placeholder_opens():
    """A supply source whose part is missing: its role is not known, so it is not checked (and not a crash)."""
    data = car_data()
    data["design"]["actuators"][0]["supply"] = "wheel-fl"
    data = without_part(data, "wheel")
    project = Project.model_validate(data)
    assert [m.id for m in missing_definitions(project)] == ["wheel"]
