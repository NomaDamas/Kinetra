"""J-06 failure causes from actual engine telemetry, plus event/failure-time negatives.

Run: `uv run pytest packages/judge -q -k failure_cause`.
The six fixed-seed scenes use `PreviewRun`; the analytic J-02a trajectory supplies precise negative and hand-calculation
cases. No expected cause is handwritten into an engine scene: the classifier must read the emitted run events.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from kinetra_core import (
    BreakEvent,
    FrameEvent,
    OverturnEvent,
    Project,
    PropellantDepletedEvent,
    SeparationEvent,
    SlipEvent,
    TorqueShortageEvent,
)
from kinetra_engine.run import PreviewRun
from pydantic import TypeAdapter

from kinetra_judge import Goal, Status, classify_failure_causes, evaluate_goal
from test_goal_eval import GOAL, trajectory

ENGINE_TESTS = Path(__file__).resolve().parents[2] / "engine" / "tests"
if str(ENGINE_TESTS) not in sys.path:
    sys.path.insert(0, str(ENGINE_TESTS))

from test_actuator import SRC as MOTOR_SRC, motor_rig  # noqa: E402
from test_body_tree import box, instance, joint, part, project  # noqa: E402
from test_break_runtime import breakable_tower  # noqa: E402
from test_terrain_ramp import STEEL, on_ramp  # noqa: E402
from test_thrust import entry, rocket  # noqa: E402

SEED = 458
EVENT = TypeAdapter(FrameEvent)


def run(project: Project, seconds: float = 0.04):
    preview = PreviewRun(
        project,
        run_id="j06-fixed-seed",
        project_id="j06",
        revision=1,
        duration_s=seconds,
        seed=SEED,
        frame_every_ticks=1,
    )
    items = list(preview)
    return preview.started, items[:-1], items[-1]


def failed_rotation(instance_id: str) -> Goal:
    return Goal.model_validate(
        {"conditions": [{"kind": "rotation", "id": "impossible-turn", "instance": instance_id, "axis": "z", "angle_deg": 720.0}]}
    )


def events(frames, kind):
    return [e for frame in frames for e in frame.events if isinstance(e, kind)]


def overhang() -> Project:
    # X-03a's hand fixture: 4 kg base and 6 kg arm put the COM 0.08 m beyond the base edge.
    # Use the snap-enabled parts from the X-03a fixture so the fixed joint compiles.
    from test_tipover import snap

    parts = [
        part("base", [box("b", 0.2, 0.2, 0.1)], [snap("top", (0, 0, 0.05))]),
        part("arm", [box("a", 0.6, 0.1, 0.1)], [snap("s1", (-0.3, 0, -0.05))]),
    ]
    instances = [instance("base", "base", (0, 0, 0.05)), instance("arm", "arm", (0.3, 0, 0.15))]
    return project(parts, instances, [joint("weld", "fixed", ("base", "top"), ("arm", "s1"))])


def cube() -> Project:
    # A stationary supported cube with no actuator, tank or breakable joint: no supported cause.
    return project([part("cube", [box("c", 0.1, 0.1, 0.1)])], [instance("cube1", "cube", (0, 0, 0.05))])


def scheduled_motor() -> Project:
    data = motor_rig().model_dump(mode="json")
    data["design"]["schedule"] = {
        "entries": [
            {
                "type": "actuate",
                "id": "spin",
                "actuator": "drive",
                "start": 0.0,
                "end": 0.04,
                "command": 1.0,
                "badge": "declared",
                "source": MOTOR_SRC,
            }
        ]
    }
    return Project.model_validate(data)


def test_failure_cause_fixed_seed_overturn_scene():
    stream = run(overhang())
    report = classify_failure_causes(failed_rotation("base"), *stream)
    observed = events(stream[1], OverturnEvent)
    assert observed and any(e.grounded for e in observed)
    cause = next(c for c in report.causes if c.kind == "overturn")
    assert cause.measured.value < 0.0 and cause.threshold.value == 0.0
    assert cause.margin_ratio == pytest.approx(cause.measured.value / cause.details["reference_length_m"])
    assert cause.measured.badge == cause.threshold.badge == "sim"


def test_failure_cause_fixed_seed_slip_scene():
    theta = math.atan(0.23) + math.radians(5.0)
    stream = run(on_ramp("earth", theta, STEEL["id"]), 0.2)
    report = classify_failure_causes(failed_rotation("block1"), *stream)
    assert events(stream[1], SlipEvent)
    cause = next(c for c in report.causes if c.kind == "slip")
    assert cause.measured.value >= cause.threshold.value > 0.0
    assert cause.related == "ramp1"


def test_failure_cause_fixed_seed_torque_shortage_scene():
    stream = run(scheduled_motor())
    report = classify_failure_causes(failed_rotation("m1"), *stream)
    assert events(stream[1], TorqueShortageEvent)
    cause = next(c for c in report.causes if c.kind == "torque_shortage")
    assert cause.subject == "drive" and cause.measured.value > cause.threshold.value
    assert cause.measured.unit.value == cause.threshold.unit.value == "N*m"


def test_failure_cause_fixed_seed_propellant_depletion_scene():
    stream = run(rocket([entry("burn", "main", 0.0, 0.04, 1.0)], tank_params=(("initial_fill", 1e-6, "1"),)))
    report = classify_failure_causes(failed_rotation("tank"), *stream)
    observed = [e for e in events(stream[1], PropellantDepletedEvent) if e.unmet]
    assert observed
    cause = next(c for c in report.causes if c.kind == "propellant_depleted")
    assert cause.details["remaining_kg"] == 0.0 and cause.related == "tank"
    assert cause.measured.value > cause.threshold.value and cause.margin_ratio < 0.0


def test_failure_cause_fixed_seed_break_scene_uses_joint_not_part():
    stream = run(breakable_tower(1.0), 0.2)
    goal = Goal.model_validate({"conditions": [{"kind": "no_break", "id": "holds", "joints": ["weld"]}]})
    report = classify_failure_causes(goal, *stream)
    assert events(stream[1], BreakEvent)
    (cause,) = report.causes
    assert cause.kind == "break" and cause.subject == "weld"
    assert cause.tick == report.failure_tick and cause.measured.value > cause.threshold.value == 1.0


def test_failure_cause_fixed_seed_unclassified_scene_does_not_invent_a_cause():
    stream = run(cube())
    report = classify_failure_causes(failed_rotation("cube1"), *stream)
    assert report.goal_status is Status.FAILED and report.causes == () and report.unclassified


def add_events(stream, additions):
    started, frames, ended = stream
    by_tick = {}
    for item in additions:
        event = EVENT.validate_python(item)
        by_tick.setdefault(event.tick, []).append(event)
    changed = []
    previous = -1
    for frame in frames:
        extra = tuple(e for tick, items in by_tick.items() for e in items if previous < tick <= frame.tick)
        changed.append(frame.model_copy(update={"events": frame.events + extra}))
        previous = frame.tick
    return started, changed, ended


def observation(tick=100, *, grounded=False):
    return {"kind": "overturn", "tick": tick, "grounded": grounded, "margin": {"value": -0.1, "unit": "m"},
            "reference_length": {"value": 0.2, "unit": "m"}}


def burnout(tick=100, *, unmet=False):
    return {"kind": "propellant_depleted", "tick": tick, "actuator": "main", "tank": "tank",
            "requested": {"value": 8.0, "unit": "N"}, "available": {"value": 0.0 if unmet else 8.0, "unit": "N"},
            "remaining": {"value": 0.0, "unit": "kg"}, "unmet": unmet}


def slip(tick=100, measured=12.0, limit=10.0):
    return {"kind": "slip", "tick": tick, "body": "car", "other": {"kind": "ground"},
            "tangential": {"value": measured, "unit": "N"}, "friction_limit": {"value": limit, "unit": "N"}}


def test_failure_cause_success_has_zero_causes_despite_airborne_burnout_and_separation_events():
    stream = add_events(
        trajectory(vx=1.5, vz0=4.0, turns=1.0, separation_tick=300),
        [observation(100, grounded=False), burnout(200, unmet=False)],
    )
    assert evaluate_goal(Goal.model_validate(GOAL), *stream).status is Status.MET
    report = classify_failure_causes(Goal.model_validate(GOAL), *stream)
    assert report.causes == () and not report.unclassified and report.goal_status is Status.MET
    # Observations remain in the run record; filtering the report does not erase them.
    assert events(stream[1], OverturnEvent) and events(stream[1], PropellantDepletedEvent) and events(stream[1], SeparationEvent)


def test_failure_cause_actual_two_stage_separation_is_not_a_break():
    from test_separation import separate, stages

    stream = run(stages([separate("stage", "sep", 0.01)]), seconds=0.03)
    goal = Goal.model_validate({"conditions": [{"kind": "no_break", "id": "hold", "joints": ["mount"]}]})
    assert evaluate_goal(goal, *stream).status is Status.MET
    report = classify_failure_causes(goal, *stream)
    assert report.causes == () and not report.unclassified
    assert events(stream[1], SeparationEvent) and not events(stream[1], BreakEvent)


def test_failure_cause_failed_run_excludes_airborne_scheduled_burnout_and_late_break():
    stream = add_events(
        trajectory(vx=0.2, vz0=6.0, turns=0.75, break_tick=200),
        [
            observation(100, grounded=False),
            burnout(150, unmet=False),
            {"kind": "break", "tick": 300, "reason": "over_threshold", "joint": "axle",
             "load": {"value": 4.0, "unit": "N"}, "threshold": {"value": 2.0, "unit": "N"}},
        ],
    )
    report = classify_failure_causes(Goal.model_validate(GOAL), *stream)
    assert report.failure_tick == 200
    assert [(c.kind, c.subject, c.tick) for c in report.causes] == [("break", "mount", 200)]
    assert any(e.tick == 300 for e in events(stream[1], BreakEvent))  # observed, but after failure


def test_failure_cause_intended_two_stage_separation_is_never_break_and_later_other_joint_is():
    goal = Goal.model_validate(GOAL)
    success = classify_failure_causes(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0, separation_tick=100))
    assert success.causes == ()
    failed_stream = add_events(
        trajectory(vx=0.2, vz0=6.0, turns=0.75, break_tick=200),
        [{"kind": "separation", "tick": 100, "reason": "intended_separation", "separator": "stage-separator",
          "joint": "stage-joint", "entry": "stage", "impulse": {"value": 1.0, "unit": "N*s"}}],
    )
    failed = classify_failure_causes(goal, *failed_stream)
    assert [(c.kind, c.subject) for c in failed.causes] == [("break", "mount")]


def test_failure_cause_no_goal_and_undetermined_have_empty_causes():
    stream = add_events(trajectory(vx=1.5, vz0=4.0, turns=1.0), [observation(100, grounded=True), slip(150)])
    no_goal = classify_failure_causes(None, *stream)
    assert no_goal.goal_status is None and no_goal.causes == () and not no_goal.unclassified
    undetermined_stream = add_events(trajectory(vx=1.5, vz0=4.0, turns=1.0, contacts=False), [observation(100, grounded=True)])
    undetermined = classify_failure_causes(Goal.model_validate(GOAL), *undetermined_stream)
    assert undetermined.goal_status is Status.UNDETERMINED and undetermined.causes == () and not undetermined.unclassified


def test_failure_cause_two_margin_ratios_match_hand_calculation_and_causes_are_time_sorted():
    stream = add_events(
        trajectory(vx=0.2, vz0=6.0, turns=0.75, break_tick=200),
        [slip(100, measured=12.0, limit=10.0)],
    )
    report = classify_failure_causes(Goal.model_validate(GOAL), *stream)
    assert [(c.kind, c.tick) for c in report.causes] == [("slip", 100), ("break", 200)]
    # Hand 1: (10 N - 12 N) / |12 N| = -1/6. Hand 2: (1 N - 2 N) / |2 N| = -1/2.
    assert report.causes[0].margin_ratio == pytest.approx(-1.0 / 6.0)
    assert report.causes[1].margin_ratio == pytest.approx(-0.5)
    assert report.rule.endswith("인과를 증명한 것이 아니다") and not report.is_verdict
    assert all(c.measured.badge == c.threshold.badge == "sim" for c in report.causes)
