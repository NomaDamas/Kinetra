"""Compile checks per part and joint (X-01d) that the body tree (X-01a) does not make by building: actuators without a curve,
joined snap points that do not meet, joint axes the two snap frames disagree on, and an assembly in the air.

**One placement rule.** Whether two joined snap points accept each other and meet, and whether the assembly floats, is the
validator's rule (C-02c, `kinetra_core.check_placement`, tolerance `PLACEMENT_TOLERANCE` = 1 micrometre). The compiler asks
the same function, so an edit the validator accepts never fails to compile for placement, and a file that carries such
a problem (the validator only refuses what an edit introduces) is refused here. Overlaps are not compile errors: they
stay the validator's finding. A part without a shape recipe has no geometry, so the validator does not call its group
floating (unknown, not a pass), and neither does the compiler.

**Axis.** A hinge or slider axis is written in the frame of its `a` snap point (`Joint.unit_axis`). The compiler uses that
line (X-01a). The same unit vector read in the frame of the `b` snap point must lie on the same world line, either
direction: mating snap frames may face each other (the right motor of the four-wheel car example is turned 180 degrees,
its shaft axis is -Y where the wheel's hub is +Y). Otherwise the joint would turn `b` about an axis that is not its own.
`AXIS_TOLERANCE` bounds the sine of the angle between the two; like `PLACEMENT_TOLERANCE` it is a numerical tolerance
for stored doubles, not a physical claim.

**Actuators.** A motor or thruster actuator on a part with a role is checked by `DesignSpec` (the role must fit, and the
role's curve is required by `PartDef`). A part with no role is accepted there on purpose (`part-motor.md`); it has no
curve, so the compiler refuses it here (`no_curve`).
"""

from __future__ import annotations

from collections.abc import Mapping

from kinetra_core import ActuatorKind, DesignSpec, Instance, JointKind, PartDef, Reason, ReasonCode, RefKind
from kinetra_core import convex as cx
from kinetra_core.partdef import MOTOR_CURVE, THRUSTER_CURVE

from .errors import CompileError, CompileErrorCode

AXIS_TOLERANCE = 1e-6
"""Largest sine of the angle between a joint's axis read from its `a` and from its `b` snap frame. Numerical, not physical."""

_CURVE = {ActuatorKind.MOTOR: MOTOR_CURVE, ActuatorKind.THRUSTER: THRUSTER_CURVE}


def _parts_of(instances: tuple[str, ...], by_id: Mapping[str, Instance]) -> tuple[str, ...]:
    """The parts of `instances`, each once, in the order first met."""
    return tuple(dict.fromkeys(by_id[i].part for i in instances))


def check_actuators(design: DesignSpec) -> None:
    """`no_curve` for the first actuator (id order) on an instance whose part has no role."""
    by_id = {i.id: i for i in design.instances}
    parts = {p.id: p for p in design.parts}
    for act in design.actuators:
        inst = by_id[act.instance]
        if parts[inst.part].role is None:
            raise CompileError(
                f"{act.kind.value} actuator {act.id!r} is on instance {inst.id!r} of part {inst.part!r}, which has no role: "
                f"it has no curve {_CURVE[act.kind]!r} to drive by (give the part the role {act.kind.value!r} with its curve, "
                "or put the actuator on a part that has it)",
                code=CompileErrorCode.NO_CURVE,
                instances=(inst.id,),
                parts=(inst.part,),
                joints=() if act.joint is None else (act.joint,),
                actuators=(act.id,),
            )


def check_snaps(design: DesignSpec, findings: tuple[Reason, ...]) -> None:
    """`findings` are `check_placement`'s. `snap_mismatch` for the first joint the validator finds with snap points that do not accept each other or do not meet."""
    by_id = {i.id: i for i in design.instances}
    joints = {j.id: j for j in design.joints}
    for reason in findings:
        if reason.code is ReasonCode.INVALID_SNAP:
            joint = joints[next(r.id for r in reason.ids if r.kind is RefKind.JOINT)]
            instances = (joint.a.instance, joint.b.instance)
            raise CompileError(
                reason.message, code=CompileErrorCode.SNAP_MISMATCH, instances=instances, parts=_parts_of(instances, by_id), joints=(joint.id,)
            )


def check_floating(design: DesignSpec, findings: tuple[Reason, ...]) -> None:
    """`findings` are `check_placement`'s. `floating` for the first group the validator finds touching neither the ground nor a terrain prop."""
    by_id = {i.id: i for i in design.instances}
    for reason in findings:
        if reason.code is ReasonCode.FLOATING:
            instances = tuple(r.id for r in reason.ids if r.kind is RefKind.INSTANCE)
            raise CompileError(
                f"{reason.message} (a start above the ground is not part of a project yet: J-02)",
                code=CompileErrorCode.FLOATING,
                instances=instances,
                parts=_parts_of(instances, by_id),
            )


def _shown(v: tuple[float, float, float]) -> str:
    """`v` for a sentence: rounded to 1e-9 so a rotation's rounding noise does not show as `-2.22e-16`."""
    return "(" + ", ".join(f"{round(c, 9) + 0.0:.6g}" for c in v) + ")"


def check_axes(design: DesignSpec) -> None:
    """`axis_mismatch` for the first hinge or slider (id order) whose axis from its `a` and its `b` snap frame is not one line."""
    by_id = {i.id: i for i in design.instances}
    parts: dict[str, PartDef] = {p.id: p for p in design.parts}

    def snap_axis(instance: str, snap_point: str, axis: tuple[float, float, float]) -> tuple[float, float, float]:
        inst = by_id[instance]
        snap = next(s for s in parts[inst.part].snap_points if s.id == snap_point)
        r_inst, r_snap = cx.rotation(inst.pose.orientation), cx.rotation(snap.orientation)
        local = (cx.dot(r_snap[0], axis), cx.dot(r_snap[1], axis), cx.dot(r_snap[2], axis))
        return (cx.dot(r_inst[0], local), cx.dot(r_inst[1], local), cx.dot(r_inst[2], local))

    for joint in design.joints:
        if joint.kind is JointKind.FIXED:
            continue
        ua = snap_axis(joint.a.instance, joint.a.snap_point, joint.unit_axis)
        ub = snap_axis(joint.b.instance, joint.b.snap_point, joint.unit_axis)
        cross = (ua[1] * ub[2] - ua[2] * ub[1], ua[2] * ub[0] - ua[0] * ub[2], ua[0] * ub[1] - ua[1] * ub[0])
        sine = (cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) ** 0.5
        if sine > AXIS_TOLERANCE:
            instances = (joint.a.instance, joint.b.instance)
            raise CompileError(
                f"{joint.kind.value} joint {joint.id!r}: its axis is {_shown(ua)} in the world from snap point "
                f"{joint.a.snap_point!r} of {joint.a.instance!r} but {_shown(ub)} from {joint.b.snap_point!r} of "
                f"{joint.b.instance!r}: the two snap frames must put it on one line (turn an instance)",
                code=CompileErrorCode.AXIS_MISMATCH,
                instances=instances,
                parts=_parts_of(instances, by_id),
                joints=(joint.id,),
            )
