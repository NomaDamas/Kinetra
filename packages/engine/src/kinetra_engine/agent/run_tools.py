"""Run and verdict request tools of the agent (G-02c): the agent may ask the core for a run or a verdict and read the answer; it
can never write one.

    tools = RunTools(hub, "car")                                  # one project of a `Hub` (C-05a); `judge` is J-01's
    result = tools.call("request_run", {"duration_s": 2.0})       # one preview run of the document as it is now
    result.started, result.first_frame, result.last_frame, result.ended    # the run's own messages, frozen
    tools.call("request_verdict", {"seed": 7})                    # the core's judge, or "no verdict engine yet"

Rules (`docs/architecture/agent-edit-tools.md`, "실행·판정 요청 도구 (G-02c)"):

- **A request changes no document (C7).** Both tools read the document's current project, revision and verdict state through
  the `Hub` and publish nothing: no revision, no history entry, no `applied`, no change of the verdict state.
- **A run is a preview, never a verdict (V1, F6).** `request_run` is the channel's `run` (X-02a) without a connection: the same
  `PreviewRun` (kind `preview`, badge `sim`), stepped to its end in the calling thread. Its result carries `is_verdict: false` and
  `RUN_LABEL`, and the arguments have no field for the kind of run, so an agent cannot ask for a `verdict_sample`.
- **A verdict comes only from the core's judge (simulation and Monte Carlo, V1).** `request_verdict` hands the document as it is
  to the `judge` the core was given (J-01d connects J-01's judge here) and returns its content as it is, bound to the revision and
  `definition_hash` the tool read. A core without a judge says so (`ok: false`, nothing run): a preview run is never offered in
  place of a verdict.
- **The result can only be read.** `RunToolResult` is a frozen dataclass; the run's messages are frozen models; the verdict content
  is frozen on the way in (objects become read-only mappings, lists become tuples). No tool takes a verdict, a p_success or a CI:
  the guard of G-04 refuses such a key, or a tool named for writing one (`set_verdict`, `write_p_success`), as `forbidden` before
  the schema; the schemas are `extra="forbid"`; and the closed `Command` union has no command that carries a verdict (C-02c).
- Same conventions as the edit tools (G-02a): tool specs are OpenAI function-tool objects (`run_specs()`), a call is a tool name and
  its JSON arguments (text or an object), and a bad call is a result with reasons, never an exception.

Limits (not hidden): `call` runs the engine in the calling thread until the run ends, as long as `duration_s` asks (at most the
`MAX_TICK` ticks a run counts, like the channel's `run`); a caller on an event loop runs it in a worker thread. The run's frames
other than the first and the last are not kept.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kinetra_core import Frame, Project, ProjectIncomplete, Reason, ReasonCode, RunEnded, RunKind, RunStarted, project_hash
from kinetra_core.frames import MAX_SEED
from kinetra_engine.compiler import CompileError
from kinetra_engine.protocol import Hub
from kinetra_engine.protocol.server import compile_reason
from kinetra_engine.run import PreviewRun

from . import guard as gd

RUN_LABEL = "1회 실행. 판정이 아닙니다"
"""Shown with every run result: the words a client shows for a preview run (`client-adapter.md` F6, plan 4.5 L1)."""

_Seed = Annotated[int, Field(strict=True, ge=0, le=MAX_SEED)]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequestRunArgs(_Args):
    """Run the project once as it is now, for `duration_s` seconds of simulated time. A preview, not a verdict."""

    duration_s: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, description="Simulated time to run [s].")]
    seed: _Seed = Field(default=0, description="Recorded with the run; the preview run draws nothing from it yet.")


class RequestVerdictArgs(_Args):
    """Ask the core's judge (simulation and Monte Carlo) for a verdict on the project as it is now."""

    seed: _Seed = Field(default=0, description="The seed of the judge's sampling.")


_TOOLS: dict[str, tuple[type[_Args], str]] = {
    "request_run": (
        RequestRunArgs,
        "Run the project once as it is now and read how it ended: the first and last poses, the end, the trajectory hash. "
        "A preview, never a verdict; the project does not change.",
    ),
    "request_verdict": (
        RequestVerdictArgs,
        "Ask the core's judge for a verdict on the project as it is now and read it. Only the core's simulation and Monte "
        "Carlo make a verdict; the project does not change.",
    ),
}

RUN_TOOL_NAMES = tuple(_TOOLS)


def run_specs() -> list[dict]:
    """The tools as OpenAI function-tool objects, like `edit_tools.specs()`."""
    return [
        {"type": "function", "function": {"name": name, "description": text, "parameters": model.model_json_schema()}}
        for name, (model, text) in _TOOLS.items()
    ]


# --- verdict ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictRequest:
    """What the judge is asked: the document as the tool read it."""

    project_id: str
    revision: int
    definition_hash: str
    project: Project
    seed: int


Judge = Callable[[VerdictRequest], Mapping[str, Any]]
"""The core's judge (J-01): a verdict's content, as J's schema has it, for one request. Connected by J-01d."""


def freeze(value: Any) -> Any:
    """`value` (JSON data) made read-only all the way down: objects become `MappingProxyType`s of their frozen values, lists
    and tuples become tuples. Raises `TypeError` for anything that is not JSON data (a key that is not a string, a set, an
    object) and `ValueError` for a non-finite number (NaN, ±inf: JSON has none), so what the judge gives is what `to_json`
    can show."""
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("a verdict's object keys are strings")
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"a verdict holds JSON numbers, and {value!r} is not one")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"a verdict holds JSON data, not {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class Verdict:
    """A verdict of the core's judge on the document at `revision` (`definition_hash`), read-only."""

    project_id: str
    revision: int
    definition_hash: str
    seed: int
    content: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.content, MappingProxyType):
            raise TypeError("a verdict's content is a frozen JSON object (`freeze` of the judge's mapping)")

    def to_json(self) -> dict:
        return {
            "by": "core",
            "project_id": self.project_id,
            "revision": self.revision,
            "definition_hash": self.definition_hash,
            "seed": self.seed,
            "content": _thaw(self.content),
        }


# --- result -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunToolResult:
    """What a run or verdict request answered. Frozen, and so is everything in it.

    `request_run`: `started`, `first_frame`, `last_frame` and `ended` are the run's own `run_started`, tick-0 frame, end frame
    and `run_ended` (X-02a). `request_verdict`: `verdict` is the judge's, `None` when the core has none. `verdict_state` is the
    document's (`none`, `valid`, `invalid`; D5) when the tool read it. `reasons` say why a request was refused."""

    ok: bool
    tool: str
    summary: str
    reasons: tuple[Reason, ...] = ()
    revision: int | None = None
    verdict_state: str | None = None
    started: RunStarted | None = None
    first_frame: Frame | None = None
    last_frame: Frame | None = None
    ended: RunEnded | None = None
    verdict: Verdict | None = None

    def to_json(self) -> dict:
        """What goes back to the model. A run is labelled as no verdict; a verdict is the core's."""
        out: dict[str, Any] = {"ok": self.ok, "tool": self.tool, "summary": self.summary}
        if self.revision is not None:
            out["revision"] = self.revision
        if self.verdict_state is not None:
            out["verdict_state"] = self.verdict_state
        if self.reasons:
            out["reasons"] = [r.model_dump(mode="json") for r in self.reasons]
        if self.started is not None:
            out["is_verdict"] = False
            out["label"] = RUN_LABEL
            out["run"] = {
                "started": self.started.model_dump(mode="json"),
                "first_frame": self.first_frame.model_dump(mode="json") if self.first_frame else None,
                "last_frame": self.last_frame.model_dump(mode="json") if self.last_frame else None,
                "ended": self.ended.model_dump(mode="json") if self.ended else None,
            }
        if self.verdict is not None:
            out["verdict"] = self.verdict.to_json()
        return out


def _refused(tool: str, *reasons: Reason) -> RunToolResult:
    return RunToolResult(ok=False, tool=tool, summary=f"{tool} was refused; nothing was run", reasons=reasons)


def _invalid(message: str) -> Reason:
    return Reason(code=ReasonCode.INVALID_COMMAND, message=message)


# --- the tools ----------------------------------------------------------------------------------------------------


class RunTools:
    """The run and verdict request tools of one project of a `Hub`. Read the document; never publish."""

    def __init__(self, hub: Hub, project_id: str, *, judge: Judge | None = None):
        if project_id not in hub.documents:
            raise KeyError(project_id)
        self._hub, self._project_id, self._judge = hub, project_id, judge

    specs = staticmethod(run_specs)

    def call(self, tool: str, arguments: str | Mapping[str, Any]) -> RunToolResult:
        """Answer one call. Never raises for a bad call; the result says why."""
        entry = _TOOLS.get(tool)
        if entry is None:
            named = gd.guard_tool(tool)  # G-04: `set_verdict` is an attempt, not a typo
            return _refused(tool, *(named or (_invalid(f"unknown tool {tool!r}; the run tools are {list(RUN_TOOL_NAMES)}"),)))
        too_deep = _invalid(f"{tool}: the arguments nest deeper than {gd.MAX_ARGUMENT_DEPTH} levels; no tool takes that")
        if isinstance(arguments, str) and gd.json_too_deep(arguments):
            return _refused(tool, too_deep)
        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (ValueError, TypeError) as e:
            return _refused(tool, _invalid(f"{tool}: the arguments are not JSON: {e}"))
        except RecursionError:
            return _refused(tool, too_deep)
        if not isinstance(raw, dict):
            return _refused(tool, _invalid(f"{tool}: the arguments must be a JSON object"))
        forbidden = gd.guard_arguments(tool, raw)  # G-04: a verdict key is an attempt to write one
        if forbidden:
            return _refused(tool, *forbidden)
        try:
            args = entry[0].model_validate(raw)
        except ValidationError as e:
            return _refused(
                tool,
                *(_invalid(f"{tool}: not a valid call: {'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}") for err in e.errors()),
            )
        if isinstance(args, RequestRunArgs):
            return self._request_run(args)
        return self._request_verdict(args)  # type: ignore[arg-type]

    def _request_run(self, args: RequestRunArgs) -> RunToolResult:
        tool = "request_run"
        document = self._hub.documents[self._project_id]
        revision = document.revision
        try:
            run = PreviewRun(
                document.project,
                run_id=uuid.uuid4().hex,
                project_id=self._project_id,
                revision=revision,
                duration_s=args.duration_s,
                seed=args.seed,
                kind=RunKind.PREVIEW,
            )
        except ProjectIncomplete as e:
            return _refused(tool, *e.reasons)
        except CompileError as e:
            return _refused(tool, compile_reason(e))
        except ValueError as e:  # a duration longer than a run can count
            return _refused(tool, _invalid(str(e)))
        first = last = ended = None
        for item in run:
            if isinstance(item, Frame):
                first = first or item
                last = item
            else:
                ended = item
        assert ended is not None and last is not None  # a run always yields a frame, then its run_ended
        reason = ended.end.reason
        how = {"completed": "completed", "failed": "failed: the engine met a non-finite state"}.get(reason, reason)
        return RunToolResult(
            ok=True,
            tool=tool,
            summary=f"one preview run of revision {revision}, {how} at tick {ended.last_tick} ({last.sim_time_s:g} s); {RUN_LABEL}",
            revision=revision,
            verdict_state=document.verdict.value,
            started=run.started,
            first_frame=first,
            last_frame=last,
            ended=ended,
        )

    def _request_verdict(self, args: RequestVerdictArgs) -> RunToolResult:
        tool = "request_verdict"
        document = self._hub.documents[self._project_id]
        revision, state = document.revision, document.verdict.value
        if self._judge is None:
            return RunToolResult(
                ok=False,
                tool=tool,
                summary=(
                    "this core has no verdict engine yet (J-01): a verdict comes only from the core's simulation and Monte "
                    "Carlo, and a preview run is not one; nothing was run"
                ),
                revision=revision,
                verdict_state=state,
            )
        project = document.project
        request = VerdictRequest(self._project_id, revision, project_hash(project), project, args.seed)
        verdict = Verdict(self._project_id, revision, request.definition_hash, args.seed, freeze(self._judge(request)))
        return RunToolResult(
            ok=True,
            tool=tool,
            summary=f"the core's verdict on revision {revision}",
            revision=revision,
            verdict_state=state,
            verdict=verdict,
        )
