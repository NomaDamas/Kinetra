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
  - `void-decomposition` (B-01f): an added component with a through-bore is replaced by box pieces whose union
    **approximates** the component minus the bore; each such void is listed in `decomposed_voids` with its host's volume
    error. The approximation is stated: `derivation.tolerance` (a badged `Quantity`: `default` when the caller gave none,
    otherwise the caller's) bounds `|error|` of **every decomposed host** on its own, as a fraction of that host's volume
    minus its bore. Voids the decomposition does not cover stay in `filled_voids` (a part may have both), each with the
    reason in `derivation.assumptions`. Pieces of a ring (tube) overlap each other: that is allowed in a collision (only
    mass needs disjoint solids, and mass never comes from the proxy), so a host's `union_volume` is its own number and
    `proxy_volume` adds the union volumes, not the sum of the geom volumes.
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
from .provenance import Badge, Number, Provenance, Quantity

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


class RingReport(BaseModel):
    """How a tube's ring of boxes sits against the real tube. `wall_closed`: every ray from the axis enters the wall once
    and leaves once, so there is no radial slit (the model rejects `False`). `inner_deviation` [m] is the largest radial
    distance the proxy's bore wall is from the real bore (towards the wall); `outer_deviation` [m] the largest the
    proxy's outer surface is inside the real outer cylinder (the notches between boxes)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    staves: int = Field(ge=3)
    wall_closed: bool
    inner_deviation: Number = Field(ge=0.0)
    outer_deviation: Number = Field(ge=0.0)

    @model_validator(mode="after")
    def _closed(self) -> "RingReport":
        if not self.wall_closed:
            raise ValueError("a ring with a radial slit in its wall is not a tube: wall_closed must be true")
        return self


class DecomposedVoid(BaseModel):
    """A subtracted shape component the proxy kept as a gap: the pieces of its `host` (the added component that contains
    it) leave this void empty.

    `volume` is the void's volume, `host_volume` the host primitive's, `union_volume` the volume of the union of the host's
    pieces (all in m^3), and `error` = `(union_volume - (host_volume - volume)) / (host_volume - volume)` the signed error
    of this host alone. `layout`: `strips` (disjoint boxes cut across a plate) or `ring` (boxes around a tube's axis,
    overlapping; `ring` then carries the report)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Literal["box", "cylinder", "sphere"]
    host: Name
    volume: Number = Field(gt=0.0)
    host_volume: Number = Field(gt=0.0)
    union_volume: Number = Field(gt=0.0)
    error: Number
    layout: Literal["strips", "ring"]
    ring: RingReport | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "DecomposedVoid":
        net = self.host_volume - self.volume
        if not net > 0.0:
            raise ValueError("host_volume must exceed the void's volume")
        if abs(self.error - (self.union_volume - net) / net) > _VOLUME_REL_TOL * max(1.0, abs(self.error)):
            raise ValueError("error must be (union_volume - (host_volume - volume)) / (host_volume - volume)")
        if (self.layout == "ring") != (self.ring is not None):
            raise ValueError("a ring layout carries its ring report, a strips layout does not")
        return self


class ProxyDerivation(BaseModel):
    """What the proxy was derived from: the recipe and the parameter values, with their badges, and how the voids were
    handled. `tolerance` (a fraction, unit `1`, badge `default` when the engine's default, otherwise the caller's) is the
    bound on every decomposed host's `|error|`; it is present exactly when `method` is `void-decomposition`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["added-primitives", "void-decomposition"]
    tolerance: Quantity | None = None
    shape: Provenance
    parameters: tuple[ParameterUse, ...]
    input_badges: tuple[Badge, ...]
    assumptions: tuple[str, ...]

    @model_validator(mode="after")
    def _input_badges_are_the_inputs_badges(self) -> "ProxyDerivation":
        if (self.method == "void-decomposition") != (self.tolerance is not None):
            raise ValueError("tolerance is given exactly when method is 'void-decomposition'")
        if self.tolerance is not None:
            if self.tolerance.unit is not Unit.ONE or not 0.0 < self.tolerance.value <= 1.0:
                raise ValueError("tolerance is a fraction in (0, 1], unit '1'")
            if self.tolerance.badge is Badge.SIM:
                raise ValueError("a tolerance is chosen, not computed: badge 'sim' is not allowed")
        order = list(Badge)
        want = tuple(sorted({self.shape.badge, *(u.value.badge for u in self.parameters)}, key=order.index))
        if self.input_badges != want:
            raise ValueError(f"input_badges must be {[b.value for b in want]} (the badges of the inputs listed), got {[b.value for b in self.input_badges]}")
        return self


class CollisionProxy(SimProvenance):
    """The collision proxy of one part.

    `proxy_volume` and `recipe_volume` are the volumes of the proxy (the union of its geoms) and of the shape recipe (added
    minus voids, the volume `MassProperties` reports); `volume_error` is `(proxy - recipe) / recipe`, dimensionless and
    **signed**. In every proxy `proxy_volume - recipe_volume` = the sum of `filled_voids` volumes + the sum of
    `union_volume - (host_volume - volume)` over `decomposed_voids`.

    - `added-primitives`: `decomposed_voids` is empty, every geom is its component unchanged (`id == component`), the
      geoms do not overlap each other and `proxy_volume` is their sum; the error is never negative.
    - `void-decomposition`: `decomposed_voids` is not empty. A host's geoms are its pieces (`component` = the host's id), the
      rest are components unchanged. `|error|` of each decomposed host is within `derivation.tolerance`. The decomposition the
      engine builds is inside the recipe's material, so each host's error is never positive; the model does not require it.

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
        void_ids = [v.id for v in self.filled_voids] + [v.id for v in self.decomposed_voids]
        if len(set(void_ids)) != len(void_ids):
            raise ValueError("duplicate void id")
        hosts = [v.host for v in self.decomposed_voids]
        if len(set(hosts)) != len(hosts):
            raise ValueError("a host has one decomposed void")
        for field, unit in (("proxy_volume", Unit.M3), ("recipe_volume", Unit.M3), ("volume_error", Unit.ONE)):
            if getattr(self, field).unit is not unit:
                raise ValueError(f"{field} must be in {unit.value!r}")
        proxy, recipe = self.proxy_volume.value, self.recipe_volume.value
        if not recipe > 0.0:
            raise ValueError("recipe_volume must be above zero")
        error = self.volume_error.value
        if abs(error - (proxy - recipe) / recipe) > _VOLUME_REL_TOL * max(1.0, abs(error)):
            raise ValueError("volume_error must be (proxy_volume - recipe_volume) / recipe_volume")
        by_component: dict[str, list[ProxyGeom]] = {}
        for g in self.geoms:
            by_component.setdefault(g.component, []).append(g)
        kept = 0.0  # volume of the components that are copied unchanged
        for component, geoms in by_component.items():
            if component not in hosts:
                if len(geoms) != 1 or geoms[0].id != component:
                    raise ValueError(f"component {component!r} is copied unchanged: one geom whose id is the component's")
                kept += geoms[0].volume
        union = 0.0
        extra = 0.0
        for v in self.decomposed_voids:
            pieces = by_component.get(v.host)
            if not pieces:
                raise ValueError("every decomposed void's host must have at least one piece")
            total = sum(g.volume for g in pieces)
            if any(g.primitive != "box" for g in pieces):
                raise ValueError("the pieces of a decomposed host are boxes")
            if v.layout == "strips" and abs(v.union_volume - total) > _VOLUME_REL_TOL * max(v.union_volume, total):
                raise ValueError("the strips of a host are disjoint: union_volume must be the sum of their volumes")
            if v.layout == "ring" and v.union_volume > total * (1.0 + _VOLUME_REL_TOL):
                raise ValueError("union_volume of a ring cannot exceed the sum of its boxes' volumes")
            union += v.union_volume
            extra += v.union_volume - (v.host_volume - v.volume)
        if abs(proxy - (kept + union)) > _VOLUME_REL_TOL * max(proxy, kept + union):
            raise ValueError("proxy_volume must be the sum of the copied geom volumes and the hosts' union volumes")
        filled = sum(v.volume for v in self.filled_voids)
        if abs(proxy - recipe - (filled + extra)) > _VOLUME_REL_TOL * max(proxy, recipe):
            raise ValueError("proxy_volume - recipe_volume must be the sum of the filled void volumes and the decomposed hosts' errors")
        if self.derivation.method == "added-primitives":
            if self.decomposed_voids:
                raise ValueError("an added-primitives proxy has no decomposed voids")
        else:
            if not self.decomposed_voids:
                raise ValueError("a void-decomposition proxy lists the voids it decomposed")
            tolerance = self.derivation.tolerance
            assert tolerance is not None  # ProxyDerivation ties it to the method
            for v in self.decomposed_voids:
                if abs(v.error) > tolerance.value * (1.0 + _VOLUME_REL_TOL):
                    raise ValueError(f"|error| {abs(v.error)} of host {v.host!r} exceeds the stated tolerance {tolerance.value}")
        return self
