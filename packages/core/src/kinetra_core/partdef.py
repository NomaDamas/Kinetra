"""`PartDef` (C-01a): a parametric part definition. Parameters with ranges, snap points, specifications.

Every number is a `Quantity` (badge and source required) except a snap point's pose, which is one declared value:
it carries one badge and source for the whole pose.

Collections are tuples, so a `PartDef` is immutable and hashable. Order is part of the value and is preserved;
the canonical order that definition hashes use is `canonical.py` (C-03).

The optional `shape` (B-01a, `shape.py`) is the recipe mass, centre of mass and inertia are computed from. The
optional `mass_parameter` (B-02c) names a kg parameter that fixes the mass itself; the recipe then only places it.

Not here: the computation (`kinetra_engine.parts`, result in `massprops.py`), collision proxy (B-01b), export policy (HW-02a), instances
and joints (C-01b), MJCF (X-01).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .conventions import ID_PATTERN, Unit
from .curve import NamedCurve
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


class PartRole(StrEnum):
    """What a part is for, where the simulation needs to know (B-03b). A part without a role is only a body.

    The actuator on an instance must fit its part's role (`designspec.py`): a motor actuator drives a `motor` part, a
    thruster actuator a `thruster` part. What a role requires of the definition is checked by `PartDef` (the
    required curves and specs), so a part that says `motor` always has the numbers a motor needs.
    """

    MOTOR = "motor"
    THRUSTER = "thruster"
    WHEEL = "wheel"
    BATTERY = "battery"
    TANK = "tank"
    SPRING_DAMPER = "spring_damper"


MOTOR_CURVE = "torque_speed"
"""Name of a motor's torque-speed curve in `PartDef.curves`: x = shaft speed [rad/s], y = torque [N*m] at full command."""
MOTOR_RATED_VOLTAGE = "rated_voltage"
"""Name of the spec a motor part must have: the supply voltage [V] the curve is for."""

THRUSTER_CURVE = "thrust"
"""Name of a thruster's thrust curve in `PartDef.curves` (B-03c): x = time since the command went on [s], y = thrust [N] at
full command. After the last point the thrust stays at the last value (steady burn)."""
THRUSTER_RATED_THRUST = "rated_thrust"
"""Spec a thruster part must have: the steady thrust [N] at full command. It equals the last point of the thrust curve."""
THRUSTER_PROPELLANT_FLOW = "propellant_flow"
"""Spec a thruster part must have: propellant mass flow [kg/s] at the rated thrust. Flow follows thrust in proportion."""
THRUSTER_OPENING_RESPONSE = "opening_response"
"""Optional spec of a thruster part: the time [s] from the command to full thrust. When present it must equal the time at
which the `thrust` curve first reaches the rated thrust, so the spec and the curve cannot tell two different rises."""
THRUSTER_NOZZLE = "nozzle"
"""Snap point a thruster part must have: at the nozzle exit; its +Z is the exhaust direction, the thrust on the part is -Z."""


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
    role: PartRole | None = None
    curves: tuple[NamedCurve, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "PartDef":
        for label, names in (
            ("parameter name", [p.name for p in self.parameters]),
            ("snap point id", [s.id for s in self.snap_points]),
            ("spec name", [s.name for s in self.specs]),
            ("curve name", [c.name for c in self.curves]),
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
        if self.role is PartRole.MOTOR:
            self._check_motor()
        if self.role is PartRole.THRUSTER:
            self._check_thruster()
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

    def _check_motor(self) -> None:
        """A motor part has a rated voltage and a torque-speed curve of a motor: it starts at stall and ends at no load.

        The curve is `(speed [rad/s], torque [N*m])`. It starts at speed 0 with a positive stall torque, ends at a
        positive no-load speed with torque 0, and the torque never rises with speed. A motor that can push harder
        while it spins faster is not a motor this model knows (a DC motor's torque falls with speed).
        """
        by_name = {c.name: c.curve for c in self.curves}
        curve = by_name.get(MOTOR_CURVE)
        if curve is None:
            raise ValueError(f"a motor part needs the curve {MOTOR_CURVE!r} (speed [rad/s] -> torque [N*m])")
        if (curve.x_unit, curve.y_unit) != (Unit.RAD_PER_S, Unit.N_M):
            raise ValueError(
                f"curve {MOTOR_CURVE!r} is speed [rad/s] -> torque [N*m], got {curve.x_unit.value!r} -> {curve.y_unit.value!r}"
            )
        pts = curve.points
        if pts[0].x != 0.0:
            raise ValueError(f"curve {MOTOR_CURVE!r} starts at speed 0 (stall), got {pts[0].x}")
        if not pts[0].y > 0.0:
            raise ValueError(f"curve {MOTOR_CURVE!r}: stall torque must be positive, got {pts[0].y}")
        if pts[-1].y != 0.0:
            raise ValueError(f"curve {MOTOR_CURVE!r} ends at no load (torque 0), got {pts[-1].y} N*m at {pts[-1].x} rad/s")
        for a, b in zip(pts, pts[1:]):
            if b.y > a.y:
                raise ValueError(
                    f"curve {MOTOR_CURVE!r}: torque must not rise with speed, but goes {a.y} -> {b.y} N*m "
                    f"between {a.x} and {b.x} rad/s"
                )
        spec = next((s for s in self.specs if s.name == MOTOR_RATED_VOLTAGE), None)
        if spec is None:
            raise ValueError(f"a motor part needs the spec {MOTOR_RATED_VOLTAGE!r} (V)")
        if spec.unit is not Unit.V or not spec.value > 0.0:
            raise ValueError(f"spec {MOTOR_RATED_VOLTAGE!r} is a positive voltage in 'V', got {spec.value} {spec.unit.value!r}")

    def _check_thruster(self) -> None:
        """A thruster part is a game-level thrust source: a thrust curve, a rated thrust, a propellant flow and a nozzle frame.

        The curve is `(time since the command went on [s], thrust [N])`: it starts at time 0, never goes negative and
        ends at the positive steady thrust, which is the `rated_thrust` spec. The `propellant_flow` spec [kg/s] is the
        mass flow at that thrust. The `nozzle` snap point gives where the force acts and which way (its +Z is the exhaust
        direction). Nothing here says what the propellant is or how it burns: that is outside the model (B-03c).
        """
        by_name = {c.name: c.curve for c in self.curves}
        curve = by_name.get(THRUSTER_CURVE)
        if curve is None:
            raise ValueError(f"a thruster part needs the curve {THRUSTER_CURVE!r} (time [s] -> thrust [N])")
        if (curve.x_unit, curve.y_unit) != (Unit.S, Unit.N):
            raise ValueError(
                f"curve {THRUSTER_CURVE!r} is time [s] -> thrust [N], got {curve.x_unit.value!r} -> {curve.y_unit.value!r}"
            )
        pts = curve.points
        if pts[0].x != 0.0:
            raise ValueError(f"curve {THRUSTER_CURVE!r} starts at time 0 (the command goes on), got {pts[0].x}")
        if any(p.y < 0.0 for p in pts):
            raise ValueError(f"curve {THRUSTER_CURVE!r}: thrust must not be negative")
        if not pts[-1].y > 0.0:
            raise ValueError(f"curve {THRUSTER_CURVE!r} ends at the steady thrust, which must be positive, got {pts[-1].y}")
        specs = {s.name: s for s in self.specs}
        for name, unit in ((THRUSTER_RATED_THRUST, Unit.N), (THRUSTER_PROPELLANT_FLOW, Unit.KG_PER_S)):
            spec = specs.get(name)
            if spec is None:
                raise ValueError(f"a thruster part needs the spec {name!r} ({unit.value})")
            if spec.unit is not unit or not spec.value > 0.0:
                raise ValueError(f"spec {name!r} is positive in {unit.value!r}, got {spec.value} {spec.unit.value!r}")
        rated = specs[THRUSTER_RATED_THRUST].value
        if abs(rated - pts[-1].y) > 1e-9 * max(abs(rated), abs(pts[-1].y)):
            raise ValueError(
                f"spec {THRUSTER_RATED_THRUST!r} ({rated} N) must equal the last point of curve {THRUSTER_CURVE!r} ({pts[-1].y} N)"
            )
        opening = specs.get(THRUSTER_OPENING_RESPONSE)
        if opening is not None:
            if opening.unit is not Unit.S or not opening.value > 0.0:
                raise ValueError(f"spec {THRUSTER_OPENING_RESPONSE!r} is positive in 's', got {opening.value} {opening.unit.value!r}")
            rise = next(p.x for p in pts if abs(p.y - rated) <= 1e-9 * abs(rated))
            if abs(opening.value - rise) > 1e-9 * max(opening.value, rise):
                raise ValueError(
                    f"spec {THRUSTER_OPENING_RESPONSE!r} ({opening.value} s) must equal the time the curve {THRUSTER_CURVE!r} "
                    f"first reaches the rated thrust ({rise} s)"
                )
        if not any(sp.id == THRUSTER_NOZZLE for sp in self.snap_points):
            raise ValueError(f"a thruster part needs the snap point {THRUSTER_NOZZLE!r} (nozzle exit, +Z = exhaust direction)")

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
