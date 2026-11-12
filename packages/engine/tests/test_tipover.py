"""X-03a: support polygon, centre-of-mass projection and tip-over angle, against hand calculation.

Every expected number is written out from the textbook rule (centre of mass = sum m c / sum m; tip-over angle =
atan(distance from the centre-of-mass projection to the nearest support edge / centre-of-mass height)), not read back from
the code under test. Dimensions, densities and poses are fixtures declared by the test (`사용자 선언`), not part data.
"""

from __future__ import annotations

import math

import pytest
from test_body_tree import ROT_X90, ROT_Z90, SRC, box, cyl, instance, joint, part, project, q, snap, sphere

from kinetra_core import Project

from kinetra_engine.compiler import build_body_tree
from kinetra_engine.statics import RIM_SEGMENTS, TipoverError, tipover

RHO = 1000.0  # kg/m^3, the material of test_body_tree


def xy(points):
    return sorted((round(s.point[0], 12) + 0.0, round(s.point[1], 12) + 0.0) for s in points)


# --- hand calculation 1: a block standing on its base ---------------------------------------------------------------


def test_tipover_block_on_its_base_matches_the_hand_angle():
    # 0.4 x 0.2 x 0.6 m block, base on z = 0: centre of mass (0, 0, 0.3), support rectangle x +-0.2, y +-0.1.
    # Nearest edge 0.1 m away (the long sides): angle = atan(0.1 / 0.3) = 18.43 deg; the short sides atan(0.2 / 0.3).
    tree = build_body_tree(project([part("blk", [box("b", 0.4, 0.2, 0.6, at=(0, 0, 0.3))])], [instance("i", "blk")]))
    t = tipover(tree)
    assert t.mass == pytest.approx(0.4 * 0.2 * 0.6 * RHO, rel=1e-12)
    assert t.center_of_mass == pytest.approx((0.0, 0.0, 0.3), abs=1e-15)
    assert t.kind == "polygon" and xy(t.polygon) == [(-0.2, -0.1), (-0.2, 0.1), (0.2, -0.1), (0.2, 0.1)]
    assert t.margin == pytest.approx(0.1, rel=1e-12)
    assert t.tipover_angle == pytest.approx(math.atan(0.1 / 0.3), rel=1e-12)
    assert math.degrees(t.tipover_angle) == pytest.approx(18.4349488, rel=1e-8)
    assert sorted(e.angle for e in t.edges) == pytest.approx(sorted([math.atan(1 / 3)] * 2 + [math.atan(2 / 3)] * 2), rel=1e-12)
    assert t.stable and t.approximations == ()


def test_tipover_turned_and_moved_block_keeps_its_angle_and_turns_its_polygon():
    # the same block placed at (5, -3, 0) turned 90 deg about z: the long sides now face x
    tree = build_body_tree(project([part("blk", [box("b", 0.4, 0.2, 0.6, at=(0, 0, 0.3))])], [instance("i", "blk", (5, -3, 0), ROT_Z90)]))
    t = tipover(tree)
    assert t.com_projection == pytest.approx((5.0, -3.0), abs=1e-12)
    assert xy(t.polygon) == [(4.9, -3.2), (4.9, -2.8), (5.1, -3.2), (5.1, -2.8)]
    assert t.tipover_angle == pytest.approx(math.atan(0.1 / 0.3), rel=1e-9)


# --- hand calculation 2: a four-wheel cart with an off-centre payload, wheels on hinges --------------------------------

WHEEL_R, WHEEL_W = 0.15, 0.1
WHEELS = {"wfl": (0.5, 0.35), "wfr": (0.5, -0.35), "wrl": (-0.5, 0.35), "wrr": (-0.5, -0.35)}


def cart():
    # chassis 1.0 x 0.6 x 0.1 m centred at z = 0.25; wheels r 0.15, width 0.1, axles along y at (+-0.5, +-0.35, 0.15);
    # an 0.2 m cube payload welded on top at (0.3, 0.2, 0.4).
    chassis_snaps = [snap(w, (x, y, -0.1)) for w, (x, y) in WHEELS.items()] + [snap("pay", (0.3, 0.2, 0.15))]
    parts = [part("chassis", [box("c", 1.0, 0.6, 0.1)], chassis_snaps), part("wheel", [cyl("w", WHEEL_R, WHEEL_W)]), part("payload", [box("p", 0.2, 0.2, 0.2)])]
    instances = [instance("chassis", "chassis", (0, 0, 0.25)), instance("payload", "payload", (0.3, 0.2, 0.4))]
    instances += [instance(w, "wheel", (x, y, WHEEL_R), ROT_X90) for w, (x, y) in WHEELS.items()]
    joints = [joint(f"h_{w}", "hinge", ("chassis", w), (w, "s1"), axis=(0, 1, 0)) for w in WHEELS]
    joints.append(joint("weld", "fixed", ("chassis", "pay"), ("payload", "s1")))
    return project(parts, instances, joints)


def test_tipover_four_wheel_cart_matches_the_hand_rollover_angle():
    t = tipover(build_body_tree(cart()))
    m_chassis, m_payload, m_wheel = 1.0 * 0.6 * 0.1 * RHO, 0.2**3 * RHO, math.pi * WHEEL_R**2 * WHEEL_W * RHO
    total = m_chassis + m_payload + 4 * m_wheel  # 60 + 8 + 4 x 7.0686 = 96.27 kg
    com = (m_payload * 0.3 / total, m_payload * 0.2 / total, (m_chassis * 0.25 + m_payload * 0.4 + 4 * m_wheel * 0.15) / total)
    assert t.mass == pytest.approx(total, rel=1e-12)
    assert t.center_of_mass == pytest.approx(com, rel=1e-12)
    # each wheel touches along a line across its width: support rectangle x +-0.5, y +-(0.35 + 0.05)
    assert t.kind == "polygon" and xy(t.polygon) == [(-0.5, -0.4), (-0.5, 0.4), (0.5, -0.4), (0.5, 0.4)]
    assert {s.instance for s in t.polygon} == set(WHEELS)
    # nearest edge: the left side y = 0.4, the payload pulls the centre towards it
    assert t.margin == pytest.approx(0.4 - com[1], rel=1e-9)
    assert t.tipover_angle == pytest.approx(math.atan((0.4 - com[1]) / com[2]), rel=1e-9)
    by_side = {(round(e.a.point[0], 9), round(e.b.point[0], 9)): e.angle for e in t.edges}
    assert by_side[(0.5, 0.5)] == pytest.approx(math.atan((0.5 - com[0]) / com[2]), rel=1e-9)  # pitch over the front axle
    assert by_side[(-0.5, -0.5)] == pytest.approx(math.atan((0.5 + com[0]) / com[2]), rel=1e-9)
    assert t.stable and t.approximations == ()


# --- hand calculation 3: an overhanging arm pulls the centre of mass outside the base ---------------------------------


def test_tipover_overhang_outside_the_base_is_unstable_with_the_hand_margin():
    # base 0.2 x 0.2 x 0.1 m (4 kg) centred at (0, 0, 0.05); arm 0.6 x 0.1 x 0.1 m (6 kg) welded on it, centred at (0.3, 0, 0.15).
    # centre of mass x = 6 x 0.3 / 10 = 0.18, z = (4 x 0.05 + 6 x 0.15) / 10 = 0.11: 0.08 m beyond the edge x = 0.1.
    parts = [part("base", [box("b", 0.2, 0.2, 0.1)], [snap("top", (0, 0, 0.05))]), part("arm", [box("a", 0.6, 0.1, 0.1)], [snap("s1", (-0.3, 0, -0.05))])]
    instances = [instance("base", "base", (0, 0, 0.05)), instance("arm", "arm", (0.3, 0, 0.15))]
    t = tipover(build_body_tree(project(parts, instances, [joint("weld", "fixed", ("base", "top"), ("arm", "s1"))])))
    assert t.center_of_mass == pytest.approx((0.18, 0.0, 0.11), rel=1e-12, abs=1e-15)
    assert xy(t.polygon) == [(-0.1, -0.1), (-0.1, 0.1), (0.1, -0.1), (0.1, 0.1)]  # the arm does not reach the ground
    assert t.margin == pytest.approx(-0.08, rel=1e-9)
    assert t.tipover_angle == pytest.approx(math.atan2(-0.08, 0.11), rel=1e-9)
    assert not t.stable


# --- a standing cylinder: the disk is counted as its inscribed polygon, and says so -----------------------------------


def test_tipover_standing_cylinder_uses_the_inscribed_polygon_and_names_the_bound():
    r, length = 0.1, 0.4
    t = tipover(build_body_tree(project([part("can", [cyl("c", r, length, at=(0, 0, length / 2))])], [instance("i", "can")])))
    assert t.kind == "polygon" and len(t.polygon) == RIM_SEGMENTS
    apothem = r * math.cos(math.pi / RIM_SEGMENTS)  # distance from the centre to an edge of the inscribed regular polygon
    assert t.margin == pytest.approx(apothem, rel=1e-9)
    assert t.tipover_angle == pytest.approx(math.atan(apothem / (length / 2)), rel=1e-9)
    assert t.tipover_angle < math.atan(r / (length / 2))  # never more than the true disk's angle
    assert len(t.approximations) == 1 and f"{RIM_SEGMENTS}각형" in t.approximations[0]


# --- degenerate supports, floating, below the ground ----------------------------------------------------------------


def test_tipover_point_and_line_contacts_are_never_stable():
    ball = tipover(build_body_tree(project([part("ball", [sphere("s", 0.1)])], [instance("i", "ball", (0, 0, 0.1))])))
    assert ball.kind == "point" and ball.margin == pytest.approx(0.0, abs=1e-15) and not ball.stable
    lying = tipover(build_body_tree(project([part("rod", [cyl("c", 0.05, 0.4)])], [instance("i", "rod", (0, 0, 0.05), ROT_X90)])))
    assert lying.kind == "segment" and xy(lying.polygon) == [(0.0, -0.2), (0.0, 0.2)]
    assert lying.margin == pytest.approx(0.0, abs=1e-12) and not lying.stable and lying.edges == ()


def test_tipover_design_resting_only_on_a_terrain_prop_has_no_ground_support_and_a_buried_one_is_refused():
    # a block on top of a 1 m step: placed, not floating, but terrain props are not supports of this check (stated)
    on_step = project([part("blk", [box("b", 0.1, 0.1, 0.1)])], [instance("i", "blk", (0, 0, 1.05))]).model_dump(mode="json")
    on_step["world"]["terrain_props"] = [{"kind": "step", "id": "kerb", "placement": {"x": 0.0, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC},
                                          "length": q(1.0), "width": q(1.0), "height": q(1.0)}]
    rest = tipover(build_body_tree(Project.model_validate(on_step)))
    assert rest.kind == "none" and rest.margin is None and rest.tipover_angle is None and not rest.stable
    assert any("지형 소품" in a for a in rest.assumptions)
    with pytest.raises(TipoverError) as err:
        tipover(build_body_tree(project([part("blk", [box("b", 0.1, 0.1, 0.1)])], [instance("i", "blk", (0, 0, 0.01))])))
    assert err.value.instances == ("i",)


def test_tipover_states_its_assumptions():
    t = tipover(build_body_tree(cart()))
    assert any("결합" in a for a in t.assumptions) and any("마찰" in a for a in t.assumptions)
