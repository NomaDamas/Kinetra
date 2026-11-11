"""B-03 epic integration (#100): a car with wheels, motors, a thruster, a battery, a tank and spring-dampers, and the
parts list with each drive part's key specs and where they come from.

The design is `schemas/examples/Project.drive-car.json` (written by `drive_car_sample.py` from the shipped library parts
plus the example's own chassis and axle stubs). The expected spec values are written down again here from the
datasheets the parts cite (or the method an estimate states), and the rows of the table are compared with the library
files read as plain JSON, not through the code that built the table.

    uv run pytest packages/engine -q -k drive_parts
"""

from __future__ import annotations

import json
import math

import pytest
from drive_car_sample import (
    EXAMPLE,
    FIXTURES,
    INSTANCES,
    JOINTS,
    KEY_SPECS,
    LIBRARY,
    MANIFEST,
    build_project,
    glb_name,
    instance_glb,
    manifest,
    rotate,
    spec_rows,
)
from gltf_validate import validate

from kinetra_core import (
    BADGE_LABEL_KO,
    Badge,
    CommandRejected,
    JointKind,
    PartDef,
    PartRole,
    Project,
    ReasonCode,
    check_placement,
    export_json,
    parse_command,
    validate_command,
)

LBF = 4.4482216152605  # N per lbf (exact by definition of the pound-force)
KGF_MM = 9.80665e-3  # N*m per kgf*mm


@pytest.fixture(scope="module")
def project() -> Project:
    return build_project()


@pytest.fixture(scope="module")
def rows(project):
    return {(r["part"], r["name"]): r for r in spec_rows(project)}


def _role_of(project, instance_id):
    inst = next(i for i in project.design.instances if i.id == instance_id)
    return next(p for p in project.design.parts if p.id == inst.part).role


def _raw(part_id: str) -> dict:
    return json.loads((LIBRARY / f"{part_id}.json").read_text(encoding="utf-8"))


# ---- the car is made of the drive parts and is a valid placement ---------------------------------------------------


def test_drive_parts_car_has_every_drive_part(project):
    roles = [_role_of(project, i.id) for i in project.design.instances]
    assert roles.count(PartRole.WHEEL) == 4
    assert roles.count(PartRole.MOTOR) == 2
    assert roles.count(PartRole.THRUSTER) == 1
    assert roles.count(PartRole.BATTERY) == 1
    assert roles.count(PartRole.TANK) == 1
    assert roles.count(PartRole.SPRING_DAMPER) == 2
    library = {p.stem for p in LIBRARY.glob("*.json")}
    own = {p.id for p in project.design.parts} - library
    assert own == {"drive-chassis", "drive-stub"}  # every drive part is the shipped library definition
    for p in project.design.parts:
        if p.id in library:
            assert p == PartDef.model_validate(_raw(p.id)), p.id


def test_drive_parts_car_is_a_valid_placement(project):
    # Joined snap points meet, no two bodies interpenetrate, nothing is below the ground and nothing floats.
    assert check_placement(project) == ()
    wheels = [i for i in project.design.instances if _role_of(project, i.id) is PartRole.WHEEL]
    assert {round(w.pose.position.z, 12) for w in wheels} == {0.05}  # the tires (diameter 0.1 m) stand on the ground


def test_drive_parts_every_wheel_turns_on_a_hinge_about_the_axle(project):
    design = project.design
    insts = {i.id: i for i in design.instances}
    parts = {p.id: p for p in design.parts}
    joints = {j.id: j for j in design.joints}
    # front wheels: hinge on the chassis axle; rear wheels: fixed on an axle stub that a motor turns on a hinge
    hinge_of = {"wheel-fl": "axle-fl", "wheel-fr": "axle-fr", "wheel-rl": "drive-rl", "wheel-rr": "drive-rr"}
    for wheel, jid in hinge_of.items():
        j = joints[jid]
        assert j.kind is JointKind.HINGE and j.axis is not None and j.axis.badge is Badge.DECLARED
        a = insts[j.a.instance]
        snap = next(s for s in parts[a.part].snap_points if s.id == j.a.snap_point)
        q_inst = (a.pose.orientation.x, a.pose.orientation.y, a.pose.orientation.z, a.pose.orientation.w)
        q_snap = (snap.orientation.x, snap.orientation.y, snap.orientation.z, snap.orientation.w)
        world = rotate(q_inst, rotate(q_snap, j.unit_axis))
        assert world == pytest.approx((0.0, 1.0, 0.0), abs=1e-12), (wheel, world)  # +y: a positive angle rolls forward (+x)
        if jid.startswith("drive"):
            stub = j.b.instance
            fixed = next(k for k in design.joints if k.a.instance == stub and k.b.instance == wheel)
            assert fixed.kind is JointKind.FIXED and fixed.b.snap_point == "hub"
        else:
            assert j.b.instance == wheel and j.b.snap_point == "hub"


def test_drive_parts_motors_draw_from_the_battery_and_the_thruster_from_the_tank(project):
    acts = {a.id: a for a in project.design.actuators}
    joints = {j.id: j for j in project.design.joints}
    for aid in ("drive-motor-rl", "drive-motor-rr"):
        a = acts[aid]
        assert a.kind.value == "motor" and _role_of(project, a.instance) is PartRole.MOTOR
        assert _role_of(project, a.supply) is PartRole.BATTERY
        assert a.instance == joints[a.joint].a.instance and joints[a.joint].kind is JointKind.HINGE
    t = acts["thrust"]
    assert t.kind.value == "thruster" and t.joint is None
    assert _role_of(project, t.instance) is PartRole.THRUSTER and _role_of(project, t.supply) is PartRole.TANK
    thruster = next(i for i in project.design.instances if i.id == t.instance)
    q = thruster.pose.orientation
    assert rotate((q.x, q.y, q.z, q.w), (0.0, 0.0, -1.0)) == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)  # thrust (-z) pushes +x


ROLLING = 8  # the first JOINTS: motors, axle stubs and the four wheels (the chassis alone would float)


def _commands(project: Project) -> list[dict]:
    """The example as the commands a client would send, in placement order: definitions; the rolling chassis (chassis,
    motors, stubs, wheels and their joints) as one batch, since the chassis alone touches nothing; then each other part
    together with the joint that holds it; then actuators and the schedule."""
    d = json.loads(project.model_dump_json())["design"]
    by_id = {i["id"]: i for i in d["instances"]}
    joints = {j["id"]: j for j in d["joints"]}

    def attach(jid: str) -> list[dict]:
        j = joints[jid]
        return [{"type": "add_instance", "instance": by_id[j["b"]["instance"]]}, {"type": "add_joint", "joint": j}]

    out = [{"type": "add_material_def", "material": m} for m in d["materials"]]
    out += [{"type": "add_part_def", "part": p} for p in d["parts"]]
    rolling = [{"type": "add_instance", "instance": by_id["chassis"]}]
    for jid, *_ in JOINTS[:ROLLING]:
        rolling += attach(jid)
    out.append({"type": "batch", "commands": rolling})
    out += [{"type": "batch", "commands": attach(jid)} for jid, *_ in JOINTS[ROLLING:]]
    out += [{"type": "add_actuator", "actuator": a} for a in d["actuators"]]
    out += [{"type": "add_control_entry", "entry": e} for e in d["schedule"]["entries"]]
    return out


def test_drive_parts_car_is_built_through_validate_command_one_step_at_a_time(project):
    assert {j[4] for j in JOINTS[:ROLLING]} == {"motor-rl", "motor-rr", "stub-rl", "stub-rr", "wheel-rl", "wheel-rr", "wheel-fl", "wheel-fr"}
    p = Project.model_validate({"world": {"planet": "earth"}})
    steps = _commands(project)
    for step in steps:
        p = validate_command(p, parse_command(step)).project  # every step passes the gate (raises otherwise)
    assert export_json(p) == export_json(project)
    assert len(steps) == 3 + 8 + 1 + (len(JOINTS) - ROLLING) + 3 + 3


def test_drive_parts_validator_refuses_a_wheel_off_its_axle_and_a_thruster_on_the_battery(project):
    wheel = next(i for i in project.design.instances if i.id == "wheel-fl")
    pose = json.loads(wheel.pose.model_dump_json())
    pose["position"]["y"] += 0.005
    with pytest.raises(CommandRejected) as e:
        validate_command(project, parse_command({"type": "move_instance", "id": "wheel-fl", "pose": pose}))
    assert e.value.reasons[0].code is ReasonCode.INVALID_SNAP
    act = {"id": "thrust-2", "kind": "thruster", "instance": "thruster", "supply": "battery"}
    with pytest.raises(CommandRejected):
        validate_command(project, parse_command({"type": "add_actuator", "actuator": act}))


# ---- the specs shown are the part definitions' ---------------------------------------------------------------------


def test_drive_parts_table_has_the_key_spec_of_every_drive_part():
    names = {(p, n) for p, _, n in KEY_SPECS}
    assert {
        ("wheel", "tread_friction_static"),
        ("wheel", "tread_friction_kinetic"),
        ("motor-37d-12v-50-1", "rated_voltage"),
        ("motor-37d-12v-50-1", "torque_speed"),
        ("thruster-vacco-48003040", "rated_thrust"),
        ("battery-pack-4s", "nominal_voltage"),
        ("battery-pack-4s", "energy_capacity"),
        ("spring-damper-lee-lc032b08", "stiffness"),
        ("spring-damper-lee-lc032b08", "damping"),
    } <= names


def test_drive_parts_spec_rows_are_the_library_files_values_badges_and_sources(project):
    """Each row against the library file read as plain JSON: name, value, unit, badge and source are the same."""
    for row in spec_rows(project):
        raw = _raw(row["part"])
        assert row["part_name"] == raw["name"]
        if row["from"] == "spec":
            want = next(s for s in raw["specs"] if s["name"] == row["name"])
        elif row["from"] == "param":
            want = next(p for p in raw["parameters"] if p["name"] == row["name"])["default"]
        elif row["from"] == "curve_start":
            curve = next(c for c in raw["curves"] if c["name"] == "torque_speed")["curve"]
            want = {"value": curve["points"][0]["y"], "unit": curve["y_unit"], "badge": curve["badge"], "source": curve["source"]}
            assert curve["points"][0]["x"] == 0.0  # the stall point: torque at zero speed
        else:
            continue  # the tank's capacity is computed (badge sim): checked by hand below
        assert (row["value"], row["unit"], row["badge"]) == (want["value"], want["unit"], want["badge"]), row["name"]
        assert row["badge_label"] == BADGE_LABEL_KO[Badge(want["badge"])]
        assert (row["source_ref"], row["source_locator"], row["source_url"]) == (
            want["source"]["ref"],
            want["source"].get("locator"),
            want["source"].get("url"),
        ), row["name"]
        if row["badge"] == "cite":
            assert row["source_locator"] or row["source_url"]  # a cited value says where in the source


def test_drive_parts_spec_values_match_the_datasheets_by_hand(rows):
    hand = {
        ("wheel", "tread_friction_static"): (1.0, "1", "cite"),  # OpenStax Table 5.1, rubber on dry concrete
        ("wheel", "tread_friction_kinetic"): (0.7, "1", "cite"),
        ("motor-37d-12v-50-1", "rated_voltage"): (12.0, "V", "cite"),  # Pololu 37D, 12 V
        ("motor-37d-12v-50-1", "stall_torque (torque_speed at 0 rad/s)"): (210 * KGF_MM, "N*m", "cite"),  # 210 kgf*mm
        ("thruster-vacco-48003040", "rated_thrust"): (2 * LBF, "N", "cite"),  # VACCO 48003040, 2 lbf
        ("battery-pack-4s", "nominal_voltage"): (4 * 3.6, "V", "estimate"),  # 4 cells in series x 3.6 V
        ("battery-pack-4s", "energy_capacity"): (4 * 3.25 * 3.6 * 3600, "J", "estimate"),  # 4 x 3250 mAh x 3.6 V
        # 1000 kg/m^3 x the inside cylinder (radius 0.035 - 0.003 m, length 0.1 - 0.006 m) of the example's tank
        ("tank", "propellant_capacity"): (1000 * math.pi * 0.032**2 * 0.094, "kg", "sim"),
        ("spring-damper-lee-lc032b08", "stiffness"): (5990.0, "N/m", "cite"),  # Lee Spring LC 032B 08, 5.99 N/mm
        ("spring-damper-lee-lc032b08", "damping"): (20.0, "N*s/m", "default"),  # Kinetra's starting value, not measured
    }
    assert set(rows) == set(hand)
    for key, (value, unit, badge) in hand.items():
        r = rows[key]
        assert r["value"] == pytest.approx(value, rel=1e-12), key
        assert (r["unit"], r["badge"]) == (unit, badge), key


def test_drive_parts_curve_stall_is_the_motor_spec_stall_torque(project, rows):
    motor = next(p for p in project.design.parts if p.id == "motor-37d-12v-50-1")
    stall = next(s for s in motor.specs if s.name == "stall_torque")
    assert rows[("motor-37d-12v-50-1", "stall_torque (torque_speed at 0 rad/s)")]["value"] == stall.value


def test_drive_parts_each_row_names_the_instances_that_use_the_part(project, rows):
    users = {}
    for iid, (pid, *_) in INSTANCES.items():
        users.setdefault(pid, []).append(iid)
    for (pid, _), r in rows.items():
        assert r["instances"] == users[pid]


# ---- the committed files are what the code writes today ----------------------------------------------------------------


def test_drive_parts_example_project_is_current(project):
    assert EXAMPLE.read_bytes() == export_json(project), "run: uv run python packages/engine/tests/drive_car_sample.py"


def test_drive_parts_manifest_is_current(project):
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert m == manifest(project), "run: uv run python packages/engine/tests/drive_car_sample.py"
    assert [i["id"] for i in m["instances"]] == list(INSTANCES)
    assert m["specs"] == spec_rows(project)


def test_drive_parts_glb_per_instance_is_current_and_valid(project):
    for inst in project.design.instances:
        data = (FIXTURES / glb_name(inst.id)).read_bytes()
        assert data == instance_glb(project.design, inst.id), inst.id
        assert validate(data).doc["asset"]["version"] == "2.0"
    assert sorted(p.name for p in FIXTURES.glob("*.glb")) == sorted(glb_name(i.id) for i in project.design.instances)
