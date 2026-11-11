"""Evaluating a part's shape recipe at parameter values (B-01a), shared by mass (B-01a) and the collision proxy (B-01b).

`resolve_shape` turns the recipe into placed primitives: resolved dimensions, volume, centre, rotation and the convex body
used by the overlap tests. It rejects what the recipe's closed-form maths cannot honour (unknown or out-of-range
parameters, non-positive dimensions, components that break the disjoint-sum rule of `kinetra_core.shape`), so both users
get the same answer to "is this recipe evaluable".
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from kinetra_core import ParameterUse, PartDef, Quantity
from kinetra_core.shape import Box, Cylinder, ShapeComponent, Sphere

from . import _convex as cx

# Relative tolerance of the overlap and containment tests, times the larger size of the two elements compared.
# It does not depend on where the elements sit or on any other element.
_REL_TOL = 1e-9


class ShapeError(ValueError):
    """The part cannot be evaluated: missing shape, bad parameter value, or a recipe that breaks the disjoint-sum rule."""


Mat3 = tuple[cx.Vec, cx.Vec, cx.Vec]


def rotation(q) -> Mat3:
    """Rotation matrix (rows) of a unit quaternion {x, y, z, w}."""
    x, y, z, w = q.x, q.y, q.z, q.w
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n  # the model allows norm 1 +- 1e-6; use the exact rotation
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def _columns(r: Mat3) -> tuple[cx.Vec, cx.Vec, cx.Vec]:
    return tuple((r[0][j], r[1][j], r[2][j]) for j in range(3))  # type: ignore[return-value]


def primitive_volume(p: Box | Cylinder | Sphere, dims: Mapping[str, float]) -> float:
    if isinstance(p, Box):
        return dims["size_x"] * dims["size_y"] * dims["size_z"]
    if isinstance(p, Cylinder):
        return math.pi * dims["radius"] ** 2 * dims["length"]
    return 4.0 / 3.0 * math.pi * dims["radius"] ** 3


def _body(p: Box | Cylinder | Sphere, dims: Mapping[str, float], center: cx.Vec, r: Mat3) -> cx.Body:
    axes = _columns(r)
    if isinstance(p, Box):
        return cx.Body("box", center, axes, (dims["size_x"] / 2, dims["size_y"] / 2, dims["size_z"] / 2))
    if isinstance(p, Cylinder):
        return cx.Body("cylinder", center, axes, (dims["radius"], dims["radius"], dims["length"] / 2))
    return cx.Body("sphere", center, axes, (dims["radius"],) * 3)


def _resolve_parameters(part: PartDef, overrides: Mapping[str, Quantity] | None) -> dict[str, Quantity]:
    """Every parameter the shape could use, as a Quantity: the override if given, else the part's default."""
    overrides = dict(overrides or {})
    by_name = {p.name: p for p in part.parameters}
    unknown = sorted(set(overrides) - set(by_name))
    if unknown:
        raise ShapeError(f"unknown parameters {unknown} (the part has {sorted(by_name)})")
    out: dict[str, Quantity] = {}
    for name, p in by_name.items():
        q = overrides.get(name, p.default)
        if q.unit is not p.unit:
            raise ShapeError(f"parameter {name!r}: need unit {p.unit.value!r}, got {q.unit.value!r}")
        if not p.min.value <= q.value <= p.max.value:
            raise ShapeError(f"parameter {name!r}: {q.value} is outside the allowed range [{p.min.value}, {p.max.value}]")
        # Plain Quantity: an `Instance.parameters` entry is a ParamValue (with a `name`) and must not leak into the result.
        out[name] = Quantity(value=q.value, unit=q.unit, badge=q.badge, source=q.source)
    return out


def _tol(a: cx.Body, b: cx.Body) -> float:
    return _REL_TOL * 2.0 * max(max(a.half), max(b.half))


def _check_disjoint_sum(items: list[tuple[ShapeComponent, cx.Body]]) -> None:
    adds = [(c, b) for c, b in items if c.operation == "add"]
    voids = [(c, b) for c, b in items if c.operation == "subtract"]
    for group, label in ((adds, "added components"), (voids, "voids")):
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if not cx.separated(group[i][1], group[j][1], _tol(group[i][1], group[j][1])):
                    raise ShapeError(
                        f"{label} {group[i][0].id!r} and {group[j][0].id!r} overlap; "
                        "components must have disjoint interiors (split or shrink one)"
                    )
    for c, b in voids:
        if not any(cx.contained(b, ab, _tol(b, ab)) for _, ab in adds):
            raise ShapeError(
                f"void {c.id!r} is not inside a single added component; "
                "a void across two added components must be split into one void per component"
            )


@dataclass(frozen=True)
class Placed:
    """One shape component evaluated at the parameter values."""

    component: ShapeComponent
    dims: Mapping[str, float]  # metres, under the field names of `kinetra_core.shape`
    volume: float  # m^3, positive
    center: cx.Vec
    rotation: Mat3
    body: cx.Body


@dataclass(frozen=True)
class Resolved:
    quantities: Mapping[str, Quantity]  # every parameter of the part, at the value used
    placed: tuple[Placed, ...]  # in recipe order


def resolve_shape(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> Resolved:
    """Evaluate `part.shape` at the part's parameter defaults or `parameters`, and check the disjoint-sum rule."""
    if part.shape is None:
        raise ShapeError(f"part {part.id!r} has no shape recipe")
    quantities = _resolve_parameters(part, parameters)
    values = {n: q.value for n, q in quantities.items()}

    placed: list[Placed] = []
    for comp in part.shape.components:
        dims = {name: expr.evaluate(values) for name, expr in comp.primitive.dimensions()}
        for name, v in dims.items():
            if not v > 0.0:  # also catches NaN; a part-range check already ran, this guards the override path
                raise ShapeError(f"component {comp.id!r}: {name} is {v} m, must be above zero")
        center = comp.position.evaluate(values)
        r = rotation(comp.orientation)
        placed.append(Placed(comp, dims, primitive_volume(comp.primitive, dims), center, r, _body(comp.primitive, dims, center, r)))

    _check_disjoint_sum([(p.component, p.body) for p in placed])
    return Resolved(quantities, tuple(placed))


def signed_volumes(resolved: Resolved) -> list[float]:
    """Volume of each component in recipe order, positive for `add` and negative for `subtract`. Mass and the collision
    proxy both sum exactly this list, so the net volume of a recipe is the same number for both (and a recipe whose net
    volume is positive for one is accepted by the other)."""
    return [(p.volume if p.component.operation == "add" else -p.volume) for p in resolved.placed]


def parameter_uses(part: PartDef, resolved: Resolved) -> tuple[ParameterUse, ...]:
    """The parameters some dimension or position of the recipe refers to, with the value each had, sorted by name."""
    assert part.shape is not None
    used = sorted({t.param for c in part.shape.components for _, e in c.axis_exprs() for t in e.terms})
    return tuple(ParameterUse(name=n, value=resolved.quantities[n]) for n in used)
