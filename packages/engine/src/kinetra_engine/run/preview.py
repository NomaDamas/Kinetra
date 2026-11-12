"""Compile a project and run it once (X-02a): the run stream of `client-adapter.md` 3.3, produced by the engine.

    compile_project(project, cache=None, ground_friction=None, timestep_s=None) -> CompiledModel
    PreviewRun(project, run_id=..., project_id=..., revision=..., duration_s=..., seed=0, timestep_s=None) -> iterate: Frame ..., RunEnded
    PreviewRun(..., kind=RunKind.VERDICT_SAMPLE, ground_friction=μ, assumption_values=values)  # one verdict sample (J-01a/#571)

Port of the legacy live run (`legacy-v0`, `packages/engine/src/kinetra_engine/live.py`): the model is compiled from the
document as it is, and every frame is produced by stepping the engine (`mj_step1`/`mj_step2`) while the stream is read. Nothing is a
replay of a stored file. For a verdict sample, `assumption_values` replaces every bound target in an ephemeral validated
copy through `apply_assumption_values`; the base project and its `definition_hash` still identify the run. Ordinary previews
leave the project unchanged and need no such mapping.

**Gate (C-06).** `compile_project` calls `require_complete(project, compile)` and `PreviewRun` calls
`require_complete(project, run)` before anything else: a project with a missing definition is refused
(`ProjectIncomplete`), never run with a part left out.

**Stream.** `PreviewRun.started` is the `run_started`; iterating the run steps the engine and yields the frames, then
the `run_ended`. Tick 0 (the saved pose) is the first frame; then every `frame_every_ticks` ticks; and always a frame at
the end tick (the end frame rule of 3.3), also when it falls between two intervals. Every frame passes `check_frame`
before it is yielded. A body's pose is the world pose of its frame, which is the frame of its smallest-id instance
(`bodytree.py`); the client places the other instances of a welded body by their saved poses relative to it.

**Time (F2).** A public tick is `timestep_s`; a break-enabled run divides each tick into the fixed 16 internal steps chosen
at construction, while other runs use one step. Frames, events and the trajectory hash retain public-tick semantics.
Iterating does not look at the wall clock: how fast the frames are read (a slow core, a slow client, the `speed` of the
transport) cannot change a pose or a time. The trajectory is a function of the compiled model and the number of ticks
only (`client-adapter.md` 4.1). The public time step is MuJoCo's default 0.002 s (`MAX_TIMESTEP_S`) unless the run is
given a smaller `timestep_s`; both it and the internal step count are fixed for the whole run (X-10 compares breaks at
the public time step, half and a quarter of it; no option changes either during a run).

**End.** `completed` at the first tick at or after `duration_s`. `failed` when the engine finds a non-finite position,
velocity or acceleration (it then resets its state, so the run cannot go on): the end frame is the last finite tick,
which the run kept, and there is no trajectory hash. The trajectory hash of a completed run is SHA-256 over the
float64 generalized positions of every tick from 0 to the end, in order, tagged with the run's platform tag (H1). It
is a hash of this run's stream, kept by the core (F7); two records are compared (match, mismatch, not comparable) by
`kinetra_core.compare_trajectories` (X-02d).

**Model labels.** The model labels of the compile (`model_labels`: the proxy approximations, the contact labels of
X-01e — the friction rule, slow slip, no rolling friction, tread and default friction per instance — and `근사: 집중 항력`
where the planet has air, W-03b), and what the compiled model does not apply of the planet, read from the model itself so a label goes away once a leaf sets it: the planet's gravity
when the model's gravity differs from the planet's `data/bodies` value (W-03a sets it, so this label does not appear
today), and the ground when the model has none (X-01e compiles it, so this label does not appear today either). Last,
`BREAK_LABEL` when a joint has a `break_threshold` (X-04b: a break compares one force against one threshold).

**Drives (X-01b), thrust (X-01c) and drag (W-03b).** The model is compiled from `compile_thrust` (the body tree with its
thrusters and the propellant of its tanks), `compile_drives` (springs on sliders, one motor per motor actuator) and
`compile_drag` (one lumped drag area per body). This run owns the step loop. Every tick: a `DriveRuntime` writes the motors'
torque from the project's control schedule (the command of an actuator during the step from `t = (tick - 1) * timestep_s` is
the `command` of its schedule entry with `start <= t < end`; a schedule has at most one such entry per actuator,
`DesignSpec`; else 0) and drains their batteries, and `ThrustRun.begin_step` draws the propellant, puts the step's mass on
the bodies and adds the thrust into `xfrc_applied`. Then the step is `mj_step1` (this step's positions and velocities),
`DragRuntime.apply` (adds each body's drag into `xfrc_applied`), `mj_step2`, `DragRuntime.restore` (puts back the rows it
touched). Last, `ThrustRun.end_step` restores the rows thrust used and puts the mass left on the bodies. On the Moon the air
density is 0, drag touches nothing, and the trajectory is bit for bit the one of `mj_step`.

**Breaks (X-04b, X-10).** Right after `mj_step2` (before `DragRuntime.restore` and `ThrustRun.end_step`, so the step's applied
forces and masses are still there) a `BreakWatch` reads the force on every joint that has a `break_threshold` and compares
its mean over the last `BREAK_LOAD_WINDOW` (0.02 s, `kinetra_core.break_window`) with the threshold (`compiler/breaks.py`).
The joints over their threshold are released in joint id order: the tree loses them (`release`),
the model is compiled again from it with the drives of the joints left, and the state of the tick is carried into it
(`carry_state`); the motors, the tanks, the drag and the frames follow the new model by name. Each released
joint is a `break` event of that tick (`reason` `over_threshold`, `joint`, `load`, `threshold`, in N), carried by the next
frame (the frame of the tick itself when one is sent there). After a break the trajectory hash goes on over the new model's
generalized positions.

**Separations (X-08).** Before the step from `t = (tick - 1) * timestep_s`, every schedule `separate` entry with `at <= t` not
run yet, then every manual request (`PreviewRun.separate`, made between two frames), releases its separator's `face_b` joint
by the same path as a break (`release`, compile again, `carry_state`, the runtimes follow), and `push_apart` gives the two
sides the declared impulse (`compiler/separation.py`). Each is a `separation` event of that tick (`reason`
`intended_separation`, `separator`, `joint`, `entry` or `None` for a manual one, `impulse` in N*s), never a `break`. A
separator is let go of once: a second request is refused (`separate`) or, for a schedule entry after a manual request, does
nothing; a separator whose joint broke before its time has nothing left to release and gives no event. The side that came
away keeps running in the same world to the end, with its thrusters and motors on their own schedule entries.
A released body is a free body of the run until the end tick (X-13): no rule removes a piece or takes it out of the
physics by distance, count or time, every frame carries its pose, and the hash covers its free joint.

**Contacts (#562).** A `ContactWatch` (`contacts.py`, which states the threshold, the dedupe and the order) reads the
contacts of the pose at tick 0 and after every tick (after the break or separation of that tick, on the model the tick ends
with) and adds a `contact` `begin`/`end` event for every body–ground, body–prop and body–body pair whose touching changed;
the frame of that tick or the next carries them, after the tick's `break` or `separation` events. After a release the watch
is bound to the model compiled again and goes on by name. Met conditions are not in the stream yet; their leaf adds them.
While a joint can still break, a `TimestepSensitivity` checks the run against the measured speed, mass-ratio and
spring limits and checks each break for time-step-dependent threshold overshoot; out of those bounds, `run_ended.labels`
carries "시간 간격 민감: 파단 결과가 약한 증거" with the reasons (`docs/research/engine/break-timestep.md`).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator, Mapping
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
    apply_assumption_values,
    check_frame,
    project_hash,
    require_complete,
)
from kinetra_core.bodies import load_body
from kinetra_core.break_window import BREAK_LOAD_WINDOW, MAX_TIMESTEP_S
from kinetra_core.frames import MAX_TICK

from ..compiler import (
    BREAK_LABEL,
    BREAK_SUBSTEPS_PER_TICK,
    SEPARATION_LABEL,
    BodyTree,
    BreakWatch,
    Drag,
    DragRuntime,
    DriveRuntime,
    Drives,
    SeparationSchedule,
    ThrustModel,
    ThrustRun,
    TimestepSensitivity,
    breakable_joints,
    carry_state,
    compile_drag,
    compile_drives,
    compile_thrust,
    model_labels,
    push_apart,
    release,
    separator_joints,
    to_mjcf,
)
from ..parts import PartCache
from .contacts import ContactWatch
from .platform_tag import platform_tag

FRAME_RATE_CEILING_HZ = 60.0
"""The default frame rate of a live preview is at most this many frames per simulated second. It is the one display
rate A0-02a measured (`spikes/web-client/REPORT.md`, 60 Hz, 16.7 ms), and `client-adapter.md` 3.3 asks the default to
stay at or below what the client can draw. Value badge `기본값`: a choice, not a measurement of this core."""

_UNSTABLE = (mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC)


@dataclass(frozen=True)
class CompiledModel:
    """A project compiled for the engine: its body tree, its thrusters and tanks, its springs and motors, its drag, the MJCF
    text (an artifact, never saved or sent: 2절) and the loaded model (dry masses; a run puts the propellant on)."""

    tree: BodyTree
    thrust: ThrustModel
    drives: Drives
    drag: Drag
    mjcf: str
    model: mujoco.MjModel


def compile_project(
    project: Project,
    cache: PartCache | None = None,
    ground_friction: float | None = None,
    timestep_s: float | None = None,
) -> CompiledModel:
    """Compile `project`, the ground at `ground_friction` (default the planet's nominal; a Monte Carlo sample of the planet's
    `ground_friction` distribution, W-03c, J-01a), with the actual integrator step `timestep_s` [s] (`None`: MuJoCo's
    default, `MAX_TIMESTEP_S`; else above 0 and at most that). Raises `ProjectIncomplete` for a missing definition,
    `ValueError` for a time step out of range and `CompileError` (with its `CompileErrorCode`) for a refused design."""
    require_complete(project, BlockedOperation.COMPILE)
    if timestep_s is not None and not 0.0 < timestep_s <= MAX_TIMESTEP_S:
        raise ValueError(f"time step {timestep_s} s: a run's time step is above 0 and at most {MAX_TIMESTEP_S} s")
    thrust = compile_thrust(project, cache)  # build_body_tree, with the thrusters and the tanks' propellant
    tree = thrust.tree
    drives = compile_drives(tree)
    mjcf = to_mjcf(tree, drives=drives, ground_friction=ground_friction, timestep_s=timestep_s)
    return CompiledModel(tree, thrust, drives, compile_drag(tree), mjcf, mujoco.MjModel.from_xml_string(mjcf))


def commands_at(design: DesignSpec, t: float) -> dict[str, float]:
    """The command of every actuator that has a schedule entry covering simulated time `t` (`start <= t < end`)."""
    return {e.actuator: e.command for e in design.schedule.actuations if e.start <= t < e.end}


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
        ground_friction: float | None = None,
        assumption_values: Mapping[str, float] | None = None,
        timestep_s: float | None = None,
    ):
        require_complete(project, BlockedOperation.RUN)
        timestep_s = MAX_TIMESTEP_S if timestep_s is None else timestep_s
        if not 0.0 < timestep_s <= MAX_TIMESTEP_S:
            raise ValueError(f"time step {timestep_s} s: a run's public time step is above 0 and at most {MAX_TIMESTEP_S} s")
        # The run belongs to the base project revision; bound samples change only its ephemeral compile input, just as
        # the ground-friction override does. Recompiles after a break keep the resulting body tree and sampled values.
        compile_input = project if assumption_values is None else apply_assumption_values(project, assumption_values)
        has_breaks = any(j.break_threshold is not None for j in compile_input.design.joints)
        self._substeps = BREAK_SUBSTEPS_PER_TICK if has_breaks else 1
        self._timestep_s = timestep_s / self._substeps  # actual integrator dt, also used when a release recompiles
        compiled = compile_project(compile_input, cache, ground_friction, self._timestep_s)
        self._ground_friction = ground_friction
        self.compiled = compiled
        model = compiled.model
        self._model = model
        self.end_tick = end_tick(duration_s, timestep_s)
        tag = platform_tag(model, substeps_per_tick=self._substeps)
        bodies = compiled.tree.bodies
        self._body_ids = [b.id for b in bodies]
        self._follow(model)
        breakable = [BREAK_LABEL] if breakable_joints(compiled.tree) else []
        self._separators = separator_joints(compiled.tree.design)
        separable = [SEPARATION_LABEL] if self._separators else []
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
                "model_labels": [label.text for label in model_labels(compiled.tree)]
                + list(environment_labels(project, model))
                + breakable
                + separable,
                "platform": tag,
            }
        )
        self._iterated = False
        self._events: list[dict] = []  # events since the last frame made; the next frame carries them
        self._requested: list[str] = []  # manual separations asked since the last step (`separate`)
        self._separated: set[str] = set()  # separators let go of (or asked to) during the run: never again

    @property
    def separators(self) -> tuple[str, ...]:
        """The separator instances this run can separate (each holds a part at its `face_b`), in instance id order."""
        return tuple(self._separators)

    def separate(self, separator: str) -> None:
        """Manual control (`client-adapter.md` I5): separate `separator` at the start of the next step, by the same path as a
        schedule entry (the event's `entry` is `None`). Between two frames of the iteration, this is the step right after the
        last frame read. Raises `ValueError` for an instance that is not one of `separators`, and for one already separated
        or asked to: a separation cannot be undone."""
        if separator not in self._separators:
            raise ValueError(f"{separator!r} is not a separator holding a part at its face_b; the run's separators are {list(self._separators)}")
        if separator in self._separated or separator in self._requested:
            raise ValueError(f"separator {separator!r} is separated already: a separation cannot be undone")
        self._requested.append(separator)

    def _follow(self, model: mujoco.MjModel) -> None:
        """Read the frames' poses from `model` (the compiled one, or the one compiled again after a break)."""
        self._model = model
        self._rows = np.array([mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b) for b in self._body_ids])

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
            {
                "type": "frame",
                "run_id": self.started.run_id,
                "tick": tick,
                "sim_time_s": tick * self.started.timestep_s,
                "poses": poses,
                "events": self._events,
            }
        )
        self._events = []
        return frame

    def __iter__(self) -> Iterator[Frame | RunEnded]:
        if self._iterated:
            raise RuntimeError("a run is iterated once")
        self._iterated = True
        model, run, every = self._model, self.started, self.started.frame_every_ticks
        data = mujoco.MjData(model)
        tree, drive_spec = self.compiled.tree, self.compiled.drives
        drives = DriveRuntime(model, drive_spec)
        thrust = ThrustRun(self.compiled.thrust, model, data)  # puts the tanks' propellant on their bodies
        drag = DragRuntime(model, self.compiled.drag)
        watch = BreakWatch(tree, model, BREAK_LOAD_WINDOW.value.value)
        sensitivity = TimestepSensitivity(model, public_timestep_s=run.timestep_s) if watch.joints else None  # conservative pre-substep spring bound
        schedule = SeparationSchedule(tree.design)
        contacts = ContactWatch(model)
        design, dt = tree.design, run.timestep_s

        def released(joints: list[str]) -> None:
            """X-04b's release: `joints` leave the tree, the model is compiled again, the state is carried over and every
            runtime follows the new model by name."""
            nonlocal tree, drive_spec, model, data, drag
            tree, drive_spec = release(tree, joints), drive_spec.without_joints(joints)
            new_model = mujoco.MjModel.from_xml_string(
                to_mjcf(tree, drives=drive_spec, ground_friction=self._ground_friction, timestep_s=self._timestep_s)
            )
            data = carry_state(model, data, new_model)
            model = new_model
            drives.rebind(model, drive_spec)
            thrust.rebind(model, data)
            drag = DragRuntime(model, self.compiled.drag)  # holds nothing between steps: the same bodies, found by name
            watch.bind(tree, model)
            contacts.bind(model)
            self._follow(model)

        trajectory = hashlib.sha256(data.qpos.tobytes())
        last_good = data.qpos.copy()
        self._events.extend(contacts.events(model, data, 0))
        frame = self._frame(data, 0)
        check_frame(run, frame, final=self.end_tick == 0)
        yield frame
        sent = 0
        for tick in range(1, self.end_tick + 1):
            asked = [(e.separator, e.id) for e in schedule.due((tick - 1) * dt)] + [(s, None) for s in self._requested]
            self._requested.clear()
            held = {b.joint.id for b in tree.bodies if b.joint is not None}
            going = []
            for separator, entry in asked:
                if separator in self._separated:
                    continue  # apart already (a manual request before its entry, or the other way round): irreversible
                self._separated.add(separator)
                sep = self._separators[separator]
                if sep.joint in held:  # else a break released it first: nothing left to release or push
                    going.append((sep, entry))
            if going:
                released([sep.joint for sep, _ in going])
                for sep, entry in going:
                    push_apart(model, data, tree, sep)
                    self._events.append(
                        {
                            "kind": "separation",
                            "tick": tick,
                            "reason": "intended_separation",
                            "separator": sep.separator,
                            "joint": sep.joint,
                            "entry": entry,
                            "impulse": {"value": sep.impulse, "unit": "N*s"},
                        }
                    )
                last_good = data.qpos.copy()  # the new model's coordinates
            np.copyto(last_good, data.qpos)
            checkpoint = None
            if self._substeps > 1:
                saved_data = mujoco.MjData(model)
                mujoco.mj_copyData(saved_data, model, data)
                mass_state = {name: getattr(model, name).copy() for name in ("body_mass", "body_ipos", "body_inertia", "body_iquat")}
                checkpoint = (
                    model, tree, drive_spec, saved_data, dict(drives.supplies), dict(drives.energy), dict(thrust.supplies),
                    mass_state, dict(sensitivity._found) if sensitivity is not None else {}, len(self._events)
                )
            for substep in range(self._substeps):
                step_time = ((tick - 1) * self._substeps + substep) * self._timestep_s
                drives.apply(data, commands_at(design, step_time), self._timestep_s)
                thrust.begin_step(step_time)
                mujoco.mj_step1(model, data)
                drag.apply(data)
                mujoco.mj_step2(model, data)
                over = watch.over(model, data)  # actual force of this internal step, with its applied forces and masses
                if sensitivity is not None and watch.joints:
                    sensitivity.observe(model, data)
                drag.restore(data)
                thrust.end_step()
                if any(data.warning[w].number for w in _UNSTABLE) or not np.isfinite(data.qpos).all():
                    good = tick - 1
                    if checkpoint is not None:
                        model, tree, drive_spec, data, drive_supplies, drive_energy, thrust_supplies, mass_state, sensitivity_found, event_count = checkpoint
                        drives = DriveRuntime(model, drive_spec, supplies=drive_supplies)
                        drives.energy = drive_energy
                        thrust = ThrustRun(self.compiled.thrust, model, data)
                        thrust.supplies = thrust_supplies
                        thrust.rebind(model, data)
                        for name, values in mass_state.items():  # exact boundary mass, COM and inertia, not a fresh full-tank load
                            getattr(model, name)[:] = values
                        watch.bind(tree, model)
                        contacts.bind(model)
                        self._follow(model)
                        if sensitivity is not None:
                            sensitivity._found = sensitivity_found
                        del self._events[event_count:]  # a partial tick's releases were not completed public events
                    elif good != sent:
                        data.qpos[:] = last_good
                    if good != sent:
                        frame = self._frame(data, good)
                        check_frame(run, frame, final=True)
                        yield frame
                    yield RunEnded.model_validate({"type": "run_ended", "run_id": run.run_id, "last_tick": good, "end": {"reason": "failed"}, "labels": self._labels(sensitivity)})
                    return
                if over:
                    if sensitivity is not None:
                        sensitivity.observe_breaks(over)
                    broken = [o.joint for o in over]
                    released(broken)
                    last_good = data.qpos.copy()  # the new model's coordinates
                    self._events.extend(
                        {
                            "kind": "break",
                            "tick": tick,
                            "reason": "over_threshold",
                            "joint": o.joint,
                            "load": {"value": o.load, "unit": "N"},
                            "threshold": {"value": o.threshold, "unit": "N"},
                        }
                        for o in over
                    )
            self._events.extend(contacts.events(model, data, tick))
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
                "labels": self._labels(sensitivity),
            }
        )

    @staticmethod
    def _labels(sensitivity: TimestepSensitivity | None) -> list[str]:
        label = None if sensitivity is None else sensitivity.label()
        return [] if label is None else [label]
