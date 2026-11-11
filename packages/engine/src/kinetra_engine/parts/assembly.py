"""Mass of an assembled design: one `mass_properties` per instance, and their sum (B-02 epic integration).

    assembly_mass(design, cache=None) -> AssemblyMass

Each instance of a `DesignSpec` is compiled as `mass_properties(part, material, instance parameters)`: the part and
the material are the ones the design carries (by id), the parameters are the ones the instance sets (the rest are the part's
defaults). The total is the sum of those masses and nothing else: no joint, pose or mount adds or removes mass. It is summed
with `math.fsum`, so it is the correctly rounded value of the exact sum of the per-instance floats and does not depend on the
order of the instances. `AssemblyMass.total` is badge `sim`; the badges of the inputs are in each instance's
`properties.derivation` and in `input_badges` here.

Not here: the assembly's centre of mass and inertia (the poses' rotation would be needed), an actuator's supply
(`tank_total_mass` adds propellant), a mass change in flight (X-01c).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from kinetra_core import Badge, DerivedScalar, DesignSpec, MassProperties, Quantity, Source, Unit

from ._shape import ShapeError
from .cache import PartCache
from .mass import mass_properties

_COMPUTED_BY = "kinetra_engine.parts.assembly_mass (math.fsum of the per-instance mass_properties masses)"


@dataclass(frozen=True)
class InstanceMass:
    instance: str
    part: str
    material: str | None
    properties: MassProperties

    @property
    def mass(self) -> float:
        """Mass of this instance [kg]."""
        return self.properties.mass.value


@dataclass(frozen=True)
class AssemblyMass:
    instances: tuple[InstanceMass, ...]
    total: DerivedScalar
    input_badges: tuple[Badge, ...]


def assembly_mass(design: DesignSpec, cache: PartCache | None = None) -> AssemblyMass:
    """Per-instance masses (in the design's instance order) and their total [kg].

    Raises `ShapeError` naming the instance when a part has no recipe, a parameter is out of range, or a part without a
    declared mass has no material; an empty design has total 0."""
    parts = {p.id: p for p in design.parts}
    materials = {m.id: m for m in design.materials}
    compute = cache.mass_properties if cache is not None else mass_properties
    rows: list[InstanceMass] = []
    for inst in design.instances:
        part = parts[inst.part]
        material = materials[inst.material] if inst.material is not None else None
        values: Mapping[str, Quantity] = {p.name: p for p in inst.parameters}
        try:
            props = compute(part, material, values)
        except ShapeError as e:
            raise ShapeError(f"instance {inst.id!r} (part {part.id!r}): {e}") from e
        rows.append(InstanceMass(inst.id, part.id, material.id if material is not None else None, props))
    total = math.fsum(r.mass for r in rows)
    badges = {b for r in rows for b in r.properties.derivation.input_badges}
    return AssemblyMass(
        instances=tuple(rows),
        total=DerivedScalar(
            value=total,
            unit=Unit.KG,
            badge=Badge.SIM,
            source=Source(ref=_COMPUTED_BY, locator=f"{len(rows)} instance(s)"),
        ),
        input_badges=tuple(sorted(badges, key=list(Badge).index)),
    )
