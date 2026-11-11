"""B-03d: `Actuator.supply` (a motor draws from a battery instance, a thruster from a tank instance) and the battery and
tank part roles. Fixtures are test declarations (`사용자 선언`), not real part data."""

from __future__ import annotations

import copy

import pytest
from pydantic import TypeAdapter, ValidationError

from kinetra_core import Command, CommandRejected, DesignSpec, PartDef, Project, ReasonCode, Ref, RefKind, apply_command
from test_designspec import SRC, four_wheel_car, param, pose, q, snap
from test_commands import project_data


def cmd(**d):
    return TypeAdapter(Command).validate_python(d)


def spec(name, value, unit):
    return {"name": name, **q(value, unit)}


def battery_part():
    return {
        "id": "cell",
        "name": "Cell",
        "role": "battery",
        "specs": [spec("energy_capacity", 42120.0, "J"), spec("nominal_voltage", 3.6, "V")],
        "snap_points": [snap("plus", "terminal", accepts=["terminal"])],
    }


def tank_part():
    def prim(op, r, l):
        return {
            "id": "body" if op == "add" else "inside",
            "operation": op,
            "primitive": {"kind": "cylinder", "radius": {"offset": r, "terms": []}, "length": {"offset": l, "terms": []}},
            "position": {"x": {"offset": 0.0, "terms": []}, "y": {"offset": 0.0, "terms": []}, "z": {"offset": 0.0, "terms": []}},
        }

    return {
        "id": "tank",
        "name": "Tank",
        "role": "tank",
        "parameters": [param("propellant_density", "kg/m^3", 1000.0, 1.0, 2000.0)],
        "shape": {"badge": "declared", "source": SRC, "components": [prim("add", 0.06, 0.2), prim("subtract", 0.057, 0.194)]},
    }


def car_with_supplies():
    d = four_wheel_car()
    d["parts"] += [battery_part(), tank_part(), {"id": "motor-role", "name": "x"}]
    d["instances"] += [
        {"id": "cell-1", "part": "cell", "pose": pose(0.0, 0.0, 0.2)},
        {"id": "tank-1", "part": "tank", "material": "steel", "pose": pose(0.0, 0.0, 0.4)},
    ]
    d["actuators"][0]["supply"] = "cell-1"
    d["actuators"][1]["supply"] = "cell-1"  # two motors on one battery
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1", "supply": "tank-1"})
    return d


def reject(d, match):
    with pytest.raises(ValidationError, match=match):
        DesignSpec.model_validate(d)


def test_supply_motors_draw_from_a_battery_and_a_thruster_from_a_tank():
    spec_ = DesignSpec.model_validate(car_with_supplies())
    assert [a.supply for a in spec_.actuators] == ["cell-1", "cell-1", "tank-1"]
    assert DesignSpec.model_validate(four_wheel_car()).actuators[0].supply is None  # not metered: nothing runs out


def test_supply_rejects_an_unknown_instance():
    d = car_with_supplies()
    d["actuators"][0]["supply"] = "ghost"
    reject(d, "unknown supply instance 'ghost'")


def test_supply_of_a_motor_must_be_a_battery_and_of_a_thruster_a_tank():
    d = car_with_supplies()
    d["actuators"][0]["supply"] = "tank-1"
    reject(d, "a motor draws from a part with role 'battery', but supply 'tank-1' is part 'tank' with role 'tank'")
    d = car_with_supplies()
    d["actuators"][2]["supply"] = "cell-1"
    reject(d, "a thruster draws from a part with role 'tank', but supply 'cell-1' is part 'cell' with role 'battery'")


def test_supply_part_without_a_role_is_not_a_battery():
    d = car_with_supplies()
    d["actuators"][0]["supply"] = "wheel-fl"  # a wheel part with no role in this fixture
    reject(d, "supply 'wheel-fl' is part 'wheel' with no role")


def test_supply_error_names_the_things_that_are_wrong():
    from kinetra_core import RefError

    d = car_with_supplies()
    d["actuators"][0]["supply"] = "tank-1"
    with pytest.raises(ValidationError) as e:
        DesignSpec.model_validate(d)
    refs = e.value.errors()[0]["ctx"]["error"].refs
    assert {(r.kind, r.id) for r in refs} == {(RefKind.INSTANCE, "tank-1"), (RefKind.PART, "tank"), (RefKind.ACTUATOR, "drive-motor-l")}
    assert isinstance(e.value.errors()[0]["ctx"]["error"], RefError)


# ---- the roles -------------------------------------------------------------------------------------------------------------


def test_supply_battery_and_tank_parts_validate_with_what_their_role_needs():
    assert PartDef.model_validate(battery_part()).role.value == "battery"
    assert PartDef.model_validate(tank_part()).role.value == "tank"


def test_supply_tank_initial_fill_and_battery_initial_charge_are_fractions():
    t = tank_part()
    t["parameters"].append(param("initial_fill", "1", 0.5, 0.0, 1.0))
    PartDef.model_validate(t)
    t["parameters"][-1] = param("initial_fill", "1", 0.5, 0.0, 1.5)
    with pytest.raises(ValidationError, match="is a fraction"):
        PartDef.model_validate(t)
    t["parameters"][-1] = param("initial_fill", "m", 0.5, 0.0, 1.0)
    with pytest.raises(ValidationError, match="is a fraction"):
        PartDef.model_validate(t)
    b = battery_part()
    b["parameters"] = [param("initial_charge", "1", 1.0, -0.1, 1.0)]
    with pytest.raises(ValidationError, match="is a fraction"):
        PartDef.model_validate(b)


# ---- removing the supply takes the actuators that drew from it ---------------------------------------------------------------


@pytest.fixture
def supplied() -> Project:
    """The committed four-wheel-car project plus a battery and a tank, both motors on the battery, a thruster on the tank."""
    data = project_data()
    d = data["design"]
    d["parts"] += [battery_part(), tank_part()]
    d["instances"] += [
        {"id": "cell-1", "part": "cell", "pose": pose(0.0, 0.0, 0.2)},
        {"id": "tank-1", "part": "tank", "material": d["materials"][0]["id"], "pose": pose(0.0, 0.0, 0.4)},
    ]
    for a in d["actuators"]:
        a["supply"] = "cell-1"
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1", "supply": "tank-1"})
    d["schedule"]["entries"].append(
        {"type": "actuate", "id": "burn-1", "actuator": "thrust-1", "start": 0.0, "end": 1.0, "command": 1.0, "badge": "declared", "source": SRC}
    )
    return Project.model_validate(data)


def test_supply_removing_the_battery_removes_the_motors_that_drew_from_it_and_the_inverse_restores_them(supplied):
    done = apply_command(supplied, cmd(type="remove_instance", id="cell-1"))
    d = done.project.design
    assert [a.id for a in d.actuators] == ["thrust-1"]
    assert [e.actuator for e in d.schedule.entries] == ["thrust-1"]
    assert apply_command(done.project, done.inverse).project == supplied


def test_supply_removing_the_tank_removes_the_thruster_and_its_entries(supplied):
    done = apply_command(supplied, cmd(type="remove_instance", id="tank-1"))
    d = done.project.design
    assert [a.id for a in d.actuators] == ["drive-motor-l", "drive-motor-r"]
    assert d.schedule.entries and all(e.actuator != "thrust-1" for e in d.schedule.entries)
    assert apply_command(done.project, done.inverse).project == supplied


def test_supply_an_actuator_cannot_be_added_with_a_supply_of_the_wrong_kind(supplied):
    with pytest.raises(CommandRejected) as e:
        apply_command(supplied, cmd(type="add_actuator", actuator={"id": "bad", "kind": "thruster", "instance": "motor-l", "supply": "cell-1"}))
    assert e.value.reasons[0].code is ReasonCode.INVALID_PROJECT
    assert Ref(kind=RefKind.INSTANCE, id="cell-1") in e.value.reasons[0].ids


def test_supply_a_part_replacement_that_unmakes_a_battery_is_rejected(supplied):
    d = copy.deepcopy(battery_part())
    del d["role"]
    d["specs"] = []
    with pytest.raises(CommandRejected) as e:
        apply_command(supplied, cmd(type="replace_part_def", part=d))
    assert e.value.reasons[0].code is ReasonCode.INVALID_PROJECT


def test_supply_a_motor_or_thruster_on_a_complete_battery_or_tank_part_is_rejected():
    """The actuator rule of B-03b: a motor drives a `motor` part. A battery and a tank are complete parts here."""
    d = car_with_supplies()
    d["actuators"].append({"id": "m-on-cell", "kind": "motor", "instance": "cell-1", "joint": "drive-l"})
    reject(d, "a motor drives a part with role 'motor', but instance 'cell-1' is part 'cell' with role 'battery'")
    d = car_with_supplies()
    d["actuators"][2]["instance"] = "tank-1"
    reject(d, "a thruster drives a part with role 'thruster', but instance 'tank-1' is part 'tank' with role 'tank'")


def test_supply_is_part_of_the_project_hash_and_an_unset_supply_is_not_written(supplied):
    """C-03: `Actuator.supply` is in the canonical text when set (drawing from another battery is another design) and left
    out when None (its default is pinned in `test_hash_omitted_defaults_are_pinned`)."""
    from kinetra_core import project_hash
    from kinetra_core.canonical import canonical_json

    base = project_hash(supplied)
    d = supplied.model_dump(mode="json")
    assert '"supply":"cell-1"' in canonical_json(supplied)
    d["design"]["instances"].append({**next(i for i in d["design"]["instances"] if i["id"] == "cell-1"), "id": "cell-2"})
    d["design"]["actuators"][0]["supply"] = "cell-2"
    assert project_hash(Project.model_validate(d)) != base
    for a in d["design"]["actuators"]:
        a["supply"] = None
    assert '"supply"' not in canonical_json(Project.model_validate(d))
