"""Assumption table (C-01c): value, distribution, source, confidence.

Moved from the legacy `SpecSheet` assumption structure (`legacy-v0:schemas/spec_sheet.schema.json`, `Assumption`,
`Fixed`/`Uniform`/`Normal`, `Confidence`). Same fields and same JSON identifiers, with these changes:

| legacy | here |
|---|---|
| `value` + `unit` + `source` (free text) | `value`: a `Quantity` (value, unit from the closed `Unit` vocabulary, badge, structured `Source`) |
| `distribution` (`Fixed`, `Uniform`, `Normal`) | same kinds and parameters (`FixedDistribution`, `UniformDistribution`, `NormalDistribution`), `kind` required. `Uniform` and `Normal` carry their own badge and source (C-01a rule: a number has a badge), because a cited nominal does not cite its spread. The nominal must lie inside the distribution's support (uniform: `low <= value <= high`; normal: within `clip_low`/`clip_high` when set) |
| `key` (any string) | `key`: `NAME_PATTERN`; unique in the table |
| `label` (any string), `confidence` (`low`/`med`/`high`), `editable` | `label`: 1 to 100 characters, not blank; the others unchanged |

`value` is the nominal (the deterministic search uses it); the distribution is what Monte-Carlo samples. The
distribution's numbers are in `value.unit`. An optional typed `binding` names an instance parameter, material
property or part specification; `Project` rejects a missing target, a unit mismatch and two rows bound to one target. An unbound row has no
unit meaning to check and remains explicitly unapplied by the verdict (#571).
Not carried over from the legacy `SpecSheet`: parts, param bounds, success criteria, template id and tier; they
belong to other leaves (C-01b, J-02).

`AssumptionTable` rejects a key named like a planet constant (`gravity`, `ground_friction` ...,
`world.PLANET_CONSTANT_NAMES`). That is a courtesy that tells the user where the value lives, not the guarantee:
the guarantee is that the engine reads planet constants only from `data/bodies` (W-03a) and the validator refuses
commands that change them (C-02c). A standalone `Assumption` is not checked, and a differently named key is not
caught. The model labels the verdict shows next to the table ("근사: 균일 중력" etc.) are W-03b's and W-06's.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from .conventions import ID_PATTERN, NAME_PATTERN
from .provenance import Number, Provenance, Quantity
from .world import PLANET_CONSTANT_NAMES


class Confidence(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"


class FixedDistribution(BaseModel):
    """No spread: Monte-Carlo uses the nominal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["fixed"]


class UniformDistribution(Provenance):
    kind: Literal["uniform"]
    low: Number
    high: Number

    @model_validator(mode="after")
    def _ordered(self) -> "UniformDistribution":
        if not self.low <= self.high:
            raise ValueError("uniform: low must be <= high")
        return self


class NormalDistribution(Provenance):
    kind: Literal["normal"]
    mean: Number
    std: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
    clip_low: Number | None = None
    clip_high: Number | None = None

    @model_validator(mode="after")
    def _clip_ordered(self) -> "NormalDistribution":
        if self.clip_low is not None and self.clip_high is not None and not self.clip_low <= self.clip_high:
            raise ValueError("normal: clip_low must be <= clip_high")
        return self


Distribution = Annotated[
    FixedDistribution | UniformDistribution | NormalDistribution, Field(discriminator="kind")
]


class InstanceParameterBinding(BaseModel):
    """Bind an assumption to one instance's parameter (the part default when the instance omits it)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["instance_parameter"]
    instance: str = Field(pattern=ID_PATTERN)
    parameter: str = Field(pattern=NAME_PATTERN)


class MaterialPropertyBinding(BaseModel):
    """Bind an assumption to one physical property of a material carried by the project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["material_property"]
    material: str = Field(pattern=ID_PATTERN)
    property: Literal["density", "yield_strength", "elastic_modulus", "friction"]


class PartSpecBinding(BaseModel):
    """Bind an assumption to one named specification of a part carried by the project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["part_spec"]
    part: str = Field(pattern=ID_PATTERN)
    spec: str = Field(pattern=NAME_PATTERN)


AssumptionBinding = Annotated[
    InstanceParameterBinding | MaterialPropertyBinding | PartSpecBinding, Field(discriminator="kind")
]
"""A typed design-value target. `Project` checks that it exists and has the assumption's unit."""


class Assumption(BaseModel):
    """One assumption of the verdict, as the human-review panel shows it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(
        pattern=NAME_PATTERN, description="Stable machine key, e.g. 'vehicle_mass'. Verdict sensitivities cite it."
    )
    label: str = Field(min_length=1, max_length=100, description="Name shown in the panel.")
    value: Quantity
    distribution: Distribution = Field(default_factory=lambda: FixedDistribution(kind="fixed"))
    confidence: Confidence
    editable: StrictBool = True
    binding: AssumptionBinding | None = None
    """The design value this row varies. `None` leaves the row explicitly unapplied by a verdict."""

    @field_validator("label")
    @classmethod
    def _label_has_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label must not be blank")
        return v

    @model_validator(mode="after")
    def _nominal_inside_support(self) -> "Assumption":
        d, v = self.distribution, self.value.value
        if isinstance(d, UniformDistribution) and not d.low <= v <= d.high:
            raise ValueError(f"nominal {v} is outside the uniform range [{d.low}, {d.high}]")
        if isinstance(d, NormalDistribution):
            if d.clip_low is not None and v < d.clip_low:
                raise ValueError(f"nominal {v} is below clip_low {d.clip_low}")
            if d.clip_high is not None and v > d.clip_high:
                raise ValueError(f"nominal {v} is above clip_high {d.clip_high}")
        return self


class AssumptionTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assumptions: tuple[Assumption, ...] = ()

    @model_validator(mode="after")
    def _keys(self) -> "AssumptionTable":
        keys = [a.key for a in self.assumptions]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate assumption key")
        for k in keys:
            if k in PLANET_CONSTANT_NAMES:
                raise ValueError(
                    f"{k!r} is a planet constant, not an assumption of the project: the engine reads it from data/bodies"
                )
        return self
