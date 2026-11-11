"""C-01b: DesignSpec. The four-wheel car is a fixture declared by the test (`사용자 선언`): its numbers are not
real part data (catalog parts come with B-02a, B-03a, B-03b, each with a source)."""

from __future__ import annotations

import copy
import itertools

import pytest
from pydantic import ValidationError

from kinetra_core import Badge, DesignSpec, JointKind, Unit

SRC = {"ref": "unit-test fixture", "locator": "test_designspec.py"}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def q(value, unit, badge="declared", source=None):
    return {"value": value, "unit": unit, "badge": badge, "source": source or SRC}


def axis(offset=0.0, terms=()):
    return {"offset": offset, "terms": list(terms)}


def snap(id, kind, x=0.0, y=0.0, z=0.0, accepts=()):
    return {
        "id": id,
        "kind": kind,
        "accepts": list(accepts),
        "position": {"x": axis(x), "y": axis(y), "z": axis(z)},
        "orientation": IDENTITY,
        "badge": "declared",
        "source": SRC,
    }


def pose(x=0.0, y=0.0, z=0.0, orientation=IDENTITY):
    return {"position": {"x": x, "y": y, "z": z}, "orientation": orientation, "badge": "declared", "source": SRC}


TURN_180_Z = {"x": 0.0, "y": 0.0, "z": 1.0, "w": 0.0}


def material(id="steel"):
    return {
        "id": id,
        "name": id,
        "density": q(1000.0, "kg/m^3"),
        "yield_strength": q(1.0e7, "Pa"),
        "elastic_modulus": q(1.0e9, "Pa"),
        "friction": q(0.5, "1", "default", {"ref": "test default"}),
    }


def param(name, unit, default, lo, hi):
    return {"name": name, "unit": unit, "default": q(default, unit), "min": q(lo, unit), "max": q(hi, unit)}


def four_wheel_car():
    """An assembled car: chassis, two motors fixed to its rear, four wheels, all hubs at z = 0.05 m (the default
    wheel radius). Rear wheels turn on the motor shafts (the right motor is turned 180 deg about Z so its shaft
    points to -y), front wheels on passive axles. The motors drive the two rear hinges for 5 s. Every joined
    pair of snap points coincides in world space (`test_designspec_four_wheel_car_is_assembled`)."""
    parts = [
        {
            "id": "chassis",
            "name": "Chassis",
            "parameters": [param("length", "m", 0.4, 0.2, 0.8)],
            "snap_points": [
                snap("motor-l", "motor_mount", -0.1, 0.1, accepts=["motor_mount"]),
                snap("motor-r", "motor_mount", -0.1, -0.1, accepts=["motor_mount"]),
                snap("axle-fl", "axle_mount", 0.1, 0.1, accepts=["shaft"]),
                snap("axle-fr", "axle_mount", 0.1, -0.1, accepts=["shaft"]),
            ],
        },
        {
            "id": "motor",
            "name": "Motor",
            "snap_points": [snap("mount", "motor_mount", accepts=["motor_mount"]), snap("shaft", "shaft", y=0.03, accepts=["shaft"])],
        },
        {
            "id": "wheel",
            "name": "Wheel",
            "parameters": [param("diameter", "m", 0.1, 0.05, 0.2)],
            "snap_points": [snap("hub", "shaft", accepts=["shaft", "axle_mount"])],
        },
    ]
    instances = [
        {"id": "chassis-1", "part": "chassis", "material": "steel", "pose": pose(z=0.05)},
        {"id": "motor-l", "part": "motor", "pose": pose(-0.1, 0.1, 0.05)},
        {"id": "motor-r", "part": "motor", "pose": pose(-0.1, -0.1, 0.05, TURN_180_Z)},
        {"id": "wheel-rl", "part": "wheel", "parameters": [{"name": "diameter", **q(0.1, "m")}], "pose": pose(-0.1, 0.13, 0.05)},
        {"id": "wheel-rr", "part": "wheel", "pose": pose(-0.1, -0.13, 0.05)},
        {"id": "wheel-fl", "part": "wheel", "pose": pose(0.1, 0.1, 0.05)},
        {"id": "wheel-fr", "part": "wheel", "pose": pose(0.1, -0.1, 0.05)},
    ]
    joints = [
        {"id": "weld-ml", "kind": "fixed", "a": {"instance": "chassis-1", "snap_point": "motor-l"}, "b": {"instance": "motor-l", "snap_point": "mount"}},
        {"id": "weld-mr", "kind": "fixed", "a": {"instance": "chassis-1", "snap_point": "motor-r"}, "b": {"instance": "motor-r", "snap_point": "mount"}},
        {"id": "drive-l", "kind": "hinge", "a": {"instance": "motor-l", "snap_point": "shaft"}, "b": {"instance": "wheel-rl", "snap_point": "hub"}},
        {"id": "drive-r", "kind": "hinge", "a": {"instance": "motor-r", "snap_point": "shaft"}, "b": {"instance": "wheel-rr", "snap_point": "hub"}},
        {"id": "axle-fl", "kind": "hinge", "a": {"instance": "chassis-1", "snap_point": "axle-fl"}, "b": {"instance": "wheel-fl", "snap_point": "hub"}},
        {"id": "axle-fr", "kind": "hinge", "a": {"instance": "chassis-1", "snap_point": "axle-fr"}, "b": {"instance": "wheel-fr", "snap_point": "hub"}},
    ]
    actuators = [
        {"id": "drive-motor-l", "kind": "motor", "instance": "motor-l", "joint": "drive-l"},
        {"id": "drive-motor-r", "kind": "motor", "instance": "motor-r", "joint": "drive-r"},
    ]
    entries = [
        {"type": "actuate", "id": f"run-{n}", "actuator": a, "start": 0.0, "end": 5.0, "command": 1.0, "badge": "declared", "source": SRC}
        for n, a in enumerate(("drive-motor-l", "drive-motor-r"))
    ]
    return {
        "materials": [material()],
        "parts": parts,
        "instances": instances,
        "joints": joints,
        "actuators": actuators,
        "schedule": {"entries": entries},
    }


def reject(d, match):
    with pytest.raises(ValidationError, match=match):
        DesignSpec.model_validate(d)


# --- the four-wheel car -----------------------------------------------------------------------------------


def test_designspec_four_wheel_car_validates():
    spec = DesignSpec.model_validate(four_wheel_car())
    assert [i.id for i in spec.instances] == ["chassis-1", "motor-l", "motor-r", "wheel-rl", "wheel-rr", "wheel-fl", "wheel-fr"]
    assert sum(1 for i in spec.instances if i.part == "wheel") == 4
    assert [j.kind for j in spec.joints].count(JointKind.HINGE) == 4
    assert spec.instances[0].pose.badge is Badge.DECLARED
    assert spec.instances[3].parameters[0].unit is Unit.M


def rotate(q, v):
    """Rotate vector v by unit quaternion q = (x, y, z, w): v + 2w(u x v) + 2 u x (u x v), u = (x, y, z)."""
    ux, uy, uz, w = q.x, q.y, q.z, q.w
    vx, vy, vz = v
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    dx, dy, dz = uy * cz - uz * cy, uz * cx - ux * cz, ux * cy - uy * cx
    return (vx + 2 * (w * cx + dx), vy + 2 * (w * cy + dy), vz + 2 * (w * cz + dz))


def world_snap_position(spec, ref):
    inst = next(i for i in spec.instances if i.id == ref.instance)
    part = next(p for p in spec.parts if p.id == inst.part)
    snap_pt = next(s for s in part.snap_points if s.id == ref.snap_point)
    values = {p.name: p.default.value for p in part.parameters} | {p.name: p.value for p in inst.parameters}

    def axis_value(a):
        return a.offset + sum(t.factor * values[t.param] for t in a.terms)

    local = (axis_value(snap_pt.position.x), axis_value(snap_pt.position.y), axis_value(snap_pt.position.z))
    r = rotate(inst.pose.orientation, local)
    p = inst.pose.position
    return (p.x + r[0], p.y + r[1], p.z + r[2])


def snap_of(spec, ref):
    inst = next(i for i in spec.instances if i.id == ref.instance)
    part = next(p for p in spec.parts if p.id == inst.part)
    return next(s for s in part.snap_points if s.id == ref.snap_point)


def test_designspec_four_wheel_car_is_assembled():
    """The fixture is a real car, not a bag of parts: joined snap points coincide in world space and accept each
    other, wheels sit on the ground plane z = 0 (hub z = radius), and the stored pose is what makes it so."""
    spec = DesignSpec.model_validate(four_wheel_car())
    assert len(spec.joints) == 6
    for joint in spec.joints:
        pa, pb = world_snap_position(spec, joint.a), world_snap_position(spec, joint.b)
        assert pa == pytest.approx(pb, abs=1e-9), joint.id
        sa, sb = snap_of(spec, joint.a), snap_of(spec, joint.b)
        assert sb.kind in sa.accepts and sa.kind in sb.accepts, joint.id  # B-04b will enforce this rule
    for inst in spec.instances:
        assert inst.pose.position.z == pytest.approx(0.05, abs=1e-9), inst.id
    right_shaft = world_snap_position(spec, next(j for j in spec.joints if j.id == "drive-r").a)
    assert right_shaft[1] == pytest.approx(-0.13, abs=1e-9)  # the 180 deg turn points the right motor outward


def test_designspec_round_trips_through_json_and_hashes():
    spec = DesignSpec.model_validate(four_wheel_car())
    again = DesignSpec.model_validate_json(spec.model_dump_json())
    assert again == spec
    assert hash(again) == hash(spec)


def test_designspec_empty_is_valid():
    assert DesignSpec.model_validate({}) == DesignSpec()


def test_designspec_json_schema_is_produced():
    schema = DesignSpec.model_json_schema()
    assert {"instances", "joints", "actuators", "schedule"} <= set(schema["properties"])
    defs = schema["$defs"]
    assert defs["BreakThreshold"]["properties"]["unit"]["const"] == "N"
    assert defs["ActuateEntry"]["properties"]["type"]["const"] == "actuate"


# --- references to snap points and other ids -------------------------------------------------------------


@pytest.mark.parametrize("side", ["a", "b"])
def test_designspec_rejects_missing_snap_point(side):
    d = four_wheel_car()
    d["joints"][2][side]["snap_point"] = "no-such-point"
    reject(d, rf"joints\[2\] \('drive-l'\)\.{side}.*no snap point 'no-such-point'")


def test_designspec_rejects_snap_point_of_another_part():
    d = four_wheel_car()
    d["joints"][2]["b"]["snap_point"] = "mount"  # a motor's snap point, but wheel-rl is a wheel
    reject(d, "part 'wheel' of instance 'wheel-rl' has no snap point 'mount'")


def test_designspec_rejects_unknown_instance_in_joint():
    d = four_wheel_car()
    d["joints"][0]["b"]["instance"] = "ghost"
    reject(d, "unknown instance 'ghost'")


def test_designspec_rejects_unknown_part():
    d = four_wheel_car()
    d["instances"][1]["part"] = "no-such-part"
    reject(d, "unknown part 'no-such-part'")


def test_designspec_rejects_unknown_material():
    d = four_wheel_car()
    d["instances"][0]["material"] = "unobtainium"
    reject(d, "unknown material 'unobtainium'")


def test_designspec_rejects_snap_point_used_by_two_joints():
    d = four_wheel_car()
    d["joints"][3]["a"] = copy.deepcopy(d["joints"][2]["a"])
    reject(d, "already used by joint 'drive-l'")


def test_designspec_rejects_joint_to_itself():
    d = four_wheel_car()
    d["joints"][0]["b"] = {"instance": "chassis-1", "snap_point": "axle-fl"}
    reject(d, "both ends are on instance 'chassis-1'")


@pytest.mark.parametrize("collection", ["materials", "parts", "instances", "joints", "actuators"])
def test_designspec_rejects_duplicate_ids(collection):
    d = four_wheel_car()
    d[collection].append(copy.deepcopy(d[collection][0]))
    reject(d, f"duplicate {collection[:-1]} id")


# --- instance parameters ---------------------------------------------------------------------------------


def test_designspec_rejects_unknown_parameter():
    d = four_wheel_car()
    d["instances"][3]["parameters"] = [{"name": "width", **q(0.05, "m")}]
    reject(d, "has no parameter 'width'")


def test_designspec_rejects_parameter_outside_range():
    d = four_wheel_car()
    d["instances"][3]["parameters"] = [{"name": "diameter", **q(0.5, "m")}]
    reject(d, r"outside the part's range \[0.05, 0.2\]")


def test_designspec_rejects_parameter_in_wrong_unit():
    d = four_wheel_car()
    d["instances"][3]["parameters"] = [{"name": "diameter", **q(0.1, "kg")}]
    reject(d, "parameter 'diameter' is in 'm', got 'kg'")


def test_designspec_rejects_parameter_set_twice():
    d = four_wheel_car()
    d["instances"][3]["parameters"] = [{"name": "diameter", **q(0.1, "m")}, {"name": "diameter", **q(0.11, "m")}]
    reject(d, "set more than once")


def test_designspec_rejects_parameter_without_source():
    d = four_wheel_car()
    p = {"name": "diameter", **q(0.1, "m")}
    del p["source"]
    d["instances"][3]["parameters"] = [p]
    reject(d, "source")


# --- pose ------------------------------------------------------------------------------------------------


def test_designspec_rejects_pose_without_badge_or_source():
    for field in ("badge", "source"):
        d = four_wheel_car()
        del d["instances"][0]["pose"][field]
        reject(d, field)


def test_designspec_rejects_non_unit_quaternion():
    d = four_wheel_car()
    d["instances"][0]["pose"]["orientation"] = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 2.0}
    reject(d, "unit norm")


@pytest.mark.parametrize("bad", ["0.1", True, float("nan")])
def test_designspec_rejects_non_number_position(bad):
    d = four_wheel_car()
    d["instances"][0]["pose"]["position"]["x"] = bad
    reject(d, "position")


# --- joints: limits and break threshold ------------------------------------------------------------------


def hinge_limits(lo=-1.0, hi=1.0, unit="rad"):
    return {"lower": q(lo, unit), "upper": q(hi, unit)}


def test_designspec_accepts_joint_limits_and_break_threshold():
    d = four_wheel_car()
    d["joints"][4]["limits"] = hinge_limits()
    d["joints"][4]["break_threshold"] = q(500.0, "N", "estimate", {"ref": "test estimate"})
    spec = DesignSpec.model_validate(d)
    j = next(j for j in spec.joints if j.id == "axle-fl")
    assert j.limits.upper.value == 1.0
    assert j.break_threshold.unit is Unit.N
    assert j.break_threshold.badge is Badge.ESTIMATE


def test_designspec_slider_limits_are_in_metres():
    d = four_wheel_car()
    d["joints"][4]["kind"] = "slider"
    d["joints"][4]["limits"] = hinge_limits(0.0, 0.1, "m")
    DesignSpec.model_validate(d)
    d["joints"][4]["limits"] = hinge_limits(0.0, 0.1, "rad")
    reject(d, "limits of a slider joint are in 'm'")


def test_designspec_hinge_limits_are_in_radians():
    d = four_wheel_car()
    d["joints"][4]["limits"] = hinge_limits(-0.1, 0.1, "m")
    reject(d, "limits of a hinge joint are in 'rad'")


def test_designspec_fixed_joint_has_no_limits():
    d = four_wheel_car()
    d["joints"][0]["limits"] = hinge_limits()
    reject(d, "a fixed joint has no limits")


@pytest.mark.parametrize("lo,hi", [(1.0, 1.0), (1.0, -1.0)])
def test_designspec_rejects_limits_out_of_order(lo, hi):
    d = four_wheel_car()
    d["joints"][4]["limits"] = hinge_limits(lo, hi)
    reject(d, "lower < upper")


def test_designspec_rejects_limits_with_mixed_units():
    d = four_wheel_car()
    d["joints"][4]["limits"] = {"lower": q(-1.0, "rad"), "upper": q(1.0, "m")}
    reject(d, "share a unit")


@pytest.mark.parametrize("value,unit", [(0.0, "N"), (-5.0, "N"), (500.0, "N*m"), (500.0, "m")])
def test_designspec_rejects_bad_break_threshold(value, unit):
    d = four_wheel_car()
    d["joints"][4]["break_threshold"] = q(value, unit)
    reject(d, "break_threshold")


def test_designspec_rejects_break_threshold_without_source():
    d = four_wheel_car()
    d["joints"][4]["break_threshold"] = q(500.0, "N")
    del d["joints"][4]["break_threshold"]["source"]
    reject(d, "source")


def test_designspec_rejects_unknown_joint_kind():
    d = four_wheel_car()
    d["joints"][4]["kind"] = "ball"
    reject(d, "kind")


# --- actuators -------------------------------------------------------------------------------------------


def test_designspec_motor_needs_a_joint():
    d = four_wheel_car()
    del d["actuators"][0]["joint"]
    reject(d, "a motor needs the joint it drives")


def test_designspec_thruster_drives_no_joint():
    d = four_wheel_car()
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1", "joint": "drive-l"})
    reject(d, "a thruster drives no joint")


def test_designspec_rejects_actuator_on_unknown_instance_or_joint():
    d = four_wheel_car()
    d["actuators"][0]["instance"] = "ghost"
    reject(d, "unknown instance 'ghost'")
    d = four_wheel_car()
    d["actuators"][0]["joint"] = "ghost"
    reject(d, "unknown joint 'ghost'")


def test_designspec_rejects_actuator_far_from_its_joint():
    d = four_wheel_car()
    d["actuators"][0]["instance"] = "wheel-fl"
    reject(d, "is not at either end of joint 'drive-l'")


def test_designspec_rejects_second_actuator_on_the_same_drive():
    d = four_wheel_car()
    d["actuators"].append({"id": "drive-motor-l2", "kind": "motor", "instance": "motor-l", "joint": "drive-l"})
    reject(d, "same motor on instance 'motor-l' and joint 'drive-l' as actuator 'drive-motor-l'")
    d = four_wheel_car()
    d["actuators"] += [
        {"id": "thrust-1", "kind": "thruster", "instance": "chassis-1"},
        {"id": "thrust-2", "kind": "thruster", "instance": "chassis-1"},
    ]
    reject(d, "same thruster on instance 'chassis-1' as actuator 'thrust-1'")


def test_designspec_two_thrusters_on_different_instances_are_fine():
    d = four_wheel_car()
    d["actuators"] += [
        {"id": "thrust-1", "kind": "thruster", "instance": "chassis-1"},
        {"id": "thrust-2", "kind": "thruster", "instance": "motor-l"},
    ]
    DesignSpec.model_validate(d)


def test_designspec_rejects_motor_on_fixed_joint():
    d = four_wheel_car()
    d["actuators"][0]["joint"] = "weld-ml"
    reject(d, "joint 'weld-ml' is fixed")


# --- control schedule ------------------------------------------------------------------------------------


_entry_ids = itertools.count(1)


def entry(actuator="drive-motor-l", start=0.0, end=1.0, command=0.5, id=None):
    return {"type": "actuate", "id": id or f"e-{next(_entry_ids)}", "actuator": actuator, "start": start, "end": end, "command": command, "badge": "declared", "source": SRC}


def test_designspec_schedule_accepts_back_to_back_and_thruster():
    d = four_wheel_car()
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1"})
    d["schedule"]["entries"] = [
        entry(start=5.0, end=6.0, command=-1.0),
        entry(start=0.0, end=5.0),
        entry("thrust-1", 1.0, 2.0, 1.0),
        entry("thrust-1", 0.0, 1.0, 0.0),
    ]
    spec = DesignSpec.model_validate(d)
    assert len(spec.schedule.entries) == 4


def test_designspec_rejects_schedule_entry_for_unknown_actuator():
    d = four_wheel_car()
    d["schedule"]["entries"] = [entry("ghost")]
    reject(d, "unknown actuator 'ghost'")


@pytest.mark.parametrize("start,end", [(1.0, 1.0), (2.0, 1.0), (-0.1, 1.0)])
def test_designspec_rejects_bad_interval(start, end):
    d = four_wheel_car()
    d["schedule"]["entries"] = [entry(start=start, end=end)]
    reject(d, "start|end")


@pytest.mark.parametrize("command", [1.5, -1.01, float("inf")])
def test_designspec_rejects_command_outside_unit_range(command):
    d = four_wheel_car()
    d["schedule"]["entries"] = [entry(command=command)]
    reject(d, "command")


def test_designspec_rejects_negative_thruster_command():
    d = four_wheel_car()
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1"})
    d["schedule"]["entries"] = [entry("thrust-1", command=-0.5)]
    reject(d, "takes a command in \\[0, 1\\]")


def test_designspec_rejects_overlapping_entries_on_one_actuator():
    d = four_wheel_car()
    d["schedule"]["entries"] = [entry(start=0.0, end=2.0), entry(start=1.0, end=3.0, command=-0.5)]
    reject(d, "overlapping entries")


def test_designspec_allows_overlap_on_different_actuators():
    d = four_wheel_car()
    d["schedule"]["entries"] = [entry("drive-motor-l", 0.0, 2.0), entry("drive-motor-r", 1.0, 3.0)]
    DesignSpec.model_validate(d)


def test_designspec_rejects_schedule_entry_without_badge_or_source():
    for field in ("badge", "source"):
        d = four_wheel_car()
        e = entry()
        del e[field]
        d["schedule"]["entries"] = [e]
        reject(d, field)


def test_designspec_rejects_duplicate_and_missing_entry_ids():
    d = four_wheel_car()
    d["schedule"]["entries"] = [entry(id="same"), entry("drive-motor-r", id="same")]
    reject(d, "duplicate schedule entry id: \\['same'\\]")
    e = entry()
    del e["id"]
    d["schedule"]["entries"] = [e]
    reject(d, "id")
    d["schedule"]["entries"] = [entry(id="Not An Id")]
    reject(d, "id")


def test_designspec_rejects_unknown_entry_type():
    d = four_wheel_car()
    e = entry()
    e["type"] = "separate"
    d["schedule"]["entries"] = [e]
    reject(d, "type")


def test_designspec_rejects_unknown_fields():
    d = four_wheel_car()
    d["joints"][0]["spring"] = 1.0
    reject(d, "spring")


# --- part role and actuator kind (B-03b) --------------------------------------------------------------------------
# These exercise the DesignSpec check only: every PartDef below is valid on its own (a motor part has its curve and
# rated voltage; the other roles have no requirements of their own here), so a rejection is the role-actuator rule.


def part(d, id):
    return next(p for p in d["parts"] if p["id"] == id)


def make_motor_part(d, id="motor"):
    p = part(d, id)
    p["role"] = "motor"
    p["specs"] = [{"name": "rated_voltage", **q(12.0, "V")}]
    p["curves"] = [
        {
            "name": "torque_speed",
            "curve": {
                "badge": "declared",
                "source": SRC,
                "x_unit": "rad/s",
                "y_unit": "N*m",
                "points": [{"x": 0.0, "y": 2.0}, {"x": 20.0, "y": 0.0}],
            },
        }
    ]


def test_designspec_motor_actuator_on_a_motor_part_is_accepted():
    d = four_wheel_car()
    make_motor_part(d)
    assert DesignSpec.model_validate(d).parts  # the definition alone is valid; both motor actuators sit on it


def make_spring_damper_part(d, id="motor"):
    p = part(d, id)
    p["role"] = "spring_damper"
    p["parameters"] = [
        *p.get("parameters", []),
        {"name": "stiffness", "unit": "N/m", "default": q(5000.0, "N/m"), "min": q(100.0, "N/m"), "max": q(1e5, "N/m")},
        {"name": "damping", "unit": "N*s/m", "default": q(20.0, "N*s/m"), "min": q(0.0, "N*s/m"), "max": q(500.0, "N*s/m")},
    ]


@pytest.mark.parametrize("role", ["wheel", "battery", "tank", "spring_damper", "thruster"])
def test_designspec_motor_actuator_on_a_part_with_another_role_is_rejected(role):
    d = four_wheel_car()
    if role == "spring_damper":
        make_spring_damper_part(d)  # a spring-damper part must be valid on its own for the role-actuator rule to be what rejects
    else:
        part(d, "motor")["role"] = role
    reject(d, f"a motor drives a part with role 'motor', but instance 'motor-l' is part 'motor' with role '{role}'")


def test_designspec_thruster_actuator_on_a_valid_motor_part_is_rejected():
    d = four_wheel_car()
    make_motor_part(d, "chassis")
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1"})
    reject(d, "a thruster drives a part with role 'thruster', but instance 'chassis-1' is part 'chassis' with role 'motor'")


def test_designspec_part_without_role_takes_any_actuator_kind():
    d = four_wheel_car()
    assert all("role" not in p for p in d["parts"])
    d["actuators"].append({"id": "thrust-1", "kind": "thruster", "instance": "chassis-1"})
    DesignSpec.model_validate(d)


def test_designspec_part_role_must_be_a_known_role():
    d = four_wheel_car()
    part(d, "motor")["role"] = "engine"
    reject(d, "role")
