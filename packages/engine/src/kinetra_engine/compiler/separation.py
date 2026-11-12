"""Intended separation (X-08): a separator lets go of the joint at its `face_b` and pushes the two sides apart.

    separator_joints(design) -> {separator instance: SeparatorJoint}   # what each separator would release, and how hard it pushes
    check_separations(design)                                          # compile errors of the schedule's separation entries (X-01d)
    schedule = SeparationSchedule(design)                              # the entries in time order; `due(t)` hands out each once
    push_apart(model, data, tree, separator)                           # after the release: the declared impulse on both sides

**What comes apart.** A separator (B-15) is joined to one part at `face_a` and to another at `face_b`, both by fixed joints.
A separation releases the joint at **`face_b`**; the separator stays with the side of `face_a`. So there are two sides, the
one that keeps the separator and the one that leaves, and the remaining side's mass and centre of mass are the sums of the
instances it still holds. The joint at `face_b` is never welded (`bodytree.py`): the two sides are two bodies from the start,
held by that joint without a degree of freedom, like a breakable fixed joint (X-04b). The release is X-04b's: the tree loses
the joint (`breaks.release`), the model is compiled again and `breaks.carry_state` carries the state.

**Push.** Right after the release the declared separation impulse `J` [N*s] (`separation_impulse`, the instance's value or the
part's default) acts once, as an impulse, on both sides at one point, the centre of `face_b` in the world: `J * direction_a` on
the side of `face_a` and `J * direction_b` on the other, the two faces' outward normals (`parts.separator`). The normals are
opposite, so the two impulses are equal and opposite and act at the same point: linear and angular momentum are conserved.
The velocity change is the exact one of the rigid-body equations, `dv = M^-1 J_p^T p` (MuJoCo's `mj_applyFT` puts the impulse
on the generalized coordinates, the factored mass matrix of the current state solves it), with the propellant mass a tank holds
at that moment (`ThrustRun`). `J = 0` releases the joint and pushes nothing. How the push is made (any energy source) is not
modelled (B-15); the run says so in its model labels (`SEPARATION_LABEL`).

**Schedule.** A `SeparateEntry` (`kinetra_core.designspec`) names the separator instance and the time `at` [s]. The run
separates at the first tick whose step starts at or after `at` (the step from `t = (tick - 1) * timestep_s`, the same instant an
actuate entry's command takes effect) before that step is taken. A separation cannot be undone, so one separator has at most one
entry: two at the same time contradict each other (`separation_conflict`) and a later second one would release what is already
apart (`separation_twice`). An entry whose separator holds nothing at `face_b` has nothing to release (`separation_unjoined`).
These are compile errors in the X-01d form, checked in separator id order, then time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import mujoco
import numpy as np

from kinetra_core import SEPARATOR_FACE_B, DesignSpec, PartRole, SeparateEntry

from ..parts.separator import separator_from_part
from .errors import CompileError, CompileErrorCode

if TYPE_CHECKING:  # bodytree imports this module for the welding rule and the checks
    from .bodytree import BodyTree

Vec = tuple[float, float, float]

SEPARATION_LABEL = (
    "단순화 모델: 의도한 분리는 선언 분리 충격량을 한 순간에 분리 면 중심에서 두 쪽에 크기가 같고 방향이 반대로 준다"
    "(밀어내는 시간 모양, 충격 하중, 에너지원 없음)"
)
"""The `model_labels` sentence of a run whose design has a separator holding a part at `face_b`."""


@dataclass(frozen=True)
class SeparatorJoint:
    """What separator instance `separator` releases: fixed joint `joint` at its `face_b`, whose other end is instance `held`.
    `impulse` is the declared separation impulse [N*s]. `point` is the centre of `face_b` and `direction_a`, `direction_b` the
    two faces' outward unit normals, all in the separator's part frame."""

    separator: str
    joint: str
    held: str
    impulse: float
    point: Vec
    direction_a: Vec
    direction_b: Vec


def separator_joints(design: DesignSpec) -> dict[str, SeparatorJoint]:
    """Every separator instance of `design` that holds a part at `face_b`, by instance id (in `design`'s instance order). The
    design must be complete (no placeholder, C-06): the compiler calls this after `require_complete`."""
    parts = {p.id: p for p in design.parts}
    at_face_b: dict[str, tuple[str, str]] = {}
    for j in design.joints:
        for end, other in ((j.a, j.b), (j.b, j.a)):
            if end.snap_point == SEPARATOR_FACE_B:
                at_face_b[end.instance] = (j.id, other.instance)
    found = {}
    for inst in design.instances:
        part = parts[inst.part]
        if part.role is not PartRole.SEPARATOR or inst.id not in at_face_b:
            continue
        sep = separator_from_part(part, {p.name: p for p in inst.parameters})
        joint, held = at_face_b[inst.id]
        found[inst.id] = SeparatorJoint(inst.id, joint, held, sep.impulse.value, sep.position_b, sep.direction_a, sep.direction_b)
    return found


def check_separations(design: DesignSpec) -> None:
    """The first compile error of the schedule's separation entries, by separator id then time: `separation_unjoined`,
    `separation_conflict` (two at the same time), `separation_twice` (a later second one)."""
    by_separator: dict[str, list[SeparateEntry]] = {}
    for e in design.schedule.separations:
        by_separator.setdefault(e.separator, []).append(e)
    if not by_separator:
        return
    held = separator_joints(design)
    parts = {i.id: i.part for i in design.instances}
    for separator in sorted(by_separator):
        entries = sorted(by_separator[separator], key=lambda e: (e.at, e.id))
        if separator not in held:
            raise CompileError(
                f"schedule entry {entries[0].id!r} separates {separator!r}, but nothing is joined to its {SEPARATOR_FACE_B!r}: "
                "there is no joint to release",
                code=CompileErrorCode.SEPARATION_UNJOINED,
                instances=(separator,),
                parts=(parts[separator],),
            )
        if len(entries) > 1:
            first, other = entries[0], entries[1]
            same_time = other.at == first.at
            sep = held[separator]
            raise CompileError(
                f"schedule entries {first.id!r} and {other.id!r} both separate {separator!r} "
                + (
                    f"at {first.at:g} s: one separator, two contradicting entries at one time"
                    if same_time
                    else f"(at {first.at:g} s and {other.at:g} s): a separation cannot be undone, so the second has nothing to release"
                ),
                code=CompileErrorCode.SEPARATION_CONFLICT if same_time else CompileErrorCode.SEPARATION_TWICE,
                instances=(separator, sep.held),
                parts=tuple(dict.fromkeys((parts[separator], parts[sep.held]))),
                joints=(sep.joint,),
            )


class SeparationSchedule:
    """The separation entries of a design in time order (then separator id), each handed out once by `due`."""

    def __init__(self, design: DesignSpec) -> None:
        self._entries = sorted(design.schedule.separations, key=lambda e: (e.at, e.separator, e.id))
        self._next = 0

    def due(self, t: float) -> tuple[SeparateEntry, ...]:
        """The entries not handed out yet whose time `at` is at or before `t` [s], in order."""
        start = self._next
        while self._next < len(self._entries) and self._entries[self._next].at <= t:
            self._next += 1
        return tuple(self._entries[start : self._next])


def push_apart(model: mujoco.MjModel, data: mujoco.MjData, tree: BodyTree, sep: SeparatorJoint) -> None:
    """Give the two sides of `sep` (already released in `tree`, `model` compiled from it, `data` its state) the declared impulse:
    `impulse * direction_a` on the separator's body and `impulse * direction_b` on the body of `held`, both at the centre of
    `face_b`, as an instantaneous velocity change `dv = M^-1 J^T p` of `data.qvel`."""
    if sep.impulse == 0.0:
        return
    instances = {ci.instance: ci for ci in tree.instances}
    ci = instances[sep.separator]
    body = tree.body_of(sep.separator)
    frame = instances[body.id]  # a body's frame is its smallest-id instance's (bodytree.py)
    r_body, r_inst = _matrix(frame.orientation), _matrix(ci.orientation)  # saved world rotations
    r_rel = r_body.T @ r_inst  # the separator's rotation in its body's frame
    point_body = r_body.T @ (np.array(ci.position) - np.array(frame.position)) + r_rel @ np.array(sep.point)
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    mujoco.mj_crb(model, data)
    mujoco.mj_factorM(model, data)
    row_a = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body.id)
    row_b = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, tree.body_of(sep.held).id)
    r_world = data.xmat[row_a].reshape(3, 3) @ r_rel  # the separator's rotation in the world now
    point = data.xpos[row_a] + data.xmat[row_a].reshape(3, 3) @ point_body
    impulse = np.zeros(model.nv)
    torque = np.zeros(3)
    for row, direction in ((row_a, sep.direction_a), (row_b, sep.direction_b)):
        mujoco.mj_applyFT(model, data, sep.impulse * (r_world @ np.array(direction)), torque, point, row, impulse)
    dv = np.zeros(model.nv)
    mujoco.mj_solveM(model, data, dv.reshape(1, -1), impulse.reshape(1, -1))
    data.qvel[:] += dv


def _matrix(q: tuple[float, float, float, float]) -> np.ndarray:
    """The rotation matrix of a unit quaternion `(w, x, y, z)`."""
    r = np.zeros(9)
    mujoco.mju_quat2Mat(r, np.array(q))
    return r.reshape(3, 3)
