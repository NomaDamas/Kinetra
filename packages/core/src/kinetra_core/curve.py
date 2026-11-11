"""`Curve` (B-03b): a tabulated relation between two quantities, with one badge and source for the whole table.

A motor's torque-speed curve and a thruster's thrust curve (B-03c) are `Curve`s. They are points `(x, y)`, `x` strictly
increasing, joined by straight lines. There is no extrapolation: outside `[x_0, x_n]` the curve says nothing, and the
evaluation in `kinetra_engine.parts.curves` raises instead of guessing a value.

Units are per curve (`x_unit`, `y_unit`, from the closed `Unit` vocabulary), so the points are bare numbers in them;
the badge and source cover all points, the way a snap point's badge covers its whole pose (`partdef.py`). A curve whose
points come from different places is split into curves with one source each, or its source says where each point is from
(`Source.ref`/`locator`).

Which curve names a part must have for its role, and what shape they have, is `partdef.py` (`PartDef.role`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from .conventions import Unit
from .geometry import Name
from .provenance import Number, Provenance


class CurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Number
    y: Number


class Curve(Provenance):
    """Piecewise-linear `y(x)`: at least two points, `x` strictly increasing, in `x_unit` and `y_unit`."""

    x_unit: Unit
    y_unit: Unit
    points: tuple[CurvePoint, ...]

    @field_validator("points")
    @classmethod
    def _points(cls, v: tuple[CurvePoint, ...]) -> tuple[CurvePoint, ...]:
        if len(v) < 2:
            raise ValueError(f"a curve needs at least 2 points, got {len(v)}")
        for n, (a, b) in enumerate(zip(v, v[1:])):
            if not b.x > a.x:
                raise ValueError(f"x must be strictly increasing: points[{n}].x = {a.x}, points[{n + 1}].x = {b.x}")
        return v


class NamedCurve(BaseModel):
    """A curve a part defines under a name (`torque_speed` for a motor, `thrust` for a thruster)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name
    curve: Curve
