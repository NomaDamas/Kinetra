"""Static load at every joint of a design resting on flat ground, against its break threshold (X-03b).

    static_loads(tree, tolerance=PLACEMENT_TOLERANCE) -> StaticLoads

An L0 analytic check (`client-adapter.md`, "파생값(L0)"; `studio-plan.md` 정역학): no simulation, no verdict. It answers
"which joint would let go while the design just stands there", before a run.

**Which side hangs.** The compiler accepts only designs whose joints (fixed, hinge and slider together) form one tree over the
instances (`bodytree.py`: no fixed loop, no body loop, one piece), so cutting a joint splits the instances in two sides. The
ground contacts are those of X-03a (`tipover`, the collision proxies within `tolerance` of z = 0).

- One side touches the ground and the other does not (`HANGING`): the other side (the *free side*) is held by gravity and
  this joint only, so its free-body diagram gives the joint load exactly: the force is the free side's weight
  `F = (0, 0, -m g)` and the moment about the joint point is `M = (c - p) x F`, with `m` and `c` the free side's mass and
  centre of mass (sums of the instances' `MassProperties`, never the proxy), `p` the world position of the joint's `a` snap
  point and `g` the planet's gravity from the compiled tree (`data/bodies`). `force` and `moment` are what the free side puts
  on the joint (on the supported side); the joint pushes back with the opposite.
- Both sides touch the ground (`INDETERMINATE`): the ground and the joint share the weight and rigid-body statics does not
  say how (more unknown reactions than equations). No number is given; the reason is.
- Nothing touches the ground (`UNSUPPORTED`): floating, or resting only on terrain props, which X-03a does not read.

**Against the threshold.** `Joint.break_threshold` is one force [N] (X-04a), so the magnitude `load = |F|` is compared with
it: `margin = threshold - load` [N], `utilization = load / threshold`, `exceeds = load > threshold` (the threshold is the load
*above* which the joint releases, `BreakThreshold`). The moment is reported but not compared: a force threshold says nothing
about bending, and X-04a's threshold assumes no bending. A joint without a threshold never breaks (`Joint`) and has no margin.

**Free axis.** A hinge holds no moment about its axis and a slider no force along its axis. `axis_load` is that component of the
free side's load (N m about the hinge axis, N along the slider axis, signed along the joint axis in the world): what a motor,
a limit or a spring must hold for the design to stay at its stored pose. Nonzero means the joint moves unless something holds it.

**Assumptions** (also in `StaticLoads.assumptions`): every joint is held at its stored coordinate (0) and the design is at
rest; gravity is the only load (no thrust, motor torque, spring preload, acceleration, drag); the ground is z = 0 and terrain
props are not supports. If the design is not stable on its support (`tipover`), it is not at rest at this pose and the result
says so (`caveats`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from kinetra_core import PLACEMENT_TOLERANCE, Joint, JointKind

from ..compiler.bodytree import BodyTree, CompiledInstance, Vec, mv, qmul, quat_of, rot, vadd, vsub
from .tipover import Tipover, tipover

ASSUMPTIONS = (
    "가정: 모든 결합은 저장된 자세(좌표 0)에 고정되고 설계는 정지해 있다",
    "가정: 하중은 중력뿐이다(추력, 모터 토크, 스프링 예압, 가속, 항력 없음)",
    "가정: 지면은 z = 0 평면이고 지형 소품은 받침으로 세지 않는다",
    "가정: 결합을 끊어 지면에 닿지 않는 쪽의 무게를 그 결합이 모두 진다. 양쪽이 다 지면에 닿으면 부정정이라 값을 내지 않는다",
    "한계: 임계는 힘 [N] 하나라 하중의 크기만 비교한다. 굽힘 모멘트와 하중 방향은 비교하지 않는다(X-04a 단순화 모델)",
)


class LoadStatus(StrEnum):
    HANGING = "hanging"  # one side hangs on this joint: the load is its weight
    INDETERMINATE = "indeterminate"  # both sides on the ground: statics does not split the weight
    UNSUPPORTED = "unsupported"  # nothing on the ground


@dataclass(frozen=True)
class JointLoad:
    """The static load of one joint. World frame, SI (N, N m, kg, m). Load fields are `None` unless `status` is `HANGING`;
    threshold fields are `None` when the joint has no `break_threshold` or no load."""

    joint: str
    kind: JointKind
    status: LoadStatus
    reason: str | None  # why there is no load, for INDETERMINATE and UNSUPPORTED
    point: Vec  # world position of the `a` snap point, the moment's reference
    axis: Vec | None  # hinge or slider axis in the world, None for a fixed joint
    free_side: str | None  # "a" or "b": the side that hangs
    free_instances: tuple[str, ...]  # canonical order
    free_mass: float | None
    force: Vec | None  # what the free side puts on the joint
    moment: Vec | None  # about `point`
    load: float | None  # |force|
    axis_load: float | None  # hinge: moment . axis [N m]; slider: force . axis [N]; None for fixed
    threshold: float | None  # Joint.break_threshold [N]
    margin: float | None  # threshold - load [N]
    utilization: float | None  # load / threshold
    exceeds: bool  # load > threshold


@dataclass(frozen=True)
class StaticLoads:
    """See the module docstring. `joints` in canonical (id) order; `gravity` [m/s^2] of `planet`; `tipover` the X-03a result
    the ground contacts and the stability come from."""

    planet: str
    gravity: float
    joints: tuple[JointLoad, ...]
    tipover: Tipover
    caveats: tuple[str, ...]
    assumptions: tuple[str, ...] = ASSUMPTIONS

    def joint(self, joint_id: str) -> JointLoad:
        return next(j for j in self.joints if j.joint == joint_id)

    @property
    def exceeding(self) -> tuple[JointLoad, ...]:
        """Joints whose static load is above their break threshold."""
        return tuple(j for j in self.joints if j.exceeds)


def static_loads(tree: BodyTree, *, tolerance: float = PLACEMENT_TOLERANCE) -> StaticLoads:
    """The static load of every joint of `tree` at its stored pose and its margin to the break threshold (module docstring).
    `tolerance` [m] is X-03a's ground-contact tolerance. Raises `TipoverError` for a geom below the ground."""
    t = tipover(tree, tolerance=tolerance)
    g = tree.planet.gravity.value
    grounded = {c.instance for c in t.contacts}
    instances = {i.instance: i for i in tree.instances}
    order = [i.instance for i in tree.instances]
    adjacency: dict[str, list[tuple[str, str]]] = {i: [] for i in order}  # instance -> (other instance, joint id)
    for j in tree.joints:
        adjacency[j.a.instance].append((j.b.instance, j.id))
        adjacency[j.b.instance].append((j.a.instance, j.id))

    loads = tuple(_joint_load(tree, j, instances, order, adjacency, grounded, g) for j in tree.joints)
    caveats = ()
    if grounded and not t.stable:
        caveats = (
            f"주의: 지지 여유가 {t.margin:.3g} m(0 이하)라 설계가 이 자세로 정지해 있지 않다(X-03a). 하중은 이 자세로 붙잡아 둔 값이다",
        )
    return StaticLoads(planet=tree.planet.planet, gravity=g, joints=loads, tipover=t, caveats=caveats)


def _joint_load(
    tree: BodyTree,
    j: Joint,
    instances: dict[str, CompiledInstance],
    order: list[str],
    adjacency: dict[str, list[tuple[str, str]]],
    grounded: set[str],
    g: float,
) -> JointLoad:
    point, snap_quat = _snap_world(tree, instances[j.a.instance], j.a.snap_point)
    axis = None if j.kind is JointKind.FIXED else mv(rot(snap_quat), j.unit_axis)
    side_b = _side(j.b.instance, j.id, adjacency)
    b_on, a_on = bool(side_b & grounded), bool(grounded - side_b)
    threshold = None if j.break_threshold is None else j.break_threshold.value
    if a_on == b_on:
        status = LoadStatus.INDETERMINATE if a_on else LoadStatus.UNSUPPORTED
        reason = (
            "양쪽이 다 지면에 닿아 지면과 결합이 무게를 어떻게 나누는지 정역학만으로 정해지지 않는다(부정정)"
            if a_on
            else "설계가 지면(z = 0)에 닿지 않아 정지 하중이 없다(떠 있거나 지형 소품에만 얹힘)"
        )
        return JointLoad(j.id, j.kind, status, reason, point, axis, None, (), None, None, None, None, None, threshold, None, None, False)

    free_side = "a" if b_on else "b"
    free = [i for i in order if (i in side_b) == (free_side == "b")]
    weighted = [(instances[i].properties.mass.value, _com_world(instances[i])) for i in free]
    m = math.fsum(w for w, _ in weighted)
    c: Vec = tuple(math.fsum(w * x[k] for w, x in weighted) / m for k in range(3))  # type: ignore[assignment]
    force: Vec = (0.0, 0.0, -m * g)
    moment = _cross(vsub(c, point), force)
    load = math.sqrt(force[0] ** 2 + force[1] ** 2 + force[2] ** 2)
    axis_load = None
    if j.kind is JointKind.HINGE:
        axis_load = _dot(moment, axis)  # type: ignore[arg-type]
    elif j.kind is JointKind.SLIDER:
        axis_load = _dot(force, axis)  # type: ignore[arg-type]
    return JointLoad(
        joint=j.id,
        kind=j.kind,
        status=LoadStatus.HANGING,
        reason=None,
        point=point,
        axis=axis,
        free_side=free_side,
        free_instances=tuple(free),
        free_mass=m,
        force=force,
        moment=moment,
        load=load,
        axis_load=axis_load,
        threshold=threshold,
        margin=None if threshold is None else threshold - load,
        utilization=None if threshold is None else load / threshold,
        exceeds=threshold is not None and load > threshold,
    )


def _side(start: str, cut: str, adjacency: dict[str, list[tuple[str, str]]]) -> set[str]:
    """Instances reached from `start` without crossing joint `cut` (the joints form a tree over the instances)."""
    seen, stack = {start}, [start]
    while stack:
        for other, jid in adjacency[stack.pop()]:
            if jid != cut and other not in seen:
                seen.add(other)
                stack.append(other)
    return seen


def _com_world(i: CompiledInstance) -> Vec:
    c = i.properties.center_of_mass
    return vadd(mv(rot(i.orientation), (c.x, c.y, c.z)), i.position)


def _snap_world(tree: BodyTree, inst: CompiledInstance, snap_id: str) -> tuple[Vec, tuple[float, float, float, float]]:
    """World position and orientation `(w, x, y, z)` of a snap point (as the compiler places joints, `bodytree.py`)."""
    design_inst = next(i for i in tree.design.instances if i.id == inst.instance)
    part = next(p for p in tree.design.parts if p.id == inst.part)
    snap = next(s for s in part.snap_points if s.id == snap_id)
    values = {p.name: p.default.value for p in part.parameters} | {p.name: p.value for p in design_inst.parameters}
    return vadd(mv(rot(inst.orientation), snap.position.evaluate(values)), inst.position), qmul(inst.orientation, quat_of(snap.orientation))


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
