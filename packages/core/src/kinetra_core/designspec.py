"""`DesignSpec` (C-01b): what the user built. Part instances, joints, actuators, control schedule.

A `DesignSpec` carries the `Material` and `PartDef` definitions its instances use. What a definition says about an
instance (parameter names, units and ranges, a joint's snap point, an actuator's role) is checked here, at
validation, and a conflict is rejected with the ids involved. An instance whose part or material the project does
not carry is a placeholder (C-06, `missing.py`, `docs/architecture/missing-definitions.md`): it validates, keeps its
pose, parameter values and joints, and nothing that needs the missing definition is checked until it is linked back.
Other references (joint -> instance, actuator -> instance, schedule -> actuator) stay closed.

Where numbers are physical they follow C-01a: a `Quantity` (value, unit, badge, source), or one `Provenance`
that covers a whole record whose numbers have fixed units by field (an instance pose in m and a unit quaternion,
a schedule entry's times in s), the way a snap point's pose does in `partdef.py`.

Conventions are `conventions.py`: SI, right-handed +Z up, quaternion `{x, y, z, w}`. A pose is the world pose of
the instance's part frame. The pose is the stored authority for where an instance is: a joint does not move
anything, it says which two snap points belong together. Whether the joined snap points actually coincide at the
stored poses, and whether a part floats free, is a placement check (C-02c validator, X-01d compile errors), not
a `DesignSpec` validation. A joint's coordinate is 0 at the saved pose (hinge angle 0 rad, slider offset 0 m);
`limits` are travel from there.

Joint graph: `a` is the parent side, `b` the child. This model only checks that each end exists and that no snap
point is used twice. That the joints form a tree (no loop, one connected assembly) is the body-tree builder's
rule, reported as a compile error (X-01a, X-01d).

Stable ids (G3): instance, joint, actuator and schedule entry ids match `ID_PATTERN` and are unique inside their own collection.
An actuator's id is also its control channel id (client-adapter I5): manual control (`control`) and schedule
entries name the actuator. Two actuators with the same kind, instance and joint are rejected (a second channel
to the same drive is ambiguous). Which part may carry which actuator kind: a motor actuator on a part whose role is
`motor`, a thruster on `thruster` (`PartRole`, B-03b). A part with another role is rejected; a part with no role is
accepted (a bare body, and the compiler reports that it has no curve).

Not here: MJCF (X-01); joint axis, DoF rules per kind, snap compatibility (B-04a, B-04b); springs and dampers
(B-03e, X-01b); torque-speed and thrust curves and what a command of 1 means in N*m or N (B-03b, B-03c, X-01b,
X-01c); release/separation schedule entries (X-08); definition hashes (`canonical.py`, C-03);
`World` and assumptions (C-01c).
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import ID_PATTERN, Unit
from .material import Material
from .partdef import Name, PartDef, PartRole, Quaternion
from .provenance import Number, Provenance, Quantity
from .refs import Ref, RefError, RefKind

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
_Command = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1, le=1)]


class WorldPosition(BaseModel):
    """A position in metres, world frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Number
    y: Number
    z: Number


class Pose(Provenance):
    """World pose of an instance's part frame. One badge and source cover the whole pose."""

    position: WorldPosition
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


_ACTUATOR_ROLE = {ActuatorKind.MOTOR: PartRole.MOTOR, ActuatorKind.THRUSTER: PartRole.THRUSTER}
"""The part role an actuator kind drives. A part with a different role is rejected; a part without a role is a bare body
and is accepted here (the compiler cannot find a curve on it and reports that, X-01d)."""


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


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(i for i, c in Counter(ids).items() if c > 1)


class ActuateEntry(Provenance):
    """Command `command` on `actuator` during `[start, end)` seconds of simulated time.

    `command` is the fraction of the actuator's full command, in [-1, 1] for a motor (sign is direction) and
    [0, 1] for a thruster. What full command means physically comes from the part (B-03b, B-03c, X-01b, X-01c).
    One badge and source cover the entry. `id` names the entry inside the schedule (unique there): commands
    that edit an entry name it by id, never by position, so a reordered or partly accepted batch cannot change
    a different entry than the one meant.
    """

    type: Literal["actuate"]
    id: _Id
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
    """The time-axis control program. Entries are kept in the order given; time order is not required. Entry ids
    are unique inside the schedule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[ActuateEntry, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> "ControlSchedule":
        dup = _duplicates([e.id for e in self.entries])
        if dup:
            raise RefError(f"duplicate schedule entry id: {dup}", *(Ref(kind=RefKind.SCHEDULE_ENTRY, id=i) for i in dup))
        return self


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
                raise RefError(f"duplicate {label} id: {dup}", *(Ref(kind=RefKind(label), id=i) for i in dup))

        materials = {m.id for m in self.materials}
        parts = {p.id: p for p in self.parts}
        instances = {i.id: i for i in self.instances}
        joints = {j.id: j for j in self.joints}
        actuators = {a.id: a for a in self.actuators}

        # A part or material the project does not carry is not an error (C-06, `missing.py`): the instance stays as a
        # placeholder with its pose, parameter values and joints. What would need the definition (parameter names,
        # units and ranges, a snap point's existence, an actuator's role) cannot be checked and is not; it is checked
        # again when the definition is linked back (`relink_instance`, `add_part_def`), which validates the whole
        # project. A snap point is still used by one joint only: that needs no definition.
        for n, inst in enumerate(self.instances):
            where = f"instances[{n}] ({inst.id!r})"
            part = parts.get(inst.part)
            if part is None:
                continue
            defs = {p.name: p for p in part.parameters}
            for v in inst.parameters:
                d = defs.get(v.name)
                if d is None:
                    raise RefError(f"{where}: part {part.id!r} has no parameter {v.name!r}", Ref(kind=RefKind.PARAMETER, id=f"{inst.id}/{v.name}"))
                if v.unit is not d.unit:
                    raise RefError(f"{where}: parameter {v.name!r} is in {d.unit.value!r}, got {v.unit.value!r}", Ref(kind=RefKind.PARAMETER, id=f"{inst.id}/{v.name}"))
                if not d.min.value <= v.value <= d.max.value:
                    raise RefError(
                        f"{where}: parameter {v.name!r} = {v.value} is outside the part's range [{d.min.value}, {d.max.value}]",
                        Ref(kind=RefKind.PARAMETER, id=f"{inst.id}/{v.name}"),
                    )

        used: dict[tuple[str, str], str] = {}
        for n, joint in enumerate(self.joints):
            for side in ("a", "b"):
                ref: SnapRef = getattr(joint, side)
                where = f"joints[{n}] ({joint.id!r}).{side}"
                inst = instances.get(ref.instance)
                if inst is None:
                    raise RefError(f"{where}: unknown instance {ref.instance!r}", Ref(kind=RefKind.INSTANCE, id=ref.instance), Ref(kind=RefKind.JOINT, id=joint.id))
                if inst.part in parts and ref.snap_point not in {s.id for s in parts[inst.part].snap_points}:
                    raise RefError(
                        f"{where}: part {inst.part!r} of instance {ref.instance!r} has no snap point {ref.snap_point!r}",
                        Ref(kind=RefKind.SNAP_POINT, id=f"{ref.instance}/{ref.snap_point}"),
                        Ref(kind=RefKind.JOINT, id=joint.id),
                    )
                key = (ref.instance, ref.snap_point)
                if key in used:
                    raise RefError(
                        f"{where}: snap point {ref.snap_point!r} of {ref.instance!r} is already used by joint {used[key]!r}",
                        Ref(kind=RefKind.SNAP_POINT, id=f"{ref.instance}/{ref.snap_point}"),
                        Ref(kind=RefKind.JOINT, id=used[key]),
                        Ref(kind=RefKind.JOINT, id=joint.id),
                    )
                used[key] = joint.id

        for n, act in enumerate(self.actuators):
            where = f"actuators[{n}] ({act.id!r})"
            if act.instance not in instances:
                raise RefError(f"{where}: unknown instance {act.instance!r}", Ref(kind=RefKind.INSTANCE, id=act.instance), Ref(kind=RefKind.ACTUATOR, id=act.id))
            actuated_part = parts.get(instances[act.instance].part)
            role = None if actuated_part is None else actuated_part.role
            want_role = _ACTUATOR_ROLE[act.kind]
            if role is not None and role is not want_role:
                raise RefError(
                    f"{where}: a {act.kind.value} drives a part with role {want_role.value!r}, "
                    f"but instance {act.instance!r} is part {instances[act.instance].part!r} with role {role.value!r}",
                    Ref(kind=RefKind.INSTANCE, id=act.instance),
                    Ref(kind=RefKind.PART, id=instances[act.instance].part),
                    Ref(kind=RefKind.ACTUATOR, id=act.id),
                )
            if act.joint is not None:
                joint = joints.get(act.joint)
                if joint is None:
                    raise RefError(f"{where}: unknown joint {act.joint!r}", Ref(kind=RefKind.JOINT, id=act.joint), Ref(kind=RefKind.ACTUATOR, id=act.id))
                if joint.kind is JointKind.FIXED:
                    raise RefError(f"{where}: joint {act.joint!r} is fixed, nothing to drive", Ref(kind=RefKind.JOINT, id=act.joint), Ref(kind=RefKind.ACTUATOR, id=act.id))
                if act.instance not in (joint.a.instance, joint.b.instance):
                    raise RefError(
                        f"{where}: instance {act.instance!r} is not at either end of joint {act.joint!r}",
                        Ref(kind=RefKind.INSTANCE, id=act.instance),
                        Ref(kind=RefKind.JOINT, id=act.joint),
                        Ref(kind=RefKind.ACTUATOR, id=act.id),
                    )

        seen_drive: dict[tuple[ActuatorKind, str, str | None], str] = {}
        for n, act in enumerate(self.actuators):
            drive = (act.kind, act.instance, act.joint)
            if drive in seen_drive:
                raise RefError(
                    f"actuators[{n}] ({act.id!r}): same {act.kind.value} on instance {act.instance!r}"
                    f"{'' if act.joint is None else f' and joint {act.joint!r}'} as actuator {seen_drive[drive]!r}",
                    Ref(kind=RefKind.ACTUATOR, id=act.id),
                    Ref(kind=RefKind.ACTUATOR, id=seen_drive[drive]),
                )
            seen_drive[drive] = act.id

        by_actuator: dict[str, list[ActuateEntry]] = {}
        for n, entry in enumerate(self.schedule.entries):
            where = f"schedule.entries[{n}]"
            act = actuators.get(entry.actuator)
            if act is None:
                raise RefError(f"{where}: unknown actuator {entry.actuator!r}", Ref(kind=RefKind.ACTUATOR, id=entry.actuator), Ref(kind=RefKind.SCHEDULE_ENTRY, id=entry.id))
            if act.kind is ActuatorKind.THRUSTER and entry.command < 0:
                raise RefError(f"{where}: thruster {act.id!r} takes a command in [0, 1], got {entry.command}", Ref(kind=RefKind.SCHEDULE_ENTRY, id=entry.id), Ref(kind=RefKind.ACTUATOR, id=act.id))
            by_actuator.setdefault(entry.actuator, []).append(entry)
        for actuator_id, entries in by_actuator.items():
            entries.sort(key=lambda e: e.start)
            for prev, nxt in zip(entries, entries[1:]):
                if nxt.start < prev.end:
                    raise RefError(
                        f"schedule: actuator {actuator_id!r} has overlapping entries [{prev.start}, {prev.end}) and [{nxt.start}, {nxt.end})",
                        Ref(kind=RefKind.SCHEDULE_ENTRY, id=prev.id),
                        Ref(kind=RefKind.SCHEDULE_ENTRY, id=nxt.id),
                        Ref(kind=RefKind.ACTUATOR, id=actuator_id),
                    )
        return self
