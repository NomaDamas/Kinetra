"""X-03b: static load of every joint at rest against its break threshold, against the hand calculation of a cantilever.

Every expected number is written out from the free-body diagram of the hanging side (force = its weight m g, moment about the
joint point = sum of m_i g x lever arm_i; for a cantilever with a uniform arm and a tip load, M = w L^2 / 2 + P L), not read
back from the code under test. g is read from `data/bodies` through `load_body`, not from the compiled tree. Dimensions,
densities, poses and declared thresholds are fixtures chosen by the test (`사용자 선언`), not part data.
"""

from __future__ import annotations

import math

import pytest
from test_body_tree import SRC, box, instance, joint, part, project, q, snap
from test_break_threshold import length, material

from kinetra_core import JointKind, Project
from kinetra_core.bodies import load_body

from kinetra_engine.break_threshold import LoadMode, SolidCircle, critical_load
from kinetra_engine.compiler import build_body_tree
from kinetra_engine.statics import LoadStatus, static_loads

RHO = 1000.0  # kg/m^3, the material of test_body_tree
G_EARTH = load_body("earth").gravity.value

# --- the cantilever: a 0.4 m cube wall (64 kg) on the ground, a 0.6 x 0.1 x 0.1 m arm (6 kg) welded to its +x face at
# height 0.3 m, a 0.1 m cube tip load (1 kg) welded to the arm's end. Arm root at x = 0.2, arm end at x = 0.8.
M_WALL, M_ARM, M_TIP = 0.4**3 * RHO, 0.6 * 0.1 * 0.1 * RHO, 0.1**3 * RHO
L, TIP_HALF = 0.6, 0.05


def cantilever(root_kind="fixed", root_axis=None, root_threshold=None, tip_threshold=None, tip_reversed=False, planet="earth"):
    parts = [
        part("wall", [box("w", 0.4, 0.4, 0.4)], [snap("face", (0.2, 0.0, 0.1))]),
        part("arm", [box("a", L, 0.1, 0.1)], [snap("root", (-L / 2, 0.0, 0.0)), snap("end", (L / 2, 0.0, 0.0))]),
        part("tip", [box("t", 0.1, 0.1, 0.1)], [snap("s1", (-TIP_HALF, 0.0, 0.0))]),
    ]
    instances = [instance("wall", "wall", (0, 0, 0.2)), instance("arm", "arm", (0.2 + L / 2, 0, 0.3)), instance("tip", "tip", (0.2 + L + TIP_HALF, 0, 0.3))]
    root = joint("root", root_kind, ("wall", "face"), ("arm", "root"), axis=root_axis)
    tip = joint("tip", "fixed", ("tip", "s1"), ("arm", "end")) if tip_reversed else joint("tip", "fixed", ("arm", "end"), ("tip", "s1"))
    for j, threshold in ((root, root_threshold), (tip, tip_threshold)):
        if threshold is not None:
            j["break_threshold"] = threshold
    data = project(parts, instances, [root, tip]).model_dump(mode="json")
    data["world"]["planet"] = planet
    return build_body_tree(Project.model_validate(data))


def newton(value):
    return q(value, "N")


def grounded_pair(kind="fixed"):
    """Two 8 kg, 0.2 m cubes side by side, joined at (0.1, 0, 0.1), each with a 0.2 m square ground patch."""
    parts = [part("cube", [box("c", 0.2, 0.2, 0.2)], [snap("px", (0.1, 0, 0)), snap("nx", (-0.1, 0, 0))])]
    instances = [instance("l", "cube", (0, 0, 0.1)), instance("r", "cube", (0.2, 0, 0.1))]
    axis = (0, 1, 0) if kind == "hinge" else None
    return project(parts, instances, [joint("weld", kind, ("l", "px"), ("r", "nx"), axis=axis)])


def test_static_load_cantilever_matches_the_hand_shear_and_bending_moment():
    s = static_loads(cantilever())
    assert s.planet == "earth" and s.gravity == G_EARTH and s.caveats == ()
    root, tip = s.joint("root"), s.joint("tip")
    # root: the arm and the tip load hang on it. Shear = (w L + P) = (6 + 1) g; moment about the root
    # M = w L^2 / 2 + P (L + half the tip cube) = g (6 x 0.3 + 1 x 0.65) = 2.45 g, about +y (gravity at +x of the root).
    assert root.status is LoadStatus.HANGING and root.free_side == "b" and root.free_instances == ("arm", "tip")
    assert root.point == pytest.approx((0.2, 0.0, 0.3), abs=1e-12)
    assert root.free_mass == pytest.approx(M_ARM + M_TIP, rel=1e-12)
    assert root.force == pytest.approx((0.0, 0.0, -(M_ARM + M_TIP) * G_EARTH), rel=1e-12)
    assert root.load == pytest.approx(7.0 * G_EARTH, rel=1e-12)
    m_root = G_EARTH * (M_ARM * L / 2 + M_TIP * (L + TIP_HALF))
    assert m_root == pytest.approx(2.45 * G_EARTH, rel=1e-12)
    assert root.moment == pytest.approx((0.0, m_root, 0.0), rel=1e-12, abs=1e-12)
    # tip joint: only the 1 kg cube hangs on it, lever 0.05 m
    assert tip.free_instances == ("tip",) and tip.load == pytest.approx(M_TIP * G_EARTH, rel=1e-12)
    assert tip.moment == pytest.approx((0.0, M_TIP * G_EARTH * TIP_HALF, 0.0), rel=1e-12, abs=1e-12)
    # no threshold: never breaks, no margin
    assert root.threshold is None and root.margin is None and root.utilization is None and not root.exceeds
    assert root.axis is None and root.axis_load is None
    assert root.force_interval is None and root.moment_interval is None and root.load_interval is None


def test_static_load_margin_to_a_threshold_and_an_exceeded_one():
    # root: A36 pin d = 1 mm in single shear (X-04a): V = 0.577 x 248.2e6 x pi (0.0005)^2 = 112.48 N > 7 g = 68.65 N.
    # tip: a declared 5 N threshold, below the 1 kg cube's 9.81 N.
    pin = critical_load(material("steel-a36"), SolidCircle(length(0.001)), LoadMode.SHEAR)
    v_pin = 0.577 * 248.2e6 * math.pi * 0.0005**2
    assert pin.value == pytest.approx(v_pin, rel=1e-12)
    s = static_loads(cantilever(root_threshold=pin.quantity.model_dump(mode="json"), tip_threshold=newton(5.0)))
    root, tip = s.joint("root"), s.joint("tip")
    assert root.threshold == pytest.approx(v_pin, rel=1e-12)
    assert root.margin == pytest.approx(v_pin - 7.0 * G_EARTH, rel=1e-12) and root.margin > 0
    assert root.utilization == pytest.approx(7.0 * G_EARTH / v_pin, rel=1e-12) and not root.exceeds
    assert tip.margin == pytest.approx(5.0 - G_EARTH, rel=1e-12) and tip.margin < 0 and tip.exceeds
    assert s.exceeding == (tip,)


def test_static_load_thresholded_welds_compile_to_separate_bodies_with_the_same_loads():
    # X-04b: a fixed joint with a break_threshold does not weld, so wall, arm and tip are three bodies instead of one.
    # The joint loads are a free-body result over instances and must not change with that grouping.
    welded = cantilever()
    split = cantilever(root_threshold=newton(1000.0), tip_threshold=newton(1000.0))
    assert len(welded.bodies) == 1 and len(split.bodies) == 3
    a, b = static_loads(welded), static_loads(split)
    for jid in ("root", "tip"):
        assert b.joint(jid).status is LoadStatus.HANGING
        assert b.joint(jid).force == pytest.approx(a.joint(jid).force, rel=1e-12)
        assert b.joint(jid).moment == pytest.approx(a.joint(jid).moment, rel=1e-12, abs=1e-12)
    assert b.joint("root").load == pytest.approx(7.0 * G_EARTH, rel=1e-12)
    assert b.joint("root").margin == pytest.approx(1000.0 - 7.0 * G_EARTH, rel=1e-12)
    assert b.tipover.margin == pytest.approx(a.tipover.margin, rel=1e-12) and b.tipover.stable


def test_static_load_threshold_equal_to_the_load_does_not_exceed():
    # BreakThreshold is the load *above* which the joint releases
    s = static_loads(cantilever(tip_threshold=newton(M_TIP * G_EARTH)))
    assert s.joint("tip").margin == pytest.approx(0.0, abs=1e-12) and not s.joint("tip").exceeds


def test_static_load_follows_the_planet_gravity():
    g_moon = load_body("moon").gravity.value
    s = static_loads(cantilever(planet="moon"))
    assert s.gravity == g_moon and g_moon != G_EARTH
    assert s.joint("root").load == pytest.approx(7.0 * g_moon, rel=1e-12)
    assert s.joint("root").moment[1] == pytest.approx(2.45 * g_moon, rel=1e-12)


def test_static_load_free_side_may_be_the_joints_a_side():
    s = static_loads(cantilever(tip_reversed=True))
    tip = s.joint("tip")
    assert tip.free_side == "a" and tip.free_instances == ("tip",)
    assert tip.point == pytest.approx((0.85 - TIP_HALF, 0.0, 0.3), abs=1e-12)
    assert tip.load == pytest.approx(M_TIP * G_EARTH, rel=1e-12)


def test_static_load_hinge_names_the_moment_its_free_axis_cannot_hold():
    # a hinge about +y at the root: the 2.45 g N m bending moment is about its axis, so a motor or limit must hold all of it
    pitch = static_loads(cantilever(root_kind="hinge", root_axis=(0, 1, 0))).joint("root")
    assert pitch.kind is JointKind.HINGE and pitch.axis == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
    assert pitch.axis_load == pytest.approx(2.45 * G_EARTH, rel=1e-12)
    assert pitch.load == pytest.approx(7.0 * G_EARTH, rel=1e-12)
    # a hinge about +x (along the arm): gravity makes no moment about it
    roll = static_loads(cantilever(root_kind="hinge", root_axis=(1, 0, 0))).joint("root")
    assert roll.axis_load == pytest.approx(0.0, abs=1e-12)


def test_static_load_both_sides_on_the_ground_is_indeterminate_and_floating_has_none():
    # Ground and weld share the weight, so there is still no unique point result.
    pair = grounded_pair()
    weld = static_loads(build_body_tree(pair)).joint("weld")
    assert weld.status is LoadStatus.INDETERMINATE and "부정정" in weld.reason
    assert weld.load is None and weld.force is None and weld.margin is None and not weld.exceeds
    assert weld.load_interval is not None and weld.force_interval is not None and weld.moment_interval is not None
    # the same pair resting only on a terrain step: nothing on z = 0
    on_step = pair.model_dump(mode="json")
    for inst in on_step["design"]["instances"]:
        inst["pose"]["position"]["z"] += 1.0
    on_step["world"]["terrain_props"] = [{"kind": "step", "id": "kerb", "placement": {"x": 0.1, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC},
                                          "length": q(1.0), "width": q(1.0), "height": q(1.0)}]
    s = static_loads(build_body_tree(Project.model_validate(on_step)))
    assert s.joint("weld").status is LoadStatus.UNSUPPORTED and s.joint("weld").load is None and s.caveats == ()
    assert s.joint("weld").force_interval is None and s.joint("weld").load_interval is None


def test_static_load_indeterminate_intervals_match_hand_reaction_bounds():
    # Hand calculation for grounded_pair: m_a = m_b = 8 kg, W = 16g, p = (0.1, 0, 0.1), and the b-side
    # contact coordinates relative to p are dx = {0, 0.2}, dy = {-0.1, 0.1}, dz = -0.1. The global normal
    # sum on b lies in [0, W], so F_z = R_b,z - 8g lies in [-8g, 8g]. Each tangent component is bounded by
    # mu W, where mu is the smaller of default geom friction 1 and Earth ground friction.
    mu = load_body("earth").ground_friction.value.value
    s = static_loads(build_body_tree(grounded_pair()))
    weld = s.joint("weld")
    assert s.tolerance == 1e-6  # numerical placement/contact tolerance [m], not a force tolerance
    assert weld.force is None and weld.moment is None and weld.load is None
    fx, fy, fz = weld.force_interval
    for component in (fx, fy):
        assert component.lower == pytest.approx(-16 * mu * G_EARTH, rel=1e-12)
        assert component.upper == pytest.approx(16 * mu * G_EARTH, rel=1e-12)
    assert fz.lower == pytest.approx(-8 * G_EARTH, rel=1e-12)
    assert fz.upper == pytest.approx(8 * G_EARTH, rel=1e-12)
    # M_x = sum(dy R_z - dz R_y); M_y = sum(dz R_x - dx R_z) + 0.1*8g;
    # M_z = sum(dx R_y - dy R_x). Independent cone-component relaxation gives the following conservative bounds.
    mx, my, mz = weld.moment_interval
    assert mx.lower == pytest.approx(-1.6 * (1 + mu) * G_EARTH, rel=1e-12)
    assert mx.upper == pytest.approx(1.6 * (1 + mu) * G_EARTH, rel=1e-12)
    assert my.lower == pytest.approx(-(2.4 + 1.6 * mu) * G_EARTH, rel=1e-12)
    assert my.upper == pytest.approx((0.8 + 1.6 * mu) * G_EARTH, rel=1e-12)
    assert mz.lower == pytest.approx(-4.8 * mu * G_EARTH, rel=1e-12)
    assert mz.upper == pytest.approx(4.8 * mu * G_EARTH, rel=1e-12)
    assert weld.load_interval.lower == pytest.approx(0.0, abs=1e-12)
    expected_max = G_EARTH * math.sqrt(2 * (16 * mu) ** 2 + 8**2)
    assert weld.load_interval.upper == pytest.approx(expected_max, rel=1e-12)
    # The +y hinge projection is exactly the hand-bounded M_y interval, still not a unique axis torque.
    hinge = static_loads(build_body_tree(grounded_pair("hinge"))).joint("weld")
    assert hinge.axis_load is None
    assert hinge.axis_load_interval.lower == pytest.approx(my.lower, rel=1e-12)
    assert hinge.axis_load_interval.upper == pytest.approx(my.upper, rel=1e-12)


def test_static_load_says_when_the_design_is_not_at_rest():
    # X-03a's overhang: base 0.2 m (4 kg) with a 0.6 m arm (6 kg) welded on top, centre of mass 0.08 m beyond the base
    parts = [part("base", [box("b", 0.2, 0.2, 0.1)], [snap("top", (0, 0, 0.05))]), part("arm", [box("a", 0.6, 0.1, 0.1)], [snap("s1", (-0.3, 0, -0.05))])]
    instances = [instance("base", "base", (0, 0, 0.05)), instance("arm", "arm", (0.3, 0, 0.15))]
    s = static_loads(build_body_tree(project(parts, instances, [joint("weld", "fixed", ("base", "top"), ("arm", "s1"))])))
    assert not s.tipover.stable and len(s.caveats) == 1 and "정지해 있지 않다" in s.caveats[0]
    weld = s.joint("weld")
    assert weld.load == pytest.approx(6.0 * G_EARTH, rel=1e-12)
    assert weld.moment == pytest.approx((0.0, 6.0 * G_EARTH * 0.3, 0.0), rel=1e-12, abs=1e-12)


def test_static_load_states_its_assumptions():
    s = static_loads(cantilever())
    assert any("중력뿐" in a for a in s.assumptions) and any("부정정" in a for a in s.assumptions)
    assert any("굽힘 모멘트" in a for a in s.assumptions)
