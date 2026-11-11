"""Evaluating a part's curves (B-03b): `Curve` lookup and the motor's torque-speed limit.

A `Curve` (`kinetra_core.curve`) is piecewise linear and says nothing outside its first and last `x`. `evaluate` is exact
at the points and linear between them; outside it raises `CurveRangeError`. It never extrapolates (a line extended past
a datasheet's last point is a claim the datasheet does not make).

`motor_torque_limit` is what a motor's `torque_speed` curve means for the simulation: the torque the motor can deliver
at full command (command 1) at a given shaft speed. Beyond the no-load speed the motor can deliver no torque (0 N*m):
that is the curve's own end (torque 0 at no-load), not an extrapolation, and the model has no braking or
regeneration quadrant. How a command between 0 and 1 scales it, and the sign of the command, is the compiler's (X-01b).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from kinetra_core import MOTOR_CURVE, MOTOR_RATED_VOLTAGE, Curve, PartDef, PartRole


class CurveRangeError(ValueError):
    """`x` is outside the range the curve is defined on."""


def evaluate(curve: Curve, x: float) -> float:
    """`y(x)` by linear interpolation between the neighbouring points. Raises `CurveRangeError` outside `[x_first, x_last]`."""
    pts = curve.points
    lo, hi = pts[0].x, pts[-1].x
    if not lo <= x <= hi:
        raise CurveRangeError(f"x = {x} {curve.x_unit.value} is outside the curve's range [{lo}, {hi}] {curve.x_unit.value}")
    i = bisect.bisect_right([p.x for p in pts], x)
    if i == len(pts):  # x == last point
        return pts[-1].y
    a, b = pts[i - 1], pts[i]
    t = (x - a.x) / (b.x - a.x)
    return a.y + t * (b.y - a.y)


@dataclass(frozen=True)
class MotorCharacteristics:
    """The numbers a motor part is specified by, read from its definition (not computed from a model)."""

    stall_torque: float  # N*m, torque at speed 0, command 1
    no_load_speed: float  # rad/s, speed at which the torque has fallen to 0, command 1
    rated_voltage: float  # V, the supply the curve is for


def _motor_curve(part: PartDef) -> Curve:
    if part.role is not PartRole.MOTOR:
        raise ValueError(f"part {part.id!r} has role {None if part.role is None else part.role.value!r}, not 'motor'")
    return next(c.curve for c in part.curves if c.name == MOTOR_CURVE)  # PartDef validated that it exists


def motor_characteristics(part: PartDef) -> MotorCharacteristics:
    """Stall torque, no-load speed and rated voltage of a motor part (the curve's end points and the rated-voltage spec)."""
    curve = _motor_curve(part)
    volts = next(s.value for s in part.specs if s.name == MOTOR_RATED_VOLTAGE)
    return MotorCharacteristics(stall_torque=curve.points[0].y, no_load_speed=curve.points[-1].x, rated_voltage=volts)


def motor_torque_limit(part: PartDef, speed: float) -> float:
    """Torque [N*m] the motor can deliver at full command at shaft speed `speed` [rad/s] (direction does not matter).

    The motor's `torque_speed` curve at `|speed|`; 0 at and beyond its no-load speed.
    """
    curve = _motor_curve(part)
    s = abs(speed)
    if s >= curve.points[-1].x:
        return 0.0
    return evaluate(curve, s)
