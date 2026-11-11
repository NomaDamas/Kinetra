"""`PartDef` (C-01a): a parametric part definition. Parameters with ranges, snap points, specifications.

Every number is a `Quantity` (badge and source required) except a snap point's pose, which is one declared value:
it carries one badge and source for the whole pose.

Collections are tuples, so a `PartDef` is immutable and hashable. Order is part of the value and is preserved;
the canonical form for definition hashes (C-03) is C-03's to fix.

Not here: the shape recipe and mass/inertia (B-01a), collision proxy (B-01b), export policy (HW-02a), instances
and joints (C-01b), MJCF (X-01).
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .conventions import ID_PATTERN, NAME_PATTERN, QUATERNION_NORM_TOLERANCE, Unit
from .provenance import Number, Provenance, Quantity

Name = Annotated[str, Field(pattern=NAME_PATTERN)]


class ParamDef(BaseModel):
    """A named parameter of the part with its default and allowed range, all in `unit`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name
    unit: Unit
    default: Quantity
    min: Quantity
    max: Quantity

    @field_validator("default", "min", "max")
    @classmethod
    def _unit_matches(cls, q: Quantity, info: ValidationInfo) -> Quantity:
        unit = info.data.get("unit")
        if unit is not None and q.unit is not unit:
            raise ValueError(f"must be in {unit.value!r} like the parameter, got {q.unit.value!r}")
        return q

    @model_validator(mode="after")
    def _range(self) -> "ParamDef":
        if not self.min.value <= self.default.value <= self.max.value:
            raise ValueError(
                f"{self.name}: need min <= default <= max, got {self.min.value} <= {self.default.value} <= {self.max.value}"
            )
        return self


class SpecDef(Quantity):
    """A named specification (사양): no-load speed, rated thrust, capacity ... Name and unit are the part's."""

    name: Name


class ParamTerm(BaseModel):
    """`factor * <value of parameter param>`. The parameter must be a length."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    param: Name
    factor: Number


class AxisExpr(BaseModel):
    """One coordinate of a snap point in the part's local frame [m]: `offset + sum(factor * param)`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: Number
    terms: tuple[ParamTerm, ...] = ()


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: AxisExpr
    y: AxisExpr
    z: AxisExpr


class Quaternion(BaseModel):
    """Unit quaternion with named components (`conventions.py`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Number
    y: Number
    z: Number
    w: Number

    @model_validator(mode="after")
    def _unit_norm(self) -> "Quaternion":
        n = math.hypot(self.x, self.y, self.z, self.w)  # no overflow for huge finite components
        if abs(n - 1.0) > QUATERNION_NORM_TOLERANCE:
            raise ValueError(f"quaternion must have unit norm, got {n}")
        return self


class SnapPoint(Provenance):
    """A place where this part can attach to another. `kind` and `accepts` are compatibility tags (B-04b matches them).

    `position` is in metres in the part's local frame and may follow length parameters; `orientation` is the
    local frame of the snap point. Badge and source cover the whole pose.
    """

    id: str = Field(pattern=ID_PATTERN)
    kind: Name
    accepts: tuple[Name, ...] = ()
    position: Position
    orientation: Quaternion

    @field_validator("accepts")
    @classmethod
    def _unique(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError("accepts has duplicate tags")
        return v


class PartDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    parameters: tuple[ParamDef, ...] = ()
    snap_points: tuple[SnapPoint, ...] = ()
    specs: tuple[SpecDef, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "PartDef":
        for label, names in (
            ("parameter name", [p.name for p in self.parameters]),
            ("snap point id", [s.id for s in self.snap_points]),
            ("spec name", [s.name for s in self.specs]),
        ):
            if len(set(names)) != len(names):
                raise ValueError(f"duplicate {label}")
        param_names = {p.name for p in self.parameters}
        for s in self.snap_points:
            if s.id in param_names:
                raise ValueError(f"snap point id {s.id!r} collides with a parameter name")
        for s in self.specs:
            if s.name in param_names:
                raise ValueError(f"spec name {s.name!r} collides with a parameter name")
        units = {p.name: p.unit for p in self.parameters}
        for s in self.snap_points:
            for axis_name in ("x", "y", "z"):
                for t in getattr(s.position, axis_name).terms:
                    if t.param not in units:
                        raise ValueError(f"snap point {s.id!r}: unknown parameter {t.param!r}")
                    if units[t.param] is not Unit.M:
                        raise ValueError(f"snap point {s.id!r}: parameter {t.param!r} is not a length (m)")
        return self
