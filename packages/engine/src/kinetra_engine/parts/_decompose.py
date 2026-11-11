"""Convex decomposition of a part with a round through-bore (B-01f): box pieces inside the recipe's material.

A convex primitive has no hole, and a circle is not a finite union of boxes, so the result is an **inner approximation**
with a stated error. Two recipes are supported, the two the issue names; everything else is `plan_through_bore`'s reason
string, and `collision.py` fills that void or rejects the part (the caller chooses).

- a **plate with a bore**: an added box and one subtracted cylinder whose axis is parallel to a box axis, whose length is the
  box's extent along it (a through-hole) and which lies inside the box. Layout `strips`.
- a **tube**: an added cylinder and one subtracted cylinder of the same length with an axis parallel to the tube's. Layout `ring`,
  built around the bore's axis with the outer radius `R - e` for an off-centre bore (`e` = distance between the axes).

Every piece lies inside (host minus bore): it never leaves the host and never enters the bore, so the union is a subset of
the recipe, a body that fits in the real bore fits in the proxy's, and the error `(union - recipe) / recipe` of a host is
never positive. It is computed from the pieces (areas of rectangles and of the staves' union), not sampled.

**Strips (plate).** The cross-section (rectangle minus disc) is cut across `j` at `y_c - r cos(pi m / n)` for `m = 0..n`
(`n` even; so the bore centre is a boundary and the cuts crowd where the circle is steep) and at the plate's two edges. A
strip that misses the bore is one box; one that meets it is two boxes, one on each side of the bore. A box takes the narrower
host width and the wider bore chord of the strip's two ends; within a strip a circular edge is monotone (no strip contains
the bore's centre line), so that is an inner bound. Boundaries closer than `MIN_STRIP_FRACTION * r` to a neighbour are merged
(the merged strip is still monotone, still inner) so no piece is a sliver thinner than that along `j`. A piece's other
dimensions are the real wall, however thin. The pieces of one host have disjoint interiors, so the union volume is their sum.

**Ring (tube).** `N` boxes ("staves") of radial extent `[r, b]` and tangential width `w`, centred on the angles `2 pi m / N`,
inner face on the bore's tangent line, outer corners on the outer circle: `b = sqrt(R^2 - w^2 / 4)`. With `theta = 2 pi / N`:

- `w >= 2 r tan(theta / 2)`: adjacent inner faces overlap, so the bore's boundary is a closed regular `N`-gon of apothem `r`;
- `w < 2 r tan(theta)`: a stave meets only its two neighbours (a point at angle `a` from a stave's axis is in it only if
  `w >= 2 r tan a`), so the union is `N (stave - overlap of two neighbours)`, exact, with no triple overlaps;
- **closure** (every ray from the axis enters the wall once and leaves once: no radial slit): for a ray at angle `phi` from one
  stave's axis, between it and its neighbour, the two intervals of the ray inside the staves overlap. With `psi0 =
  atan(w / 2r)` and `phi* = max(0, theta - psi0)` that holds exactly when `r cos(phi*) <= b cos(theta - phi*)` (the other
  inequality of the pair, `w cos(theta - phi) >= 2 r sin(phi)`, is concave in `phi` and holds at both ends of the range once
  the first condition does).

The pieces overlap at the neighbours' sides; that is allowed in a collision (only mass needs disjoint solids). For each `N`
from 6 the width `w` is searched over `1.01 .. 1.90` times its lower bound; the smallest `N` with a closed `w` that is within
the tolerance is used. The report carries the max radial deviation of the inner surface (`r / cos(pi / N) - r`) and of the
outer surface (the radius of the notch between two staves, found by a fine scan of the two staves' reach `min(b / cos a,
w / (2 sin a))`; for an off-centre bore `e` is added, an upper bound of how far the real outer wall is from the ring's).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kinetra_core.shape import Box, Cylinder

from ._shape import Placed

MAX_STRIPS = 64  # largest even strip count tried for a plate
MAX_STAVES = 96  # largest stave count tried for a tube
MIN_STRIP_FRACTION = 0.02  # strips thinner than this fraction of the bore radius are merged into a neighbour
_W_MULTIPLIERS = tuple(1.0 + 0.9 * (k + 1) / 90 for k in range(90))  # 1.01 .. 1.90 times 2 r tan(pi / N)
_PARALLEL_DRIFT = 1e-9  # the bore's lateral drift over the host length, in bore radii, still treated as parallel
_LEN_TOL = 1e-9  # relative: the bore spans the host along the axis


class Infeasible(Exception):
    """A supported bore that no piece count up to the limit decomposes within the tolerance; `reason` says why."""


@dataclass(frozen=True)
class Piece:
    """One box in the host's own axes: `center` (metres from the host's centre), `size` along the host's axes, and `angle`
    (radians) of a further rotation about the host's axis `k` (0 for strips; staves of a ring have it)."""

    center: tuple[float, float, float]
    size: tuple[float, float, float]
    angle: float = 0.0


@dataclass(frozen=True)
class RingStats:
    staves: int
    closed: bool
    inner_deviation: float  # m, max radial distance the proxy's bore wall is from the real one
    outer_deviation: float  # m, max radial distance the proxy's outer surface is inside the real one


@dataclass(frozen=True)
class BorePlan:
    """A supported through-bore: the host, the void, and what `decompose` needs."""

    host: Placed
    void: Placed
    k: int  # host axis the bore runs along
    i: int
    j: int  # the other two host axes; strips are cut across `j`
    bore: tuple[float, float]  # bore centre along axes i and j, from the host's centre
    sizes: tuple[float, float, float]  # host extents along its own axes
    radius: float
    is_tube: bool


@dataclass(frozen=True)
class Decomposition:
    plan: BorePlan
    layout: str  # "strips" | "ring"
    pieces: tuple[Piece, ...]
    union_volume: float  # m^3
    net_volume: float  # m^3, host minus bore
    ring: RingStats | None

    @property
    def error(self) -> float:
        """Signed: (union - net) / net."""
        return (self.union_volume - self.net_volume) / self.net_volume


def _col(p: Placed, i: int) -> tuple[float, float, float]:
    r = p.rotation
    return (r[0][i], r[1][i], r[2][i])


def _to_host(host: Placed, w: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(_col(host, i)[a] * w[a] for a in range(3)) for i in range(3))  # type: ignore[return-value]


def plan_through_bore(host: Placed, void: Placed) -> BorePlan | str:
    """The plan for `void` in `host`, or the reason it is not a supported through-bore."""
    vp, hp = void.component.primitive, host.component.primitive
    if not isinstance(vp, Cylinder):
        return f"a {vp.kind} void is not a cylinder"
    if not isinstance(hp, (Box, Cylinder)):
        return f"its host is a {hp.kind}"
    radius, length = void.dims["radius"], void.dims["length"]
    d = _to_host(host, _col(void, 2))
    c = _to_host(host, tuple(void.center[a] - host.center[a] for a in range(3)))  # type: ignore[arg-type]
    if isinstance(hp, Box):
        sizes = (host.dims["size_x"], host.dims["size_y"], host.dims["size_z"])
        axis = max(range(3), key=lambda a: abs(d[a]))
    else:
        sizes = (2 * host.dims["radius"], 2 * host.dims["radius"], host.dims["length"])
        axis = 2
    k = axis
    drift = math.sqrt(sum(d[a] ** 2 for a in range(3) if a != k)) * length / 2
    if abs(d[k]) < 0.5 or drift > _PARALLEL_DRIFT * radius:
        return "its axis is not parallel to an axis of the host" if isinstance(hp, Box) else "its axis is not the host's axis"
    if abs(length - sizes[k]) > _LEN_TOL * sizes[k] or abs(c[k]) > _LEN_TOL * sizes[k]:
        return "it does not go through the host (a blind pocket or a partial hole)"
    i, j = [a for a in range(3) if a != k]
    return BorePlan(host, void, k, i, j, (c[i], c[j]), sizes, radius, isinstance(hp, Cylinder))


def decompose(plan: BorePlan, tolerance: float) -> Decomposition:
    """Pieces for `plan` with `|error| <= tolerance` (a fraction of host minus bore), or `Infeasible`."""
    if plan.is_tube:
        return _ring(plan, tolerance)
    return _strips(plan, tolerance)


# --- plate: strips -----------------------------------------------------------------------------------------------------


def _half_width(f2: float) -> float:
    return math.sqrt(f2) if f2 > 0.0 else 0.0


def _boundaries(b: float, hy: float, r: float, n: int) -> list[float]:
    """Strip boundaries across j: the bore's cosine grid and the plate's edges (`-b`, `b`, half-size along j), with
    boundaries nearer than `MIN_STRIP_FRACTION * r` to a neighbour merged. The edges and the bore centre are kept."""
    keep = {-b, b, hy}
    verts = sorted({hy - r * math.cos(math.pi * m / n) for m in range(n + 1)} | keep)
    gap = MIN_STRIP_FRACTION * r
    changed = True
    while changed:
        changed = False
        for idx in range(len(verts) - 1):
            lo, hi = verts[idx], verts[idx + 1]
            if hi - lo < gap:
                drop = lo if lo not in keep else hi
                if drop in keep:
                    continue
                verts.remove(drop)
                changed = True
                break
    return verts


def _strips(plan: BorePlan, tolerance: float) -> Decomposition:
    i, j, k = plan.i, plan.j, plan.k
    a, b = plan.sizes[i] / 2, plan.sizes[j] / 2
    hx, hy = plan.bore
    r, length = plan.radius, plan.sizes[k]
    net = (4.0 * a * b - math.pi * r * r) * length
    scale = max(a, b, abs(hx), abs(hy), r)
    worst = 0.0
    for n in range(4, MAX_STRIPS + 1, 2):
        verts = _boundaries(b, hy, r, n)
        pieces: list[Piece] = []
        for v0, v1 in zip(verts, verts[1:]):
            if v1 - v0 <= 1e-12 * scale:
                continue
            # The bore's centre line is always a boundary, so within a strip the chord only grows or only shrinks.
            s = max(_half_width(r * r - (v0 - hy) ** 2), _half_width(r * r - (v1 - hy) ** 2))
            for p_lo, p_hi in (((-a, hx - s), (hx + s, a)) if s > 0.0 else ((-a, a),)):
                if p_hi - p_lo > 1e-12 * scale:
                    centre, size = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
                    centre[i], centre[j] = (p_lo + p_hi) / 2, (v0 + v1) / 2
                    size[i], size[j], size[k] = p_hi - p_lo, v1 - v0, length
                    pieces.append(Piece(tuple(centre), tuple(size)))  # type: ignore[arg-type]
        union = sum(p.size[0] * p.size[1] * p.size[2] for p in pieces)
        worst = (net - union) / net
        if worst <= tolerance:
            return Decomposition(plan, "strips", tuple(pieces), union, net, None)
    raise Infeasible(
        f"cannot be cut into boxes within {tolerance:.3g} of its volume using up to {MAX_STRIPS} strips "
        f"(it still misses {worst:.3g}); raise the tolerance"
    )


# --- tube: ring of staves ----------------------------------------------------------------------------------------------


def _clip(subject: list[tuple[float, float]], clip: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convex polygon intersection (Sutherland-Hodgman), both counter-clockwise."""

    def left(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0.0

    def cut(p, q, a, b):
        x1, y1, x2, y2, x3, y3, x4, y4 = *p, *q, *a, *b
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / ((x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4))
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    out = subject
    for idx in range(len(clip)):
        a, b = clip[idx], clip[(idx + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break
        prev = inp[-1]
        for cur in inp:
            if left(cur, a, b):
                if not left(prev, a, b):
                    out.append(cut(prev, cur, a, b))
                out.append(cur)
            elif left(prev, a, b):
                out.append(cut(prev, cur, a, b))
            prev = cur
    return out


def _area(poly: list[tuple[float, float]]) -> float:
    if len(poly) < 3:
        return 0.0
    return abs(sum(poly[m][0] * poly[(m + 1) % len(poly)][1] - poly[(m + 1) % len(poly)][0] * poly[m][1] for m in range(len(poly)))) / 2.0


def _stave(r: float, b: float, w: float, angle: float) -> list[tuple[float, float]]:
    c, s = math.cos(angle), math.sin(angle)
    return [(c * x - s * y, s * x + c * y) for x, y in ((r, -w / 2), (b, -w / 2), (b, w / 2), (r, w / 2))]


def _reach(b: float, w: float, a: float) -> float:
    """Farthest radius at which a ray at angle `a` from a stave's axis is still inside it."""
    return min(b / math.cos(a), w / (2.0 * math.sin(a)) if a > 0.0 else math.inf)


def _closed(r: float, b: float, w: float, theta: float) -> bool:
    """Every ray between two neighbouring staves meets their union in one interval (see the module docstring)."""
    psi0 = math.atan(w / (2.0 * r))
    phi = max(0.0, theta - psi0)
    return r * math.cos(phi) <= b * math.cos(theta - phi) * (1.0 - 1e-12)


def _outer_reach_min(r: float, b: float, w: float, theta: float) -> float:
    """Smallest radius, over all directions, up to which the ring's outer surface reaches: the deepest notch between two
    staves. A ray at angle `phi` from one stave's axis is inside it for radii in `[r / cos(phi), min(b / cos(phi),
    w / (2 sin(phi)))]`, so the outer reach of the pair at `phi` is the larger of the two upper ends. Taken over 4096 rays
    across half a notch (`phi = 0 .. theta / 2`; the other half is the mirror image), plus the two ends exactly: the value
    is an upper bound of the true minimum that is within `R * theta^2 / 4096` of it for the shapes searched."""
    psi0 = math.atan(w / (2.0 * r))

    def reach(phi: float) -> float:
        up = 0.0
        for angle in (phi, theta - phi):
            if angle <= psi0:
                up = max(up, _reach(b, w, angle))
        return up

    return min(reach(theta / 2.0 * m / 4096) for m in range(4097))


def _ring(plan: BorePlan, tolerance: float) -> Decomposition:
    """Ring of staves around the **bore's** axis. An off-centre bore (offset `e` from the tube's axis) is built with the outer
    radius `R - e`, the largest circle about the bore's axis that lies inside the tube, so the ring never leaves the tube; the
    thick side of the wall is then missed and the tolerance sees it."""
    r, true_r, length = plan.radius, plan.sizes[0] / 2.0, plan.sizes[2]
    ex, ey = plan.bore
    offset = math.hypot(ex, ey)
    big_r = true_r - offset
    net = math.pi * (true_r * true_r - r * r) * length
    if not big_r > r:
        raise Infeasible("has its bore too close to the tube's outer wall for any ring around the bore's axis")
    worst, why = 1.0, "its wall is too thin for any ring of boxes that stays closed"
    for staves in range(6, MAX_STAVES + 1):
        theta = 2.0 * math.pi / staves
        low = 2.0 * r * math.tan(theta / 2.0)
        best: tuple[float, float, float] | None = None  # (union area, w, b)
        for mult in _W_MULTIPLIERS:
            w = low * mult
            b2 = big_r * big_r - w * w / 4.0
            if b2 <= r * r or w >= 2.0 * r * math.tan(theta):
                continue
            b = math.sqrt(b2)
            if not _closed(r, b, w, theta):
                continue
            s0 = _stave(r, b, w, 0.0)
            union = staves * ((b - r) * w - _area(_clip(s0, _stave(r, b, w, theta))))
            if best is None or union > best[0]:
                best = (union, w, b)
        if best is None:
            continue
        union_area, w, b = best
        union = union_area * length
        worst = (net - union) / net
        if worst <= tolerance:
            rho = (r + b) / 2.0
            pieces = tuple(
                Piece((ex + rho * math.cos(a), ey + rho * math.sin(a), 0.0), (b - r, w, length), a)
                for a in (theta * m for m in range(staves))
            )
            stats = RingStats(staves, True, r / math.cos(theta / 2.0) - r, offset + big_r - _outer_reach_min(r, b, w, theta))
            return Decomposition(plan, "ring", pieces, union, net, stats)
        why = f"it still misses {worst:.3g} of its volume with {staves} boxes"
    raise Infeasible(f"cannot be made into a closed ring of at most {MAX_STAVES} boxes within {tolerance:.3g} of its volume ({why}); raise the tolerance")
