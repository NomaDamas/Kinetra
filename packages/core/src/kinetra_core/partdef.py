"""`PartDef` (C-01a): a parametric part definition. Parameters with ranges, snap points, specifications.

Every number is a `Quantity` (badge and source required) except a snap point's pose, which is one declared value:
it carries one badge and source for the whole pose.

Collections are tuples, so a `PartDef` is immutable and hashable. Order is part of the value and is preserved;
the canonical form for definition hashes (C-03) is C-03's to fix.

The optional `shape` (B-01a, `shape.py`) is the recipe mass, centre of mass and inertia are computed from. The
optional `mass_parameter` (B-02c) names a kg parameter that fixes the mass itself; the recipe then only places it.

Not here: the computation (`kinetra_engine.parts`, result in `massprops.py`), collision proxy (B-01b), export policy (HW-02a), instances
and joints (C-01b), MJCF (X-01).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .conventions import ID_PATTERN, Unit
from .geometry import AxisExpr, Name, ParamTerm, Position, Quaternion  # noqa: F401  (AxisExpr, ParamTerm: re-exported)
from .provenance import Provenance, Quantity
from .shape import Shape


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
    shape: Shape | None = None
    mass_parameter: Name | None = None
    """B-02c. Names a parameter in kg whose value *is* the part's mass (a payload, a ballast weight, a datasheet mass).
    The shape recipe then only says where that mass sits: it is spread uniformly over the recipe's net volume. A part
    without it gets its mass from the instance's material density times the shape volume. The value is the instance's
    (`Instance.parameters`) or this definition's default, with its own badge and source."""

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
        if self.shape is not None:
            self._check_shape(self.shape, {p.name: p for p in self.parameters})
        if self.mass_parameter is not None:
            self._check_mass_parameter(self.mass_parameter, {p.name: p for p in self.parameters})
        return self

    def _check_mass_parameter(self, name: str, params: dict[str, ParamDef]) -> None:
        p = params.get(name)
        if p is None:
            raise ValueError(f"mass_parameter {name!r} is not a parameter of the part")
        if p.unit is not Unit.KG:
            raise ValueError(f"mass_parameter {name!r} must be in 'kg', got {p.unit.value!r}")
        if not p.min.value > 0.0:
            raise ValueError(f"mass_parameter {name!r}: min must be above zero over the whole range, got {p.min.value} kg")
        if self.shape is None:
            raise ValueError("mass_parameter needs a shape recipe: the mass is spread over the recipe's volume")

    @staticmethod
    def _check_shape(shape: Shape, params: dict[str, ParamDef]) -> None:
        for comp in shape.components:
            for path, expr in comp.axis_exprs():
                where = f"shape component {comp.id!r} {path}"
                lo = hi = expr.offset
                for param in sorted({t.param for t in expr.terms}):
                    if param not in params:
                        raise ValueError(f"{where}: unknown parameter {param!r}")
                    if params[param].unit is not Unit.M:
                        raise ValueError(f"{where}: parameter {param!r} is not a length (m)")
                    # Terms of one parameter are summed first: the expression is linear, so its extremes are at the range ends.
                    factor = sum(t.factor for t in expr.terms if t.param == param)
                    a, b = factor * params[param].min.value, factor * params[param].max.value
                    lo, hi = lo + min(a, b), hi + max(a, b)
                if path.startswith("primitive.") and lo <= 0.0:
                    raise ValueError(
                        f"{where}: must stay above zero over the whole parameter range, but reaches {lo} m"
                    )
