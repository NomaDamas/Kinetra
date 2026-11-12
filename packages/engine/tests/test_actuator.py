"""X-01b: joints' springs and motors in MuJoCo, the motor's torque-speed limit, battery draw, and the wheel's rolling (B-03a).

Expected numbers are written out by hand from the datasheet values the parts cite (`part-motor.md`, `part-spring-damper.md`,
`parts-battery-tank.md`) and from textbook formulas; MuJoCo 4.0.0 runs the compiled MJCF. Poses, the test blocks and the incline
angle are fixtures declared by the test (`사용자 선언`). The test anchors a rig's root body to the world by removing its free
joint from the MJCF (a bench clamp; the project has no "fixed to the ground" yet), sets the gravity it needs on the loaded model
(overriding the planet gravity of the MJCF `<option>`, W-03a) and turns contact off on the clamped rigs (nothing in them touches
anything). The rolling test uses the compiled ground plane and friction (X-01e).
"""

from __future__ import annotations

import math
import re

import mujoco
import numpy as np
import pytest
from gltf_samples import catalog_material, library_part

from kinetra_core import Project, load_body
from kinetra_engine.compiler import CompileError, CompileErrorCode, DriveRuntime, build_body_tree, compile_drives, to_mjcf
from kinetra_engine.parts import collision_proxy

SRC = {"ref": "X-01b test fixture: value chosen by the test", "locator": "test_actuator.py"}
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
S2 = math.sqrt(0.5)
ROT_X90 = {"x": S2, "y": 0.0, "z": 0.0, "w": S2}  # part +y -> world +z

MOTOR = library_part("motor-37d-12v-50-1")
WHEEL = library_part("wheel")
BATTERY = library_part("battery-18650")
SPRING = library_part("spring-damper-lee-lc032b08")
POM = catalog_material("pom-delrin-150")

# Pololu 37D 12 V 50:1 datasheet values as the part cites them (part-motor.md)
T0 = 210 * 9.80665e-3  # stall torque [N*m], 210 kg*mm
W0 = 200 * 2 * math.pi / 60  # no-load speed [rad/s], 200 rpm
VOLT, I_NL, I_STALL = 12.0, 0.2, 5.5  # rated voltage [V], no-load and stall current [A]
CELL_ENERGY = 42120.0  # battery-18650 energy_capacity [J] (parts-battery-tank.md)
K_SPRING, C_SPRING = 5990.0, 20.0  # spring-damper-lee-lc032b08 stiffness [N/m] (cited) and damping [N*s/m] (default)


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(offset=0.0):
    return {"offset": offset, "terms": []}


def instance(id, part, at=(0.0, 0.0, 0.0), quat=None, material=None, parameters=()):
    inst = {"id": id, "part": part, "pose": {"badge": "declared", "source": SRC, "position": dict(zip("xyz", at)), "orientation": quat or IDENT}}
    if material is not None:
        inst["material"] = material
    if parameters:
        inst["parameters"] = [{"name": n, **q(v, u)} for n, v, u in parameters]
    return inst


def joint(id, kind, a, b, limits=None):
    j = {"id": id, "kind": kind, "a": {"instance": a[0], "snap_point": a[1]}, "b": {"instance": b[0], "snap_point": b[1]}}
    if limits is not None:
        unit = "rad" if kind == "hinge" else "m"
        j["limits"] = {"lower": q(limits[0], unit), "upper": q(limits[1], unit)}
    return j


def block_part(id, size, snaps=(("s1", "plug", (0.0, 0.0, 0.0)),)):
    """A test block (density from `MAT`), a box of `size` centred on its origin, snap points `(id, kind, position)` (+Z the part's +Z,
    each accepting its own kind)."""
    return {"id": id, "name": id, "parameters": [],
            "snap_points": [{"id": i, "kind": k, "accepts": [k], "badge": "declared", "source": SRC, "position": {"x": ax(p[0]), "y": ax(p[1]), "z": ax(p[2])}, "orientation": IDENT}
                            for i, k, p in snaps],
            "shape": {"badge": "declared", "source": SRC, "components": [
                {"id": "b", "operation": "add", "primitive": {"kind": "box", "size_x": ax(size[0]), "size_y": ax(size[1]), "size_z": ax(size[2])}, "position": {"x": ax(), "y": ax(), "z": ax()}}]}}


MAT = {"id": "mat", "name": "Test material", "density": q(1000.0, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"),
       "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


def project(parts, instances, joints=(), actuators=(), materials=(MAT,), planet="earth"):
    dump = [p if isinstance(p, dict) else p.model_dump(mode="json") for p in parts]
    mats = [m if isinstance(m, dict) else m.model_dump(mode="json") for m in materials]
    return Project.model_validate({"design": {"materials": mats, "parts": dump, "instances": list(instances), "joints": list(joints), "actuators": list(actuators)},
                                   "world": {"planet": planet}})


def anchored(xml: str) -> str:
    """The rig's root clamped to the world: its free joint removed."""
    out, n = re.subn(r"\s*<freejoint [^>]*/>", "", xml)
    assert n == 1
    return out


def load(proj, anchor=True, gravity=(0.0, 0.0, 0.0)):
    tree = build_body_tree(proj)
    drives = compile_drives(tree)
    xml = to_mjcf(tree, drives=drives)
    model = mujoco.MjModel.from_xml_string(anchored(xml) if anchor else xml)
    model.opt.gravity[:] = gravity
    # Clamped, the root is welded to the world, and MuJoCo then collides it with its child (its parent-child filter skips bodies
    # welded to the world). These rigs have no ground and nothing to touch, so contact is off.
    model.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONTACT
    return model, mujoco.MjData(model), drives


def dof(model, joint_id):
    return int(model.jnt_dofadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)])


# --- motor rig: the 37D gearmotor turning a POM wheel on its shaft --------------------------------------------------------


# The motor stands on the ground, shaft up: its lowest point (the encoder's end) is at z = 0.
H = -min(g.center[2] - next(d.value for d in g.dimensions if d.name == "length") / 2 for g in collision_proxy(MOTOR).geoms)
BRACKET = block_part("bracket", (0.02, 0.02, 0.02), (("mount", "motor_mount", (-0.05, 0.0, 0.0)), ("cell", "face", (0.01, 0.0, 0.0))))


def motor_rig(limits=None, supply=False, charge=None, motor=MOTOR):
    """Motor `m1` (clamped) with wheel `w1` on hinge `axle` (shaft snap +Z, vertical); actuator `drive`. With `supply`, a test
    bracket holds the motor at its mount and battery `b1` at its side, and `drive` draws from `b1`. Joined snap points meet."""
    instances = [instance("m1", MOTOR.id, (0.0, 0.0, H)), instance("w1", WHEEL.id, (0.0, 0.0, H + 0.014), ROT_X90, material=POM.id)]
    joints = [joint("axle", "hinge", ("m1", "shaft"), ("w1", "hub"), limits=limits)]
    act = {"id": "drive", "kind": "motor", "instance": "m1", "joint": "axle"}
    parts, materials = [motor, WHEEL], [POM]
    if supply:
        params = () if charge is None else (("initial_charge", charge, "1"),)
        instances.append(instance("br", "bracket", (0.05, 0.0, H), material="mat"))
        instances.append(instance("b1", BATTERY.id, (0.06925, 0.0, H), parameters=params))  # side-xn at x - 0.00925
        joints.append(joint("hold", "fixed", ("br", "mount"), ("m1", "mount")))
        joints.append(joint("clip", "fixed", ("br", "cell"), ("b1", "side-xn")))
        act["supply"] = "b1"
        parts += [BATTERY, BRACKET]
        materials.append(MAT)
    return project(parts, instances, joints, [act], materials=materials)


def run(model, data, runtime, commands, seconds):
    dt = model.opt.timestep
    for _ in range(round(seconds / dt)):
        runtime.apply(data, commands, dt)
        mujoco.mj_step(model, data)


def test_actuator_motor_drive_takes_the_part_curve():
    model, data, drives = load(motor_rig())
    (m,) = drives.motors
    assert (m.actuator, m.joint, m.instance, m.supply) == ("drive", "axle", "m1", None)
    assert m.stall_torque == pytest.approx(T0, rel=1e-12) and m.no_load_speed == pytest.approx(W0, rel=1e-12) and m.rated_voltage == VOLT
    act = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "drive")
    assert not model.actuator_ctrllimited[act] and model.actuator_gear[act][0] == 1.0
    # the back-EMF is the hinge's damping: T0 / W0, the slope of the datasheet line (#546)
    assert model.dof_damping[dof(model, "axle")] == pytest.approx(T0 / W0, rel=1e-12)


def motor_torque(model, data, joint_id="axle"):
    """The motor's torque on the hinge: the actuator's part plus the back-EMF the hinge's damping applies."""
    return float(data.actuator_force[0] + data.qfrc_damper[dof(model, joint_id)])


@pytest.mark.parametrize("command", [1.0, 0.5, -1.0, -0.25])
def test_actuator_no_load_speed_is_the_datasheet_speed_times_the_command(command):
    """No load: the wheel spins up until the torque is 0, at |u| x 200 rpm in the command's direction."""
    model, data, drives = load(motor_rig())
    runtime = DriveRuntime(model, drives)
    run(model, data, runtime, {"drive": command}, 1.0)
    assert data.qvel[dof(model, "axle")] == pytest.approx(command * W0, rel=1e-6)
    assert motor_torque(model, data) == pytest.approx(0.0, abs=1e-6 * T0)


@pytest.mark.parametrize("command", [1.0, 0.5, -1.0])
def test_actuator_free_rig_never_spins_the_hinge_past_the_no_load_speed(command):
    """#546: the same rig not clamped (free root, no gravity). The motor body's own inertia about the axle is tiny (3e-5 kg*m^2),
    so an explicit stall torque from the step's starting speed threw the hinge to ~137 rad/s in one step. With the back-EMF as
    implicit joint damping the relative speed rises to |u| x 20.944 rad/s and never past it: every step's speed is at most
    |u| W0 (1 + 1e-9) (stated tolerance, rounding), and after 0.2 s it is |u| W0 within 1e-6."""
    model, data, drives = load(motor_rig(), anchor=False)
    runtime = DriveRuntime(model, drives)
    d = dof(model, "axle")
    peak = 0.0
    for _ in range(round(0.2 / model.opt.timestep)):
        runtime.apply(data, {"drive": command}, model.opt.timestep)
        mujoco.mj_step(model, data)
        peak = max(peak, abs(float(data.qvel[d])))
        assert math.copysign(1.0, command) * data.qvel[d] >= 0.0  # never turns against the command
    assert peak <= abs(command) * W0 * (1 + 1e-9)
    assert data.qvel[d] == pytest.approx(command * W0, rel=1e-6)


@pytest.mark.parametrize("command", [1.0, 0.5])
def test_actuator_stall_torque_against_the_joint_limit_is_the_datasheet_stall_torque(command):
    """The hinge's upper limit is the saved pose, so a positive command stalls the motor there: it holds |u| x 210 kg*mm."""
    model, data, drives = load(motor_rig(limits=(-1.0, 0.0)))
    runtime = DriveRuntime(model, drives)
    run(model, data, runtime, {"drive": command}, 0.5)
    d = dof(model, "axle")
    assert abs(data.qvel[d]) < 1e-4
    assert motor_torque(model, data) == pytest.approx(command * T0, rel=1e-4)
    assert data.qfrc_constraint[d] == pytest.approx(-command * T0, rel=1e-4)  # the limit takes it


def test_actuator_torque_speed_limit_follows_the_curve():
    (m,) = compile_drives(build_body_tree(motor_rig())).motors
    # full command: the curve from (0, T0) to (W0, 0); outside it the DC motor's line T0 (u - w / W0): braking past the
    # no-load speed, more than the stall torque when driven backwards (#546)
    assert m.torque(1.0, 0.0) == pytest.approx(T0, rel=1e-12)
    assert m.torque(1.0, W0 / 2) == pytest.approx(T0 / 2, rel=1e-12)
    assert m.torque(1.0, W0) == pytest.approx(0.0, abs=1e-12)
    assert m.torque(1.0, 3 * W0) == pytest.approx(-2 * T0, rel=1e-12)
    assert m.torque(1.0, -5.0) == pytest.approx(T0 * (1 + 5 / W0), rel=1e-12)
    # half command: half the voltage, the line scaled by 1/2 on both axes: T0 (u - w / W0)
    assert m.torque(0.5, W0 / 4) == pytest.approx(T0 * (0.5 - 0.25), rel=1e-12)
    assert m.torque(0.5, W0 / 2) == pytest.approx(0.0, abs=1e-12)
    # sign: the same curve the other way round
    assert m.torque(-1.0, -W0 / 2) == pytest.approx(-T0 / 2, rel=1e-12)
    assert m.torque(-1.0, W0) == pytest.approx(-2 * T0, rel=1e-12)
    # command 0 is 0 V: the shorted motor brakes
    assert m.torque(0.0, 3.0) == pytest.approx(-T0 * 3 / W0, rel=1e-12)
    # what the actuator applies on top of the hinge damping: u T0 at every speed for this linear curve
    for u, w in ((1.0, 0.0), (1.0, 7.0), (0.5, -3.0), (-0.25, 30.0), (0.0, 5.0)):
        assert m.ctrl(u, w) == pytest.approx(u * T0, abs=1e-12)
    with pytest.raises(ValueError):
        m.torque(1.5, 0.0)


# --- battery draw ----------------------------------------------------------------------------------------------------------


def test_actuator_battery_draw_at_no_load_and_at_stall_matches_the_datasheet_power():
    """At no load the motor takes 12 V x 0.2 A = 2.4 W, at stall 12 V x 5.5 A = 66 W (datasheet currents at the rated voltage)."""
    model, data, drives = load(motor_rig(supply=True))
    runtime = DriveRuntime(model, drives)
    assert runtime.supplies["b1"].remaining == CELL_ENERGY
    run(model, data, runtime, {"drive": 1.0}, 0.5)  # spin up
    before = runtime.energy["drive"]
    run(model, data, runtime, {"drive": 1.0}, 1.0)
    assert runtime.energy["drive"] - before == pytest.approx(VOLT * I_NL * 1.0, rel=1e-6)

    model, data, drives = load(motor_rig(limits=(-1.0, 0.0), supply=True))
    runtime = DriveRuntime(model, drives)
    run(model, data, runtime, {"drive": 1.0}, 0.5)
    before = runtime.energy["drive"]
    run(model, data, runtime, {"drive": 1.0}, 1.0)
    assert runtime.energy["drive"] - before == pytest.approx(VOLT * I_STALL * 1.0, rel=1e-4)
    assert runtime.supplies["b1"].remaining == pytest.approx(CELL_ENERGY - runtime.energy["drive"], rel=1e-12)


def test_actuator_an_empty_battery_drives_nothing():
    """1e-4 of a full cell is 4.212 J: at stall (66 W) it lasts 63.8 ms, then the motor gives no torque."""
    model, data, drives = load(motor_rig(limits=(-1.0, 0.0), supply=True, charge=1e-4))
    runtime = DriveRuntime(model, drives)
    run(model, data, runtime, {"drive": 1.0}, 0.06)
    assert motor_torque(model, data) > 0.99 * T0 and not runtime.supplies["b1"].empty
    run(model, data, runtime, {"drive": 1.0}, 0.01)
    assert runtime.supplies["b1"].empty
    assert runtime.energy["drive"] == pytest.approx(CELL_ENERGY * 1e-4, rel=1e-12)
    run(model, data, runtime, {"drive": 1.0}, 0.01)
    assert data.actuator_force[0] == 0.0  # the driving part is gone; only the back-EMF damping is left


def test_actuator_motor_without_current_specs_cannot_be_metered():
    bare = MOTOR.model_copy(update={"specs": tuple(s for s in MOTOR.specs if s.name != "stall_current")})
    proj = motor_rig(supply=True, motor=bare)
    with pytest.raises(CompileError, match="stall_current") as e:
        compile_drives(build_body_tree(proj))
    assert e.value.code is CompileErrorCode.NO_CURRENT and e.value.parts == (MOTOR.id,) and e.value.actuators == ("drive",)


# --- spring-damper on a slider ---------------------------------------------------------------------------------------------


BASE = block_part("base", (0.1, 0.1, 0.02), (("top", "spring_end", (0.0, 0.0, 0.01)),))
WEIGHT = block_part("weight", (0.1, 0.1, 0.05), (("bottom", "spring_end", (0.0, 0.0, -0.025)),))  # 0.5 kg at 1000 kg/m^3
HALF = 0.009525  # the spring's end snap points, half its free length (part-spring-damper.md)


def spring_rig(damping=None, joint_kind="slider"):
    """Base block `base` on the ground (clamped), spring `sp` standing on it (welded at `end_a`), 0.5 kg block `mass` on slider
    `susp` at the spring's top `end_b` (+Z). Joined snap points meet."""
    params = () if damping is None else (("damping", damping, "N*s/m"),)
    instances = [instance("base", "base", (0.0, 0.0, 0.01), material="mat"), instance("sp", SPRING.id, (0.0, 0.0, 0.02 + HALF), parameters=params),
                 instance("mass", "weight", (0.0, 0.0, 0.02 + 2 * HALF + 0.025), material="mat")]
    joints = [joint("weld", "fixed", ("base", "top"), ("sp", "end_a")), joint("susp", joint_kind, ("sp", "end_b"), ("mass", "bottom"))]
    return project([BASE, WEIGHT, SPRING], instances, joints)


def crossings(t, x):
    """Times x crosses 0 downward, linearly interpolated."""
    out = []
    for i in range(1, len(x)):
        if x[i - 1] > 0.0 >= x[i]:
            out.append(t[i - 1] + (t[i] - t[i - 1]) * x[i - 1] / (x[i - 1] - x[i]))
    return out


def oscillate(damping, seconds=0.3):
    model, data, drives = load(spring_rig(damping))
    model.opt.integrator = mujoco.mjtIntegrator.mjINT_RK4
    model.opt.timestep = 1e-5
    d = dof(model, "susp")
    data.qpos[model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "susp")]] = 1e-3
    t, x = [], []
    for _ in range(round(seconds / model.opt.timestep)):
        mujoco.mj_step(model, data)
        t.append(data.time)
        x.append(float(data.qpos[d]))
    return drives, np.array(t), np.array(x)


def test_actuator_spring_damper_part_sets_the_slider_stiffness_and_damping():
    model, _, drives = load(spring_rig())
    (s,) = drives.springs
    assert (s.joint, s.instance, s.stiffness, s.damping) == ("susp", "sp", K_SPRING, C_SPRING)
    j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "susp")
    assert model.jnt_stiffness[j] == K_SPRING and model.dof_damping[dof(model, "susp")] == C_SPRING
    assert model.qpos_spring[model.jnt_qposadr[j]] == 0.0  # force 0 at the saved pose


def test_actuator_spring_period_in_mujoco_matches_the_hand_calculation():
    """0.5 kg block on k = 5990 N/m, no damping: T = 2 pi sqrt(0.5 / 5990) = 57.4052 ms (part-spring-damper.md)."""
    _, t, x = oscillate(0.0)
    m = 0.1 * 0.1 * 0.05 * 1000.0
    hand = 2 * math.pi * math.sqrt(m / K_SPRING)
    assert hand == pytest.approx(57.4052e-3, rel=1e-6)
    c = crossings(t, x)
    assert len(c) >= 4
    assert np.diff(c) == pytest.approx(hand, rel=1e-5)


def test_actuator_damped_spring_in_mujoco_matches_the_hand_calculation():
    """Default 20 N*s/m on 0.5 kg: zeta = 0.182727, T_d = 58.3883 ms, each peak 0.31106 x the one before."""
    _, t, x = oscillate(None)
    c = crossings(t, x)
    assert np.diff(c) == pytest.approx(58.3883e-3, rel=1e-5)
    peaks = [x[i] for i in range(1, len(x) - 1) if x[i - 1] < x[i] >= x[i + 1] and x[i] > 0]
    ratios = np.array(peaks[1:4]) / np.array(peaks[0:3])
    assert ratios == pytest.approx(0.31106, rel=1e-3)


def test_actuator_spring_damper_on_a_hinge_is_a_compile_error():
    with pytest.raises(CompileError, match="exactly one slider") as e:
        compile_drives(build_body_tree(spring_rig(joint_kind="hinge")))
    assert e.value.code is CompileErrorCode.SPRING_JOINT and e.value.instances == ("sp",) and e.value.joints == ("susp",)


def test_actuator_spring_damper_at_no_moving_joint_is_a_compile_error():
    proj = project([BASE, SPRING], [instance("base", "base", (0.0, 0.0, 0.01), material="mat"), instance("sp", SPRING.id, (0.0, 0.0, 0.02 + HALF))],
                   [joint("weld", "fixed", ("base", "top"), ("sp", "end_a"))])
    with pytest.raises(CompileError, match="found none") as e:
        compile_drives(build_body_tree(proj))
    assert e.value.code is CompileErrorCode.SPRING_JOINT


def test_actuator_motor_on_a_part_without_curve_or_on_a_slider_is_a_compile_error():
    plain = block_part("block", (0.1, 0.1, 0.1), (("top", "plug", (0.0, 0.0, 0.05)), ("bottom", "plug", (0.0, 0.0, -0.05))))
    proj = project([plain], [instance("a", "block", (0.0, 0.0, 0.05), material="mat"), instance("b", "block", (0.0, 0.0, 0.15), material="mat")],
                   [joint("j", "hinge", ("a", "top"), ("b", "bottom"))], [{"id": "drive", "kind": "motor", "instance": "a", "joint": "j"}])
    with pytest.raises(CompileError) as e:  # no torque-speed curve on a part with no role: refused by build_body_tree (X-01d)
        compile_drives(build_body_tree(proj))
    assert e.value.code is CompileErrorCode.NO_CURVE
    rig = motor_rig()
    slid = project([MOTOR, WHEEL], [i.model_dump(mode="json") for i in rig.design.instances],
                   [{**rig.design.joints[0].model_dump(mode="json", exclude_none=True), "kind": "slider"}],
                   [{"id": "drive", "kind": "motor", "instance": "m1", "joint": "axle"}], materials=(POM,))
    with pytest.raises(CompileError, match="drives a hinge") as e:
        compile_drives(build_body_tree(slid))
    assert e.value.code is CompileErrorCode.MOTOR_JOINT and e.value.actuators == ("drive",)


def test_actuator_mjcf_with_drives_is_byte_identical_for_the_same_project():
    a, b = motor_rig(supply=True), motor_rig(supply=True)
    ta, tb = build_body_tree(a), build_body_tree(b)
    assert to_mjcf(ta, drives=compile_drives(ta)) == to_mjcf(tb, drives=compile_drives(tb))


# --- the wheel rolling down an incline on three planets (B-03a's carried DoD) ------------------------------------------------

THETA = math.radians(30.0)


def rolling(planet):
    """The B-03a wheel (POM) alone, standing on the ground plane z = 0 (lowest point on it), axis (its y) horizontal, at rest. The
    30 deg incline is the planet's gravity turned by 30 deg about the wheel's axis, `g (sin, 0, -cos)`: in the plane's frame that
    is the same problem as the plane tilted under vertical gravity, and the wheel stays a grounded assembly. Friction is the compiled
    contact (X-01e) of the project's planet: min(tread 0.7, that planet's nominal ground friction) = the ground's nominal, each planet
    its own (asserted below). The model's gravity is the compiled planet's, turned."""
    r = WHEEL.parameters[0].default.value / 2  # diameter 0.1 m
    proj = project([WHEEL], [instance("w1", WHEEL.id, (0.0, 0.0, r), material=POM.id)], materials=(POM,), planet=planet)
    tree = build_body_tree(proj)
    xml = to_mjcf(tree, drives=compile_drives(tree))
    model = mujoco.MjModel.from_xml_string(xml)
    ground = load_body(planet).ground_friction.value.value
    assert model.geom_friction[0][0] == ground and min(model.geom_friction[i][0] for i in range(model.ngeom)) == ground
    g = load_body(planet).gravity.value
    assert tuple(model.opt.gravity) == (0.0, 0.0, -g)  # compiled for this planet (W-03a)
    model.opt.gravity[:] = (g * math.sin(THETA), 0.0, -g * math.cos(THETA))
    data = mujoco.MjData(model)
    t, v, spin = [], [], []
    for _ in range(round(1.0 / model.opt.timestep)):
        mujoco.mj_step(model, data)
        t.append(data.time)
        v.append(float(data.qvel[0]))  # downhill: +x
        spin.append(float(data.qvel[4]))  # angular velocity about y (rolling towards +x)
    body = tree.root
    k = body.inertia[1] / (body.mass * r * r)  # I_yy / (m r^2) of the compiled wheel
    return g, k, r, np.array(t), np.array(v), np.array(spin)


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_actuator_wheel_rolls_down_an_incline_at_g_sin_theta_over_one_plus_k(planet):
    g, k, r, t, v, spin = rolling(planet)
    assert k == pytest.approx(0.4625, rel=1e-3)  # parts-wheel.md: I_yy / (m R^2) of the seven discs
    hand = g * math.sin(THETA) / (1.0 + k)
    window = t >= 0.2  # after the contact has settled
    slope = np.polyfit(t[window], v[window], 1)[0]
    assert slope == pytest.approx(hand, rel=2e-3)  # measured: -0.115 % (earth), -0.045 % (mars), -0.020 % (moon)
    # rolling, not sliding: the contact point is at rest, v = omega r
    assert spin[-1] * r == pytest.approx(v[-1], rel=2e-3)  # measured: 0.16 %, 0.047 %, 0.007 % of v
