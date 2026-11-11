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
from .provenance import Badge, Provenance, Quantity
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
    required curves, specs and parameters), so a part that says `motor` always has the numbers a motor needs and one that says
    `spring_damper` has its stiffness and damping (B-03e).
    """

    MOTOR = "motor"
    THRUSTER = "thruster"
    WHEEL = "wheel"
    BATTERY = "battery"
    TANK = "tank"
    SPRING_DAMPER = "spring_damper"
    SEPARATOR = "separator"


MOTOR_CURVE = "torque_speed"
"""Name of a motor's torque-speed curve in `PartDef.curves`: x = shaft speed [rad/s], y = torque [N*m] at full command."""
MOTOR_RATED_VOLTAGE = "rated_voltage"
"""Name of the spec a motor part must have: the supply voltage [V] the curve is for."""
SPRING_STIFFNESS = "stiffness"
"""Name of the parameter a spring-damper part must have: the spring rate [N/m] along its axis."""
SPRING_DAMPING = "damping"
"""Name of the parameter a spring-damper part must have: the viscous damping coefficient [N*s/m] along its axis."""

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
BATTERY_ENERGY_CAPACITY = "energy_capacity"
"""Name of the spec a battery part must have: the energy [J] it holds when full (B-03d)."""
BATTERY_NOMINAL_VOLTAGE = "nominal_voltage"
"""Name of the spec a battery part must have: its nominal terminal voltage [V], what a motor's `rated_voltage` is compared with."""
BATTERY_INITIAL_CHARGE = "initial_charge"
"""Optional parameter of a battery part: the fraction of the capacity it starts with, a dimensionless number in [0, 1]. Absent: full."""
TANK_PROPELLANT_DENSITY = "propellant_density"
"""Name of the parameter a tank part must have: the mean density [kg/m^3] of what it holds when full (B-03d). The capacity
[kg] is this times the volume of the tank's inside, so resizing the tank resizes what it holds. The inside is the shape's
`subtract` components. No propellant is named and no pressure or temperature is modelled: it is one number the user sets."""
TANK_INITIAL_FILL = "initial_fill"
"""Optional parameter of a tank part: the fraction of the capacity it starts with, dimensionless in [0, 1]. Absent: full."""

SEPARATOR_IMPULSE = "separation_impulse"
"""Name of the parameter a separator part must have (B-15): the declared separation impulse [N*s] the part gives each side when it
lets go, 0 allowed. It is the only number about how the release pushes: no energy source is named or modelled. The value is
the user's (`사용자 선언`) or the definition's placeholder (`기본값`); other badges are rejected."""
SEPARATOR_FACE_A = "face_a"
"""Snap point a separator part must have: the face of side `a`, at +Z of the part. The declared impulse pushes the body joined here
along +Z of this frame (outward) and the body joined at `face_b` the opposite way."""
SEPARATOR_FACE_B = "face_b"
"""Snap point a separator part must have: the face of side `b`, at -Z of the part, its +Z (outward normal) pointing to -Z."""
SEPARATOR_BADGES = frozenset({Badge.DECLARED, Badge.DEFAULT})
"""The badges a separation impulse may carry: the user declared it or the definition's default stands in. A cited, estimated or
simulated impulse would claim a source for a number no source exists for (V5)."""


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
        if self.role is PartRole.SPRING_DAMPER:
            self._check_spring_damper()
        if self.role is PartRole.THRUSTER:
            self._check_thruster()
        if self.role is PartRole.SEPARATOR:
            self._check_separator()
        if self.role is PartRole.BATTERY:
            self._check_battery()
        if self.role is PartRole.TANK:
            self._check_tank()
        return self

    def _check_separator(self) -> None:
        """A separator part is a declared-mass body that holds two parts together and lets go on command (B-15).

        Its specification is a mass (`mass_parameter`), dimensions (length parameters) and the declared separation impulse
        (`separation_impulse` [N*s], never negative, badge `declared` or `default`), and nothing else: no specs, no curves
        and no other parameter, so no field can carry an energy source (what pushes, how). The release itself is an event of
        the simulation (X-08). It needs the two faces the held parts are joined to.
        """
        if self.mass_parameter is None:
            raise ValueError("a separator part declares its mass: it needs a mass_parameter (kg)")
        if self.specs:
            raise ValueError(f"a separator part has no specs, its specification is parameters: got {[s.name for s in self.specs]}")
        if self.curves:
            raise ValueError(f"a separator part has no curves: got {[c.name for c in self.curves]}")
        by_name = {p.name: p for p in self.parameters}
        impulse = by_name.get(SEPARATOR_IMPULSE)
        if impulse is None:
            raise ValueError(f"a separator part needs the parameter {SEPARATOR_IMPULSE!r} (N*s)")
        if impulse.unit is not Unit.N_S:
            raise ValueError(f"parameter {SEPARATOR_IMPULSE!r} is an impulse in 'N*s', got {impulse.unit.value!r}")
        if not impulse.min.value >= 0.0:
            raise ValueError(f"parameter {SEPARATOR_IMPULSE!r}: min must not be negative, got {impulse.min.value} N*s (0 is allowed)")
        for label, q in (("default", impulse.default), ("min", impulse.min), ("max", impulse.max)):
            if q.badge not in SEPARATOR_BADGES:
                raise ValueError(
                    f"parameter {SEPARATOR_IMPULSE!r} {label}: badge must be 'declared' or 'default', got {q.badge.value!r}"
                )
        for p in self.parameters:
            if p.name == SEPARATOR_IMPULSE or p.name == self.mass_parameter:
                continue
            if p.unit is not Unit.M:
                raise ValueError(
                    f"a separator part's parameters are its mass, its dimensions (m) and {SEPARATOR_IMPULSE!r}; "
                    f"{p.name!r} is in {p.unit.value!r}"
                )
        ids = {s.id for s in self.snap_points}
        for need in (SEPARATOR_FACE_A, SEPARATOR_FACE_B):
            if need not in ids:
                raise ValueError(f"a separator part needs the snap point {need!r} (the face one held part is joined to)")

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

    def _check_battery(self) -> None:
        """A battery part says how much energy it holds and at what voltage (specs `energy_capacity` [J], `nominal_voltage` [V])."""
        specs = {s.name: s for s in self.specs}
        for name, unit in ((BATTERY_ENERGY_CAPACITY, Unit.J), (BATTERY_NOMINAL_VOLTAGE, Unit.V)):
            spec = specs.get(name)
            if spec is None:
                raise ValueError(f"a battery part needs the spec {name!r} ({unit.value})")
            if spec.unit is not unit or not spec.value > 0.0:
                raise ValueError(f"spec {name!r} is a positive number in {unit.value!r}, got {spec.value} {spec.unit.value!r}")
        self._check_fraction_param(BATTERY_INITIAL_CHARGE)

    def _check_tank(self) -> None:
        """A tank part has an inside (a shape with a `subtract` component) and the parameter `propellant_density` [kg/m^3],
        positive over its whole range. Capacity = density x volume of the inside (`kinetra_engine.parts.tank_supply`)."""
        if self.shape is None or not any(c.operation == "subtract" for c in self.shape.components):
            raise ValueError("a tank part needs a shape with an inside: at least one 'subtract' component")
        rho = next((p for p in self.parameters if p.name == TANK_PROPELLANT_DENSITY), None)
        if rho is None:
            raise ValueError(f"a tank part needs the parameter {TANK_PROPELLANT_DENSITY!r} (kg/m^3), the density of what it holds")
        if rho.unit is not Unit.KG_PER_M3 or not rho.min.value > 0.0:
            raise ValueError(
                f"parameter {TANK_PROPELLANT_DENSITY!r} is a positive density in 'kg/m^3' over its whole range, "
                f"got unit {rho.unit.value!r}, min {rho.min.value}"
            )
        self._check_fraction_param(TANK_INITIAL_FILL)

    def _check_fraction_param(self, name: str) -> None:
        p = next((p for p in self.parameters if p.name == name), None)
        if p is not None and (p.unit is not Unit.ONE or p.min.value < 0.0 or p.max.value > 1.0):
            raise ValueError(
                f"parameter {name!r} is a fraction: unit '1' and range inside [0, 1], got {p.unit.value!r} [{p.min.value}, {p.max.value}]"
            )

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

    def _check_spring_damper(self) -> None:
        """A spring-damper part has the two parameters the user tunes: a stiffness [N/m] that stays above zero over the
        whole range (a zero spring is not a spring) and a damping [N*s/m] that is never negative (negative damping
        feeds energy into the motion). Zero damping is allowed: an undamped spring is a spring."""
        by_name = {p.name: p for p in self.parameters}
        k = by_name.get(SPRING_STIFFNESS)
        if k is None:
            raise ValueError(f"a spring-damper part needs the parameter {SPRING_STIFFNESS!r} (N/m)")
        if k.unit is not Unit.N_PER_M:
            raise ValueError(f"parameter {SPRING_STIFFNESS!r} is a spring rate in 'N/m', got {k.unit.value!r}")
        if not k.min.value > 0.0:
            raise ValueError(f"parameter {SPRING_STIFFNESS!r}: min must be above zero over the whole range, got {k.min.value} N/m")
        c = by_name.get(SPRING_DAMPING)
        if c is None:
            raise ValueError(f"a spring-damper part needs the parameter {SPRING_DAMPING!r} (N*s/m)")
        if c.unit is not Unit.N_S_PER_M:
            raise ValueError(f"parameter {SPRING_DAMPING!r} is a damping coefficient in 'N*s/m', got {c.unit.value!r}")
        if not c.min.value >= 0.0:
            raise ValueError(f"parameter {SPRING_DAMPING!r}: min must not be negative, got {c.min.value} N*s/m")
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
