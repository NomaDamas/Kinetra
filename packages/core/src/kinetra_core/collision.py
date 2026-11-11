"""Collision proxy of a part, derived from its shape recipe (B-01b, B-01f), with the signed volume error against the recipe.

Engine-independent result model. The computation is `kinetra_engine.parts.collision_proxy`; mapping the geoms to an
engine's geometry (MuJoCo `box`, `cylinder`, `sphere`) is the compiler's job (X-01a), not this module's. Physics data
reaches the engine as this data, never as an engine fragment (`docs/architecture/client-adapter.md` A1).

- **Primitives only.** A proxy is a set of analytic primitives (`box`, `cylinder`, `sphere`) in the part's local frame
  (`conventions.py`), the same primitives and conventions as the shape recipe (`shape.py`): box `size_*` are full extents,
  the cylinder axis is the geom's local z. Each is convex, so each maps to one engine primitive geom. There is no mesh
  kind: the visual mesh (B-01c) is never a collision shape, and the type cannot hold one.
- **Two methods** (`derivation.method`), because a convex primitive cannot have a hole.
  - `added-primitives` (B-01b): the proxy is the added components, each copied unchanged. A subtracted component (hole,
    pocket) is **filled** and listed in `filled_voids`; the proxy has more volume than the recipe, by exactly the filled
    volumes. There is no tolerance.
  - `void-decomposition` (B-01f): an added component that contains voids is replaced by convex pieces whose union
    **approximates** the component minus its voids; each void is listed in `decomposed_voids`. The approximation is
    stated: `derivation.tolerance` is the bound the computation guarantees on `|volume_error|`. The error is signed (a decomposition may have less volume than the recipe, or more). `proxy_volume` is the sum of the geom
    volumes, which is the volume of their union only when the pieces do not overlap; the engine's decomposition keeps
    them interior-disjoint. Pieces may overlap in a collision (only mass needs disjoint solids, and mass never comes
    from the proxy), but then `proxy_volume` counts the overlap twice.
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
    `center` its centre in metres and `orientation` its rotation about that centre. `component` is the id of the added
    shape component the geom belongs to. With method `added-primitives` the geom is that component's primitive unchanged
    and `id == component`; with `void-decomposition` a component that has voids is several geoms (pieces), each with
    its own `id`. `volume` is in m^3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    component: Name
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


class FilledVoid(BaseModel):
    """A subtracted shape component the proxy could not keep: it is solid in the proxy. `volume` [m^3] is what the proxy
    gained from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Literal["box", "cylinder", "sphere"]
    volume: Number = Field(gt=0.0)


class DecomposedVoid(BaseModel):
    """A subtracted shape component the proxy kept as a gap: the pieces of its `host` (the added component that contains
    it) leave this void empty, up to the tolerance. `volume` [m^3] is the void's own volume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Literal["box", "cylinder", "sphere"]
    host: Name
    volume: Number = Field(gt=0.0)


class ProxyDerivation(BaseModel):
    """What the proxy was derived from: the recipe and the parameter values, with their badges, and how the voids were
    handled. `tolerance` is the bound the decomposition was built to on `|volume_error|` (a fraction of the recipe
    volume); it is present exactly when `method` is `void-decomposition`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["added-primitives", "void-decomposition"]
    tolerance: Number | None = Field(default=None, gt=0.0, le=1.0)
    shape: Provenance
    parameters: tuple[ParameterUse, ...]
    input_badges: tuple[Badge, ...]
    assumptions: tuple[str, ...]

    @model_validator(mode="after")
    def _input_badges_are_the_inputs_badges(self) -> "ProxyDerivation":
        if (self.method == "void-decomposition") != (self.tolerance is not None):
            raise ValueError("tolerance is given exactly when method is 'void-decomposition'")
        order = list(Badge)
        want = tuple(sorted({self.shape.badge, *(u.value.badge for u in self.parameters)}, key=order.index))
        if self.input_badges != want:
            raise ValueError(f"input_badges must be {[b.value for b in want]} (the badges of the inputs listed), got {[b.value for b in self.input_badges]}")
        return self


class CollisionProxy(SimProvenance):
    """The collision proxy of one part.

    `proxy_volume` and `recipe_volume` are the volumes of the geoms and of the shape recipe (added minus voids, the volume
    `MassProperties` reports); `volume_error` is `(proxy - recipe) / recipe`, dimensionless and **signed**.

    - `added-primitives`: `filled_voids` lists every void the proxy filled, `decomposed_voids` is empty, their volumes add
      up to `proxy_volume - recipe_volume` and the error is never negative.
    - `void-decomposition`: `decomposed_voids` lists every void kept as a gap, `filled_voids` is empty, and
      `-derivation.tolerance <= volume_error <= derivation.tolerance`. The sign carries no rule here (a decomposition
      may have less volume than the recipe, or more); the engine's decomposition of round through-bores keeps every piece
      inside the recipe's material, so its error is never positive.

    Mass, centre of mass and inertia never come from the proxy; they come from `MassProperties` (B-01a).
    """

    part_id: str = Field(pattern=ID_PATTERN)
    geoms: tuple[ProxyGeom, ...] = Field(min_length=1)
    filled_voids: tuple[FilledVoid, ...]
    decomposed_voids: tuple[DecomposedVoid, ...]
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
        if len({v.id for v in self.decomposed_voids}) != len(self.decomposed_voids):
            raise ValueError("duplicate decomposed void id")
        for field, unit in (("proxy_volume", Unit.M3), ("recipe_volume", Unit.M3), ("volume_error", Unit.ONE)):
            if getattr(self, field).unit is not unit:
                raise ValueError(f"{field} must be in {unit.value!r}")
        proxy, recipe = self.proxy_volume.value, self.recipe_volume.value
        if not recipe > 0.0:
            raise ValueError("recipe_volume must be above zero")
        geoms = sum(g.volume for g in self.geoms)
        if abs(proxy - geoms) > _VOLUME_REL_TOL * max(proxy, geoms):
            raise ValueError("proxy_volume must be the sum of the geom volumes")
        error = self.volume_error.value
        if abs(error - (proxy - recipe) / recipe) > _VOLUME_REL_TOL * max(1.0, abs(error)):
            raise ValueError("volume_error must be (proxy_volume - recipe_volume) / recipe_volume")
        if self.derivation.method == "added-primitives":
            if self.decomposed_voids:
                raise ValueError("an added-primitives proxy has no decomposed voids")
            if self.derivation.tolerance is not None:
                raise ValueError("an added-primitives proxy states no tolerance")
            if any(g.id != g.component for g in self.geoms):
                raise ValueError("an added-primitives geom is its component unchanged: id must equal component")
            voids = sum(v.volume for v in self.filled_voids)
            if abs(proxy - recipe - voids) > _VOLUME_REL_TOL * max(proxy, recipe):
                raise ValueError("proxy_volume - recipe_volume must be the sum of the filled void volumes")
        else:
            if self.filled_voids:
                raise ValueError("a void-decomposition proxy has no filled voids")
            if not self.decomposed_voids:
                raise ValueError("a void-decomposition proxy lists the voids it decomposed")
            pieced = {g.component for g in self.geoms}
            if any(v.host not in pieced for v in self.decomposed_voids):
                raise ValueError("every decomposed void's host must have at least one piece")
            tolerance = self.derivation.tolerance
            assert tolerance is not None  # ProxyDerivation ties it to the method
            if abs(error) > tolerance * (1.0 + _VOLUME_REL_TOL):
                raise ValueError(f"|volume_error| {abs(error)} exceeds the stated tolerance {tolerance}")
        return self
