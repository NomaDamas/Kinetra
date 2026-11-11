"""B-04a: fixed, hinge and slider joints. The axis field, the degrees of freedom each kind leaves, and what a
coordinate and its limits mean (0 is the saved pose). Every number is a value the test declares (`사용자 선언`)."""

from __future__ import annotations

import copy
import math

import pytest
from pydantic import TypeAdapter, ValidationError

import kinetra_core.convex as cx
from kinetra_core import (
    DEFAULT_JOINT_AXIS,
    Command,
    CommandRejected,
    DesignSpec,
    Joint,
    JointAxis,
    JointKind,
    Project,
    ReasonCode,
    apply_command,
    canonical_json,
    joint_dof,
    project_hash,
)
from test_designspec import four_wheel_car, q, SRC

IDENTITY_R = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ENDS = {"a": {"instance": "chassis-1", "snap_point": "axle-fl"}, "b": {"instance": "wheel-fl", "snap_point": "hub"}}


def axis_json(x=0.0, y=0.0, z=1.0, **extra):
    return {"x": x, "y": y, "z": z, "badge": "declared", "source": SRC, **extra}


def limits_json(lo, hi, unit):
    return {"lower": q(lo, unit), "upper": q(hi, unit)}


def joint(kind="hinge", **fields) -> Joint:
    return Joint.model_validate({"id": "j1", "kind": kind, **ENDS, **fields})


def rejects(match, **fields):
    with pytest.raises(ValidationError, match=match):
        joint(**fields)


def apply(r, v):
    return tuple(sum(r[i][k] * v[k] for k in range(3)) for i in range(3))


def close(a, b, tol=1e-12):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# --- degrees of freedom per kind -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,rotational,translational",
    [(JointKind.FIXED, 0, 0), (JointKind.HINGE, 1, 0), (JointKind.SLIDER, 0, 1)],
)
def test_joint_degrees_of_freedom_per_kind(kind, rotational, translational):
    dof = joint_dof(kind)
    assert (dof.rotational, dof.translational) == (rotational, translational)
    assert dof.total == rotational + translational
    assert joint(kind.value).dof == dof


def test_joint_every_kind_has_a_dof_entry():
    assert {k for k in JointKind} == {JointKind.FIXED, JointKind.HINGE, JointKind.SLIDER}
    assert [joint_dof(k).total for k in (JointKind.FIXED, JointKind.HINGE, JointKind.SLIDER)] == [0, 1, 1]


def test_joint_fixed_leaves_b_where_it_is_and_takes_no_other_coordinate():
    j = joint("fixed")
    assert j.displacement() == (IDENTITY_R, (0.0, 0.0, 0.0))
    for bad in (0.1, -0.1, 1e-12):
        with pytest.raises(ValueError, match="fixed joint has no coordinate"):
            j.displacement(bad)


def test_joint_hinge_rotates_about_its_axis_and_never_translates():
    j = joint("hinge", axis=axis_json(0.0, 0.0, 1.0))
    r, t = j.displacement(math.pi / 2)
    assert t == (0.0, 0.0, 0.0)
    assert close(apply(r, (1.0, 0.0, 0.0)), (0.0, 1.0, 0.0))  # right-handed: +X turns toward +Y about +Z
    assert close(apply(r, (0.0, 0.0, 1.0)), (0.0, 0.0, 1.0))  # points on the axis stay


def test_joint_hinge_about_a_slanted_axis_is_a_rotation_that_fixes_the_axis():
    n = math.sqrt(3.0)
    j = joint("hinge", axis=axis_json(1 / n, 1 / n, 1 / n))
    r, _ = j.displacement(2 * math.pi / 3)
    assert close(apply(r, (1.0, 0.0, 0.0)), (0.0, 1.0, 0.0))  # 120 deg about (1,1,1) cycles the axes x -> y -> z
    assert close(apply(r, (0.0, 1.0, 0.0)), (0.0, 0.0, 1.0))
    assert close(apply(r, (1 / n, 1 / n, 1 / n)), (1 / n, 1 / n, 1 / n))
    assert abs(cx.dot(r[0], cx.cross(r[1], r[2])) - 1.0) < 1e-12  # proper rotation
    for row in r:
        assert abs(cx.norm(row) - 1.0) < 1e-12


def test_joint_hinge_negative_axis_is_the_same_line_with_the_coordinate_flipped():
    up, down = joint("hinge", axis=axis_json(0.0, 1.0, 0.0)), joint("hinge", axis=axis_json(0.0, -1.0, 0.0))
    ru, _ = up.displacement(0.7)
    rd, _ = down.displacement(-0.7)
    assert all(close(ru[i], rd[i]) for i in range(3))


def test_joint_slider_translates_along_its_axis_and_never_rotates():
    j = joint("slider", axis=axis_json(0.0, 0.6, 0.8))
    r, t = j.displacement(0.5)
    assert r == IDENTITY_R
    assert close(t, (0.0, 0.3, 0.4))
    assert close(j.displacement(-0.5)[1], (0.0, -0.3, -0.4))


@pytest.mark.parametrize("kind", ["hinge", "slider"])
def test_joint_coordinate_zero_is_the_saved_pose(kind):
    for axis in (None, axis_json(1.0, 0.0, 0.0)):
        assert joint(kind, axis=axis).displacement(0.0) == (IDENTITY_R, (0.0, 0.0, 0.0))
        assert joint(kind, axis=axis).displacement() == (IDENTITY_R, (0.0, 0.0, 0.0))


@pytest.mark.parametrize("kind", ["hinge", "slider"])
def test_joint_coordinate_rejects_what_is_not_finite(kind):
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="must be finite"):
            joint(kind).displacement(bad)


# --- axis -------------------------------------------------------------------------------------------------------


def test_joint_axis_defaults_to_plus_z_of_the_a_snap_frame():
    assert DEFAULT_JOINT_AXIS == (0.0, 0.0, 1.0)
    for kind in ("hinge", "slider"):
        j = joint(kind)
        assert j.axis is None and j.unit_axis == DEFAULT_JOINT_AXIS


def test_joint_axis_is_read_back_as_a_unit_vector():
    j = joint("hinge", axis=axis_json(0.0, 1.0 + 5e-7, 0.0))  # inside the tolerance
    assert j.unit_axis == (0.0, 1.0, 0.0)


def test_joint_axis_carries_a_badge_and_a_source():
    j = joint("hinge", axis=axis_json(1.0, 0.0, 0.0))
    assert j.axis.badge.value == "declared" and j.axis.source.ref == SRC["ref"]
    with pytest.raises(ValidationError, match="source"):
        joint("hinge", axis={"x": 1.0, "y": 0.0, "z": 0.0, "badge": "declared"})
    with pytest.raises(ValidationError, match="badge"):
        joint("hinge", axis={"x": 1.0, "y": 0.0, "z": 0.0, "source": SRC})


@pytest.mark.parametrize("v", [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 0.0, 2.0), (0.0, 0.0, 0.9)])
def test_joint_axis_must_have_unit_length(v):
    rejects("unit length", kind="hinge", axis=axis_json(*v))
    rejects("unit length", kind="slider", axis=axis_json(*v))


@pytest.mark.parametrize("bad", ["1.0", True, math.nan, math.inf])
def test_joint_axis_components_must_be_finite_numbers(bad):
    with pytest.raises(ValidationError):
        joint("hinge", axis=axis_json(bad, 0.0, 0.0))


def test_joint_axis_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        JointAxis.model_validate(axis_json(w=0.0))


def test_joint_fixed_has_no_axis():
    rejects("a fixed joint has no axis", kind="fixed", axis=axis_json())
    with pytest.raises(ValueError, match="fixed joint has no axis"):
        joint("fixed").unit_axis


# --- limits: the coordinate is 0 at the saved pose --------------------------------------------------------------


def test_joint_limits_must_contain_the_saved_pose():
    joint("hinge", limits=limits_json(-1.0, 1.0, "rad"))
    joint("hinge", limits=limits_json(0.0, 1.0, "rad"))  # the saved pose may sit on a limit
    joint("slider", limits=limits_json(-0.2, 0.0, "m"))
    for lo, hi in ((0.1, 1.0), (-1.0, -0.1)):
        rejects(r"lower <= 0 <= upper", kind="hinge", limits=limits_json(lo, hi, "rad"))
        rejects(r"lower <= 0 <= upper", kind="slider", limits=limits_json(lo, hi, "m"))


def test_joint_limits_bound_the_coordinate_inclusively():
    j = joint("hinge", limits=limits_json(-0.5, 1.0, "rad"))
    j.displacement(-0.5)
    j.displacement(1.0)
    for bad in (-0.5000001, 1.0000001):
        with pytest.raises(ValueError, match="outside the limits"):
            j.displacement(bad)
    s = joint("slider", limits=limits_json(0.0, 0.05, "m"))
    assert close(s.displacement(0.05)[1], (0.0, 0.0, 0.05))
    with pytest.raises(ValueError, match="outside the limits"):
        s.displacement(0.06)


def test_joint_without_limits_is_unlimited():
    j = joint("hinge")
    r, _ = j.displacement(100.0)  # a wheel axle turns any number of times
    assert abs(cx.dot(r[0], r[0]) - 1.0) < 1e-12


def test_joint_limits_unit_follows_the_kind():
    rejects("limits of a hinge joint are in 'rad'", kind="hinge", limits=limits_json(-0.1, 0.1, "m"))
    rejects("limits of a slider joint are in 'm'", kind="slider", limits=limits_json(-0.1, 0.1, "rad"))
    rejects("a fixed joint has no limits", kind="fixed", limits=limits_json(-0.1, 0.1, "rad"))


# --- break threshold: a field of all three kinds ----------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fixed", "hinge", "slider"])
def test_joint_break_threshold_is_a_field_of_every_kind(kind):
    j = joint(kind, break_threshold=q(250.0, "N"))
    assert j.break_threshold.value == 250.0 and j.break_threshold.unit.value == "N"
    assert joint(kind).break_threshold is None  # None: never breaks


@pytest.mark.parametrize("kind", ["fixed", "hinge", "slider"])
def test_joint_break_threshold_must_be_a_positive_force(kind):
    for bad in (q(0.0, "N"), q(-1.0, "N"), q(1.0, "N*m")):
        rejects("break_threshold", kind=kind, break_threshold=bad)


# --- a joint inside a design: the field travels through the model, commands and the hash -------------------------


def car_with(joint_id, **fields):
    d = four_wheel_car()
    next(j for j in d["joints"] if j["id"] == joint_id).update(fields)
    return d


def test_joint_axis_and_limits_validate_inside_a_design():
    spec = DesignSpec.model_validate(car_with("axle-fl", axis=axis_json(0.0, 1.0, 0.0), limits=limits_json(-3.0, 3.0, "rad")))
    j = next(j for j in spec.joints if j.id == "axle-fl")
    assert j.unit_axis == (0.0, 1.0, 0.0) and j.limits.upper.value == 3.0


def test_joint_a_slider_in_a_design_may_be_driven_by_a_motor_but_a_fixed_joint_may_not():
    d = four_wheel_car()
    d["joints"][2].update(kind="slider", limits=limits_json(0.0, 0.1, "m"), axis=axis_json(0.0, 1.0, 0.0))
    DesignSpec.model_validate(d)  # drive-l is a slider now, with its motor still on it
    d["joints"][2] = {k: v for k, v in d["joints"][2].items() if k not in ("axis", "limits")} | {"kind": "fixed"}
    with pytest.raises(ValidationError, match="is fixed, nothing to drive"):
        DesignSpec.model_validate(d)


def test_joint_axis_changes_the_hash_and_an_absent_axis_is_not_written():
    base = Project.model_validate({"design": four_wheel_car(), "world": {"planet": "earth"}})
    axed = Project.model_validate({"design": car_with("axle-fl", axis=axis_json(0.0, 1.0, 0.0)), "world": {"planet": "earth"}})
    assert project_hash(base) != project_hash(axed)
    assert '"axis"' not in canonical_json(base)  # the default (None) is left out, so older files keep their hash
    assert '"axis"' in canonical_json(axed)


def project_with_car():
    d = four_wheel_car()
    return Project.model_validate({"design": d, "world": {"planet": "earth"}})


def replace(project, **fields):
    old = next(j for j in project.design.joints if j.id == "axle-fl").model_dump(mode="json")
    return TypeAdapter(Command).validate_python({"type": "replace_joint", "joint": {**old, **fields}})


def test_joint_replace_joint_sets_axis_and_limits_and_the_inverse_restores_them():
    p = project_with_car()
    done = apply_command(p, replace(p, axis=axis_json(0.0, 1.0, 0.0), limits=limits_json(-1.0, 1.0, "rad")))
    j = next(j for j in done.project.design.joints if j.id == "axle-fl")
    assert j.axis.y == 1.0 and j.limits.lower.value == -1.0
    assert [x.id for x in done.project.design.joints] == [x.id for x in p.design.joints]  # same place in the list
    undone = apply_command(done.project, done.inverse)
    assert undone.project == p
    assert next(j for j in undone.project.design.joints if j.id == "axle-fl").axis is None


def test_joint_replace_joint_can_turn_a_hinge_into_a_slider_with_matching_limits():
    p = project_with_car()
    done = apply_command(p, replace(p, kind="slider", axis=axis_json(0.0, 0.0, 1.0), limits=limits_json(0.0, 0.02, "m")))
    assert next(j for j in done.project.design.joints if j.id == "axle-fl").dof == joint_dof(JointKind.SLIDER)


@pytest.mark.parametrize(
    "fields,match",
    [
        ({"kind": "fixed", "axis": axis_json()}, "fixed joint has no axis"),
        ({"kind": "fixed", "limits": limits_json(-1.0, 1.0, "rad")}, "fixed joint has no limits"),
        ({"limits": limits_json(0.1, 1.0, "rad")}, r"lower <= 0 <= upper"),
        ({"kind": "slider", "limits": limits_json(-1.0, 1.0, "rad")}, "slider joint are in 'm'"),
        ({"axis": axis_json(0.0, 0.0, 2.0)}, "unit length"),
    ],
)
def test_joint_replace_joint_that_breaks_the_kind_rules_is_rejected_and_changes_nothing(fields, match):
    p = project_with_car()
    before = copy.deepcopy(p)
    with pytest.raises((CommandRejected, ValidationError)) as e:
        apply_command(p, replace(p, **fields))
    assert match in str(e.value)
    if isinstance(e.value, CommandRejected):
        assert e.value.reasons[0].code is ReasonCode.INVALID_PROJECT
    assert p == before


# --- the example car: its hinges name their axis ----------------------------------------------------------------


def world_axis(spec, joint_):
    """The joint axis in the world: the `a` instance's rotation, then the `a` snap point's rotation, then the axis."""
    inst = next(i for i in spec.instances if i.id == joint_.a.instance)
    part = next(p for p in spec.parts if p.id == inst.part)
    snap = next(s for s in part.snap_points if s.id == joint_.a.snap_point)
    v = apply(cx.rotation(snap.orientation), joint_.unit_axis)
    return apply(cx.rotation(inst.pose.orientation), v)


def test_joint_the_example_hinges_turn_about_the_wheel_axle_in_the_world():
    spec = DesignSpec.model_validate(four_wheel_car())
    hinges = [j for j in spec.joints if j.kind is JointKind.HINGE]
    assert len(hinges) == 4
    for j in hinges:
        assert j.axis is None  # the fixture states no axis (+Z of the snap frame), which is not the wheel axle

    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[3] / "schemas" / "examples"
    for name in ("DesignSpec.four-wheel-car.json", "Project.four-wheel-car.json", "Project.rocket-car-skeleton.json"):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        design = DesignSpec.model_validate(data.get("design", data))
        for j in design.joints:
            if j.kind is JointKind.HINGE:
                assert j.axis is not None and j.axis.badge.value == "declared", (name, j.id)
                w = world_axis(design, j)
                assert abs(abs(w[1]) - 1.0) < 1e-12 and abs(w[0]) < 1e-12 and abs(w[2]) < 1e-12, (name, j.id, w)  # the world Y line
            else:
                assert j.axis is None
