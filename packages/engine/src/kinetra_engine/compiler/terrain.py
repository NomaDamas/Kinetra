"""Terrain props of a compiled model (W-05): the project's ramps and steps (`World.terrain_props`, C-01c) as static MJCF geoms.

    terrain_geoms(props) -> tuple[TerrainGeom, ...]

**Geometry** is `kinetra_core.world`'s frame, the same solids the validator's placement check uses (`validator._prop_bodies`):

| prop | MJCF geom |
|---|---|
| ramp (`incline`, `length` the horizontal run, `width`) | `type="mesh"`: the triangular prism with footprint `length` x `width` at z = 0 and rise `length * tan(incline)` above local x = +length / 2, six vertices in the prop frame |
| step (`length`, `width`, `height`) | `type="box"`, half extents `(length / 2, width / 2, height / 2)`, centre at height `height / 2` |

The prop frame is centred on the footprint at (`x`, `y`, 0) and turned by `yaw` about +Z: `pos="x y 0"` (a step's centre `z` is
`height / 2`), `quat="cos(yaw / 2) 0 0 sin(yaw / 2)"`. MuJoCo moves a mesh's vertices to its own centroid and turns the geom
frame to match (XML reference, `mesh`), so the vertices land where they are written in the world.

The geoms sit in `<worldbody>` after the ground: fixed, massless (a world geom has no body to move), and never in contact with
the ground or each other (MuJoCo does not collide geoms of one body). The name is `PROP_GEOM_PREFIX + <prop id>`, which no
instance geom (`<instance>/<proxy geom>`) or project id can be. Friction is `contact.py`'s (X-01e): a prop with a `material`
takes `Material.friction`, a prop without one is the planet's ground (`world.py`) and takes the ground's coefficient, the
nominal or the Monte Carlo sample `to_mjcf` was given (W-03c).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from kinetra_core import RampProp, TerrainProp

PROP_GEOM_PREFIX = "__kinetra_prop_"
"""A prop's geom (and a ramp's mesh) is named `__kinetra_prop_<prop id>`. A project id cannot start with `_` (`ID_PATTERN`)."""

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class TerrainGeom:
    """One prop as an MJCF geom, world frame. `type` `mesh` (a ramp: `vertices` in the prop frame, `size` empty) or `box` (a
    step: `size` the half extents, `vertices` empty). `material` is the prop's, `None` for the planet's ground."""

    prop: str
    kind: Literal["ramp", "step"]
    name: str
    type: Literal["mesh", "box"]
    pos: Vec
    quat: tuple[float, float, float, float]
    size: tuple[float, ...]
    vertices: tuple[Vec, ...]
    material: str | None


def ramp_vertices(length: float, width: float, incline: float) -> tuple[Vec, ...]:
    """The six vertices of a ramp in its frame (`convex.Body.vertices` for a wedge, same order): for y = -width/2 then +width/2,
    the bottom of the slope, the foot of the high end and its top."""
    lx, hy, rise = length / 2, width / 2, length * math.tan(incline)
    return tuple((x, sy * hy, z) for sy in (-1.0, 1.0) for x, z in ((-lx, 0.0), (lx, 0.0), (lx, rise)))


def terrain_geoms(props: tuple[TerrainProp, ...]) -> tuple[TerrainGeom, ...]:
    """The geoms of `props`, in their order (the tree's canonical order: by id)."""
    out = []
    for p in props:
        yaw = p.placement.yaw
        quat = (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))
        name = PROP_GEOM_PREFIX + p.id
        if isinstance(p, RampProp):
            vertices = ramp_vertices(p.length.value, p.width.value, p.incline.value)
            out.append(TerrainGeom(p.id, "ramp", name, "mesh", (p.placement.x, p.placement.y, 0.0), quat, (), vertices, p.material))
        else:
            h = p.height.value
            size = (p.length.value / 2, p.width.value / 2, h / 2)
            out.append(TerrainGeom(p.id, "step", name, "box", (p.placement.x, p.placement.y, h / 2), quat, size, (), p.material))
    return tuple(out)
