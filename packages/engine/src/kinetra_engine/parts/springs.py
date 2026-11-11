"""Spring-dampers (B-03e): the stiffness and damping of a `spring_damper` part, and what they mean for a mass on it.

A spring-damper part carries two parameters, `stiffness` k [N/m] and `damping` c [N*s/m] (`kinetra_core.SPRING_STIFFNESS`,
`SPRING_DAMPING`), tuned like any other parameter (range-checked, overridden per instance). The force it exerts along its axis
is linear in the joint coordinate x [m] (0 at the saved pose, `project-model.md`) and its rate v [m/s]:

    F = -k x - c v

`oscillation(k, c, m)` is the textbook solution of m x'' + c x' + k x = 0 that the simulation has to reproduce:
undamped angular frequency w0 = sqrt(k / m), period T = 2 pi / w0, damping ratio zeta = c / (2 sqrt(k m)), and for
zeta < 1 the damped period T_d = T / sqrt(1 - zeta^2). Turning the part into a MuJoCo joint stiffness/damping, and what a
joint's own spring fields are, is X-01b.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from kinetra_core import SPRING_DAMPING, SPRING_STIFFNESS, PartDef, PartRole, Quantity

from ._shape import _resolve_parameters


@dataclass(frozen=True)
class SpringDamperCharacteristics:
    """The two numbers a spring-damper part is tuned by, at the parameter values used."""

    stiffness: float  # N/m, spring rate along the part's z axis
    damping: float  # N*s/m, viscous damping coefficient along the same axis


def spring_damper_characteristics(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> SpringDamperCharacteristics:
    """Stiffness and damping of a spring-damper part at its defaults or at `parameters` (an override outside the part's range
    raises `ShapeError`, an unknown name too)."""
    if part.role is not PartRole.SPRING_DAMPER:
        raise ValueError(f"part {part.id!r} has role {None if part.role is None else part.role.value!r}, not 'spring_damper'")
    q = _resolve_parameters(part, parameters)
    return SpringDamperCharacteristics(stiffness=q[SPRING_STIFFNESS].value, damping=q[SPRING_DAMPING].value)


def spring_damper_force(stiffness: float, damping: float, displacement: float, velocity: float) -> float:
    """Force [N] the spring-damper exerts on the moving end at coordinate `displacement` [m] and rate `velocity` [m/s]:
    `-k x - c v` (towards the saved pose, against the motion)."""
    return -stiffness * displacement - damping * velocity


@dataclass(frozen=True)
class Oscillation:
    """Free motion of a mass on a spring-damper."""

    natural_angular_frequency: float  # rad/s, sqrt(k / m)
    period: float  # s, undamped period 2 pi / w0
    damping_ratio: float  # 1, c / (2 sqrt(k m))
    critical_damping: float  # N*s/m, 2 sqrt(k m)
    damped_period: float | None  # s, T / sqrt(1 - zeta^2) when zeta < 1; None when the motion does not oscillate (zeta >= 1)


def oscillation(stiffness: float, damping: float, mass: float) -> Oscillation:
    """Natural frequency, period and damping of `mass` [kg] on a spring-damper (hand formulas, see the module docstring)."""
    if not (math.isfinite(stiffness) and stiffness > 0.0):
        raise ValueError(f"stiffness must be a positive finite number, got {stiffness}")
    if not (math.isfinite(damping) and damping >= 0.0):
        raise ValueError(f"damping must be a non-negative finite number, got {damping}")
    if not (math.isfinite(mass) and mass > 0.0):
        raise ValueError(f"mass must be a positive finite number, got {mass}")
    w0 = math.sqrt(stiffness / mass)
    c_crit = 2.0 * math.sqrt(stiffness * mass)
    zeta = damping / c_crit
    damped = 2.0 * math.pi / (w0 * math.sqrt(1.0 - zeta * zeta)) if zeta < 1.0 else None
    return Oscillation(w0, 2.0 * math.pi / w0, zeta, c_crit, damped)
