"""X-02a: compile and run a project over the core protocol and receive the frame stream.

`uv run pytest packages/engine -q -k "simulate and stream"`

The project is two blocks welded on top of each other, standing on the ground plane z = 0 (the joined snap points meet
at the saved pose, the placement checks pass). The compiled model has no ground and the engine's default gravity
(W-03a has not landed), so the body falls; the stream says so in `model_labels`. Values are the test's own choices
(`SRC`), not data.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path

import mujoco
import pytest
from pydantic import TypeAdapter
from websockets.asyncio.client import connect

from kinetra_core import (
    PROTOCOL_VERSION,
    ClientMessage,
    Frame,
    Project,
    ProjectIncomplete,
    ReasonCode,
    RunCompleted,
    RunEnded,
    RunFailed,
    RunKind,
    RunStarted,
    ServerMessage,
    check_frame,
    check_placement,
    check_run,
    decode_frame,
    project_hash,
)
from kinetra_engine.protocol import Hub
from kinetra_engine.run import FRAME_RATE_CEILING_HZ, PreviewRun, compile_project, default_frame_every_ticks, end_tick
from kinetra_engine.run.platform_tag import _wheel_tags

SERVER = TypeAdapter(ServerMessage)
CLIENT = TypeAdapter(ClientMessage)
SRC = {"ref": "X-02a test fixture: value chosen by the test", "locator": "test_simulate_stream.py"}
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
TILT = {"x": 0.0, "y": math.sin(0.15), "z": 0.0, "w": math.cos(0.15)}  # 0.3 rad about +y, so the pose is not trivial


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def pos(x, y, z):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def snap(ident, z, quat=IDENT):
    return {"id": ident, "kind": "plug", "accepts": ["plug"], "badge": "declared", "source": SRC, "position": pos(0, 0, z), "orientation": quat}


BLOCK = {
    "id": "block",
    "name": "block",
    "parameters": [],
    "snap_points": [snap("bottom", 0.0, {"x": 1.0, "y": 0.0, "z": 0.0, "w": 0.0}), snap("top", 0.2)],
    "shape": {
        "badge": "declared",
        "source": SRC,
        "components": [
            {"id": "b", "operation": "add", "primitive": {"kind": "box", "size_x": ax(0.2), "size_y": ax(0.1), "size_z": ax(0.2)}, "position": pos(0, 0, 0.1)}
        ],
    },
}
MATERIAL = {"id": "mat", "name": "Test material", "density": q(1000.0, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


def instance(ident, z, material="mat"):
    return {"id": ident, "part": "block", "material": material,
            "pose": {"badge": "declared", "source": SRC, "position": {"x": 0.0, "y": 0.0, "z": z}, "orientation": IDENT}}


def tower(material="mat"):
    """`base` on the ground, `top` welded on it: one rigid body of two instances."""
    weld = {"id": "weld", "kind": "fixed", "a": {"instance": "base", "snap_point": "top"}, "b": {"instance": "top", "snap_point": "bottom"}}
    return Project.model_validate(
        {
            "design": {"materials": [MATERIAL], "parts": [BLOCK], "instances": [instance("base", 0.0), instance("top", 0.2, material)], "joints": [weld]},
            "world": {"planet": "moon"},
        }
    )


def run_of(project, duration_s=0.25, run_id="run-1", **kw):
    return PreviewRun(project, run_id=run_id, project_id="tower", revision=3, duration_s=duration_s, **kw)


def split(run):
    items = list(run)
    return items[:-1], items[-1]


# --- the run itself ----------------------------------------------------------------------------------------------


def test_simulate_stream_fixture_is_a_valid_placement():
    assert check_placement(tower()) == ()


def test_simulate_stream_run_started_names_the_document_platform_and_bodies():
    project = tower()
    run = run_of(project)
    s = run.started
    assert s.kind is RunKind.PREVIEW and s.badge == "sim"
    assert (s.project_id, s.revision, s.definition_hash, s.planet) == ("tower", 3, project_hash(project), "moon")
    assert [(b.id, b.instances) for b in s.bodies] == [("base", ("base", "top"))]
    model = run.compiled.model
    assert s.timestep_s == model.opt.timestep == s.platform.compute.timestep_s
    assert s.frame_every_ticks == default_frame_every_ticks(s.timestep_s)
    assert 1.0 / (s.timestep_s * s.frame_every_ticks) <= FRAME_RATE_CEILING_HZ
    assert 1.0 / (s.timestep_s * (s.frame_every_ticks - 1)) > FRAME_RATE_CEILING_HZ  # the fewest ticks under the ceiling
    tag = s.platform
    assert tag.engine.name == "mujoco" and tag.engine.version == mujoco.__version__ and tag.engine.distribution == "wheel"
    assert tag.compute.integrator == mujoco.mjtIntegrator(model.opt.integrator).name.removeprefix("mjINT_").lower()
    assert tag.compute.solver["iterations"] == model.opt.iterations
    assert (tag.threads.physics, tag.threads.solver) == (1, 1)
    # the planet is the moon, the model has the engine's default gravity and no ground: the labels say both
    assert any("중력" in label and "W-03a" in label for label in s.model_labels)
    assert any("지면 없음" in label for label in s.model_labels)


def test_simulate_stream_frames_pass_check_run_with_the_end_frame_off_the_grid():
    run = run_of(tower(), duration_s=0.25)
    frames, ended = split(run)
    s = run.started
    assert isinstance(ended, RunEnded) and isinstance(ended.end, RunCompleted)
    check_run(s, frames, ended)
    assert ended.end.trajectory.platform == s.platform
    last = end_tick(0.25, s.timestep_s)
    assert last * s.timestep_s >= 0.25 > (last - 1) * s.timestep_s
    assert last % s.frame_every_ticks  # 125 ticks, every 9: the end lies between two intervals
    assert [f.tick for f in frames] == [*range(0, last, s.frame_every_ticks), last]
    assert ended.last_tick == last


def test_simulate_stream_poses_are_the_engine_state_falling_under_the_model_gravity():
    run = run_of(tower(), duration_s=0.2)
    frames, _ = split(run)
    g = run.compiled.model.opt.gravity[2]
    first, last = frames[0], frames[-1]
    z0 = first.poses[0].position.z
    assert z0 == pytest.approx(0.0, abs=1e-12)  # the body frame is the frame of `base`, which stands at z = 0
    # semi-implicit Euler from rest: z_n = z_0 + g dt^2 n(n+1)/2 (the engine's default integrator, `compute.integrator`)
    n, dt = last.tick, run.started.timestep_s
    assert run.started.platform.compute.integrator == "euler"
    assert last.poses[0].position.z == pytest.approx(z0 + g * dt * dt * n * (n + 1) / 2, rel=1e-9)
    assert last.poses[0].orientation.w == pytest.approx(1.0)


def test_simulate_stream_a_slower_than_real_time_run_has_the_same_ticks_times_and_poses():
    """A0-05 (D6): the speed at which the core runs does not change the trajectory. One run is read as fast as it
    goes; the other is held back after every frame so it runs slower than real time. Same ticks, same times, same
    poses bit for bit, same trajectory hash."""
    fast = list(run_of(tower(), duration_s=0.1))
    slow_run = run_of(tower(), duration_s=0.1)
    slow, started = [], time.perf_counter()
    for item in slow_run:
        slow.append(item)
        if isinstance(item, Frame):
            time.sleep(slow_run.started.timestep_s * slow_run.started.frame_every_ticks * 1.5)
    wall = time.perf_counter() - started
    assert wall > slow[-2].sim_time_s  # it really was slower than real time
    assert [(f.tick, f.sim_time_s, f.poses) for f in fast[:-1]] == [(f.tick, f.sim_time_s, f.poses) for f in slow[:-1]]
    assert fast[-1].end.trajectory.hash == slow[-1].end.trajectory.hash


def test_simulate_stream_compile_and_run_call_require_complete():
    broken = tower(material="no-such-material")
    with pytest.raises(ProjectIncomplete) as compile_refused:
        compile_project(broken)
    assert compile_refused.value.operation.value == "compile"
    with pytest.raises(ProjectIncomplete) as run_refused:
        run_of(broken)
    assert run_refused.value.operation.value == "run"
    assert [m.id for m in run_refused.value.missing] == ["no-such-material"]


def test_simulate_stream_a_diverging_run_fails_with_its_last_finite_frame():
    run = run_of(tower(), duration_s=0.1)
    run.compiled.model.opt.gravity[:] = (0.0, 0.0, -1e308)  # the engine meets a non-finite state on the first steps
    frames, ended = split(run)
    assert isinstance(ended.end, RunFailed)
    check_run(run.started, frames, ended)
    assert all(math.isfinite(f.poses[0].position.z) for f in frames)


# --- over the core protocol --------------------------------------------------------------------------------------


async def _session(hub, *messages, until):
    """Open a connection, say hello, subscribe to `tower`, send `messages`; collect what the core sends (binary frames
    decoded against the last `run_started`) until `until(received)`."""
    async with hub.serve(allowed_origins=[None]) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"type": "hello", "protocol": PROTOCOL_VERSION}))
            await ws.send(json.dumps({"type": "subscribe", "project": "tower"}))
            for m in messages:
                await ws.send(json.dumps(m))
            received, started = [], None
            while not until(received):
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                if isinstance(raw, bytes):
                    received.append(decode_frame(raw, started.run_id, [b.id for b in started.bodies]))
                    continue
                message = SERVER.validate_json(raw)
                if isinstance(message, RunStarted):
                    started = message
                received.append(message)
            return received


def _ended(n=1):
    return lambda received: sum(isinstance(m, RunEnded) for m in received) >= n


def _stream(received):
    started = next(m for m in received if isinstance(m, RunStarted))
    frames = [m for m in received if isinstance(m, Frame)]
    ended = next(m for m in received if isinstance(m, RunEnded))
    return started, frames, ended


def test_simulate_stream_over_the_protocol_passes_the_stream_checks():
    """`run` → `run_started`, binary frames, `run_ended`: every frame passes `check_frame` and the whole stream
    `check_run` (the checks the C-05c reference client applies), and the stream equals the run computed directly."""
    hub = Hub({"tower": tower()})
    request = {"type": "run", "id": "run-1", "duration_s": 0.25, "speed": 0}
    assert CLIENT.validate_python(request).type == "run"  # a client message of the schema
    received = asyncio.run(_session(hub, request, until=_ended()))
    started, frames, ended = _stream(received)
    assert started.run_id == ended.run_id == "run-1"
    for f in frames:
        check_frame(started, f, final=True)
    check_run(started, frames, ended)
    direct_frames, direct_end = split(run_of(tower(), duration_s=0.25, run_id="run-1"))
    assert [f.tick for f in frames] == [f.tick for f in direct_frames]
    for wire, direct in zip(frames, direct_frames):
        assert wire.sim_time_s == direct.sim_time_s
        for a, b in zip(wire.poses, direct.poses):  # float32 on the wire
            assert (a.position.x, a.position.y, a.position.z) == pytest.approx((b.position.x, b.position.y, b.position.z), abs=1e-6)
    assert ended.end.trajectory.hash == direct_end.end.trajectory.hash
    assert started.definition_hash == project_hash(hub.documents["tower"].project)


def test_simulate_stream_paced_slower_than_real_time_over_the_protocol_keeps_ticks_times_and_poses():
    """A0-05 (D6) over the wire: `speed` 0.5 (the core holds each frame until twice its simulated time has passed on
    the wall clock, slower than real time) and `speed` 0 (as fast as it goes) give the same frames and hash."""
    hub = Hub({"tower": tower()})
    started_at = time.perf_counter()
    slow = asyncio.run(_session(hub, {"type": "run", "id": "slow", "duration_s": 0.2, "speed": 0.5}, until=_ended()))
    slow_wall = time.perf_counter() - started_at
    fast = asyncio.run(_session(hub, {"type": "run", "id": "fast", "duration_s": 0.2, "speed": 0}, until=_ended()))
    _, slow_frames, slow_end = _stream(slow)
    _, fast_frames, fast_end = _stream(fast)
    assert slow_wall >= 0.2 / 0.5  # the last frame (0.2 s of simulated time) went out no earlier than 0.4 s
    assert [(f.tick, f.sim_time_s, f.poses) for f in slow_frames] == [(f.tick, f.sim_time_s, f.poses) for f in fast_frames]
    assert slow_end.end.trajectory.hash == fast_end.end.trajectory.hash


def test_simulate_stream_refusals_carry_reasons():
    incomplete = Hub({"tower": tower(material="no-such-material")})
    received = asyncio.run(
        _session(incomplete, {"type": "run", "id": "r", "duration_s": 0.1}, until=lambda r: any(m.type == "rejected" for m in r))
    )
    rejected = next(m for m in received if m.type == "rejected")
    assert rejected.id == "r" and rejected.reasons[0].code is ReasonCode.MISSING_DEFINITION
    assert not any(isinstance(m, RunStarted) for m in received)

    hub = Hub({"tower": tower()})
    received = asyncio.run(
        _session(
            hub,
            {"type": "run", "id": "first", "duration_s": 0.2, "speed": 0.5},
            {"type": "run", "id": "second", "duration_s": 0.1},
            {"type": "run", "id": "bad", "duration_s": -1},
            until=lambda r: sum(m.type == "rejected" for m in r) >= 2 and _ended()(r),
        )
    )
    reasons = {m.id: m.reasons[0] for m in received if m.type == "rejected"}
    assert reasons["second"].code is ReasonCode.INVALID_COMMAND and "one run at a time" in reasons["second"].message
    assert reasons["bad"].code is ReasonCode.INVALID_COMMAND
    started, frames, ended = _stream(received)
    assert started.run_id == "first"
    check_run(started, frames, ended)


def test_simulate_stream_platform_tag_names_the_locked_engine_wheel_and_the_commit():
    assert _wheel_tags("mujoco_core-4.0.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl") == {
        "cp312-cp312-manylinux_2_27_x86_64",
        "cp312-cp312-manylinux_2_28_x86_64",
    }
    tag = run_of(tower()).started.platform
    lock = (Path(__file__).resolve().parents[3] / "uv.lock").read_text(encoding="utf-8")
    assert f'hash = "{tag.engine.artifact_hash}"' in lock  # the hash of a wheel file uv.lock pins
    assert len(tag.core_build.commit) in (40, 64)
