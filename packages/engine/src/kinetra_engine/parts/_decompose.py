"""Convex decomposition of a part with a round through-hole (B-01f): box pieces whose union approximates the recipe.

A convex primitive has no hole, and a circle is not a finite union of boxes, so the result is an approximation with a
**proved** bound. Two recipes are supported, the two the issue names:

- a **plate with a bore**: an added box and one subtracted cylinder whose axis is parallel to a box axis and whose length
  is the box's extent along it (a through-hole);
- a **tube**: an added cylinder and one subtracted cylinder with the same axis direction and the same length.

Both reduce to a cross-section: a rectangle (plate) or a disc (tube) minus a disc (the bore), extruded along the axis
`k`. The cross-section is cut into strips perpendicular to `q` (the second remaining axis). A strip that does not meet the
bore is one box; a strip that does is two boxes, one each side of the bore. Each box is the strip at its mid-line: its
width follows the host edge and the bore edge at the strip's centre. Strip boundaries are placed at the bore's
`y - r cos(pi j / n)` (and the disc's `-R cos(pi j / n)`), `j = 0..n`, `n` even, so every boundary is closer together
where the circle is steep and the bore centre (and the disc centre) is a boundary.

**Inner approximation.** Inside one strip a circular edge (the bore's half-width, the disc's half-width) is monotone,
because no strip straddles a centre line. A box takes the narrower host width and the wider bore width of the strip's two
ends, so **every piece lies inside the recipe's material**: it never leaves the host and never enters the bore. The union
is a subset of the recipe, so the volume error is never positive and is exactly minus the missed volume. A body that fits
in the real bore fits in the proxy's; the proxy never blocks space the recipe leaves free. The missed area of a strip is
computed in closed form (`integral sqrt(rho^2 - u^2) du`), not sampled. The smallest even `n` whose missed volume
is within the tolerance (`collision.py` picks it, one `n` for the whole part) is used; if none up to `MAX_STRIPS` is, the
proxy is rejected with the reason. Pieces of one host have disjoint interiors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kinetra_core.shape import Box, Cylinder

from ._shape import Placed

# Largest even strip count tried. 2 * n + 2 boxes at most per host.
MAX_STRIPS = 64
_AXIS_TOL = 1e-12  # |cos| of the angle between the bore axis and a host axis, off from 1
_LEN_TOL = 1e-9  # relative: the bore spans the host along the axis


@dataclass(frozen=True)
class Piece:
    """One box of a decomposition, in the host's own axes: `center` (metres from the host's centre) and `size`."""

    center: tuple[float, float, float]
    size: tuple[float, float, float]


@dataclass(frozen=True)
class BorePlan:
    """A supported through-bore: the host, the void, and the numbers `pieces` needs."""

    host: Placed
    void: Placed
    k: int  # host axis the bore runs along
    i: int
    j: int  # the other two host axes; strips are cut perpendicular to `j`
    bore: tuple[float, float]  # bore centre along axes i and j, from the host's centre
    sizes: tuple[float, float, float]  # host extents along its own axes
    radius: float
    is_disc: bool


def _col(p: Placed, i: int) -> tuple[float, float, float]:
    r = p.rotation
    return (r[0][i], r[1][i], r[2][i])


def _to_host(host: Placed, w: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(_col(host, i)[a] * w[a] for a in range(3)) for i in range(3))  # type: ignore[return-value]


def plan_through_bore(host: Placed, void: Placed) -> BorePlan | None:
    """The plan for `void` in `host`, or None when the pair is not a supported through-bore (a box with a cylinder along
    one of its axes spanning it, or a cylinder with a coaxial-direction cylinder spanning it; anything else is a blind
    pocket, a sphere, a skew or partial hole, which this module does not decompose)."""
    if not isinstance(void.component.primitive, Cylinder):
        return None
    hp = host.component.primitive
    if not isinstance(hp, (Box, Cylinder)):
        return None
    d = _to_host(host, _col(void, 2))
    c = _to_host(host, tuple(void.center[a] - host.center[a] for a in range(3)))  # type: ignore[arg-type]
    if isinstance(hp, Box):
        sizes = (host.dims["size_x"], host.dims["size_y"], host.dims["size_z"])
        ks = [a for a in range(3) if abs(d[a]) >= 1.0 - _AXIS_TOL]
        if not ks:
            return None
        k = ks[0]
    else:
        sizes = (2 * host.dims["radius"], 2 * host.dims["radius"], host.dims["length"])
        if abs(d[2]) < 1.0 - _AXIS_TOL:
            return None
        k = 2
    length = void.dims["length"]
    if abs(length - sizes[k]) > _LEN_TOL * sizes[k] or abs(c[k]) > _LEN_TOL * sizes[k]:
        return None
    i, j = [a for a in range(3) if a != k]
    return BorePlan(host, void, k, i, j, (c[i], c[j]), sizes, void.dims["radius"], not isinstance(hp, Box))


def pieces(plan: BorePlan, n: int) -> tuple[tuple[Piece, ...], float]:
    """Box pieces (disjoint interiors, all inside the host minus the bore) for `n` strips (even, >= 4) and the volume
    [m^3] of the host minus the bore that they miss."""
    k, i, j = plan.k, plan.i, plan.j
    length = plan.sizes[k]
    rects, missed = _strips(plan.is_disc, plan.sizes[i] / 2, plan.sizes[j] / 2, plan.bore[0], plan.bore[1], plan.radius, n)
    out = []
    for p_lo, p_hi, q_lo, q_hi in rects:
        centre, size = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        centre[i], centre[j] = (p_lo + p_hi) / 2, (q_lo + q_hi) / 2
        size[i], size[j], size[k] = p_hi - p_lo, q_hi - q_lo, length
        out.append(Piece(tuple(centre), tuple(size)))  # type: ignore[arg-type]
    return tuple(out), missed * length


def _half_width(f2: float) -> float:
    return math.sqrt(f2) if f2 > 0.0 else 0.0


def _arc_area(rho: float, u0: float, u1: float) -> float:
    """Integral of sqrt(rho^2 - u^2) du from u0 to u1 (u0 <= u1, both within [-rho, rho] up to rounding)."""

    def f(u: float) -> float:
        u = max(-rho, min(rho, u))
        return 0.5 * (u * _half_width(rho * rho - u * u) + rho * rho * math.asin(u / rho))

    return f(u1) - f(u0)


def _strips(is_disc: bool, a: float, b: float, hx: float, hy: float, r: float, n: int):
    """Rectangles (p_lo, p_hi, q_lo, q_hi) inside the cross-section, and the area [m^2] of the cross-section they miss.

    Rectangle host: half-sizes `a` (p) and `b` (q). Disc host: radius `a`. The bore has centre (hx, hy), radius `r`. Each
    strip takes the narrower of the host's two edge widths and the wider of the bore's, so a piece never leaves the host
    and never enters the bore. The missed area is the exact area of the strip minus the area of its pieces."""
    verts = {hy - r * math.cos(math.pi * m / n) for m in range(n + 1)}
    if is_disc:
        verts |= {-a * math.cos(math.pi * m / n) for m in range(n + 1)}
        verts.add(0.0)
    else:
        verts |= {-b, b}
    scale = max(a, b, abs(hx), abs(hy), r)
    ordered = sorted(verts)
    rects: list[tuple[float, float, float, float]] = []
    missed = 0.0
    for v0, v1 in zip(ordered, ordered[1:]):
        h = v1 - v0
        vm = (v0 + v1) / 2
        outer = 2.0 * _arc_area(a, v0, v1) if is_disc else 2.0 * a * h
        in_bore = abs(vm - hy) < r
        true_area = outer - (2.0 * _arc_area(r, v0 - hy, v1 - hy) if in_bore else 0.0)
        got = 0.0
        if h > 1e-12 * scale:
            xo = min(_half_width(a * a - v0 * v0), _half_width(a * a - v1 * v1)) if is_disc else a
            if in_bore:
                s = max(_half_width(r * r - (v0 - hy) ** 2), _half_width(r * r - (v1 - hy) ** 2))
                sides = ((-xo, hx - s), (hx + s, xo))
            else:
                sides = ((-xo, xo),)
            for p_lo, p_hi in sides:
                if p_hi - p_lo > 1e-12 * scale:
                    rects.append((p_lo, p_hi, v0, v1))
                    got += (p_hi - p_lo) * h
        missed += max(true_area - got, 0.0) + 4e-15 * scale * scale
    return rects, missed
