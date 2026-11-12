"""J-02a: success conditions evaluated on a trajectory. `uv run pytest packages/judge -q -k goal_eval`.

The two trajectories of the DoD (one success, one failure) are analytic, written here so every expected value is a hand
calculation: a car (body `car`, with a wheel body `wheel-1` under it) rests on the ground at tick 0, leaves it at
launch speed (`vx`, `vz0`), flies a ballistic arc under Earth's gravity (9.80665 m/s^2, `data/bodies/earth.json`) while
turning about its body y axis at a constant rate, and touches down when its height is back at the start (the wheel's
ground contact `begin`), where it stays. Every threshold is a value chosen by the test, not a product number.

    success: vx 1.5, vz0 4 -> touchdown at tick ceil(2 * 4 / g / dt) = 408 (0.816 s), one full turn by then
    failure: vx 0.2, vz0 6 -> touchdown at tick ceil(2 * 6 / g / dt) = 612 (1.224 s), three quarters of a turn, and the
             joint `mount` breaks at tick 200

The last test runs the real engine (X-02a) and evaluates its stream.
"""

from __future__ import annotations

import math

import pytest
from kinetra_core import Frame, Project, RunEnded, RunStarted
from pydantic import ValidationError

from kinetra_judge import Goal, Status, evaluate_goal

G = 9.80665  # m/s^2, data/bodies/earth.json
DT = 0.002
EVERY = 4
LAST = 750
REST_Z = 0.25
WHEEL_DROP = 0.2
PLATFORM = {
    "os": {"kind": "macos", "kernel_release": "24.6.0"},
    "cpu": {"architecture": "arm64", "model": "test"},
    "image_digest": None,
    "engine": {"name": "analytic-fixture", "version": "0", "distribution": "custom_build", "compiler": "none (pure Python)", "build_flags": ""},
    "runtime": {"python": "3.12", "numpy": "2"},
    "core_build": {"commit": "0" * 40},
    "compute": {"integrator": "closed-form ballistic arc", "timestep_s": DT, "solver": {}},
    "threads": {"physics": 1, "solver": 1},
}

GOAL = {
    "conditions": [
        {"kind": "reach", "id": "over-the-line", "instance": "car", "region": {"min": {"x": 1.0, "y": -0.5, "z": 0.0}, "max": {"x": 1.5, "y": 0.5, "z": 1.0}}},
        {"kind": "rotation", "id": "one-turn", "instance": "thruster-1", "axis": "y", "angle_deg": 340.0},
        {"kind": "landing", "id": "lands-upright", "instance": "car", "max_tilt_deg": 10.0, "max_speed_m_s": 5.0},
        {"kind": "time_limit", "id": "within-1s", "seconds": 1.0},
        {"kind": "no_break", "id": "mount-holds", "joints": ["mount"]},
        {"kind": "no_break", "id": "axle-holds", "joints": ["axle"]},
    ]
}


def touchdown_tick(vz0: float) -> int:
    return math.ceil(2.0 * vz0 / G / DT)


def trajectory(vx: float, vz0: float, turns: float, break_tick: int | None = None, contacts: bool = True, last: int = LAST, reason: str = "completed", every: int = EVERY):
    """The run stream (`RunStarted`, frames, `RunEnded`) of the analytic jump described in the module docstring."""
    down = touchdown_tick(vz0)
    started = RunStarted.model_validate(
        {
            "type": "run_started", "run_id": "jump", "kind": "preview", "badge": "sim", "project_id": "jump", "revision": 0,
            "definition_hash": "sha256:" + "0" * 64, "planet": "earth", "seed": 0, "timestep_s": DT, "frame_every_ticks": every,
            "bodies": [{"id": "car", "instances": ["car", "thruster-1"]}, {"id": "wheel-1", "instances": ["wheel-1"]}],
            "platform": PLATFORM,
        }
    )
    events = []
    if contacts:
        events += [(0, "begin"), (1, "end"), (down, "begin")]
        events = [{"kind": "contact", "tick": t, "phase": p, "body": "wheel-1", "other": {"kind": "ground"}} for t, p in events]
    if break_tick is not None:
        events.append({"kind": "break", "tick": break_tick, "joint": "mount", "crossing_time_s": (break_tick - 0.5) * DT,
                       "load": {"value": 1.0, "unit": "N"}, "release_load": {"value": 2.0, "unit": "N"}, "threshold": {"value": 1.0, "unit": "N"}})
    ticks = [*range(0, last + 1, every), *([last] if last % every else [])]
    frames, previous = [], -1
    for tick in ticks:
        t = min(tick, down) * DT
        x, z = vx * t, REST_Z + vz0 * t - G * t * t / 2.0
        half = math.pi * turns * min(tick, down) / down  # half the angle turned about y
        q = {"x": 0.0, "y": math.sin(half), "z": 0.0, "w": math.cos(half)}
        frames.append(
            Frame.model_validate(
                {
                    "type": "frame", "run_id": "jump", "tick": tick, "sim_time_s": tick * DT,
                    "poses": [
                        {"body": "car", "position": {"x": x, "y": 0.0, "z": z}, "orientation": q},
                        {"body": "wheel-1", "position": {"x": x, "y": 0.0, "z": z - WHEEL_DROP}, "orientation": q},
                    ],
                    "events": [e for e in events if previous < e["tick"] <= tick],
                }
            )
        )
        previous = tick
    end = {"reason": reason}
    if reason != "failed":
        end["trajectory"] = {"hash": "sha256:" + "1" * 64, "platform": PLATFORM}
    ended = RunEnded.model_validate({"type": "run_ended", "run_id": "jump", "last_tick": last, "end": end})
    return started, frames, ended


def by_id(result):
    return {c.id: c for c in result.conditions}


def test_goal_eval_success_trajectory_meets_every_condition():
    goal = Goal.model_validate(GOAL)
    assert touchdown_tick(4.0) == 408  # 2 * 4 / 9.80665 / 0.002 = 407.9
    result = evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0))
    c = by_id(result)
    assert result.status is Status.MET and result.badge == "sim"
    # reach: x >= 1.0 from t = 1.0 / 1.5 = 0.667 s (tick 333.3); the first frame after is tick 336 (z = 0.25 + 4 * 0.672 - g * 0.672^2 / 2 = 0.73 m)
    assert (c["over-the-line"].status, c["over-the-line"].tick) == (Status.MET, 336)
    # rotation: 340 / 360 of the turn is at tick 408 * 340 / 360 = 385.3; the first frame after is tick 388 (342.4 deg)
    assert (c["one-turn"].status, c["one-turn"].tick) == (Status.MET, 388)
    assert c["one-turn"].measured["rotation_deg"] == pytest.approx(360.0 * 388 / 408, abs=1e-9)
    # landing at the wheel's ground contact (tick 408): a whole turn, so no tilt; vertical speed g * 0.816 - 4
    landing = c["lands-upright"]
    vz = G * 408 * DT - 4.0
    assert (landing.status, landing.tick) == (Status.MET, 408)
    assert landing.measured["tilt_deg"] == pytest.approx(0.0, abs=1e-9)
    assert landing.measured["vertical_speed_m_s"] == pytest.approx(vz, abs=1e-9)
    assert landing.measured["speed_m_s"] == pytest.approx(math.hypot(1.5, vz), abs=1e-9)  # 4.274 m/s <= 5
    assert (c["within-1s"].status, c["within-1s"].tick) == (Status.MET, 408)  # the last achievement, 0.816 s <= 1 s
    assert (c["mount-holds"].status, c["mount-holds"].tick) == (Status.MET, LAST)  # no break, decided at the end
    assert result.tick == LAST
    assert result.labels[0] == "1회 실행의 조건 평가이며 판정이 아닙니다"


def test_goal_eval_failure_trajectory_fails_each_condition_at_its_tick():
    goal = Goal.model_validate(GOAL)
    assert touchdown_tick(6.0) == 612  # 2 * 6 / 9.80665 / 0.002 = 611.8
    result = evaluate_goal(goal, *trajectory(vx=0.2, vz0=6.0, turns=0.75, break_tick=200))
    c = by_id(result)
    assert result.status is Status.FAILED
    assert result.tick == 200 and result.time_s == pytest.approx(0.4)  # the first condition decided failed: the break
    # reach: x stops at 0.2 * 1.224 = 0.245 m < 1.0, decided at the end of the completed run
    assert (c["over-the-line"].status, c["over-the-line"].tick) == (Status.FAILED, LAST)
    assert (c["one-turn"].status, c["one-turn"].tick) == (Status.FAILED, LAST)
    assert c["one-turn"].measured["rotation_deg"] == pytest.approx(270.0, abs=1e-9)
    # landing at tick 612: three quarters of a turn about y leave the body's up axis horizontal (90 deg)
    landing = c["lands-upright"]
    vz = G * 612 * DT - 6.0
    assert (landing.status, landing.tick) == (Status.FAILED, 612)
    assert landing.measured["tilt_deg"] == pytest.approx(90.0, abs=1e-9)
    assert landing.measured["speed_m_s"] == pytest.approx(math.hypot(0.2, vz), abs=1e-9)  # 6.0 m/s > 5
    assert "기울기" in landing.reason and "속도" in landing.reason
    assert (c["within-1s"].status, c["within-1s"].tick) == (Status.FAILED, 500)  # 1.0 s / 0.002 s
    assert (c["mount-holds"].status, c["mount-holds"].tick) == (Status.FAILED, 200)
    assert c["mount-holds"].measured == {"load_n": 1.0, "threshold_n": 1.0}
    assert (c["axle-holds"].status, c["axle-holds"].tick) == (Status.MET, LAST)  # another joint's break does not count


def test_goal_eval_says_undetermined_instead_of_guessing():
    goal = Goal.model_validate(GOAL)
    # no contact event in the whole stream: "never touched" and "touches not reported" look the same
    result = evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0, contacts=False))
    c = by_id(result)
    assert c["lands-upright"].status is Status.UNDETERMINED and c["lands-upright"].tick is None
    assert c["within-1s"].status is Status.UNDETERMINED
    assert result.status is Status.UNDETERMINED and result.tick is None
    # a run stopped at tick 300: what was not decided by then is undetermined, not failed
    result = evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0, last=300, reason="stopped"))
    c = by_id(result)
    assert {c[i].status for i in ("over-the-line", "one-turn", "lands-upright", "within-1s", "mount-holds")} == {Status.UNDETERMINED}
    assert result.status is Status.UNDETERMINED
    # a failed condition still fails the goal of a stopped run
    result = evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0, break_tick=100, last=300, reason="stopped"))
    assert (result.status, result.tick) == (Status.FAILED, 100)


def test_goal_eval_time_limit_between_two_ticks_admits_only_the_earlier_tick():
    # 0.815 s lies between tick 407 (0.814 s) and tick 408 (0.816 s), where the success trajectory lands
    goal = Goal.model_validate({"conditions": [*GOAL["conditions"][:3], {"kind": "time_limit", "id": "tight", "seconds": 0.815}]})
    result = evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0))
    c = by_id(result)
    assert (c["lands-upright"].status, c["lands-upright"].tick) == (Status.MET, 408)
    assert (c["tight"].status, c["tight"].tick) == (Status.FAILED, 407)
    assert (result.status, result.tick) == (Status.FAILED, 407)
    goal = Goal.model_validate({"conditions": [*GOAL["conditions"][:3], {"kind": "time_limit", "id": "loose", "seconds": 0.817}]})
    assert by_id(evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0)))["loose"].status is Status.MET  # 0.816 <= 0.817


def test_goal_eval_landing_tilt_over_its_limit_fails_even_without_a_speed():
    # frames every 400 ticks: the flight (ticks 1..408) holds one frame (400), too few for a speed
    goal = Goal.model_validate({"conditions": [GOAL["conditions"][2]]})
    landing = by_id(evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=0.75, every=400)))["lands-upright"]
    # attitude at frame 400: 0.75 * 360 * 400 / 408 = 264.7 deg about y, so the up axis is 360 - 264.7 = 95.3 deg off > 10
    assert (landing.status, landing.tick) == (Status.FAILED, 408)
    assert landing.measured == {"tilt_deg": pytest.approx(360.0 - 270.0 * 400 / 408, abs=1e-9)}
    # within its tilt limit (one turn: 360 * 8 / 408 = 7.06 deg short of upright <= 10), the speed decides: undetermined
    landing = by_id(evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0, every=400)))["lands-upright"]
    assert landing.status is Status.UNDETERMINED and landing.measured["tilt_deg"] == pytest.approx(360.0 * 8 / 408, abs=1e-9)


def test_goal_eval_refuses_bad_goals_and_unknown_instances():
    with pytest.raises(ValidationError, match="unique"):
        Goal.model_validate({"conditions": [{"kind": "no_break", "id": "a"}, {"kind": "no_break", "id": "a"}]})
    with pytest.raises(ValidationError, match="time_limit needs"):
        Goal.model_validate({"conditions": [{"kind": "time_limit", "id": "t", "seconds": 1.0}, {"kind": "no_break", "id": "a"}]})
    with pytest.raises(ValidationError, match="min must be at most"):
        Goal.model_validate({"conditions": [{"kind": "reach", "id": "r", "instance": "car", "region": {"min": {"x": 1, "y": 0, "z": 0}, "max": {"x": 0, "y": 1, "z": 1}}}]})
    with pytest.raises(ValidationError):
        Goal.model_validate({"conditions": [{"kind": "no_break", "id": "a", "verdict": "pass"}]})
    goal = Goal.model_validate({"conditions": [{"kind": "rotation", "id": "r", "instance": "ghost", "axis": "x", "angle_deg": 90}]})
    with pytest.raises(ValueError, match="ghost"):
        evaluate_goal(goal, *trajectory(vx=1.5, vz0=4.0, turns=1.0))


def test_goal_eval_on_a_real_engine_run():
    """A 0.1 m cube resting on the ground on Earth, run by the engine (X-02a) for 1 s: it stays in the box around its
    start, does not turn, and has no joint to break. (A start above the ground is refused by the compiler today.)"""
    from kinetra_engine.run import PreviewRun

    src = {"ref": "J-02a test fixture: value chosen by the test", "locator": "test_goal_eval.py"}

    def q(value, unit):
        return {"value": value, "unit": unit, "badge": "declared", "source": src}

    def ax(v):
        return {"offset": v, "terms": []}

    shape = {"badge": "declared", "source": src, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "box", "size_x": ax(0.1), "size_y": ax(0.1), "size_z": ax(0.1)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    material = {"id": "mat", "name": "Test material", "density": q(7850.0, "kg/m^3"), "yield_strength": q(2.5e8, "Pa"),
                "elastic_modulus": q(2.0e11, "Pa"), "friction": q(0.5, "1")}
    part = {"id": "cube", "name": "cube", "parameters": [], "snap_points": [], "shape": shape}
    inst = {"id": "cube1", "part": "cube", "material": "mat", "pose": {"badge": "declared", "source": src,
            "position": {"x": 0.0, "y": 0.0, "z": 0.05}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    project = Project.model_validate({"design": {"materials": [material], "parts": [part], "instances": [inst], "joints": []}, "world": {"planet": "earth"}})
    run = PreviewRun(project, run_id="drop", project_id="drop", revision=0, duration_s=1.0)
    stream = list(run)
    frames, ended = stream[:-1], stream[-1]
    goal = Goal.model_validate(
        {
            "conditions": [
                {"kind": "reach", "id": "down", "instance": "cube1", "region": {"min": {"x": -1, "y": -1, "z": 0.0}, "max": {"x": 1, "y": 1, "z": 0.2}}},
                {"kind": "time_limit", "id": "fast", "seconds": 0.5},
                {"kind": "rotation", "id": "turn", "instance": "cube1", "axis": "z", "angle_deg": 90},
                {"kind": "no_break", "id": "whole"},
            ]
        }
    )
    result = evaluate_goal(goal, run.started, frames, ended)
    c = by_id(result)
    assert (c["down"].status, c["down"].tick) == (Status.MET, 0)  # the saved pose is in the box
    assert (c["turn"].status, c["turn"].tick) == (Status.FAILED, run.end_tick) and abs(c["turn"].measured["rotation_deg"]) < 1.0
    limit = round(0.5 / run.started.timestep_s)  # the turn is not met by 0.5 s, so the time limit fails there
    assert (c["fast"].status, c["fast"].tick) == (Status.FAILED, limit)
    assert (c["whole"].status, c["whole"].tick) == (Status.MET, run.end_tick)
    assert (result.status, result.tick) == (Status.FAILED, limit)
