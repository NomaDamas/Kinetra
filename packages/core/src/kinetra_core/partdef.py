"""`PartDef` (C-01a): a parametric part definition. Parameters with ranges, snap points, specifications.

Every number is a `Quantity` (badge and source required) except where noted on `SnapPoint`: a snap point's pose
is one declared value, so it carries one badge and source for the whole pose.

Not here: the shape recipe and mass/inertia (B-01a), collision proxy (B-01b), export policy (HW-02a), instances
and joints (C-01b), MJCF (X-01).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .conventions import QUATERNION_NORM_TOLERANCE, Unit
from .material import ID_PATTERN
from .provenance import Number, Provenance, Quantity, require_unit

NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class ParamDef(BaseModel):
    """A named parameter of the part with its default and allowed range, all in `unit`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=NAME_PATTERN)
    unit: Unit
    default: Quantity
    min: Quantity
    max: Quantity

    @model_validator(mode="after")
    def _range(self) -> "ParamDef":
        for field in ("default", "min", "max"):
            require_unit(getattr(self, field), self.unit, f"{self.name}.{field}")
        if not self.min.value <= self.default.value <= self.max.value:
            raise ValueError(
                f"{self.name}: need min <= default <= max, got {self.min.value} <= {self.default.value} <= {self.max.value}"
            )
        return self


class ParamTerm(BaseModel):
    """`factor * <value of parameter param>`. The parameter must be a length."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    param: str = Field(pattern=NAME_PATTERN)
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
        n = math.sqrt(self.x**2 + self.y**2 + self.z**2 + self.w**2)
        if abs(n - 1.0) > QUATERNION_NORM_TOLERANCE:
            raise ValueError(f"quaternion must have unit norm, got {n}")
        return self


class SnapPoint(Provenance):
    """A place where this part can attach to another. `kind` and `accepts` are compatibility tags (B-04b matches them).

    `position` is in metres in the part's local frame and may follow length parameters; `orientation` is the
    local frame of the snap point. Badge and source cover the whole pose.
    """

    id: str = Field(pattern=ID_PATTERN)
    kind: str = Field(pattern=NAME_PATTERN)
    accepts: tuple[str, ...] = ()
    position: Position
    orientation: Quaternion

    @field_validator("accepts")
    @classmethod
    def _accepts(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        import re

        for tag in v:
            if not re.fullmatch(NAME_PATTERN, tag):
                raise ValueError(f"accepts tag {tag!r} does not match {NAME_PATTERN}")
        if len(set(v)) != len(v):
            raise ValueError("accepts has duplicate tags")
        return v


class PartDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    parameters: tuple[ParamDef, ...] = ()
    snap_points: tuple[SnapPoint, ...] = ()
    specs: dict[str, Quantity] = Field(default_factory=dict)  # 사양: no-load speed, rated thrust, capacity ...

    @field_validator("specs")
    @classmethod
    def _spec_keys(cls, v: dict[str, Quantity]) -> dict[str, Quantity]:
        import re

        for key in v:
            if not re.fullmatch(NAME_PATTERN, key):
                raise ValueError(f"spec key {key!r} does not match {NAME_PATTERN}")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "PartDef":
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("duplicate parameter names")
        ids = [s.id for s in self.snap_points]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate snap point ids")
        units = {p.name: p.unit for p in self.parameters}
        for s in self.snap_points:
            for axis_name in ("x", "y", "z"):
                for t in getattr(s.position, axis_name).terms:
                    if t.param not in units:
                        raise ValueError(f"snap point {s.id!r}: unknown parameter {t.param!r}")
                    if units[t.param] is not Unit.M:
                        raise ValueError(f"snap point {s.id!r}: parameter {t.param!r} is not a length (m)")
        return self
