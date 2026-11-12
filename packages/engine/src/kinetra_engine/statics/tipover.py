"""Support polygon, centre-of-mass projection and tip-over angle of a compiled design on flat ground (X-03a).

    tipover(tree, tolerance=PLACEMENT_TOLERANCE) -> Tipover

An L0 analytic check (`client-adapter.md`, "파생값(L0)"; `studio-plan.md` 정역학): no simulation, no verdict.

**Ground and up.** The world convention of the project: flat ground is the plane z = 0 and +Z is up (`project-model.md`,
지형 소품). Gravity points along -Z on every planet, so the polygon, the margin and the angle do not depend on the planet:
only the direction of gravity enters, not its size.

**Support points.** The collision proxies of the body tree (`BodyGeom`, the shapes the engine collides with) placed at the
stored pose. A point of a geom whose height is within `tolerance` of z = 0 is a support point:

- sphere: its lowest point;
- box: every corner within `tolerance` (a face gives 4, an edge 2, a corner 1);
- cylinder: the exact lowest point of each end rim, and `RIM_SEGMENTS` points spaced evenly on each rim. A standing
  cylinder rests on a disk; the evenly spaced rim points give the inscribed polygon of that disk, which is inside the
  disk, so the margin is never overstated. The understatement is at most `r (1 - cos(pi / RIM_SEGMENTS))` per disk and the
  result names it (`approximations`).

A geom that reaches below z = -`tolerance` is a `TipoverError`: it is in the ground (`overlap` of `check_placement`), and a
contact patch through the ground is not a set of points.

**Polygon.** The convex hull (seen from above, counter-clockwise) of the support points: `none` (nothing touches the
ground: floating, or resting only on terrain props, which this check does not read), `point`, `segment` or `polygon`.

**Margin and angle.** `margin` is the signed horizontal distance from the projection of the centre of mass to the edge of
the support region: positive inside (distance to the nearest edge), negative outside (minus the distance to the region).
A point or segment has no inside, so its margin is at most 0. `tipover_angle = atan2(margin, h)` with `h` the height of the
centre of mass: the rigid design turned about the nearest edge by this angle (or standing on a slope this steep, if it
does not slide) has its centre of mass straight above that edge. Each polygon edge also has its own angle (`edges`), the
tip angle in that direction. `stable` is `margin > 0`; 0 is balanced on the edge and is not stable.

**Assumptions** (also in `Tipover.assumptions`, so they reach the user with the number): every joint is held at its stored
coordinate (0) and the whole design is one rigid body; the ground is flat z = 0 and terrain props are not supports; friction
is enough that nothing slides before tipping; nothing pushes but gravity (no thrust, motor torque, spring preload).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from kinetra_core import PLACEMENT_TOLERANCE

from ..compiler.bodytree import BodyGeom, BodyTree, Quat, Vec, mv, qmul, rot, vadd

RIM_SEGMENTS = 64
"""Evenly spaced points per cylinder rim. A numerical choice (not a physical value): the inscribed 64-gon of a disk loses at
most r (1 - cos(pi / 64)) ~ 0.0012 r of margin, and the result states the bound."""

ASSUMPTIONS = (
    "가정: 모든 결합은 저장된 자세(좌표 0)에 고정되고 설계 전체가 한 강체다",
    "가정: 지면은 z = 0 평면이고 지형 소품은 받침으로 세지 않는다",
    "가정: 넘어지기 전에 미끄러지지 않을 만큼 마찰이 있다",
    "가정: 중력 말고 미는 힘이 없다(추력, 모터 토크, 스프링 예압 없음)",
)

Point2 = tuple[float, float]
SupportKind = Literal["none", "point", "segment", "polygon"]


class TipoverError(ValueError):
    """The design cannot be checked as resting on the ground; `instances` are the ones the reason is about."""

    def __init__(self, message: str, *, instances: tuple[str, ...] = ()):
        super().__init__(message)
        self.instances = instances


@dataclass(frozen=True)
class SupportPoint:
    """A point of a collision geom on the ground, world frame [m]; `geom` is the `BodyGeom.name`."""

    instance: str
    geom: str
    point: Vec


@dataclass(frozen=True)
class SupportEdge:
    """Edge `a` -> `b` of the support polygon (counter-clockwise from above). `distance` [m] is the signed horizontal distance
    from the centre-of-mass projection to the edge's line (positive inside), `angle` [rad] = atan2(distance, height)."""

    a: SupportPoint
    b: SupportPoint
    distance: float
    angle: float


@dataclass(frozen=True)
class Tipover:
    """See the module docstring. Lengths in m, angles in rad, mass in kg, world frame."""

    mass: float
    center_of_mass: Vec
    com_projection: Point2
    com_height: float
    contacts: tuple[SupportPoint, ...]  # every support point, in geom order
    kind: SupportKind
    polygon: tuple[SupportPoint, ...]  # hull vertices, counter-clockwise from above
    edges: tuple[SupportEdge, ...]  # only for `polygon`
    margin: float | None  # None when nothing touches the ground
    tipover_angle: float | None
    stable: bool
    approximations: tuple[str, ...]
    assumptions: tuple[str, ...] = ASSUMPTIONS


def tipover(tree: BodyTree, *, tolerance: float = PLACEMENT_TOLERANCE) -> Tipover:
    """The support polygon, centre-of-mass projection and tip-over angle of `tree` at its stored pose (module docstring).
    `tolerance` [m] is how close to z = 0 a point counts as on the ground; the default is the placement check's numerical
    tolerance for stored doubles. Raises `TipoverError` for a geom below the ground."""
    frames = {i.instance: (i.position, i.orientation) for i in tree.instances}

    weighted: list[tuple[float, Vec]] = []
    contacts: list[SupportPoint] = []
    disk_radii: list[float] = []
    for body in tree.bodies:
        tb, qb = frames[body.id]  # a body's frame is that of its smallest instance, whose id it carries
        rb = rot(qb)
        weighted.append((body.mass, vadd(mv(rb, body.com), tb)))
        for g in body.geoms:
            points, disk = _ground_points(g, vadd(mv(rb, g.pos), tb), qmul(qb, g.quat), tolerance)
            contacts.extend(SupportPoint(g.instance, g.name, p) for p in points)
            if disk:
                disk_radii.append(g.size[0])

    mass = math.fsum(m for m, _ in weighted)
    com: Vec = tuple(math.fsum(m * c[k] for m, c in weighted) / mass for k in range(3))  # type: ignore[assignment]
    p: Point2 = (com[0], com[1])
    h = com[2]

    hull = _hull(contacts, tolerance)
    kind: SupportKind = ("none", "point", "segment")[len(hull)] if len(hull) < 3 else "polygon"
    edges: tuple[SupportEdge, ...] = ()
    margin: float | None
    if kind == "none":
        margin = None
    elif kind == "point":
        margin = -math.dist(p, _xy(hull[0]))
    elif kind == "segment":
        margin = -_segment_distance(p, _xy(hull[0]), _xy(hull[1]))
    else:
        pairs = list(zip(hull, hull[1:] + hull[:1]))
        dists = [_line_distance(p, _xy(a), _xy(b)) for a, b in pairs]
        edges = tuple(SupportEdge(a, b, d, math.atan2(d, h)) for (a, b), d in zip(pairs, dists))
        margin = min(dists) if min(dists) >= 0.0 else -min(_segment_distance(p, _xy(a), _xy(b)) for a, b in pairs)

    approximations = ()
    if disk_radii:
        loss = max(disk_radii) * (1.0 - math.cos(math.pi / RIM_SEGMENTS))
        approximations = (f"근사: 원판 접촉을 내접 {RIM_SEGMENTS}각형으로 셈(여유를 최대 {loss:.3g} m 작게 냄)",)
    return Tipover(
        mass=mass,
        center_of_mass=com,
        com_projection=p,
        com_height=h,
        contacts=tuple(contacts),
        kind=kind,
        polygon=tuple(hull),
        edges=edges,
        margin=margin,
        tipover_angle=None if margin is None else math.atan2(margin, h),
        stable=margin is not None and margin > 0.0,
        approximations=approximations,
    )


# --- support points of one geom --------------------------------------------------------------------------------------


def _ground_points(g: BodyGeom, center: Vec, quat: Quat, tol: float) -> tuple[list[Vec], bool]:
    """World points of `g` on the ground, and whether a whole cylinder rim lies on it (a disk). `center`, `quat`: world."""
    r = rot(quat)
    if g.type == "sphere":
        candidates = [(center[0], center[1], center[2] - g.size[0])]
    elif g.type == "box":
        hx, hy, hz = g.size
        candidates = [vadd(mv(r, (sx * hx, sy * hy, sz * hz)), center) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    else:
        radius, half = g.size
        axis = (r[0][2], r[1][2], r[2][2])
        e1 = (r[0][0], r[1][0], r[2][0])
        e2 = (r[0][1], r[1][1], r[2][1])
        # direction in the rim plane that points down most: -(up minus its part along the axis)
        down = (axis[2] * axis[0], axis[2] * axis[1], -(1.0 - axis[2] * axis[2]))
        n = math.sqrt(down[0] ** 2 + down[1] ** 2 + down[2] ** 2)
        candidates = []
        for s in (-1.0, 1.0):
            c = (center[0] + s * half * axis[0], center[1] + s * half * axis[1], center[2] + s * half * axis[2])
            if n > 0.0:
                candidates.append((c[0] + radius * down[0] / n, c[1] + radius * down[1] / n, c[2] + radius * down[2] / n))
            for k in range(RIM_SEGMENTS):
                phi = 2.0 * math.pi * k / RIM_SEGMENTS
                cs, sn = math.cos(phi), math.sin(phi)
                candidates.append(tuple(c[i] + radius * (cs * e1[i] + sn * e2[i]) for i in range(3)))  # type: ignore[arg-type]
    low = min(c[2] for c in candidates)
    if low < -tol:
        raise TipoverError(
            f"geom {g.name!r} of instance {g.instance!r} reaches {-low:.6g} m below the ground (z = 0): it overlaps the ground",
            instances=(g.instance,),
        )
    on = [c for c in candidates if c[2] <= tol]
    disk = g.type == "cylinder" and len(on) > RIM_SEGMENTS // 2
    return on, disk


# --- plane geometry, seen from above -------------------------------------------------------------------------------


def _xy(s: SupportPoint) -> Point2:
    return (s.point[0], s.point[1])


def _cross(o: Point2, a: Point2, b: Point2) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _hull(points: list[SupportPoint], tol: float) -> list[SupportPoint]:
    """Convex hull, counter-clockwise (monotone chain). Points closer than `tol` to a kept point are merged (the region loses
    at most `tol`); a vertex is dropped only when it is exactly not a left turn, so a fine arc keeps every vertex. A hull no
    wider than `tol` is the segment between its two ends."""
    unique: list[SupportPoint] = []
    for s in sorted(points, key=lambda s: (s.point[0], s.point[1], s.instance, s.geom)):
        if not any(math.dist(_xy(s), _xy(u)) <= tol for u in unique):
            unique.append(s)
    if len(unique) <= 2:
        return unique

    def half(seq: list[SupportPoint]) -> list[SupportPoint]:
        out: list[SupportPoint] = []
        for s in seq:
            while len(out) >= 2 and _cross(_xy(out[-2]), _xy(out[-1]), _xy(s)) <= 0.0:
                out.pop()
            out.append(s)
        return out

    lower, upper = half(unique), half(unique[::-1])
    hull = lower[:-1] + upper[:-1]
    a = hull[0]
    b = max(hull, key=lambda s: math.dist(_xy(a), _xy(s)))
    if len(hull) == 2 or all(abs(_line_distance(_xy(s), _xy(a), _xy(b))) <= tol for s in hull):
        return [a, b]  # all on one line: the two ends
    return hull


def _line_distance(p: Point2, a: Point2, b: Point2) -> float:
    """Signed distance from `p` to the line `a` -> `b`, positive on the left (inside a counter-clockwise polygon)."""
    return _cross(a, b, p) / math.dist(a, b)


def _segment_distance(p: Point2, a: Point2, b: Point2) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))
