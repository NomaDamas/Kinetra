"""Collision proxy of a part from its shape recipe (B-01b, B-01f).

Added components become convex analytic primitives. A subtracted component cannot be one; there are two ways to treat it.

- **Decompose (B-01f)**, when every void of the part is a through-bore of its host (`_decompose.plan_through_bore`: a
  plate with a round hole, a tube; one bore per host): the host becomes box pieces around the bore, so the bore stays
  empty. The union is **inside** the recipe's material (see `_decompose`), so `volume_error` is negative and is, in
  magnitude, the missed fraction of the recipe volume, computed in closed form; it is within `tolerance` (the strip count is
  the smallest even number that gets it there) or the proxy is rejected with the reason (`ShapeError`).
- **Fill (B-01b)**, for every other void (blind pocket, sphere, skew hole, two bores in one host): all voids of the part
  are filled and listed in `filled_voids`; the error is the filled volume, never negative.

The visual mesh is never read (B-01c, and the result type has no mesh kind).

    collision_proxy(part, parameters=None, tolerance=DEFAULT_TOLERANCE) -> CollisionProxy

Units are SI and the frame is the part's local frame (`kinetra_core.conventions`). Parameters are resolved, checked and
placed exactly as `mass_properties` does (`_shape.resolve_shape`), and `recipe_volume` is the same signed sum, so a recipe
evaluates for both or for neither and the two report the same volume bit for bit. Mass, centre of mass and inertia stay
with `mass_properties`; nothing here feeds them.
"""

from __future__ import annotations

from collections.abc import Mapping

from kinetra_core import (
    Badge,
    CollisionProxy,
    DecomposedVoid,
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

from . import _convex as cx
from ._decompose import MAX_STRIPS, BorePlan, pieces, plan_through_bore
from ._shape import Placed, ShapeError, parameter_uses, resolve_shape, signed_volumes

# Upper bound on (volume of the symmetric difference between the decomposed proxy and the recipe) / recipe volume.
# Missed volume as a fraction of the recipe volume. Chosen, not derived: 10 % keeps a 50 mm bore in a 300 x 200 mm plate
# at 8 strips and a tube of outer radius 50 mm and bore radius 40 mm at about 34 strips (a few tens of boxes); tighter
# tolerances or thinner walls cost more pieces (at most MAX_STRIPS strips are tried).
DEFAULT_TOLERANCE = 0.10

_COMPUTED_BY = "kinetra_engine.parts.collision_proxy (convex primitives; voids decomposed or filled)"

_COMMON = (
    "Each added shape component that has no void becomes one proxy geom of the same primitive, size, centre and "
    "orientation; no mesh and no approximation of the primitives.",
)
_FILLED = (
    "A convex primitive has no hole: every subtracted component is filled in the proxy, so the proxy volume is the "
    "recipe volume plus the filled voids. The error is reported, not removed.",
)
_DECOMPOSED = (
    "A round bore is not a finite union of boxes: each added component with a through-bore is replaced by box pieces "
    "(disjoint interiors) cut into strips across the bore. Each box takes the narrower host width and the wider bore "
    "width of its strip, so every piece is inside the recipe's material: the bore is empty in the proxy (a body can enter "
    "or pass through it) and nothing sticks out. The price is volume the proxy misses, so volume_error is negative; it is "
    "computed from the closed-form area of each circular edge, not sampled, and is within the stated tolerance.",
    "Pieces may touch and may overlap in a collision; mass, centre of mass and inertia come from the shape recipe "
    "(MassProperties), never from the proxy geoms.",
)


def _piece_geoms(plan: BorePlan, n: int):
    """(index, centre in the part frame, size along the host's axes) of the pieces of `plan` for `n` strips, and the
    volume the pieces miss."""
    host = plan.host
    out, missed = pieces(plan, n)
    rows = []
    for idx, piece in enumerate(out):
        centre = host.center
        for a in range(3):
            centre = cx.add(centre, cx.scale(host.body.axes[a], piece.center[a]))
        rows.append((idx, centre, piece.size))
    return rows, missed


def _piece_id(host_id: str, idx: int) -> str:
    suffix = f"_p{idx}"
    return host_id[: 64 - len(suffix)] + suffix


def _plans(resolved) -> list[BorePlan] | None:
    """One `BorePlan` per void if every void is a through-bore of the single added component that contains it and no
    host has two bores; otherwise None (the whole part then takes the fill path)."""
    adds = [p for p in resolved.placed if p.component.operation == "add"]
    voids = [p for p in resolved.placed if p.component.operation == "subtract"]
    if not voids:
        return None
    plans: list[BorePlan] = []
    for v in voids:
        hosts = [h for h in adds if cx.contained(v.body, h.body, _HOST_TOL * 2.0 * max(max(v.body.half), max(h.body.half)))]
        plan = plan_through_bore(hosts[0], v) if len(hosts) == 1 else None
        if plan is None:
            return None
        plans.append(plan)
    if len({id(pl.host) for pl in plans}) != len(plans):
        return None
    return plans


_HOST_TOL = 1e-9


def collision_proxy(
    part: PartDef,
    parameters: Mapping[str, Quantity] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> CollisionProxy:
    """The collision proxy of `part` and its signed volume error against the shape recipe.

    `parameters` overrides the part's defaults (a `Quantity` in metres, within the parameter's range, with its own badge
    and source), as in `mass_properties`. `tolerance` (0 < tolerance <= 1) bounds the volume a decomposed proxy misses,
    as a fraction of the recipe volume; it has no effect on a part without through-bores. Raises `ShapeError` for a part without a recipe, a bad parameter value, a recipe that breaks the
    disjoint-sum rule (`kinetra_core.shape`), or a through-bore whose walls are too thin to decompose within `tolerance`
    (at most `MAX_STRIPS` strips)."""
    if not 0.0 < tolerance <= 1.0:
        raise ShapeError(f"tolerance must be in (0, 1], got {tolerance}")
    resolved = resolve_shape(part, parameters)
    shape = part.shape  # resolve_shape raised ShapeError if there is none
    assert shape is not None

    adds = [p for p in resolved.placed if p.component.operation == "add"]
    voids = [p for p in resolved.placed if p.component.operation == "subtract"]
    recipe_volume = sum(signed_volumes(resolved))  # the same sum, in the same order, as mass_properties().volume
    if not recipe_volume > 0.0:
        raise ShapeError("the voids remove all the material: net volume is not positive")

    plans = _plans(resolved)
    geoms: list[ProxyGeom] = []
    sim = {"badge": Badge.SIM, "source": Source(ref=_COMPUTED_BY, locator=f"part {part.id}")}
    filled: tuple[FilledVoid, ...] = ()
    decomposed: tuple[DecomposedVoid, ...] = ()

    def copied(p: Placed) -> ProxyGeom:
        return ProxyGeom(
            id=p.component.id,
            component=p.component.id,
            primitive=p.component.primitive.kind,
            dimensions=tuple(Dimension(name=n, value=v) for n, v in p.dims.items()),
            center=p.center,
            orientation=p.component.orientation,
            volume=p.volume,
        )

    if plans is None:
        geoms = [copied(p) for p in adds]
        filled = tuple(FilledVoid(id=p.component.id, primitive=p.component.primitive.kind, volume=p.volume) for p in voids)
        method, assumptions, tol = "added-primitives", _COMMON + _FILLED, None
        proxy_volume = sum(g.volume for g in geoms)
    else:
        n = next((n for n in range(4, MAX_STRIPS + 1, 2) if sum(pieces(pl, n)[1] for pl in plans) <= tolerance * recipe_volume), None)
        if n is None:
            worst = sum(pieces(pl, MAX_STRIPS)[1] for pl in plans) / recipe_volume
            raise ShapeError(
                f"the through-bores of part {part.id!r} cannot be decomposed into boxes within {tolerance:.3g} of the part's "
                f"volume using up to {MAX_STRIPS} strips (misses {worst:.3g} of the volume at {MAX_STRIPS}); the wall is too thin for the "
                "tolerance: raise the tolerance or thicken the wall"
            )
        hosts = {id(pl.host): pl for pl in plans}
        for p in adds:
            pl = hosts.get(id(p))
            if pl is None:
                geoms.append(copied(p))
                continue
            rows, _ = _piece_geoms(pl, n)
            for idx, centre, size in rows:
                geoms.append(
                    ProxyGeom(
                        id=_piece_id(p.component.id, idx),
                        component=p.component.id,
                        primitive="box",
                        dimensions=tuple(Dimension(name=nm, value=v) for nm, v in zip(("size_x", "size_y", "size_z"), size)),
                        center=centre,
                        orientation=p.component.orientation,
                        volume=size[0] * size[1] * size[2],
                    )
                )
        decomposed = tuple(
            DecomposedVoid(id=pl.void.component.id, primitive="cylinder", host=pl.host.component.id, volume=pl.void.volume) for pl in plans
        )
        method, assumptions, tol = "void-decomposition", _COMMON + _DECOMPOSED, tolerance
        proxy_volume = sum(g.volume for g in geoms)

    uses = parameter_uses(part, resolved)
    badges = sorted({shape.badge, *(u.value.badge for u in uses)}, key=list(Badge).index)
    return CollisionProxy(
        part_id=part.id,
        geoms=tuple(geoms),
        filled_voids=filled,
        decomposed_voids=decomposed,
        proxy_volume=DerivedScalar(value=proxy_volume, unit=Unit.M3, **sim),
        recipe_volume=DerivedScalar(value=recipe_volume, unit=Unit.M3, **sim),
        volume_error=DerivedScalar(value=(proxy_volume - recipe_volume) / recipe_volume, unit=Unit.ONE, **sim),
        derivation=ProxyDerivation(
            method=method,
            tolerance=tol,
            shape=Provenance(badge=shape.badge, source=shape.source),
            parameters=uses,
            input_badges=tuple(badges),
            assumptions=assumptions,
        ),
        **sim,
    )
