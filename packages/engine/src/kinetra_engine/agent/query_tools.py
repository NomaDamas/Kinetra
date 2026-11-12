"""Query tools of the agent (G-02b): the calls an LLM (or the MCP server, G-08) makes to read the state of a project in numbers.

    tools = QueryTools()
    result = tools.run(project, "mass_properties", "{}")   # a pure function of `project`; nothing is edited or published
    result.data                                            # the numbers, each with its unit and badge, as the core computed them
    tools.record(started, frames, ended)                   # keep the summary of a finished run for `rollout_summary`
    HubQueryTools(hub, "car").call("statics_check", {})    # the same, against the document's current project

Rules (`docs/architecture/agent-query-tools.md`):

- **Read only.** A query never builds a `Command` and never publishes: `run` reads the project it is given and `HubQueryTools.call`
  reads the document's current project; the revision, history and subscribers do not see a query. There is no argument through
  which a query could set a value.
- **The core computes, the tool copies.** Every number is what a core function returned, unrounded: the instances, joints,
  actuators and schedule as the project holds them (`list_parts`); the masses of `compile_thrust`'s body tree (`mass_properties`,
  each instance's `mass_properties` of B-02 placed at its pose) and the propellant of its tanks at the start of a run; X-03a's
  `tipover` (`statics_check`); the frames and the end of a recorded run (`rollout_summary`, `summarize_rollout`). Nothing is
  estimated in this module: a tool that cannot get its number from the core is refused with the core's reason
  (`missing_definition` of C-06, the compiler's `CompileError` as the run request words it, a design in the ground).
- **Badges travel with the numbers.** What the project holds keeps its own badge (a parameter, a pose). What a core function
  computed is `sim`, with `computed_by` naming the function, and `input_badges` the badges of what it was computed from
  (`massprops.py`). The static check is an L0 analytic number and says so (`STATICS_LABEL`), with its assumptions. A run summary
  is one run: `ROLLOUT_NOTICE` (`client-adapter.md` F6) is in every summary, and no field reads as a verdict.
- **Calls are checked like the edit tools' (G-02a, G-04).** JSON object arguments, a strict `extra="forbid"` schema, an unknown
  tool or field is `invalid_command`, and the permission guard names an attempt at a planet constant, a verdict or the material
  catalog as `forbidden` before the schema.

A recorded run is the whole stream (`check_run` passes) of one run: `record` keeps only its summary, by `run_id`; the newest
record of a `run_id` replaces the older one. A summary says whether it was run on the design the query reads
(`definition_hash` against `project_hash` of the queried project).
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kinetra_core import (
    ActuateEntry,
    Badge,
    BreakEvent,
    ConditionMetEvent,
    ContactEvent,
    Frame,
    Project,
    ProjectIncomplete,
    Reason,
    ReasonCode,
    Ref,
    RefKind,
    RunEnded,
    RunStarted,
    SeparationEvent,
    check_run,
    project_hash,
)
from kinetra_core.conventions import ID_PATTERN
from kinetra_engine.protocol import Hub
from kinetra_engine.protocol.server import compile_reason

from ..compiler import CompileError, ThrustModel, compile_thrust
from ..compiler.bodytree import Vec, mv, quat_of, rot, vadd
from ..statics import BADGE_STRENGTH, InputBadges, TipoverError, tipover, weakest
from . import guard as gd

ROLLOUT_NOTICE = "1회 실행. 판정이 아닙니다"
"""In every run summary: the client's text for one run (`client-adapter.md` F6). A summary is a record of one run, never a verdict."""

STATICS_LABEL = "L0 해석 계산(X-03a 지지 다각형과 전복각). 시뮬도 판정도 아니다"
"""In every static check: what kind of number it is (`statics-tipover.md`)."""

SAMPLING_NOTE = "강체 프레임 원점의 자세를 받은 프레임에서만 읽었다(frame_every_ticks 틱마다와 끝 틱). 프레임 사이의 틱은 보지 않았다"
"""In every run summary: the extremes are over the frames of the stream, not over every tick."""

_MASS_BY = "kinetra_engine.compiler.compile_thrust (body tree X-01a: per-instance mass_properties B-02 at the stored pose; tank propellant X-01c)"
_STATICS_BY = "kinetra_engine.statics.tipover (X-03a) on the body tree of compile_thrust"
_ROLLOUT_BY = "kinetra_engine.agent.query_tools.summarize_rollout over the run's frames and run_ended"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ListPartsArgs(_Args):
    pass


class MassPropertiesArgs(_Args):
    pass


class StaticsCheckArgs(_Args):
    pass


class RolloutSummaryArgs(_Args):
    run_id: str | None = Field(default=None, pattern=ID_PATTERN, max_length=64, description="A recorded run; omitted: the newest one.")


_TOOLS: dict[str, tuple[type[_Args], str]] = {
    "list_parts": (
        ListPartsArgs,
        "Read the parts (instances with their part, material, parameters, pose and snap points), joints, actuators and control schedule of the project.",
    ),
    "mass_properties": (
        MassPropertiesArgs,
        "Read the mass and centre of mass of every part and of the whole design (dry, and with the propellant its tanks hold at the start), as the core computes them.",
    ),
    "statics_check": (
        StaticsCheckArgs,
        "Read the static check before a run: support polygon on the ground, centre-of-mass projection, margin and tip-over angle (L0 analysis, not a verdict).",
    ),
    "rollout_summary": (
        RolloutSummaryArgs,
        "Read the summary of a finished run: how it ended, where each body started and ended, its lowest and highest point and tilt, and its events. One run, not a verdict.",
    ),
}

QUERY_TOOL_NAMES = tuple(_TOOLS)


def query_specs() -> list[dict]:
    """The query tools as OpenAI function-tool objects, in the same shape as `edit_tools.specs()`."""
    return [
        {"type": "function", "function": {"name": name, "description": text, "parameters": model.model_json_schema()}}
        for name, (model, text) in _TOOLS.items()
    ]


@dataclass(frozen=True)
class QueryResult:
    """What a query returned. `ok`: `data` holds the numbers; otherwise `reasons` say why there are none."""

    ok: bool
    tool: str
    summary: str
    data: Mapping[str, Any] | None = None
    reasons: tuple[Reason, ...] = ()

    def to_json(self) -> dict:
        out: dict[str, Any] = {"ok": self.ok, "tool": self.tool, "summary": self.summary}
        if self.data is not None:
            out["data"] = dict(self.data)
        if self.reasons:
            out["reasons"] = [r.model_dump(mode="json") for r in self.reasons]
        return out


class QueryError(Exception):
    def __init__(self, reasons: tuple[Reason, ...]):
        super().__init__("; ".join(r.message for r in reasons))
        self.reasons = reasons


# --- shared numbers ----------------------------------------------------------------------------------------------


def _xyz(v: Vec) -> dict[str, float]:
    return {"x": float(v[0]), "y": float(v[1]), "z": float(v[2])}


def _quantity(q: Any) -> dict[str, Any]:
    return {"value": q.value, "unit": q.unit.value, "badge": q.badge.value}


def _badges(badges: Iterable[Badge]) -> list[str]:
    order = list(Badge)
    return [b.value for b in sorted(set(badges), key=order.index)]


def _strength(badges: Iterable[Badge]) -> tuple[Badge, ...]:
    """Distinct `badges`, strongest first (`BADGE_STRENGTH`, X-07)."""
    return tuple(sorted(set(badges), key=BADGE_STRENGTH.index))


def _weighted(rows: Iterable[tuple[float, Vec]]) -> tuple[float, Vec]:
    rows = list(rows)
    mass = math.fsum(m for m, _ in rows)
    return mass, tuple(math.fsum(m * c[k] for m, c in rows) / mass for k in range(3))  # type: ignore[return-value]


def _compile(project: Project) -> ThrustModel:
    try:
        return compile_thrust(project)
    except ProjectIncomplete as e:
        raise QueryError(tuple(e.reasons)) from e
    except CompileError as e:
        raise QueryError((compile_reason(e),)) from e


# --- the tools ---------------------------------------------------------------------------------------------------


def list_parts(project: Project) -> dict[str, Any]:
    """The design as the project holds it. An instance whose part the project does not carry (a placeholder, C-06) is listed
    with `missing_definition` and no snap points: nothing is made up for it."""
    design = project.design
    parts = {p.id: p for p in design.parts}
    materials = {m.id for m in design.materials}
    instances = []
    for inst in design.instances:
        part = parts.get(inst.part)
        p = inst.pose
        row: dict[str, Any] = {
            "id": inst.id,
            "part": inst.part,
            "part_name": part.name if part is not None else None,
            "role": part.role.value if part is not None and part.role is not None else None,
            "material": inst.material,
            "parameters": [{"name": v.name, **_quantity(v)} for v in inst.parameters],
            "pose": {
                "position": {"x": p.position.x, "y": p.position.y, "z": p.position.z, "unit": "m"},
                "orientation": {"x": p.orientation.x, "y": p.orientation.y, "z": p.orientation.z, "w": p.orientation.w},
                "badge": p.badge.value,
            },
            "snap_points": [s.id for s in part.snap_points] if part is not None else [],
        }
        missing = [kind for kind, ok in (("part", part is not None), ("material", inst.material is None or inst.material in materials)) if not ok]
        if missing:
            row["missing_definition"] = missing
        instances.append(row)
    joints = []
    for j in design.joints:
        row = {"id": j.id, "kind": j.kind.value, "a": {"instance": j.a.instance, "snap_point": j.a.snap_point}, "b": {"instance": j.b.instance, "snap_point": j.b.snap_point}}
        if j.limits is not None:
            row["limits"] = j.limits.model_dump(mode="json")
        if j.break_threshold is not None:
            row["break_threshold"] = j.break_threshold.model_dump(mode="json")
        joints.append(row)
    return {
        "planet": project.world.planet,
        "instances": instances,
        "joints": joints,
        "actuators": [{"id": a.id, "kind": a.kind.value, "instance": a.instance, "joint": a.joint, "supply": a.supply} for a in design.actuators],
        "schedule": [
            {"type": "actuate", "id": e.id, "actuator": e.actuator, "start_s": e.start, "end_s": e.end, "command": e.command, "badge": e.badge.value}
            if isinstance(e, ActuateEntry)
            else {"type": "separate", "id": e.id, "separator": e.separator, "at_s": e.at, "badge": e.badge.value}
            for e in design.schedule.entries
        ],
    }


def mass_summary(model: ThrustModel) -> dict[str, Any]:
    """Masses [kg] and centres of mass [m, world] of `model`: per instance, the dry design, and the design with what its tanks
    hold at the start of a run (`Supply.remaining`, X-01c)."""
    tree = model.tree
    rows = []
    for ci in tree.instances:
        p = ci.properties
        c = p.center_of_mass
        world = vadd(mv(rot(ci.orientation), (c.x, c.y, c.z)), ci.position)
        rows.append(
            {
                "instance": ci.instance,
                "part": ci.part,
                "material": ci.material,
                "body": ci.body,
                "mass_kg": p.mass.value,
                "center_of_mass_m": _xyz(world),
                "input_badges": _badges(p.derivation.input_badges),
            }
        )
    dry, dry_com = _weighted((r["mass_kg"], tuple(r["center_of_mass_m"].values())) for r in rows)
    frames = {ci.instance: (ci.position, ci.orientation) for ci in tree.instances}
    loaded = [(r["mass_kg"], tuple(r["center_of_mass_m"].values())) for r in rows]
    for s in model.stores:  # the propellant at the centre of the tank's inside (`PropellantStore`, X-01c)
        t, q = frames[s.body]  # a body's frame is its smallest instance's, whose id it carries
        loaded.append((s.supply.remaining, vadd(mv(rot(q), s.centroid), t)))
    wet, wet_com = _weighted(loaded)
    return {
        "badge": Badge.SIM.value,
        "computed_by": _MASS_BY,
        "instances": rows,
        "dry": {"mass_kg": dry, "center_of_mass_m": _xyz(dry_com)},
        "propellant": [
            {"tank": s.instance, "body": s.body, "mass_kg": s.supply.remaining, "capacity_kg": s.supply.capacity.value, "input_badges": _badges(s.supply.input_badges)}
            for s in model.stores
        ],
        "with_propellant": {"mass_kg": wet, "center_of_mass_m": _xyz(wet_com)},
        "input_badges": _badges(b for ci in tree.instances for b in ci.properties.derivation.input_badges),
    }


def statics_summary(model: ThrustModel) -> dict[str, Any]:
    """X-03a's `tipover` of `model`'s body tree, as numbers with their units, and the badges of what it was computed from
    (`inputs`, rows like X-07's `InputBadges`, strongest first): `mass` is every instance's B-01a `Derivation.input_badges` (the
    shape, density and parameters the masses and the collision proxies both come from), `pose` the stored poses' badges, and
    `gravity` the data file's (`data/bodies`; only its direction enters the check). `badge` is the weakest of them (X-07's
    `weakest`): a computed value is never better than its weakest input. Raises `QueryError` for a design in the ground."""
    try:
        t = tipover(model.tree)
    except TipoverError as e:
        raise QueryError((Reason(code=ReasonCode.OVERLAP, message=f"the static check cannot rest the design on the ground: {e}", ids=tuple(Ref(kind=RefKind.INSTANCE, id=i) for i in e.instances)),)) from e

    def point(s: Any) -> dict[str, Any]:
        return {"instance": s.instance, "geom": s.geom, **_xyz(s.point)}

    tree = model.tree
    inputs = (
        InputBadges("mass", _strength(b for ci in tree.instances for b in ci.properties.derivation.input_badges)),
        InputBadges("pose", _strength(i.pose.badge for i in tree.design.instances)),
        InputBadges("gravity", (tree.planet.gravity.badge,)),
    )
    return {
        "label": STATICS_LABEL,
        "badge": weakest(b for r in inputs for b in r.badges).value,
        "inputs": [{"input": r.input, "badges": [b.value for b in r.badges]} for r in inputs],
        "computed_by": _STATICS_BY,
        "mass_kg": t.mass,
        "center_of_mass_m": _xyz(t.center_of_mass),
        "com_projection_m": {"x": t.com_projection[0], "y": t.com_projection[1]},
        "com_height_m": t.com_height,
        "support": t.kind,
        "support_points": len(t.contacts),
        "polygon": [point(s) for s in t.polygon],
        "edges": [
            {"a": point(e.a), "b": point(e.b), "distance_m": e.distance, "angle_rad": e.angle, "angle_deg": math.degrees(e.angle)} for e in t.edges
        ],
        "margin_m": t.margin,
        "tipover_angle_rad": t.tipover_angle,
        "tipover_angle_deg": None if t.tipover_angle is None else math.degrees(t.tipover_angle),
        "stable": t.stable,
        "approximations": list(t.approximations),
        "assumptions": list(t.assumptions),
    }


def _tilt(q0: Any, q1: Any) -> float:
    """Angle [rad] between the world up axis carried by the turn from orientation `q0` to `q1` and the world up axis: how far
    the body tipped since `q0`, whatever it turned about the vertical."""
    r0, r1 = rot(quat_of(q0)), rot(quat_of(q1))
    up = sum(r1[2][k] * r0[2][k] for k in range(3))  # (R1 R0^T)[2][2]
    return math.acos(max(-1.0, min(1.0, up)))


def summarize_rollout(started: RunStarted, frames: Iterable[Frame], ended: RunEnded) -> dict[str, Any]:
    """The summary of one whole run stream. Raises `ValueError` (`check_run`) unless `frames` and `ended` are the whole stream of
    `started`. Every number is a value of the stream or a difference, distance or angle of two of its poses."""
    frames = list(frames)
    check_run(started, frames, ended)
    first, last = frames[0], frames[-1]
    bodies = []
    for b in started.bodies:
        poses = [next(p for p in f.poses if p.body == b.id) for f in frames]
        p0, p1 = poses[0].position, poses[-1].position
        d = (p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
        tilts = [_tilt(poses[0].orientation, p.orientation) for p in poses]
        low = min(range(len(poses)), key=lambda i: poses[i].position.z)
        high = max(range(len(poses)), key=lambda i: poses[i].position.z)
        bodies.append(
            {
                "body": b.id,
                "instances": list(b.instances),
                "start_m": _xyz((p0.x, p0.y, p0.z)),
                "end_m": _xyz((p1.x, p1.y, p1.z)),
                "displacement_m": _xyz(d),
                "distance_m": math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2),
                "horizontal_distance_m": math.hypot(d[0], d[1]),
                "lowest_z_m": poses[low].position.z,
                "lowest_at_tick": frames[low].tick,
                "highest_z_m": poses[high].position.z,
                "highest_at_tick": frames[high].tick,
                "end_tilt_deg": math.degrees(tilts[-1]),
                "max_tilt_deg": math.degrees(max(tilts)),
            }
        )
    events = [e for f in frames for e in f.events]
    counts: dict[str, int] = {}
    for e in events:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    end = ended.end
    trajectory = getattr(end, "trajectory", None)
    return {
        "notice": ROLLOUT_NOTICE,
        "badge": started.badge,
        "computed_by": _ROLLOUT_BY,
        "run_id": started.run_id,
        "kind": started.kind.value,
        "project_id": started.project_id,
        "revision": started.revision,
        "definition_hash": started.definition_hash,
        "planet": started.planet,
        "seed": started.seed,
        "timestep_s": started.timestep_s,
        "frame_every_ticks": started.frame_every_ticks,
        "frames": len(frames),
        "start_tick": first.tick,
        "last_tick": ended.last_tick,
        "end_time_s": last.sim_time_s,
        "end": end.reason,
        # H1: the hash goes with its platform tag, as `run_ended` carries them (a hash without its tag is not evidence); none for a failed run
        "trajectory": trajectory.model_dump(mode="json") if trajectory is not None else None,
        "model_labels": list(started.model_labels),
        "sampling": SAMPLING_NOTE,
        "bodies": bodies,
        "events": counts,
        "breaks": [e.model_dump(mode="json") for e in events if isinstance(e, BreakEvent)],
        "separations": [e.model_dump(mode="json") for e in events if isinstance(e, SeparationEvent)],
        "conditions_met": [e.model_dump(mode="json") for e in events if isinstance(e, ConditionMetEvent)],
        "contacts_begun": sum(1 for e in events if isinstance(e, ContactEvent) and e.phase == "begin"),
    }


class QueryTools:
    """The query tools. Holds the summaries of the runs it was given (`record`); `run` is otherwise a function of `project`."""

    specs = staticmethod(query_specs)

    def __init__(self) -> None:
        self._rollouts: dict[str, str] = {}  # run_id -> the summary as JSON text: every read is a new object, no caller can change a record
        self._rollouts_lock = threading.Lock()  # MCP runs in a worker thread while queries stay on the event loop

    def record(self, started: RunStarted, frames: Iterable[Frame], ended: RunEnded) -> dict[str, Any]:
        """Summarize a finished run (`summarize_rollout`) and keep the summary under its `run_id` for `rollout_summary`. The
        record is kept as JSON text; what is returned (here and by every query) is a fresh copy."""
        text = json.dumps(summarize_rollout(started, frames, ended), ensure_ascii=False)
        with self._rollouts_lock:
            self._rollouts.pop(started.run_id, None)
            self._rollouts[started.run_id] = text
        return json.loads(text)

    def run(self, project: Project, tool: str, arguments: str | Mapping[str, Any]) -> QueryResult:
        """Answer one query about `project`. Never raises for a bad call and never changes `project`; the result says why."""
        entry = _TOOLS.get(tool)
        if entry is None:
            named = gd.guard_tool(tool)  # G-04: `set_gravity` is an attempt, not a typo
            return _refused(tool, named or (Reason(code=ReasonCode.INVALID_COMMAND, message=f"unknown tool {tool!r}; the query tools are {list(QUERY_TOOL_NAMES)}"),))
        if isinstance(arguments, str) and gd.json_too_deep(arguments):
            return _refused(tool, (Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: the arguments nest deeper than {gd.MAX_ARGUMENT_DEPTH} levels; no tool takes that"),))
        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (ValueError, TypeError) as e:
            return _refused(tool, (Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: the arguments are not JSON: {e}"),))
        if not isinstance(raw, dict):
            return _refused(tool, (Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: the arguments must be a JSON object"),))
        forbidden = gd.guard_arguments(tool, raw)
        if forbidden:
            return _refused(tool, forbidden)
        try:
            args = entry[0].model_validate(raw)
        except ValidationError as e:
            return _refused(
                tool,
                tuple(
                    Reason(code=ReasonCode.INVALID_COMMAND, message=f"{tool}: not a valid call: {'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}")
                    for err in e.errors()
                ),
            )
        try:
            data, summary = getattr(self, f"_{tool}")(project, args)
        except QueryError as e:
            return _refused(tool, e.reasons)
        return QueryResult(ok=True, tool=tool, summary=summary, data=data)

    def _list_parts(self, project: Project, _: ListPartsArgs) -> tuple[dict, str]:
        data = list_parts(project)
        return data, f"{len(data['instances'])} part(s), {len(data['joints'])} joint(s), {len(data['actuators'])} actuator(s), {len(data['schedule'])} schedule entries"

    def _mass_properties(self, project: Project, _: MassPropertiesArgs) -> tuple[dict, str]:
        data = mass_summary(_compile(project))
        return data, f"dry mass {data['dry']['mass_kg']!r} kg, with propellant {data['with_propellant']['mass_kg']!r} kg (computed, badge sim)"

    def _statics_check(self, project: Project, _: StaticsCheckArgs) -> tuple[dict, str]:
        data = statics_summary(_compile(project))
        return data, f"support {data['support']}, margin {data['margin_m']!r} m, tip-over angle {data['tipover_angle_deg']!r} deg ({STATICS_LABEL})"

    def _rollout_summary(self, project: Project, args: RolloutSummaryArgs) -> tuple[dict, str]:
        with self._rollouts_lock:
            if not self._rollouts:
                raise QueryError((Reason(code=ReasonCode.UNKNOWN_ID, message="no run has been recorded yet; a run is summarized once it has ended"),))
            run_id = args.run_id or next(reversed(self._rollouts))
            text = self._rollouts.get(run_id)
            if text is None:
                raise QueryError((Reason(code=ReasonCode.UNKNOWN_ID, message=f"no recorded run {run_id!r}; the recorded runs are {list(self._rollouts)}"),))
        summary = json.loads(text)
        current = summary["definition_hash"] == project_hash(project)
        data = {**summary, "current_design": current}
        return data, f"run {run_id!r} ended {summary['end']} at tick {summary['last_tick']}; {ROLLOUT_NOTICE}" + ("" if current else "; it was run on another version of the design")


def _refused(tool: str, reasons: tuple[Reason, ...]) -> QueryResult:
    return QueryResult(ok=False, tool=tool, summary=f"{tool} was refused; nothing was read", reasons=reasons)


class HubQueryTools:
    """The query tools of one project of a `Hub`: a call reads the document's current project. Nothing is published."""

    def __init__(self, hub: Hub, project_id: str, *, tools: QueryTools | None = None):
        if project_id not in hub.documents:
            raise KeyError(project_id)
        self._hub, self._project_id = hub, project_id
        self.tools = tools or QueryTools()

    def call(self, tool: str, arguments: str | Mapping[str, Any]) -> QueryResult:
        return self.tools.run(self._hub.documents[self._project_id].project, tool, arguments)
