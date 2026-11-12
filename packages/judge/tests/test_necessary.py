"""J-01b: the necessary-condition screen against hand calculations.

Every bound is written out here from the textbook rule it rests on (work = m g h, friction impulse <= mu N, the X-01b motor
line and current line), with the masses and centres of mass the compiler gives for the fixture (B-01a mass properties are
not under test). Poses, the test block, the arm and the regions are fixtures declared by the test (`사용자 선언`), not part data.
The motor is the library Pololu 37D (`part-motor.md`), the cell the library 18650 (`parts-battery-tank.md`).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from kinetra_core import PartDef, Project, load_body, load_material_catalog
from kinetra_engine.compiler import build_body_tree, compile_drives
from kinetra_engine.parts import collision_proxy

from kinetra_judge import INFEASIBLE, NUMERIC_MARGIN, CheckStatus, Goal, motor_efficiency_bound, motor_peak_power, necessary_screen

LIBRARY = Path(__file__).parents[2] / "engine" / "src" / "kinetra_engine" / "parts" / "library"
SRC = {"ref": "J-01b test fixture: value chosen by the test", "locator": "test_necessary.py"}
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
S2 = math.sqrt(0.5)
ROT_X90 = {"x": S2, "y": 0.0, "z": 0.0, "w": S2}  # part +y -> world +z
ROT_Y90 = {"x": 0.0, "y": S2, "z": 0.0, "w": S2}  # part +z -> world +x


def library_part(part_id: str) -> PartDef:
    return PartDef.model_validate_json((LIBRARY / f"{part_id}.json").read_text(encoding="utf-8"))


MOTOR, WHEEL, BATTERY = library_part("motor-37d-12v-50-1"), library_part("wheel"), library_part("battery-18650")
POM = load_material_catalog().get("pom-delrin-150").material

# Pololu 37D 12 V 50:1 as the part cites it (part-motor.md)
T0 = 210 * 9.80665e-3  # stall torque [N*m]
W0 = 200 * 2 * math.pi / 60  # no-load speed [rad/s]
VOLT, I_NL, I_STALL = 12.0, 0.2, 5.5  # [V], [A], [A]
CELL_ENERGY = 42120.0  # battery-18650 energy_capacity [J]


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(offset=0.0):
    return {"offset": offset, "terms": []}


def instance(id, part, at, quat=None, material=None):
    inst = {"id": id, "part": part, "pose": {"badge": "declared", "source": SRC, "position": dict(zip("xyz", at)), "orientation": quat or IDENT}}
    if material is not None:
        inst["material"] = material
    return inst


def joint(id, kind, a, b):
    return {"id": id, "kind": kind, "a": {"instance": a[0], "snap_point": a[1]}, "b": {"instance": b[0], "snap_point": b[1]}}


def block_part(id, size, snaps):
    """A box of `size` centred on its origin; snap points `(id, kind, position, orientation)` accepting their own kind."""
    return {"id": id, "name": id, "parameters": [],
            "snap_points": [{"id": i, "kind": k, "accepts": [k], "badge": "declared", "source": SRC,
                             "position": {"x": ax(p[0]), "y": ax(p[1]), "z": ax(p[2])}, "orientation": o} for i, k, p, o in snaps],
            "shape": {"badge": "declared", "source": SRC, "components": [
                {"id": "b", "operation": "add", "primitive": {"kind": "box", "size_x": ax(size[0]), "size_y": ax(size[1]), "size_z": ax(size[2])},
                 "position": {"x": ax(), "y": ax(), "z": ax()}}]}}


def material(id, density):
    return {"id": id, "name": id, "density": q(density, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


MAT = material("mat", 1000.0)


def project(parts, instances, joints, actuators, materials, planet):
    dump = [p if isinstance(p, dict) else p.model_dump(mode="json") for p in parts]
    mats = [m if isinstance(m, dict) else m.model_dump(mode="json") for m in materials]
    return Project.model_validate({"design": {"materials": mats, "parts": dump, "instances": instances, "joints": joints, "actuators": actuators},
                                   "world": {"planet": planet}})


# The 37D stands on the ground shaft up (lowest point, the encoder's end, at z = 0); a POM wheel turns on its shaft about the
# vertical; a test bracket holds the motor and an 18650 cell that powers it (the X-01b battery rig).
H = -min(g.center[2] - next(d.value for d in g.dimensions if d.name == "length") / 2 for g in collision_proxy(MOTOR).geoms)
BRACKET = block_part("bracket", (0.02, 0.02, 0.02), (("mount", "motor_mount", (-0.05, 0.0, 0.0), IDENT), ("cell", "face", (0.01, 0.0, 0.0), IDENT)))


def rig(planet="earth", hold_threshold=None):
    instances = [instance("m1", MOTOR.id, (0.0, 0.0, H)), instance("w1", WHEEL.id, (0.0, 0.0, H + 0.014), ROT_X90, material=POM.id),
                 instance("br", "bracket", (0.05, 0.0, H), material="mat"), instance("b1", BATTERY.id, (0.06925, 0.0, H))]
    joints = [joint("axle", "hinge", ("m1", "shaft"), ("w1", "hub")), joint("hold", "fixed", ("br", "mount"), ("m1", "mount")),
              joint("clip", "fixed", ("br", "cell"), ("b1", "side-xn"))]
    if hold_threshold is not None:
        joints[1]["break_threshold"] = q(hold_threshold, "N")
    act = [{"id": "drive", "kind": "motor", "instance": "m1", "joint": "axle", "supply": "b1"}]
    return project([MOTOR, WHEEL, BATTERY, BRACKET], instances, joints, act, [POM, MAT], planet)


def goal(*conditions):
    return Goal.model_validate({"conditions": list(conditions)})


def reach(instance_id, lo, hi):
    return {"kind": "reach", "id": "there", "instance": instance_id,
            "region": {"min": dict(zip("xyz", lo)), "max": dict(zip("xyz", hi))}}


def by_name(screen):
    return {c.name: c for c in screen.checks}


def eta_by_hand() -> float:
    """sup over s in [0, 1] of shaft / battery power at command 1, speed s W0, torque T0 (1 - s) (straight 37D curve), by a
    dense grid (a method independent of the exact segment solution)."""
    n = 200_000
    return max(s * W0 * T0 * (1 - s) / (VOLT * (I_NL + (I_STALL - I_NL) * (1 - s))) for s in (i / n for i in range(n + 1)))


def test_necessary_motor_bounds_match_the_hand_calculation():
    motor = compile_drives(build_body_tree(rig())).motors[0]
    assert motor_peak_power(motor) == pytest.approx(T0 * W0 / 4, rel=1e-12)  # straight line: max at W0 / 2
    assert motor_efficiency_bound(motor) == pytest.approx(eta_by_hand(), rel=1e-8)
    assert 0.0 < motor_efficiency_bound(motor) < 1.0


def tree_numbers(proj):
    tree = build_body_tree(proj)
    com = {}
    for ci in tree.instances:
        c = ci.properties.center_of_mass
        w, x, y, z = ci.orientation
        # rotate (c.x, c.y, c.z) by the unit quaternion (w, x, y, z)
        v = (c.x, c.y, c.z)
        t = (2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0]))
        r = (v[0] + w * t[0] + y * t[2] - z * t[1], v[1] + w * t[1] + z * t[0] - x * t[2], v[2] + w * t[2] + x * t[1] - y * t[0])
        com[ci.instance] = tuple(ci.position[k] + r[k] for k in range(3))
    mass = {ci.instance: ci.properties.mass.value for ci in tree.instances}
    return tree, mass, com


# --- impossible case 1: energy ----------------------------------------------------------------------------------------


def test_necessary_energy_one_cell_cannot_lift_the_motor_ten_kilometres():
    # The motor's body (motor + bracket + cell, welded) must put its reference point 10 km up: the origin of its smallest
    # instance, the cell `b1` (J-02a). Work needed m g (10 000 - |origin - com| - com_z); the cell gives at most eta x 42 120 J,
    # the wheel at most its potential energy.
    proj = rig()
    tree, mass, com = tree_numbers(proj)
    g = load_body("earth").gravity.value
    body = ("b1", "br", "m1")
    m = math.fsum(mass[i] for i in body)
    c = tuple(math.fsum(mass[i] * com[i][k] for i in body) / m for k in range(3))
    need = m * g * (10_000.0 - math.dist((0.06925, 0.0, H), c) - c[2])
    available = eta_by_hand() * CELL_ENERGY + mass["w1"] * g * com["w1"][2]
    assert need > available  # about 3.0e4 J against about 1.9e4 J
    screen = necessary_screen(proj, goal(reach("m1", (-1.0, -1.0, 10_000.0), (1.0, 1.0, 10_001.0))))
    e = by_name(screen)["energy_height"]
    assert (e.status, e.unit) == (CheckStatus.FAILED, "J")
    assert e.required == pytest.approx(need, rel=1e-9)
    assert e.available == pytest.approx(available, rel=1e-7)
    assert screen.verdict == INFEASIBLE


def test_necessary_energy_passes_for_a_reachable_height_and_proves_nothing():
    screen = necessary_screen(rig(), goal(reach("m1", (-1.0, -1.0, 1.0), (1.0, 1.0, 2.0))))
    assert by_name(screen)["energy_height"].status is CheckStatus.PASSED
    assert screen.verdict is None
    assert any("통과는 된다는 뜻이 아니다" in label for label in screen.labels)


# --- impossible case 2 and the boundary case: friction impulse on the Moon -------------------------------------------


def horizontal_numbers(proj, seconds):
    """Hand bound of the horizontal travel of the centre of mass by `seconds` on the Moon (no air, so no drag term):
    mu (g T^2 / 2 + W / (M g)), W = min(eta E_cell, (T0 W0 / 4) T); and the reach radius of the wheel's origin: the wheel body's
    |origin - com| plus, for the motor body, |origin - shaft anchor| + |anchor - com|, weighted by mass."""
    tree, mass, com = tree_numbers(proj)
    g = load_body("moon").gravity.value
    total = math.fsum(mass.values())
    c = tuple(math.fsum(mass[i] * com[i][k] for i in mass) / total for k in range(3))
    work = min(eta_by_hand() * CELL_ENERGY, T0 * W0 / 4 * seconds)
    lift = g * seconds**2 / 2 + work / (total * g)
    origin = (0.0, 0.0, H + 0.014)  # the wheel's origin is its hub, on the shaft snap point
    motor_body = ("b1", "br", "m1")
    m_m = math.fsum(mass[i] for i in motor_body)
    c_m = tuple(math.fsum(mass[i] * com[i][k] for i in motor_body) / m_m for k in range(3))
    radius = (mass["w1"] * math.dist(origin, com["w1"]) + m_m * (0.0 + math.dist(origin, c_m))) / total
    return c, lift, radius


def test_necessary_impulse_on_the_moon_friction_cannot_carry_it_fifty_metres_in_two_seconds():
    proj = rig("moon")
    c, lift, radius = horizontal_numbers(proj, 2.0)
    mu_high = load_body("moon").ground_friction.distribution.high  # 0.9004 (tan 42 deg, bodies.md)
    x0 = 50.0
    screen = necessary_screen(proj, goal(reach("w1", (x0, -1.0, 0.0), (x0 + 1.0, 1.0, 1.0)), {"kind": "time_limit", "id": "t", "seconds": 2.0}))
    i = by_name(screen)["impulse_horizontal"]
    assert i.status is CheckStatus.FAILED
    assert i.favorable == {"ground_friction": mu_high}
    assert i.available == pytest.approx(mu_high * lift, rel=1e-9)
    assert i.required == pytest.approx(x0 - c[0] - radius, rel=1e-9)
    assert screen.verdict == INFEASIBLE


def test_necessary_boundary_fails_at_the_nominal_friction_but_not_at_the_favorable_end():
    # A region between the nominal bound (mu 0.6573) and the favourable one (mu 0.9004): no INFEASIBLE.
    proj = rig("moon")
    c, lift, radius = horizontal_numbers(proj, 2.0)
    friction = load_body("moon").ground_friction
    nominal, high = friction.value.value * lift, friction.distribution.high * lift
    x0 = c[0] + radius + (nominal + high) / 2
    screen = necessary_screen(proj, goal(reach("w1", (x0, -1.0, 0.0), (x0 + 1.0, 1.0, 1.0)), {"kind": "time_limit", "id": "t", "seconds": 2.0}))
    i = by_name(screen)["impulse_horizontal"]
    assert i.nominal_available == pytest.approx(nominal, rel=1e-9)
    assert i.nominal_available < i.required < i.available
    assert i.status is CheckStatus.PASSED and screen.verdict is None


# --- energy rotation ----------------------------------------------------------------------------------------------------


def test_necessary_rotation_bound_is_time_times_the_spin_all_energy_allows():
    proj = rig()
    tree, mass, com = tree_numbers(proj)
    g = load_body("earth").gravity.value
    seconds = 0.5
    energy = min(eta_by_hand() * CELL_ENERGY, T0 * W0 / 4 * seconds) + math.fsum(mass[i] * g * com[i][2] for i in mass)
    i = tree.body_of("w1").inertia
    import numpy as np

    lam = np.linalg.eigvalsh(np.array([[i[0], i[3], i[4]], [i[3], i[1], i[5]], [i[4], i[5], i[2]]]))[0]
    bound = math.degrees(seconds * math.sqrt(2 * energy / lam))
    screen = necessary_screen(proj, goal({"kind": "rotation", "id": "spin", "instance": "w1", "axis": "y", "angle_deg": 1.0e6},
                                         {"kind": "time_limit", "id": "t", "seconds": seconds}))
    r = by_name(screen)["energy_rotation"]
    assert r.available == pytest.approx(bound, rel=1e-9)
    assert r.status is CheckStatus.FAILED and screen.verdict == INFEASIBLE


# --- static torque: a warning, never INFEASIBLE -----------------------------------------------------------------------


def test_necessary_static_torque_is_a_warning_not_a_verdict():
    # The 37D lies on its side (shaft along +x, lowest point on the ground) and holds a 0.02 x 0.5 x 0.02 m arm of a
    # declared 8000 kg/m^3 sticking out along +y. Gravity moment about the shaft: 1.6 kg x g x 0.25 m = 3.92 N*m > 2.0594 N*m.
    radius = max(next(d.value for d in g.dimensions if d.name == "radius") for g in collision_proxy(MOTOR).geoms)
    shaft = (0.014, 0.0, radius)
    arm = block_part("arm", (0.02, 0.5, 0.02), (("hub", "shaft", (-0.01, -0.25, 0.0), ROT_Y90),))
    arm["snap_points"][0]["accepts"] = ["shaft"]
    instances = [instance("m1", MOTOR.id, (0.0, 0.0, radius), ROT_Y90), instance("a1", "arm", (shaft[0] + 0.01, 0.25, radius), material="heavy")]
    proj = project([MOTOR, arm], instances, [joint("axle", "hinge", ("m1", "shaft"), ("a1", "hub"))],
                   [{"id": "drive", "kind": "motor", "instance": "m1", "joint": "axle"}], [material("heavy", 8000.0)], "earth")
    screen = necessary_screen(proj, goal(reach("a1", (-1.0, -1.0, 0.3), (1.0, 1.0, 1.0)), {"kind": "time_limit", "id": "t", "seconds": 5.0}))
    s = by_name(screen)["static_torque"]
    g = load_body("earth").gravity.value
    assert (s.status, s.joint, s.condition) == (CheckStatus.WARNING, "axle", None)
    assert s.required == pytest.approx(0.02 * 0.5 * 0.02 * 8000.0 * g * 0.25, rel=1e-9)
    assert s.available == pytest.approx(T0, rel=1e-12)
    assert screen.verdict is None  # the arm can still be swung up: not a proof of impossibility


def test_necessary_unapplied_project_assumptions_are_labelled():
    proj = rig()
    data = proj.model_dump(mode="json")
    data["assumptions"] = {"assumptions": [{"key": "vehicle_mass", "label": "Vehicle mass", "value": q(1.0, "kg"), "confidence": "low"}]}
    screen = necessary_screen(Project.model_validate(data), goal(reach("m1", (-1.0, -1.0, 0.0), (1.0, 1.0, 1.0))))
    assert "미적용: 가정 vehicle_mass는 모델에 바인딩되지 않아 흔들지 않았다" in screen.labels


# --- review of #578: breakable joints, disconnected trees, the numerical margin ---------------------------------------


def test_necessary_breakable_joint_takes_each_candidate_instance_alone():
    # With a break threshold on `hold` the piece the cell moves with can change, so the reference candidates are the body's
    # instances with an id at most the condition's, each alone; the most favourable one decides.
    proj = rig(hold_threshold=1000.0)
    tree, mass, com = tree_numbers(proj)
    g = load_body("earth").gravity.value
    body = tree.body_of("br").instances
    work = eta_by_hand() * CELL_ENERGY
    options = []
    for p in (i for i in body if i <= "br"):
        need = mass[p] * g * (10_000.0 - math.dist(next(ci.position for ci in tree.instances if ci.instance == p), com[p]) - com[p][2])
        others = math.fsum(mass[i] * g * com[i][2] for i in mass if i != p)
        options.append((need, work + others))
    need, available = min(options, key=lambda o: o[0] - o[1])
    e = by_name(necessary_screen(proj, goal(reach("br", (-1.0, -1.0, 10_000.0), (1.0, 1.0, 10_001.0)))))["energy_height"]
    assert e.required == pytest.approx(need, rel=1e-9) and e.available == pytest.approx(available, rel=1e-7)


def test_necessary_reach_radius_of_a_tree_with_several_free_bodies_is_not_applicable():
    from kinetra_engine.compiler import release

    from kinetra_judge import necessary

    proj = rig("moon")
    d = necessary._Design(proj)
    d.tree = release(d.tree, ["axle"])  # the wheel is a free body no joint chain reaches
    c = goal(reach("w1", (50.0, -1.0, 0.0), (51.0, 1.0, 1.0)), {"kind": "time_limit", "id": "t", "seconds": 2.0}).conditions[0]
    i = necessary._impulse_horizontal(c, d, 2.0)
    assert i.status is CheckStatus.NOT_APPLICABLE and "이어지지 않은 몸" in i.reason


def test_necessary_numerical_margin_keeps_a_requirement_just_over_the_bound_feasible():
    proj = rig("moon")
    c, lift, radius = horizontal_numbers(proj, 2.0)
    high = load_body("moon").ground_friction.distribution.high * lift
    x0 = c[0] + radius + high * (1.0 + NUMERIC_MARGIN.value / 2)  # over the bound, inside the margin
    i = by_name(necessary_screen(proj, goal(reach("w1", (x0, -1.0, 0.0), (x0 + 1.0, 1.0, 1.0)), {"kind": "time_limit", "id": "t", "seconds": 2.0})))["impulse_horizontal"]
    assert i.available < i.required < i.available * (1.0 + NUMERIC_MARGIN.value)
    assert i.status is CheckStatus.PASSED
    assert NUMERIC_MARGIN.badge.value == "default"


@pytest.mark.parametrize("planet", ["earth", "moon"])
@pytest.mark.parametrize("command", [0.0, 0.3, 1.0])
def test_necessary_engine_energy_stays_under_the_bound(planet, command):
    """The measurement behind NUMERIC_MARGIN's source: the rig run by MuJoCo (default time step, compiled contacts, 5 s) never
    gains more mechanical energy (MuJoCo's kinetic + potential) than the motor-work bound min(eta x drawn, P t). Largest
    gain / bound seen: 0.429 at command 1 (earth and moon), 0.248 / 0.269 at 0.3; at command 0 the energy never rises."""
    import mujoco
    from kinetra_engine.compiler import DriveRuntime, to_mjcf

    tree = build_body_tree(rig(planet))
    drives = compile_drives(tree)
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree, drives=drives))
    model.opt.enableflags |= mujoco.mjtEnableBit.mjENBL_ENERGY
    data = mujoco.MjData(model)
    runtime = DriveRuntime(model, drives)
    mujoco.mj_forward(model, data)
    e0 = data.energy[0] + data.energy[1]
    motor = drives.motors[0]
    worst = 0.0
    for k in range(1, 2501):
        runtime.apply(data, {"drive": command}, model.opt.timestep)
        mujoco.mj_step(model, data)
        gain = data.energy[0] + data.energy[1] - e0
        bound = min(motor_efficiency_bound(motor) * runtime.energy["drive"], motor_peak_power(motor) * k * model.opt.timestep)
        assert gain <= bound * (1.0 + NUMERIC_MARGIN.value) + 1e-12
        if bound > 0.0:
            worst = max(worst, gain / bound)
    assert worst < 0.5
