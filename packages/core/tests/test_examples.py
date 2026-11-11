"""C-01 epic integration (#60): the three example projects and `packages/core/scripts/validate_examples.py`."""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

import kinetra_core
from kinetra_core import ActuatorKind, JointKind, Project, SetParameter, apply_command

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "core" / "scripts"))
import validate_examples as ve  # noqa: E402

EXAMPLES = ROOT / "schemas" / "examples"
CAR = "Project.four-wheel-car.json"
ROCKET = "Project.rocket-car-skeleton.json"
EMPTY = "Project.empty.json"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def project(name: str) -> Project:
    return Project.model_validate(load(name))


def numbers_with_badges(node, path=""):
    """Every `{value, badge}` / `{..., badge, source}` object in a JSON tree, so a test can inspect all numbers' badges."""
    if isinstance(node, dict):
        if "badge" in node:
            yield path, node
        for k, v in node.items():
            yield from numbers_with_badges(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from numbers_with_badges(v, f"{path}/{i}")


# --- the script ----------------------------------------------------------------------------------------------


def test_validate_examples_script_passes_on_the_committed_examples(capsys):
    assert ve.main([]) == 0
    out = capsys.readouterr().out
    for name in ve.REQUIRED:
        assert name in out


def test_all_three_required_examples_exist_and_are_projects():
    assert len(ve.REQUIRED) == 3
    for name in ve.REQUIRED:
        assert (EXAMPLES / name).is_file(), name
        project(name)


def write(tmp_path: Path, name: str, data) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_dangling_reference_is_caught_by_the_model_not_by_json_schema(tmp_path):
    """A dangling reference is invisible to JSON Schema and caught by the model: the script reports it."""
    data = load(CAR)
    data["design"]["joints"][0]["a"]["snap_point"] = "no-such-snap-point"
    path = write(tmp_path, CAR, data)
    problems = ve.validate_file(path)
    assert problems and all("JSON Schema" not in p for p in problems)
    assert any("model" in p and "no-such-snap-point" in p for p in problems)


def test_a_wrong_unit_fails_both_validators(tmp_path):
    data = load(CAR)
    data["design"]["materials"][0]["density"]["unit"] = "g/cm^3"
    problems = ve.validate_file(write(tmp_path, CAR, data))
    assert any("JSON Schema" in p for p in problems) and any("model" in p for p in problems)


def test_script_reports_a_planet_without_data(tmp_path):
    data = load(EMPTY)
    data["world"]["planet"] = "pluto"
    problems = ve.validate_file(write(tmp_path, EMPTY, data))
    assert any("planet data" in p and "pluto" in p for p in problems)


def test_script_rejects_a_name_that_is_not_a_model_and_bad_json(tmp_path):
    assert "not an exported kinetra_core model" in ve.validate_file(write(tmp_path, "Nope.x.json", {}))[0]
    bad = tmp_path / "Project.bad.json"
    bad.write_text("{", encoding="utf-8")
    assert "not JSON" in ve.validate_file(bad)[0]


def test_script_main_fails_on_a_broken_file_and_names_it(tmp_path, capsys):
    data = load(EMPTY)
    del data["world"]
    path = write(tmp_path, "Project.broken.json", data)
    assert ve.main([str(path)]) == 1
    assert "Project.broken.json" in capsys.readouterr().err


def test_required_examples_cannot_silently_disappear(monkeypatch, tmp_path):
    (tmp_path / EMPTY).write_text((EXAMPLES / EMPTY).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ve, "EXAMPLES", tmp_path)
    monkeypatch.setattr(ve, "ROOT", tmp_path.parent)
    assert ve.main([]) == 1


def test_a_rocket_car_without_a_scheduled_thruster_fails(tmp_path, monkeypatch):
    for name in ve.REQUIRED:
        data = load(name)
        if name == ROCKET:
            data["design"]["schedule"] = {"entries": []}
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ve, "EXAMPLES", tmp_path)
    monkeypatch.setattr(ve, "ROOT", tmp_path.parent)
    assert any("no thruster has a schedule entry" in p for p in ve.check_rocket_car_has_a_thruster(sorted(tmp_path.glob("*.json"))))


# --- the examples are what they say they are -----------------------------------------------------------------


def test_the_empty_project_is_empty():
    p = project(EMPTY)
    assert load(EMPTY) == {"world": {"planet": "earth"}}
    d = p.design
    assert not (d.materials or d.parts or d.instances or d.joints or d.actuators or d.schedule.entries)
    assert p.world.terrain_props == () and p.assumptions.assumptions == ()


def test_the_four_wheel_car_has_four_wheels_and_two_motors_on_hinges():
    d = project(CAR).design
    assert sum(1 for i in d.instances if i.part == "wheel") == 4
    assert [a.kind for a in d.actuators] == [ActuatorKind.MOTOR] * 2
    hinges = {j.id for j in d.joints if j.kind == JointKind.HINGE}
    assert {a.joint for a in d.actuators} <= hinges and len(hinges) == 4


def test_the_rocket_car_has_a_scheduled_thruster_and_no_thruster_joint():
    p = project(ROCKET)
    d = p.design
    (thruster,) = [a for a in d.actuators if a.kind == ActuatorKind.THRUSTER]
    assert thruster.joint is None  # C-01b: a thruster drives no joint
    assert {e.actuator for e in d.schedule.entries} == {thruster.id}
    assert all(0.0 <= e.command <= 1.0 for e in d.schedule.entries)  # thruster command is [0, 1]
    assert p.world.planet == "moon"  # a rocket needs no atmosphere or wheels' traction to make the point
    assert sum(1 for i in d.instances if i.part == "wheel") == 4


@pytest.mark.parametrize("name", [CAR, ROCKET])
def test_example_designs_are_assembled(name):
    """Joined snap points coincide in world space (the same check as `test_designspec_four_wheel_car_is_assembled`)."""
    from test_designspec import snap_of, world_snap_position  # same helpers, one definition

    spec = project(name).design
    for joint in spec.joints:
        pa, pb = world_snap_position(spec, joint.a), world_snap_position(spec, joint.b)
        assert pa == pytest.approx(pb, abs=1e-9), joint.id
        sa, sb = snap_of(spec, joint.a), snap_of(spec, joint.b)
        assert sb.kind in sa.accepts and sa.kind in sb.accepts, joint.id


@pytest.mark.parametrize("name", [CAR, ROCKET, EMPTY])
def test_examples_round_trip_through_json(name):
    p = project(name)
    assert Project.model_validate_json(p.model_dump_json()) == p


def test_a_command_applies_to_an_example_project_and_inverts():
    """The examples are usable documents for C-02a, not just valid files."""
    p = project(CAR)
    wheel = next(i for i in p.design.instances if i.part == "wheel")
    value = {"name": "diameter", "value": 0.12, "unit": "m", "badge": "declared", "source": load(CAR)["design"]["instances"][3]["pose"]["source"]}
    result = apply_command(p, SetParameter(type="set_parameter", instance=wheel.id, parameter=value))
    assert result.project != p
    assert apply_command(result.project, result.inverse).project == p


# --- honesty (V5): no number claims more than "declared" / "default" / "estimate" -----------------------------


@pytest.mark.parametrize("name", [CAR, ROCKET, EMPTY])
def test_example_numbers_make_no_real_performance_claim(name):
    """These are fixtures. `cite` would claim a document, `sim` a computed result; neither is true here."""
    for path, node in numbers_with_badges(load(name)):
        assert node["badge"] in {"declared", "default", "estimate"}, (name, path, node["badge"])
        if node["badge"] == "declared":
            assert node["source"]["declared_by"] == "kinetra-docs" and "illustrative" in node["source"]["ref"], (name, path)
        else:
            assert "illustrative" in node["source"]["ref"], (name, path)


def test_the_rocket_thrust_is_a_declared_fixture_not_a_performance_claim():
    rocket = next(p for p in project(ROCKET).design.parts if p.id == "rocket")
    (spec,) = rocket.specs
    assert spec.name == "rated_thrust" and spec.badge == "declared" and math.isfinite(spec.value)
    assert "not a measured part" in spec.source.ref


def test_examples_are_not_modified_by_loading(tmp_path):
    before = copy.deepcopy(load(CAR))
    project(CAR)
    assert load(CAR) == before


def test_every_example_file_names_an_exported_model():
    for path in EXAMPLES.glob("*.json"):
        assert hasattr(kinetra_core, ve.model_name(path)), path.name
