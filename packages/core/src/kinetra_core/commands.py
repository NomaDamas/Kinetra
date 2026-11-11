"""`Command` and the applier (C-02a): every edit of a `Project` is one of these, whoever sends it.

`apply_command(project, command)` returns `Applied(project, inverse)`: a new validated `Project` and the command that
undoes this one. It never mutates its input and either returns a valid `Project` or raises `CommandRejected`
with reasons (code, sentence, ids; `client-adapter.md` 3.2 `rejected`). Applying the inverse to the new project
gives back a project equal to the original (order of every collection included), and the inverse's inverse
redoes the edit. C-02b builds undo, redo and history on that pair; C-02c adds the policy checks (placement,
planet constants, who may send what); C-05a puts the commands on the wire.

Shape rules (read by C-02b, C-02c, C-03, C-05a, XR-02):

- A command is a frozen pydantic model with a required literal `type` tag. `Command` is the discriminated union
  of them, so JSON from any client (`schemas/Command.schema.json`) parses to one exact command or fails.
- A command says it in the document's words (`client-adapter.md` I2): ids, parameter names, SI values with
  badge and source. No screen coordinates, no device poses. It does not name who sent it: the issuer belongs to
  the history record (C-02b), not to the edit.
- One command is one atomic edit. The result is validated as a whole `Project` (`model_validate`, not
  `model_copy`), so a command that would leave a reference dangling, a range broken or an id duplicated is
  rejected and nothing changes. A `Project` that exists has no dangling state; a command cannot build one.
- Removing something removes what hangs on it in the same command. `RemoveInstance` takes the instance's
  joints, the actuators on the instance or on those joints, and those actuators' schedule entries with it;
  `RemoveJoint` takes the actuators on the joint and their entries; `RemoveActuator` takes its entries. The
  inverse is a `CommandBatch` that adds all of it back at the original positions. Definitions are the
  exception: `RemovePartDef` and `RemoveMaterialDef` are rejected while anything uses the definition
  (`in_use`), because the user never deleted the users.
- Lists keep order (`project-model.md`: order is part of the value). An `Add*` takes an optional `index`
  (default: the end) so an inverse can put the item back where it was.
- `CommandBatch` is a group applied in order, all or nothing (`client-adapter.md` C2). Only edit commands go in
  a batch (no nesting). Its inverse is a batch of the inverses in reverse order. One history entry per batch is
  C-02b's.
- `MoveInstance` sets the stored pose of one instance and moves nothing else; joints do not drag their
  partners (`project-model.md`: the pose is the authority). A gizmo that moves an assembly sends a batch.
  Whether the joined snap points still meet is the placement check (C-02c).
- There is deliberately no command that carries a planet constant, a material value change or a verdict
  (`client-adapter.md` C4): `SelectPlanet` names a planet by id and `AddMaterialDef` embeds a whole definition
  (an edit of a value is a remove and an add, visible in history). Which origins may send material or part
  definitions at all is C-02c's policy.

Not here: the issuer and history (C-02b), policy checks and the reason texts of placement (C-02c), save format
and hashes (C-03), the wire messages (C-05a), terrain prop edits (W-05), water (FL-02b), release entries (X-08).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .assumption import Assumption
from .conventions import ID_PATTERN
from .designspec import ActuateEntry, Actuator, Instance, Joint, ParamValue, Pose
from .geometry import Name
from .material import Material
from .partdef import PartDef
from .project import Project

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_Index = Annotated[int, Field(strict=True, ge=0)]


class ReasonCode(StrEnum):
    UNKNOWN_ID = "unknown_id"
    DUPLICATE_ID = "duplicate_id"
    IN_USE = "in_use"
    INDEX_OUT_OF_RANGE = "index_out_of_range"
    INVALID_COMMAND = "invalid_command"
    INVALID_PROJECT = "invalid_project"


class Reason(BaseModel):
    """Why a command was rejected: a stable `code`, a readable sentence and the ids it is about."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ReasonCode
    message: str = Field(min_length=1)
    ids: tuple[str, ...] = ()


class CommandRejected(Exception):
    """The command (or a command of the batch) was refused. The project it was applied to is unchanged."""

    def __init__(self, reasons: tuple[Reason, ...]):
        self.reasons = reasons
        super().__init__("; ".join(f"[{r.code.value}] {r.message}" for r in reasons))


class _Cmd(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- definitions ------------------------------------------------------------------------------------------


class AddPartDef(_Cmd):
    """Put a part definition into the project (`DesignSpec` carries the definitions it uses)."""

    type: Literal["add_part_def"]
    part: PartDef
    index: _Index | None = None


class RemovePartDef(_Cmd):
    """Take a part definition out. Rejected while an instance uses it."""

    type: Literal["remove_part_def"]
    id: _Id


class AddMaterialDef(_Cmd):
    type: Literal["add_material_def"]
    material: Material
    index: _Index | None = None


class RemoveMaterialDef(_Cmd):
    """Take a material definition out. Rejected while an instance or a terrain prop uses it."""

    type: Literal["remove_material_def"]
    id: _Id


# --- instances --------------------------------------------------------------------------------------------


class AddInstance(_Cmd):
    type: Literal["add_instance"]
    instance: Instance
    index: _Index | None = None


class RemoveInstance(_Cmd):
    """Delete an instance with its joints, the actuators on it or on those joints, and their schedule entries."""

    type: Literal["remove_instance"]
    id: _Id


class MoveInstance(_Cmd):
    """Set the stored world pose of one instance."""

    type: Literal["move_instance"]
    id: _Id
    pose: Pose


class SetParameter(_Cmd):
    """Set a parameter of an instance (unit and range are the part's). `index` is where a parameter that is not
    set yet goes in the instance's list; for one that is set already it must be absent."""

    type: Literal["set_parameter"]
    instance: _Id
    parameter: ParamValue
    index: _Index | None = None


class ClearParameter(_Cmd):
    """Unset a parameter of an instance: it takes the part's default again."""

    type: Literal["clear_parameter"]
    instance: _Id
    name: Name


class SetInstanceMaterial(_Cmd):
    """Assign a material of the project to an instance; `None` assigns none."""

    type: Literal["set_instance_material"]
    id: _Id
    material: _Id | None


# --- joints ------------------------------------------------------------------------------------------------


class AddJoint(_Cmd):
    type: Literal["add_joint"]
    joint: Joint
    index: _Index | None = None


class RemoveJoint(_Cmd):
    """Release a joint, with the actuators that drive it and their schedule entries."""

    type: Literal["remove_joint"]
    id: _Id


# --- actuators and control ---------------------------------------------------------------------------------


class AddActuator(_Cmd):
    type: Literal["add_actuator"]
    actuator: Actuator
    index: _Index | None = None


class RemoveActuator(_Cmd):
    """Remove an actuator with its schedule entries."""

    type: Literal["remove_actuator"]
    id: _Id


class AddControlEntry(_Cmd):
    type: Literal["add_control_entry"]
    entry: ActuateEntry
    index: _Index | None = None


class RemoveControlEntry(_Cmd):
    """Remove the schedule entry at `index` (entries have no id; the position is the identity)."""

    type: Literal["remove_control_entry"]
    index: _Index


class ReplaceControlEntry(_Cmd):
    type: Literal["replace_control_entry"]
    index: _Index
    entry: ActuateEntry


# --- assumptions and world ---------------------------------------------------------------------------------


class AddAssumption(_Cmd):
    type: Literal["add_assumption"]
    assumption: Assumption
    index: _Index | None = None


class SetAssumption(_Cmd):
    """Replace the assumption with the same `key`, in place."""

    type: Literal["set_assumption"]
    assumption: Assumption


class RemoveAssumption(_Cmd):
    type: Literal["remove_assumption"]
    key: Annotated[str, Field(min_length=1)]


class SelectPlanet(_Cmd):
    """Put the project on another planet, by id. The planet's constants are not part of any command."""

    type: Literal["select_planet"]
    planet: _Id


_EditCommands = Union[
    AddPartDef,
    RemovePartDef,
    AddMaterialDef,
    RemoveMaterialDef,
    AddInstance,
    RemoveInstance,
    MoveInstance,
    SetParameter,
    ClearParameter,
    SetInstanceMaterial,
    AddJoint,
    RemoveJoint,
    AddActuator,
    RemoveActuator,
    AddControlEntry,
    RemoveControlEntry,
    ReplaceControlEntry,
    AddAssumption,
    SetAssumption,
    RemoveAssumption,
    SelectPlanet,
]

EditCommand = Annotated[_EditCommands, Field(discriminator="type")]
"""One edit. What can be in a `CommandBatch`."""


class CommandBatch(_Cmd):
    """Edits applied in order as one: all of them or none (`client-adapter.md` C2)."""

    type: Literal["batch"]
    commands: tuple[EditCommand, ...] = Field(min_length=1)


Command = Annotated[Union[_EditCommands, CommandBatch], Field(discriminator="type")]
"""Any command: one edit or a batch of edits."""


class Applied(BaseModel):
    """The result of `apply_command`: the new project and the command that undoes the edit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project: Project
    inverse: Command


# --- applier ------------------------------------------------------------------------------------------------


def _reject(code: ReasonCode, message: str, *ids: str) -> CommandRejected:
    return CommandRejected((Reason(code=code, message=message, ids=ids),))


def _dump(model: BaseModel) -> dict:
    return model.model_dump(mode="json")


def _rebuild(project: Project, edit, ids: tuple[str, ...]) -> Project:
    """Apply `edit` to the JSON form of `project` and validate the whole result."""
    data = project.model_dump(mode="json")
    edit(data)
    try:
        return Project.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
            if err["loc"]
            else err["msg"].removeprefix("Value error, ")
            for err in e.errors()
        )
        raise _reject(ReasonCode.INVALID_PROJECT, f"the result would not be a valid project: {problems}", *ids) from e


def _find(items, ident: str, what: str, attr: str = "id") -> int:
    for n, item in enumerate(items):
        if getattr(item, attr) == ident:
            return n
    raise _reject(ReasonCode.UNKNOWN_ID, f"no {what} {ident!r}", ident)


def _absent(items, ident: str, what: str, attr: str = "id") -> None:
    if any(getattr(item, attr) == ident for item in items):
        raise _reject(ReasonCode.DUPLICATE_ID, f"{what} {ident!r} already exists", ident)


def _slot(index: int | None, length: int, what: str, *ids: str) -> int:
    """Where an inserted item goes: `index`, or the end."""
    at = length if index is None else index
    if at > length:
        raise _reject(ReasonCode.INDEX_OUT_OF_RANGE, f"index {at} is past the end of {what} (length {length})", *ids)
    return at


def _existing(index: int, length: int, what: str) -> int:
    if index >= length:
        raise _reject(ReasonCode.INDEX_OUT_OF_RANGE, f"{what} has no entry at index {index} (length {length})")
    return index


def _instance_json(data: dict, ident: str) -> dict:
    return next(i for i in data["design"]["instances"] if i["id"] == ident)


def _dependents(project: Project, *, instance=None, joint_ids=(), actuator_ids=()):
    """What hangs on an instance, joints or actuators: (index, model) lists of joints, actuators, entries."""
    d = project.design
    joints = [(n, j) for n, j in enumerate(d.joints) if j.id in joint_ids or instance in (j.a.instance, j.b.instance)]
    removed_joints = {j.id for _, j in joints}
    actuators = [
        (n, a)
        for n, a in enumerate(d.actuators)
        if a.id in actuator_ids or a.instance == instance or (a.joint is not None and a.joint in removed_joints)
    ]
    removed_actuators = {a.id for _, a in actuators}
    entries = [(n, e) for n, e in enumerate(d.schedule.entries) if e.actuator in removed_actuators]
    return joints, actuators, entries


def _drop_dependents(data: dict, joints, actuators, entries) -> None:
    design = data["design"]
    joint_ids, actuator_ids, entry_at = {j.id for _, j in joints}, {a.id for _, a in actuators}, {n for n, _ in entries}
    design["joints"] = [j for j in design["joints"] if j["id"] not in joint_ids]
    design["actuators"] = [a for a in design["actuators"] if a["id"] not in actuator_ids]
    design["schedule"]["entries"] = [e for n, e in enumerate(design["schedule"]["entries"]) if n not in entry_at]


def _restore(joints, actuators, entries) -> tuple[EditCommand, ...]:
    """Add back, in original order, so each list ends up exactly as it was: joints, then the actuators on them,
    then their entries (every step validates on its own)."""
    return (
        *(AddJoint(type="add_joint", joint=j, index=n) for n, j in joints),
        *(AddActuator(type="add_actuator", actuator=a, index=n) for n, a in actuators),
        *(AddControlEntry(type="add_control_entry", entry=e, index=n) for n, e in entries),
    )


def _apply_edit(project: Project, c: EditCommand) -> tuple[Project, tuple[EditCommand, ...]]:
    """One edit. Returns the new project and the inverse as edits to apply in order."""
    d = project.design
    match c:
        case AddPartDef():
            _absent(d.parts, c.part.id, "part")
            at = _slot(c.index, len(d.parts), "parts", c.part.id)
            new = _rebuild(project, lambda x: x["design"]["parts"].insert(at, _dump(c.part)), (c.part.id,))
            return new, (RemovePartDef(type="remove_part_def", id=c.part.id),)

        case RemovePartDef():
            at = _find(d.parts, c.id, "part definition")
            users = [i.id for i in d.instances if i.part == c.id]
            if users:
                raise _reject(ReasonCode.IN_USE, f"part {c.id!r} is used by instances {users}", c.id, *users)
            new = _rebuild(project, lambda x: x["design"]["parts"].pop(at), (c.id,))
            return new, (AddPartDef(type="add_part_def", part=d.parts[at], index=at),)

        case AddMaterialDef():
            _absent(d.materials, c.material.id, "material")
            at = _slot(c.index, len(d.materials), "materials", c.material.id)
            new = _rebuild(project, lambda x: x["design"]["materials"].insert(at, _dump(c.material)), (c.material.id,))
            return new, (RemoveMaterialDef(type="remove_material_def", id=c.material.id),)

        case RemoveMaterialDef():
            at = _find(d.materials, c.id, "material definition")
            users = [i.id for i in d.instances if i.material == c.id]
            users += [p.id for p in project.world.terrain_props if p.material == c.id]
            if users:
                raise _reject(ReasonCode.IN_USE, f"material {c.id!r} is used by {users}", c.id, *users)
            new = _rebuild(project, lambda x: x["design"]["materials"].pop(at), (c.id,))
            return new, (AddMaterialDef(type="add_material_def", material=d.materials[at], index=at),)

        case AddInstance():
            _absent(d.instances, c.instance.id, "instance")
            at = _slot(c.index, len(d.instances), "instances", c.instance.id)
            new = _rebuild(project, lambda x: x["design"]["instances"].insert(at, _dump(c.instance)), (c.instance.id,))
            return new, (RemoveInstance(type="remove_instance", id=c.instance.id),)

        case RemoveInstance():
            at = _find(d.instances, c.id, "instance")
            joints, actuators, entries = _dependents(project, instance=c.id)

            def edit(x):
                x["design"]["instances"].pop(at)
                _drop_dependents(x, joints, actuators, entries)

            new = _rebuild(project, edit, (c.id,))
            return new, (AddInstance(type="add_instance", instance=d.instances[at], index=at), *_restore(joints, actuators, entries))

        case MoveInstance():
            at = _find(d.instances, c.id, "instance")
            new = _rebuild(project, lambda x: _instance_json(x, c.id).update(pose=_dump(c.pose)), (c.id,))
            return new, (MoveInstance(type="move_instance", id=c.id, pose=d.instances[at].pose),)

        case SetParameter():
            at = _find(d.instances, c.instance, "instance")
            inst = d.instances[at]
            names = [v.name for v in inst.parameters]
            ids = (c.instance, c.parameter.name)
            if c.parameter.name in names:
                if c.index is not None:
                    raise _reject(ReasonCode.INVALID_COMMAND, f"{c.parameter.name!r} is set already: no index", *ids)
                k = names.index(c.parameter.name)
                new = _rebuild(project, lambda x: _instance_json(x, c.instance)["parameters"].__setitem__(k, _dump(c.parameter)), ids)
                return new, (SetParameter(type="set_parameter", instance=c.instance, parameter=inst.parameters[k]),)
            k = _slot(c.index, len(names), f"parameters of {c.instance!r}", *ids)
            new = _rebuild(project, lambda x: _instance_json(x, c.instance)["parameters"].insert(k, _dump(c.parameter)), ids)
            return new, (ClearParameter(type="clear_parameter", instance=c.instance, name=c.parameter.name),)

        case ClearParameter():
            at = _find(d.instances, c.instance, "instance")
            inst = d.instances[at]
            names = [v.name for v in inst.parameters]
            if c.name not in names:
                raise _reject(ReasonCode.UNKNOWN_ID, f"instance {c.instance!r} has no parameter {c.name!r} set", c.instance, c.name)
            k = names.index(c.name)
            new = _rebuild(project, lambda x: _instance_json(x, c.instance)["parameters"].pop(k), (c.instance, c.name))
            return new, (SetParameter(type="set_parameter", instance=c.instance, parameter=inst.parameters[k], index=k),)

        case SetInstanceMaterial():
            at = _find(d.instances, c.id, "instance")
            ids = (c.id,) if c.material is None else (c.id, c.material)
            new = _rebuild(project, lambda x: _instance_json(x, c.id).update(material=c.material), ids)
            return new, (SetInstanceMaterial(type="set_instance_material", id=c.id, material=d.instances[at].material),)

        case AddJoint():
            _absent(d.joints, c.joint.id, "joint")
            at = _slot(c.index, len(d.joints), "joints", c.joint.id)
            new = _rebuild(project, lambda x: x["design"]["joints"].insert(at, _dump(c.joint)), (c.joint.id,))
            return new, (RemoveJoint(type="remove_joint", id=c.joint.id),)

        case RemoveJoint():
            at = _find(d.joints, c.id, "joint")
            joints, actuators, entries = _dependents(project, joint_ids={c.id})
            new = _rebuild(project, lambda x: _drop_dependents(x, joints, actuators, entries), (c.id,))
            return new, _restore(joints, actuators, entries)

        case AddActuator():
            _absent(d.actuators, c.actuator.id, "actuator")
            at = _slot(c.index, len(d.actuators), "actuators", c.actuator.id)
            new = _rebuild(project, lambda x: x["design"]["actuators"].insert(at, _dump(c.actuator)), (c.actuator.id,))
            return new, (RemoveActuator(type="remove_actuator", id=c.actuator.id),)

        case RemoveActuator():
            at = _find(d.actuators, c.id, "actuator")
            joints, actuators, entries = _dependents(project, actuator_ids={c.id})
            new = _rebuild(project, lambda x: _drop_dependents(x, joints, actuators, entries), (c.id,))
            return new, _restore(joints, actuators, entries)

        case AddControlEntry():
            entries = d.schedule.entries
            at = _slot(c.index, len(entries), "schedule entries", c.entry.actuator)
            new = _rebuild(project, lambda x: x["design"]["schedule"]["entries"].insert(at, _dump(c.entry)), (c.entry.actuator,))
            return new, (RemoveControlEntry(type="remove_control_entry", index=at),)

        case RemoveControlEntry():
            at = _existing(c.index, len(d.schedule.entries), "the schedule")
            new = _rebuild(project, lambda x: x["design"]["schedule"]["entries"].pop(at), ())
            return new, (AddControlEntry(type="add_control_entry", entry=d.schedule.entries[at], index=at),)

        case ReplaceControlEntry():
            at = _existing(c.index, len(d.schedule.entries), "the schedule")
            new = _rebuild(project, lambda x: x["design"]["schedule"]["entries"].__setitem__(at, _dump(c.entry)), (c.entry.actuator,))
            return new, (ReplaceControlEntry(type="replace_control_entry", index=at, entry=d.schedule.entries[at]),)

        case AddAssumption():
            table = project.assumptions.assumptions
            _absent(table, c.assumption.key, "assumption", "key")
            at = _slot(c.index, len(table), "assumptions", c.assumption.key)
            new = _rebuild(project, lambda x: x["assumptions"]["assumptions"].insert(at, _dump(c.assumption)), (c.assumption.key,))
            return new, (RemoveAssumption(type="remove_assumption", key=c.assumption.key),)

        case SetAssumption():
            table = project.assumptions.assumptions
            at = _find(table, c.assumption.key, "assumption", "key")
            new = _rebuild(project, lambda x: x["assumptions"]["assumptions"].__setitem__(at, _dump(c.assumption)), (c.assumption.key,))
            return new, (SetAssumption(type="set_assumption", assumption=table[at]),)

        case RemoveAssumption():
            table = project.assumptions.assumptions
            at = _find(table, c.key, "assumption", "key")
            new = _rebuild(project, lambda x: x["assumptions"]["assumptions"].pop(at), (c.key,))
            return new, (AddAssumption(type="add_assumption", assumption=table[at], index=at),)

        case SelectPlanet():
            new = _rebuild(project, lambda x: x["world"].update(planet=c.planet), (c.planet,))
            return new, (SelectPlanet(type="select_planet", planet=project.world.planet),)

    raise AssertionError(f"unhandled command {type(c).__name__}")  # pragma: no cover  (the union is closed)


def _pack(edits: tuple[EditCommand, ...]) -> Command:
    return edits[0] if len(edits) == 1 else CommandBatch(type="batch", commands=edits)


def apply_command(project: Project, command: Command) -> Applied:
    """Apply `command` to `project`. Returns the new project and the inverse command; raises `CommandRejected`
    (project untouched) when the edit is refused or its result would not be a valid `Project`."""
    if not isinstance(command, CommandBatch):
        new, inverse = _apply_edit(project, command)
        return Applied(project=new, inverse=_pack(inverse))
    current, inverse = project, ()
    for n, edit in enumerate(command.commands):
        try:
            current, undo = _apply_edit(current, edit)
        except CommandRejected as e:
            raise CommandRejected(
                tuple(Reason(code=r.code, message=f"commands[{n}] ({edit.type}): {r.message}", ids=r.ids) for r in e.reasons)
            ) from e
        inverse = undo + inverse
    return Applied(project=current, inverse=_pack(inverse))
