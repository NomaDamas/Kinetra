"""Collision proxy of a part from its shape recipe (B-01b).

The proxy is the recipe's added components, each one a convex analytic primitive copied unchanged (so each maps to one
engine primitive geom). A subtracted component cannot be represented by a convex primitive: it is filled, listed in
`filled_voids`, and the volume it adds is the reported `volume_error`. The visual mesh is never read (B-01c, and the
result type has no mesh kind).

    collision_proxy(part, parameters=None) -> CollisionProxy

Units are SI and the frame is the part's local frame (`kinetra_core.conventions`). Parameters are resolved, checked and
placed exactly as `mass_properties` does (`_shape.resolve_shape`), so a recipe either evaluates for both or for neither.
"""

from __future__ import annotations

from collections.abc import Mapping

from kinetra_core import (
    Badge,
    CollisionProxy,
    DerivedScalar,
    Dimension,
    FilledVoid,
    PartDef,
    Provenance,
    ProxyDerivation,
    ProxyGeom,
    Quantity,
    Source,
    Unit,
)

from ._shape import ShapeError, parameter_uses, resolve_shape

_COMPUTED_BY = "kinetra_engine.parts.collision_proxy (added primitives copied; voids filled)"

_ASSUMPTIONS = (
    "Each added shape component becomes one proxy geom of the same primitive, size, centre and orientation; "
    "no mesh and no approximation of the primitives.",
    "A convex primitive has no hole: every subtracted component is filled in the proxy, so the proxy volume is the "
    "recipe volume plus the filled voids. The error is reported, not removed.",
)


def collision_proxy(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> CollisionProxy:
    """The collision proxy of `part` and its volume error against the shape recipe.

    `parameters` overrides the part's defaults (a `Quantity` in metres, within the parameter's range, with its own badge
    and source), as in `mass_properties`. Raises `ShapeError` for a part without a recipe, a bad parameter value, or a
    recipe that breaks the disjoint-sum rule (`kinetra_core.shape`)."""
    resolved = resolve_shape(part, parameters)
    shape = part.shape  # resolve_shape raised ShapeError if there is none
    assert shape is not None

    adds = [p for p in resolved.placed if p.component.operation == "add"]
    voids = [p for p in resolved.placed if p.component.operation == "subtract"]
    proxy_volume = sum(p.volume for p in adds)
    filled = sum(p.volume for p in voids)
    recipe_volume = proxy_volume - filled
    if not recipe_volume > 0.0:
        raise ShapeError("the voids remove all the material: net volume is not positive")

    geoms = tuple(
        ProxyGeom(
            id=p.component.id,
            primitive=p.component.primitive.kind,
            dimensions=tuple(Dimension(name=n, value=v) for n, v in p.dims.items()),
            center=p.center,
            orientation=p.component.orientation,
            volume=p.volume,
        )
        for p in adds
    )
    uses = parameter_uses(part, resolved)
    badges = sorted({shape.badge, *(u.value.badge for u in uses)}, key=list(Badge).index)
    sim = {"badge": Badge.SIM, "source": Source(ref=_COMPUTED_BY, locator=f"part {part.id}")}
    return CollisionProxy(
        part_id=part.id,
        geoms=geoms,
        filled_voids=tuple(FilledVoid(id=p.component.id, primitive=p.component.primitive.kind, volume=p.volume) for p in voids),
        proxy_volume=DerivedScalar(value=proxy_volume, unit=Unit.M3, **sim),
        recipe_volume=DerivedScalar(value=recipe_volume, unit=Unit.M3, **sim),
        volume_error=DerivedScalar(value=filled / recipe_volume, unit=Unit.ONE, **sim),
        derivation=ProxyDerivation(
            shape=Provenance(badge=shape.badge, source=shape.source),
            parameters=uses,
            input_badges=tuple(badges),
            assumptions=_ASSUMPTIONS,
        ),
        **sim,
    )
