"""Collision proxy of a part, derived from its shape recipe (B-01b), with the volume error against the recipe.

Engine-independent result model. The computation is `kinetra_engine.parts.collision_proxy`; mapping the geoms to an
engine's geometry (MuJoCo `box`, `cylinder`, `sphere`) is the compiler's job (X-01a), not this module's. Physics data
reaches the engine as this data, never as an engine fragment (`docs/architecture/client-adapter.md` A1).

- **Primitives only.** A proxy is a set of analytic primitives (`box`, `cylinder`, `sphere`) in the part's local frame
  (`conventions.py`), the same primitives and conventions as the shape recipe (`shape.py`): box `size_*` are full extents,
  the cylinder axis is the geom's local z. Each is convex, so each maps to one engine primitive geom. There is no mesh
  kind: the visual mesh (B-01c) is never a collision shape, and the type cannot hold one.
- **Voids are not representable.** A convex primitive cannot have a hole. The proxy is the added components; a subtracted
  component (hole, pocket) is **filled** and listed in `filled_voids` with its volume. The proxy therefore never has less
  volume than the recipe, and the difference is reported, not hidden: `volume_error` is
  `(proxy volume - recipe volume) / recipe volume`, zero when the recipe has no voids.
- **Badge.** Every derived number is badge `sim`; the shape recipe, the parameter values used and their badges travel in
  `derivation`, as in `massprops.py`.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import ID_PATTERN, Unit
from .geometry import Name, Quaternion
from .massprops import PRIMITIVE_DIMENSIONS, DerivedScalar, Dimension, ParameterUse, SimProvenance
from .provenance import Badge, Number, Provenance

_VOLUME_REL_TOL = 1e-9


def _primitive_volume(primitive: str, d: dict[str, float]) -> float:
    if primitive == "box":
        return d["size_x"] * d["size_y"] * d["size_z"]
    if primitive == "cylinder":
        return math.pi * d["radius"] ** 2 * d["length"]
    return 4.0 / 3.0 * math.pi * d["radius"] ** 3


class ProxyGeom(BaseModel):
    """One convex primitive of the proxy, in the part frame.

    `dimensions` are resolved lengths in metres under the names `shape.py` gives them (`size_x`, `radius`, `length`, ...),
    `center` its centre in metres and `orientation` its rotation about that centre. `id` is the id of the added shape
    component it copies; the geom is that component's primitive, unchanged. `volume` is in m^3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Literal["box", "cylinder", "sphere"]
    dimensions: tuple[Dimension, ...]
    center: tuple[Number, Number, Number]
    orientation: Quaternion
    volume: Number = Field(gt=0.0)

    @model_validator(mode="after")
    def _dimensions_fit_the_primitive(self) -> "ProxyGeom":
        got = tuple(d.name for d in self.dimensions)
        want = PRIMITIVE_DIMENSIONS[self.primitive]
        if got != want:
            raise ValueError(f"a {self.primitive} has dimensions {list(want)}, got {list(got)}")
        if not all(d.value > 0.0 for d in self.dimensions):
            raise ValueError("every dimension must be above zero")
        want_volume = _primitive_volume(self.primitive, {d.name: d.value for d in self.dimensions})
        if abs(self.volume - want_volume) > _VOLUME_REL_TOL * want_volume:
            raise ValueError(f"volume {self.volume} does not match the {self.primitive}'s dimensions ({want_volume})")
        return self

    def dimension(self, name: str) -> float:
        return next(d.value for d in self.dimensions if d.name == name)


class FilledVoid(BaseModel):
    """A subtracted shape component the proxy could not keep: it is solid in the proxy. `volume` [m^3] is what the proxy
    gained from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Literal["box", "cylinder", "sphere"]
    volume: Number = Field(gt=0.0)


class ProxyDerivation(BaseModel):
    """What the proxy was derived from: the recipe and the parameter values, with their badges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["added-primitives"] = "added-primitives"
    shape: Provenance
    parameters: tuple[ParameterUse, ...]
    input_badges: tuple[Badge, ...]
    assumptions: tuple[str, ...]

    @model_validator(mode="after")
    def _input_badges_are_the_inputs_badges(self) -> "ProxyDerivation":
        order = list(Badge)
        want = tuple(sorted({self.shape.badge, *(u.value.badge for u in self.parameters)}, key=order.index))
        if self.input_badges != want:
            raise ValueError(f"input_badges must be {[b.value for b in want]} (the badges of the inputs listed), got {[b.value for b in self.input_badges]}")
        return self


class CollisionProxy(SimProvenance):
    """The collision proxy of one part.

    `proxy_volume` and `recipe_volume` are the volumes of the geoms and of the shape recipe (added minus voids, the volume
    `MassProperties` reports); `volume_error` is `(proxy - recipe) / recipe`, dimensionless and never negative.
    `filled_voids` lists every void the proxy filled; their volumes add up to `proxy_volume - recipe_volume`.
    """

    part_id: str = Field(pattern=ID_PATTERN)
    geoms: tuple[ProxyGeom, ...] = Field(min_length=1)
    filled_voids: tuple[FilledVoid, ...]
    proxy_volume: DerivedScalar
    recipe_volume: DerivedScalar
    volume_error: DerivedScalar
    derivation: ProxyDerivation

    @model_validator(mode="after")
    def _consistent(self) -> "CollisionProxy":
        ids = [g.id for g in self.geoms]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate geom id")
        if len({v.id for v in self.filled_voids}) != len(self.filled_voids):
            raise ValueError("duplicate filled void id")
        for field, unit in (("proxy_volume", Unit.M3), ("recipe_volume", Unit.M3), ("volume_error", Unit.ONE)):
            if getattr(self, field).unit is not unit:
                raise ValueError(f"{field} must be in {unit.value!r}")
        proxy, recipe = self.proxy_volume.value, self.recipe_volume.value
        if not recipe > 0.0:
            raise ValueError("recipe_volume must be above zero")
        geoms = sum(g.volume for g in self.geoms)
        voids = sum(v.volume for v in self.filled_voids)
        if abs(proxy - geoms) > _VOLUME_REL_TOL * max(proxy, geoms):
            raise ValueError("proxy_volume must be the sum of the geom volumes")
        if abs(proxy - recipe - voids) > _VOLUME_REL_TOL * max(proxy, recipe):
            raise ValueError("proxy_volume - recipe_volume must be the sum of the filled void volumes")
        if abs(self.volume_error.value - (proxy - recipe) / recipe) > _VOLUME_REL_TOL * max(1.0, abs(self.volume_error.value)):
            raise ValueError("volume_error must be (proxy_volume - recipe_volume) / recipe_volume")
        return self
