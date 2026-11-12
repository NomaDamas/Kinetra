"""Length expressions, positions and orientations shared by `PartDef` (C-01a) and the shape recipe (B-01a).

Split out of `partdef.py` so `shape.py` can use them without a circular import. `partdef` re-exports them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import NAME_PATTERN, QUATERNION_NORM_TOLERANCE
from .provenance import Number

Name = Annotated[str, Field(pattern=NAME_PATTERN)]


class ParamTerm(BaseModel):
    """`factor * <value of parameter param>`. The parameter must be a length."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    param: Name
    factor: Number


class AxisExpr(BaseModel):
    """A length in metres: `offset + sum(factor * param)`. A snap point coordinate in the part's local frame, or a
    dimension of a shape component (`shape.py`). Every `param` is a length parameter of the part."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: Number
    terms: tuple[ParamTerm, ...] = ()

    def evaluate(self, values: Mapping[str, float]) -> float:
        """The length in metres for the given parameter values [m]."""
        return self.offset + sum(t.factor * values[t.param] for t in self.terms)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: AxisExpr
    y: AxisExpr
    z: AxisExpr

    def evaluate(self, values: Mapping[str, float]) -> tuple[float, float, float]:
        return (self.x.evaluate(values), self.y.evaluate(values), self.z.evaluate(values))


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
