"""B-03 epic integration: a car with the drive parts, a `Project` built from the shipped library parts (wheel, motor,
thruster, battery pack, tank, spring-damper) on a plate chassis.

    uv run python packages/engine/tests/drive_car_sample.py     # rewrites the example, the glb per instance and the manifest

Writes (and `test_drive_parts.py` checks they are current):

- `schemas/examples/Project.drive-car.json`: the project.
- `packages/engine/tests/fixtures/drive-car/<instance>.glb`: the glb of each instance (its part, material and parameters).
- `packages/engine/tests/fixtures/drive-car/manifest.json`: per instance the part, its name and role, material and pose;
  the parts list; and the key specs of the drive parts as the part definitions state them (name, value, unit, badge,
  source). `tools/gltf-check` (`capture:drive-car`) draws the car and prints that table beside it.

Every instance is placed by solving the joints from the chassis outwards (the world position of the parent's snap point
minus the child's snap point turned by the child's orientation), so no coordinate below is typed in twice.

Two parts are this example's own, not library parts (both `사용자 선언`): the chassis (`drive-chassis`: a flat aluminium
deck with the snap points a car needs, which the library plate does not have: motor mounts, axle mounts, seats; and two
hangers that hold the rear motors under the deck) and the axle stub (`drive-stub`: a short aluminium rod between a
motor shaft and a wheel hub). The stub is there because the library wheel's hub is a solid cylinder and the motor's
`shaft` snap is in the middle of its shaft: a wheel hung directly on the shaft would interpenetrate it, and
`check_placement` (rightly) calls that an overlap. Dimensions are this example's choices, not a real vehicle's.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from kinetra_core import BADGE_LABEL_KO, Badge, DesignSpec, PartDef, Project, export_json, load_material_catalog
from kinetra_engine.parts import evaluate, part_glb, tank_supply

ROOT = Path(__file__).resolve().parents[3]
LIBRARY = ROOT / "packages" / "engine" / "src" / "kinetra_engine" / "parts" / "library"
EXAMPLE = ROOT / "schemas" / "examples" / "Project.drive-car.json"
FIXTURES = Path(__file__).parent / "fixtures" / "drive-car"
MANIFEST = FIXTURES / "manifest.json"

DECLARED_BY = "kinetra-b03-drive-car"
DECLARED_AT = "2026-11-12T00:00:00Z"
S = math.sqrt(0.5)
IDENTITY = (0.0, 0.0, 0.0, 1.0)
SHAFT_OUT_LEFT = (-S, 0.0, 0.0, S)  # about x by -90 deg: part +z (motor shaft) -> world +y
SHAFT_OUT_RIGHT = (S, 0.0, 0.0, S)  # about x by +90 deg: part +z -> world -y
TURN_Z = (0.0, 0.0, 1.0, 0.0)  # 180 deg about z: a right-hand wheel's outer hub boss faces -y
EXHAUST_AFT = (0.0, -S, 0.0, S)  # about y by -90 deg: thruster +z (exhaust) -> world -x, thrust pushes +x
ALONG_X = (0.0, S, 0.0, S)  # about y by +90 deg: spring axis (+z) -> world +x

# Chassis geometry (the chassis frame is the deck centre; the deck is level, identity orientation).
DECK_L, DECK_W, DECK_T = 0.36, 0.24, 0.008
CHASSIS_Z = 0.09  # deck centre height: the rear motors (axis 0.05 m, gearbox radius 0.0184 m) hang under the deck
WHEEL_R = 0.05  # library wheel default diameter 0.1 m: the axle is 0.05 m above flat ground
AXLE_X = (0.12, -0.12)  # front, rear axle x
MOTOR_Y = 0.08  # |y| of the motor face plates (motor origin, its `mount` snap)
WHEEL_Y = 0.145  # |y| of the wheel centres: the tire (width 0.04 m) starts at 0.125, outside the deck edge 0.12
GEARBOX_R = 0.0184  # library motor gearbox radius
SHAFT_SNAP, SHAFT_TIP = 0.014, 0.022  # library motor: `shaft` snap and shaft end along the motor's +z
HUB_REACH = 0.0344  # library wheel (width 0.04 m): the inner hub boss ends this far inboard of the wheel centre
STUB_R = 0.004
STUB_START = SHAFT_TIP - SHAFT_SNAP  # the stub body starts at the shaft tip (end faces touch)
STUB_LEN = (WHEEL_Y - HUB_REACH) - (MOTOR_Y + SHAFT_TIP)  # and ends at the wheel's inner hub boss (end faces touch)
STUB_OUT = WHEEL_Y - MOTOR_Y - SHAFT_SNAP  # wheel centre along the stub axis, from its `in` snap
THRUSTER_BODY_R = 0.014  # library thruster valve body radius: its axis sits this high above the deck top
SPRING_Y = 0.06


def _source(ref: str) -> dict:
    return {"ref": ref, "declared_by": DECLARED_BY, "declared_at": DECLARED_AT}


def _declared(ref: str) -> dict:
    return {"badge": "declared", "source": _source(f"B-03 drive-car example: {ref}")}


def _param(name: str, value: float, unit: str = "m") -> dict:
    return {"name": name, "value": value, "unit": unit, **_declared(f"{name} chosen by the example, not a measured part")}


def _expr(v: float) -> dict:
    return {"offset": v, "terms": []}


def _pos(x: float, y: float, z: float) -> dict:
    return {"x": _expr(x), "y": _expr(y), "z": _expr(z)}


def _quat(q: tuple[float, float, float, float]) -> dict:
    return dict(zip("xyzw", q))


def _snap(sid: str, kind: str, accepts: list[str], at: tuple[float, float, float], why: str) -> dict:
    return {"id": sid, "kind": kind, "accepts": accepts, "position": _pos(*at), "orientation": _quat(IDENTITY), **_declared(why)}


def _box(cid: str, size: tuple[float, float, float], at: tuple[float, float, float]) -> dict:
    sx, sy, sz = size
    return {
        "id": cid,
        "primitive": {"kind": "box", "size_x": _expr(sx), "size_y": _expr(sy), "size_z": _expr(sz)},
        "operation": "add",
        "position": _pos(*at),
        "orientation": _quat(IDENTITY),
    }


def library_part(part_id: str) -> PartDef:
    return PartDef.model_validate_json((LIBRARY / f"{part_id}.json").read_text(encoding="utf-8"))


def chassis_part() -> PartDef:
    """The deck and two motor hangers, and every snap point the car uses (chassis frame = deck centre)."""
    z_axle = WHEEL_R - CHASSIS_Z
    z_top = DECK_T / 2
    deck_bottom = CHASSIS_Z - DECK_T / 2
    motor_top = WHEEL_R + GEARBOX_R
    hanger_h = deck_bottom - motor_top
    hanger_z = (deck_bottom + motor_top) / 2 - CHASSIS_Z
    xf, xr = AXLE_X
    snaps = [
        _snap("motor-rl", "motor_mount", ["motor_mount"], (xr, MOTOR_Y, z_axle), "rear left motor face plate, under its hanger"),
        _snap("motor-rr", "motor_mount", ["motor_mount"], (xr, -MOTOR_Y, z_axle), "rear right motor face plate, under its hanger"),
        _snap("axle-fl", "axle_mount", ["shaft"], (xf, WHEEL_Y, z_axle), "front left axle end (the wheel centre); the axle is not drawn"),
        _snap("axle-fr", "axle_mount", ["shaft"], (xf, -WHEEL_Y, z_axle), "front right axle end (the wheel centre); the axle is not drawn"),
        _snap("battery-seat", "face", ["face"], (0.05, 0.0, z_top), "battery seat on the deck top"),
        _snap("tank-seat", "face", ["face"], (-0.04, 0.0, z_top), "tank seat on the deck top"),
        _snap("thruster-mount", "face", ["face"], (-0.10, 0.0, z_top + THRUSTER_BODY_R), "thruster mount: the back face of its valve body, which lies on the deck"),
        _snap("spring-l", "spring_end", ["spring_end"], (DECK_L / 2, SPRING_Y, 0.0), "left bumper spring seat on the deck's front face"),
        _snap("spring-r", "spring_end", ["spring_end"], (DECK_L / 2, -SPRING_Y, 0.0), "right bumper spring seat on the deck's front face"),
    ]
    components = [
        _box("deck", (DECK_L, DECK_W, DECK_T), (0.0, 0.0, 0.0)),
        _box("hanger_l", (0.02, 0.024, hanger_h), (xr, MOTOR_Y - 0.012, hanger_z)),
        _box("hanger_r", (0.02, 0.024, hanger_h), (xr, -MOTOR_Y + 0.012, hanger_z)),
    ]
    return PartDef.model_validate(
        {
            "id": "drive-chassis",
            "name": "Drive car chassis (deck with motor hangers)",
            "snap_points": snaps,
            "shape": {**_declared("a flat deck and two motor hangers drawn from boxes; dimensions chosen by the example"), "components": components},
        }
    )


def stub_part() -> PartDef:
    """A rod between a motor shaft (`in`, at the shaft's snap point) and a wheel hub (`out`, at the wheel centre)."""
    return PartDef.model_validate(
        {
            "id": "drive-stub",
            "name": "Axle stub (motor shaft to wheel hub)",
            "snap_points": [
                _snap("in", "shaft", ["shaft"], (0.0, 0.0, 0.0), "on the motor's shaft snap; the rod starts at the shaft tip"),
                _snap("out", "axle_mount", ["shaft"], (0.0, 0.0, STUB_OUT), "the wheel centre; the rod ends at the wheel's inner hub boss"),
            ],
            "shape": {
                **_declared("a rod of radius 4 mm along the axle, end to end with the motor shaft and the wheel hub"),
                "components": [
                    {
                        "id": "rod",
                        "primitive": {"kind": "cylinder", "radius": _expr(STUB_R), "length": _expr(STUB_LEN)},
                        "operation": "add",
                        "position": _pos(0.0, 0.0, STUB_START + STUB_LEN / 2),
                        "orientation": _quat(IDENTITY),
                    }
                ],
            },
        }
    )


MATERIALS = ("al6061-t6", "pom-delrin-150", "steel-a36")

# instance id -> (part id, material, parameters the instance sets, orientation). The rest are the part's defaults.
INSTANCES: dict[str, tuple[str, str | None, dict[str, tuple[float, str]], tuple[float, float, float, float]]] = {
    "chassis": ("drive-chassis", "al6061-t6", {}, IDENTITY),
    "motor-rl": ("motor-37d-12v-50-1", None, {}, SHAFT_OUT_LEFT),
    "motor-rr": ("motor-37d-12v-50-1", None, {}, SHAFT_OUT_RIGHT),
    "stub-rl": ("drive-stub", "al6061-t6", {}, SHAFT_OUT_LEFT),
    "stub-rr": ("drive-stub", "al6061-t6", {}, SHAFT_OUT_RIGHT),
    "wheel-rl": ("wheel", "pom-delrin-150", {}, IDENTITY),
    "wheel-rr": ("wheel", "pom-delrin-150", {}, TURN_Z),
    "wheel-fl": ("wheel", "pom-delrin-150", {}, IDENTITY),
    "wheel-fr": ("wheel", "pom-delrin-150", {}, TURN_Z),
    "battery": ("battery-pack-4s", None, {}, IDENTITY),
    "tank": ("tank", "al6061-t6", {"radius": (0.035, "m"), "length": (0.1, "m")}, IDENTITY),
    "thruster": ("thruster-vacco-48003040", "steel-a36", {}, EXHAUST_AFT),
    "spring-l": ("spring-damper-lee-lc032b08", None, {}, ALONG_X),
    "spring-r": ("spring-damper-lee-lc032b08", None, {}, ALONG_X),
}

# (joint id, kind, parent instance, parent snap, child instance, child snap, hinge axis in the parent snap's frame).
# The order is the placement order: a child's parent is placed first. `chassis` is the root.
JOINTS: tuple[tuple[str, str, str, str, str, str, tuple[float, float, float] | None], ...] = (
    ("mount-rl", "fixed", "chassis", "motor-rl", "motor-rl", "mount", None),
    ("mount-rr", "fixed", "chassis", "motor-rr", "motor-rr", "mount", None),
    ("drive-rl", "hinge", "motor-rl", "shaft", "stub-rl", "in", (0.0, 0.0, 1.0)),  # shaft +z = world +y
    ("drive-rr", "hinge", "motor-rr", "shaft", "stub-rr", "in", (0.0, 0.0, -1.0)),  # shaft +z = world -y: flipped so + rolls forward
    ("hub-rl", "fixed", "stub-rl", "out", "wheel-rl", "hub", None),
    ("hub-rr", "fixed", "stub-rr", "out", "wheel-rr", "hub", None),
    ("axle-fl", "hinge", "chassis", "axle-fl", "wheel-fl", "hub", (0.0, 1.0, 0.0)),
    ("axle-fr", "hinge", "chassis", "axle-fr", "wheel-fr", "hub", (0.0, 1.0, 0.0)),
    ("seat-battery", "fixed", "chassis", "battery-seat", "battery", "bottom", None),
    ("seat-tank", "fixed", "chassis", "tank-seat", "tank", "bottom", None),
    ("mount-thruster", "fixed", "chassis", "thruster-mount", "thruster", "mount", None),
    ("bumper-l", "fixed", "chassis", "spring-l", "spring-l", "end_a", None),
    ("bumper-r", "fixed", "chassis", "spring-r", "spring-r", "end_a", None),
)

ACTUATORS = (
    {"id": "drive-motor-rl", "kind": "motor", "instance": "motor-rl", "joint": "drive-rl", "supply": "battery"},
    {"id": "drive-motor-rr", "kind": "motor", "instance": "motor-rr", "joint": "drive-rr", "supply": "battery"},
    {"id": "thrust", "kind": "thruster", "instance": "thruster", "supply": "tank"},
)

SCHEDULE = (
    ("run-rl", "drive-motor-rl", 0.0, 3.0, 1.0),
    ("run-rr", "drive-motor-rr", 0.0, 3.0, 1.0),
    ("burn", "thrust", 1.0, 2.0, 1.0),
)


def rotate(q: tuple[float, float, float, float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    """`v` turned by the unit quaternion `q` (x, y, z, w)."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 q_vec x v; v' = v + w t + q_vec x t
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


def local_snap(part: PartDef, values: dict[str, float], snap_id: str) -> tuple[float, float, float]:
    s = next(s for s in part.snap_points if s.id == snap_id)
    return tuple(a.offset + sum(t.factor * values[t.param] for t in a.terms) for a in (s.position.x, s.position.y, s.position.z))  # type: ignore[return-value]


def parts() -> dict[str, PartDef]:
    own = {"drive-chassis": chassis_part(), "drive-stub": stub_part()}
    return {pid: own[pid] if pid in own else library_part(pid) for pid in dict.fromkeys(p for p, _, _, _ in INSTANCES.values())}


def build_project() -> Project:
    defs = parts()
    values = {
        iid: {p.name: p.default.value for p in defs[pid].parameters} | {n: v for n, (v, _) in params.items()}
        for iid, (pid, _, params, _) in INSTANCES.items()
    }
    position = {"chassis": (0.0, 0.0, CHASSIS_Z)}
    for _, _, parent, parent_snap, child, child_snap, _ in JOINTS:
        qa, qb = INSTANCES[parent][3], INSTANCES[child][3]
        pa = rotate(qa, local_snap(defs[INSTANCES[parent][0]], values[parent], parent_snap))
        pb = rotate(qb, local_snap(defs[INSTANCES[child][0]], values[child], child_snap))
        base = position[parent]
        position[child] = tuple(base[k] + pa[k] - pb[k] for k in range(3))
    instances = []
    for iid, (pid, material, params, q) in INSTANCES.items():
        x, y, z = position[iid]
        instances.append(
            {
                "id": iid,
                "part": pid,
                "material": material,
                "parameters": [_param(n, v, u) for n, (v, u) in params.items()],
                "pose": {
                    "position": {"x": x, "y": y, "z": z},
                    "orientation": _quat(q),
                    **_declared("placed by solving the joints so that joined snap points meet"),
                },
            }
        )
    joints = []
    for jid, kind, a, sa, b, sb, axis in JOINTS:
        joint = {"id": jid, "kind": kind, "a": {"instance": a, "snap_point": sa}, "b": {"instance": b, "snap_point": sb}}
        if axis is not None:
            joint["axis"] = {
                "x": axis[0],
                "y": axis[1],
                "z": axis[2],
                **_declared("hinge axis along the axle (world +y), so a positive angle rolls the car forward (+x)"),
            }
        joints.append(joint)
    schedule = [
        {"type": "actuate", "id": eid, "actuator": act, "start": t0, "end": t1, "command": c, **_declared("a demonstration program, not a tuned run")}
        for eid, act, t0, t1, c in SCHEDULE
    ]
    catalog = load_material_catalog()
    return Project.model_validate(
        {
            "design": {
                "materials": [catalog.get(m).material.model_dump(mode="json") for m in MATERIALS],
                "parts": [p.model_dump(mode="json") for p in defs.values()],
                "instances": instances,
                "joints": joints,
                "actuators": list(ACTUATORS),
                "schedule": {"entries": schedule},
            },
            "world": {"planet": "earth"},
        }
    )


def glb_name(instance_id: str) -> str:
    return f"{instance_id}.glb"


def instance_glb(design: DesignSpec, instance_id: str) -> bytes:
    inst = next(i for i in design.instances if i.id == instance_id)
    part = next(p for p in design.parts if p.id == inst.part)
    material = next((m for m in design.materials if m.id == inst.material), None)
    return part_glb(part, material, {p.name: p for p in inst.parameters})


# The key specs of each drive part, as (part id, where, name). `where` is `spec` (PartDef.specs), `param` (the
# parameter's default), `curve_start` (the first point of a curve: the stall torque of a torque-speed curve) or
# `supply` (the tank's propellant capacity, `tank_supply` at the instance's parameters).
KEY_SPECS: tuple[tuple[str, str, str], ...] = (
    ("wheel", "spec", "tread_friction_static"),
    ("wheel", "spec", "tread_friction_kinetic"),
    ("motor-37d-12v-50-1", "spec", "rated_voltage"),
    ("motor-37d-12v-50-1", "curve_start", "torque_speed"),
    ("thruster-vacco-48003040", "spec", "rated_thrust"),
    ("battery-pack-4s", "spec", "nominal_voltage"),
    ("battery-pack-4s", "spec", "energy_capacity"),
    ("tank", "supply", "propellant_capacity"),
    ("spring-damper-lee-lc032b08", "param", "stiffness"),
    ("spring-damper-lee-lc032b08", "param", "damping"),
)


def spec_rows(project: Project) -> list[dict]:
    """The key specs as the project's part definitions state them: nothing here is typed in, every number is read."""
    defs = {p.id: p for p in project.design.parts}
    rows = []
    for pid, where, name in KEY_SPECS:
        part = defs[pid]
        users = [i.id for i in project.design.instances if i.part == pid]
        if where == "spec":
            q = next(s for s in part.specs if s.name == name)
            label = name
        elif where == "param":
            q = next(p for p in part.parameters if p.name == name).default
            label = name
        elif where == "curve_start":
            curve = next(c for c in part.curves if c.name == name).curve
            q = {"value": evaluate(curve, curve.points[0].x), "unit": curve.y_unit, "badge": curve.badge, "source": curve.source}
            label = f"stall_torque ({name} at {curve.points[0].x:g} {curve.x_unit.value})"
        else:  # supply
            inst = next(i for i in project.design.instances if i.part == pid)
            q = tank_supply(part, {p.name: p for p in inst.parameters}).capacity
            label = name
        if not isinstance(q, dict):
            q = {"value": q.value, "unit": q.unit, "badge": q.badge, "source": q.source}
        src = q["source"]
        rows.append(
            {
                "part": pid,
                "part_name": part.name,
                "instances": users,
                "from": where,
                "name": label,
                "value": q["value"],
                "unit": q["unit"].value,
                "badge": q["badge"].value,
                "badge_label": BADGE_LABEL_KO[Badge(q["badge"])],
                "source_ref": src.ref,
                "source_locator": src.locator,
                "source_url": src.url,
            }
        )
    return rows


def manifest(project: Project) -> dict:
    """What the browser page needs: no number in it is computed outside the engine and the part definitions."""
    design = project.design
    defs = {p.id: p for p in design.parts}
    rows = []
    for inst in design.instances:
        pos, q = inst.pose.position, inst.pose.orientation
        part = defs[inst.part]
        rows.append(
            {
                "id": inst.id,
                "part": inst.part,
                "part_name": part.name,
                "role": part.role.value if part.role is not None else None,
                "material": inst.material,
                "glb": glb_name(inst.id),
                "pose": {"position": {"x": pos.x, "y": pos.y, "z": pos.z}, "orientation": {"x": q.x, "y": q.y, "z": q.z, "w": q.w}},
            }
        )
    return {
        "project": EXAMPLE.name,
        "planet": project.world.planet,
        "instances": rows,
        "joints": [{"id": j.id, "kind": j.kind.value, "a": j.a.instance, "b": j.b.instance} for j in design.joints],
        "actuators": [{"id": a.id, "kind": a.kind.value, "instance": a.instance, "joint": a.joint, "supply": a.supply} for a in design.actuators],
        "specs": spec_rows(project),
    }


def main() -> None:
    project = build_project()
    EXAMPLE.write_bytes(export_json(project))
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for inst in project.design.instances:
        (FIXTURES / glb_name(inst.id)).write_bytes(instance_glb(project.design, inst.id))
    MANIFEST.write_text(json.dumps(manifest(project), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", EXAMPLE, MANIFEST, "and", len(project.design.instances), "glb files")


if __name__ == "__main__":
    main()
