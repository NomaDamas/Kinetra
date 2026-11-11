"""`Command` and the applier (C-02a): every edit of a `Project` is one of these, whoever sends it.

`apply_command(project, command)` returns `ApplyResult(project, inverse)`: a new validated `Project` and the command
that undoes this one. It never mutates its input and either returns a valid `Project` or raises `CommandRejected`
with reasons (code, sentence, typed refs; `client-adapter.md` 3.2 `rejected`). Applying the inverse to the new
project gives back a project equal to the original (order of every collection included), and the inverse's inverse
redoes the edit. C-02b builds undo, redo and history on that pair; C-02c (`validator.py`) adds the policy checks (placement,
planet constants, the material catalog, verdicts); C-05a puts the commands on the wire.

Shape rules (read by C-02b, C-02c, C-03, C-05a, XR-02):

- A command is a frozen pydantic model with a required literal `type` tag. `Command` is the discriminated union
  of them, so JSON from any client (`schemas/Command.schema.json`) parses to one exact command or fails.
- A command says it in the document's words (`client-adapter.md` I2): ids, parameter names, SI values with
  badge and source. No screen coordinates, no device poses. It does not name who sent it: the issuer belongs to
  the history record (C-02b), not to the edit.
- Things are named by id, never by position. A command made against revision N must not silently edit another
  thing when it is applied to N+1 or after a partial accept of a batch (`client-adapter.md` C2, C5): an id that
  is gone is `unknown_id`. `index` exists only on `add_*`, as where to put the new item (default: the end); it
  never says which existing item to change.
- One command is one atomic edit. The result is validated as a whole `Project` (`model_validate`, not
  `model_copy`), so a command that would leave a reference dangling, a range broken or an id duplicated is
  rejected and nothing changes. A `Project` that exists has no dangling state; a command cannot build one.
- Removing something removes what hangs on it in the same command. `RemoveInstance` takes the instance's
  joints, the actuators on the instance or on those joints, and those actuators' schedule entries with it;
  `RemoveJoint` takes the actuators on the joint and their entries; `RemoveActuator` takes its entries. The
  inverse is a `CommandBatch` that adds all of it back at the original positions. Definitions are the
  exception: `RemovePartDef` and `RemoveMaterialDef` are rejected while anything uses the definition
  (`in_use`), because the user never deleted the users. A definition that is in use cannot be removed by any
  command; it can be replaced in place (next point).
- Lists keep order (`project-model.md`: order is part of the value). `ReplacePartDef`, `ReplaceMaterialDef`,
  `ReplaceJoint`, `ReplaceControlEntry`, `SetAssumption` change the item with the same id in place: position and
  everything that references the id stay. The whole project is validated again, so a replacement that breaks a
  user (a part without a parameter an instance sets, a joint that is fixed now under a motor, an instance
  parameter outside the new range) is rejected with the validator's sentence and the ref of what broke.
  Replacing a definition in place keeps the usage: the user is never asked to remove it first.
- `CommandBatch` is a group applied in order, all or nothing (`client-adapter.md` C2). Only edit commands go in
  a batch (no nesting). Its inverse is a batch of the inverses in reverse order. One history entry per batch is
  C-02b's. **Every intermediate state of a batch must be a valid `Project`, not only the last one**: a batch
  that swaps the time slots of two entries of one actuator is rejected at its first command for overlapping.
  Order the commands so each step is valid (remove or shorten first, then add), or use a `replace_*` command.
- `MoveInstance` sets the stored pose of one instance and moves nothing else; joints do not drag their
  partners (`project-model.md`: the pose is the authority). A gizmo that moves an assembly sends a batch.
  Whether the joined snap points still meet is the placement check (C-02c).
- A command that sets what is already there (same planet, same material, same pose) is accepted and returns an
  equal project. `apply_command` does not filter it; C-02b decides whether an empty history entry or a verdict
  invalidation (`client-adapter.md` D5) is worth it, by comparing `result.project == project`.
- Assumptions with `editable: false` are the system's (a template or the engine put them there): `add_assumption`
  refuses to create one, `set_assumption` and `remove_assumption` refuse to touch one and `set_assumption` cannot
  change `editable` (all `not_editable`). That keeps every inverse applicable.
- There is deliberately no command that carries a planet constant, or a verdict (`client-adapter.md` C4):
  `SelectPlanet` names a planet by id. A material or part definition is replaced as a whole and only by id; which
  origins may send definition commands at all: none is allowed or refused by origin (C-02c: the validator takes no origin).
- Cost: every edit dumps the project to JSON and validates all of it again, so one edit costs O(project) and a
  batch of n edits n x O(project) (about 11 ms per edit at 200 instances, 25 ms at 1000, measured in the
  review of #497). Tracked in its own issue; it does not change the command shapes.

Not here: the issuer and history (C-02b), policy checks and placement (C-02c, `validator.py`), save format
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
from .missing import MissingDefinition
from .partdef import PartDef
from .project import Project
from .refs import Ref, RefError, RefKind

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_Index = Annotated[int, Field(strict=True, ge=0)]


class ReasonCode(StrEnum):
    UNKNOWN_ID = "unknown_id"
    DUPLICATE_ID = "duplicate_id"
    IN_USE = "in_use"
    INDEX_OUT_OF_RANGE = "index_out_of_range"
    INVALID_COMMAND = "invalid_command"
    INVALID_PROJECT = "invalid_project"
    NOT_EDITABLE = "not_editable"
    FORBIDDEN = "forbidden"  # C-02c: planet constants, the material catalog, verdicts
    MISSING_DEFINITION = "missing_definition"  # C-06: a project with an instance whose part or material it does not carry
    INVALID_SNAP = "invalid_snap"  # C-02c: a joint whose snap points do not accept each other or do not meet
    OVERLAP = "overlap"  # C-02c: interpenetrating parts, or a part below the ground
    FLOATING = "floating"  # C-02c: nothing connects the part to the ground
    NOTHING_TO_UNDO = "nothing_to_undo"
    NOTHING_TO_REDO = "nothing_to_redo"


class Reason(BaseModel):
    """Why a command was rejected: a stable `code`, a readable sentence and what it is about. `ids` are typed
    refs (`kind` and `id`) because an id is only unique inside its own collection: a part `wheel` and an instance
    `wheel` are different things."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ReasonCode
    message: str = Field(min_length=1)
    ids: tuple[Ref, ...] = ()


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


class ReplacePartDef(_Cmd):
    """Replace the part definition with the same id, in place. Instances keep using it, so the new definition
    must still suit every one of them (their parameters, their joints' snap points): else the command is
    rejected with the validator's sentence and the offending ref."""

    type: Literal["replace_part_def"]
    part: PartDef


class RemovePartDef(_Cmd):
    """Take a part definition out. Rejected while an instance uses it, unless `unlink` is set: then the instances
    that use it stay as placeholders without a definition (C-06). `unlink` is what the inverse of an `add_part_def`
    that gave placeholders their definition says, so that undo can put the placeholders back; the validator refuses
    it from any sender (`missing_definition`: a command never creates a placeholder)."""

    type: Literal["remove_part_def"]
    id: _Id
    unlink: bool = False


class AddMaterialDef(_Cmd):
    type: Literal["add_material_def"]
    material: Material
    index: _Index | None = None


class ReplaceMaterialDef(_Cmd):
    """Replace the material definition with the same id, in place (instances and terrain props keep using it)."""

    type: Literal["replace_material_def"]
    material: Material


class RemoveMaterialDef(_Cmd):
    """Take a material definition out. Rejected while an instance or a terrain prop uses it, unless `unlink` is set:
    then the instances that use it stay without a definition (C-06; see `RemovePartDef`). A terrain prop that uses
    it still refuses."""

    type: Literal["remove_material_def"]
    id: _Id
    unlink: bool = False


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


class RelinkInstance(_Cmd):
    """Point an instance at another part definition of the project: the way back for an instance whose definition is
    missing (C-06, `docs/architecture/missing-definitions.md`; the other ways are `add_part_def` with the missing id
    and `remove_instance`). The part must be one the project carries and must suit the instance (its parameters and
    its joints' snap points): else the command is rejected with the validator's sentence and the offending ref."""

    type: Literal["relink_instance"]
    id: _Id
    part: _Id


# --- joints ------------------------------------------------------------------------------------------------


class AddJoint(_Cmd):
    type: Literal["add_joint"]
    joint: Joint
    index: _Index | None = None


class ReplaceJoint(_Cmd):
    """Replace the joint with the same id, in place: same position, and the actuators and schedule entries on it
    stay. Changes its limits, break threshold, kind or ends. Rejected if the new joint no longer suits what is on
    it (a motor on a joint that is fixed now, a motor whose instance is no longer at an end)."""

    type: Literal["replace_joint"]
    joint: Joint


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
    """Add a schedule entry. `index` is only where it goes in the list; the entry is known by its `id`."""

    type: Literal["add_control_entry"]
    entry: ActuateEntry
    index: _Index | None = None


class RemoveControlEntry(_Cmd):
    """Remove the schedule entry with this id."""

    type: Literal["remove_control_entry"]
    id: _Id


class ReplaceControlEntry(_Cmd):
    """Replace the schedule entry with the same id (`entry.id`), in place."""

    type: Literal["replace_control_entry"]
    entry: ActuateEntry


# --- assumptions and world ---------------------------------------------------------------------------------


class AddAssumption(_Cmd):
    """Add an assumption. It must be `editable`: one that is not could never be changed or removed again, so its
    inverse would not apply."""

    type: Literal["add_assumption"]
    assumption: Assumption
    index: _Index | None = None


class SetAssumption(_Cmd):
    """Replace the assumption with the same `key`, in place. Refused (`not_editable`) when the stored one is not
    `editable`, and when the new one would change `editable`."""

    type: Literal["set_assumption"]
    assumption: Assumption


class RemoveAssumption(_Cmd):
    """Remove the assumption with this key. Refused (`not_editable`) when it is not `editable`."""

    type: Literal["remove_assumption"]
    key: Name


class SelectPlanet(_Cmd):
    """Put the project on another planet, by id. The planet's constants are not part of any command."""

    type: Literal["select_planet"]
    planet: _Id


_EditCommands = Union[
    AddPartDef,
    ReplacePartDef,
    RemovePartDef,
    AddMaterialDef,
    ReplaceMaterialDef,
    RemoveMaterialDef,
    AddInstance,
    RemoveInstance,
    MoveInstance,
    SetParameter,
    ClearParameter,
    SetInstanceMaterial,
    RelinkInstance,
    AddJoint,
    ReplaceJoint,
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
    """Edits applied in order as one: all of them or none (`client-adapter.md` C2). Every intermediate state
    must be a valid `Project` (see the module docstring)."""

    type: Literal["batch"]
    commands: tuple[EditCommand, ...] = Field(min_length=1)


Command = Annotated[Union[_EditCommands, CommandBatch], Field(discriminator="type")]
"""Any command: one edit or a batch of edits."""


class ApplyResult(BaseModel):
    """The result of `apply_command`: the new project and the command that undoes the edit. Not the wire message
    `applied` of `client-adapter.md` 3.1 (revision number, issuer, changed parts): C-05a builds that from this."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project: Project
    inverse: Command


# --- applier ------------------------------------------------------------------------------------------------


def _ref(kind: RefKind, ident: str) -> Ref:
    return Ref(kind=kind, id=ident)


def _reject(code: ReasonCode, message: str, *refs: Ref) -> CommandRejected:
    return CommandRejected((Reason(code=code, message=message, ids=refs),))


def _dump(model: BaseModel) -> dict:
    return model.model_dump(mode="json")


def _rebuild(project: Project, edit, refs: tuple[Ref, ...]) -> Project:
    """Apply `edit` to the JSON form of `project` and validate the whole result. A refusal by a validator comes
    back as one reason per problem, carrying the refs the validator named (the dangling id, not just the command's
    own); `refs` (what the command is about) stand in when the validator named none."""
    data = project.model_dump(mode="json")
    edit(data)
    try:
        return Project.model_validate(data)
    except ValidationError as e:
        reasons = []
        for err in e.errors():
            cause = err.get("ctx", {}).get("error")
            named = cause.refs if isinstance(cause, RefError) else ()
            where = ".".join(str(part) for part in err["loc"])
            text = err["msg"].removeprefix("Value error, ")
            reasons.append(
                Reason(
                    code=ReasonCode.INVALID_PROJECT,
                    message=f"the result would not be a valid project: {where + ': ' if where else ''}{text}",
                    ids=named or refs,
                )
            )
        raise CommandRejected(tuple(reasons)) from e


def _find(items, ident: str, kind: RefKind, what: str, attr: str = "id") -> int:
    for n, item in enumerate(items):
        if getattr(item, attr) == ident:
            return n
    raise _reject(ReasonCode.UNKNOWN_ID, f"no {what} {ident!r}", _ref(kind, ident))


def _absent(items, ident: str, kind: RefKind, what: str, attr: str = "id") -> None:
    if any(getattr(item, attr) == ident for item in items):
        raise _reject(ReasonCode.DUPLICATE_ID, f"{what} {ident!r} already exists", _ref(kind, ident))


def _slot(index: int | None, length: int, what: str, *refs: Ref) -> int:
    """Where an inserted item goes: `index`, or the end."""
    at = length if index is None else index
    if at > length:
        raise _reject(ReasonCode.INDEX_OUT_OF_RANGE, f"index {at} is past the end of {what} (length {length})", *refs)
    return at


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
    joint_ids, actuator_ids, entry_ids = {j.id for _, j in joints}, {a.id for _, a in actuators}, {e.id for _, e in entries}
    design["joints"] = [j for j in design["joints"] if j["id"] not in joint_ids]
    design["actuators"] = [a for a in design["actuators"] if a["id"] not in actuator_ids]
    design["schedule"]["entries"] = [e for e in design["schedule"]["entries"] if e["id"] not in entry_ids]


def _restore(joints, actuators, entries) -> tuple[EditCommand, ...]:
    """Add back, in original order, so each list ends up exactly as it was: joints, then the actuators on them,
    then their entries (every step validates on its own)."""
    return (
        *(AddJoint(type="add_joint", joint=j, index=n) for n, j in joints),
        *(AddActuator(type="add_actuator", actuator=a, index=n) for n, a in actuators),
        *(AddControlEntry(type="add_control_entry", entry=e, index=n) for n, e in entries),
    )


def _replace_in_place(project, command_refs, collection, ident, model, key="id"):
    """Rebuild with the item whose `key` is `ident` swapped for `model`; returns the new project."""

    def edit(x):
        items = collection(x)
        at = next(n for n, item in enumerate(items) if item[key] == ident)
        items[at] = _dump(model)

    return _rebuild(project, edit, command_refs)


def missing_reasons(missing: tuple[MissingDefinition, ...]) -> tuple[Reason, ...]:
    """One `missing_definition` reason per missing definition: its refs are the definition, then its instances."""
    return tuple(
        Reason(
            code=ReasonCode.MISSING_DEFINITION,
            message=f"{m.kind} {m.id!r} has no definition in the project (used by instances {list(m.instances)})",
            ids=(Ref(kind=RefKind(m.kind), id=m.id), *(Ref(kind=RefKind.INSTANCE, id=i) for i in m.instances)),
        )
        for m in missing
    )


def _apply_edit(project: Project, c: EditCommand) -> tuple[Project, tuple[EditCommand, ...]]:
    """One edit. Returns the new project and the inverse as edits to apply in order."""
    d = project.design
    match c:
        case AddPartDef():
            ref = _ref(RefKind.PART, c.part.id)
            _absent(d.parts, c.part.id, RefKind.PART, "part")
            at = _slot(c.index, len(d.parts), "parts", ref)
            new = _rebuild(project, lambda x: x["design"]["parts"].insert(at, _dump(c.part)), (ref,))
            relinks = any(i.part == c.part.id for i in d.instances)  # placeholders get their definition: undo makes them again
            return new, (RemovePartDef(type="remove_part_def", id=c.part.id, unlink=relinks),)

        case ReplacePartDef():
            ref = _ref(RefKind.PART, c.part.id)
            at = _find(d.parts, c.part.id, RefKind.PART, "part definition")
            new = _replace_in_place(project, (ref,), lambda x: x["design"]["parts"], c.part.id, c.part)
            return new, (ReplacePartDef(type="replace_part_def", part=d.parts[at]),)

        case RemovePartDef():
            at = _find(d.parts, c.id, RefKind.PART, "part definition")
            users = [i.id for i in d.instances if i.part == c.id]
            if users and not c.unlink:
                raise _reject(
                    ReasonCode.IN_USE,
                    f"part {c.id!r} is used by instances {users}",
                    _ref(RefKind.PART, c.id),
                    *(_ref(RefKind.INSTANCE, u) for u in users),
                )
            new = _rebuild(project, lambda x: x["design"]["parts"].pop(at), (_ref(RefKind.PART, c.id),))
            return new, (AddPartDef(type="add_part_def", part=d.parts[at], index=at),)

        case AddMaterialDef():
            ref = _ref(RefKind.MATERIAL, c.material.id)
            _absent(d.materials, c.material.id, RefKind.MATERIAL, "material")
            at = _slot(c.index, len(d.materials), "materials", ref)
            new = _rebuild(project, lambda x: x["design"]["materials"].insert(at, _dump(c.material)), (ref,))
            relinks = any(i.material == c.material.id for i in d.instances)
            return new, (RemoveMaterialDef(type="remove_material_def", id=c.material.id, unlink=relinks),)

        case ReplaceMaterialDef():
            ref = _ref(RefKind.MATERIAL, c.material.id)
            at = _find(d.materials, c.material.id, RefKind.MATERIAL, "material definition")
            new = _replace_in_place(project, (ref,), lambda x: x["design"]["materials"], c.material.id, c.material)
            return new, (ReplaceMaterialDef(type="replace_material_def", material=d.materials[at]),)

        case RemoveMaterialDef():
            at = _find(d.materials, c.id, RefKind.MATERIAL, "material definition")
            users = [_ref(RefKind.INSTANCE, i.id) for i in d.instances if i.material == c.id]
            users += [_ref(RefKind.PROP, p.id) for p in project.world.terrain_props if p.material == c.id]
            if any(u.kind is RefKind.PROP for u in users) or (users and not c.unlink):
                raise _reject(
                    ReasonCode.IN_USE,
                    f"material {c.id!r} is used by {[u.id for u in users]}",
                    _ref(RefKind.MATERIAL, c.id),
                    *users,
                )
            new = _rebuild(project, lambda x: x["design"]["materials"].pop(at), (_ref(RefKind.MATERIAL, c.id),))
            return new, (AddMaterialDef(type="add_material_def", material=d.materials[at], index=at),)

        case AddInstance():
            ref = _ref(RefKind.INSTANCE, c.instance.id)
            _absent(d.instances, c.instance.id, RefKind.INSTANCE, "instance")
            at = _slot(c.index, len(d.instances), "instances", ref)
            new = _rebuild(project, lambda x: x["design"]["instances"].insert(at, _dump(c.instance)), (ref,))
            return new, (RemoveInstance(type="remove_instance", id=c.instance.id),)

        case RemoveInstance():
            ref = _ref(RefKind.INSTANCE, c.id)
            at = _find(d.instances, c.id, RefKind.INSTANCE, "instance")
            joints, actuators, entries = _dependents(project, instance=c.id)

            def edit(x):
                x["design"]["instances"].pop(at)
                _drop_dependents(x, joints, actuators, entries)

            new = _rebuild(project, edit, (ref,))
            return new, (AddInstance(type="add_instance", instance=d.instances[at], index=at), *_restore(joints, actuators, entries))

        case MoveInstance():
            ref = _ref(RefKind.INSTANCE, c.id)
            at = _find(d.instances, c.id, RefKind.INSTANCE, "instance")
            new = _rebuild(project, lambda x: _instance_json(x, c.id).update(pose=_dump(c.pose)), (ref,))
            return new, (MoveInstance(type="move_instance", id=c.id, pose=d.instances[at].pose),)

        case SetParameter():
            at = _find(d.instances, c.instance, RefKind.INSTANCE, "instance")
            inst = d.instances[at]
            names = [v.name for v in inst.parameters]
            refs = (_ref(RefKind.PARAMETER, f"{c.instance}/{c.parameter.name}"),)
            if c.parameter.name in names:
                if c.index is not None:
                    raise _reject(ReasonCode.INVALID_COMMAND, f"{c.parameter.name!r} is set already: no index", *refs)
                k = names.index(c.parameter.name)
                new = _rebuild(project, lambda x: _instance_json(x, c.instance)["parameters"].__setitem__(k, _dump(c.parameter)), refs)
                return new, (SetParameter(type="set_parameter", instance=c.instance, parameter=inst.parameters[k]),)
            k = _slot(c.index, len(names), f"parameters of {c.instance!r}", *refs)
            new = _rebuild(project, lambda x: _instance_json(x, c.instance)["parameters"].insert(k, _dump(c.parameter)), refs)
            return new, (ClearParameter(type="clear_parameter", instance=c.instance, name=c.parameter.name),)

        case ClearParameter():
            at = _find(d.instances, c.instance, RefKind.INSTANCE, "instance")
            inst = d.instances[at]
            names = [v.name for v in inst.parameters]
            refs = (_ref(RefKind.PARAMETER, f"{c.instance}/{c.name}"),)
            if c.name not in names:
                raise _reject(ReasonCode.UNKNOWN_ID, f"instance {c.instance!r} has no parameter {c.name!r} set", *refs)
            k = names.index(c.name)
            new = _rebuild(project, lambda x: _instance_json(x, c.instance)["parameters"].pop(k), refs)
            return new, (SetParameter(type="set_parameter", instance=c.instance, parameter=inst.parameters[k], index=k),)

        case SetInstanceMaterial():
            at = _find(d.instances, c.id, RefKind.INSTANCE, "instance")
            refs = (_ref(RefKind.INSTANCE, c.id), *(() if c.material is None else (_ref(RefKind.MATERIAL, c.material),)))
            new = _rebuild(project, lambda x: _instance_json(x, c.id).update(material=c.material), refs)
            return new, (SetInstanceMaterial(type="set_instance_material", id=c.id, material=d.instances[at].material),)

        case RelinkInstance():
            at = _find(d.instances, c.id, RefKind.INSTANCE, "instance")
            refs = (_ref(RefKind.INSTANCE, c.id), _ref(RefKind.PART, c.part))
            new = _rebuild(project, lambda x: _instance_json(x, c.id).update(part=c.part), refs)
            return new, (RelinkInstance(type="relink_instance", id=c.id, part=d.instances[at].part),)

        case AddJoint():
            ref = _ref(RefKind.JOINT, c.joint.id)
            _absent(d.joints, c.joint.id, RefKind.JOINT, "joint")
            at = _slot(c.index, len(d.joints), "joints", ref)
            new = _rebuild(project, lambda x: x["design"]["joints"].insert(at, _dump(c.joint)), (ref,))
            return new, (RemoveJoint(type="remove_joint", id=c.joint.id),)

        case ReplaceJoint():
            ref = _ref(RefKind.JOINT, c.joint.id)
            at = _find(d.joints, c.joint.id, RefKind.JOINT, "joint")
            new = _replace_in_place(project, (ref,), lambda x: x["design"]["joints"], c.joint.id, c.joint)
            return new, (ReplaceJoint(type="replace_joint", joint=d.joints[at]),)

        case RemoveJoint():
            _find(d.joints, c.id, RefKind.JOINT, "joint")
            joints, actuators, entries = _dependents(project, joint_ids={c.id})
            new = _rebuild(project, lambda x: _drop_dependents(x, joints, actuators, entries), (_ref(RefKind.JOINT, c.id),))
            return new, _restore(joints, actuators, entries)

        case AddActuator():
            ref = _ref(RefKind.ACTUATOR, c.actuator.id)
            _absent(d.actuators, c.actuator.id, RefKind.ACTUATOR, "actuator")
            at = _slot(c.index, len(d.actuators), "actuators", ref)
            new = _rebuild(project, lambda x: x["design"]["actuators"].insert(at, _dump(c.actuator)), (ref,))
            return new, (RemoveActuator(type="remove_actuator", id=c.actuator.id),)

        case RemoveActuator():
            _find(d.actuators, c.id, RefKind.ACTUATOR, "actuator")
            joints, actuators, entries = _dependents(project, actuator_ids={c.id})
            new = _rebuild(project, lambda x: _drop_dependents(x, joints, actuators, entries), (_ref(RefKind.ACTUATOR, c.id),))
            return new, _restore(joints, actuators, entries)

        case AddControlEntry():
            ref = _ref(RefKind.SCHEDULE_ENTRY, c.entry.id)
            _absent(d.schedule.entries, c.entry.id, RefKind.SCHEDULE_ENTRY, "schedule entry")
            at = _slot(c.index, len(d.schedule.entries), "schedule entries", ref)
            new = _rebuild(project, lambda x: x["design"]["schedule"]["entries"].insert(at, _dump(c.entry)), (ref,))
            return new, (RemoveControlEntry(type="remove_control_entry", id=c.entry.id),)

        case RemoveControlEntry():
            at = _find(d.schedule.entries, c.id, RefKind.SCHEDULE_ENTRY, "schedule entry")
            new = _rebuild(project, lambda x: x["design"]["schedule"]["entries"].pop(at), (_ref(RefKind.SCHEDULE_ENTRY, c.id),))
            return new, (AddControlEntry(type="add_control_entry", entry=d.schedule.entries[at], index=at),)

        case ReplaceControlEntry():
            ref = _ref(RefKind.SCHEDULE_ENTRY, c.entry.id)
            at = _find(d.schedule.entries, c.entry.id, RefKind.SCHEDULE_ENTRY, "schedule entry")
            new = _replace_in_place(project, (ref,), lambda x: x["design"]["schedule"]["entries"], c.entry.id, c.entry)
            return new, (ReplaceControlEntry(type="replace_control_entry", entry=d.schedule.entries[at]),)

        case AddAssumption():
            table = project.assumptions.assumptions
            ref = _ref(RefKind.ASSUMPTION, c.assumption.key)
            _absent(table, c.assumption.key, RefKind.ASSUMPTION, "assumption", "key")
            if not c.assumption.editable:
                raise _reject(ReasonCode.NOT_EDITABLE, f"assumption {c.assumption.key!r} is not editable: it could never be changed or removed again", ref)
            at = _slot(c.index, len(table), "assumptions", ref)
            new = _rebuild(project, lambda x: x["assumptions"]["assumptions"].insert(at, _dump(c.assumption)), (ref,))
            return new, (RemoveAssumption(type="remove_assumption", key=c.assumption.key),)

        case SetAssumption():
            table = project.assumptions.assumptions
            ref = _ref(RefKind.ASSUMPTION, c.assumption.key)
            at = _find(table, c.assumption.key, RefKind.ASSUMPTION, "assumption", "key")
            if not table[at].editable:
                raise _reject(ReasonCode.NOT_EDITABLE, f"assumption {c.assumption.key!r} is not editable", ref)
            if not c.assumption.editable:
                raise _reject(ReasonCode.NOT_EDITABLE, f"assumption {c.assumption.key!r}: an edit cannot make it not editable", ref)
            new = _rebuild(project, lambda x: x["assumptions"]["assumptions"].__setitem__(at, _dump(c.assumption)), (ref,))
            return new, (SetAssumption(type="set_assumption", assumption=table[at]),)

        case RemoveAssumption():
            table = project.assumptions.assumptions
            ref = _ref(RefKind.ASSUMPTION, c.key)
            at = _find(table, c.key, RefKind.ASSUMPTION, "assumption", "key")
            if not table[at].editable:
                raise _reject(ReasonCode.NOT_EDITABLE, f"assumption {c.key!r} is not editable", ref)
            new = _rebuild(project, lambda x: x["assumptions"]["assumptions"].pop(at), (ref,))
            return new, (AddAssumption(type="add_assumption", assumption=table[at], index=at),)

        case SelectPlanet():
            new = _rebuild(project, lambda x: x["world"].update(planet=c.planet), (_ref(RefKind.PLANET, c.planet),))
            return new, (SelectPlanet(type="select_planet", planet=project.world.planet),)

    raise AssertionError(f"unhandled command {type(c).__name__}")  # pragma: no cover  (the union is closed)


def _pack(edits: tuple[EditCommand, ...]) -> Command:
    return edits[0] if len(edits) == 1 else CommandBatch(type="batch", commands=edits)


def apply_command(project: Project, command: Command) -> ApplyResult:
    """Apply `command` to `project`. Returns the new project and the inverse command; raises `CommandRejected`
    (project untouched) when the edit is refused or its result would not be a valid `Project`."""
    if not isinstance(command, CommandBatch):
        new, inverse = _apply_edit(project, command)
        return ApplyResult(project=new, inverse=_pack(inverse))
    current, inverse = project, ()
    for n, edit in enumerate(command.commands):
        try:
            current, undo = _apply_edit(current, edit)
        except CommandRejected as e:
            raise CommandRejected(
                tuple(Reason(code=r.code, message=f"commands[{n}] ({edit.type}): {r.message}", ids=r.ids) for r in e.reasons)
            ) from e
        inverse = undo + inverse
    return ApplyResult(project=current, inverse=_pack(inverse))
