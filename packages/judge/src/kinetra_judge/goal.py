"""Success conditions evaluated on a run's trajectory (J-02a; `docs/architecture/goal-eval.md`).

    Goal.model_validate(json) -> Goal                               # the conditions of "it works", all of which must hold
    evaluate_goal(goal, started, frames, ended) -> GoalResult       # met | failed | undetermined, per condition and overall

A trajectory is one whole run stream of the core (`RunStarted`, its `Frame`s, `RunEnded`; C-05b, X-02a), checked by
`check_run` before anything is read. Five condition kinds, each about an instance of the project (the body that holds
it is followed, so a part that broke off is evaluated on its own trajectory):

| kind | met when | decided failed when |
|---|---|---|
| `reach` | the body's origin is in the box at a frame | the run completed without that |
| `rotation` | the summed rotation about a body axis reaches the angle at a frame | the run completed without that |
| `landing` | at the first touchdown the tilt and the speed are within their limits | at the first touchdown either is over its limit; or the run completed with contacts but no touchdown |
| `time_limit` | every `reach`, `rotation`, `landing` is met at or before `seconds` | one of them is not met by `seconds` (decided at that tick, or at the end of a shorter run) |
| `no_break` | the run completed without a `break` event (of the listed joints) | a `break` event (the first one's tick) |

`undetermined` is said, never guessed: when the run stopped or failed before a condition was decided, when a landing
needs a velocity from fewer than two frames, and when a landing is asked of a stream that has no contact event at all
(the stream cannot tell "never touched" from "touches were not reported"). A goal is `met` only when every condition is;
it is `failed` as soon as one condition is, at the earliest tick a condition was decided failed (J-06 classifies causes
at or before that tick); else `undetermined`.

This is the evaluation of one run, not a verdict (V1, P4): a verdict is the Monte Carlo of J-01 over many runs.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Union

from kinetra_core import BreakEvent, ContactEvent, Frame, RunEnded, RunStarted, check_run
from kinetra_core.conventions import ID_PATTERN
from pydantic import BaseModel, ConfigDict, Field, model_validator

_Id = Annotated[str, Field(pattern=ID_PATTERN)]
_Finite = Annotated[float, Field(strict=False, allow_inf_nan=False)]
_Positive = Annotated[float, Field(allow_inf_nan=False, gt=0)]
_NonNegative = Annotated[float, Field(allow_inf_nan=False, ge=0)]

SAMPLING_LABEL = "근사: 조건은 프레임 간격(sample_interval_s)마다 표본화한 자세로 평가한다. 프레임 사이에 잠깐 일어난 일은 보지 못한다"
VELOCITY_LABEL = "근사: 착지 속도는 착지 시점까지의 프레임 위치(공중 구간의 마지막 세 프레임, 둘뿐이면 두 프레임)의 차분으로 추정한다"
ORIGIN_LABEL = "도달·착지 속도는 인스턴스가 속한 몸의 기준점(가장 작은 id 인스턴스의 원점) 위치로 본다"
NOT_VERDICT_LABEL = "1회 실행의 조건 평가이며 판정이 아닙니다"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Point(_Strict):
    """A position in metres, world frame (+Z up)."""

    x: _Finite
    y: _Finite
    z: _Finite


class Box(_Strict):
    """An axis-aligned box in the world frame [m]: `min` and `max` are opposite corners."""

    min: Point
    max: Point

    @model_validator(mode="after")
    def _ordered(self) -> "Box":
        if not (self.min.x <= self.max.x and self.min.y <= self.max.y and self.min.z <= self.max.z):
            raise ValueError("box: every component of min must be at most the same component of max")
        return self

    def contains(self, x: float, y: float, z: float) -> bool:
        return self.min.x <= x <= self.max.x and self.min.y <= y <= self.max.y and self.min.z <= z <= self.max.z


class ReachCondition(_Strict):
    """The body of `instance` reaches `region` (its origin is inside the box at some frame)."""

    kind: Literal["reach"]
    id: _Id
    instance: _Id
    region: Box


class RotationCondition(_Strict):
    """The body of `instance` turns at least `angle_deg` about its own `axis` (body frame), counted from the run start:
    the sum of the frame-to-frame rotations about that axis, so turning back counts negative and its magnitude is
    compared."""

    kind: Literal["rotation"]
    id: _Id
    instance: _Id
    axis: Literal["x", "y", "z"]
    angle_deg: _Positive


class LandingCondition(_Strict):
    """At the first touchdown, the body of `instance` is tilted at most `max_tilt_deg` from the attitude it had at tick 0
    (the angle between the body's up direction then and now) and moves at most `max_speed_m_s`.

    A touchdown is a ground contact `begin` of a body of the `touch` instances (empty: every body of the run) at a tick
    when none of those bodies touched the ground: what began before is resting, not landing."""

    kind: Literal["landing"]
    id: _Id
    instance: _Id
    max_tilt_deg: _NonNegative
    max_speed_m_s: _NonNegative
    touch: tuple[_Id, ...] = ()


class TimeLimitCondition(_Strict):
    """Every `reach`, `rotation` and `landing` condition of the goal is met at or before `seconds` of simulated time."""

    kind: Literal["time_limit"]
    id: _Id
    seconds: _Positive


class NoBreakCondition(_Strict):
    """No joint of `joints` (empty: any joint) breaks during the run. A break is a `break` event (load over its
    threshold, X-04b); an intended separation (X-08) is not a break."""

    kind: Literal["no_break"]
    id: _Id
    joints: tuple[_Id, ...] = ()


Condition = Annotated[
    Union[ReachCondition, RotationCondition, LandingCondition, TimeLimitCondition, NoBreakCondition],
    Field(discriminator="kind"),
]

_ACHIEVEMENTS = ("reach", "rotation", "landing")


class Goal(_Strict):
    """The success conditions of a project: the run succeeds when all of them hold."""

    conditions: Annotated[tuple[Condition, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistent(self) -> "Goal":
        ids = [c.id for c in self.conditions]
        if len(set(ids)) != len(ids):
            raise ValueError("condition ids must be unique")
        kinds = {c.kind for c in self.conditions}
        if "time_limit" in kinds and not kinds.intersection(_ACHIEVEMENTS):
            raise ValueError("a time_limit needs a reach, rotation or landing condition to limit")
        return self


class Status(StrEnum):
    MET = "met"
    FAILED = "failed"
    UNDETERMINED = "undetermined"

    @property
    def label_ko(self) -> str:
        return _STATUS_KO[self]


_STATUS_KO = {Status.MET: "충족", Status.FAILED: "실패", Status.UNDETERMINED: "판단 불가"}


class ConditionResult(_Strict):
    """One condition on one run. `tick` is when it was decided (met or failed; `None` when undetermined), `measured`
    the values it was decided on (key names end in their unit), `reason` one Korean sentence."""

    id: _Id
    kind: str
    status: Status
    tick: int | None
    time_s: float | None
    measured: dict[str, float]
    reason: str


class GoalResult(_Strict):
    """A goal on one run. `tick` is the earliest tick a condition was decided failed (`failed`), the tick the last
    condition was met (`met`), or `None` (`undetermined`). Every value is read from the run's stream (badge `sim`);
    `labels` are the approximations of the evaluation."""

    run_id: str
    badge: Literal["sim"]
    status: Status
    tick: int | None
    time_s: float | None
    sample_interval_s: float
    conditions: tuple[ConditionResult, ...]
    labels: tuple[str, ...]


# --- quaternions (x, y, z, w; Hamilton product) ----------------------------------------------------------------

_Q = tuple[float, float, float, float]


def _q(o) -> _Q:
    return (o.x, o.y, o.z, o.w)


def _mul(a: _Q, b: _Q) -> _Q:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _conj(q: _Q) -> _Q:
    return (-q[0], -q[1], -q[2], q[3])


def _rotate(q: _Q, v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z, _ = _mul(_mul(q, (v[0], v[1], v[2], 0.0)), _conj(q))
    return (x, y, z)


def _rotvec(q: _Q) -> tuple[float, float, float]:
    """The rotation vector (axis times angle in rad, angle in [0, pi]) of unit quaternion `q`."""
    x, y, z, w = q if q[3] >= 0 else (-q[0], -q[1], -q[2], -q[3])
    s = math.sqrt(x * x + y * y + z * z)
    if s == 0.0:
        return (0.0, 0.0, 0.0)
    angle = 2.0 * math.atan2(s, w)
    return (x / s * angle, y / s * angle, z / s * angle)


def _angle_between(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    cx, cy, cz = a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]
    return math.atan2(math.sqrt(cx * cx + cy * cy + cz * cz), a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


# --- evaluation -------------------------------------------------------------------------------------------------


class _Run:
    """The stream read once: each body's samples, contact and break events in tick order."""

    def __init__(self, started: RunStarted, frames: Sequence[Frame], ended: RunEnded):
        check_run(started, frames, ended)
        self.started, self.frames, self.ended = started, frames, ended
        self.dt = started.timestep_s
        self.body_of = {i: b.id for b in started.bodies for i in b.instances}
        self.last_tick = ended.last_tick
        self.completed = ended.end.reason == "completed"
        events = [e for f in frames for e in f.events]
        self.contacts = sorted((e for e in events if isinstance(e, ContactEvent)), key=lambda e: e.tick)
        self.breaks = sorted((e for e in events if isinstance(e, BreakEvent)), key=lambda e: e.tick)

    def body(self, instance: str) -> str:
        try:
            return self.body_of[instance]
        except KeyError:
            raise ValueError(f"a condition names instance {instance!r}, which is not in the run's bodies") from None

    def poses(self, body: str) -> list[tuple[int, object]]:
        return [(f.tick, next(p for p in f.poses if p.body == body)) for f in self.frames]


def _result(c, status: Status, tick: int | None, run: _Run, measured: dict[str, float], reason: str) -> ConditionResult:
    return ConditionResult(
        id=c.id,
        kind=c.kind,
        status=status,
        tick=tick,
        time_s=None if tick is None else tick * run.dt,
        measured=measured,
        reason=reason,
    )


def _unfinished(c, run: _Run, measured: dict[str, float], failed_reason: str) -> ConditionResult:
    """A condition still open at the last frame: failed when the run completed, else undetermined."""
    if run.completed:
        return _result(c, Status.FAILED, run.last_tick, run, measured, failed_reason)
    return _result(c, Status.UNDETERMINED, None, run, measured, f"실행이 끝까지 가지 못했다({run.ended.end.reason}): {failed_reason}")


def _reach(c: ReachCondition, run: _Run) -> ConditionResult:
    for tick, pose in run.poses(run.body(c.instance)):
        p = pose.position
        if c.region.contains(p.x, p.y, p.z):
            return _result(c, Status.MET, tick, run, {"x_m": p.x, "y_m": p.y, "z_m": p.z}, "목표 영역에 도달했다")
    return _unfinished(c, run, {}, "목표 영역에 도달하지 않았다")


def _rotation(c: RotationCondition, run: _Run) -> ConditionResult:
    k = "xyz".index(c.axis)
    target = math.radians(c.angle_deg)
    total, previous = 0.0, None
    for tick, pose in run.poses(run.body(c.instance)):
        q = _q(pose.orientation)
        if previous is not None:
            total += _rotvec(_mul(_conj(previous), q))[k]
            if abs(total) >= target:
                return _result(c, Status.MET, tick, run, {"rotation_deg": math.degrees(total)}, f"몸 {c.axis}축으로 목표 각도만큼 돌았다")
        previous = q
    return _unfinished(c, run, {"rotation_deg": math.degrees(total)}, f"몸 {c.axis}축 회전이 목표 각도에 못 미쳤다")


def _touchdown(c: LandingCondition, run: _Run) -> tuple[int, int] | None:
    """(airborne since, touchdown tick) of the first touchdown, or None."""
    bodies = {run.body(i) for i in c.touch} if c.touch else {b.id for b in run.started.bodies}
    touching: set[str] = set()
    airborne_since = 0
    for e in run.contacts:
        if e.body not in bodies or e.other.kind != "ground":
            continue
        if e.phase == "begin":
            if not touching and e.tick > 0:
                return airborne_since, e.tick
            touching.add(e.body)
        else:
            touching.discard(e.body)
            if not touching:
                airborne_since = e.tick
    return None


def _velocity(samples: list[tuple[int, object]], tick: int, dt: float) -> tuple[float, float, float] | None:
    """Velocity [m/s] at `tick` from the last three samples (the derivative of the quadratic through them, exact for
    constant acceleration), or the last two (their difference), or None."""
    if len(samples) < 2:
        return None
    pts = samples[-3:]
    t = [s[0] * dt for s in pts]
    t_c = tick * dt
    out = []
    for axis in ("x", "y", "z"):
        v = [getattr(s[1].position, axis) for s in pts]
        if len(pts) == 2:
            out.append((v[1] - v[0]) / (t[1] - t[0]))
            continue
        # derivative at t_c of the Lagrange polynomial through (t[i], v[i])
        d = 0.0
        for i in range(3):
            j, m = [n for n in range(3) if n != i]
            d += v[i] * ((t_c - t[j]) + (t_c - t[m])) / ((t[i] - t[j]) * (t[i] - t[m]))
        out.append(d)
    return (out[0], out[1], out[2])


def _landing(c: LandingCondition, run: _Run) -> ConditionResult:
    body = run.body(c.instance)
    found = _touchdown(c, run)
    if found is None:
        if not run.contacts:
            return _result(c, Status.UNDETERMINED, None, run, {}, "궤적에 접촉 이벤트가 하나도 없어 착지를 가릴 수 없다")
        return _unfinished(c, run, {}, "착지(공중에서 지면 접촉 시작)가 없었다")
    since, tick = found
    poses = run.poses(body)
    q0 = _q(poses[0][1].orientation)
    up_body = _rotate(_conj(q0), (0.0, 0.0, 1.0))  # the body-frame direction that pointed up at tick 0
    flight = [(t, p) for t, p in poses if since <= t <= tick]
    attitude = [(t, p) for t, p in poses if t <= tick][-1][1]
    tilt = math.degrees(_angle_between(_rotate(_q(attitude.orientation), up_body), (0.0, 0.0, 1.0)))
    v = _velocity(flight, tick, run.dt)
    if v is None:
        if tilt > c.max_tilt_deg:  # decided by the attitude alone: a known failure is not undetermined
            return _result(c, Status.FAILED, tick, run, {"tilt_deg": tilt}, "첫 착지에서 기울기가 한도를 넘었다(속도는 공중 프레임이 둘보다 적어 내지 못했다)")
        return _result(c, Status.UNDETERMINED, None, run, {"tilt_deg": tilt}, "착지 전 공중 구간의 프레임이 둘보다 적어 속도를 낼 수 없다")
    speed = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    measured = {"tilt_deg": tilt, "speed_m_s": speed, "vertical_speed_m_s": -v[2]}
    over = [s for s, bad in (("기울기", tilt > c.max_tilt_deg), ("속도", speed > c.max_speed_m_s)) if bad]
    if over:
        return _result(c, Status.FAILED, tick, run, measured, f"첫 착지에서 {'와 '.join(over)}가 한도를 넘었다")
    return _result(c, Status.MET, tick, run, measured, "첫 착지의 기울기와 속도가 한도 안이다")


def _no_break(c: NoBreakCondition, run: _Run) -> ConditionResult:
    for e in run.breaks:
        if not c.joints or e.joint in c.joints:
            return _result(c, Status.FAILED, e.tick, run, {"load_n": e.load.value, "threshold_n": e.threshold.value}, f"결합 {e.joint}이 파단됐다")
    if run.completed:
        return _result(c, Status.MET, run.last_tick, run, {}, "파단 없이 실행이 끝났다")
    return _result(c, Status.UNDETERMINED, None, run, {}, f"실행이 끝까지 가지 못했다({run.ended.end.reason}): 그때까지 파단은 없었다")


def _time_limit(c: TimeLimitCondition, run: _Run, others: list[ConditionResult]) -> ConditionResult:
    """Met when every achievement (`reach`, `rotation`, `landing`) is met at a tick whose time (`tick * timestep_s`)
    is at or before `seconds`; the limit tick is the last such tick, so a limit between two ticks admits only the earlier
    one. Failed as soon as one is known not to be: met after the limit, failed, or (`reach`, `rotation`) still open while
    the frames reached the limit; decided at the limit tick, or at the last tick of a run that ended before it. Else
    undetermined (a landing that could not be evaluated, or a run that stopped before the limit)."""
    limit_tick = math.floor(c.seconds / run.dt + 1e-9)
    achieved = [r for r in others if r.kind in _ACHIEVEMENTS]
    measured = {"limit_s": c.seconds}
    if all(r.status is Status.MET and r.tick <= limit_tick for r in achieved):
        last = max(r.tick for r in achieved)
        return _result(c, Status.MET, last, run, {**measured, "last_met_s": last * run.dt}, "한도 안에 모든 목표를 충족했다")
    late = [
        r.id
        for r in achieved
        if (r.status is Status.MET and r.tick > limit_tick)
        or r.status is Status.FAILED
        or (r.status is Status.UNDETERMINED and r.kind != "landing" and run.last_tick >= limit_tick)
    ]
    if late:
        return _result(c, Status.FAILED, min(limit_tick, run.last_tick), run, measured, f"한도 시각까지 충족되지 않았다: {', '.join(late)}")
    return _result(c, Status.UNDETERMINED, None, run, measured, "한도 안에 충족됐는지 가릴 수 없다")


_EVALUATE = {"reach": _reach, "rotation": _rotation, "landing": _landing, "no_break": _no_break}


def evaluate_goal(goal: Goal, started: RunStarted, frames: Sequence[Frame], ended: RunEnded) -> GoalResult:
    """Evaluate every condition of `goal` on one run stream. Raises `ValueError` when the stream is not a whole run
    (`check_run`) or a condition names an instance that is not in the run."""
    run = _Run(started, frames, ended)
    results: dict[str, ConditionResult] = {}
    for c in goal.conditions:
        if c.kind != "time_limit":
            results[c.id] = _EVALUATE[c.kind](c, run)
    others = list(results.values())
    for c in goal.conditions:
        if c.kind == "time_limit":
            results[c.id] = _time_limit(c, run, others)
    ordered = tuple(results[c.id] for c in goal.conditions)
    failed = [r.tick for r in ordered if r.status is Status.FAILED]
    if failed:
        status, tick = Status.FAILED, min(failed)
    elif any(r.status is Status.UNDETERMINED for r in ordered):
        status, tick = Status.UNDETERMINED, None
    else:
        status, tick = Status.MET, max(r.tick for r in ordered)
    labels = [NOT_VERDICT_LABEL, SAMPLING_LABEL, ORIGIN_LABEL]
    if any(c.kind == "landing" for c in goal.conditions):
        labels.append(VELOCITY_LABEL)
    return GoalResult(
        run_id=started.run_id,
        badge="sim",
        status=status,
        tick=tick,
        time_s=None if tick is None else tick * run.dt,
        sample_interval_s=started.frame_every_ticks * run.dt,
        conditions=ordered,
        labels=tuple(labels),
    )
