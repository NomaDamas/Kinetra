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
- `ramp_slide`: the flat block of `test_terrain_ramp.py` (0.1 x 0.1 x 0.02 m, friction 1.0) on the middle of the slope of a
  1 m long, 30 degree ramp of steel A36 (catalog friction 0.23; the pair takes min(1.0, 0.23) = 0.23, X-01e), Earth. It
  slides down with a = g (sin 30 - 0.23 cos 30) = 2.950 m/s^2 from rest. The slope from the middle to the low edge is
  0.5 / cos 30 = 0.5774 m. Its downhill bottom edge reaches the low edge after 0.5774 - 0.05 m: t = sqrt(2 d / a) =
  0.5979 s = 299.0 ticks, where it touches the ground (`begin`). Its uphill bottom edge passes the low edge after
  0.5774 + 0.05 m at the same acceleration: 0.6522 s = 326.1 ticks, when it leaves the ramp for good (its last `end`). That
  second number is an estimate: from the ground touch on the front rides on the ground (friction min(1.0, 0.5628 Earth
  nominal)) instead of the slope, so the block is slower than the estimate and leaves later; the test allows 10 ticks.
  While it slides the engine's box–mesh contact comes and goes from tick to tick (one contact point, the block rocks), so
  the ramp pair has many `begin`/`end` before the last `end` (`contacts.py`: no debounce, the stream says what the engine
  did).
- the swinging arm of `test_break_runtime.py` with its hinge `pin` breakable: the arm and both blocks fly off, hit the
  ground, and the impact breaks both welds. The base and the arm were parent and child (MuJoCo does not collide them) and
  the welded blocks too, so every body–body contact here exists only in a model compiled again after a break.
- the separated pair of `test_separation.py` with zero impulse: its boxes remain touching on the ground when the scheduled
  separation recompiles the model, so their new body–body contact must appear after the `separation` event of that tick.
"""

from __future__ import annotations

import math

import pytest

from kinetra_core import BreakEvent, ContactEvent, Frame, Project, RunCompleted, SeparationEvent, check_run
from kinetra_core.bodies import load_body
from kinetra_engine.run import PreviewRun
from kinetra_judge import Goal, Status, evaluate_goal

import test_terrain_ramp as ramps
from test_break_runtime import BOB_KG, G_EARTH, HANGING_KG, swing
from test_separation import pair as separating_pair
from test_separation import separate

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


RAMP_DEG = 30.0
RAMP_M = 1.0


def ramp_slide() -> Project:
    """The block on the middle of the ramp's slope, its local x up the slope (module docstring)."""
    theta = math.radians(RAMP_DEG)
    half = ramps.THICK / 2
    centre = (-math.sin(theta) * half, 0.0, RAMP_M / 2 * math.tan(theta) + math.cos(theta) * half)
    inst = {"id": "block1", "part": "plate", "material": "grip", "pose": {"badge": "declared", "source": SRC,
            "position": dict(zip("xyz", centre, strict=True)),
            "orientation": {"w": math.cos(-theta / 2), "x": 0.0, "y": math.sin(-theta / 2), "z": 0.0}}}
    return Project.model_validate({"design": {"materials": [ramps.grip(), ramps.STEEL], "parts": [ramps.plate()], "instances": [inst], "joints": []},
                                   "world": {"planet": "earth", "terrain_props": [ramps.ramp(theta, ramps.STEEL["id"], length=RAMP_M)]}})


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


def test_contact_events_assert_alternating_refuses_a_list_that_is_not_one():
    ground = {"kind": "ground"}

    def ev(tick, phase):
        return ContactEvent(kind="contact", tick=tick, phase=phase, body="cube1", other=ground)

    assert_alternating([ev(0, "begin"), ev(3, "end"), ev(5, "begin")])
    for bad in ([ev(0, "begin"), ev(4, "begin")], [ev(2, "end")], [ev(0, "begin"), ev(3, "end"), ev(4, "end")], [ev(5, "begin"), ev(3, "end")]):
        with pytest.raises(AssertionError):
            assert_alternating(bad)


def test_contact_events_a_block_sliding_off_a_ramp_ends_its_ramp_contact_near_the_hand_estimate():
    preview, frames, _ = run(ramp_slide(), 0.8)
    g, dt = load_body("earth").gravity.value, preview.started.timestep_s
    theta = math.radians(RAMP_DEG)
    mu = min(ramps.BLOCK_FRICTION, ramps.STEEL["friction"]["value"])
    assert mu == 0.23
    a = g * (math.sin(theta) - mu * math.cos(theta))
    to_edge = RAMP_M / 2 / math.cos(theta)
    touch_s = math.sqrt(2.0 * (to_edge - ramps.SIDE / 2) / a)
    leave_s = math.sqrt(2.0 * (to_edge + ramps.SIDE / 2) / a)
    assert (round(touch_s / dt, 1), round(leave_s / dt, 1)) == (299.0, 326.1)
    events = contacts(frames)
    assert_alternating(events)
    on_ramp = [e for e in events if pair(e) == ("block1", "prop", "ramp1")]
    on_ground = [e for e in events if pair(e) == ("block1", "ground", None)]
    assert len(on_ramp) + len(on_ground) == len(events)
    assert on_ramp[0].phase == "begin" and on_ramp[0].tick <= 1  # resting on the slope at the saved pose
    assert abs(on_ground[0].tick * dt - touch_s) <= dt  # the front edge reaches the ground within one tick of the hand value
    last = on_ramp[-1]
    assert last.phase == "end" and all(e.tick < last.tick for e in on_ramp[:-1])
    assert on_ground[0].tick < last.tick
    assert 0 <= last.tick - leave_s / dt <= 10  # leaves the ramp for good at or after the estimate, within 10 ticks


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


def test_contact_events_go_on_in_the_model_compiled_again_after_a_separation():
    """X-08 uses the same release path as a break. The zero-impulse boxes stay touching, but MuJoCo excluded them as
    parent–child before the release: their first body–body `begin` is therefore in the recompiled model, after the
    `separation` event of that tick. Their ground contacts survive the rebind without duplicate `begin` events."""
    _, frames, _ = run(separating_pair([separate("stage", "sep", 0.01)], impulse=0.0), 0.03)
    events = contacts(frames)
    assert_alternating(events)
    (separation,) = [e for f in frames for e in f.events if isinstance(e, SeparationEvent)]
    begin = next(e for e in events if pair(e) == ("a", "body", "b"))
    assert (begin.tick, begin.phase) == (separation.tick, "begin")
    carrier = next(f for f in frames if begin in f.events)
    assert separation in carrier.events and carrier.events.index(separation) < carrier.events.index(begin)
    assert [(e.tick, pair(e)) for e in events if e.phase == "begin" and e.other.kind == "ground"] == [
        (0, ("a", "ground", None)),
        (0, ("b", "ground", None)),
    ]


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
