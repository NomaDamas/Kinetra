"""#562: the run stream carries `contact` `begin`/`end` events (C-05b shape) from the engine run (`PreviewRun`,
`kinetra_engine.run.contacts`), and the J-02a `landing` condition is decided on a real engine run.

`uv run pytest packages/engine -q -k contact_events`

Values chosen by the test (`SRC`), not data:

- `wall_drop`: a 0.1 m cube on Earth whose side face is flush with the side wall of a 1 m tall step (`step1`, 1 m long,
  centred at x = 0, wall at x = 0.5), bottom face 1 m above the ground. The step holds it in the project (a start in the
  air is refused by the compiler, `check_floating`), so the run starts with a cube–prop contact and the cube falls along
  the wall. Hand calculation: the ground is at 1 m, so the free fall takes T = sqrt(2 h / g) = 0.4516 s (g = 9.80665 m/s^2,
  `data/bodies/earth.json`), 225.8 ticks of 0.002 s. MuJoCo's semi-implicit Euler puts the bottom face at
  h - g dt^2 n (n + 1) / 2 after n ticks: it is at or under 0 first at n = 226 (n = 225 leaves 2.65 mm). The speed there is
  sqrt(2 g h) = 4.43 m/s.
- the swinging arm of `test_break_runtime.py` with its hinge `pin` breakable: the arm and both blocks fly off, hit the
  ground, and the impact breaks both welds. The base and the arm were parent and child (MuJoCo does not collide them) and
  the welded blocks too, so every body–body contact here exists only in a model compiled again after a break.
"""

from __future__ import annotations

import math

import pytest

from kinetra_core import BreakEvent, ContactEvent, Frame, Project, RunCompleted, check_run
from kinetra_core.bodies import load_body
from kinetra_engine.run import PreviewRun
from kinetra_judge import Goal, Status, evaluate_goal

from test_break_runtime import BOB_KG, G_EARTH, HANGING_KG, swing

SRC = {"ref": "#562 test fixture: value chosen by the test", "locator": "test_contact_events.py"}
DROP_M = 1.0
EDGE_M = 0.1


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def wall_drop() -> Project:
    """The cube against the step's wall, 1 m up (module docstring)."""
    shape = {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "box", "size_x": ax(EDGE_M), "size_y": ax(EDGE_M), "size_z": ax(EDGE_M)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    material = {"id": "mat", "name": "Test material", "density": q(7850.0, "kg/m^3"), "yield_strength": q(2.5e8, "Pa"),
                "elastic_modulus": q(2.0e11, "Pa"), "friction": q(0.5, "1")}
    part = {"id": "cube", "name": "cube", "parameters": [], "snap_points": [], "shape": shape}
    inst = {"id": "cube1", "part": "cube", "material": "mat", "pose": {"badge": "declared", "source": SRC,
            "position": {"x": 0.5 + EDGE_M / 2, "y": 0.0, "z": DROP_M + EDGE_M / 2}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    step = {"id": "step1", "kind": "step", "material": None, "placement": {"badge": "declared", "source": SRC, "x": 0.0, "y": 0.0, "yaw": 0.0},
            "length": q(1.0, "m"), "width": q(0.5, "m"), "height": q(DROP_M, "m")}
    return Project.model_validate({"design": {"materials": [material], "parts": [part], "instances": [inst], "joints": []},
                                   "world": {"planet": "earth", "terrain_props": [step]}})


def run(project: Project, duration_s: float) -> tuple[PreviewRun, list[Frame], object]:
    preview = PreviewRun(project, run_id="contact-run", project_id="p", revision=1, duration_s=duration_s)
    items = list(preview)
    frames, ended = items[:-1], items[-1]
    check_run(preview.started, frames, ended)  # every event in the first frame after it, tick <= frame tick
    assert isinstance(ended.end, RunCompleted)
    return preview, frames, ended


def contacts(frames: list[Frame]) -> list[ContactEvent]:
    return [e for f in frames for e in f.events if isinstance(e, ContactEvent)]


def pair(e: ContactEvent) -> tuple:
    return (e.body, e.other.kind, getattr(e.other, "id", None))


def assert_alternating(events: list[ContactEvent]) -> None:
    """Dedupe: per pair the phases alternate begin, end, begin, ..., starting with begin; ticks never go back."""
    touching: set[tuple] = set()
    ticks = [e.tick for e in events]
    assert ticks == sorted(ticks)
    for e in events:
        if e.phase == "begin":
            assert pair(e) not in touching, e
            touching.add(pair(e))
        else:
            assert pair(e) in touching, e
            touching.discard(pair(e))


def test_contact_events_first_ground_begin_of_a_1m_drop_matches_the_hand_calculation():
    preview, frames, _ = run(wall_drop(), 0.6)
    g = load_body("earth").gravity.value
    dt = preview.started.timestep_s
    assert g == 9.80665 and dt == 0.002
    hand_s = math.sqrt(2.0 * DROP_M / g)
    assert hand_s == pytest.approx(0.45160075575178754, rel=1e-12)
    euler_tick = next(n for n in range(1, 1000) if DROP_M - g * dt * dt * n * (n + 1) / 2.0 <= 0.0)
    assert euler_tick == 226
    events = contacts(frames)
    assert_alternating(events)
    # the cube starts against the step's wall (tick 0, the saved pose), and touches the ground once, at the hand-calculated tick
    assert [(e.tick, e.phase, pair(e)) for e in events] == [
        (0, "begin", ("cube1", "prop", "step1")),
        (euler_tick, "begin", ("cube1", "ground", None)),
    ]
    landing = events[1]
    assert abs(landing.tick * dt - hand_s) <= dt  # within one tick of the free-fall time
    assert landing.force is None  # not given by this pass (module docstring of `contacts.py`)
    carrier = next(f for f in frames if landing in f.events)
    previous = frames[frames.index(carrier) - 1]
    assert previous.tick < landing.tick <= carrier.tick  # C-05b: the next frame carries it


def test_contact_events_ten_runs_give_the_same_event_list():
    lists = [[e.model_dump() for e in contacts(run(wall_drop(), 0.6)[1])] for _ in range(10)]
    assert lists[0] and all(other == lists[0] for other in lists[1:])


def test_contact_events_go_on_in_the_model_compiled_again_after_a_break():
    """`pin` breaks in the swing, then the welds at the impact (`test_break_runtime.py`): the body–body contacts that
    follow (arm and blocks, arm and base) exist only in the models compiled again, so the watch followed them."""
    tip, mid, pin = 2 * BOB_KG * G_EARTH, 6 * BOB_KG * G_EARTH, 1.5 * HANGING_KG * G_EARTH
    _, frames, _ = run(swing(tip, mid, pin), 1.0)
    events = contacts(frames)
    assert_alternating(events)
    broke = {e.joint: e.tick for f in frames for e in f.events if isinstance(e, BreakEvent)}
    assert set(broke) == {"pin", "weld-mid", "weld-tip"}
    assert (events[0].tick, events[0].phase, pair(events[0])) == (0, "begin", ("base", "ground", None))
    begun = {}
    for e in events:
        if e.phase == "begin":
            begun.setdefault(pair(e), e.tick)
    # body–ground after the pin broke; body–body only between bodies a break had freed from each other (pair: smaller id first)
    assert begun[("bob-tip", "ground", None)] > broke["pin"]
    assert begun[("arm", "body", "bob-tip")] >= broke["weld-tip"]
    assert begun[("arm", "body", "base")] > broke["pin"]
    assert all(b.other.kind != "body" or b.tick >= min(broke.values()) for b in events)
    # the same run again gives the same events
    assert contacts(run(swing(tip, mid, pin), 1.0)[1]) == events


@pytest.mark.parametrize(("max_speed", "status"), [(5.0, Status.MET), (4.0, Status.FAILED)])
def test_contact_events_decide_the_landing_condition_on_an_engine_run(max_speed, status):
    """J-02a `landing` on the engine's stream: the touchdown is the ground `begin` at tick 226 (the prop contact since tick
    0 is not ground), upright, at about sqrt(2 g h) = 4.43 m/s; a 5 m/s limit is met, a 4 m/s limit fails there."""
    preview, frames, ended = run(wall_drop(), 0.6)
    goal = Goal.model_validate({"conditions": [{"kind": "landing", "id": "lands", "instance": "cube1", "max_tilt_deg": 10.0, "max_speed_m_s": max_speed}]})
    result = evaluate_goal(goal, preview.started, frames, ended)
    landing = result.conditions[0]
    assert (landing.status, landing.tick) == (status, 226)
    g = load_body("earth").gravity.value
    assert landing.measured["speed_m_s"] == pytest.approx(math.sqrt(2.0 * g * DROP_M), rel=1e-2)
    assert landing.measured["tilt_deg"] == pytest.approx(0.0, abs=1e-6)
