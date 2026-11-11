"""Deterministic triangle meshes of the three recipe primitives (B-01c). Part-local frame, metres, right-handed, +Z up.

Pure functions of the dimensions and the module constants below: no randomness, no adaptive refinement, so the same
recipe always yields the same triangles in the same order. Every mesh is closed, outward-wound (counter-clockwise seen
from outside) and carries one unit normal per vertex.

- box: 24 vertices (4 per face, flat normals), 12 triangles. Exact.
- cylinder (axis local z): `CYLINDER_SEGMENTS` side segments, smooth side normals, flat caps with a centre vertex. The
  side is an inscribed polygon, so the mesh volume is `n/2 * sin(2 pi / n) * r^2 * h`, below the true cylinder.
- sphere: `SPHERE_SEGMENTS` meridians and `SPHERE_STACKS` latitude bands, a vertex at each pole (fans, so no degenerate
  triangle), vertices on the sphere. The mesh is inscribed, so its volume is below the true sphere's.

The mesh is for drawing only (A1 in `docs/architecture/client-adapter.md`): mass and inertia come from the closed forms,
the collision proxy from B-01b. How much smaller the drawn volume is: `docs/architecture/part-visual.md`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

CYLINDER_SEGMENTS = 64
SPHERE_SEGMENTS = 48
SPHERE_STACKS = 24

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Mesh:
    """Vertex arrays and counter-clockwise triangles (three indices each), flat tuples."""

    positions: tuple[float, ...]  # x, y, z per vertex
    normals: tuple[float, ...]  # unit, same layout
    indices: tuple[int, ...]

    @property
    def vertex_count(self) -> int:
        return len(self.positions) // 3


class _Builder:
    def __init__(self) -> None:
        self.p: list[float] = []
        self.n: list[float] = []
        self.i: list[int] = []

    def vertex(self, pos: Vec, normal: Vec) -> int:
        self.p.extend(pos)
        self.n.extend(normal)
        return len(self.p) // 3 - 1

    def tri(self, a: int, b: int, c: int) -> None:
        self.i.extend((a, b, c))

    def mesh(self) -> Mesh:
        return Mesh(tuple(self.p), tuple(self.n), tuple(self.i))


# (normal, u, v) with u x v = normal; the face quad is (-u,-v) (u,-v) (u,v) (-u,v), counter-clockwise from outside.
_BOX_FACES: tuple[tuple[Vec, Vec, Vec], ...] = (
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
)


def box(size_x: float, size_y: float, size_z: float) -> Mesh:
    half = (size_x / 2, size_y / 2, size_z / 2)
    b = _Builder()
    for normal, u, v in _BOX_FACES:
        centre = tuple(normal[k] * half[k] for k in range(3))
        corners = []
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corners.append(tuple(centre[k] + su * u[k] * half[k] + sv * v[k] * half[k] for k in range(3)))
        ids = [b.vertex(c, tuple(float(x) for x in normal)) for c in corners]
        b.tri(ids[0], ids[1], ids[2])
        b.tri(ids[0], ids[2], ids[3])
    return b.mesh()


def cylinder(radius: float, length: float, segments: int = CYLINDER_SEGMENTS) -> Mesh:
    half = length / 2
    ring = [(math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    b = _Builder()
    lo = [b.vertex((radius * c, radius * s, -half), (c, s, 0.0)) for c, s in ring]
    hi = [b.vertex((radius * c, radius * s, half), (c, s, 0.0)) for c, s in ring]
    for i in range(segments):
        j = (i + 1) % segments
        b.tri(lo[i], lo[j], hi[j])
        b.tri(lo[i], hi[j], hi[i])
    top_c = b.vertex((0.0, 0.0, half), (0.0, 0.0, 1.0))
    top = [b.vertex((radius * c, radius * s, half), (0.0, 0.0, 1.0)) for c, s in ring]
    for i in range(segments):
        b.tri(top_c, top[i], top[(i + 1) % segments])
    bot_c = b.vertex((0.0, 0.0, -half), (0.0, 0.0, -1.0))
    bot = [b.vertex((radius * c, radius * s, -half), (0.0, 0.0, -1.0)) for c, s in ring]
    for i in range(segments):
        b.tri(bot_c, bot[(i + 1) % segments], bot[i])
    return b.mesh()


def sphere(radius: float, segments: int = SPHERE_SEGMENTS, stacks: int = SPHERE_STACKS) -> Mesh:
    b = _Builder()
    north = b.vertex((0.0, 0.0, radius), (0.0, 0.0, 1.0))
    rings: list[list[int]] = []
    for k in range(1, stacks):
        phi = math.pi * k / stacks  # polar angle from +z
        sp, cp = math.sin(phi), math.cos(phi)
        row = []
        for i in range(segments):
            theta = 2 * math.pi * i / segments
            n = (sp * math.cos(theta), sp * math.sin(theta), cp)
            row.append(b.vertex((radius * n[0], radius * n[1], radius * n[2]), n))
        rings.append(row)
    south = b.vertex((0.0, 0.0, -radius), (0.0, 0.0, -1.0))
    for i in range(segments):
        j = (i + 1) % segments
        b.tri(north, rings[0][i], rings[0][j])
        b.tri(south, rings[-1][j], rings[-1][i])
    for upper, lower in zip(rings, rings[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            b.tri(upper[i], lower[i], lower[j])
            b.tri(upper[i], lower[j], upper[j])
    return b.mesh()


def tessellate(kind: str, dims: Mapping[str, float]) -> Mesh:
    if kind == "box":
        return box(dims["size_x"], dims["size_y"], dims["size_z"])
    if kind == "cylinder":
        return cylinder(dims["radius"], dims["length"])
    if kind == "sphere":
        return sphere(dims["radius"])
    raise ValueError(f"no tessellation for primitive {kind!r}")
