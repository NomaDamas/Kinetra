"""Mass, centre of mass and inertia of a part from its shape recipe (B-01a).

Pure Python, no CAD kernel. Each primitive has a closed-form volume and inertia; components combine by the parallel-axis
theorem, voids as negative mass. The assumptions that makes exact are in `kinetra_core.shape` and are listed in every
result's `derivation.assumptions`; `docs/architecture/part-mass.md` explains why this is not build123d.

    mass_properties(part, material, parameters=None) -> MassProperties

Units are SI and the frame is the part's local frame (`kinetra_core.conventions`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from kinetra_core import (
    Badge,
    ComponentContribution,
    Derivation,
    DerivedInertia,
    DerivedScalar,
    DerivedVector,
    Dimension,
    MassProperties,
    Material,
    PartDef,
    Provenance,
    Quantity,
    Source,
    Unit,
)
from kinetra_core.shape import Box, Cylinder, Sphere

from . import _convex as cx
from ._shape import ShapeError, parameter_uses, resolve_shape

_COMPUTED_BY = "kinetra_engine.parts.mass_properties (analytic primitives, parallel-axis composition)"

_ASSUMPTIONS = (
    "Homogeneous rigid body: the material's single density applies to every added component; voids are empty.",
    "Volumes and inertias are the exact closed forms of box, cylinder and sphere; fillets, chamfers and threads are not modelled.",
    "Added components have disjoint interiors, voids have disjoint interiors, and each void lies inside one added "
    "component. This was tested with a separating-plane and a containment test on the primitives, not by a CAD boolean.",
)


def _principal_inertia(p: Box | Cylinder | Sphere, m: float, dims: Mapping[str, float]) -> cx.Vec:
    """Diagonal of the inertia tensor about the primitive's own centre, in its own axes."""
    if isinstance(p, Box):
        a, b, c = dims["size_x"], dims["size_y"], dims["size_z"]
        return (m * (b * b + c * c) / 12.0, m * (a * a + c * c) / 12.0, m * (a * a + b * b) / 12.0)
    if isinstance(p, Cylinder):
        r, h = dims["radius"], dims["length"]
        t = m * (3.0 * r * r + h * h) / 12.0
        return (t, t, m * r * r / 2.0)
    i = 0.4 * m * dims["radius"] ** 2
    return (i, i, i)


def mass_properties(
    part: PartDef,
    material: Material,
    parameters: Mapping[str, Quantity] | None = None,
) -> MassProperties:
    """Volume, mass, centre of mass and inertia of `part` made of `material`, with the inputs that produced them.

    `parameters` overrides the part's defaults (a `Quantity` in metres, within the parameter's range, with its own badge
    and source). The result is badge `sim`; `derivation` lists the shape, density and parameter values with their badges.
    """
    resolved = resolve_shape(part, parameters)
    shape = part.shape  # resolve_shape raised ShapeError if there is none
    placed = resolved.placed
    rho = material.density.value

    # Signed volumes: +added, -void.
    signed = [(p.volume if p.component.operation == "add" else -p.volume) for p in placed]
    volume = sum(signed)
    if not volume > 0.0:
        raise ShapeError("the voids remove all the material: net volume is not positive")
    mass = rho * volume
    com = tuple(sum(s * rho * pl.center[i] for s, pl in zip(signed, placed)) / mass for i in range(3))

    ixx = iyy = izz = ixy = ixz = iyz = 0.0
    for s, pl in zip(signed, placed):
        center, r = pl.center, pl.rotation
        am = rho * pl.volume
        diag = _principal_inertia(pl.component.primitive, am, pl.dims)
        sign = 1.0 if s > 0 else -1.0  # a void is negative mass
        # R diag(d) R^T about the component's own centre, in part axes.
        t = [[sum(r[i][k] * diag[k] * r[j][k] for k in range(3)) for j in range(3)] for i in range(3)]
        d = (center[0] - com[0], center[1] - com[1], center[2] - com[2])
        # Parallel-axis diagonal from the offset components: |d|^2 - d_i^2 would cancel to nothing for a small
        # perpendicular offset along a long one.
        ixx += sign * (t[0][0] + am * (d[1] * d[1] + d[2] * d[2]))
        iyy += sign * (t[1][1] + am * (d[0] * d[0] + d[2] * d[2]))
        izz += sign * (t[2][2] + am * (d[0] * d[0] + d[1] * d[1]))
        ixy += sign * (t[0][1] - am * d[0] * d[1])
        ixz += sign * (t[0][2] - am * d[0] * d[2])
        iyz += sign * (t[1][2] - am * d[1] * d[2])

    _check_physical(mass, (ixx, iyy, izz, ixy, ixz, iyz))

    uses = parameter_uses(part, resolved)
    input_badges = sorted(
        {shape.badge, material.density.badge, *(q.value.badge for q in uses)}, key=list(Badge).index
    )
    source = Source(ref=_COMPUTED_BY, locator=f"part {part.id}, material {material.id}")
    sim = {"badge": Badge.SIM, "source": source}
    contributions = tuple(
        ComponentContribution(
            id=pl.component.id,
            primitive=pl.component.primitive.kind,
            operation=pl.component.operation,
            dimensions=tuple(Dimension(name=n, value=v_) for n, v_ in pl.dims.items()),
            volume=pl.volume,
            mass=rho * pl.volume,
            center=pl.center,
            orientation=pl.component.orientation,
        )
        for pl in placed
    )
    return MassProperties(
        part_id=part.id,
        volume=DerivedScalar(value=volume, unit=Unit.M3, **sim),
        mass=DerivedScalar(value=mass, unit=Unit.KG, **sim),
        center_of_mass=DerivedVector(x=com[0], y=com[1], z=com[2], unit=Unit.M, **sim),
        inertia=DerivedInertia(ixx=ixx, iyy=iyy, izz=izz, ixy=ixy, ixz=ixz, iyz=iyz, unit=Unit.KG_M2, **sim),
        derivation=Derivation(
            shape=Provenance(badge=shape.badge, source=shape.source),
            material_id=material.id,
            density=material.density,
            parameters=uses,
            components=contributions,
            input_badges=tuple(input_badges),
            assumptions=_ASSUMPTIONS,
        ),
    )


def _principal_moments(i: tuple[float, float, float, float, float, float]) -> list[float]:
    """Eigenvalues of the symmetric inertia matrix (cyclic Jacobi)."""
    a = [[i[0], i[3], i[4]], [i[3], i[1], i[5]], [i[4], i[5], i[2]]]
    for _ in range(60):
        off = abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2])
        if off <= 1e-15 * (abs(a[0][0]) + abs(a[1][1]) + abs(a[2][2])) or off == 0.0:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            if a[p][q] == 0.0:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
            t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            for k in range(3):
                akp, akq = a[k][p], a[k][q]
                a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
            for k in range(3):
                apk, aqk = a[p][k], a[q][k]
                a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
    return sorted(a[k][k] for k in range(3))


_PHYSICAL_REL_TOL = 1e-9


def _check_physical(mass: float, inertia: tuple[float, float, float, float, float, float]) -> None:
    """Reject a result no real body can have: negative or non-finite mass, negative principal moments, or principal
    moments that break the triangle inequality. Voids that poke out of the material within the geometric tolerance, or
    rounding, could otherwise leave such a tensor behind."""
    if not (math.isfinite(mass) and mass > 0.0) or not all(math.isfinite(x) for x in inertia):
        raise ShapeError("the computed mass or inertia is not finite and positive")
    lo, mid, hi = _principal_moments(inertia)
    slack = _PHYSICAL_REL_TOL * (lo + mid + hi)
    if lo < -slack or lo + mid < hi - slack:
        raise ShapeError(
            f"the computed inertia is not physical (principal moments {lo:.6g}, {mid:.6g}, {hi:.6g} kg*m^2); "
            "a void probably sticks out of the material"
        )
