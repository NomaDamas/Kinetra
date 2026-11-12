"""J-06: classify observed run events for a failed goal, without claiming causation or a verdict.

    classify_failure_causes(goal, started, frames, ended) -> FailureCauseReport

`goal=None`, a met goal, and an undetermined goal all produce zero causes. For a failed goal, only observations at or
before J-02a's first failure tick are eligible. The run stream remains the source of observed events; this report contains
only the filtered causes. See `docs/architecture/failure-cause.md` for the five formulas and margin-ratio definitions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from kinetra_core import (
    BreakEvent,
    Frame,
    OverturnEvent,
    PropellantDepletedEvent,
    RunEnded,
    RunStarted,
    SlipEvent,
    TorqueShortageEvent,
    Unit,
    check_run,
)
from pydantic import BaseModel, ConfigDict, Field

from .goal import Goal, Status, evaluate_goal

CAUSE_RULE = "원인은 성공 조건이 실패로 확정된 시점 또는 그 이전에 임계를 넘은 관측 사건이며, 인과를 증명한 것이 아니다"
NOT_VERDICT = "1회 실행 기록의 실패 원인 분류이며 판정이 아닙니다"
OBSERVATION_DISTINCTION = "관측된 사건과 실패 원인은 다르다. 성공한 실행과 성공 조건이 없는 실행은 원인을 분류하지 않는다"

CRITERIA = {
    "overturn": "지면에 닿아 있는 동안 무게중심 투영의 지지 다각형 부호 거리 < 0 m",
    "slip": "접촉 쌍의 접선력 합 > 0이고 접선력 합 ≥ 마찰 한계(쿨롱 솔버의 미끄럼 포화)",
    "torque_shortage": "모터 명령의 영속도 요구 토크 > 현재 속도와 공급 상태에서 가능한 토크",
    "propellant_depleted": "추력 요구 중 탱크 잔량 0 kg이고 요구 추진제 공급 충족률 < 1",
    "break": "reason=over_threshold인 결합 해제 이벤트(결합 하중 > 결합 임계)",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class SimValue(_Strict):
    """One value computed from this run's engine telemetry; unit is explicit and provenance is always `sim`."""

    value: _Finite
    unit: Unit
    badge: Literal["sim"] = "sim"


class FailureCause(_Strict):
    """One eligible observation. `margin_ratio` is `(threshold - measured) / abs(measured)` except overturn, where it is
    signed support margin / `details['reference_length_m']`. Negative means outside the threshold."""

    kind: Literal["overturn", "slip", "torque_shortage", "propellant_depleted", "break"]
    tick: int = Field(ge=0)
    time_s: _Finite
    subject: str
    related: str | None = None
    measured: SimValue
    threshold: SimValue
    margin_ratio: _Finite
    criterion: str
    details: dict[str, _Finite] = Field(default_factory=dict)


class FailureCauseReport(_Strict):
    """J-06 output for one run. Empty causes are mandatory for no goal, met, and undetermined runs. `unclassified` is
    true only for a failed goal with no supported cause; it never invents one."""

    run_id: str
    badge: Literal["sim"] = "sim"
    is_verdict: Literal[False] = False
    goal_status: Status | None
    failure_tick: int | None = None
    failure_time_s: _Finite | None = None
    causes: tuple[FailureCause, ...] = ()
    unclassified: bool = False
    rule: str = CAUSE_RULE
    labels: tuple[str, ...] = (NOT_VERDICT, OBSERVATION_DISTINCTION)


def _value(value: float, unit: Unit) -> SimValue:
    return SimValue(value=float(value), unit=unit)


def _margin(measured: float, threshold: float) -> float:
    """Relative margin for the four demand/limit causes. Every eligible event has nonzero measured demand."""
    if measured == 0.0:
        raise ValueError("a demand/limit failure cause needs a nonzero measured demand")
    return (threshold - measured) / abs(measured)


def _cause(
    kind: str,
    tick: int,
    dt: float,
    subject: str,
    measured: SimValue,
    threshold: SimValue,
    *,
    related: str | None = None,
    details: dict[str, float] | None = None,
    margin_ratio: float | None = None,
) -> FailureCause:
    return FailureCause(
        kind=kind,
        tick=tick,
        time_s=tick * dt,
        subject=subject,
        related=related,
        measured=measured,
        threshold=threshold,
        margin_ratio=_margin(measured.value, threshold.value) if margin_ratio is None else margin_ratio,
        criterion=CRITERIA[kind],
        details={} if details is None else details,
    )


def _convert(event, dt: float) -> FailureCause | None:
    if isinstance(event, OverturnEvent):
        if not event.grounded:
            return None
        return _cause(
            "overturn",
            event.tick,
            dt,
            "assembly",
            _value(event.margin.value, Unit.M),
            _value(0.0, Unit.M),
            details={"reference_length_m": event.reference_length.value},
            margin_ratio=event.margin.value / event.reference_length.value,
        )
    if isinstance(event, SlipEvent):
        related = event.other.kind if event.other.kind == "ground" else event.other.id
        return _cause(
            "slip",
            event.tick,
            dt,
            event.body,
            _value(event.tangential.value, Unit.N),
            _value(event.friction_limit.value, Unit.N),
            related=related,
        )
    if isinstance(event, TorqueShortageEvent):
        return _cause(
            "torque_shortage",
            event.tick,
            dt,
            event.actuator,
            _value(event.required.value, Unit.N_M),
            _value(event.limit.value, Unit.N_M),
        )
    if isinstance(event, PropellantDepletedEvent):
        if not event.unmet:
            return None
        return _cause(
            "propellant_depleted",
            event.tick,
            dt,
            event.actuator,
            _value(event.requested.value, Unit.N),
            _value(event.available.value, Unit.N),
            related=event.tank,
            details={"remaining_kg": event.remaining.value},
        )
    if isinstance(event, BreakEvent) and event.reason == "over_threshold":
        return _cause(
            "break",
            event.tick,
            dt,
            event.joint,
            _value(event.load.value, Unit.N),
            _value(event.threshold.value, Unit.N),
        )
    return None


def classify_failure_causes(
    goal: Goal | None,
    started: RunStarted,
    frames: Sequence[Frame],
    ended: RunEnded,
) -> FailureCauseReport:
    """Classify one whole run stream. No goal, success, and undetermined are deliberately not classified."""
    check_run(started, frames, ended)
    if goal is None:
        return FailureCauseReport(run_id=started.run_id, goal_status=None)
    result = evaluate_goal(goal, started, frames, ended)
    if result.status is not Status.FAILED:
        return FailureCauseReport(run_id=started.run_id, goal_status=result.status)
    assert result.tick is not None  # J-02a: every failed overall goal has its earliest failed condition tick
    causes = []
    for frame in frames:
        for event in frame.events:
            if event.tick > result.tick:
                continue
            cause = _convert(event, started.timestep_s)
            if cause is not None:
                causes.append(cause)
    causes.sort(key=lambda c: (c.tick, c.kind, c.subject, c.related or ""))
    return FailureCauseReport(
        run_id=started.run_id,
        goal_status=result.status,
        failure_tick=result.tick,
        failure_time_s=result.time_s,
        causes=tuple(causes),
        unclassified=not causes,
    )
