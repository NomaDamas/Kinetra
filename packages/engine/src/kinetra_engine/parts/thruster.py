"""Thruster part (B-03c): a game-level generic thrust source. Thrust curve, direction, propellant draw.

What is modelled: a force of `command x thrust(t)` newtons along a fixed axis of the part, applied at the nozzle, for as long
as the command is on and propellant is left. `t` is the time since the command went on, `thrust(t)` is the part's `thrust`
curve (a valve opening ramp, then steady). Propellant leaves at a mass flow in proportion to the thrust:
`mdot = thrust x propellant_flow / rated_thrust`, so the effective exhaust velocity `rated_thrust / propellant_flow`
(equivalently the specific impulse) is one number for the part.

What is not: combustion, nozzle flow, what the propellant is, how the thrust changes with tank pressure or ambient
pressure (the datasheet curves of thrust against inlet pressure are not read), the valve closing transient (the force
stops when the command goes off), thermal effects, and wear. Those are out of scope (`docs/architecture/parts-thruster.md`).

Frame: the `nozzle` snap point of the part sits at the nozzle exit and its +Z is the exhaust direction, so the force on
the part acts along -Z of that frame. `Thruster.direction` is that force direction in the part frame (a unit vector) and
`Thruster.position` is the nozzle point, in metres.

The curve is read here, not extrapolated by `curves.evaluate`: before time 0 the thrust is 0 and after the last point it
stays at the last value, which `PartDef` requires to be the rated (steady) thrust. This is the thruster's own rule: a
burn is as long as the command, which is longer than any table.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from kinetra_core import BADGE_LABEL_KO, Badge, PartDef, PartRole, Quantity, Unit
from kinetra_core.partdef import (
    THRUSTER_CURVE,
    THRUSTER_NOZZLE,
    THRUSTER_PROPELLANT_FLOW,
    THRUSTER_RATED_THRUST,
)

from kinetra_core.convex import rotation

G0 = 9.80665  # gravity-scan: ok standard gravity g0 of the Isp definition (CGPM 1901), not a planet constant
"""Standard gravity [m/s^2]. Used only to turn a specific impulse [s] into a mass flow (Isp = F / (mdot g0)), never as a planet value."""

CATALOG = Path(__file__).parent / "thruster_catalog.json"
OUT_OF_CATALOG_KO = "카탈로그 밖"
"""Qualifier of the value badge (design-system brief 4절): shown as `카탈로그 밖 · 사용자 선언`."""


class ThrusterError(ValueError):
    """The part is not a thruster this module can read, or the command or duration is not valid."""


@dataclass(frozen=True)
class Thruster:
    """A thruster part read at its default parameters. Times in s, thrust in N, flow in kg/s, lengths in m."""

    part_id: str
    times: tuple[float, ...]
    thrusts: tuple[float, ...]
    rated_thrust: float
    propellant_flow: float
    position: tuple[float, float, float]
    direction: tuple[float, float, float]
    """Unit vector of the force on the part, in the part frame (opposite of the exhaust)."""

    @property
    def exhaust_velocity(self) -> float:
        """Effective exhaust velocity [m/s] = rated thrust / mass flow."""
        return self.rated_thrust / self.propellant_flow

    @property
    def specific_impulse(self) -> float:
        """Specific impulse [s] = rated thrust / (mass flow x g0)."""
        return self.rated_thrust / (self.propellant_flow * G0)

    def thrust(self, t: float, command: float = 1.0) -> float:
        """Thrust [N] `t` seconds after the command went on to `command` in [0, 1]. 0 before it went on."""
        _check_command(command)
        if math.isnan(t) or math.isinf(t):
            raise ThrusterError(f"time must be finite, got {t}")
        if t < 0.0:
            return 0.0
        return command * self._at(t)

    def force(self, t: float, command: float = 1.0) -> tuple[float, float, float]:
        """Force on the part [N], part frame, at the nozzle point `position`."""
        f = self.thrust(t, command)
        return (f * self.direction[0], f * self.direction[1], f * self.direction[2])

    def mass_flow(self, t: float, command: float = 1.0) -> float:
        """Propellant mass flow [kg/s] at that moment: in proportion to the thrust."""
        return self.thrust(t, command) * self.propellant_flow / self.rated_thrust

    def _at(self, t: float) -> float:
        ts, fs = self.times, self.thrusts
        if t >= ts[-1]:
            return fs[-1]
        for i in range(len(ts) - 1):
            if t <= ts[i + 1]:
                return fs[i] + (fs[i + 1] - fs[i]) * (t - ts[i]) / (ts[i + 1] - ts[i])
        return fs[-1]  # unreachable: t < ts[-1] lies in some segment


@dataclass(frozen=True)
class Burn:
    """What one burn gives: command held at `command` from time 0 for `requested` seconds, or until the propellant is gone.

    `duration` is the time the thruster really fired (<= `requested`). `impulse` [N*s] is the integral of the thrust over
    that time and `propellant_used` [kg] the integral of the mass flow. Badge `sim` (computed from the part's numbers,
    exactly, not stepped); the inputs keep their own badges in the part.
    """

    requested: float
    duration: float
    command: float
    impulse: float
    propellant_used: float
    depleted: bool
    """True when the propellant ran out before `requested` (the thruster stopped at `duration`)."""
    badge: Badge = Badge.SIM


def _check_command(command: float) -> None:
    if not 0.0 <= command <= 1.0:
        raise ThrusterError(f"thruster command is a fraction in [0, 1], got {command}")


def thruster_from_part(part: PartDef) -> Thruster:
    """Read the thrust curve, rated thrust, propellant flow and nozzle frame of a `thruster` part (default parameters)."""
    if part.role is not PartRole.THRUSTER:
        raise ThrusterError(f"part {part.id!r} has role {part.role.value if part.role else None!r}, not 'thruster'")
    curve = next(c.curve for c in part.curves if c.name == THRUSTER_CURVE)  # PartDef guarantees it
    specs = {s.name: s for s in part.specs}
    nozzle = next(s for s in part.snap_points if s.id == THRUSTER_NOZZLE)
    values = {p.name: p.default.value for p in part.parameters}
    r = rotation(nozzle.orientation)
    exhaust = (r[0][2], r[1][2], r[2][2])  # the snap frame's +Z in the part frame
    return Thruster(
        part_id=part.id,
        times=tuple(p.x for p in curve.points),
        thrusts=tuple(p.y for p in curve.points),
        rated_thrust=specs[THRUSTER_RATED_THRUST].value,
        propellant_flow=specs[THRUSTER_PROPELLANT_FLOW].value,
        position=nozzle.position.evaluate(values),
        direction=(-exhaust[0], -exhaust[1], -exhaust[2]),
    )


def _impulse_and_time(th: Thruster, command: float, until_t: float, until_impulse: float) -> tuple[float, float]:
    """Integrate `command x thrust(t)` from 0 to the earlier of `until_t` and the time the impulse reaches
    `until_impulse`. Returns (time reached, impulse there). Exact: the curve is piecewise linear, so each piece is a
    trapezoid and the stop inside a piece solves a quadratic."""
    ts, fs = th.times, th.thrusts
    t, imp = 0.0, 0.0
    # Pieces: the table segments, then a constant piece to infinity at the last value.
    pieces = [(ts[i], ts[i + 1], fs[i], fs[i + 1]) for i in range(len(ts) - 1)]
    pieces.append((ts[-1], math.inf, fs[-1], fs[-1]))
    for t0, t1, f0, f1 in pieces:
        if t0 >= until_t:
            break
        if t0 > t:  # the table starts at 0 (PartDef), so this is the gap that never happens; keeps the loop total
            t = t0
        end = min(t1, until_t)
        slope = 0.0 if math.isinf(t1) else (f1 - f0) / (t1 - t0)
        a, b = command * f0, command * slope  # thrust = a + b*tau, tau measured from t0
        span = end - t0
        piece = a * span + 0.5 * b * span * span
        if imp + piece >= until_impulse:
            need = until_impulse - imp
            # a*tau + b*tau^2/2 = need, stable root
            disc = a * a + 2.0 * b * need
            tau = 0.0 if need <= 0.0 else 2.0 * need / (a + math.sqrt(max(disc, 0.0)))
            return t0 + tau, until_impulse
        imp += piece
        t = end
    return t, imp


def burn(th: Thruster, duration: float, command: float = 1.0, propellant: float | None = None) -> Burn:
    """Hold `command` for `duration` seconds from the moment it goes on, with `propellant` kg available (None: unlimited).

    The thrust follows the part's curve from time 0 and the propellant draw is the thrust times `propellant_flow /
    rated_thrust`. If the propellant would run out first the thruster stops there (`depleted`), and the impulse and
    the propellant used are those up to that moment. The propellant is never overdrawn.
    """
    _check_command(command)
    if not (duration >= 0.0 and math.isfinite(duration)):
        raise ThrusterError(f"burn duration must be finite and >= 0 s, got {duration}")
    if propellant is not None and not (propellant >= 0.0 and math.isfinite(propellant)):
        raise ThrusterError(f"available propellant must be finite and >= 0 kg, got {propellant}")
    k = th.propellant_flow / th.rated_thrust  # kg per N*s
    if command == 0.0:
        return Burn(duration, duration, command, 0.0, 0.0, False)
    limit = math.inf if propellant is None else propellant / k
    t, imp = _impulse_and_time(th, command, duration, limit)
    depleted = propellant is not None and t < duration
    return Burn(duration, t, command, imp, imp * k, depleted)


@cache
def catalog_thrusts() -> tuple[Quantity, ...]:
    """The rated thrusts [N] of the cited cold-gas thrusters (`thruster_catalog.json`): what 'in the catalog' means."""
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    return tuple(Quantity.model_validate(q) for q in raw["thrusts"])


@dataclass(frozen=True)
class CatalogFinding:
    """The rated thrust of a thruster part against the cited catalog range.

    `label` is what the value badge shows: the badge's name, with `카탈로그 밖 · ` before it when the value is outside
    [`catalog_min`, `catalog_max`] (closed range over the cited thrusts only).
    """

    value: float
    unit: Unit
    badge: Badge
    catalog_min: float
    catalog_max: float
    in_catalog: bool
    label: str


def catalog_finding(part: PartDef) -> CatalogFinding:
    """Is the rated thrust of `part` inside what the cited catalog covers?

    A value outside the range is not refused: it is shown as `카탈로그 밖 · <its badge>` (a declared 8 kN thruster reads
    `카탈로그 밖 · 사용자 선언`), and the verdict is only as good as that declaration. A value inside the range is shown
    with its own badge: being in the range does not make a declared value a cited one.
    """
    if part.role is not PartRole.THRUSTER:
        raise ThrusterError(f"part {part.id!r} is not a thruster")
    values = [q.value for q in catalog_thrusts()]
    lo, hi = min(values), max(values)
    spec = next(s for s in part.specs if s.name == THRUSTER_RATED_THRUST)
    inside = lo <= spec.value <= hi
    label = BADGE_LABEL_KO[spec.badge]
    return CatalogFinding(
        value=spec.value,
        unit=spec.unit,
        badge=spec.badge,
        catalog_min=lo,
        catalog_max=hi,
        in_catalog=inside,
        label=label if inside else f"{OUT_OF_CATALOG_KO} · {label}",
    )
