"""Edit tools of the agent (G-02a): the calls an LLM (or the MCP server, G-08) may make to change a project, and what each becomes.

    tools = EditTools(library=load_library())
    result = tools.run(project, "add_part", '{"part": "plate", "place": {"type": "on_ground"}}')   # a pure function of `project`
    result.command    # the `Command` the call became (one edit or a `CommandBatch`), `None` when it was refused
    result.project    # the project after it, as `validate_command` (C-02c) accepts it
    HubEditTools(hub, "car").call("add_part", args)      # the same, then published through the `Hub` (C-05a) as `Origin.AGENT`

Rules (the issue's DoD; read by G-03a proposals, G-04 guard, G-08 MCP server):

- **A tool call is only ever a `Command`.** Nothing here edits a project. `run` turns the call into a `Command` and hands it to
  `validate_command` (structure `apply_command`, policy and placement C-02c); a refusal comes back as `ToolResult.reasons` (the
  validator's own `Reason`s, code + sentence + typed refs) so an agent can read why and try again (G-03a). `HubEditTools` publishes
  that `Command` through `Hub.publish`, so the document's history, revision and subscribers see it like any other edit (C1).
  No tool takes an origin, and no tool can carry a planet constant, a verdict or a change of the material catalog: such a field is
  not in any argument schema (`extra="forbid"`), and the commands the tools build are the closed `Command` union. An attempt is
  refused as `forbidden` before the schema by the guard (G-04, `guard.py`), and what an accepted call uses beyond the catalogs is
  in `ToolResult.out_of_catalog`; `HubEditTools.call` publishes such a call only with the user's confirmation.
- **Position is a snap point, not a coordinate** (`studio-plan.md` risk 3). A part is placed by naming its own snap point and the snap
  point it meets (`snap_to`), joined at once by a joint; two parts already in the project are joined with `connect`. The pose of the
  instance is then computed in closed form (`snapmath.py`), so the two snap frames coincide (`facing: aligned`) or face each other
  (`facing: opposed`, their +Z axes opposite), turned about the joining axis by a whole number of quarter turns. The one place
  with nothing to snap to is the ground: `on_ground` rests the part, unrotated, with its lowest point on z = 0 at ground position
  (x, y) [m]. It is only for a part with a shape recipe (the validator can then check support and overlap); a part without one is
  refused, there is no free height. There is no tool that moves or rotates a part by numbers.
- **What the agent states is declared, what the tool computes is `sim`.** Parameter values, joint limits, break thresholds and
  control-schedule numbers the call carries are the user's: badge `declared`, source = the optional `source` text of the call
  (the user's words or reason) or a default sentence, `declared_by` "agent edit tools (G-02a)". The ground spot (x, y) of `on_ground` is the call's, so that pose is `declared` too (z is
  computed). A pose the tool computes from snap
  points is a closed-form calculation: badge `sim` (`project-model.md`), `source.ref` names the two snap points. Nothing is `cite`:
  the tools cite no document.
- **Schema violations are refused before anything is built.** Arguments are JSON; an unparsable string, an unknown tool, an unknown
  or missing field, a string for a number, a boolean for a number, an id that is not an id: `invalid_command`, one reason per
  problem, nothing applied. Names that do not exist in the project are `unknown_id` with the typed ref.
- **Definitions come from the library, never from the call.** `add_part` takes a part id; the `PartDef` is the project's own when the
  project already carries one under that id, else the library's (`load_library`, `kinetra_engine/parts/library`), added in the same
  batch. A material is the project's, else the catalog's exact entry (`load_material_catalog`). A call cannot define a part or a
  material, so the catalog and the part definitions cannot be changed through these tools.
- Ids the call leaves out are made deterministically: the first unused `<part>-<n>` for an instance, `joint-<n>`, `actuator-<n>`,
  `step-<n>`.
- **No placeholders (C-06).** Every tool adds the definitions it needs in the same command (`add_part_def`, `add_material_def`), so
  an accepted call never leaves an instance whose part or material the project lacks; and `validate_command` refuses a call whose
  result has more missing definitions than before (`missing_definition`), whatever the call. A tool that must read the part of an
  instance that is already a placeholder (a project opened with a missing definition) is refused with that same reason and names
  the missing part; it makes up no mass, shape or snap point. Nor does a tool re-link placeholders by adding a library part or catalog
  material under the id they use: that choice is the user's (`add_part_def`, `relink_instance`). `remove_part` is the one tool that works on a placeholder.
- Same conventions as the gateway (G-01): tool specs are OpenAI function-tool objects (`specs()`; `Gateway.chat` has no `tools`
  field, so G-03a's `proposal.py` puts them in the system message), a call is a tool name and its JSON arguments, and no text
  returned here contains anything from the environment (the tools never read it).

Limits (not hidden): `connect` and `set_parameter` move what they must so the joined snap points meet, but a part that is joined
on two sides (a closed loop of joints) cannot be moved: the validator refuses with `invalid_snap` and the call fails as a whole. A
parameter change re-seats the instance on its first joint (`resnap`), or back on the ground when it has no joint and rests there;
instances hanging from it do not follow (a joint moves
nothing, `project-model.md`), so a change that moves a snap point other parts hang on is refused by the validator. Joint axes and
which frames may mate are B-04a/B-04b's.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from kinetra_core import (
    ActuateEntry,
    Actuator,
    ActuatorKind,
    AddActuator,
    AddControlEntry,
    AddInstance,
    AddJoint,
    AddMaterialDef,
    AddPartDef,
    Badge,
    BreakThreshold,
    ClearParameter,
    Command,
    CommandBatch,
    CommandRejected,
    Instance,
    Joint,
    JointKind,
    JointLimits,
    Material,
    MissingDefinition,
    MoveInstance,
    Origin,
    ParamValue,
    PartDef,
    Pose,
    Project,
    Publish,
    Quantity,
    Reason,
    ReasonCode,
    Ref,
    RefError,
    RefKind,
    RemoveActuator,
    RemoveControlEntry,
    RemoveInstance,
    RemoveJoint,
    ReplaceControlEntry,
    ReplaceJoint,
    ScheduleEntry,
    SetInstanceMaterial,
    SetParameter,
    SnapRef,
    Source,
    Unit,
    WorldPosition,
    load_material_catalog,
    missing_reasons,
    validate_command,
)
from kinetra_core import convex as cx
from kinetra_core.conventions import ID_PATTERN
from kinetra_engine.protocol import Hub

from . import guard as gd
from . import snapmath as sm

LIBRARY_DIR = Path(__file__).resolve().parents[1] / "parts" / "library"
"""Where the part definitions the tools may add live (`docs/process/add-part.md`)."""

DECLARED_BY = "agent edit tools (G-02a)"
DEFAULT_SOURCE = "stated in the user's request and passed on by the agent edit tools (G-02a)"


def load_library(directory: Path = LIBRARY_DIR) -> dict[str, PartDef]:
    """The part definitions in `directory` by id (`<id>.json`, `PartDef.model_validate_json`)."""
    parts = {}
    for path in sorted(directory.glob("*.json")):
        part = PartDef.model_validate_json(path.read_text(encoding="utf-8"))
        if part.id != path.stem:
            raise ValueError(f"{path.name}: the part id {part.id!r} must be the file name")
        parts[part.id] = part
    return parts


# --- arguments ---------------------------------------------------------------------------------------------------

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
_Num = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
_NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
_Fraction = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1, le=1)]
_Quarter = Annotated[int, Field(strict=True, ge=0, le=3)]
_Source = Annotated[str | None, Field(max_length=400)]
_Facing = Literal["opposed", "aligned"]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapArg(_Args):
    """A snap point of an instance that is in the project."""

    instance: _Id
    snap_point: _Id


class LimitsArg(_Args):
    """Travel limits of the joint coordinate from the saved pose: rad for a hinge, m for a slider. `lower < upper`."""

    lower: _Num
    upper: _Num


class JointArg(_Args):
    kind: Literal["fixed", "hinge", "slider"] = "fixed"
    id: _Id | None = None
    limits: LimitsArg | None = None
    break_threshold: _Positive | None = Field(default=None, description="Joint load [N] above which the joint releases.")
    source: _Source = None


class OnGround(_Args):
    """Rest the part, unrotated, on the ground at (x, y) [m]: its lowest point at z = 0 (z is computed, never given). Only for a part with
    a shape recipe; the validator can then check support and overlap. The ground spot (x, y) is the caller's: `declared` with the call's `source`."""

    type: Literal["on_ground"]
    x: _Num = 0.0
    y: _Num = 0.0


class SnapTo(_Args):
    type: Literal["snap_to"]
    snap_point: _Id = Field(description="The new part's own snap point that meets the target.")
    target: SnapArg
    facing: _Facing
    roll_quarter_turns: _Quarter = 0
    joint: JointArg = JointArg()


class AddPartArgs(_Args):
    """Add a part from the library and place it: on the ground, or at a snap point of a part that is already there."""

    part: _Id
    instance_id: _Id | None = None
    parameters: dict[_Name, _Num] = Field(default_factory=dict, description="Parameter values in the part's own unit (SI).")
    material: _Id | None = Field(default=None, description="A material of the project or of the catalog.")
    place: Annotated[Union[OnGround, SnapTo], Field(discriminator="type")]
    source: _Source = None


class RemovePartArgs(_Args):
    instance: _Id


class SetParameterArgs(_Args):
    instance: _Id
    name: _Name
    value: _Num = Field(description="In the parameter's own unit (SI); the part's range applies.")
    resnap: StrictBool = Field(default=True, description="Move the instance so its first joint still meets after the change.")
    source: _Source = None


class ClearParameterArgs(_Args):
    instance: _Id
    name: _Name
    resnap: StrictBool = True


class SetMaterialArgs(_Args):
    instance: _Id
    material: _Id | None = Field(description="A material of the project or of the catalog; null assigns none.")


class ConnectArgs(_Args):
    """Join two parts that are in the project at two of their snap points. `move: assembly` first moves everything joined to
    `b` so that `b`'s snap point meets `a`'s; `none` joins them where they already are."""

    a: SnapArg
    b: SnapArg
    facing: _Facing
    roll_quarter_turns: _Quarter = 0
    joint: JointArg = JointArg()
    move: Literal["assembly", "none"] = "assembly"


class SetJointArgs(_Args):
    joint: _Id
    kind: Literal["fixed", "hinge", "slider"] | None = None
    limits: LimitsArg | None = None
    break_threshold: _Positive | None = None
    clear: list[Literal["limits", "break_threshold"]] = Field(default_factory=list)
    source: _Source = None


class RemoveJointArgs(_Args):
    joint: _Id


class AddActuatorArgs(_Args):
    kind: Literal["motor", "thruster"]
    instance: _Id
    joint: _Id | None = Field(default=None, description="The joint a motor drives; a thruster has none.")
    id: _Id | None = None


class RemoveActuatorArgs(_Args):
    actuator: _Id


class ScheduleCommandArgs(_Args):
    """Command `command` (fraction of full command: -1..1 for a motor, 0..1 for a thruster) on `actuator` during [start, end) s."""

    actuator: _Id
    start: _NonNegative
    end: _NonNegative
    command: _Fraction
    id: _Id | None = None
    source: _Source = None


class ChangeCommandArgs(_Args):
    entry: _Id
    start: _NonNegative | None = None
    end: _NonNegative | None = None
    command: _Fraction | None = None
    source: _Source = None


class RemoveCommandArgs(_Args):
    entry: _Id


_TOOLS: dict[str, tuple[type[_Args], str]] = {
    "add_part": (AddPartArgs, "Add a part of the library and place it, on the ground or at a snap point of a part already there. The snap point joins them."),
    "remove_part": (RemovePartArgs, "Delete a part with its joints, the actuators on it and their schedule entries."),
    "set_parameter": (SetParameterArgs, "Set a parameter of a part (SI, within the part's range)."),
    "clear_parameter": (ClearParameterArgs, "Unset a parameter of a part: it takes the part's default."),
    "set_material": (SetMaterialArgs, "Assign a material (of the project or the catalog) to a part, or none."),
    "connect": (ConnectArgs, "Join two parts of the project at two snap points; the assembly of the second one is moved to meet the first."),
    "set_joint": (SetJointArgs, "Change a joint's kind, limits or break threshold."),
    "remove_joint": (RemoveJointArgs, "Release a joint with the actuators that drive it and their schedule entries."),
    "add_actuator": (AddActuatorArgs, "Put a motor (on a joint) or a thruster on a part."),
    "remove_actuator": (RemoveActuatorArgs, "Remove an actuator with its schedule entries."),
    "schedule_command": (ScheduleCommandArgs, "Add a control-schedule entry: command an actuator during [start, end) seconds."),
    "change_command": (ChangeCommandArgs, "Change the times or the command of a control-schedule entry."),
    "remove_command": (RemoveCommandArgs, "Remove a control-schedule entry."),
}

TOOL_NAMES = tuple(_TOOLS)


def specs() -> list[dict]:
    """The tools as OpenAI function-tool objects (G-03a's `Proposer` puts them in the system message)."""
    return [
        {"type": "function", "function": {"name": name, "description": text, "parameters": model.model_json_schema()}}
        for name, (model, text) in _TOOLS.items()
    ]


# --- result ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolResult:
    """What a tool call did. `ok` means the command was accepted (by the validator, and by the document when published).

    `out_of_catalog` (G-04) is what the call introduces beyond the catalogs, each with the label its value badge shows
    (`카탈로그 밖 · 사용자 선언`, `카탈로그와 다름`). `needs_confirmation` means the call was not published because the user
    has not confirmed those findings (`HubEditTools.call`); `command` and `project` are then what it would apply."""

    ok: bool
    tool: str
    summary: str
    command: Command | None = None
    project: Project | None = None
    reasons: tuple[Reason, ...] = ()
    effects: Mapping[str, Any] = field(default_factory=dict)
    revision: int | None = None
    out_of_catalog: tuple[gd.OutOfCatalog, ...] = ()
    needs_confirmation: bool = False

    def to_json(self) -> dict:
        """What goes back to the model: the outcome in words and ids, the reasons as the validator wrote them."""
        out: dict[str, Any] = {"ok": self.ok, "tool": self.tool, "summary": self.summary}
        if self.effects:
            out["effects"] = dict(self.effects)
        if self.revision is not None:
            out["revision"] = self.revision
        if self.reasons:
            out["reasons"] = [r.model_dump(mode="json") for r in self.reasons]
        if self.out_of_catalog:
            out["out_of_catalog"] = [f.to_json() for f in self.out_of_catalog]
        if self.needs_confirmation:
            out["needs_confirmation"] = True
        return out


def _refuse(code: ReasonCode, message: str, *refs: Ref) -> CommandRejected:
    return CommandRejected((Reason(code=code, message=message, ids=refs),))


def _reason_of(tool: str, err: Mapping[str, Any]) -> Reason:
    cause = err.get("ctx", {}).get("error")
    where = ".".join(str(part) for part in err["loc"])
    text = str(err["msg"]).removeprefix("Value error, ")
    return Reason(
        code=ReasonCode.INVALID_COMMAND,
        message=f"{tool}: the record this call asks for is not valid: {where + ': ' if where else ''}{text}",
        ids=cause.refs if isinstance(cause, RefError) else (),
    )


def _changed_ids(before: Project, after: Project) -> dict[str, dict[str, list[str]]]:
    def ids(p: Project) -> dict[str, set[str]]:
        d = p.design
        return {
            "parts": {x.id for x in d.parts},
            "materials": {x.id for x in d.materials},
            "instances": {x.id for x in d.instances},
            "joints": {x.id for x in d.joints},
            "actuators": {x.id for x in d.actuators},
            "schedule_entries": {x.id for x in d.schedule.entries},
        }

    b, a = ids(before), ids(after)
    out: dict[str, dict[str, list[str]]] = {"added": {}, "removed": {}}
    for kind in a:
        if a[kind] - b[kind]:
            out["added"][kind] = sorted(a[kind] - b[kind])
        if b[kind] - a[kind]:
            out["removed"][kind] = sorted(b[kind] - a[kind])
    return {k: v for k, v in out.items() if v}


# --- the tools ---------------------------------------------------------------------------------------------------


class EditTools:
    """The edit tools over a project. Holds no project: `run` is a function of the project it is given."""

    def __init__(self, library: Mapping[str, PartDef] | None = None, clock: Callable[[], datetime] | None = None):
        self._library = dict(load_library() if library is None else library)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    specs = staticmethod(specs)

    def run(self, project: Project, tool: str, arguments: str | Mapping[str, Any]) -> ToolResult:
        """Turn one call into a `Command` and validate it against `project`. Never raises for a bad call; the result says why."""
        entry = _TOOLS.get(tool)
        if entry is None:
            named = gd.guard_tool(tool)  # G-04: `set_gravity` is an attempt, not a typo
            return self._refused(tool, named or (Reason(code=ReasonCode.INVALID_COMMAND, message=f"unknown tool {tool!r}; the tools are {list(TOOL_NAMES)}"),))
        too_deep = (Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: the arguments nest deeper than {gd.MAX_ARGUMENT_DEPTH} levels; no tool takes that"),)
        if isinstance(arguments, str) and gd.json_too_deep(arguments):  # before the parser, whose own limit is the platform's
            return self._refused(tool, too_deep)
        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (ValueError, TypeError) as e:
            return self._refused(tool, (Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: the arguments are not JSON: {e}"),))
        except RecursionError:  # not reached after the scan above; kept so no input can raise out of `run`
            return self._refused(tool, too_deep)
        if not isinstance(raw, dict):
            return self._refused(tool, (Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: the arguments must be a JSON object"),))
        forbidden = gd.guard_arguments(tool, raw)  # G-04: before the schema, so an attempt is named as one
        if forbidden:
            return self._refused(tool, forbidden)
        try:
            args = entry[0].model_validate(raw)
        except ValidationError as e:
            reasons = tuple(
                Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: not a valid call: {'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}")
                for err in e.errors()
            )
            return self._refused(tool, reasons)
        try:
            command, summary = getattr(self, f"_{tool}")(project, args)
            applied = validate_command(project, command)
        except CommandRejected as e:
            return self._refused(tool, e.reasons)
        except ValidationError as e:  # the call is well-formed but the record it asks for is not (a motor without a joint, limits on a fixed joint)
            return self._refused(tool, tuple(_reason_of(tool, err) for err in e.errors()))
        found = gd.introduced(project, applied.project, self._library)
        labels = sorted({f.label for f in found})
        return ToolResult(
            ok=True,
            tool=tool,
            summary=summary + (f"; out of the catalog: {', '.join(labels)}" if found else ""),
            command=command,
            project=applied.project,
            effects=_changed_ids(project, applied.project),
            out_of_catalog=found,
        )

    @staticmethod
    def _refused(tool: str, reasons: tuple[Reason, ...]) -> ToolResult:
        return ToolResult(ok=False, tool=tool, summary=f"{tool} was refused; nothing changed", reasons=reasons)

    # --- helpers

    def _declared(self, source: str | None) -> dict:
        return {
            "badge": Badge.DECLARED,
            "source": Source(ref=source or DEFAULT_SOURCE, declared_by=DECLARED_BY, declared_at=self._clock()),
        }

    @staticmethod
    def _computed(ref: str) -> dict:
        return {"badge": Badge.SIM, "source": Source(ref=ref)}

    @staticmethod
    def _instance(project: Project, ident: str) -> Instance:
        for i in project.design.instances:
            if i.id == ident:
                return i
        raise _refuse(ReasonCode.UNKNOWN_ID, f"no instance {ident!r}", Ref(kind=RefKind.INSTANCE, id=ident))

    @staticmethod
    def _part_of(project: Project, inst: Instance) -> PartDef:
        """The definition of `inst`'s part. A placeholder (C-06: the project does not carry the part) has none, and a tool never invents one
        or works around it: the call is refused with the `missing_definition` reason of the core. (`remove_part` needs no definition and
        is the way out, as are `relink_instance` and `add_part_def`, which are commands and not tools.)"""
        for p in project.design.parts:
            if p.id == inst.part:
                return p
        users = tuple(i.id for i in project.design.instances if i.part == inst.part)
        raise CommandRejected(missing_reasons((MissingDefinition(kind="part", id=inst.part, instances=users),)))

    @staticmethod
    def _snap_ref(inst_id: str, snap_id: str) -> Ref:
        return Ref(kind=RefKind.SNAP_POINT, id=f"{inst_id}/{snap_id}")

    def _snap_frame(self, project: Project, inst: Instance, snap_id: str) -> tuple[sm.Vec, sm.Mat]:
        """World position and rotation of the snap point `snap_id` of `inst` at its stored pose and parameters."""
        part = self._part_of(project, inst)
        if snap_id not in {s.id for s in part.snap_points}:
            raise _refuse(
                ReasonCode.UNKNOWN_ID,
                f"part {part.id!r} of instance {inst.id!r} has no snap point {snap_id!r}; it has {[s.id for s in part.snap_points]}",
                self._snap_ref(inst.id, snap_id),
            )
        p, r = sm.snap_local(part, snap_id, sm.parameter_values(part, inst))
        rw = cx.rotation(inst.pose.orientation)
        t = (inst.pose.position.x, inst.pose.position.y, inst.pose.position.z)
        return cx.add(sm.apply(rw, p), t), sm.matmul(rw, r)

    @staticmethod
    def _pose(r: sm.Mat, t: sm.Vec, provenance: dict) -> Pose:
        return Pose(
            position=WorldPosition(x=sm.clean(t[0]), y=sm.clean(t[1]), z=sm.clean(t[2])),
            orientation=sm.to_quaternion(r),
            **provenance,
        )

    @staticmethod
    def _seat(
        target: tuple[sm.Vec, sm.Mat], own_p: sm.Vec, own_r: sm.Mat, facing: str, roll: int
    ) -> tuple[sm.Mat, sm.Vec]:
        """Rotation and position of an instance whose snap point (`own_p`, `own_r` in its part) meets the world frame `target`."""
        (pw, rw) = target
        q = sm.RX_PI if facing == "opposed" else sm.IDENTITY
        snap_world = sm.matmul(sm.matmul(rw, q), sm.rz_quarter(roll))
        r = sm.matmul(snap_world, sm.transpose(own_r))
        t = cx.sub(pw, sm.apply(r, own_p))
        return r, t

    @staticmethod
    def _fresh(prefix: str, taken: set[str]) -> str:
        n = 1
        prefix = prefix[:50]
        while f"{prefix}-{n}" in taken:
            n += 1
        return f"{prefix}-{n}"

    @staticmethod
    def _not_a_placeholder(project: Project, kind: str, ident: str) -> None:
        """Adding a library or catalog definition under an id that placeholders already use would silently re-link them to a definition
        the user never chose. That is the user's decision (`add_part_def`/`relink_instance`, C-06), not a tool's: refused."""
        users = tuple(i.id for i in project.design.instances if (i.part if kind == "part" else i.material) == ident)
        if users:
            raise CommandRejected(missing_reasons((MissingDefinition(kind=kind, id=ident, instances=users),)))  # type: ignore[arg-type]

    def _definition(self, project: Project, part_id: str) -> tuple[PartDef, bool]:
        for p in project.design.parts:
            if p.id == part_id:
                return p, False
        self._not_a_placeholder(project, "part", part_id)
        if part_id in self._library:
            return self._library[part_id], True
        raise _refuse(
            ReasonCode.UNKNOWN_ID,
            f"no part {part_id!r} in the project or the library; the library has {sorted(self._library)}",
            Ref(kind=RefKind.PART, id=part_id),
        )

    @staticmethod
    def _material(project: Project, material_id: str) -> tuple[Material | None, bool]:
        """(the material to add or None when the project has it, whether it must be added)."""
        if any(m.id == material_id for m in project.design.materials):
            return None, False
        EditTools._not_a_placeholder(project, "material", material_id)
        catalog = load_material_catalog()
        try:
            return catalog.get(material_id).material, True
        except KeyError:
            known = sorted({m.id for m in project.design.materials} | {e.material.id for e in catalog.entries})
            raise _refuse(
                ReasonCode.UNKNOWN_ID, f"no material {material_id!r} in the project or the catalog; known: {known}", Ref(kind=RefKind.MATERIAL, id=material_id)
            ) from None

    def _joint(self, project: Project, jid: str | None, kind: str, a: SnapRef, b: SnapRef, arg: JointArg, extra_taken: set[str] = frozenset()) -> Joint:  # type: ignore[assignment]
        ident = jid or self._fresh("joint", {j.id for j in project.design.joints} | set(extra_taken))
        limits = None
        if arg.limits is not None:
            unit = {"hinge": Unit.RAD, "slider": Unit.M}.get(kind)
            if unit is None:
                raise _refuse(ReasonCode.INVALID_COMMAND, f"a {kind} joint has no limits", Ref(kind=RefKind.JOINT, id=ident))
            prov = self._declared(arg.source)
            limits = JointLimits(
                lower=Quantity(value=arg.limits.lower, unit=unit, **prov), upper=Quantity(value=arg.limits.upper, unit=unit, **prov)
            )
        threshold = None
        if arg.break_threshold is not None:
            threshold = BreakThreshold(value=arg.break_threshold, unit=Unit.N, **self._declared(arg.source))
        return Joint(id=ident, kind=JointKind(kind), a=a, b=b, limits=limits, break_threshold=threshold)

    @staticmethod
    def _batch(edits: list) -> Command:
        return edits[0] if len(edits) == 1 else CommandBatch(type="batch", commands=tuple(edits))

    # --- add_part / remove_part

    def _add_part(self, project: Project, a: AddPartArgs) -> tuple[Command, str]:
        part, add_def = self._definition(project, a.part)
        by_name = {p.name: p for p in part.parameters}
        values = {p.name: p.default.value for p in part.parameters}
        declared = self._declared(a.source)
        params = []
        for name, value in a.parameters.items():
            if name not in by_name:
                raise _refuse(
                    ReasonCode.UNKNOWN_ID,
                    f"part {part.id!r} has no parameter {name!r}; it has {sorted(by_name)}",
                    Ref(kind=RefKind.PARAMETER, id=f"{a.instance_id or part.id}/{name}"),
                )
            values[name] = value
            params.append(ParamValue(name=name, value=value, unit=by_name[name].unit, **declared))
        taken = {i.id for i in project.design.instances}
        ident = a.instance_id or self._fresh(part.id, taken)
        if ident in taken:
            raise _refuse(ReasonCode.DUPLICATE_ID, f"instance {ident!r} already exists", Ref(kind=RefKind.INSTANCE, id=ident))
        edits: list = []
        if add_def:
            edits.append(AddPartDef(type="add_part_def", part=part))
        if a.material is not None:
            material, add_material = self._material(project, a.material)
            if add_material:
                edits.append(AddMaterialDef(type="add_material_def", material=material))

        place = a.place
        if isinstance(place, OnGround):
            geometry = sm.world_bodies(part, values, sm.IDENTITY, (0.0, 0.0, 0.0))
            low = sm.lowest_z(geometry)
            if low is None:
                raise _refuse(
                    ReasonCode.INVALID_COMMAND,
                    f"part {part.id!r} has no shape recipe, so the validator could not check its support or overlap: it cannot be put on the ground "
                    "by this tool. Place it at a snap point of a part that is in the project",
                    Ref(kind=RefKind.PART, id=part.id),
                )
            # One badge covers a whole pose (`Pose`). (x, y) are the caller's number, so the pose is `declared`; z is computed.
            note = "z computed by resting the lowest point of the part on the ground (snapmath)"
            pose = self._pose(
                sm.IDENTITY, (place.x, place.y, -low), {"badge": Badge.DECLARED, "source": Source(ref=f"{a.source or DEFAULT_SOURCE}; {note}", declared_by=DECLARED_BY, declared_at=self._clock())}
            )
            joint = None
            where = f"on the ground at ({place.x:g}, {place.y:g}) m"
        else:
            target = self._instance(project, place.target.instance)
            own = next((s for s in part.snap_points if s.id == place.snap_point), None)
            if own is None:
                raise _refuse(
                    ReasonCode.UNKNOWN_ID,
                    f"part {part.id!r} has no snap point {place.snap_point!r}; it has {[s.id for s in part.snap_points]}",
                    self._snap_ref(ident, place.snap_point),
                )
            frame = self._snap_frame(project, target, place.target.snap_point)
            own_p, own_r = sm.snap_local(part, own.id, values)
            r, t = self._seat(frame, own_p, own_r, place.facing, place.roll_quarter_turns)
            pose = self._pose(
                r, t, self._computed(f"snap placement: {own.id!r} of {ident!r} meets {place.target.snap_point!r} of {place.target.instance!r} ({place.facing})")
            )
            joint = self._joint(
                project,
                place.joint.id,
                place.joint.kind,
                SnapRef(instance=place.target.instance, snap_point=place.target.snap_point),
                SnapRef(instance=ident, snap_point=own.id),
                place.joint,
            )
            where = f"at snap point {place.target.snap_point!r} of {place.target.instance!r}, joined by a {joint.kind.value} joint {joint.id!r}"
        edits.append(
            AddInstance(
                type="add_instance",
                instance=Instance(id=ident, part=part.id, parameters=tuple(params), material=a.material, pose=pose),
            )
        )
        if joint is not None:
            edits.append(AddJoint(type="add_joint", joint=joint))
        return self._batch(edits), f"added {part.id!r} as instance {ident!r} {where}"

    def _remove_part(self, project: Project, a: RemovePartArgs) -> tuple[Command, str]:
        self._instance(project, a.instance)
        return RemoveInstance(type="remove_instance", id=a.instance), f"removed instance {a.instance!r} with what hangs on it"

    # --- parameters and material

    def _translated(self, inst: Instance, t: sm.Vec, why: str) -> MoveInstance:
        """`inst` at position `t` with its orientation as it is (a parameter change never turns a snap frame)."""
        pose = Pose(position=WorldPosition(x=sm.clean(t[0]), y=sm.clean(t[1]), z=sm.clean(t[2])), orientation=inst.pose.orientation, **self._computed(why))
        return MoveInstance(type="move_instance", id=inst.id, pose=pose)

    def _reseat(self, project: Project, inst: Instance, new_params: tuple[ParamValue, ...]) -> list:
        """Moves that keep the assembly meeting after `inst` gets `new_params` (snap points move, orientations do not, so every move
        is a translation): `inst` slides to meet the joint it hangs from (as the `b` side) or, with none, back onto the ground when it
        rested there; then every assembly hanging from `inst` through its other joints is carried by the same amount its snap point
        moved. Whatever is joined on more than one side (a loop) is not moved: the validator then says which joint no longer meets."""
        part = self._part_of(project, inst)
        changed = inst.model_copy(update={"parameters": new_params})  # only to read the values: nothing is stored from it
        old_values, new_values = sm.parameter_values(part, inst), sm.parameter_values(part, changed)
        r = cx.rotation(inst.pose.orientation)
        t_old = (inst.pose.position.x, inst.pose.position.y, inst.pose.position.z)
        anchor = next((j for j in project.design.joints if j.b.instance == inst.id), None)
        t_new = t_old
        if anchor is not None:
            other = anchor.a
            target = self._snap_frame(project, self._instance(project, other.instance), other.snap_point)
            p_own, _ = sm.snap_local(part, anchor.b.snap_point, new_values)
            t_new = cx.sub(target[0], sm.apply(r, p_own))
            why = f"re-seated on joint {anchor.id!r} after a parameter change (snapmath)"
        else:
            before = sm.lowest_z(sm.world_bodies(part, old_values, r, t_old))
            if before is not None and abs(before) <= 1e-9:
                after = sm.lowest_z(sm.world_bodies(part, new_values, r, t_old))
                t_new = (t_old[0], t_old[1], t_old[2] - after)
            why = f"rests on the ground after a parameter change: lowest point of {inst.id!r} at z = 0 (snapmath)"
        moves: list = []
        if max(abs(x - y) for x, y in zip(t_new, t_old)) >= 1e-12:
            if anchor is None:  # only z is recomputed; (x, y) stay the caller's, so the pose keeps its provenance
                pose = Pose(position=WorldPosition(x=sm.clean(t_new[0]), y=sm.clean(t_new[1]), z=sm.clean(t_new[2])), orientation=inst.pose.orientation, badge=inst.pose.badge, source=inst.pose.source)
                moves.append(MoveInstance(type="move_instance", id=inst.id, pose=pose))
            else:
                moves.append(self._translated(inst, t_new, why))
        held = {inst.id} | ({anchor.a.instance} if anchor is not None else set())
        for joint in project.design.joints:
            if inst.id not in (joint.a.instance, joint.b.instance) or joint is anchor:
                continue
            own, far = (joint.a, joint.b) if joint.a.instance == inst.id else (joint.b, joint.a)
            p_new, _ = sm.snap_local(part, own.snap_point, new_values)
            meet = cx.add(sm.apply(r, p_new), t_new)
            far_inst = self._instance(project, far.instance)
            p_far, r_far = sm.snap_local(self._part_of(project, far_inst), far.snap_point, sm.parameter_values(self._part_of(project, far_inst), far_inst))
            now = cx.add(sm.apply(cx.rotation(far_inst.pose.orientation), p_far), (far_inst.pose.position.x, far_inst.pose.position.y, far_inst.pose.position.z))
            delta = cx.sub(meet, now)
            if max(abs(x) for x in delta) < 1e-12:
                continue
            members = [m for m in self._assembly(project, far.instance, avoid=inst.id)]
            if held & set(members):
                continue  # joined back to what holds `inst`: a loop, not moved
            for m in members:
                mi = self._instance(project, m)
                moves.append(self._translated(mi, cx.add((mi.pose.position.x, mi.pose.position.y, mi.pose.position.z), delta), f"carried with {inst.id!r} after a parameter change (snapmath)"))
        return moves

    def _set_parameter(self, project: Project, a: SetParameterArgs) -> tuple[Command, str]:
        inst = self._instance(project, a.instance)
        part = self._part_of(project, inst)
        definition = next((p for p in part.parameters if p.name == a.name), None)
        if definition is None:
            raise _refuse(
                ReasonCode.UNKNOWN_ID,
                f"part {part.id!r} has no parameter {a.name!r}; it has {[p.name for p in part.parameters]}",
                Ref(kind=RefKind.PARAMETER, id=f"{inst.id}/{a.name}"),
            )
        value = ParamValue(name=a.name, value=a.value, unit=definition.unit, **self._declared(a.source))
        is_set = any(p.name == a.name for p in inst.parameters)
        edits: list = [SetParameter(type="set_parameter", instance=inst.id, parameter=value)]
        if a.resnap:
            new = tuple(value if p.name == a.name else p for p in inst.parameters) if is_set else inst.parameters + (value,)
            edits += self._reseat(project, inst, new)
        return self._batch(edits), f"set {a.name} of {inst.id!r} to {a.value:g} {definition.unit.value}" + (f" and moved {len(edits) - 1} instance(s) to keep the joints meeting" if len(edits) > 1 else "")

    def _clear_parameter(self, project: Project, a: ClearParameterArgs) -> tuple[Command, str]:
        inst = self._instance(project, a.instance)
        edits: list = [ClearParameter(type="clear_parameter", instance=inst.id, name=a.name)]
        if a.resnap:
            edits += self._reseat(project, inst, tuple(p for p in inst.parameters if p.name != a.name))
        return self._batch(edits), f"cleared {a.name} of {inst.id!r}: the part's default applies"

    def _set_material(self, project: Project, a: SetMaterialArgs) -> tuple[Command, str]:
        self._instance(project, a.instance)
        edits: list = []
        if a.material is not None:
            material, add = self._material(project, a.material)
            if add:
                edits.append(AddMaterialDef(type="add_material_def", material=material))
        edits.append(SetInstanceMaterial(type="set_instance_material", id=a.instance, material=a.material))
        return self._batch(edits), f"material of {a.instance!r} is now {a.material!r}"

    # --- joints

    def _assembly(self, project: Project, root: str, avoid: str | None = None) -> list[str]:
        """Instances reachable from `root` through joints (not through `avoid`), `root` first, in a fixed order."""
        seen, queue = {root} | ({avoid} if avoid else set()), deque([root])
        order = [root]
        while queue:
            at = queue.popleft()
            for j in project.design.joints:
                for here, there in ((j.a.instance, j.b.instance), (j.b.instance, j.a.instance)):
                    if here == at and there not in seen:
                        seen.add(there)
                        order.append(there)
                        queue.append(there)
        return order

    def _connect(self, project: Project, a: ConnectArgs) -> tuple[Command, str]:
        inst_a, inst_b = self._instance(project, a.a.instance), self._instance(project, a.b.instance)
        if inst_a.id == inst_b.id:
            raise _refuse(ReasonCode.INVALID_COMMAND, f"both ends are on instance {inst_a.id!r}", Ref(kind=RefKind.INSTANCE, id=inst_a.id))
        frame_a = self._snap_frame(project, inst_a, a.a.snap_point)
        self._snap_frame(project, inst_b, a.b.snap_point)  # existence of b's snap point
        edits: list = []
        if a.move == "assembly":
            part_b = self._part_of(project, inst_b)
            own_p, own_r = sm.snap_local(part_b, a.b.snap_point, sm.parameter_values(part_b, inst_b))
            r_new, t_new = self._seat(frame_a, own_p, own_r, a.facing, a.roll_quarter_turns)
            r_old = cx.rotation(inst_b.pose.orientation)
            t_old = (inst_b.pose.position.x, inst_b.pose.position.y, inst_b.pose.position.z)
            rd = sm.matmul(r_new, sm.transpose(r_old))
            members = self._assembly(project, inst_b.id)
            if inst_a.id in members:
                raise _refuse(
                    ReasonCode.INVALID_COMMAND,
                    f"{inst_a.id!r} and {inst_b.id!r} are already joined through other joints; joining them again would close a loop",
                    Ref(kind=RefKind.INSTANCE, id=inst_a.id),
                    Ref(kind=RefKind.INSTANCE, id=inst_b.id),
                )
            why = f"snap placement: {a.b.snap_point!r} of {inst_b.id!r} meets {a.a.snap_point!r} of {inst_a.id!r} ({a.facing})"
            for m in members:
                inst = self._instance(project, m)
                r_m = sm.matmul(rd, cx.rotation(inst.pose.orientation))
                t_m = cx.add(sm.apply(rd, cx.sub((inst.pose.position.x, inst.pose.position.y, inst.pose.position.z), t_old)), t_new)
                edits.append(MoveInstance(type="move_instance", id=m, pose=self._pose(r_m, t_m, self._computed(why))))
        joint = self._joint(
            project, a.joint.id, a.joint.kind, SnapRef(instance=inst_a.id, snap_point=a.a.snap_point), SnapRef(instance=inst_b.id, snap_point=a.b.snap_point), a.joint
        )
        edits.append(AddJoint(type="add_joint", joint=joint))
        moved = f", moving {len(edits) - 1} instance(s)" if len(edits) > 1 else ""
        return self._batch(edits), f"joined {a.a.snap_point!r} of {inst_a.id!r} and {a.b.snap_point!r} of {inst_b.id!r} with a {joint.kind.value} joint {joint.id!r}{moved}"

    def _find_joint(self, project: Project, ident: str) -> Joint:
        for j in project.design.joints:
            if j.id == ident:
                return j
        raise _refuse(ReasonCode.UNKNOWN_ID, f"no joint {ident!r}", Ref(kind=RefKind.JOINT, id=ident))

    def _set_joint(self, project: Project, a: SetJointArgs) -> tuple[Command, str]:
        old = self._find_joint(project, a.joint)
        kind = a.kind or old.kind.value
        arg = JointArg(kind=kind, limits=a.limits, break_threshold=a.break_threshold, source=a.source)  # type: ignore[arg-type]
        fresh = self._joint(project, old.id, kind, old.a, old.b, arg)
        limits = None if "limits" in a.clear else (fresh.limits if a.limits is not None else old.limits)
        threshold = None if "break_threshold" in a.clear else (fresh.break_threshold if a.break_threshold is not None else old.break_threshold)
        new = Joint(id=old.id, kind=JointKind(kind), a=old.a, b=old.b, limits=limits, break_threshold=threshold)
        return ReplaceJoint(type="replace_joint", joint=new), f"joint {old.id!r} is now a {kind} joint"

    def _remove_joint(self, project: Project, a: RemoveJointArgs) -> tuple[Command, str]:
        self._find_joint(project, a.joint)
        return RemoveJoint(type="remove_joint", id=a.joint), f"released joint {a.joint!r} with the actuators that drive it"

    # --- actuators and control

    def _add_actuator(self, project: Project, a: AddActuatorArgs) -> tuple[Command, str]:
        self._instance(project, a.instance)
        ident = a.id or self._fresh("actuator", {x.id for x in project.design.actuators})
        actuator = Actuator(id=ident, kind=ActuatorKind(a.kind), instance=a.instance, joint=a.joint)
        return AddActuator(type="add_actuator", actuator=actuator), f"added {a.kind} actuator {ident!r} on {a.instance!r}"

    def _remove_actuator(self, project: Project, a: RemoveActuatorArgs) -> tuple[Command, str]:
        if not any(x.id == a.actuator for x in project.design.actuators):
            raise _refuse(ReasonCode.UNKNOWN_ID, f"no actuator {a.actuator!r}", Ref(kind=RefKind.ACTUATOR, id=a.actuator))
        return RemoveActuator(type="remove_actuator", id=a.actuator), f"removed actuator {a.actuator!r} with its schedule entries"

    def _schedule_command(self, project: Project, a: ScheduleCommandArgs) -> tuple[Command, str]:
        ident = a.id or self._fresh("step", {e.id for e in project.design.schedule.entries})
        entry = ActuateEntry(type="actuate", id=ident, actuator=a.actuator, start=a.start, end=a.end, command=a.command, **self._declared(a.source))
        return AddControlEntry(type="add_control_entry", entry=entry), f"scheduled {a.command:g} on {a.actuator!r} from {a.start:g} s to {a.end:g} s as {ident!r}"

    def _find_entry(self, project: Project, ident: str) -> ScheduleEntry:
        for e in project.design.schedule.entries:
            if e.id == ident:
                return e
        raise _refuse(ReasonCode.UNKNOWN_ID, f"no schedule entry {ident!r}", Ref(kind=RefKind.SCHEDULE_ENTRY, id=ident))

    def _change_command(self, project: Project, a: ChangeCommandArgs) -> tuple[Command, str]:
        old = self._find_entry(project, a.entry)
        if not isinstance(old, ActuateEntry):
            raise _refuse(
                ReasonCode.INVALID_COMMAND,
                f"schedule entry {old.id!r} is a separation, not an actuator command: it has no start, end or command to change",
                Ref(kind=RefKind.SCHEDULE_ENTRY, id=old.id),
            )
        new = ActuateEntry(
            type="actuate",
            id=old.id,
            actuator=old.actuator,
            start=old.start if a.start is None else a.start,
            end=old.end if a.end is None else a.end,
            command=old.command if a.command is None else a.command,
            **self._declared(a.source),
        )
        return ReplaceControlEntry(type="replace_control_entry", entry=new), f"changed schedule entry {old.id!r}"

    def _remove_command(self, project: Project, a: RemoveCommandArgs) -> tuple[Command, str]:
        self._find_entry(project, a.entry)
        return RemoveControlEntry(type="remove_control_entry", id=a.entry), f"removed schedule entry {a.entry!r}"


class HubEditTools:
    """The edit tools of one project of a `Hub`: a call is built against the document's current project and published through
    `Hub.publish` (so history, revision, `applied` broadcast and the document's own validation are the ones every client gets)."""

    def __init__(self, hub: Hub, project_id: str, *, origin: Origin = Origin.AGENT, tools: EditTools | None = None):
        if project_id not in hub.documents:
            raise KeyError(project_id)
        self._hub, self._project_id, self._origin = hub, project_id, origin
        self._tools = tools or EditTools()

    def call(self, tool: str, arguments: str | Mapping[str, Any], *, confirmed: Iterable[gd.OutOfCatalog | str] = ()) -> ToolResult:
        """Run the call against the document's current project and publish it. A call that introduces out-of-catalog values
        (G-04) is published only when the id of every one of its findings is in `confirmed`, the findings (or their `id`s)
        the user has seen and accepted (a result's `out_of_catalog`); otherwise nothing is published and the result has
        `needs_confirmation`. An id is bound to the definition's hash, so a value or definition that changed since needs a
        new confirmation. `confirmed` is a keyword of this method, never a field of the call: the model cannot confirm for
        the user."""
        document = self._hub.documents[self._project_id]
        result = self._tools.run(document.project, tool, arguments)
        if not result.ok:
            return result
        ids = {c if isinstance(c, str) else c.id for c in confirmed}
        unconfirmed = [f for f in result.out_of_catalog if f.id not in ids]
        if unconfirmed:
            labels = ", ".join(sorted({f.label for f in unconfirmed}))
            return replace(
                result,
                ok=False,
                needs_confirmation=True,
                summary=f"{tool} is out of the catalog ({labels}) and waits for the user's confirmation; nothing changed",
            )
        message = Publish(
            type="publish", id=uuid.uuid4().hex, base_revision=document.revision, command=result.command, origin=self._origin  # type: ignore[arg-type]
        )
        outcome = self._hub.publish(self._project_id, message)
        if outcome.reply.type == "rejected":
            return ToolResult(ok=False, tool=tool, summary=f"{tool} was refused by the document; nothing changed", reasons=tuple(outcome.reply.reasons))
        return replace(result, project=document.project, revision=outcome.reply.revision)
