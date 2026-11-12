"""The run stream: `run_started`, `frame`, `run_ended` (C-05b; `client-adapter.md` 3.3).

These are the *content* of the run stream (rule G1: transport-neutral), in the same package as the document messages
(`protocol.py`) so `export_schemas.py` types them for every client. Nothing here names an engine's internals (rule
(G2/F1): a body is a rigid body of the project, a pose is a position and a quaternion, an event is a contact, a break
(a joint released over its threshold), a separation (a joint released on purpose, X-08), a met condition, or an observed
overturn/slip/torque-shortage/propellant-depletion threshold crossing (J-06 telemetry). The engine's name and version
appear only as *values* of the platform tag.

Two forms of one frame (same meaning, same checks):

- **JSON** (`Frame`): self-describing, every pose names its body. Used by recordings, fixtures, shared bundles, the
  headless reference client and any small scene.
- **Binary** (`encode_frame` / `decode_frame`): one WebSocket binary message per frame for the live stream, 28 bytes per
  body. Poses go by position in `RunStarted.bodies`, so the body list of a run is fixed (F8, S1).

Conventions (G4): SI units (m, s, N), right-handed, +Z up. A quaternion has the components `x, y, z, w` (`w` the scalar,
unit length), exactly as in the Project JSON (`conventions.QUATERNION_COMPONENTS`). In JSON they are named; in the
binary pose block they are four consecutive float32 in that order.

Time (F2): a `tick` is a step of the physics integrator, counted from 0; `sim_time_s = tick * timestep_s`. A frame is
sent every `frame_every_ticks` ticks, so the frame rate is `1 / (timestep_s * frame_every_ticks)` of *simulated* time and
means nothing about wall time. An event carries the tick it happened at, which can lie between two frames; a frame
carries the events since the previous frame (`previous.tick < event.tick <= frame.tick`).

Values: every number in the stream is the engine's own output, badge `sim` (G6), said once by `RunStarted.badge`
instead of per number. The stream is what the engine produced, not a verdict: `RunStarted.kind` says whether the client
may call it a preview (F6).

The platform tag (A0-05, `docs/decisions/engine.md` 5.4, H1) is the eight run conditions that can change a trajectory
hash. `PlatformTag` forbids unknown fields on purpose: a ninth component changes what "same tag" means, so it is a new
protocol number and not a field a client silently ignores. The trajectory hash is only evidence together with its tag:
`RunCompleted.trajectory` and `RunStopped.trajectory` hold both or neither (the JSON Schema says so: those variants
require it, `RunFailed` has none).

A conditional rule is a discriminated union, never an after-validator, so the generated JSON Schema (and a client built from
it) enforces what the model enforces: `PlatformTag.engine` by `distribution`, `ContactEvent.other` by its `kind`,
`RunEnded.end` by `reason`.

Messages ignore fields they do not know (G5), like the document messages; a client ignores a `type` it does not know.
Not here: the trajectory hash computation (`kinetra_engine.run.preview`) and the comparison of two records
(`trajectory.py`, X-02d), `control` and acknowledgement messages (X-02c, flow control #420), the transport
of binary messages in `kinetra_engine.protocol` (X-02).
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .conventions import ID_PATTERN, NAME_PATTERN, Unit
from .designspec import WorldPosition
from .geometry import Quaternion
from .provenance import Badge, Number

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_Name = Annotated[str, Field(pattern=NAME_PATTERN)]
_Text = Annotated[str, Field(min_length=1, max_length=200)]
_Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_RunId = Annotated[str, Field(min_length=1, max_length=128)]
_Revision = Annotated[int, Field(strict=True, ge=0)]
_Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
_NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]

MAX_TICK = 2**32 - 1
"""Largest tick and body count: the binary header stores both as an unsigned 32-bit integer."""
MAX_SEED = 2**53 - 1
"""Largest seed: `Number.MAX_SAFE_INTEGER`, the largest integer a JavaScript client reads exactly from JSON."""

_Tick = Annotated[int, Field(strict=True, ge=0, le=MAX_TICK)]
_Count = Annotated[int, Field(strict=True, ge=1, le=MAX_TICK)]


class _Obj(BaseModel):
    """A stream object ignores fields it does not know (G5) and is immutable."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class _Strict(BaseModel):
    """Unknown fields are an error: the platform tag (a ninth component changes what "same tag" means), and the two
    variants that must lack something, `GroundTarget` (no id) and `RunFailed` (no trajectory)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --- platform tag (engine.md 5.4 table, the eight components) -------------------------------------------------


class OsTag(_Strict):
    """① Operating system: kind (`linux`, `macos`, ...) and kernel release."""

    kind: _Text
    kernel_release: _Text


class CpuTag(_Strict):
    """② CPU: architecture (`x86_64`, `arm64`, ...) and model string."""

    architecture: _Text
    model: _Text


class _EngineBase(_Strict):
    """④ The physics engine: its name and version are values, never field names."""

    name: _Text
    version: _Text


class WheelEngine(_EngineBase):
    """Distributed as a package wheel (PyPI): the hash of the distributed file identifies the binary."""

    distribution: Literal["wheel"]
    artifact_hash: _Hash


class WasmEngine(_EngineBase):
    """Distributed as a WASM package: the hash of the distributed file identifies the binary."""

    distribution: Literal["wasm_package"]
    artifact_hash: _Hash


class CustomBuildEngine(_EngineBase):
    """Built by us: the compiler and the build flags identify the binary (`build_flags` may be an empty string)."""

    distribution: Literal["custom_build"]
    compiler: _Text
    build_flags: Annotated[str, Field(max_length=2000)]


EngineTag = Annotated[Union[WheelEngine, WasmEngine, CustomBuildEngine], Field(discriminator="distribution")]
"""Which fields identify the engine binary depends on how it was distributed, so the JSON Schema says it: a wheel or a
WASM package requires `artifact_hash`, a custom build requires `compiler` and `build_flags`, and none of them may be
`null` or missing."""


class RuntimeTag(_Strict):
    """⑤ Python and NumPy versions."""

    python: _Text
    numpy: _Text


class CoreBuildTag(_Strict):
    """⑥ The core build: its commit (the force-applying paths and their order are in it)."""

    commit: Annotated[str, Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")]


SolverValue = Union[Number, bool, str]
"""One solver setting's value."""


def _solver_names_schema(schema: dict) -> None:
    """pydantic writes a constrained dict key as `patternProperties`, which lets a non-matching key through in JSON
    Schema. Rewrite it as `propertyNames` (same pattern, from the same `Field`) and `additionalProperties` (the value
    schema), so the schema refuses exactly the names the model refuses."""
    ((pattern, value),) = schema.pop("patternProperties").items()
    schema["propertyNames"] = {"pattern": pattern}
    schema["additionalProperties"] = value


class ComputeTag(_Strict):
    """⑦ The settings the run actually used: integrator, `timestep_s` [s] and the solver's settings by name
    (`NAME_PATTERN`)."""

    integrator: _Text
    timestep_s: _Positive
    solver: Annotated[dict[_Name, SolverValue], Field(json_schema_extra=_solver_names_schema)]


class ThreadTag(_Strict):
    """⑧ Thread counts of the physics step and of the solver."""

    physics: Annotated[int, Field(strict=True, ge=1)]
    solver: Annotated[int, Field(strict=True, ge=1)]


class PlatformTag(_Strict):
    """The eight run conditions of `engine.md` 5.4 (H1). Two tags are the same tag when all eight are equal
    (`==`). `image_digest` is required and `None` means "no image" (not a container): leaving it out is an error, so
    a run cannot lose that component by omission."""

    os: OsTag
    cpu: CpuTag
    image_digest: _Hash | None
    engine: EngineTag
    runtime: RuntimeTag
    core_build: CoreBuildTag
    compute: ComputeTag
    threads: ThreadTag


# --- run_started ----------------------------------------------------------------------------------------------


class RunKind(StrEnum):
    PREVIEW = "preview"  # one run: the client shows "1회 실행. 판정이 아닙니다" (F6)
    VERDICT_SAMPLE = "verdict_sample"  # one sample of a verdict's Monte Carlo


class BodyRef(_Obj):
    """A rigid body of the run and the project instances it consists of (welded instances move as one body). `id` is
    the body's stable id (G3): a pose's `body`, a contact's `body` and a body `other` name it. A break names a joint
    (`Joint.id` of the project), not a body."""

    id: _Id
    instances: Annotated[tuple[_Id, ...], Field(min_length=1)]


class RunStarted(_Obj):
    """A run begins. `revision` and `definition_hash` name the document the run was compiled from, `bodies` is the
    fixed body list in the order of the binary pose block, `platform` the platform tag the trajectory hash at the end
    belongs to. `frame_every_ticks` is how many ticks lie between two frames."""

    type: Literal["run_started"]
    run_id: _RunId
    kind: RunKind
    badge: Literal[Badge.SIM]
    project_id: _Id
    revision: _Revision
    definition_hash: _Hash
    planet: _Id
    seed: Annotated[int, Field(strict=True, ge=0, le=MAX_SEED)]
    timestep_s: _Positive
    frame_every_ticks: Annotated[int, Field(strict=True, ge=1)]
    bodies: Annotated[tuple[BodyRef, ...], Field(min_length=1, max_length=MAX_TICK)]
    model_labels: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    platform: PlatformTag

    @model_validator(mode="after")
    def _consistent(self) -> "RunStarted":
        if self.timestep_s != self.platform.compute.timestep_s:
            raise ValueError("timestep_s differs from platform.compute.timestep_s: one run has one time step")
        ids = [b.id for b in self.bodies]
        if len(set(ids)) != len(ids):
            raise ValueError("body ids must be unique")
        instances = [i for b in self.bodies for i in b.instances]
        if len(set(instances)) != len(instances):
            raise ValueError("an instance belongs to one body")
        return self


# --- frame ----------------------------------------------------------------------------------------------------


class BodyPose(_Obj):
    """Position [m] and orientation (unit quaternion `x, y, z, w`) of body `body`, in the world frame."""

    body: _Id
    position: WorldPosition
    orientation: Quaternion


class ForceN(_Obj):
    """A force in newtons (`unit` is always `N`, so a client never guesses)."""

    value: _NonNegative
    unit: Literal[Unit.N]


class LengthM(_Obj):
    """A signed length in metres (a support margin is negative outside the support region)."""

    value: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: Literal[Unit.M]


class TorqueNm(_Obj):
    """A non-negative torque magnitude in newton-metres."""

    value: _NonNegative
    unit: Literal[Unit.N_M]


class MassKg(_Obj):
    """A non-negative mass in kilograms."""

    value: _NonNegative
    unit: Literal[Unit.KG]


class OverturnEvent(_Obj):
    """Observed centre-of-mass projection outside the support polygon. This is not automatically a failure cause:
    `grounded` is false after liftoff (the polygon is the last ground support), and J-06 excludes that observation."""

    kind: Literal["overturn"]
    tick: _Tick
    grounded: bool
    margin: LengthM
    reference_length: LengthM


class TorqueShortageEvent(_Obj):
    """Observed motor command's zero-speed torque request over the speed- and supply-dependent available torque."""

    kind: Literal["torque_shortage"]
    tick: _Tick
    actuator: _Id
    required: TorqueNm
    limit: TorqueNm


class PropellantDepletedEvent(_Obj):
    """Observed empty tank. `unmet` distinguishes an unfulfilled thrust request from a scheduled burn that ended
    exactly as the tank became empty; only the former can become a J-06 cause."""

    kind: Literal["propellant_depleted"]
    tick: _Tick
    actuator: _Id
    tank: _Id
    requested: ForceN
    available: ForceN
    remaining: MassKg
    unmet: bool


class BodyTarget(_Obj):
    """What a body touched: another body of the run."""

    kind: Literal["body"]
    id: _Id


class PropTarget(_Obj):
    """What a body touched: a terrain prop, by its id in the project's world."""

    kind: Literal["prop"]
    id: _Id


class GroundTarget(_Strict):
    """What a body touched: the ground. It has no id (the ground of the planet is one thing), so an `id` is refused."""

    kind: Literal["ground"]


ContactTarget = Annotated[Union[BodyTarget, PropTarget, GroundTarget], Field(discriminator="kind")]
"""The other side of a contact. A body or a prop requires an `id`; the ground has none."""


class SlipEvent(_Obj):
    """Observed nonzero tangential contact force at or over its Coulomb friction limit, aggregated per body/target pair."""

    kind: Literal["slip"]
    tick: _Tick
    body: _Id
    other: ContactTarget
    tangential: ForceN
    friction_limit: ForceN


class ContactEvent(_Obj):
    """`body` touches (`phase` `begin`) or stops touching (`end`) `other`. `force` is the contact force at `begin`,
    if known."""

    kind: Literal["contact"]
    tick: _Tick
    phase: Literal["begin", "end"]
    body: _Id
    other: ContactTarget
    force: ForceN | None = None


class ImpulseNs(_Obj):
    """An impulse in newton-seconds (`unit` is always `N*s`)."""

    value: _NonNegative
    unit: Literal[Unit.N_S]


class BreakEvent(_Obj):
    """Joint `joint` released because the load on it went over its break threshold (both in N; plan 4.6, a simplified
    model). `reason` is the release's cause, `over_threshold` ("임계 초과"): only this one is a break (X-08)."""

    kind: Literal["break"]
    tick: _Tick
    reason: Literal["over_threshold"]
    joint: _Id
    load: ForceN
    threshold: ForceN


class SeparationEvent(_Obj):
    """Separator instance `separator` let go of joint `joint` on purpose (X-08): `reason` is `intended_separation` ("의도한
    분리"), never a break. Each side received the declared separation `impulse`, equal and opposite. `entry` is the schedule
    entry that asked for it, `null` for a manual request during the run. `tick` is the first tick whose state is apart."""

    kind: Literal["separation"]
    tick: _Tick
    reason: Literal["intended_separation"]
    separator: _Id
    joint: _Id
    entry: _Id | None
    impulse: ImpulseNs


class ConditionMetEvent(_Obj):
    """A success condition of the project became true. This is not a verdict (P4): it says the run satisfied it."""

    kind: Literal["condition_met"]
    tick: _Tick
    condition: _Id


FrameEvent = Annotated[
    Union[
        ContactEvent,
        BreakEvent,
        SeparationEvent,
        ConditionMetEvent,
        OverturnEvent,
        SlipEvent,
        TorqueShortageEvent,
        PropellantDepletedEvent,
    ],
    Field(discriminator="kind"),
]
"""Anything observed during a run. A joint released during the run is a `break` (reason `over_threshold`) or a
`separation` (reason `intended_separation`), never both. Threshold observations are not failure causes by themselves:
J-06 filters them by goal status, failure tick, ground contact and unmet thrust demand."""

_EVENTS = TypeAdapter(tuple[FrameEvent, ...])


class Frame(_Obj):
    """The state of run `run_id` at `tick` (`sim_time_s` seconds): every body's pose, and the events since the
    previous frame."""

    type: Literal["frame"]
    run_id: _RunId
    tick: _Tick
    sim_time_s: _NonNegative
    poses: Annotated[tuple[BodyPose, ...], Field(max_length=MAX_TICK)]
    events: tuple[FrameEvent, ...] = ()

    @model_validator(mode="after")
    def _checked(self) -> "Frame":
        ids = [p.body for p in self.poses]
        if len(set(ids)) != len(ids):
            raise ValueError("a body has one pose per frame")
        late = [e for e in self.events if e.tick > self.tick]
        if late:
            raise ValueError(f"an event lies after its frame's tick {self.tick}: {late[0].kind} at {late[0].tick}")
        return self


def check_frame(run: RunStarted, frame: Frame, *, final: bool = False) -> None:
    """Raise `ValueError` unless `frame` is a full frame of `run`: the run's id, exactly the run's bodies, the events
    only name the run's bodies, `sim_time_s == tick * timestep_s` (within float64 rounding), and the tick is a multiple
    of `frame_every_ticks` unless it is the `final` frame (the end tick, which may lie between two intervals). A client
    or a test that holds both messages can call this; `Frame` alone cannot know."""
    if frame.run_id != run.run_id:
        raise ValueError(f"frame of run {frame.run_id!r}, the run is {run.run_id!r}")
    ids = {b.id for b in run.bodies}
    if {p.body for p in frame.poses} != ids:
        raise ValueError("a frame carries exactly the bodies of its run (S1: full frames)")
    if not final and frame.tick % run.frame_every_ticks:
        raise ValueError(f"tick {frame.tick} is not a multiple of frame_every_ticks {run.frame_every_ticks}")
    if not math.isclose(frame.sim_time_s, frame.tick * run.timestep_s, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(f"sim_time_s {frame.sim_time_s} is not tick {frame.tick} x timestep_s {run.timestep_s}")
    for e in frame.events:
        named = [e.body] if isinstance(e, (ContactEvent, SlipEvent)) else []
        if isinstance(e, (ContactEvent, SlipEvent)) and isinstance(e.other, BodyTarget):
            named.append(e.other.id)
        unknown = [b for b in named if b not in ids]
        if unknown:
            raise ValueError(f"an event names a body that is not in the run: {unknown}")


# --- run_ended ------------------------------------------------------------------------------------------------


class TrajectoryEvidence(_Obj):
    """A trajectory hash and the platform tag it belongs to. A hash without its tag is not evidence (H1), so the two
    are one object. Two of these are compared only when their tags are equal (H2)."""

    hash: _Hash
    platform: PlatformTag


class RunCompleted(_Obj):
    """The planned duration was reached. The trajectory hash and its tag are required."""

    reason: Literal["completed"]
    trajectory: TrajectoryEvidence


class RunStopped(_Obj):
    """A stop was requested and the run ended at `last_tick`. The trajectory up to there has a hash, with its tag."""

    reason: Literal["stopped"]
    trajectory: TrajectoryEvidence


class RunFailed(_Strict):
    """The engine could not go on: there is no trajectory to hash, so a `trajectory` is refused."""

    reason: Literal["failed"]


RunEnd = Annotated[Union[RunCompleted, RunStopped, RunFailed], Field(discriminator="reason")]
"""How a run ended. Only a failed run lacks a trajectory: the JSON Schema requires one for the other two."""


class RunEnded(_Obj):
    """The run is over. `last_tick` is the tick of the run's last `frame`: the core always sends a frame at the end
    tick before `run_ended`, even when the end falls between two frame intervals, so the final poses and every event
    after the previous frame reach the client (`check_run`). `end` says how the run ended and carries the trajectory
    evidence."""

    type: Literal["run_ended"]
    run_id: _RunId
    last_tick: _Tick
    end: RunEnd


def check_run(run: RunStarted, frames: Sequence[Frame], ended: RunEnded) -> None:
    """Raise `ValueError` unless `frames` and `ended` are a whole stream of `run` (a recording, or what a client got):
    at least one frame; ticks strictly increasing; every frame a full frame of the run (`check_frame`), on the
    `frame_every_ticks` grid except the last; every event in the first frame after it (`previous.tick < event.tick`);
    the last frame at `ended.last_tick`; the trajectory evidence under the run's platform tag. Frames between may be
    missing (a sender that skips a frame moves its events to the next one); the last one may not."""
    if ended.run_id != run.run_id:
        raise ValueError(f"run_ended of run {ended.run_id!r}, the run is {run.run_id!r}")
    if not frames:
        raise ValueError("a run sends at least one frame: the one at its end tick")
    previous = -1
    for i, frame in enumerate(frames):
        check_frame(run, frame, final=i == len(frames) - 1)
        if frame.tick <= previous:
            raise ValueError(f"frame ticks must increase: {frame.tick} after {previous}")
        early = [e for e in frame.events if e.tick <= previous]
        if early:
            raise ValueError(f"an event of tick {early[0].tick} belongs to an earlier frame than tick {frame.tick}")
        previous = frame.tick
    if ended.last_tick != frames[-1].tick:
        raise ValueError(f"last_tick {ended.last_tick} is not the tick of the last frame ({frames[-1].tick})")
    trajectory = getattr(ended.end, "trajectory", None)
    if trajectory is not None and trajectory.platform != run.platform:
        raise ValueError("the trajectory hash is under another platform tag than the run's")


# --- binary frame ---------------------------------------------------------------------------------------------

BINARY_FRAME_VERSION = 1
BINARY_HEADER_BYTES = 24
BINARY_BODY_BYTES = 28
"""Binary frame, little-endian. One WebSocket binary message:

    offset  0  u8   version (1)         offset 12  u32  event_bytes (length of the JSON text after the poses)
    offset  1  u8*3 zero                offset 16  f64  sim_time_s
    offset  4  u32  tick                offset 24  n x (x y z qx qy qz qw) float32, bodies in `RunStarted.bodies` order
    offset  8  u32  body_count n        then       event_bytes bytes: UTF-8 JSON array of events (`[]` when none)

Size: `24 + 28 n + event_bytes`. The pose block starts at a multiple of 4, so a JavaScript `Float32Array` can view it
without a copy. Floats are float32 (about 7 digits: 6e-5 m at 1,000 m): a display value, not the trajectory the core
hashes. The frame belongs to the latest `run_started` of the connection (S1 has one live run at a time); the message
carries no run id.
"""

_HEADER = struct.Struct("<B3xIIId")
assert _HEADER.size == BINARY_HEADER_BYTES


class FrameDecodeError(ValueError):
    """A binary frame is not a frame of this run."""


def binary_frame_size(body_count: int, event_bytes: int = 2) -> int:
    """Bytes of a binary frame with `body_count` bodies and an event text of `event_bytes` (`[]` is 2)."""
    return BINARY_HEADER_BYTES + BINARY_BODY_BYTES * body_count + event_bytes


def encode_frame(frame: Frame, bodies: Sequence[str]) -> bytes:
    """The binary form of `frame`. `bodies` is `[b.id for b in run_started.bodies]`; the frame must carry exactly those
    bodies (a full frame, S1), in any order (they are written in `bodies` order)."""
    by_id = {p.body: p for p in frame.poses}
    if set(by_id) != set(bodies) or len(frame.poses) != len(bodies):
        raise ValueError("a binary frame carries exactly the bodies of its run, each once")
    events = _EVENTS.dump_json(frame.events)
    parts = [_HEADER.pack(BINARY_FRAME_VERSION, frame.tick, len(bodies), len(events), frame.sim_time_s)]
    try:
        for b in bodies:
            p = by_id[b]
            o, q = p.position, p.orientation
            parts.append(struct.pack("<7f", o.x, o.y, o.z, q.x, q.y, q.z, q.w))
    except OverflowError as e:
        raise ValueError(f"a pose does not fit a float32: {e}") from None
    parts.append(events)
    return b"".join(parts)


def decode_frame(data: bytes | bytearray | memoryview, run_id: str, bodies: Sequence[str]) -> Frame:
    """The `Frame` of a binary message of run `run_id` whose `RunStarted.bodies` ids are `bodies`. Raises
    `FrameDecodeError` for a message that is not exactly such a frame (wrong version, length or body count, a non-finite
    number, a quaternion that is not a unit quaternion, events that are not events)."""
    data = bytes(data)
    if len(data) < BINARY_HEADER_BYTES:
        raise FrameDecodeError(f"{len(data)} bytes are shorter than the {BINARY_HEADER_BYTES}-byte header")
    version, tick, n, event_bytes, sim_time = _HEADER.unpack_from(data)
    if version != BINARY_FRAME_VERSION:
        raise FrameDecodeError(f"binary frame version {version}, this code reads {BINARY_FRAME_VERSION}")
    if data[1:4] != b"\0\0\0":
        raise FrameDecodeError("reserved header bytes are not zero")
    if n != len(bodies):
        raise FrameDecodeError(f"the frame has {n} bodies, the run has {len(bodies)}")
    if len(data) != binary_frame_size(n, event_bytes):
        raise FrameDecodeError(f"{len(data)} bytes, the header says {binary_frame_size(n, event_bytes)}")
    poses = []
    for i, body in enumerate(bodies):
        x, y, z, qx, qy, qz, qw = struct.unpack_from("<7f", data, BINARY_HEADER_BYTES + BINARY_BODY_BYTES * i)
        if not all(math.isfinite(v) for v in (x, y, z, qx, qy, qz, qw)):
            raise FrameDecodeError(f"body {body!r} has a non-finite pose")
        poses.append({"body": body, "position": {"x": x, "y": y, "z": z}, "orientation": {"x": qx, "y": qy, "z": qz, "w": qw}})
    text = data[BINARY_HEADER_BYTES + BINARY_BODY_BYTES * n :]
    try:
        events = json.loads(text.decode("utf-8"))
        return Frame.model_validate(
            {"type": "frame", "run_id": run_id, "tick": tick, "sim_time_s": sim_time, "poses": poses, "events": events}
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as e:
        raise FrameDecodeError(str(e)) from None
