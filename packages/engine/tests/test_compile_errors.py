"""X-01d: a compile error names the part, the instance, the joint and the actuator it is about, with a code and a reason.

Fixtures are the X-01a ones (`test_body_tree.py`): values chosen by the test (`사용자 선언`), not part data.
"""

from __future__ import annotations

import math

import pytest
from test_body_tree import EXAMPLES, IDENT, MATERIAL, ROT_X90, SRC, box, instance, joint, part, snap

from kinetra_core import BlockedOperation, Project, ProjectIncomplete, check_placement
from kinetra_engine.compiler import AXIS_TOLERANCE, CompileError, CompileErrorCode, build_body_tree
from kinetra_engine.compiler.checks import check_axes


def project(parts, instances, joints=(), actuators=()):
    return Project.model_validate(
        {"design": {"materials": [MATERIAL], "parts": list(parts), "instances": list(instances), "joints": list(joints), "actuators": list(actuators)},
         "world": {"planet": "earth"}}
    )


def cube(id, snaps):
    """A 0.1 m cube resting on the ground (bottom face at z = 0 when the instance is at z = 0)."""
    return part(id, [box("b", 0.1, 0.1, 0.1, at=(0.0, 0.0, 0.05))], snaps)


BASE = cube("base", [snap("top", (0.0, 0.0, 0.1))])
ARM = cube("arm", [snap("foot", (0.0, 0.0, 0.0))])


def stack(arm_at=(0.0, 0.0, 0.1), kind="fixed", axis=None, arm_quat=None):
    """`arm` stands on `base`: the arm's foot meets the base's top at (0, 0, 0.1) when `arm_at` is (0, 0, 0.1)."""
    return project([BASE, ARM], [instance("lower", "base"), instance("upper", "arm", arm_at, arm_quat)],
                   [joint("mount", kind, ("lower", "top"), ("upper", "foot"), axis=axis)])


def compile_error(p) -> CompileError:
    with pytest.raises(CompileError) as e:
        build_body_tree(p)
    return e.value


def test_compile_error_baseline_the_placed_stack_compiles():
    for kind, axis in (("fixed", None), ("hinge", (0, 0, 1)), ("slider", (0, 0, 1))):
        tree = build_body_tree(stack(kind=kind, axis=axis))
        assert {i.instance for i in tree.instances} == {"lower", "upper"}


def test_compile_error_snap_points_that_do_not_meet_name_the_joint_both_instances_and_parts():
    p = stack(arm_at=(0.0, 0.0, 0.1005))  # 0.5 mm above the base's top: the joint would hold it there
    e = compile_error(p)
    assert e.code is CompileErrorCode.SNAP_MISMATCH
    assert e.joints == ("mount",) and e.instances == ("lower", "upper") and e.parts == ("base", "arm") and e.actuators == ()
    assert "0.0005 m apart" in str(e) and "'mount'" in str(e)
    # the validator's own sentence: one placement rule for edits (C-02c) and for compiling
    (finding,) = [r for r in check_placement(p) if r.code.value == "invalid_snap"]
    assert str(e) == finding.message
    # within the validator's tolerance (1 micrometre) it is the same point
    build_body_tree(stack(arm_at=(0.0, 0.0, 0.1 + 0.5e-6)))


def test_compile_error_snap_kinds_that_do_not_accept_each_other():
    socket = {"id": "foot", "kind": "socket", "accepts": ["socket"], "badge": "declared", "source": SRC,
              "position": {"x": {"offset": 0.0, "terms": []}, "y": {"offset": 0.0, "terms": []}, "z": {"offset": 0.0, "terms": []}},
              "orientation": IDENT}
    p = project([BASE, cube("arm", [socket])], [instance("lower", "base"), instance("upper", "arm", (0.0, 0.0, 0.1))],
                [joint("mount", "fixed", ("lower", "top"), ("upper", "foot"))])
    e = compile_error(p)
    assert e.code is CompileErrorCode.SNAP_MISMATCH and e.joints == ("mount",) and e.parts == ("base", "arm")
    assert "not compatible" in str(e)


def test_compile_error_hinge_axis_the_two_snap_frames_disagree_on():
    # the arm turned 90 degrees about x: +z of its foot is -y in the world, +z of the base's top is +z
    e = compile_error(stack(kind="hinge", axis=(0, 0, 1), arm_quat=ROT_X90))
    assert e.code is CompileErrorCode.AXIS_MISMATCH
    assert e.joints == ("mount",) and e.instances == ("lower", "upper") and e.parts == ("base", "arm")
    assert "(0, 0, 1)" in str(e) and "(0, -1, 0)" in str(e)
    # turned 180 degrees about x the foot faces the other way: the same line, opposite direction, compiles
    flip = {"x": 1.0, "y": 0.0, "z": 0.0, "w": 0.0}
    upside = project([BASE, cube("arm", [snap("foot", (0.0, 0.0, 0.1))])],
                     [instance("lower", "base"), instance("upper", "arm", (0.0, 0.0, 0.2), flip)],  # spans z 0.1 to 0.2
                     [joint("mount", "hinge", ("lower", "top"), ("upper", "foot"), axis=(0, 0, 1))])
    tree = build_body_tree(upside)
    assert tree.body("upper").joint.id == "mount"
    # a slider whose axis is off by more than the tolerance (sine of the angle) is refused, within it is not
    tilt = 10 * AXIS_TOLERANCE
    tilted = {"x": math.sin(tilt / 2), "y": 0.0, "z": 0.0, "w": math.cos(tilt / 2)}
    assert compile_error(stack(kind="slider", axis=(0, 0, 1), arm_quat=tilted)).code is CompileErrorCode.AXIS_MISMATCH
    tilt = AXIS_TOLERANCE / 10
    build_body_tree(stack(kind="slider", axis=(0, 0, 1), arm_quat={"x": math.sin(tilt / 2), "y": 0.0, "z": 0.0, "w": math.cos(tilt / 2)}))


def test_compile_error_the_example_cars_axes_are_one_line_from_both_snap_frames():
    # the right motor of the four-wheel car is turned 180 degrees: its drive axis is -Y from `a`, +Y from `b` (the same line)
    for name in ("Project.four-wheel-car", "Project.rocket-car-skeleton"):
        p = Project.model_validate_json((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        assert any(j.kind.value == "hinge" for j in p.design.joints)
        check_axes(p.design)


def test_compile_error_an_assembly_in_the_air_floats():
    lifted = project([BASE, ARM], [instance("lower", "base", (0.0, 0.0, 1.0)), instance("upper", "arm", (0.0, 0.0, 1.1))],
                     [joint("mount", "fixed", ("lower", "top"), ("upper", "foot"))])
    e = compile_error(lifted)
    assert e.code is CompileErrorCode.FLOATING
    assert e.instances == ("lower", "upper") and e.parts == ("base", "arm") and e.joints == ()
    assert "J-02" in str(e)


def test_compile_error_a_motor_on_a_part_without_a_role_has_no_curve():
    p = project([BASE, ARM], [instance("lower", "base"), instance("upper", "arm", (0.0, 0.0, 0.1))],
                [joint("mount", "hinge", ("lower", "top"), ("upper", "foot"), axis=(0, 0, 1))],
                [{"id": "drive", "kind": "motor", "instance": "lower", "joint": "mount"}])
    e = compile_error(p)
    assert e.code is CompileErrorCode.NO_CURVE
    assert e.actuators == ("drive",) and e.instances == ("lower",) and e.parts == ("base",) and e.joints == ("mount",)
    assert "'torque_speed'" in str(e)
    thruster = project([BASE], [instance("lower", "base")], actuators=[{"id": "boost", "kind": "thruster", "instance": "lower"}])
    e = compile_error(thruster)
    assert e.code is CompileErrorCode.NO_CURVE and e.actuators == ("boost",) and e.joints == () and "'thrust'" in str(e)


def test_compile_error_a_part_that_cannot_be_compiled_names_the_instance_and_part():
    e = compile_error(project([BASE], [instance("lower", "base", material=None)]))  # no material and no declared mass
    assert e.code is CompileErrorCode.PART and e.instances == ("lower",) and e.parts == ("base",)


def test_compile_error_the_first_problem_in_a_fixed_order_parts_actuators_snaps_axes_tree_floating():
    # snap gap, wrong axis and floating at once: the snap is reported (the order of the module docstring)
    p = project([BASE, ARM], [instance("lower", "base", (0.0, 0.0, 1.0)), instance("upper", "arm", (0.0, 0.0, 2.0), ROT_X90)],
                [joint("mount", "hinge", ("lower", "top"), ("upper", "foot"), axis=(0, 0, 1))])
    assert compile_error(p).code is CompileErrorCode.SNAP_MISMATCH


def test_compile_error_a_missing_definition_is_refused_before_compiling():
    p = Project.model_validate(
        {"design": {"materials": [MATERIAL], "parts": [BASE], "instances": [instance("lower", "base"), instance("ghost", "no-such-part")]},
         "world": {"planet": "earth"}}
    )
    with pytest.raises(ProjectIncomplete) as e:
        build_body_tree(p)
    assert e.value.operation is BlockedOperation.COMPILE
    assert [(m.kind, m.id, m.instances) for m in e.value.missing] == [("part", "no-such-part", ("ghost",))]
