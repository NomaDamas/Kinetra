"""Body tree of a `Project` (X-01a): the instances and fixed joints turned into rigid bodies and the tree they hang in.

    build_body_tree(project, cache=None, tolerance=None) -> BodyTree

**Order (#511).** The project is read through `kinetra_core.canonical_order` and nothing else: instances, joints, the
components of a shape recipe and every other collection are in the order of their ids, whatever order the file had. So two
projects with the same `project_hash` give the same bodies, the same float sums and the same MJCF, bit for bit.

**Rigid bodies.** A `fixed` joint without a `break_threshold` welds its two instances: they are one rigid body that moves as one
(the same grouping the stream frames name, `bodies[].instances`, `client-adapter.md` F8). The body's id is the smallest instance
id of the group and its frame is that instance's frame. Its mass, centre of mass and inertia are the sum of the instances'
`MassProperties` (parallel-axis theorem, in the body frame). They are never read from the collision proxy. A `fixed` joint
**with** a `break_threshold` (X-04b) does not weld: its two sides stay two bodies, joined in the tree by that fixed joint, so the
run can read the force through it and release it (`breaks.py`).

**Tree.** `hinge`, `slider` and breakable `fixed` joints connect bodies. The bodies and these joints must form one tree: a loop,
a joint inside one rigid body and a second assembly the first is not joined to are `CompileError`s naming the instances and
joints. The root is the smallest-id body that is no joint's `b` side (the `a` side is the parent by convention); the tree is
then walked from it, and a joint met from its `b` side is reversed: the axis changes sign and the coordinate and its limits
stay the joint's own (`b` turning by q relative to `a` is `a` turning by q about the opposite axis). The root is free (6
degrees of freedom); every other body has the one degree of freedom of its hinge or slider, or none (a breakable fixed joint:
held to its parent until it breaks).

**Frames.** SI, right-handed, +Z up; quaternions are `(w, x, y, z)` here because MuJoCo orders them so (`collision-proxy.md`,
mapping table). A body's `pos`/`quat` are relative to its parent body (the root's to the world). A joint's `pos` and `axis` are
in the frame of the body it belongs to (the child): the point is the world position of the `a` snap point, the axis is
`R(a instance) R(a snap point) axis` turned into the child's frame (a fixed joint has no axis: `(0, 0, 0)`).

Not here: the springs, dampers, motors and actuator limits of a joint (X-01b), thrusters and propellant (X-01c), measuring and
releasing a breakable joint during a run (X-04b, `breaks.py`), contact friction and parameters (X-01e, `contact.py`). The tree
carries no threshold: the run reads it from `tree.joints`.

**Planet (W-03a).** The tree also carries the gravity and atmosphere density of `project.world.planet`, read from
`data/bodies` by `planet_physics` (`planet.py`) and nowhere else; a planet without readable data is a `CompileError`.

**Errors (X-01d).** A project with a missing definition is refused first (`require_complete`, `ProjectIncomplete`). Every
other refusal is a `CompileError` with a code and the instance, part, joint and actuator ids (`errors.py`); the checks per
part and joint that building does not make are in `checks.py`, run in this order: planet, parts, actuators, snaps, axes,
the tree, floating.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from kinetra_core import (
    BlockedOperation,
    CollisionProxy,
    DesignSpec,
    Instance,
    Joint,
    JointKind,
    MassProperties,
    PartDef,
    Project,
    Quantity,
    canonical_order,
    check_placement,
    require_complete,
)
from kinetra_core.geometry import Quaternion

from ..parts import PartCache, ShapeError, collision_proxy, mass_properties
from .checks import check_actuators, check_axes, check_floating, check_snaps
from .errors import CompileError, CompileErrorCode
from .planet import PlanetPhysics, planet_physics

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]
Quat = tuple[float, float, float, float]  # w, x, y, z

IDENTITY_QUAT: Quat = (1.0, 0.0, 0.0, 0.0)


# --- small linear algebra, tuples only (the order of every sum is the code's, so the bits are reproducible) -------------


def quat_of(q: Quaternion) -> Quat:
    """`{x, y, z, w}` of the model (norm 1 +- 1e-6) as a unit `(w, x, y, z)`."""
    n = math.sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
    return (q.w / n, q.x / n, q.y / n, q.z / n)


def qmul(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def qconj(q: Quat) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def qnorm(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q))
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def rot(q: Quat) -> Mat:
    w, x, y, z = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def mv(m: Mat, v: Vec) -> Vec:
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))  # type: ignore[return-value]


def mtv(m: Mat, v: Vec) -> Vec:
    """`m^T v`."""
    return tuple(m[0][i] * v[0] + m[1][i] * v[1] + m[2][i] * v[2] for i in range(3))  # type: ignore[return-value]


def vadd(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vsub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _congruent(r: Mat, i: Mat) -> Mat:
    """`r i r^T`."""
    return tuple(  # type: ignore[return-value]
        tuple(sum(r[a][k] * i[k][l] * r[b][l] for k in range(3) for l in range(3)) for b in range(3)) for a in range(3)
    )


def _inertia_matrix(p: MassProperties) -> Mat:
    i = p.inertia
    return ((i.ixx, i.ixy, i.ixz), (i.ixy, i.iyy, i.iyz), (i.ixz, i.iyz, i.izz))


# --- result types --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledInstance:
    """One instance with what the compiler computed for it: mass properties and collision proxy of its part at its
    parameters, its pose, and the body it sits in."""

    instance: str
    part: str
    material: str | None
    body: str
    position: Vec  # world [m]
    orientation: Quat  # world, (w, x, y, z)
    properties: MassProperties
    proxy: CollisionProxy


@dataclass(frozen=True)
class BodyGeom:
    """One MuJoCo `geom` of a body, from one geom of an instance's collision proxy.

    `size` is MuJoCo's `size` for the type (box: half extents; cylinder: radius, half length; sphere: radius), `pos` and
    `quat` are in the body frame, quaternion `(w, x, y, z)`. `name` is `<instance>/<proxy geom id>`."""

    name: str
    instance: str
    proxy_geom: str
    type: str
    size: tuple[float, ...]
    pos: Vec
    quat: Quat


@dataclass(frozen=True)
class BodyJoint:
    """What holds a body to its parent: one hinge or slider degree of freedom, or a breakable fixed joint (no degree of freedom,
    `axis` `(0, 0, 0)`). `axis` and `pos` are in this body's frame, `range` is the joint's travel limit (rad or m, `None` =
    unlimited), the same coordinate as the project's joint. `reversed`: the body is the joint's `a` side, so `axis` is the
    joint's with the sign flipped (and the coordinate keeps its meaning and its limits)."""

    id: str
    kind: JointKind
    pos: Vec
    axis: Vec
    range: tuple[float, float] | None
    reversed: bool


@dataclass(frozen=True)
class Body:
    """A rigid body: the instances welded together, hung in the tree.

    `pos`/`quat` relative to the parent body (the world for the root). `mass`, `com` (in the body frame) and `inertia`
    (about `com`, in the body frame, as `(ixx, iyy, izz, ixy, ixz, iyz)` matrix entries) are the sums of the instances'
    `MassProperties`."""

    id: str
    instances: tuple[str, ...]
    parent: str | None
    joint: BodyJoint | None  # None for a root, which is free
    pos: Vec
    quat: Quat
    mass: float
    com: Vec
    inertia: tuple[float, float, float, float, float, float]
    geoms: tuple[BodyGeom, ...]


@dataclass(frozen=True)
class BodyTree:
    """`bodies` in tree order (parents before children, siblings by id); `bodies[0]` is the root. A tree built from a project
    has one root; a run that released joints (`breaks.release`) has more, each a free body hung from the world. `planet`: the
    constants of `project.world.planet` from `data/bodies` (W-03a)."""

    bodies: tuple[Body, ...]
    instances: tuple[CompiledInstance, ...]  # canonical (id) order
    joints: tuple[Joint, ...]  # canonical (id) order, as the project's joints
    design: DesignSpec = field(repr=False)  # the canonical-order design the tree was built from
    planet: PlanetPhysics

    @property
    def root(self) -> Body:
        return self.bodies[0]

    @property
    def roots(self) -> tuple[Body, ...]:
        """The free bodies, in tree order: the root, then the bodies of released joints."""
        return tuple(b for b in self.bodies if b.parent is None)

    def body(self, body_id: str) -> Body:
        return next(b for b in self.bodies if b.id == body_id)

    def body_of(self, instance_id: str) -> Body:
        return next(b for b in self.bodies if instance_id in b.instances)


# --- building --------------------------------------------------------------------------------------------------------


def _parameter_values(part: PartDef, inst: Instance) -> dict[str, float]:
    return {p.name: p.default.value for p in part.parameters} | {p.name: p.value for p in inst.parameters}


def _welds(joint: Joint) -> bool:
    """A fixed joint that never breaks makes its two instances one rigid body; a breakable one keeps them two bodies."""
    return joint.kind is JointKind.FIXED and joint.break_threshold is None


def _compile_instance(
    design: DesignSpec,
    inst: Instance,
    parts: Mapping[str, PartDef],
    materials: Mapping[str, object],
    cache: PartCache | None,
    tolerance: float | Quantity | None,
) -> tuple[MassProperties, CollisionProxy]:
    part = parts[inst.part]
    material = materials[inst.material] if inst.material is not None else None
    values: dict[str, Quantity] = {p.name: p for p in inst.parameters}
    try:
        if cache is not None:
            return cache.mass_properties(part, material, values), cache.collision_proxy(part, values, tolerance)  # type: ignore[arg-type]
        return mass_properties(part, material, values), collision_proxy(part, values, tolerance)  # type: ignore[arg-type]
    except ShapeError as e:
        raise CompileError(
            f"instance {inst.id!r} (part {part.id!r}): {e}", code=CompileErrorCode.PART, instances=(inst.id,), parts=(part.id,)
        ) from e


class _Groups:
    """Union-find over ids; the representative is always the smallest id."""

    def __init__(self, ids: list[str]) -> None:
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> bool:
        """Join; `False` when they were already one."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        lo, hi = (ra, rb) if ra < rb else (rb, ra)
        self.parent[hi] = lo
        return True


def build_body_tree(
    project: Project,
    cache: PartCache | None = None,
    tolerance: float | Quantity | None = None,
    bodies_directory: Path | None = None,
) -> BodyTree:
    """The body tree of `project` (see the module docstring). `cache` serves `mass_properties` and `collision_proxy`;
    `tolerance` is the proxy decomposition tolerance (`collision_proxy`, default `DEFAULT_TOLERANCE`); `bodies_directory`
    is where the planet data is read (`load_body`, default `data/bodies`).

    Raises `ProjectIncomplete` for a missing definition and `CompileError` (`errors.py`) for a planet without readable
    data, a design with no instance, a part that cannot be compiled, an actuator without a curve, joined snap points that
    do not meet, a joint axis the two snap frames disagree on, a loop of fixed joints, a joint inside one rigid body, a
    loop among the bodies, an assembly that is not one piece, or one that floats."""
    require_complete(project, BlockedOperation.COMPILE)
    try:
        planet = planet_physics(project.world.planet, bodies_directory)
    except (KeyError, OSError, ValueError) as e:
        raise CompileError(
            f"planet {project.world.planet!r} has no readable data in data/bodies: {e}", code=CompileErrorCode.PLANET
        ) from e
    ordered_project = canonical_order(project)  # the one reading order: ids, not the file's order
    design = ordered_project.design
    if not design.instances:
        raise CompileError("the design has no instance: nothing to compile", code=CompileErrorCode.NO_INSTANCE)
    parts = {p.id: p for p in design.parts}
    materials = {m.id: m for m in design.materials}
    by_id = {i.id: i for i in design.instances}

    def parts_of(*instances: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(by_id[i].part for i in instances))

    compiled: dict[str, tuple[MassProperties, CollisionProxy]] = {
        inst.id: _compile_instance(design, inst, parts, materials, cache, tolerance) for inst in design.instances
    }
    check_actuators(design)
    findings = check_placement(ordered_project)
    check_snaps(design, findings)
    check_axes(design)

    # rigid bodies: instances welded by fixed joints that never break
    groups = _Groups(list(by_id))
    for joint in design.joints:
        if _welds(joint) and not groups.union(joint.a.instance, joint.b.instance):
            raise CompileError(
                f"fixed joint {joint.id!r} closes a loop of fixed joints between instances {joint.a.instance!r} and {joint.b.instance!r}: "
                "they are already one rigid body",
                code=CompileErrorCode.FIXED_LOOP,
                instances=(joint.a.instance, joint.b.instance),
                parts=parts_of(joint.a.instance, joint.b.instance),
                joints=(joint.id,),
            )
    members: dict[str, list[str]] = {}
    for iid in by_id:  # canonical order
        members.setdefault(groups.find(iid), []).append(iid)

    # joints between bodies: must be one tree
    tree_groups = _Groups(list(members))
    adjacency: dict[str, list[tuple[str, Joint, bool]]] = {g: [] for g in members}  # (other body, joint, other is the joint's a side)
    targets: set[str] = set()
    for joint in design.joints:
        if _welds(joint):
            continue
        ga, gb = groups.find(joint.a.instance), groups.find(joint.b.instance)
        if ga == gb:
            could_not = "break apart" if joint.kind is JointKind.FIXED else "move"
            raise CompileError(
                f"{joint.kind.value} joint {joint.id!r} joins instances {joint.a.instance!r} and {joint.b.instance!r}, "
                f"which fixed joints already weld into one rigid body {ga!r}: it could not {could_not}",
                code=CompileErrorCode.WELDED_JOINT,
                instances=(joint.a.instance, joint.b.instance),
                parts=parts_of(joint.a.instance, joint.b.instance),
                joints=(joint.id,),
            )
        if not tree_groups.union(ga, gb):
            raise CompileError(
                f"joint {joint.id!r} closes a loop between bodies {ga!r} and {gb!r}: the joints must form a tree",
                code=CompileErrorCode.LOOP,
                instances=(joint.a.instance, joint.b.instance),
                parts=parts_of(joint.a.instance, joint.b.instance),
                joints=(joint.id,),
            )
        adjacency[ga].append((gb, joint, False))
        adjacency[gb].append((ga, joint, True))
        targets.add(gb)
    pieces = sorted({tree_groups.find(g) for g in members})
    if len(pieces) > 1:
        first = [g for g in members if tree_groups.find(g) == pieces[0]]
        rest = [g for g in members if tree_groups.find(g) != pieces[0]]
        raise CompileError(
            f"the assembly is not one piece: {len(pieces)} groups of bodies have no joint between them "
            f"(for example {first[0]!r} and {rest[0]!r})",
            code=CompileErrorCode.NOT_ONE_PIECE,
            instances=(first[0], rest[0]),
            parts=parts_of(first[0], rest[0]),
        )
    check_floating(design, findings)

    root = min(g for g in members if g not in targets)  # never a joint's b side: exists, a tree has no directed cycle

    # world frames of the instances
    world: dict[str, tuple[Vec, Quat]] = {
        i: ((inst.pose.position.x, inst.pose.position.y, inst.pose.position.z), quat_of(inst.pose.orientation)) for i, inst in by_id.items()
    }

    def snap_world(ref_instance: str, snap_id: str) -> tuple[Vec, Quat]:
        inst = by_id[ref_instance]
        part = parts[inst.part]
        snap = next(s for s in part.snap_points if s.id == snap_id)
        t, q = world[ref_instance]
        return vadd(mv(rot(q), snap.position.evaluate(_parameter_values(part, inst))), t), qmul(q, quat_of(snap.orientation))

    ordered: list[str] = []
    placement: dict[str, tuple[str | None, Joint | None, bool]] = {root: (None, None, False)}
    stack = [root]
    while stack:  # depth first, siblings by id: parents before children
        g = stack.pop()
        ordered.append(g)
        kids = sorted(((other, joint, rev) for other, joint, rev in adjacency[g] if other not in placement), key=lambda k: (k[0], k[1].id))
        for other, joint, rev in kids:
            placement[other] = (g, joint, rev)
        stack.extend(reversed([k[0] for k in kids]))

    bodies: list[Body] = []
    for g in ordered:
        parent, joint, rev = placement[g]
        tb, qb = world[g]
        rb = rot(qb)
        ids = tuple(members[g])
        # mass, centre of mass and inertia of the body, in its frame
        rel: list[tuple[str, float, Vec, Mat, MassProperties]] = []
        for iid in ids:
            ti, qi = world[iid]
            qrel = qnorm(qmul(qconj(qb), qi))
            props = compiled[iid][0]
            c = props.center_of_mass
            com_i = vadd(mv(rot(qrel), (c.x, c.y, c.z)), mtv(rb, vsub(ti, tb)))
            rel.append((iid, props.mass.value, com_i, rot(qrel), props))
        mass = math.fsum(m for _, m, _, _, _ in rel)
        com = tuple(math.fsum(m * c[k] for _, m, c, _, _ in rel) / mass for k in range(3))
        entries = [[], [], [], [], [], []]  # ixx iyy izz ixy ixz iyz
        for _, m, c, r, props in rel:
            t = _congruent(r, _inertia_matrix(props))
            d = vsub(c, com)  # type: ignore[arg-type]
            # Each diagonal term from the other two offset components: |d|^2 - d_i^2 would cancel a small perpendicular
            # offset along a long one to nothing (the same rule as `parts.mass`, B-01a).
            entries[0].append(t[0][0] + m * (d[1] * d[1] + d[2] * d[2]))
            entries[1].append(t[1][1] + m * (d[0] * d[0] + d[2] * d[2]))
            entries[2].append(t[2][2] + m * (d[0] * d[0] + d[1] * d[1]))
            entries[3].append(t[0][1] - m * d[0] * d[1])
            entries[4].append(t[0][2] - m * d[0] * d[2])
            entries[5].append(t[1][2] - m * d[1] * d[2])
        inertia = tuple(math.fsum(e) for e in entries)

        geoms: list[BodyGeom] = []
        for iid in ids:
            ti, qi = world[iid]
            qrel = qnorm(qmul(qconj(qb), qi))
            r = rot(qrel)
            p_rel = mtv(rb, vsub(ti, tb))
            for pg in compiled[iid][1].geoms:
                dims = {d.name: d.value for d in pg.dimensions}
                if pg.primitive == "box":
                    gtype, size = "box", (dims["size_x"] / 2.0, dims["size_y"] / 2.0, dims["size_z"] / 2.0)
                elif pg.primitive == "cylinder":
                    gtype, size = "cylinder", (dims["radius"], dims["length"] / 2.0)
                else:
                    gtype, size = "sphere", (dims["radius"],)
                geoms.append(
                    BodyGeom(
                        name=f"{iid}/{pg.id}",
                        instance=iid,
                        proxy_geom=pg.id,
                        type=gtype,
                        size=size,
                        pos=vadd(mv(r, pg.center), p_rel),
                        quat=qnorm(qmul(qrel, quat_of(pg.orientation))),
                    )
                )

        if parent is None:
            pos, quat, bjoint = tb, qb, None
        else:
            tp, qp = world[parent]
            pos, quat = mtv(rot(qp), vsub(tb, tp)), qnorm(qmul(qconj(qp), qb))
            assert joint is not None
            ap = snap_world(joint.a.instance, joint.a.snap_point)[0]
            if joint.kind is JointKind.FIXED:  # breakable: no degree of freedom, so no axis
                axis: Vec = (0.0, 0.0, 0.0)
            else:
                axis_world = mv(rot(snap_world(joint.a.instance, joint.a.snap_point)[1]), joint.unit_axis)
                sign = -1.0 if rev else 1.0
                axis = mtv(rb, (sign * axis_world[0], sign * axis_world[1], sign * axis_world[2]))
            # Reversed (this body is the joint's `a` side): `b` moving by q about/along u relative to `a` is `a` moving by -q,
            # i.e. by q about/along -u. So the axis flips and the coordinate, hence its limits, stays the joint's own.
            limits = None if joint.limits is None else (joint.limits.lower.value, joint.limits.upper.value)
            bjoint = BodyJoint(joint.id, joint.kind, mtv(rb, vsub(ap, tb)), axis, limits, rev)
        bodies.append(Body(g, ids, parent, bjoint, pos, quat, mass, com, inertia, tuple(geoms)))  # type: ignore[arg-type]

    instances = tuple(
        CompiledInstance(i.id, i.part, i.material, groups.find(i.id), world[i.id][0], world[i.id][1], compiled[i.id][0], compiled[i.id][1])
        for i in design.instances
    )
    return BodyTree(tuple(bodies), instances, design.joints, design, planet)

