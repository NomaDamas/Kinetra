"""Collision proxy of a part from its shape recipe (B-01b, B-01f).

Added components become convex analytic primitives. A subtracted component cannot be one; each void is treated on its own.

- **Decompose (B-01f)** a void that is the only void of its host and a through-bore of it (`_decompose.plan_through_bore`):
  a box with a round hole along one of its axes becomes `strips` of boxes, a cylinder with a coaxial bore becomes a `ring`
  of boxes. The bore stays empty and every box is inside the recipe's material. The error of **each such host** (its union
  of pieces against its own volume minus its bore) is within `tolerance`, or the proxy is rejected with the reason.
- **Fill (B-01b)** every other void (blind pocket, sphere, skew or off-axis hole, a host with two voids): the host is copied
  as the primitive it is and the void is listed in `filled_voids`; the reason is in `derivation.assumptions`. With
  `on_unsupported="reject"` such a void raises `ShapeError` instead.

The visual mesh is never read (B-01c, and the result type has no mesh kind).

    collision_proxy(part, parameters=None, tolerance=None, on_unsupported="fill") -> CollisionProxy

`tolerance` is a fraction (float, or a `Quantity` of unit `1` with its own badge); `None` is `DEFAULT_TOLERANCE` with badge
`default`, a float is badge `declared` (the caller's choice). Units are SI and the frame is the part's local frame
(`kinetra_core.conventions`). Parameters are resolved, checked and placed exactly as `mass_properties` does
(`_shape.resolve_shape`), and `recipe_volume` is the same signed sum, so a recipe evaluates for both or for neither and the
two report the same volume bit for bit. Mass, centre of mass and inertia stay with `mass_properties`; nothing here feeds them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal

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
    Quaternion,
    RingReport,
    Source,
    Unit,
)

from . import _convex as cx
from ._decompose import Decomposition, Infeasible, MIN_STRIP_FRACTION, BorePlan, decompose, plan_through_bore
from ._shape import Placed, ShapeError, parameter_uses, resolve_shape, signed_volumes

# Largest allowed |error| of one decomposed host, as a fraction of that host's volume minus its bore. Chosen, not derived:
# a 50 mm bore in a 300 x 200 x 20 mm plate needs 4 strips (10 boxes, -2.5 %) and a tube of outer radius 50 mm and bore radius
# 40 mm a ring of 16 boxes (-9.0 %); see `docs/architecture/collision-proxy.md` for the table. Thinner walls and tighter
# tolerances cost more boxes, and past the limits in `_decompose` (or for a bore under a third of the radius) the part is rejected.
DEFAULT_TOLERANCE = 0.10

_COMPUTED_BY = "kinetra_engine.parts.collision_proxy (convex primitives; voids decomposed or filled)"
_DEFAULT_SOURCE = "kinetra_engine.parts.collision.DEFAULT_TOLERANCE: a chosen value, not derived from a standard or a measurement"
_CALLER_SOURCE = "tolerance argument of collision_proxy"

_COMMON = (
    "Each added shape component that is not decomposed becomes one proxy geom of the same primitive, size, centre and "
    "orientation; no mesh and no approximation of the primitives.",
)
_FILLED = (
    "A convex primitive has no hole: every void listed in filled_voids is filled in the proxy, so the proxy volume is the "
    "recipe volume plus the filled voids (and the decomposed hosts' errors). The error is reported, not removed.",
)
_DECOMPOSED = (
    "A round bore is not a finite union of boxes. Each host with a through-bore is replaced by boxes (strips across a plate, a "
    "ring around a tube) that are all inside the recipe's material: the bore is empty in the proxy (a body can enter or pass "
    "through it) and nothing sticks out. The price is volume the proxy misses, so the host's error is negative; it is computed "
    "from the pieces, not sampled, and each host is within the stated tolerance. The surfaces are stepped (strips) or "
    "faceted (ring); the ring's deviations from the real tube are in decomposed_voids[].ring.",
    "Pieces may touch and overlap each other in a collision (a ring's boxes do); mass, centre of mass and inertia come from "
    "the shape recipe (MassProperties), never from the proxy geoms.",
)

OnUnsupported = Literal["fill", "reject"]


def _tolerance(value: float | Quantity | None) -> Quantity:
    if value is None:
        return Quantity(value=DEFAULT_TOLERANCE, unit=Unit.ONE, badge=Badge.DEFAULT, source=Source(ref=_DEFAULT_SOURCE))
    if isinstance(value, Quantity):
        q = value
    else:
        q = Quantity(value=float(value), unit=Unit.ONE, badge=Badge.DECLARED, source=Source(ref=_CALLER_SOURCE))
    if q.unit is not Unit.ONE:
        raise ShapeError(f"tolerance is a fraction (unit '1'), got {q.unit.value!r}")
    if not 0.0 < q.value <= 1.0:
        raise ShapeError(f"tolerance must be in (0, 1], got {q.value}")
    if q.badge is Badge.SIM:
        raise ShapeError("tolerance is chosen, not computed: badge 'sim' is not allowed")
    return Quantity(value=q.value, unit=q.unit, badge=q.badge, source=q.source)


def _host_of(void: Placed, adds: list[Placed]) -> Placed:
    for h in adds:  # resolve_shape checked that exactly one added component contains the void's body
        if cx.contained(void.body, h.body, 1e-9 * 2.0 * max(max(void.body.half), max(h.body.half))):
            return h
    raise AssertionError("resolve_shape accepted a void outside every added component")


def _piece_id(host: str, used: set[str], counter: list[int]) -> str:
    """Next free id `<host prefix>_p<n>` of at most 64 characters; `used` holds every component id and every geom id so far."""
    while True:
        suffix = f"_p{counter[0]}"
        counter[0] += 1
        candidate = host[: 64 - len(suffix)] + suffix
        if candidate not in used:
            used.add(candidate)
            return candidate


def _mul(a: Quaternion, b: Quaternion) -> Quaternion:
    return Quaternion(
        x=a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        y=a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        z=a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
        w=a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
    )


def _piece_geoms(dec: Decomposition, used: set[str]) -> list[ProxyGeom]:
    host = dec.plan.host
    counter = [0]
    out = []
    for piece in dec.pieces:
        centre = host.center
        for a in range(3):
            centre = cx.add(centre, cx.scale(host.body.axes[a], piece.center[a]))
        orientation = host.component.orientation
        if piece.angle != 0.0:  # a stave of a ring: turned about the host's axis k, which is local z for a tube
            half = piece.angle / 2.0
            orientation = _mul(orientation, Quaternion(x=0.0, y=0.0, z=math.sin(half), w=math.cos(half)))
        x, y, z = piece.size
        out.append(
            ProxyGeom(
                id=_piece_id(host.component.id, used, counter),
                component=host.component.id,
                primitive="box",
                dimensions=(Dimension(name="size_x", value=x), Dimension(name="size_y", value=y), Dimension(name="size_z", value=z)),
                center=centre,
                orientation=orientation,
                volume=x * y * z,
            )
        )
    return out


def collision_proxy(
    part: PartDef,
    parameters: Mapping[str, Quantity] | None = None,
    tolerance: float | Quantity | None = None,
    on_unsupported: OnUnsupported = "fill",
) -> CollisionProxy:
    """The collision proxy of `part` and its signed volume error against the shape recipe.

    `parameters` overrides the part's defaults (a `Quantity` in metres, within the parameter's range, with its own badge
    and source), as in `mass_properties`. `tolerance` (see the module docstring) bounds the error of every decomposed host.
    `on_unsupported`: what to do with a void that cannot be decomposed: `"fill"` (default) fills it and says why in
    `derivation.assumptions`, `"reject"` raises `ShapeError`.

    Raises `ShapeError` for a part without a recipe, a bad parameter value, a recipe that breaks the disjoint-sum rule
    (`kinetra_core.shape`), a bad tolerance or `on_unsupported`, an unsupported void with `on_unsupported="reject"`, or a
    supported through-bore that cannot be decomposed within `tolerance`."""
    if on_unsupported not in ("fill", "reject"):
        raise ShapeError(f"on_unsupported must be 'fill' or 'reject', got {on_unsupported!r}")
    tol = _tolerance(tolerance)
    resolved = resolve_shape(part, parameters)
    shape = part.shape  # resolve_shape raised ShapeError if there is none
    assert shape is not None

    adds = [p for p in resolved.placed if p.component.operation == "add"]
    voids = [p for p in resolved.placed if p.component.operation == "subtract"]
    recipe_volume = sum(signed_volumes(resolved))  # the same sum, in the same order, as mass_properties().volume
    if not recipe_volume > 0.0:
        raise ShapeError("the voids remove all the material: net volume is not positive")

    hosts = {id(v): _host_of(v, adds) for v in voids}
    per_host: dict[int, list[Placed]] = {}
    for v in voids:
        per_host.setdefault(id(hosts[id(v)]), []).append(v)

    plans: dict[int, BorePlan] = {}  # by id(host)
    reasons: dict[str, str] = {}  # by void id
    for v in voids:
        host = hosts[id(v)]
        if len(per_host[id(host)]) > 1:
            reasons[v.component.id] = f"its host {host.component.id!r} has {len(per_host[id(host)])} voids and only one bore per host is decomposed"
            continue
        plan = plan_through_bore(host, v)
        if isinstance(plan, str):
            reasons[v.component.id] = plan
        else:
            plans[id(host)] = plan
    if reasons and on_unsupported == "reject":
        raise ShapeError(
            "cannot decompose: "
            + "; ".join(f"void {i!r}: {why}" for i, why in reasons.items())
            + " (on_unsupported='reject'; use 'fill' to fill them and report the error)"
        )

    decs: dict[int, Decomposition] = {}
    for p in adds:
        plan = plans.get(id(p))
        if plan is not None:
            try:
                decs[id(p)] = decompose(plan, tol.value)
            except Infeasible as e:
                raise ShapeError(f"void {plan.void.component.id!r} in {p.component.id!r} {e}") from None

    used = {p.component.id for p in resolved.placed}
    geoms: list[ProxyGeom] = []
    for p in adds:
        dec = decs.get(id(p))
        if dec is not None:
            geoms.extend(_piece_geoms(dec, used))
        else:
            geoms.append(
                ProxyGeom(
                    id=p.component.id,
                    component=p.component.id,
                    primitive=p.component.primitive.kind,
                    dimensions=tuple(Dimension(name=n, value=v) for n, v in p.dims.items()),
                    center=p.center,
                    orientation=p.component.orientation,
                    volume=p.volume,
                )
            )
    proxy_volume = sum(p.volume for p in adds if id(p) not in decs) + sum(d.union_volume for d in decs.values())

    decomposed = tuple(
        DecomposedVoid(
            id=d.plan.void.component.id,
            primitive="cylinder",
            host=d.plan.host.component.id,
            volume=d.plan.void.volume,
            host_volume=d.plan.host.volume,
            union_volume=d.union_volume,
            error=d.error,
            layout=d.layout,
            ring=None
            if d.ring is None
            else RingReport(staves=d.ring.staves, wall_closed=d.ring.closed, inner_deviation=d.ring.inner_deviation, outer_deviation=d.ring.outer_deviation),
        )
        for d in decs.values()
    )
    filled = tuple(
        FilledVoid(id=v.component.id, primitive=v.component.primitive.kind, volume=v.volume) for v in voids if v.component.id in reasons
    )
    assumptions = list(_COMMON)
    if decomposed:
        assumptions += _DECOMPOSED
        assumptions.append(
            f"Tolerance {tol.value:g} of each decomposed host's volume minus its bore (badge {tol.badge.value}); strips are never "
            f"thinner than {MIN_STRIP_FRACTION:g} of the bore radius across the cut."
        )
    if filled:
        assumptions += _FILLED
        assumptions += [f"Void {i!r} was filled, not decomposed: {why}." for i, why in reasons.items()]

    uses = parameter_uses(part, resolved)
    badges = sorted({shape.badge, *(u.value.badge for u in uses)}, key=list(Badge).index)
    sim = {"badge": Badge.SIM, "source": Source(ref=_COMPUTED_BY, locator=f"part {part.id}")}
    return CollisionProxy(
        part_id=part.id,
        geoms=tuple(geoms),
        filled_voids=filled,
        decomposed_voids=decomposed,
        proxy_volume=DerivedScalar(value=proxy_volume, unit=Unit.M3, **sim),
        recipe_volume=DerivedScalar(value=recipe_volume, unit=Unit.M3, **sim),
        volume_error=DerivedScalar(value=(proxy_volume - recipe_volume) / recipe_volume, unit=Unit.ONE, **sim),
        derivation=ProxyDerivation(
            method="void-decomposition" if decomposed else "added-primitives",
            tolerance=tol if decomposed else None,
            shape=Provenance(badge=shape.badge, source=shape.source),
            parameters=uses,
            input_badges=tuple(badges),
            assumptions=tuple(assumptions),
        ),
        **sim,
    )
