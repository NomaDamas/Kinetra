"""Breakable joints during a run (X-04b): read the load on every joint that has a `break_threshold`, release the ones over it.

    watch = BreakWatch(tree, model)          # the tree's joints with a threshold, bound to a loaded model
    over = watch.over(model, data)           # right after mj_step: the joints whose load is over their threshold
    tree = release(tree, [b.joint for b in over])        # those joints' child bodies become free bodies
    data = carry_state(old_model, old_data, new_model)   # the same poses and velocities in the model of the new tree

**Load.** A joint's load [N] is the magnitude of the force its child body takes from its parent during the step just taken:
the force part of MuJoCo's `cfrc_int` of the child body (the spatial force a body receives from its parent, computed by
`mj_rnePostConstraint` from the step's accelerations, contact and applied forces). That is everything the joint transmits to
the subtree it holds, along and across its axis; the torque is not compared (a threshold is a force in N, `break-threshold.md`).
A joint breaks at the first tick where its load is **over** its threshold (`load > threshold`); the load in the event is that
tick's load. A breakable `fixed` joint is a body held rigidly to its parent without a degree of freedom (`bodytree.py`), so
the same `cfrc_int` reads it.

**Release.** A broken joint's child body (with the bodies hung from it) becomes a free body: in the tree its parent and joint
go (`release`); the model is compiled again from that tree, and `carry_state` gives the new data every body's pose and
velocity of the tick of the break (joints the two models share keep their coordinate and speed by name; a released body's
new free joint takes the body frame's world pose and velocity). Nothing jumps: the frame of that tick is the same either
way. A spring or motor on the broken joint goes with it (`Drives.without_joints`).

**Determinism.** The load is read from the engine's state only, released joints are taken in joint id order, and the new
model is the same text for the same tree, so the same project and the same ticks give the same breaks and the same states.

This is a simplified model (plan 4.6, `break-threshold.md`): one scalar force against one scalar threshold. No torque, no
fatigue, no cracks, no FEM.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace

import mujoco
import numpy as np

from .bodytree import BodyTree

BREAK_LABEL = "단순화 모델: 결합 파단은 결합을 지나는 힘의 크기 [N]만 임계와 비교한다(토크, 피로, 균열, FEM 없음)"
"""The `model_labels` sentence of a run whose design has a joint with a `break_threshold`."""

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
    """The breakable joints of one run, bound to the current model. `over` reads the loads after each `mj_step`."""

    def __init__(self, tree: BodyTree, model: mujoco.MjModel) -> None:
        self.joints: tuple[BreakableJoint, ...] = ()
        self._rows: list[tuple[BreakableJoint, int]] = []
        self.bind(tree, model)

    def bind(self, tree: BodyTree, model: mujoco.MjModel) -> None:
        """Watch the joints of `tree` (after a `release`, the ones left) in `model`, compiled from that tree."""
        self.joints = breakable_joints(tree)
        self._rows = []
        for j in self.joints:
            row = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, j.body)
            if row < 0:
                raise ValueError(f"the MuJoCo model has no body {j.body!r}: it was not compiled from this body tree")
            self._rows.append((j, row))

    def over(self, model: mujoco.MjModel, data: mujoco.MjData) -> tuple[OverThreshold, ...]:
        """Right after `mj_step` (before anything restores `xfrc_applied` or the masses of the step): the joints whose load
        is over their threshold, in joint id order."""
        if not self._rows:
            return ()
        mujoco.mj_rnePostConstraint(model, data)
        found = []
        for j, row in self._rows:
            load = float(np.linalg.norm(data.cfrc_int[row, 3:6]))
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
