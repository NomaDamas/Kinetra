"""`Material` (C-01a). Density, yield strength, elastic modulus, friction; each with badge and source.

Not here: a catalog of real materials with real numbers (B-07 supplies them, each with a source), PBR slots (B-07),
the pairwise friction combination rule and the MJCF mapping (X-01). `friction` is the material's own Coulomb
sliding coefficient; how two materials' coefficients combine at a contact is the compiler's decision.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import Unit
from .provenance import Quantity, require_unit

ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    density: Quantity  # kg/m^3, > 0
    yield_strength: Quantity  # Pa, > 0
    elastic_modulus: Quantity  # Pa, > 0
    friction: Quantity  # 1 (dimensionless), >= 0

    @model_validator(mode="after")
    def _units_and_ranges(self) -> "Material":
        for name, unit, strict in (
            ("density", Unit.KG_PER_M3, True),
            ("yield_strength", Unit.PA, True),
            ("elastic_modulus", Unit.PA, True),
            ("friction", Unit.ONE, False),
        ):
            q: Quantity = getattr(self, name)
            require_unit(q, unit, name)
            if q.value <= 0 if strict else q.value < 0:
                raise ValueError(f"{name} must be {'> 0' if strict else '>= 0'}, got {q.value}")
        return self
