"""X-01c: thrust from the control schedule, propellant drawn from the tank and the body's mass falling with it.

Expected numbers are hand calculations, not read back from the code under test. The parts are the library's
(`thruster-vacco-48003040`: 2.0 lbf at 0.0267 lbm/s, 7 ms opening ramp; `tank` at its default size, 1000 kg/m^3 placeholder
propellant density, `docs/architecture/parts-battery-tank.md`); the poses, schedules and fills are declared by the test. The
straight-line check is the rocket equation: with the thrust `F(t)` and the mass flow `F(t) / v_e`, `m dv = F dt = -v_e dm`, so
`dv = v_e ln(m0 / m1)` whatever the shape of the thrust curve.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest
from gltf_samples import catalog_material, library_part

from kinetra_core import Project, ProjectIncomplete, check_placement
from kinetra_engine.compiler import CompileError, CompileErrorCode, ThrustRun, compile_thrust, to_mjcf

SRC = {"ref": "X-01c test fixture: value chosen by the test", "locator": "test_thrust.py"}
LBF, LBM = 4.4482216152605, 0.45359237  # exact definitions
F = 2.0 * LBF  # N, VACCO 48003040 datasheet
FLOW = 0.0267 * LBM  # kg/s, same datasheet
V_E = F / FLOW  # m/s, effective exhaust velocity
T_OPEN = 0.007  # s, the cited opening response; the curve ramps linearly over it
M_THRUSTER = 0.83 * LBM  # kg: the part's shape is sized so steel-a36 gives the datasheet weight (parts-thruster.md)
RHO_AL = 2700.0  # al6061-t6 in the B-07 catalog

# tank at its defaults: radius 0.06, length 0.2, wall 3 mm, neck r 0.012 x 0.03, cap 0.03 x 0.03 x 0.015, skirt r 0.048 x 0.01
R, L = 0.06, 0.2
V_INSIDE = math.pi * (R - 0.003) ** 2 * (L - 0.006)
V_SHELL = math.pi * R * R * L - V_INSIDE + math.pi * 0.012**2 * 0.03 + 0.03 * 0.03 * 0.015 + math.pi * (0.8 * R) ** 2 * 0.01
M_TANK = RHO_AL * V_SHELL
CAPACITY = 1000.0 * V_INSIDE  # 1.98016 kg

FLIP_X = {"x": 1.0, "y": 0.0, "z": 0.0, "w": 0.0}  # 180 deg about x: the nozzle's exhaust (+Z of the part) points down
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
MZ = 0.04729059031466532  # the thruster's mount and nozzle snap points sit at -/+ this on its z axis (and so do its ends)
TANK_BOTTOM_Z = -0.01 - 0.5 * L  # the tank's bottom snap point and the underside of its skirt, in the tank frame

# Every fixture stands on the ground (z = 0) with its joined snap points meeting (`check_placement` finds nothing): the
# thruster turned over, its nozzle end on the ground and its mount under what carries it. The MJCF has no ground plane, so
# standing there changes nothing in the run; it keeps the fixtures valid projects.
JET_Z = MZ  # thruster origin: nozzle end at z = 0, mount at 2 MZ
TANK_ON_JET_Z = 2 * MZ - TANK_BOTTOM_Z  # tank origin with its bottom on the thruster's mount
PLATE_T, PLATE_A = 0.01, 0.1  # test plate: 0.3 x 0.1 x 0.01 m, thrusters under it at x = +-0.1 m
M_PLATE = RHO_AL * 0.3 * 0.1 * PLATE_T
PLATE_Z = 2 * MZ + PLATE_T / 2
TANK_ON_PLATE_Z = 2 * MZ + PLATE_T - TANK_BOTTOM_Z


def ax(v):
    return {"offset": v, "terms": []}


def face(id, at, quat):
    return {"id": id, "kind": "face", "accepts": ["face"], "badge": "declared", "source": SRC,
            "position": {"x": ax(at[0]), "y": ax(at[1]), "z": ax(at[2])}, "orientation": quat}


PLATE = {"id": "plate", "name": "Test plate", "parameters": [],
         "snap_points": [face("top", (0.0, 0.0, PLATE_T / 2), IDENT), face("under-a", (PLATE_A, 0.0, -PLATE_T / 2), FLIP_X),
                         face("under-b", (-PLATE_A, 0.0, -PLATE_T / 2), FLIP_X)],
         "shape": {"badge": "declared", "source": SRC, "components": [{"id": "p", "operation": "add", "primitive": {"kind": "box", "size_x": ax(0.3),
                   "size_y": ax(0.1), "size_z": ax(PLATE_T)}, "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}}


def instance(id, part, at=(0.0, 0.0, 0.0), quat=None, material=None, params=()):
    return {"id": id, "part": part, "material": material, "parameters": [{"name": n, "value": v, "unit": u, "badge": "declared", "source": SRC} for n, v, u in params],
            "pose": {"badge": "declared", "source": SRC, "position": {"x": at[0], "y": at[1], "z": at[2]}, "orientation": quat or IDENT}}


def weld(id, a, b):
    return {"id": id, "kind": "fixed", "a": {"instance": a[0], "snap_point": a[1]}, "b": {"instance": b[0], "snap_point": b[1]}}


def entry(id, actuator, start, end, command):
    return {"type": "actuate", "id": id, "actuator": actuator, "start": start, "end": end, "command": command, "badge": "declared", "source": SRC}


def project(instances, joints, actuators, entries, extra_parts=()):
    materials = [catalog_material("al6061-t6").model_dump(mode="json"), catalog_material("steel-a36").model_dump(mode="json")]
    parts = [library_part("tank").model_dump(mode="json"), library_part("thruster-vacco-48003040").model_dump(mode="json"), *extra_parts]
    proj = Project.model_validate({"design": {"materials": materials, "parts": parts, "instances": instances, "joints": joints,
                                              "actuators": actuators, "schedule": {"entries": entries}}, "world": {"planet": "earth"}})
    assert check_placement(proj) == ()  # snaps meet, nothing overlaps or floats
    return proj


def jet(id, x=0.0):
    return instance(id, "thruster-vacco-48003040", at=(x, 0.0, JET_Z), quat=FLIP_X, material="steel-a36")


def rocket(entries, tank_params=()):
    """Tank on a thruster on its axis, exhaust down: the force is +z through the centre of mass."""
    return project([instance("tank", "tank", at=(0.0, 0.0, TANK_ON_JET_Z), material="al6061-t6", params=tank_params), jet("jet")],
                   [weld("w", ("jet", "mount"), ("tank", "bottom"))],
                   [{"id": "main", "kind": "thruster", "instance": "jet", "supply": "tank"}], entries)


def on_plate(jets, actuators, entries, tank_params=()):
    """Tank on the plate, thrusters under it at x = +a (`under-a`) and -a (`under-b`)."""
    instances = [instance("tank", "tank", at=(0.0, 0.0, TANK_ON_PLATE_Z), material="al6061-t6", params=tank_params),
                 instance("plate", "plate", at=(0.0, 0.0, PLATE_Z), material="al6061-t6")]
    joints = [weld("wt", ("plate", "top"), ("tank", "bottom"))]
    for jid, snap in jets:
        instances.append(jet(jid, PLATE_A if snap == "under-a" else -PLATE_A))
        joints.append(weld(f"w-{jid}", ("plate", snap), (jid, "mount")))
    return project(instances, joints, actuators, entries, extra_parts=[PLATE])


def start(proj, dt):
    model = compile_thrust(proj)
    m = mujoco.MjModel.from_xml_string(to_mjcf(model.tree))
    m.opt.gravity[:] = 0.0  # no gravity: the straight line of the issue
    m.opt.timestep = dt
    d = mujoco.MjData(m)
    return model, m, d, ThrustRun(model, m, d)


def run_until(run, d, t_end):
    steps = []
    while d.time < t_end - 1e-9:
        steps.append(run.step())
    return steps


def test_thrust_initial_body_carries_the_dry_parts_and_the_full_tank():
    model, m, d, run = start(rocket([]), 0.01)
    row = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "jet")  # the body takes the smallest instance id
    assert m.body_mass[row] == pytest.approx(M_TANK + M_THRUSTER + CAPACITY, rel=1e-12)
    assert run.supplies["tank"].remaining == pytest.approx(CAPACITY, rel=1e-12)
    store = model.stores[0]
    # the inside is centred on the tank's origin; the body frame is the thruster's, turned 180 deg about x
    assert store.centroid == pytest.approx((0.0, 0.0, -(TANK_ON_JET_Z - JET_Z)), abs=1e-12)
    # per kg, a solid cylinder r = 0.057, h = 0.194: (3 r^2 + h^2) / 12 about x and y, r^2 / 2 about z
    r_in, h_in = R - 0.003, L - 0.006
    assert store.inertia_per_kg[:3] == pytest.approx(((3 * r_in**2 + h_in**2) / 12, (3 * r_in**2 + h_in**2) / 12, r_in**2 / 2), rel=1e-12)


def test_thrust_empty_tank_gives_back_the_compiled_dry_inertia():
    """With no propellant the in-place mass write must reproduce what MuJoCo's compiler made of the MJCF's fullinertia."""
    model, m, d, run = start(rocket([]), 0.01)
    row = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "jet")
    compiled = mujoco.MjModel.from_xml_string(to_mjcf(model.tree))

    def tensor(mm):
        rmat = np.zeros(9)
        mujoco.mju_quat2Mat(rmat, mm.body_iquat[row])
        rmat = rmat.reshape(3, 3)
        return rmat @ np.diag(mm.body_inertia[row]) @ rmat.T

    run._load({"tank": 0.0}, ["jet"])
    assert m.body_mass[row] == pytest.approx(compiled.body_mass[row], rel=1e-14)
    assert m.body_ipos[row] == pytest.approx(compiled.body_ipos[row], abs=1e-15)
    assert tensor(m) == pytest.approx(tensor(compiled), rel=1e-12, abs=1e-15)


def test_thrust_zero_gravity_straight_line_burn_to_empty_matches_the_rocket_equation():
    """Command 1 from 0 to 200 s: the tank empties first. dv = v_e ln(m0 / m_dry), the empty time from the impulse."""
    m0 = M_TANK + M_THRUSTER + CAPACITY
    m_dry = M_TANK + M_THRUSTER
    model, m, d, run = start(rocket([entry("burn", "main", 0.0, 200.0, 1.0)]), 0.01)
    steps = run_until(run, d, 200.0)

    impulse = math.fsum(s.thrusters[0].impulse for s in steps)
    used = math.fsum(s.thrusters[0].propellant for s in steps)
    assert run.supplies["tank"].remaining == 0.0
    assert used == pytest.approx(CAPACITY, rel=1e-12)
    assert impulse == pytest.approx(V_E * CAPACITY, rel=1e-12)
    # the burn lasts until F (t - T_OPEN / 2) = v_e x capacity
    t_empty = V_E * CAPACITY / F + T_OPEN / 2  # = capacity / flow + 3.5 ms = 163.50 s
    last_full = max(s.time for s in steps if s.thrusters[0].satisfied == 1.0 and s.thrusters[0].impulse > 0.0)
    partial = [s for s in steps if 0.0 < s.thrusters[0].satisfied < 1.0]
    assert len(partial) == 1 and partial[0].time == pytest.approx(last_full + 0.01)
    assert partial[0].time <= t_empty < partial[0].time + 0.01
    assert all(s.thrusters[0].impulse == 0.0 for s in steps if s.time > partial[0].time)

    vz = d.qvel[2]
    rocket_eq = V_E * math.log(m0 / m_dry)
    assert vz == pytest.approx(rocket_eq, rel=1e-8)
    assert vz > 1.3 * V_E * CAPACITY / m0  # the constant-mass answer (legacy) is far off: the mass ratio is m0 / m_dry
    assert d.qvel[:2] == pytest.approx((0.0, 0.0), abs=1e-9) and d.qvel[3:] == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    row = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "jet")
    assert m.body_mass[row] == pytest.approx(m_dry, rel=1e-12)


@pytest.mark.parametrize("dt", [0.01, 0.002])
def test_thrust_half_command_for_thirty_seconds_matches_the_hand_calculation(dt):
    """Command 0.5 over [0, 30) s: J = 0.5 F (30 - T_OPEN / 2), m_used = J / v_e, dv = v_e ln(m0 / (m0 - m_used))."""
    m0 = M_TANK + M_THRUSTER + CAPACITY
    j = 0.5 * F * (30.0 - T_OPEN / 2)
    used = j / V_E
    model, m, d, run = start(rocket([entry("half", "main", 0.0, 30.0, 0.5)]), dt)
    steps = run_until(run, d, 40.0)
    assert math.fsum(s.thrusters[0].impulse for s in steps) == pytest.approx(j, rel=1e-12)
    assert CAPACITY - run.supplies["tank"].remaining == pytest.approx(used, rel=1e-9)
    assert max(s.thrusters[0].thrust for s in steps) == pytest.approx(0.5 * F, rel=1e-12)
    assert d.qvel[2] == pytest.approx(V_E * math.log(m0 / (m0 - used)), rel=1e-9)
    # coasting from 30 s to 40 s at that speed: no thrust, no draw
    assert all(s.thrusters[0].impulse == 0.0 and s.thrusters[0].propellant == 0.0 for s in steps if s.time >= 30.0)


def test_thrust_openings_follow_the_schedule():
    """Touching entries keep the valve open (one ramp); a gap or a command-0 entry closes it (the next one ramps again)."""
    proj = rocket([entry("a", "main", 0.0, 1.0, 1.0), entry("b", "main", 1.0, 2.0, 0.5), entry("off", "main", 2.0, 3.0, 0.0),
                   entry("c", "main", 3.0, 4.0, 1.0), entry("d", "main", 5.0, 6.0, 1.0)])
    th = compile_thrust(proj).thrusters[0]
    assert [(o.entry, o.on) for o in th.openings] == [("a", 0.0), ("b", 0.0), ("c", 3.0), ("d", 5.0)]
    ramped = F * (1.0 - T_OPEN / 2)  # one second from the valve opening
    assert th.impulse(0.0, 2.0) == pytest.approx(ramped + 0.5 * F * 1.0, rel=1e-12)  # b does not ramp again
    assert th.impulse(2.0, 3.0) == 0.0
    assert th.impulse(3.0, 6.0) == pytest.approx(2.0 * ramped, rel=1e-12)
    assert th.impulse(0.0, 6.0) == pytest.approx(th.impulse(0.0, 2.0) + th.impulse(2.0, 3.5) + th.impulse(3.5, 6.0), rel=1e-12)


def test_thrust_two_thrusters_share_one_tank_and_stop_together():
    """Two thrusters at +-x under a plate on one quarter-filled tank: the tank feeds both until empty, the last step at the
    same fraction for both."""
    fill = 0.25
    proj = on_plate([("jet-a", "under-a"), ("jet-b", "under-b")],
                    [{"id": "a", "kind": "thruster", "instance": "jet-a", "supply": "tank"}, {"id": "b", "kind": "thruster", "instance": "jet-b", "supply": "tank"}],
                    [entry("ea", "a", 0.0, 100.0, 1.0), entry("eb", "b", 0.0, 100.0, 1.0)], tank_params=[("initial_fill", fill, "1")])
    model, m, d, run = start(proj, 0.01)
    m0 = M_TANK + M_PLATE + 2 * M_THRUSTER + fill * CAPACITY
    assert run.body_mass("jet-a")[0] == pytest.approx(m0, rel=1e-12)
    steps = run_until(run, d, 100.0)
    partial = [s for s in steps if 0.0 < s.thrusters[0].satisfied < 1.0]
    assert len(partial) == 1 and partial[0].thrusters[0].satisfied == partial[0].thrusters[1].satisfied
    # two at once empty it in half the time: 2 F (t - T_OPEN / 2) = v_e x fill x capacity
    assert partial[0].time <= V_E * fill * CAPACITY / (2 * F) + T_OPEN / 2 < partial[0].time + 0.01
    assert run.supplies["tank"].remaining == 0.0
    assert d.qvel[2] == pytest.approx(V_E * math.log(m0 / (m0 - fill * CAPACITY)), rel=1e-8)
    assert d.qvel[3:] == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)  # symmetric: no turn


def test_thrust_acts_at_the_nozzle_off_axis_thrust_turns_the_body():
    """One unmetered thruster under the plate at x = +0.1 m. The body frame is the thruster's (smallest id), turned over:
    the nozzle is at (0, 0, MZ) and the force (0, 0, -F) there. The moment about the centre of mass c is
    (nozzle - c) x force, whose y part is -c_x F; fixed in the body and about its principal y axis (the assembly is symmetric
    in y), so omega_y = -c_x J / I_yy exactly. Nothing is drawn, so the mass and inertia stay."""
    proj = on_plate([("jet", "under-a")], [{"id": "main", "kind": "thruster", "instance": "jet"}], [entry("e", "main", 0.0, 0.5, 1.0)])
    model, m, d, run = start(proj, 0.001)
    steps = run_until(run, d, 0.5)
    assert run.supplies["tank"].remaining == CAPACITY  # not metered: the tank stays full
    mass, com, inertia = run.body_mass("jet")
    assert mass == pytest.approx(M_TANK + M_PLATE + M_THRUSTER + CAPACITY, rel=1e-12)
    assert com[0] < -0.05  # the tank and plate sit at -0.1 m along the body's x
    j = F * (0.5 - T_OPEN / 2)
    assert math.fsum(s.thrusters[0].impulse for s in steps) == pytest.approx(j, rel=1e-12)
    assert inertia[3] == pytest.approx(0.0, abs=1e-15) and inertia[5] == pytest.approx(0.0, abs=1e-15)  # y is principal
    omega_body = d.qvel[3:6]  # a free joint's angular velocity is in the body's own frame (its linear velocity in the world's)
    assert omega_body[1] == pytest.approx(-com[0] * j / inertia[1], rel=1e-9)
    assert omega_body[0] == pytest.approx(0.0, abs=1e-12) and omega_body[2] == pytest.approx(0.0, abs=1e-12)


def test_thrust_actuator_on_a_part_with_no_role_is_a_no_curve_compile_error():
    block = {"id": "block", "name": "block", "parameters": [], "snap_points": [{"id": "s", "kind": "plug", "accepts": ["plug"], "badge": "declared", "source": SRC,
             "position": {"x": {"offset": 0.0, "terms": []}, "y": {"offset": 0.0, "terms": []}, "z": {"offset": 0.0, "terms": []}}, "orientation": IDENT}],
             "shape": {"badge": "declared", "source": SRC, "components": [{"id": "b", "operation": "add", "primitive": {"kind": "box", "size_x": {"offset": 0.1, "terms": []},
             "size_y": {"offset": 0.1, "terms": []}, "size_z": {"offset": 0.1, "terms": []}}, "position": {"x": {"offset": 0.0, "terms": []}, "y": {"offset": 0.0, "terms": []}, "z": {"offset": 0.0, "terms": []}}}]}}
    proj = project([instance("blk", "block", at=(0.0, 0.0, 0.05), material="steel-a36")], [], [{"id": "main", "kind": "thruster", "instance": "blk"}], [], extra_parts=[block])
    with pytest.raises(CompileError) as e:
        compile_thrust(proj)
    assert e.value.code is CompileErrorCode.NO_CURVE
    assert e.value.instances == ("blk",) and e.value.parts == ("block",) and e.value.actuators == ("main",)


def test_thrust_compile_refuses_a_project_with_a_missing_definition():
    proj = rocket([])
    data = proj.model_dump(mode="json")
    data["design"]["parts"] = [p for p in data["design"]["parts"] if p["id"] != "thruster-vacco-48003040"]
    with pytest.raises(ProjectIncomplete):
        compile_thrust(Project.model_validate(data))
