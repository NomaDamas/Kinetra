"""X-06: resultant thrust, thrust line and torque about the centre of mass at one moment of the schedule.

Expected numbers are hand calculations, not read back from the code under test. Parts, poses and the X-01c constants are
those of `test_thrust.py` (VACCO 48003040: 2.0 lbf, 0.0267 lbm/s, 7 ms linear opening ramp, `인용`; the library `tank` at
its defaults). Every nozzle points straight down or up, so the force is along z and the torque about the centre of mass
`c` of a thruster at `p` is `(p - c) x (0, 0, f) = ((p - c)_y f, -(p - c)_x f, 0)`: only the x and y of `c` enter. The
tank, the plate and the thruster parts are each symmetric about their own vertical axis, so `c_x = sum m_i x_i / sum m_i`
with the thrusters at x = +-0.1 m and the rest at x = 0.
"""

from __future__ import annotations

import pytest
from gltf_samples import library_part
from test_thrust import (
    CAPACITY, IDENT, M_PLATE, M_TANK, M_THRUSTER, MZ, PLATE, PLATE_A, PLATE_T, PLATE_Z, SRC, T_OPEN, TANK_ON_PLATE_Z, V_E, F,
    entry, face, instance, jet, on_plate, project, rocket, weld,
)

from kinetra_core import Badge, Project
from kinetra_engine.compiler import compile_thrust
from kinetra_engine.statics import thrust_center
from kinetra_engine.statics.thrust_center import MAX_THRUST_NOTE, PROPELLANT_DRAWN_NOTE, PROPELLANT_FULL_NOTE

M_ON_PLATE = M_TANK + M_PLATE + CAPACITY  # tank (full) and plate, both centred on x = 0


def thruster(id, supply=None):
    return {"id": id, "kind": "thruster", "instance": f"jet-{id}", **({"supply": supply} if supply else {})}


def test_thrust_center_one_thruster_through_the_centre_of_mass():
    """Tank on a thruster on its axis. At t = 2 s (past the 7 ms ramp) the thrust is F up through the centre of mass: no
    torque, and the line is the common axis x = y = 0. The tank has given F (2 - T_OPEN / 2) / v_e kg."""
    model = compile_thrust(rocket([entry("e", "main", 0.0, 10.0, 1.0)]))
    r = thrust_center(model, 2.0)
    drawn = F * (2.0 - T_OPEN / 2) / V_E
    assert r.basis == "schedule" and r.time == 2.0 and r.grade == "L0" and r.grade_label == "해석 계산"
    assert r.propellant == {"tank": pytest.approx(CAPACITY - drawn, rel=1e-12)} and r.propellant_note == PROPELLANT_DRAWN_NOTE
    assert r.mass == pytest.approx(M_TANK + M_THRUSTER + CAPACITY - drawn, rel=1e-12)
    assert r.force == pytest.approx((0.0, 0.0, F), abs=1e-12)
    assert r.torque == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert r.center[:2] == pytest.approx((0.0, 0.0), abs=1e-12) and r.moment_arm == pytest.approx(0.0, abs=1e-12)
    assert r.direction == pytest.approx((0.0, 0.0, 1.0), abs=1e-15)
    # past the ramp the thrust is the rated 2.0 lbf of the datasheet: the spec's badge
    assert [(f.actuator, f.badge, f.badge_ko) for f in r.thrusters] == [("main", Badge.CITE, "인용")]
    assert r.input_badges == (Badge.CITE,)
    # half way up the opening ramp the thrust is half, read from the ramp's shape, which the library part estimates
    ramp = thrust_center(model, T_OPEN / 2)
    assert ramp.force[2] == pytest.approx(F / 2, rel=1e-12) and ramp.input_badges == (Badge.ESTIMATE,)


def test_thrust_center_one_thruster_off_to_the_side():
    """One thruster under the plate at x = +0.1 m, command 0.5, drawing on the tank. At t = 4 s: thrust F / 2, the tank has
    given (F / 2)(4 - T_OPEN / 2) / v_e, c_x = 0.1 M_thruster / m, torque_y = -(0.1 - c_x) F / 2, and the thrust line is
    the vertical through the nozzle (x = 0.1) at distance 0.1 - c_x from the centre of mass."""
    proj = on_plate([("jet-main", "under-a")], [thruster("main", "tank")], [entry("e", "main", 0.0, 10.0, 0.5)])
    r = thrust_center(compile_thrust(proj), 4.0)
    drawn = 0.5 * F * (4.0 - T_OPEN / 2) / V_E
    m = M_ON_PLATE + M_THRUSTER - drawn
    cx = PLATE_A * M_THRUSTER / m
    assert r.mass == pytest.approx(m, rel=1e-12)
    assert r.center_of_mass[:2] == pytest.approx((cx, 0.0), abs=1e-12)
    assert r.force == pytest.approx((0.0, 0.0, F / 2), abs=1e-12)
    assert r.torque == pytest.approx((0.0, -(PLATE_A - cx) * F / 2, 0.0), rel=1e-9, abs=1e-12)
    assert r.center == pytest.approx((PLATE_A, 0.0, r.center_of_mass[2]), abs=1e-12)
    assert r.moment_arm == pytest.approx(PLATE_A - cx, rel=1e-9)
    assert r.axial_torque == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert r.thrusters[0].command == 0.5 and not r.thrusters[0].tank_empty


def test_thrust_center_two_symmetric_thrusters_and_only_the_ones_on():
    """Thrusters at x = +-0.1 under the plate, not metered, so c_x = 0. Both on: 2F through x = 0, no torque. Only `a` on
    (`b` starts at 5 s): F at x = 0.1, torque_y = -0.1 F, not the sum of both. At 5 s + T_OPEN / 2 `b` is half way up its
    ramp: 1.5 F, torque_y = -0.1 F + 0.1 F / 2, line at x = (0.1 F - 0.1 F / 2) / 1.5 F."""
    jets = [("jet-a", "under-a"), ("jet-b", "under-b")]
    both = thrust_center(compile_thrust(on_plate(jets, [thruster("a"), thruster("b")], [entry("ea", "a", 0.0, 10.0, 1.0), entry("eb", "b", 0.0, 10.0, 1.0)])), 1.0)
    assert both.center_of_mass[:2] == pytest.approx((0.0, 0.0), abs=1e-12)
    assert both.force == pytest.approx((0.0, 0.0, 2 * F), abs=1e-12)
    assert both.torque == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert both.center[:2] == pytest.approx((0.0, 0.0), abs=1e-12)

    model = compile_thrust(on_plate(jets, [thruster("a"), thruster("b")], [entry("ea", "a", 0.0, 10.0, 1.0), entry("eb", "b", 5.0, 10.0, 1.0)]))
    one = thrust_center(model, 1.0)
    assert [f.actuator for f in one.thrusters] == ["a"]
    assert one.force == pytest.approx((0.0, 0.0, F), abs=1e-12)
    assert one.torque == pytest.approx((0.0, -PLATE_A * F, 0.0), rel=1e-12, abs=1e-12)
    assert one.center[:2] == pytest.approx((PLATE_A, 0.0), abs=1e-12) and one.moment_arm == pytest.approx(PLATE_A, rel=1e-12)

    ramp = thrust_center(model, 5.0 + T_OPEN / 2)
    assert [f.thrust for f in ramp.thrusters] == pytest.approx([F, F / 2], rel=1e-12)
    assert ramp.force == pytest.approx((0.0, 0.0, 1.5 * F), abs=1e-12)
    assert ramp.torque == pytest.approx((0.0, -PLATE_A * F + PLATE_A * F / 2, 0.0), rel=1e-12, abs=1e-12)
    assert ramp.center[0] == pytest.approx((PLATE_A * F - PLATE_A * F / 2) / (1.5 * F), rel=1e-12)


TOP_B_Z = 2 * MZ + PLATE_T  # top face of the plate
PLATE2 = {**PLATE, "id": "plate2", "snap_points": [*PLATE["snap_points"], face("top-b", (-PLATE_A, 0.0, PLATE_T / 2), IDENT)]}


def test_thrust_center_opposed_pair_is_a_couple_with_no_center():
    """`a` under the plate at x = +0.1 pushes up, `b` on top at x = -0.1 points its nozzle up and pushes down. Same F at
    t = 1 s: the resultant is 0 and the torque is the couple (0, -0.1 F - 0.1 F, 0) about any point. No thrust centre."""
    instances = [instance("tank", "tank", at=(0.0, 0.0, TANK_ON_PLATE_Z), material="al6061-t6"),
                 instance("plate", "plate2", at=(0.0, 0.0, PLATE_Z), material="al6061-t6"),
                 jet("jet-a", PLATE_A),
                 instance("jet-b", "thruster-vacco-48003040", at=(-PLATE_A, 0.0, TOP_B_Z + MZ), quat=IDENT, material="steel-a36")]
    joints = [weld("wt", ("plate", "top"), ("tank", "bottom")), weld("wa", ("plate", "under-a"), ("jet-a", "mount")),
              weld("wb", ("plate", "top-b"), ("jet-b", "mount"))]
    proj = project(instances, joints, [thruster("a"), thruster("b")], [entry("ea", "a", 0.0, 10.0, 1.0), entry("eb", "b", 0.0, 10.0, 1.0)],
                   extra_parts=[PLATE2])
    r = thrust_center(compile_thrust(proj), 1.0)
    assert [f.direction[2] for f in r.thrusters] == pytest.approx([1.0, -1.0], abs=1e-15)
    assert r.force == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert r.torque == pytest.approx((0.0, -2 * PLATE_A * F, 0.0), rel=1e-12, abs=1e-12)
    assert r.couple_only and r.center is None and r.direction is None and r.moment_arm is None and r.axial_torque is None


def test_thrust_center_without_a_schedule_is_every_thruster_at_max_with_full_tanks():
    jets = [("jet-a", "under-a"), ("jet-b", "under-b")]
    model = compile_thrust(on_plate(jets, [thruster("a", "tank"), thruster("b")], []))
    r = thrust_center(model)
    assert r.basis == "max_thrust" and r.time is None
    assert r.basis_note == MAX_THRUST_NOTE == "스케줄 없음: 모든 추력기 최대 추력 기준"
    assert r.propellant_note == PROPELLANT_FULL_NOTE and "추진제 가득 기준" in r.propellant_note
    assert r.propellant == {"tank": pytest.approx(CAPACITY, rel=1e-15)}
    assert [(f.actuator, f.command) for f in r.thrusters] == [("a", 1.0), ("b", 1.0)]
    assert r.force == pytest.approx((0.0, 0.0, 2 * F), abs=1e-12)  # the curve tops out at the rated 2.0 lbf
    assert r.mass == pytest.approx(M_ON_PLATE + 2 * M_THRUSTER, rel=1e-12)


def test_thrust_center_needs_a_time_when_there_is_a_schedule():
    model = compile_thrust(rocket([entry("e", "main", 0.0, 1.0, 1.0)]))
    with pytest.raises(ValueError, match="give the time"):
        thrust_center(model)
    with pytest.raises(ValueError, match="not negative"):
        thrust_center(model, -1.0)
    assert thrust_center(model, 1.0).thrusters == ()  # entries are [start, end): off at 1 s
    assert thrust_center(model, 1.0).force == (0.0, 0.0, 0.0) and thrust_center(model, 1.0).couple_only


def test_thrust_center_schedule_with_only_command_zero_is_zero_thrust_not_max():
    """Thruster entries that all command 0 are a schedule (every thruster off), not "no schedule": the result is 0 thrust at
    `t` on the schedule basis, never every thruster at max. Only a design with no thruster entry at all gets the max basis."""
    jets = [("jet-a", "under-a"), ("jet-b", "under-b")]
    off = compile_thrust(on_plate(jets, [thruster("a", "tank"), thruster("b")], [entry("ea", "a", 0.0, 10.0, 0.0), entry("eb", "b", 0.0, 10.0, 0.0)]))
    r = thrust_center(off, 1.0)
    assert r.basis == "schedule" and r.basis_note != MAX_THRUST_NOTE and r.propellant_note == PROPELLANT_DRAWN_NOTE
    assert r.thrusters == () and r.force == (0.0, 0.0, 0.0) and r.torque == (0.0, 0.0, 0.0) and r.couple_only
    assert r.propellant == {"tank": CAPACITY}  # nothing drawn
    with pytest.raises(ValueError, match="give the time"):
        thrust_center(off)
    none = thrust_center(compile_thrust(on_plate(jets, [thruster("a", "tank"), thruster("b")], [])))
    assert none.basis == "max_thrust" and none.basis_note == MAX_THRUST_NOTE
    assert none.force == pytest.approx((0.0, 0.0, 2 * F), abs=1e-12)


def test_thrust_center_empty_tank_gives_no_thrust():
    """Burning at command 1 empties the full tank at v_e x capacity / F + T_OPEN / 2 = 163.5 s (X-01c)."""
    model = compile_thrust(rocket([entry("e", "main", 0.0, 1000.0, 1.0)]))
    t_empty = V_E * CAPACITY / F + T_OPEN / 2
    before, after = thrust_center(model, t_empty - 0.1), thrust_center(model, t_empty + 0.1)
    assert before.force[2] == pytest.approx(F, rel=1e-12) and not before.thrusters[0].tank_empty
    assert before.propellant["tank"] == pytest.approx(0.1 * F / V_E, rel=1e-6)
    assert after.thrusters[0].tank_empty and after.thrusters[0].thrust == 0.0 and after.propellant == {"tank": 0.0}
    assert after.mass == pytest.approx(M_TANK + M_THRUSTER, rel=1e-12)


def test_thrust_center_carries_a_declared_thrust_badge():
    """The same thruster with its rated thrust and curve declared by the user: the result says `사용자 선언`."""
    part = library_part("thruster-vacco-48003040").model_dump(mode="json")
    for q in [nc["curve"] for nc in part["curves"]] + [s for s in part["specs"] if s["name"] == "rated_thrust"]:
        q["badge"], q["source"] = "declared", SRC
    data = project([jet("jet", 0.0)], [], [{"id": "main", "kind": "thruster", "instance": "jet"}], [entry("e", "main", 0.0, 1.0, 1.0)]).model_dump(mode="json")
    data["design"]["parts"] = [part if p["id"] == part["id"] else p for p in data["design"]["parts"]]
    model = compile_thrust(Project.model_validate(data))
    for t in (T_OPEN / 2, 0.5):  # on the ramp and steady
        r = thrust_center(model, t)
        assert r.input_badges == (Badge.DECLARED,) and r.thrusters[0].badge_ko == "사용자 선언"
    assert r.center[:2] == pytest.approx((0.0, 0.0), abs=1e-12) and r.force == pytest.approx((0.0, 0.0, F), abs=1e-12)
