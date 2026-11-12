"""Breakable joints during a run (X-04b, X-10): read the load on every joint that has a `break_threshold`, release the ones over it.

    watch = BreakWatch(tree, model, window_s)   # the tree's joints with a threshold, bound to a loaded model
    over = watch.over(model, data)           # right after mj_step: the joints whose load is over their threshold
    tree = release(tree, [b.joint for b in over])        # those joints' child bodies become free bodies
    data = carry_state(old_model, old_data, new_model)   # the same poses and velocities in the model of the new tree
    sensitivity = TimestepSensitivity(model)  # what puts the run where the window does not make breaks time-step invariant

**Load.** The force a joint transmits in one step is the force part of MuJoCo's `cfrc_int` of its child body (the spatial
force a body receives from its parent, computed by `mj_rnePostConstraint` from the step's accelerations, contact and applied
forces): everything the joint transmits to the subtree it holds, along and across its axis; the torque is not compared (a
threshold is a force in N, `break-threshold.md`). A joint's **load** [N] is the magnitude of the mean of that force vector
over the last `window_s` seconds of simulated time (X-10): the impulse the joint transmitted in the window divided by the
window. One step's force depends on the time step, most of all in a collision; the impulse over a fixed time does much less
(`docs/research/engine/break-timestep.md`). The window counts whole steps and, when the time step does not divide it, the
fitting part of one more; before the run's start the force is 0. The window must be longer than the time step
(`kinetra_core.break_window`: 0.02 s against at most 0.002 s). A joint breaks at the first tick where its load is **over** its
threshold (`load > threshold`); the load in the event is that tick's load. A breakable `fixed` joint is a body held rigidly to
its parent without a degree of freedom (`bodytree.py`), so the same `cfrc_int` reads it.

**Release.** A broken joint's child body (with the bodies hung from it) becomes a free body: in the tree its parent and joint
go (`release`); the model is compiled again from that tree, and `carry_state` gives the new data every body's pose and
velocity of the tick of the break (joints the two models share keep their coordinate and speed by name; a released body's
new free joint takes the body frame's world pose and velocity). Nothing jumps: the frame of that tick is the same either
way. A spring or motor on the broken joint goes with it (`Drives.without_joints`).

**Determinism.** The load is read from the engine's state only, released joints are taken in joint id order, and the new
model is the same text for the same tree, so the same project and the same ticks give the same breaks and the same states.

**Time-step sensitivity (X-10).** With the window, the three reference scenes break the same joints at the time step,
half and a quarter of it and their window loads agree within 10 %. `docs/research/engine/break-timestep.md` measured where
that stops holding; `TimestepSensitivity` checks a run against those numbers (mass ratio, springs and speed at the start and
after every step while a joint can still break, on the model the run is on, also one compiled again after a break) and its
`reasons` are why the run's breaks are weak evidence
(`TIMESTEP_SENSITIVE_LABEL`).

This is a simplified model (plan 4.6, `break-threshold.md`): one scalar force against one scalar threshold. No torque, no
fatigue, no cracks, no FEM.
"""

from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass, replace

import mujoco
import numpy as np

from .bodytree import BodyTree

BREAK_LABEL = "단순화 모델: 결합 파단은 결합을 지나는 힘을 고정된 시간 창으로 평균한 크기 [N]만 임계와 비교한다(토크, 피로, 균열, FEM 없음)"
"""The `model_labels` sentence of a run whose design has a joint with a `break_threshold`."""

TIMESTEP_SENSITIVE_LABEL = "시간 간격 민감: 파단 결과가 약한 증거"
"""The start of the `run_ended.labels` sentence of a run with a breakable joint that `TimestepSensitivity` puts out of range."""

SPEED_LIMIT_M_S = 512.0
"""The fastest body [m/s] at which the measurements kept breaks time-step invariant (`break-timestep.md`: a block dropped on the
ground passed at 512 m/s, 6.7 %, and failed at 1024 m/s, 10.5 %). Value badge `시뮬`, measured on the machine of that table."""

MASS_RATIO_LIMIT = 4096.0
"""The largest ratio of the heaviest to the lightest body at which the measurements passed (`break-timestep.md`: a load on a cart
stopped by a slider limit passed at 4096, 4.0 %, and failed at 32768, 184 %). Value badge `시뮬`."""

SPRING_LIMIT = 0.776
"""The largest omega * time step of a slider spring at which the measurements passed, omega = sqrt(k / mu) with mu the reduced mass
of the two sides (`break-timestep.md`: 0.776 passed, 0.25 %; 0.896 failed, 11.9 %). Value badge `시뮬`."""

_SIZES = {
    mujoco.mjtJoint.mjJNT_FREE: (7, 6),
    mujoco.mjtJoint.mjJNT_BALL: (4, 3),
    mujoco.mjtJoint.mjJNT_SLIDE: (1, 1),
    mujoco.mjtJoint.mjJNT_HINGE: (1, 1),
}


@dataclass(frozen=True)
class BreakableJoint:
    """Joint `joint` with its `break_threshold` [N]; `body` is the tree body it holds (its child side, which comes away)."""

    joint: str
    body: str
    threshold: float


@dataclass(frozen=True)
class OverThreshold:
    """A joint whose load [N] was over its threshold [N] in the step just taken."""

    joint: str
    body: str
    load: float
    threshold: float


def breakable_joints(tree: BodyTree) -> tuple[BreakableJoint, ...]:
    """The joints of `tree` that carry a `break_threshold` and still hold a body, in joint id order."""
    thresholds = {j.id: j.break_threshold.value for j in tree.joints if j.break_threshold is not None}
    found = [BreakableJoint(b.joint.id, b.id, thresholds[b.joint.id]) for b in tree.bodies if b.joint is not None and b.joint.id in thresholds]
    return tuple(sorted(found, key=lambda j: j.joint))


def release(tree: BodyTree, joints: Collection[str]) -> BodyTree:
    """`tree` with `joints` broken: the body each held is a free body at its saved world pose (the pose only seeds the new
    free joint's reference; `carry_state` sets the run's). The bodies keep their order, frames, masses and geoms."""
    gone = set(joints)
    held = {b.joint.id for b in tree.bodies if b.joint is not None}
    missing = sorted(gone - held)
    if missing:
        raise ValueError(f"no body of the tree is held by joint(s) {missing}")
    world = {ci.instance: (ci.position, ci.orientation) for ci in tree.instances}
    bodies = tuple(
        replace(b, parent=None, joint=None, pos=world[b.id][0], quat=world[b.id][1]) if b.joint is not None and b.joint.id in gone else b
        for b in tree.bodies
    )
    return replace(tree, bodies=bodies)


class BreakWatch:
    """The breakable joints of one run, bound to the current model. `over` reads the loads after each `mj_step` and
    compares each joint's mean force over the last `window_s` seconds of simulated time with its threshold."""

    def __init__(self, tree: BodyTree, model: mujoco.MjModel, window_s: float) -> None:
        dt = float(model.opt.timestep)
        if not window_s > dt:
            raise ValueError(f"the load window {window_s} s must be longer than the time step {dt} s")
        steps = window_s / dt
        whole = round(steps) if abs(steps - round(steps)) < 1e-9 else math.floor(steps)
        self.window_s = window_s
        self._weights = np.full(whole + 1, dt / window_s)  # newest first: `whole` whole steps, then the part of one more
        self._weights[whole] = max(0.0, steps - whole) * dt / window_s
        self._history: dict[str, np.ndarray] = {}  # joint id -> the force vectors of its last steps [N], newest first
        self.loads: dict[str, float] = {}  # joint id -> its load [N] (the window mean) after the last `over`
        self.joints: tuple[BreakableJoint, ...] = ()
        self._rows: list[tuple[BreakableJoint, int]] = []
        self.bind(tree, model)

    def bind(self, tree: BodyTree, model: mujoco.MjModel) -> None:
        """Watch the joints of `tree` (after a `release`, the ones left) in `model`, compiled from that tree. A joint that
        was already watched keeps its window: the same joint goes on carrying the same body."""
        self.joints = breakable_joints(tree)
        self._rows = []
        for j in self.joints:
            row = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, j.body)
            if row < 0:
                raise ValueError(f"the MuJoCo model has no body {j.body!r}: it was not compiled from this body tree")
            self._rows.append((j, row))
        kept = {j.joint for j in self.joints}
        self._history = {k: v for k, v in self._history.items() if k in kept}
        self.loads = {k: v for k, v in self.loads.items() if k in kept}
        for j in self.joints:
            self._history.setdefault(j.joint, np.zeros((len(self._weights), 3)))

    def over(self, model: mujoco.MjModel, data: mujoco.MjData) -> tuple[OverThreshold, ...]:
        """Right after `mj_step` (before anything restores `xfrc_applied` or the masses of the step): the joints whose load
        is over their threshold, in joint id order. Call it once per step: each call is one step of the window."""
        if not self._rows:
            return ()
        mujoco.mj_rnePostConstraint(model, data)
        found = []
        for j, row in self._rows:
            h = self._history[j.joint]
            h[1:] = h[:-1]
            h[0] = data.cfrc_int[row, 3:6]
            load = float(np.linalg.norm(self._weights @ h))
            self.loads[j.joint] = load
            if load > j.threshold:
                found.append(OverThreshold(j.joint, j.body, load, j.threshold))
        return tuple(found)


def carry_state(old_model: mujoco.MjModel, old_data: mujoco.MjData, new_model: mujoco.MjModel) -> mujoco.MjData:
    """New data for `new_model` (compiled from a `release` of the tree of `old_model`) in the state of `old_data`: the time,
    every shared joint's coordinate, speed and solver warm start by name, and for each new free joint the world pose and
    velocity of its body's frame in `old_data`. Positions-derived values of `old_data` are recomputed on the way."""
    mujoco.mj_kinematics(old_model, old_data)
    mujoco.mj_comPos(old_model, old_data)
    mujoco.mj_comVel(old_model, old_data)
    data = mujoco.MjData(new_model)
    data.time = old_data.time
    velocity = np.zeros(6)
    for j in range(new_model.njnt):
        name = mujoco.mj_id2name(new_model, mujoco.mjtObj.mjOBJ_JOINT, j)
        nq, nv = _SIZES[mujoco.mjtJoint(new_model.jnt_type[j])]
        qa, va = int(new_model.jnt_qposadr[j]), int(new_model.jnt_dofadr[j])
        k = mujoco.mj_name2id(old_model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if k >= 0:
            oq, ov = int(old_model.jnt_qposadr[k]), int(old_model.jnt_dofadr[k])
            data.qpos[qa : qa + nq] = old_data.qpos[oq : oq + nq]
            data.qvel[va : va + nv] = old_data.qvel[ov : ov + nv]
            data.qacc_warmstart[va : va + nv] = old_data.qacc_warmstart[ov : ov + nv]
            continue
        body = mujoco.mj_id2name(new_model, mujoco.mjtObj.mjOBJ_BODY, int(new_model.jnt_bodyid[j]))
        old = mujoco.mj_name2id(old_model, mujoco.mjtObj.mjOBJ_BODY, body)
        if new_model.jnt_type[j] != mujoco.mjtJoint.mjJNT_FREE or old < 0:
            raise ValueError(f"joint {name!r} of the new model is neither in the old one nor a released body's free joint")
        data.qpos[qa : qa + 3] = old_data.xpos[old]
        data.qpos[qa + 3 : qa + 7] = old_data.xquat[old]
        mujoco.mj_objectVelocity(old_model, old_data, mujoco.mjtObj.mjOBJ_XBODY, old, velocity, 0)  # (angular, linear), world axes, at the frame origin
        data.qvel[va : va + 3] = velocity[3:]  # a free joint's linear speed is in world axes
        data.qvel[va + 3 : va + 6] = old_data.xmat[old].reshape(3, 3).T @ velocity[:3]  # and its angular speed in the body's axes
    return data


class TimestepSensitivity:
    """Whether a run is where the measurements of `break-timestep.md` did not keep breaks time-step invariant: a mass ratio over
    `MASS_RATIO_LIMIT`, a slider spring over `SPRING_LIMIT` or a body faster than `SPEED_LIMIT_M_S`. All three are read from the
    model and state of the run at construction and after every step (`observe`): the model may be one compiled again after a
    break, and the masses change as tanks drain. `reasons` says which, each kind (and each spring) once, at its first value
    out of range."""

    def __init__(self, model: mujoco.MjModel) -> None:
        self._found: dict[str, str] = {}
        self._check_model(model)

    @property
    def reasons(self) -> list[str]:
        return list(self._found.values())

    def _report(self, kind: str, text: str) -> None:
        self._found.setdefault(kind, text)

    def _check_model(self, model: mujoco.MjModel) -> None:
        masses = np.asarray(model.body_mass, dtype=float)
        bodies = masses[1:]
        if bodies.size >= 2 and bodies.min() > 0.0 and bodies.max() / bodies.min() > MASS_RATIO_LIMIT:
            self._report("mass", f"질량비 {bodies.max() / bodies.min():.4g} > {MASS_RATIO_LIMIT:g}")
        if not np.any(model.jnt_stiffness > 0.0):
            return
        subtree = masses.copy()  # from the current masses (propellant on), not the compiled `body_subtreemass`
        for b in range(model.nbody - 1, 0, -1):
            subtree[model.body_parentid[b]] += subtree[b]
        dt = float(model.opt.timestep)
        for j in range(model.njnt):
            k = float(model.jnt_stiffness[j])
            if k <= 0.0 or model.jnt_type[j] != mujoco.mjtJoint.mjJNT_SLIDE:  # springs are on sliders only (`drives.py`)
                continue
            body = int(model.jnt_bodyid[j])
            held, root = float(subtree[body]), float(subtree[model.body_rootid[body]])
            reduced = held * (root - held) / root if root > held else held  # the two sides of the spring; a root slider holds all
            ratio = math.sqrt(k / reduced) * dt
            if ratio > SPRING_LIMIT:
                name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j)
                self._report(f"spring:{name}", f"스프링 {name}: omega * 시간 간격 {ratio:.3g} > {SPRING_LIMIT:g}")

    def observe(self, model: mujoco.MjModel, data: mujoco.MjData) -> None:
        """After a step, on the model the run is on now: the mass ratio and the springs again, and the fastest body's speed at
        its centre of mass [m/s] (from the step's `cvel`)."""
        self._check_model(model)
        r = data.xipos[1:] - data.subtree_com[model.body_rootid[1:]]
        v = data.cvel[1:, 3:] - np.cross(r, data.cvel[1:, :3])
        fastest = float(np.sqrt((v * v).sum(axis=1)).max()) if len(v) else 0.0
        if fastest > SPEED_LIMIT_M_S:
            self._report("speed", f"속도 {fastest:.4g} m/s > {SPEED_LIMIT_M_S:g} m/s")

    def label(self) -> str | None:
        """`TIMESTEP_SENSITIVE_LABEL` with the reasons, or `None` when the run stayed inside the measured range."""
        return f"{TIMESTEP_SENSITIVE_LABEL} ({'; '.join(self.reasons)}; docs/research/engine/break-timestep.md)" if self.reasons else None
