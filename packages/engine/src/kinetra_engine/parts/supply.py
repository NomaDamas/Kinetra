"""What a battery or a tank holds and what is left after it is drawn on (B-03d).

    battery_supply(part, parameters=None) -> Supply   # energy [J]
    tank_supply(part, parameters=None) -> Supply      # propellant mass [kg]
    supply.draw(amount) -> Draw                       # take an amount now
    supply.draw_rate(rate, dt) -> Draw                # take a rate [W or kg/s] for dt [s]
    electrical_power(mechanical_power, efficiency)    # what a motor takes from a battery to deliver a mechanical power
    tank_total_mass(dry_mass, supply)                 # the tank part's mass with what is left in it

A `Supply` is a value, not a simulation: drawing returns a new one. The simulation (X-01b for motors, X-01c for
thrusters) owns the one `Supply` per supply instance (`Actuator.supply`) and passes it through every step, so two
actuators that draw from the same instance spend the same stock.

When a request is larger than what is left, the supply gives what it has and says so (`Draw.delivered < Draw.requested`,
`Draw.satisfied < 1`). The caller scales the actuator's output by `satisfied` over that step: a motor that gets half the
energy it asked for does half the work. A supply never goes below zero.

What this does not model (the same limits are in `docs/architecture/parts-battery-tank.md`): the battery's voltage sag with
state of charge, discharge rate, temperature and ageing (the capacity is one number, in joules, at the part's nominal
voltage); regeneration (a draw is never negative); propellant temperature and pressure (a tank holds a mass).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from kinetra_core import Badge, PartDef, PartRole, Quantity, Source, Unit
from kinetra_core.partdef import (
    BATTERY_ENERGY_CAPACITY,
    BATTERY_INITIAL_CHARGE,
    TANK_INITIAL_FILL,
    TANK_PROPELLANT_DENSITY,
)

from ._shape import ShapeError, _resolve_parameters, parameter_uses, resolve_shape

__all__ = ["Draw", "Supply", "SupplyError", "battery_supply", "electrical_power", "tank_supply", "tank_total_mass"]


class SupplyError(ValueError):
    """A request to a supply that no supply can honour: a negative or non-finite amount, rate or time step (B-03f)."""


@dataclass(frozen=True)
class Draw:
    """The result of taking from a supply: the supply afterwards, what was asked for and what it could give (same unit)."""

    supply: "Supply"
    requested: float
    delivered: float

    @property
    def satisfied(self) -> float:
        """`delivered / requested` in [0, 1]; 1 for a request of nothing."""
        return 1.0 if self.requested == 0.0 else self.delivered / self.requested


@dataclass(frozen=True)
class Supply:
    """A battery's energy [J] or a tank's propellant mass [kg]: its capacity and what is left.

    `capacity` is a battery's spec as written (its own badge and source) or, for a tank, a computed value (badge `sim`,
    source: the computation). A computed value hides how good its inputs were, so `input_badges` lists the distinct badges
    of what the capacity came from, in `Badge` order (a battery: the badge of the spec itself)."""

    part_id: str
    role: PartRole
    capacity: Quantity
    remaining: float
    input_badges: tuple[Badge, ...]

    def __post_init__(self) -> None:
        if self.role is PartRole.BATTERY and self.capacity.unit is not Unit.J:
            raise ValueError(f"a battery's capacity is in 'J', got {self.capacity.unit.value!r}")
        if self.role is PartRole.TANK and self.capacity.unit is not Unit.KG:
            raise ValueError(f"a tank's capacity is in 'kg', got {self.capacity.unit.value!r}")
        if self.role not in (PartRole.BATTERY, PartRole.TANK):
            raise ValueError(f"a supply is a battery or a tank, got role {self.role.value!r}")
        if not (math.isfinite(self.capacity.value) and self.capacity.value > 0.0):
            raise ValueError(f"capacity must be a positive finite number, got {self.capacity.value}")
        if not (math.isfinite(self.remaining) and 0.0 <= self.remaining <= self.capacity.value):
            raise ValueError(f"remaining must be in [0, capacity={self.capacity.value}], got {self.remaining}")

    @property
    def unit(self) -> Unit:
        return self.capacity.unit

    @property
    def fraction(self) -> float:
        """What is left of what the supply holds when full, in [0, 1]."""
        return self.remaining / self.capacity.value

    @property
    def empty(self) -> bool:
        return self.remaining == 0.0

    def draw(self, amount: float) -> Draw:
        """Take `amount` (J or kg, not negative). Gives what is left if that is less."""
        if not (math.isfinite(amount) and amount >= 0.0):
            raise SupplyError(f"an amount drawn is a finite number that is not negative, got {amount}")
        delivered = min(amount, self.remaining)
        left = 0.0 if delivered == self.remaining else self.remaining - delivered
        return Draw(replace(self, remaining=left), amount, delivered)

    def draw_rate(self, rate: float, dt: float) -> Draw:
        """Take `rate` (W for a battery, kg/s for a tank) for `dt` seconds.

        Both are checked on their own: a negative rate is refused even when `dt` is 0 (the product `-1.0 * 0.0` is `-0.0`
        and would pass a check of the amount alone), and so is an infinite rate with `dt` 0 (`inf * 0` is NaN)."""
        if not (math.isfinite(rate) and rate >= 0.0):
            raise SupplyError(f"a rate drawn is a finite number that is not negative, got {rate}")
        if not (math.isfinite(dt) and dt >= 0.0):
            raise SupplyError(f"a time step is a finite number that is not negative, got {dt}")
        return self.draw(rate * dt)

    def time_to_empty(self, rate: float) -> float:
        """Seconds until empty at a constant `rate` (W or kg/s) from now. `math.inf` at a rate of 0."""
        if not (math.isfinite(rate) and rate >= 0.0):
            raise SupplyError(f"a rate drawn is a finite number that is not negative, got {rate}")
        return math.inf if rate == 0.0 else self.remaining / rate


def _fraction(name: str, params: dict[str, Quantity]) -> float:
    q = params.get(name)
    return 1.0 if q is None else q.value


def battery_supply(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> Supply:
    """The energy a battery part holds at the start: spec `energy_capacity` times the parameter `initial_charge` (default 1)."""
    if part.role is not PartRole.BATTERY:
        raise ShapeError(f"part {part.id!r} is not a battery (role {part.role.value if part.role else None!r})")
    spec = next(s for s in part.specs if s.name == BATTERY_ENERGY_CAPACITY)  # PartDef checked it is there
    capacity = Quantity(value=spec.value, unit=spec.unit, badge=spec.badge, source=spec.source)
    start = _fraction(BATTERY_INITIAL_CHARGE, _resolve_parameters(part, parameters))
    return Supply(part.id, PartRole.BATTERY, capacity, capacity.value * start, (spec.badge,))


def tank_supply(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> Supply:
    """The propellant a tank part holds at the start.

    Capacity [kg] = `propellant_density` [kg/m^3] x the volume of the tank's inside [m^3] (the sum of the shape's `subtract`
    components, at the parameter values). `initial_fill` (default 1) is the fraction it starts with."""
    if part.role is not PartRole.TANK:
        raise ShapeError(f"part {part.id!r} is not a tank (role {part.role.value if part.role else None!r})")
    resolved = resolve_shape(part, parameters)
    inside = sum(pl.volume for pl in resolved.placed if pl.component.operation == "subtract")
    rho = resolved.quantities[TANK_PROPELLANT_DENSITY]
    assert part.shape is not None
    badges = {part.shape.badge, rho.badge, *(u.value.badge for u in parameter_uses(part, resolved))}
    source = Source(
        ref=(
            f"computed: capacity = propellant_density ({rho.value!r} kg/m^3; {rho.badge.value}) x inside volume "
            f"({inside!r} m^3, the shape's subtract components) of part {part.id}"
        )[:500]
    )
    capacity = Quantity(value=rho.value * inside, unit=Unit.KG, badge=Badge.SIM, source=source)
    fill = _fraction(TANK_INITIAL_FILL, resolved.quantities)
    return Supply(part.id, PartRole.TANK, capacity, capacity.value * fill, tuple(sorted(badges, key=list(Badge).index)))


def electrical_power(mechanical_power: float, efficiency: float) -> float:
    """Electrical power [W] a motor takes to deliver `mechanical_power` [W] at `efficiency` (0 < efficiency <= 1).

    $P_\\mathrm{el} = P_\\mathrm{mech} / \\eta$. A motor that is braked by its load (negative mechanical power) takes nothing
    and gives nothing back: regeneration is not modelled."""
    if not (math.isfinite(efficiency) and 0.0 < efficiency <= 1.0):
        raise ValueError(f"efficiency is in (0, 1], got {efficiency}")
    if not math.isfinite(mechanical_power):
        raise ValueError(f"mechanical power must be finite, got {mechanical_power}")
    return max(mechanical_power, 0.0) / efficiency


def tank_total_mass(dry_mass: float, supply: Supply) -> float:
    """The mass [kg] of a tank part with what is left in it: its own (dry) mass plus the propellant."""
    if supply.role is not PartRole.TANK:
        raise ValueError("only a tank carries propellant mass")
    if not (math.isfinite(dry_mass) and dry_mass > 0.0):
        raise ValueError(f"dry mass must be a positive finite number, got {dry_mass}")
    return dry_mass + supply.remaining
