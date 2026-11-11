"""`DesignSpec` (C-01b): what the user built. Part instances, joints, actuators, control schedule.

A `DesignSpec` is self-contained: it carries the `Material` and `PartDef` definitions its instances use, so a
reference (instance -> part, instance -> material, joint -> snap point) is checked here, at validation, and a
dangling one is rejected with the ids involved. (Opening a project whose definitions are missing is C-06's rule
and will relax the part/material checks there, not here.)

Where numbers are physical they follow C-01a: a `Quantity` (value, unit, badge, source), or one `Provenance`
that covers a whole record whose numbers have fixed units by field (an instance pose in m and a unit quaternion,
a schedule entry's times in s), the way a snap point's pose does in `partdef.py`.

Conventions are `conventions.py`: SI, right-handed +Z up, quaternion `{x, y, z, w}`. A pose is the world pose of
the instance's part frame.

Stable ids (G3): instance, joint and actuator ids match `ID_PATTERN` and are unique inside their own collection.
An actuator's id is also its control channel id (client-adapter I5): manual control (`control`) and schedule
entries name the actuator.

Not here: MJCF (X-01); joint axis, DoF rules per kind, spring and snap compatibility (B-04a, B-04b); torque-speed
and thrust curves and what a command of 1 means in N*m or N (B-03b, B-03c, X-01b, X-01c); release/separation
schedule entries (X-08); definition hashes and missing definitions (C-03, C-06); `World` and assumptions (C-01c).
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import ID_PATTERN, Unit
from .material import Material
from .partdef import Name, PartDef, Quaternion
from .provenance import Number, Provenance, Quantity

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
_Command = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1, le=1)]


class Vec3(BaseModel):
    """A position in metres, world frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Number
    y: Number
    z: Number


class Pose(Provenance):
    """World pose of an instance's part frame. One badge and source cover the whole pose."""

    position: Vec3
    orientation: Quaternion


class ParamValue(Quantity):
    """The value of one of the part's parameters for this instance. Unit and range are the `ParamDef`'s."""

    name: Name


class Instance(BaseModel):
    """One placed part. Parameters not listed take the `PartDef` default. `material` is optional: a part whose
    mass is declared by its own specs needs none; `None` means no material is assigned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _Id
    part: _Id
    parameters: tuple[ParamValue, ...] = ()
    material: _Id | None = None
    pose: Pose

    @model_validator(mode="after")
    def _unique_parameters(self) -> "Instance":
        dup = [n for n, c in Counter(p.name for p in self.parameters).items() if c > 1]
        if dup:
            raise ValueError(f"instance {self.id!r}: parameter set more than once: {sorted(dup)}")
        return self


class SnapRef(BaseModel):
    """A snap point of a placed instance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instance: _Id
    snap_point: _Id


class JointKind(StrEnum):
    FIXED = "fixed"
    HINGE = "hinge"
    SLIDER = "slider"


class JointLimits(BaseModel):
    """Travel limits of the joint coordinate: rad for a hinge, m for a slider. `lower < upper`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lower: Quantity
    upper: Quantity

    @model_validator(mode="after")
    def _range(self) -> "JointLimits":
        if self.lower.unit is not self.upper.unit:
            raise ValueError(f"lower and upper must share a unit, got {self.lower.unit.value!r} and {self.upper.unit.value!r}")
        if not self.lower.value < self.upper.value:
            raise ValueError(f"need lower < upper, got {self.lower.value} and {self.upper.value}")
        return self


class BreakThreshold(Quantity):
    """Joint load [N] above which the joint releases. A simplified model, not FEM (plan 4.6)."""

    value: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
    unit: Literal[Unit.N]


_LIMIT_UNIT = {JointKind.HINGE: Unit.RAD, JointKind.SLIDER: Unit.M}


class Joint(BaseModel):
    """A connection between two snap points of two different instances. `a` is the parent side by convention.

    `limits` are optional (`None`: unlimited, as a wheel axle) and not allowed on a fixed joint.
    `break_threshold` is optional (`None`: never breaks).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _Id
    kind: JointKind
    a: SnapRef
    b: SnapRef
    limits: JointLimits | None = None
    break_threshold: BreakThreshold | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Joint":
        if self.a.instance == self.b.instance:
            raise ValueError(f"joint {self.id!r}: both ends are on instance {self.a.instance!r}")
        if self.limits is not None:
            want = _LIMIT_UNIT.get(self.kind)
            if want is None:
                raise ValueError(f"joint {self.id!r}: a {self.kind.value} joint has no limits")
            if self.limits.lower.unit is not want:
                raise ValueError(
                    f"joint {self.id!r}: limits of a {self.kind.value} joint are in {want.value!r}, got {self.limits.lower.unit.value!r}"
                )
        return self


class ActuatorKind(StrEnum):
    MOTOR = "motor"
    THRUSTER = "thruster"


class Actuator(BaseModel):
    """Something on `instance` that a command drives. A motor drives one joint (`joint`); a thruster has none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _Id
    kind: ActuatorKind
    instance: _Id
    joint: _Id | None = None

    @model_validator(mode="after")
    def _joint_matches_kind(self) -> "Actuator":
        if self.kind is ActuatorKind.MOTOR and self.joint is None:
            raise ValueError(f"actuator {self.id!r}: a motor needs the joint it drives")
        if self.kind is ActuatorKind.THRUSTER and self.joint is not None:
            raise ValueError(f"actuator {self.id!r}: a thruster drives no joint")
        return self


class ActuateEntry(Provenance):
    """Command `command` on `actuator` during `[start, end)` seconds of simulated time.

    `command` is the fraction of the actuator's full command, in [-1, 1] for a motor (sign is direction) and
    [0, 1] for a thruster. What full command means physically comes from the part (B-03b, B-03c, X-01b, X-01c).
    One badge and source cover the entry (a user-typed entry is `declared`, a found one `estimate` or `sim`).
    """

    type: Literal["actuate"]
    actuator: _Id
    start: _NonNegative
    end: _NonNegative
    command: _Command

    @model_validator(mode="after")
    def _interval(self) -> "ActuateEntry":
        if not self.start < self.end:
            raise ValueError(f"need start < end, got {self.start} and {self.end}")
        return self


class ControlSchedule(BaseModel):
    """The time-axis control program. Entries are kept in the order given; time order is not required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[ActuateEntry, ...] = ()


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(i for i, c in Counter(ids).items() if c > 1)


class DesignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    materials: tuple[Material, ...] = ()
    parts: tuple[PartDef, ...] = ()
    instances: tuple[Instance, ...] = ()
    joints: tuple[Joint, ...] = ()
    actuators: tuple[Actuator, ...] = ()
    schedule: ControlSchedule = ControlSchedule()

    @model_validator(mode="after")
    def _references(self) -> "DesignSpec":
        for label, ids in (
            ("material", [m.id for m in self.materials]),
            ("part", [p.id for p in self.parts]),
            ("instance", [i.id for i in self.instances]),
            ("joint", [j.id for j in self.joints]),
            ("actuator", [a.id for a in self.actuators]),
        ):
            dup = _duplicates(ids)
            if dup:
                raise ValueError(f"duplicate {label} id: {dup}")

        materials = {m.id for m in self.materials}
        parts = {p.id: p for p in self.parts}
        instances = {i.id: i for i in self.instances}
        joints = {j.id: j for j in self.joints}
        actuators = {a.id: a for a in self.actuators}

        for n, inst in enumerate(self.instances):
            where = f"instances[{n}] ({inst.id!r})"
            part = parts.get(inst.part)
            if part is None:
                raise ValueError(f"{where}: unknown part {inst.part!r}")
            if inst.material is not None and inst.material not in materials:
                raise ValueError(f"{where}: unknown material {inst.material!r}")
            defs = {p.name: p for p in part.parameters}
            for v in inst.parameters:
                d = defs.get(v.name)
                if d is None:
                    raise ValueError(f"{where}: part {part.id!r} has no parameter {v.name!r}")
                if v.unit is not d.unit:
                    raise ValueError(f"{where}: parameter {v.name!r} is in {d.unit.value!r}, got {v.unit.value!r}")
                if not d.min.value <= v.value <= d.max.value:
                    raise ValueError(
                        f"{where}: parameter {v.name!r} = {v.value} is outside the part's range [{d.min.value}, {d.max.value}]"
                    )

        used: dict[tuple[str, str], str] = {}
        for n, joint in enumerate(self.joints):
            for side in ("a", "b"):
                ref: SnapRef = getattr(joint, side)
                where = f"joints[{n}] ({joint.id!r}).{side}"
                inst = instances.get(ref.instance)
                if inst is None:
                    raise ValueError(f"{where}: unknown instance {ref.instance!r}")
                if ref.snap_point not in {s.id for s in parts[inst.part].snap_points}:
                    raise ValueError(
                        f"{where}: part {inst.part!r} of instance {ref.instance!r} has no snap point {ref.snap_point!r}"
                    )
                key = (ref.instance, ref.snap_point)
                if key in used:
                    raise ValueError(f"{where}: snap point {ref.snap_point!r} of {ref.instance!r} is already used by joint {used[key]!r}")
                used[key] = joint.id

        for n, act in enumerate(self.actuators):
            where = f"actuators[{n}] ({act.id!r})"
            if act.instance not in instances:
                raise ValueError(f"{where}: unknown instance {act.instance!r}")
            if act.joint is not None:
                joint = joints.get(act.joint)
                if joint is None:
                    raise ValueError(f"{where}: unknown joint {act.joint!r}")
                if joint.kind is JointKind.FIXED:
                    raise ValueError(f"{where}: joint {act.joint!r} is fixed, nothing to drive")
                if act.instance not in (joint.a.instance, joint.b.instance):
                    raise ValueError(f"{where}: instance {act.instance!r} is not at either end of joint {act.joint!r}")

        by_actuator: dict[str, list[ActuateEntry]] = {}
        for n, entry in enumerate(self.schedule.entries):
            where = f"schedule.entries[{n}]"
            act = actuators.get(entry.actuator)
            if act is None:
                raise ValueError(f"{where}: unknown actuator {entry.actuator!r}")
            if act.kind is ActuatorKind.THRUSTER and entry.command < 0:
                raise ValueError(f"{where}: thruster {act.id!r} takes a command in [0, 1], got {entry.command}")
            by_actuator.setdefault(entry.actuator, []).append(entry)
        for actuator_id, entries in by_actuator.items():
            entries.sort(key=lambda e: e.start)
            for prev, nxt in zip(entries, entries[1:]):
                if nxt.start < prev.end:
                    raise ValueError(
                        f"schedule: actuator {actuator_id!r} has overlapping entries [{prev.start}, {prev.end}) and [{nxt.start}, {nxt.end})"
                    )
        return self
