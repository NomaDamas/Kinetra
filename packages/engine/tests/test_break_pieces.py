"""X-13: a piece that broke off is simulated, streamed, hashed, touched and evaluated until the end of the run.

`uv run pytest packages/engine -q -k break_pieces`

There is no rule that removes a piece or takes it out of the physics (by distance, by count or by time): after a break
(X-04b) the released body is a free body of the same model until the end tick. These tests hold the run to that.

Two designs, values chosen by the test (`SRC`), not data:

- `ledge(high)`: a 0.3 x 0.3 x 1.6 m pillar (144 kg at 1000 kg/m^3) standing on the Moon's ground, with a 0.1 m cube
  (`piece`, 1 kg) on a breakable fixed joint at its side, 1 cm off its face, the cube's underside 0.75 m (`high=False`)
  or 1.45 m (`high=True`) above the ground. The joint's threshold is half the cube's weight, so it breaks within the first
  ticks (the cube hangs on it) and the cube drops from rest. Free fall from rest: t = sqrt(2 h / g), with g = 1.62 m/s^2
  (`data/bodies/moon.json`): 0.962 s for 0.75 m, 1.338 s for 1.45 m.
- `shot()`: no gravity (the run's MJCF is compiled with gravity 0, see `weightless`). A 0.1 x 0.1 x 0.4 m pillar
  (`anchor`) stands on the ground; at its side, 0.25 m up, a 0.1 m cube (`piece`) with the VACCO 2 lbf thruster welded to
  its back (`piece-jet`) is held by a breakable fixed joint (2 N); 0.3 m ahead of it a 0.1 m cube (`target`) rides a
  free slider along x hung from the pillar's top (the compiler wants one assembly, so the target hangs from the pillar
  on a slider: along its axis a slider carries no force). The thruster burns for the first 0.1 s: the joint breaks, the
  piece flies along +x, coasts after the burn and hits the target.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from gltf_samples import catalog_material, library_part
from kinetra_core import BreakEvent, Frame, Project, RunCompleted, RunStarted, check_placement, check_run
from kinetra_core.bodies import load_body
from kinetra_engine.compiler import build_body_tree, release, to_mjcf
from kinetra_engine.run import PreviewRun, compile_project
from kinetra_judge import Goal, Status, evaluate_goal

from test_break_runtime import box, instance, joint, material, snap

SRC = {"ref": "X-13 test fixture: value chosen by the test", "locator": "test_break_pieces.py"}
G_MOON = load_body("moon").gravity.value
S = math.sqrt(0.5)
OUT_X = {"x": 0.0, "y": S, "z": 0.0, "w": S}  # a snap frame facing +x
BACK_X = {"x": 0.0, "y": -S, "z": 0.0, "w": S}  # facing -x
OUT_Y = {"x": -S, "y": 0.0, "z": 0.0, "w": S}  # facing +y
BACK_Y = {"x": S, "y": 0.0, "z": 0.0, "w": S}  # facing -y
UP = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
DOWN = {"x": 1.0, "y": 0.0, "z": 0.0, "w": 0.0}
MZ = 0.04729059031466532  # the thruster's mount snap point sits at -MZ on its z axis (test_thrust.py)
PIECE_HALF = 0.05  # the cube's half size [m]
LOW_DROP, HIGH_DROP = 0.75, 1.45  # the cube's underside above the ground [m]


def ax(v):
    return {"offset": v, "terms": []}


def face(ident, at, orientation):
    return {"id": ident, "kind": "face", "accepts": ["face"], "badge": "declared", "source": SRC, "position": {"x": ax(at[0]), "y": ax(at[1]), "z": ax(at[2])}, "orientation": orientation}


def ledge(high: bool) -> Project:
    """The pillar with the cube held at its side (module docstring)."""
    parts = [
        box("pillar", (0.3, 0.3, 1.6), (0.0, 0.0, 0.8), [snap("low", (0.15, 0.0, 0.8), OUT_X), snap("high", (0.15, 0.0, 1.5), OUT_X)]),
        box("cube", (0.1, 0.1, 0.1), (0.0, 0.0, 0.0), [snap("back", (-0.06, 0.0, 0.0), BACK_X)]),  # 1 cm off its face
    ]
    drop = HIGH_DROP if high else LOW_DROP
    return Project.model_validate(
        {
            "design": {
                "materials": [material("light", 1000.0)],
                "parts": parts,
                "instances": [instance("pillar", "pillar", "light", (0.0, 0.0, 0.0)), instance("piece", "cube", "light", (0.21, 0.0, drop + PIECE_HALF))],
                "joints": [joint("snap", "fixed", ("pillar", "high" if high else "low"), ("piece", "back"), 0.5 * 1.0 * G_MOON)],
            },
            "world": {"planet": "moon"},
        }
    )


def shot() -> Project:
    """The thruster-driven piece and the target on its slider (module docstring)."""
    cube = box("cube", (0.1, 0.1, 0.1), (0.0, 0.0, 0.05), [face("back", (-0.05, 0.0, 0.05), BACK_X), snap("left", (0.0, 0.05, 0.05), OUT_Y)])
    target = box("target", (0.1, 0.1, 0.1), (0.0, 0.0, 0.05), [snap("rail", (-0.4, 0.1, 0.15), DOWN)])
    pillar = box("pillar", (0.1, 0.1, 0.4), (0.0, 0.0, 0.2), [snap("right", (0.0, -0.05, 0.3), BACK_Y), snap("rail", (0.0, 0.0, 0.4), UP)])
    jet = {
        "id": "piece-jet",
        "part": "thruster-vacco-48003040",
        "material": "steel-a36",
        "pose": {"badge": "declared", "source": SRC, "position": {"x": -0.05 - MZ, "y": 0.0, "z": 0.3}, "orientation": BACK_X},  # thrust +x
    }
    rail = {"id": "rail", "kind": "slider", "a": {"instance": "anchor", "snap_point": "rail"}, "b": {"instance": "target", "snap_point": "rail"},
            "axis": {"x": 1.0, "y": 0.0, "z": 0.0, "badge": "declared", "source": SRC}}
    mount = {"id": "mount", "kind": "fixed", "a": {"instance": "piece-jet", "snap_point": "mount"}, "b": {"instance": "piece", "snap_point": "back"}}
    burn = {"type": "actuate", "id": "burn", "actuator": "main", "start": 0.0, "end": 0.1, "command": 1.0, "badge": "declared", "source": SRC}
    return Project.model_validate(
        {
            "design": {
                "materials": [material("light", 1000.0), catalog_material("steel-a36").model_dump(mode="json")],
                "parts": [cube, target, pillar, library_part("thruster-vacco-48003040").model_dump(mode="json")],
                "instances": [
                    instance("anchor", "pillar", "light", (0.0, 0.1, 0.0)),
                    instance("piece", "cube", "light", (0.0, 0.0, 0.25)),
                    jet,
                    instance("target", "target", "light", (0.4, 0.0, 0.25)),
                ],
                "joints": [mount, joint("snap", "fixed", ("anchor", "right"), ("piece", "left"), 2.0), rail],
                "actuators": [{"id": "main", "kind": "thruster", "instance": "piece-jet"}],
                "schedule": {"entries": [burn]},
            },
            "world": {"planet": "moon"},
        }
    )


@pytest.fixture
def weightless(monkeypatch):
    """Compile every model of the run (the first and the ones after a break) with gravity 0: the MJCF's `gravity` is
    replaced. The run says so itself: its `model_labels` carry the "미적용: ... 중력" sentence (asserted)."""
    from kinetra_engine.run import preview

    real = preview.to_mjcf

    def zero_g(tree, **kw):
        return re.sub(r'gravity="[^"]*"', 'gravity="0 0 0"', real(tree, **kw), count=1)

    monkeypatch.setattr(preview, "to_mjcf", zero_g)


def run(project: Project, duration_s: float) -> tuple[RunStarted, list[Frame], RunCompleted, PreviewRun]:
    preview = PreviewRun(project, run_id="pieces", project_id="p", revision=1, duration_s=duration_s, frame_every_ticks=1)
    items = list(preview)
    frames, ended = items[:-1], items[-1]
    check_run(preview.started, frames, ended)
    assert isinstance(ended.end, RunCompleted)
    return preview.started, frames, ended, preview


def breaks(frames: list[Frame]) -> list[BreakEvent]:
    return [e for f in frames for e in f.events if isinstance(e, BreakEvent)]


def position(frame: Frame, body: str) -> np.ndarray:
    p = next(p for p in frame.poses if p.body == body)
    return np.array([p.position.x, p.position.y, p.position.z])


def quat(frame: Frame, body: str) -> np.ndarray:
    o = next(p for p in frame.poses if p.body == body).orientation
    return np.array([o.w, o.x, o.y, o.z])


def test_break_pieces_fixtures_are_valid_placements():
    assert check_placement(ledge(False)) == ()
    assert check_placement(ledge(True)) == ()
    assert check_placement(shot()) == ()


# --- the Moon drop: the piece falls, lands and stays in the stream -----------------------------------------------------


def test_break_pieces_moon_drop_time_matches_the_hand_calculation():
    """The cube comes off within the first ticks and falls 0.75 m in vacuum. Hand calculation from rest: the underside
    reaches the ground sqrt(2 h / g) = 0.962 s (481.1 ticks of 0.002 s) after the break; the engine gets there within 2
    ticks of that. While it falls, its height is the integrator's free fall to rounding (1e-9 m): with the velocity v_b it
    had at the break (the pillar settles on the soft ground then; measured -2.6 mm/s, under 1 cm/s), semi-implicit Euler
    gives z_b + v_b t - g t^2 / 2 - g dt t / 2 (the last term is the step's error against the continuous parabola)."""
    started, frames, _, _ = run(ledge(False), 1.2)
    (event,) = breaks(frames)
    b = event.tick
    assert event.joint == "snap" and b <= 5
    dt = started.timestep_s
    z = np.array([position(f, "piece")[2] for f in frames])
    assert z[b] == pytest.approx(LOW_DROP + PIECE_HALF, abs=1e-4)  # still where it hung
    landed = next(k for k in range(len(z)) if z[k] - PIECE_HALF <= 0.0)
    assert abs(landed - (b + math.sqrt(2 * LOW_DROP / G_MOON) / dt)) <= 2
    v_b = (z[b + 1] - z[b]) / dt + G_MOON * dt  # v_{b+1} = v_b - g dt and z_{b+1} = z_b + v_{b+1} dt
    assert abs(v_b) < 0.01
    for k in range(b, landed - 10):
        t = (k - b) * dt
        assert z[k] == pytest.approx(z[b] + v_b * t - 0.5 * G_MOON * t * t - 0.5 * G_MOON * dt * t, abs=1e-9)


def test_break_pieces_total_mass_is_the_same_before_and_after_the_break():
    """The model compiled again after the break (as the run does: `release` then `to_mjcf`) has the same bodies and the same
    total mass as the first one, and every body keeps its own mass: the piece is not dropped from the physics."""
    before = compile_project(ledge(False))
    after = mujoco.MjModel.from_xml_string(to_mjcf(release(build_body_tree(ledge(False)), ["snap"]), drives=before.drives))
    assert after.nbody == before.model.nbody
    assert float(after.body_mass.sum()) == pytest.approx(float(before.model.body_mass.sum()), rel=0.0, abs=1e-12)
    for body in ("pillar", "piece"):
        a = mujoco.mj_name2id(before.model, mujoco.mjtObj.mjOBJ_BODY, body)
        b = mujoco.mj_name2id(after, mujoco.mjtObj.mjOBJ_BODY, body)
        assert after.body_mass[b] == before.model.body_mass[a]
    assert float(after.body_mass.sum()) == pytest.approx(144.0 + 1.0, rel=1e-9)  # 0.3 x 0.3 x 1.6 and 0.1^3 m^3 at 1000 kg/m^3


def test_break_pieces_piece_lands_on_the_ground_and_stops():
    """After its fall the cube rests on the ground: its last height is above the ground (its underside within 1 mm of it,
    the soft contact's resting depth), it never went through it, and it has stopped (under 1 mm/s over the last 0.1 s).
    At the hit (sqrt(2 g h) = 1.56 m/s) the soft contact lets the underside in by up to 9.4 mm (measured) for a few ticks, then pushes it
    back; the cube's centre never goes below the ground."""
    started, frames, _, _ = run(ledge(False), 2.0)
    z = np.array([position(f, "piece")[2] for f in frames])
    assert z.min() > 0.0 and z.min() - PIECE_HALF > -0.02  # never through the ground
    assert z[-1] > 0.0 and z[-1] - PIECE_HALF == pytest.approx(0.0, abs=1e-3)
    last = np.array([position(f, "piece") for f in frames[-51:]])
    assert np.linalg.norm(last[-1] - last[0]) / (50 * started.timestep_s) < 1e-3


def test_break_pieces_every_body_is_in_the_last_frame_and_in_the_trajectory_hash(monkeypatch):
    """The stream keeps every body to the end: the last frame has a pose for the pillar and for the piece, which by then
    lies on the ground. The trajectory hash is over every tick's generalized positions: the last tick's are the piece's
    free joint (position, then quaternion) with the very values of the last frame's pose."""
    from kinetra_engine.run import preview

    chunks: list[bytes] = []
    real = preview.hashlib.sha256

    class Recorded:
        def __init__(self, data: bytes):
            self._h = real(data)
            chunks.append(bytes(data))

        def update(self, data: bytes) -> None:
            self._h.update(data)
            chunks.append(bytes(data))

        def hexdigest(self) -> str:
            return self._h.hexdigest()

    monkeypatch.setattr(preview, "hashlib", SimpleNamespace(sha256=Recorded))
    started, frames, ended, _ = run(ledge(False), 2.0)
    last = frames[-1]
    assert last.tick == ended.last_tick
    assert [p.body for p in last.poses] == [b.id for b in started.bodies] == ["pillar", "piece"]
    assert ended.end.trajectory.hash == "sha256:" + hashlib.sha256(b"".join(chunks)).hexdigest()
    assert len(chunks) == ended.last_tick + 1  # tick 0 and every tick after it
    qpos = np.frombuffer(chunks[-1], dtype=np.float64)
    piece = np.concatenate([position(last, "piece"), quat(last, "piece")])
    assert any(np.array_equal(qpos[i : i + 7], piece) for i in range(0, len(qpos) - 6))


def test_break_pieces_repeat_runs_hash_the_same():
    _, frames_a, end_a, _ = run(ledge(False), 1.5)
    _, frames_b, end_b, _ = run(ledge(False), 1.5)
    assert [f.model_dump() for f in frames_a] == [f.model_dump() for f in frames_b]
    assert end_a.end.trajectory.hash == end_b.end.trajectory.hash


# --- the shot without gravity: the piece hits another body ----------------------------------------------------------


def _centre_of_mass(model: mujoco.MjModel, frames: list[Frame], body: str) -> tuple[np.ndarray, float]:
    row = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body)
    out = []
    for f in frames:
        r = np.zeros(9)
        mujoco.mju_quat2Mat(r, quat(f, body))
        out.append(position(f, body) + r.reshape(3, 3) @ model.body_ipos[row])
    return np.array(out), float(model.body_mass[row])


def test_break_pieces_a_piece_hits_another_body_and_momentum_is_kept(weightless):
    """The thruster breaks `snap` (2 N) during its 0.1 s burn and the piece coasts into the target. The target was still
    (along x) and moves off after the hit; the piece slows. The momentum of the piece plus the target, from their centres
    of mass (finite differences of the frames at every tick), is the same 20 ticks before and 20 ticks after the contact:

    - along x (the hit's direction and the slider's free axis, so nothing else pushes there) within 1e-4 of it, relative
      (measured: 7e-6, the soft contact's few ticks against the central differences);
    - as a vector within 1 % of its size: the slider hangs the target from the anchor, which carries y and z forces between
      them (measured: 0.23 %). Measured speeds along x: piece 0.619 -> 0.330 m/s, target 0 -> 0.398 m/s."""
    started, frames, _, preview = run(shot(), 1.0)
    assert any(label.startswith("미적용: ") and "중력" in label for label in started.model_labels)
    (event,) = breaks(frames)
    assert event.joint == "snap" and event.tick * started.timestep_s < 0.1
    model = preview.compiled.model  # masses and centres of mass do not change at a break (previous test); no propellant here
    piece, m_piece = _centre_of_mass(model, frames, "piece")
    target, m_target = _centre_of_mass(model, frames, "target")
    dt = started.timestep_s
    v_piece = (piece[2:] - piece[:-2]) / (2 * dt)  # index k is tick k + 1
    v_target = (target[2:] - target[:-2]) / (2 * dt)
    burn_end = round(0.12 / dt)  # the burn's 0.1 s plus the valve's closing
    hit = next(k for k in range(burn_end, len(v_target)) if v_target[k][0] > 1e-3)
    gap = position(frames[hit + 1], "target")[0] - position(frames[hit + 1], "piece")[0]
    assert gap < 0.1 + 1e-3  # the cubes (0.1 m) are touching: the target moved because it was hit
    before, after = hit - 20, hit + 20
    assert abs(v_target[before][0]) < 1e-6 and v_target[after][0] > 0.1  # the hit changes the target's velocity
    assert v_piece[after][0] < v_piece[before][0]
    p_before = m_piece * v_piece[before] + m_target * v_target[before]
    p_after = m_piece * v_piece[after] + m_target * v_target[after]
    assert p_after[0] == pytest.approx(p_before[0], rel=1e-4)
    assert np.linalg.norm(p_after - p_before) <= 0.01 * np.linalg.norm(p_before)
    assert [p.body for p in frames[-1].poses] == [b.id for b in started.bodies]


# --- success conditions on a piece (J-02a) ----------------------------------------------------------------------------

GOAL = Goal.model_validate(
    {
        "conditions": [
            # the piece lies on the ground beside the pillar (its centre 0.05 m up when it rests there)
            {"kind": "reach", "id": "down", "instance": "piece", "region": {"min": {"x": 0.15, "y": -0.2, "z": 0.0}, "max": {"x": 0.35, "y": 0.2, "z": 0.06}}},
            {"kind": "time_limit", "id": "soon", "seconds": 1.2},
        ]
    }
)


@pytest.mark.parametrize(("high", "status"), [(False, Status.MET), (True, Status.FAILED)])
def test_break_pieces_goal_on_the_broken_off_part_follows_its_trajectory(high, status):
    """The goal names the part that breaks off: it must reach the ground beside the pillar within 1.2 s. From 0.75 m the
    piece falls in 0.962 s (hand calculation, module docstring): met, at the tick it comes in; from 1.45 m it needs 1.338 s:
    it reaches the box after the limit, so the goal fails at the limit's tick. Were the piece left out of the evaluation
    (not in `bodies`, or frozen where it broke off), `down` would never be met and the low scene would fail."""
    started, frames, ended, _ = run(ledge(high), 1.6)
    (event,) = breaks(frames)
    result = evaluate_goal(GOAL, started, frames, ended)
    c = {r.id: r for r in result.conditions}
    drop = HIGH_DROP if high else LOW_DROP
    dt = started.timestep_s
    hand = event.tick + math.sqrt(2 * (drop - 0.01) / G_MOON) / dt  # the box starts 1 cm above the resting height
    assert c["down"].status is Status.MET and abs(c["down"].tick - hand) <= 3
    assert result.status is status
    if status is Status.FAILED:
        assert (c["soon"].status, c["soon"].tick) == (Status.FAILED, round(1.2 / dt))
    else:
        assert c["soon"].status is Status.MET and result.tick == c["down"].tick


if __name__ == "__main__":
    # The real-time factor of the reference scene (break-threshold.md, X-13): `uv run python packages/engine/tests/test_break_pieces.py`
    import os
    import platform

    duration = 2.0
    project = ledge(False)
    for repeat in range(3):
        preview = PreviewRun(project, run_id="rtf", project_id="p", revision=1, duration_s=duration)
        wall, cpu = time.perf_counter(), time.process_time()
        items = list(preview)
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
        n = len(breaks(items[:-1]))
        print(f"repeat {repeat}: sim {duration} s, wall {wall:.3f} s, rtf {duration / wall:.2f}, rtf_cpu {duration / cpu:.2f}, breaks {n}, "
              f"bodies in last frame {len(items[-2].poses)}, hash {items[-1].end.trajectory.hash[:23]}")
    print(platform.platform(), platform.python_version(), mujoco.__version__, "load average", os.getloadavg())
