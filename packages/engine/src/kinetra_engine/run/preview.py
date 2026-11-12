"""Compile a project and run it once (X-02a): the run stream of `client-adapter.md` 3.3, produced by the engine.

    compile_project(project, cache=None) -> CompiledModel
    PreviewRun(project, run_id=..., project_id=..., revision=..., duration_s=..., seed=0) -> iterate: Frame ..., RunEnded

Port of the legacy live run (`legacy-v0`, `packages/engine/src/kinetra_engine/live.py`): the model is compiled from the
document as it is, and every frame is produced by stepping the engine (`mj_step`) while the stream is read. Nothing is a
replay of a stored file.

**Gate (C-06).** `compile_project` calls `require_complete(project, compile)` and `PreviewRun` calls
`require_complete(project, run)` before anything else: a project with a missing definition is refused
(`ProjectIncomplete`), never run with a part left out.

**Stream.** `PreviewRun.started` is the `run_started`; iterating the run steps the engine and yields the frames, then
the `run_ended`. Tick 0 (the saved pose) is the first frame; then every `frame_every_ticks` ticks; and always a frame at
the end tick (the end frame rule of 3.3), also when it falls between two intervals. Every frame passes `check_frame`
before it is yielded. A body's pose is the world pose of its frame, which is the frame of its smallest-id instance
(`bodytree.py`); the client places the other instances of a welded body by their saved poses relative to it.

**Time (F2).** A tick is one `mj_step` of `timestep_s`. Iterating does not look at the wall clock: how fast the frames
are read (a slow core, a slow client, the `speed` of the transport) cannot change a pose or a time. The trajectory is a
function of the compiled model and the number of ticks only (`client-adapter.md` 4.1).

**End.** `completed` at the first tick at or after `duration_s`. `failed` when the engine finds a non-finite position,
velocity or acceleration (it then resets its state, so the run cannot go on): the end frame is the last finite tick,
which the run kept, and there is no trajectory hash. The trajectory hash of a completed run is SHA-256 over the
float64 generalized positions of every tick from 0 to the end, in order, tagged with the run's platform tag (H1). It
is a hash of this run's stream, kept by the core (F7); two records are compared (match, mismatch, not comparable) by
`kinetra_core.compare_trajectories` (X-02d).

**Model labels.** The proxy approximation labels of the compile (`proxy_labels`), the contact labels (`contact_labels`, X-01e:
the friction rule, slow slip, no rolling friction, tread and default friction per instance), and what the compiled model
does not apply of the planet, read from the model itself so a label goes away once a leaf sets it: the planet's gravity
when the model's gravity differs from the planet's `data/bodies` value (W-03a sets it, so this label does not appear
today), and the ground when the model has none (X-01e compiles it, so this label does not appear today either).

**Drives (X-01b) and thrust (X-01c).** The model is compiled from `compile_thrust` (the body tree with its thrusters and the
propellant of its tanks) and `compile_drives` (springs on sliders, one motor per motor actuator). This run owns the step
loop. Every tick, before `mj_step`: a `DriveRuntime` writes the motors' torque from the project's control schedule (the
command of an actuator during the step from `t = (tick - 1) * timestep_s` is the `command` of its schedule entry with
`start <= t < end`; a schedule has at most one such entry per actuator, `DesignSpec`; else 0) and drains their batteries,
and `ThrustRun.begin_step` draws the propellant, puts the step's mass on the bodies and adds the thrust into
`xfrc_applied`. After `mj_step`, `ThrustRun.end_step` restores the `xfrc_applied` rows it used and puts the mass left on
the bodies. Another force source (drag, W-03b) adds into the same rows the same way, between those two calls.

**Events.** The stream carries no events yet: contacts, breaks (X-04b) and met conditions are added by their leaves.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator
from dataclasses import dataclass

import mujoco
import numpy as np

from kinetra_core import (
    BlockedOperation,
    DesignSpec,
    Frame,
    Project,
    RunEnded,
    RunKind,
    RunStarted,
    check_frame,
    project_hash,
    require_complete,
)
from kinetra_core.bodies import load_body
from kinetra_core.frames import MAX_TICK

from ..compiler import (
    BodyTree,
    DriveRuntime,
    Drives,
    ThrustModel,
    ThrustRun,
    compile_drives,
    compile_thrust,
    contact_friction,
    contact_labels,
    proxy_labels,
    to_mjcf,
)
from ..parts import PartCache
from .platform_tag import platform_tag

FRAME_RATE_CEILING_HZ = 60.0
"""The default frame rate of a live preview is at most this many frames per simulated second. It is the one display
rate A0-02a measured (`spikes/web-client/REPORT.md`, 60 Hz, 16.7 ms), and `client-adapter.md` 3.3 asks the default to
stay at or below what the client can draw. Value badge `기본값`: a choice, not a measurement of this core."""

_UNSTABLE = (mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC)


@dataclass(frozen=True)
class CompiledModel:
    """A project compiled for the engine: its body tree, its thrusters and tanks, its springs and motors, the MJCF text
    (an artifact, never saved or sent: 2절) and the loaded model (dry masses; a run puts the propellant on)."""

    tree: BodyTree
    thrust: ThrustModel
    drives: Drives
    mjcf: str
    model: mujoco.MjModel


def compile_project(project: Project, cache: PartCache | None = None) -> CompiledModel:
    """Compile `project`. Raises `ProjectIncomplete` for a missing definition and `CompileError` (with its
    `CompileErrorCode`) for a design the compiler refuses."""
    require_complete(project, BlockedOperation.COMPILE)
    thrust = compile_thrust(project, cache)  # build_body_tree, with the thrusters and the tanks' propellant
    tree = thrust.tree
    drives = compile_drives(tree)
    mjcf = to_mjcf(tree, drives=drives)
    return CompiledModel(tree, thrust, drives, mjcf, mujoco.MjModel.from_xml_string(mjcf))


def commands_at(design: DesignSpec, t: float) -> dict[str, float]:
    """The command of every actuator that has a schedule entry covering simulated time `t` (`start <= t < end`)."""
    return {e.actuator: e.command for e in design.schedule.entries if e.start <= t < e.end}


def default_frame_every_ticks(timestep_s: float) -> int:
    """The fewest ticks per frame that keep the frame rate at or under `FRAME_RATE_CEILING_HZ` (at the engine's default
    `timestep_s` 0.002 s: 9 ticks, 55.6 frames per simulated second)."""
    return max(1, math.ceil(1.0 / (timestep_s * FRAME_RATE_CEILING_HZ) - 1e-9))


def end_tick(duration_s: float, timestep_s: float) -> int:
    """The first tick whose time `tick * timestep_s` is at or after `duration_s`. Raises `ValueError` when that is more
    than `MAX_TICK` ticks; the cap is checked on the float quotient first, so a huge finite duration (whose quotient
    is `inf`) is refused instead of overflowing."""
    ticks = duration_s / timestep_s
    if not ticks <= MAX_TICK:
        raise ValueError(f"{duration_s} s is more than {MAX_TICK} ticks of {timestep_s} s, the most a run has")
    tick = max(1, math.ceil(ticks))
    while tick > 1 and (tick - 1) * timestep_s >= duration_s:
        tick -= 1
    while tick * timestep_s < duration_s:
        tick += 1
    if tick > MAX_TICK:
        raise ValueError(f"{duration_s} s is {tick} ticks of {timestep_s} s; a run has at most {MAX_TICK}")
    return tick


def environment_labels(project: Project, model: mujoco.MjModel) -> tuple[str, ...]:
    """What the run does not apply of the project's planet (its gravity, its ground), as `model_labels` sentences."""
    labels = []
    planet = load_body(project.world.planet)
    g_model = float(np.linalg.norm(model.opt.gravity))
    g_planet = planet.gravity.value
    if not math.isclose(g_model, g_planet, rel_tol=1e-9):
        labels.append(
            f"미적용: {planet.name}의 중력 {g_planet:g} m/s²가 아니라 엔진 기본 중력 {g_model:g} m/s²로 실행"
        )
    if not any(model.geom_bodyid[g] == 0 for g in range(model.ngeom)):
        labels.append("미적용: 지면 없음. 몸체는 아무것에도 닿지 않고 떨어진다")
    return tuple(labels)


class PreviewRun:
    """One run of a project. Construct, send `started`, then iterate: the frames, then the `RunEnded`. Iterate once."""

    def __init__(
        self,
        project: Project,
        *,
        run_id: str,
        project_id: str,
        revision: int,
        duration_s: float,
        seed: int = 0,
        kind: RunKind = RunKind.PREVIEW,
        frame_every_ticks: int | None = None,
        cache: PartCache | None = None,
    ):
        require_complete(project, BlockedOperation.RUN)
        compiled = compile_project(project, cache)
        self.compiled = compiled
        model = compiled.model
        self._model = model
        timestep_s = float(model.opt.timestep)
        self.end_tick = end_tick(duration_s, timestep_s)
        tag = platform_tag(model)
        bodies = compiled.tree.bodies
        self._body_ids = [b.id for b in bodies]
        self._rows = np.array([mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b.id) for b in bodies])
        self.started = RunStarted.model_validate(
            {
                "type": "run_started",
                "run_id": run_id,
                "kind": kind,
                "badge": "sim",
                "project_id": project_id,
                "revision": revision,
                "definition_hash": project_hash(project),
                "planet": project.world.planet,
                "seed": seed,
                "timestep_s": timestep_s,
                "frame_every_ticks": frame_every_ticks or default_frame_every_ticks(timestep_s),
                "bodies": [{"id": b.id, "instances": list(b.instances)} for b in bodies],
                "model_labels": [label.text for label in proxy_labels(compiled.tree)]
                + [label.text for label in contact_labels(contact_friction(compiled.tree))]
                + list(environment_labels(project, model)),
                "platform": tag,
            }
        )
        self._iterated = False

    def _frame(self, data: mujoco.MjData, tick: int) -> Frame:
        mujoco.mj_kinematics(self._model, data)  # poses of this tick's positions; the next mj_step recomputes everything
        poses = [
            {
                "body": body,
                "position": {"x": float(p[0]), "y": float(p[1]), "z": float(p[2])},
                "orientation": {"x": float(q[1]), "y": float(q[2]), "z": float(q[3]), "w": float(q[0])},
            }
            for body, p, q in zip(self._body_ids, data.xpos[self._rows], data.xquat[self._rows])
        ]
        frame = Frame.model_validate(
            {"type": "frame", "run_id": self.started.run_id, "tick": tick, "sim_time_s": tick * self.started.timestep_s, "poses": poses}
        )
        return frame

    def __iter__(self) -> Iterator[Frame | RunEnded]:
        if self._iterated:
            raise RuntimeError("a run is iterated once")
        self._iterated = True
        model, run, every = self._model, self.started, self.started.frame_every_ticks
        data = mujoco.MjData(model)
        drives = DriveRuntime(model, self.compiled.drives)
        thrust = ThrustRun(self.compiled.thrust, model, data)  # puts the tanks' propellant on their bodies
        design, dt = self.compiled.tree.design, run.timestep_s
        trajectory = hashlib.sha256(data.qpos.tobytes())
        last_good = data.qpos.copy()
        frame = self._frame(data, 0)
        check_frame(run, frame, final=self.end_tick == 0)
        yield frame
        sent = 0
        for tick in range(1, self.end_tick + 1):
            np.copyto(last_good, data.qpos)
            drives.apply(data, commands_at(design, (tick - 1) * dt), dt)
            thrust.begin_step()
            mujoco.mj_step(model, data)
            thrust.end_step()
            if any(data.warning[w].number for w in _UNSTABLE) or not np.isfinite(data.qpos).all():
                good = tick - 1
                if good != sent:
                    data.qpos[:] = last_good
                    frame = self._frame(data, good)
                    check_frame(run, frame, final=True)
                    yield frame
                yield RunEnded.model_validate({"type": "run_ended", "run_id": run.run_id, "last_tick": good, "end": {"reason": "failed"}})
                return
            trajectory.update(data.qpos.tobytes())
            final = tick == self.end_tick
            if final or tick % every == 0:
                frame = self._frame(data, tick)
                check_frame(run, frame, final=final)
                sent = tick
                yield frame
        yield RunEnded.model_validate(
            {
                "type": "run_ended",
                "run_id": run.run_id,
                "last_tick": self.end_tick,
                "end": {"reason": "completed", "trajectory": {"hash": "sha256:" + trajectory.hexdigest(), "platform": run.platform}},
            }
        )
