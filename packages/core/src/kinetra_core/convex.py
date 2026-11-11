"""Convex primitives in a frame: support functions, separation and containment (B-01a; moved from `kinetra_engine.parts`
so the placement check of the validator, C-02c, shares the exact tests the mass computation uses).

The mass computation sums component volumes, so it is only right when added components do not overlap and voids sit
inside the material. Two convex bodies have disjoint interiors exactly when a plane separates them; one convex body is
inside another exactly when the second contains the first's extent in every direction. Both are asked with the support
function `h(n) = max over the body of n . x`.

Separation looks for a separating direction among the face normals, axes, axis cross products, centre-line and
nearest-point directions that decide box-box, box-cylinder side and sphere contacts, then a fixed fibonacci set of
directions. Overlap is never missed. A pair of bodies that do not overlap but touch or nearly touch along a feature none
of these directions names (two oblique cylinders, edge to edge) can be reported as overlapping: a rejection, never a
silent double count.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .geometry import Quaternion
from .shape import Box, Cylinder, Sphere

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]  # rows

_N_FIBONACCI = 2048


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec | None:
    n = norm(a)
    return None if n < 1e-12 else scale(a, 1.0 / n)


@dataclass(frozen=True)
class Body:
    """A primitive placed in the part frame. `axes` are the body's local x, y, z as part-frame unit vectors."""

    kind: str  # "box" | "cylinder" | "sphere"
    center: Vec
    axes: tuple[Vec, Vec, Vec]
    half: Vec  # box: half extents. cylinder: (radius, radius, half length). sphere: (r, r, r)

    @property
    def axis(self) -> Vec:
        """Cylinder axis (local z)."""
        return self.axes[2]

    def support(self, n: Vec) -> float:
        c = dot(self.center, n)
        if self.kind == "box":
            return c + sum(self.half[i] * abs(dot(self.axes[i], n)) for i in range(3))
        if self.kind == "cylinder":
            axis = self.axes[2]
            # The part of n perpendicular to the axis, computed directly: sqrt(1 - t^2) loses everything near t = 1.
            return c + self.half[2] * abs(dot(axis, n)) + self.half[0] * norm(sub(n, scale(axis, dot(axis, n))))
        return c + self.half[0]

    def corners(self) -> list[Vec]:
        out = []
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    p = self.center
                    p = add(p, scale(self.axes[0], sx * self.half[0]))
                    p = add(p, scale(self.axes[1], sy * self.half[1]))
                    p = add(p, scale(self.axes[2], sz * self.half[2]))
                    out.append(p)
        return out

    def nearest_to(self, p: Vec) -> Vec:
        """The point of a box or cylinder closest to `p`."""
        d = sub(p, self.center)
        if self.kind == "box":
            q = self.center
            for i in range(3):
                t = max(-self.half[i], min(self.half[i], dot(d, self.axes[i])))
                q = add(q, scale(self.axes[i], t))
            return q
        t = max(-self.half[2], min(self.half[2], dot(d, self.axis)))
        radial = sub(d, scale(self.axis, dot(d, self.axis)))
        rn = norm(radial)
        if rn > self.half[0]:
            radial = scale(radial, self.half[0] / rn)
        return add(add(self.center, scale(self.axis, t)), radial)

    def farthest_from(self, p: Vec) -> float:
        """The largest distance from `p` to any point of the body."""
        if self.kind == "box":
            return max(norm(sub(q, p)) for q in self.corners())
        d = sub(p, self.center)
        if self.kind == "sphere":
            return norm(d) + self.half[0]
        t = dot(d, self.axis)
        s = norm(sub(d, scale(self.axis, t)))
        return math.hypot(s + self.half[0], abs(t) + self.half[2])


_FIB = [
    (
        math.sqrt(1.0 - z * z) * math.cos(i * math.pi * (3.0 - math.sqrt(5.0))),
        math.sqrt(1.0 - z * z) * math.sin(i * math.pi * (3.0 - math.sqrt(5.0))),
        z,
    )
    for i in range(_N_FIBONACCI)
    for z in [1.0 - 2.0 * (i + 0.5) / _N_FIBONACCI]
]


def _candidate_directions(a: Body, b: Body) -> list[Vec]:
    out: list[Vec] = []
    own_a = list(a.axes) if a.kind != "sphere" else []
    own_b = list(b.axes) if b.kind != "sphere" else []
    out.extend(own_a)
    out.extend(own_b)
    for x in own_a:
        for y in own_b:
            c = unit(cross(x, y))
            if c is not None:
                out.append(c)
    d = sub(b.center, a.center)
    u = unit(d)
    if u is not None:
        out.append(u)
    for ball, other in ((a, b), (b, a)):  # a sphere against a box or cylinder: the line from the nearest point
        if ball.kind == "sphere" and other.kind != "sphere":
            u = unit(sub(ball.center, other.nearest_to(ball.center)))
            if u is not None:
                out.append(u)
    for cyl, other in ((a, b), (b, a)):  # the side contact of a cylinder: the centre line with its axial part removed
        if cyl.kind == "cylinder":
            d = sub(other.center, cyl.center)
            p = unit(sub(d, scale(cyl.axis, dot(d, cyl.axis))))
            if p is not None:
                out.append(p)
    return out


def separated(a: Body, b: Body, tol: float) -> bool:
    """True if a plane separates the interiors of `a` and `b` (touching counts as separated within `tol`)."""
    for n in _candidate_directions(a, b) + _FIB:
        for s in (1.0, -1.0):
            m = scale(n, s)
            if a.support(m) + b.support(scale(m, -1.0)) <= tol:
                return True
    return False


def _basis_perp(u: Vec) -> tuple[Vec, Vec]:
    ref = (1.0, 0.0, 0.0) if abs(u[0]) < 0.9 else (0.0, 1.0, 0.0)
    v1 = unit(cross(u, ref))
    assert v1 is not None
    v2 = cross(u, v1)
    return v1, v2


def _perp(v: Vec, axis: Vec) -> Vec:
    return sub(v, scale(axis, dot(v, axis)))


def _rim_within(a: Vec, p1: Vec, p2: Vec, r: float, limit2: float, work: list[int]) -> bool:
    """Certify `|a + r (cos t p1 + sin t p2)|^2 <= limit2` for every t, or find a t where it fails.

    g(t) = |v(t)|^2 is a trigonometric polynomial of degree 2: A0 + A1 cos t + B1 sin t + A2 cos 2t + B2 sin 2t, with
    A0 = |a|^2 + r^2 (|p1|^2 + |p2|^2) / 2, (A1, B1) = 2r (a.p1, a.p2), (A2, B2) = r^2 ((|p1|^2 - |p2|^2) / 2, p1.p2).
    Hence g <= A0 + R1 + R2 everywhere (R1, R2 the amplitudes), and |g''| <= M = R1 + 4 R2. On an interval of width w
    around m, g <= g(m) + |g'(m)| w/2 + M w^2/8. Intervals whose bound is within the limit are discharged, the others are
    halved; a sampled point above the limit is a counterexample. `work` is the evaluation budget: when it runs out the
    answer is False (a rejection), never an unproven True.
    """
    a0 = dot(a, a) + r * r * (dot(p1, p1) + dot(p2, p2)) / 2.0
    a1, b1 = 2.0 * r * dot(a, p1), 2.0 * r * dot(a, p2)
    a2, b2 = r * r * (dot(p1, p1) - dot(p2, p2)) / 2.0, r * r * dot(p1, p2)
    r1, r2 = math.hypot(a1, b1), math.hypot(a2, b2)
    if a0 + r1 + r2 <= limit2:
        return True
    big_m = r1 + 4.0 * r2

    def g(t: float) -> float:
        return a0 + a1 * math.cos(t) + b1 * math.sin(t) + a2 * math.cos(2.0 * t) + b2 * math.sin(2.0 * t)

    def dg(t: float) -> float:
        return -a1 * math.sin(t) + b1 * math.cos(t) - 2.0 * a2 * math.sin(2.0 * t) + 2.0 * b2 * math.cos(2.0 * t)

    stack = [(0.0, 2.0 * math.pi)]
    while stack:
        lo, hi = stack.pop()
        if work[0] <= 0:
            return False
        work[0] -= 1
        m, w = 0.5 * (lo + hi), hi - lo
        gm = g(m)
        if gm > limit2:
            return False
        if gm + abs(dg(m)) * w / 2.0 + big_m * w * w / 8.0 <= limit2:
            continue
        stack.append((lo, m))
        stack.append((m, hi))
    return True


_RIM_BUDGET = 400_000


def _within_radius(inner: Body, outer: Body, tol: float) -> bool:
    """True if every point of `inner` is within `outer.half[0] + tol` of the line through `outer`'s axis."""
    limit = outer.half[0] + tol
    axis, oc = outer.axis, outer.center
    if inner.kind == "box":  # convex function on a polytope: the maximum is at a corner
        return all(norm(_perp(sub(q, oc), axis)) <= limit for q in inner.corners())
    if inner.kind == "sphere":
        return norm(_perp(sub(inner.center, oc), axis)) + inner.half[0] <= limit
    # cylinder: |P(p - oc)| is convex, so its maximum over the solid is on one of the two rim circles
    e1, e2 = _basis_perp(inner.axis)
    p1, p2 = _perp(e1, axis), _perp(e2, axis)
    work = [_RIM_BUDGET]
    for end in (1.0, -1.0):
        a = _perp(sub(add(inner.center, scale(inner.axis, end * inner.half[2])), oc), axis)
        if not _rim_within(a, p1, p2, inner.half[0], limit * limit, work):
            return False
    return True


def contained(inner: Body, outer: Body, tol: float) -> bool:
    """True if `inner` lies inside `outer` (within `tol`)."""
    if outer.kind == "box":
        for i, ax in enumerate(outer.axes):
            for s in (1.0, -1.0):
                n = scale(ax, s)
                if inner.support(n) > dot(outer.center, n) + outer.half[i] + tol:
                    return False
        return True
    if outer.kind == "sphere":
        return inner.farthest_from(outer.center) <= outer.half[0] + tol
    for s in (1.0, -1.0):
        n = scale(outer.axis, s)
        if inner.support(n) > dot(outer.center, n) + outer.half[2] + tol:
            return False
    return _within_radius(inner, outer, tol)


def rotation(q: Quaternion) -> Mat:
    """Rotation matrix (rows) of a unit quaternion {x, y, z, w}."""
    x, y, z, w = q.x, q.y, q.z, q.w
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n  # the model allows norm 1 +- 1e-6; use the exact rotation
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def make_body(p: Box | Cylinder | Sphere, dims: Mapping[str, float], center: Vec, r: Mat) -> Body:
    """The primitive `p` with resolved `dims` [m], centred at `center`, turned by the rotation matrix `r` (rows)."""
    axes = tuple((r[0][j], r[1][j], r[2][j]) for j in range(3))
    if isinstance(p, Box):
        return Body("box", center, axes, (dims["size_x"] / 2, dims["size_y"] / 2, dims["size_z"] / 2))  # type: ignore[arg-type]
    if isinstance(p, Cylinder):
        return Body("cylinder", center, axes, (dims["radius"], dims["radius"], dims["length"] / 2))  # type: ignore[arg-type]
    return Body("sphere", center, axes, (dims["radius"],) * 3)  # type: ignore[arg-type]
