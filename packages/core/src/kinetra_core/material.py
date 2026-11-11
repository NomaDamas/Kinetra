"""`Material` (C-01a). Density, yield strength, elastic modulus, friction; each with badge and source.

Each field has its own `Quantity` subclass, so the unit is fixed and the range is checked on that field: errors
point at `density.unit` or `friction.value`, and the JSON Schema carries the unit and the bound.

Not here: a catalog of real materials with real numbers (B-07 supplies them, each with a source), PBR slots (B-07),
the pairwise friction combination rule and the MJCF mapping (X-01). `friction` is the material's own Coulomb
sliding coefficient; how two materials' coefficients combine at a contact is the compiler's decision.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .conventions import ID_PATTERN, Unit
from .provenance import Quantity

_Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
_NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]


class Density(Quantity):
    value: _Positive
    unit: Literal[Unit.KG_PER_M3]


class YieldStrength(Quantity):
    value: _Positive
    unit: Literal[Unit.PA]


class ElasticModulus(Quantity):
    value: _Positive
    unit: Literal[Unit.PA]


class Friction(Quantity):
    """Dimensionless Coulomb coefficient."""

    value: _NonNegative
    unit: Literal[Unit.ONE]


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    density: Density
    yield_strength: YieldStrength
    elastic_modulus: ElasticModulus
    friction: Friction
