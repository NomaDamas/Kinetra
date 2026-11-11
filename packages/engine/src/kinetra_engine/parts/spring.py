"""Spring-damper (B-03e): the spring a part defines, the response a spring has, and a reference integration of it.

A joint carries a `JointSpring` (`kinetra_core.designspec`): stiffness k and damping c about the joint coordinate q,
which is 0 at the saved pose, so the restoring force (torque) is `-k q - c dq/dt`. A part with role `spring_damper`
(`PartDef._check_spring_damper`) carries k and c as the parameters `stiffness` and `damping`, each with its own badge and
source. This module is the three things between those two:

    joint_spring(part, parameters=None) -> JointSpring       # the part's k and c, with their badges, ready to put on a joint
    spring_response(spring, inertia) -> SpringResponse        # the closed forms: natural frequency, damping ratio, period
    integrate(spring, inertia, ...) -> Trajectory             # the force law integrated numerically (RK4), a check on the closed forms

`inertia` is the mass [kg] a slider's spring moves, or the moment of inertia [kg*m^2] about the axis of a hinge's. It is the
inertia of what hangs on the spring, not of the spring: a coil spring's own mass is not added (the limits are in
`docs/architecture/part-spring.md`).

The closed forms are the textbook second-order system $m\\ddot q + c\\dot q + k q = 0$: $\\omega_0 = \\sqrt{k/m}$, $\\zeta = c / (2\\sqrt{km})$,
damped $\\omega_d = \\omega_0\\sqrt{1-\\zeta^2}$ and period $T = 2\\pi/\\omega_d$ when $\\zeta < 1$. A system with $\\zeta \\ge 1$ does not oscillate and has no period.
The integrator uses no closed form: it steps the force law, so comparing its measured period to the closed form is a real test
of both. Gravity does not change the period (it shifts the equilibrium by $mg/k$ for a vertical slider); the integrator takes
an optional constant `force` for that case.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from kinetra_core import (
    SPRING_DAMPING,
    SPRING_STIFFNESS,
    JointSpring,
    PartDef,
    PartRole,
    Quantity,
    SpringDamping,
    SpringStiffness,
)

from ._shape import ShapeError, _resolve_parameters


def joint_spring(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> JointSpring:
    """The `JointSpring` of a `spring_damper` part at its default parameters or at `parameters` (an instance's overrides).

    Stiffness and damping keep the badge and source their parameter value had (the part's default, or the instance's own). A
    value outside the part's range, in another unit, or for a name the part does not have is a `ShapeError`, as for `mass_properties`.
    """
    if part.role is not PartRole.SPRING_DAMPER:
        raise ShapeError(f"part {part.id!r} has role {None if part.role is None else part.role.value!r}, not 'spring_damper'")
    values = _resolve_parameters(part, parameters)
    k, c = values[SPRING_STIFFNESS], values[SPRING_DAMPING]
    return JointSpring(
        stiffness=SpringStiffness(value=k.value, unit=k.unit, badge=k.badge, source=k.source),
        damping=SpringDamping(value=c.value, unit=c.unit, badge=c.badge, source=c.source),
    )


@dataclass(frozen=True)
class SpringResponse:
    """What a spring and damper do to an `inertia` hanging on them, from the second-order system's closed forms."""

    stiffness: float  # N/m or N*m/rad
    damping: float  # N*s/m or N*m*s/rad
    inertia: float  # kg or kg*m^2
    natural_frequency: float  # rad/s, sqrt(k/m): the frequency with no damping
    damping_ratio: float  # c / (2 sqrt(k m)); below 1 the motion oscillates
    damped_frequency: float | None  # rad/s, omega_0 sqrt(1 - zeta^2); None when damping_ratio >= 1
    period: float | None  # s, 2 pi / damped_frequency; None when it does not oscillate
    undamped_period: float  # s, 2 pi sqrt(m / k): the period the damper does not change much

    @property
    def oscillates(self) -> bool:
        return self.period is not None


def spring_response(spring: JointSpring, inertia: float) -> SpringResponse:
    """Natural frequency, damping ratio and period of `spring` carrying `inertia` (kg for a slider, kg*m^2 for a hinge)."""
    if not (math.isfinite(inertia) and inertia > 0.0):
        raise ValueError(f"the inertia on the spring must be a positive number, got {inertia}")
    k, c = spring.stiffness.value, spring.damping.value
    if not k > 0.0:
        raise ValueError("a spring with stiffness 0 has no natural frequency (a pure damper does not oscillate)")
    w0 = math.sqrt(k / inertia)
    zeta = c / (2.0 * math.sqrt(k * inertia))
    wd = w0 * math.sqrt(1.0 - zeta * zeta) if zeta < 1.0 else None
    return SpringResponse(
        stiffness=k,
        damping=c,
        inertia=inertia,
        natural_frequency=w0,
        damping_ratio=zeta,
        damped_frequency=wd,
        period=None if wd is None else 2.0 * math.pi / wd,
        undamped_period=2.0 * math.pi / w0,
    )


@dataclass(frozen=True)
class Trajectory:
    """The joint coordinate q [m or rad] and its rate [m/s or rad/s] at times `t` [s], equally spaced by `dt`."""

    dt: float
    t: tuple[float, ...]
    q: tuple[float, ...]
    v: tuple[float, ...]

    def upward_zero_crossings(self, about: float = 0.0) -> tuple[float, ...]:
        """Times at which q crosses `about` going up, each found by linear interpolation between two samples."""
        out = []
        for i in range(len(self.q) - 1):
            a, b = self.q[i] - about, self.q[i + 1] - about
            if a < 0.0 <= b:
                out.append(self.t[i] + self.dt * (-a) / (b - a))
        return tuple(out)

    def measured_period(self, about: float = 0.0) -> float:
        """Mean time between the first and the last upward crossings of `about`: the period of an oscillation about it.
        Needs at least two crossings."""
        c = self.upward_zero_crossings(about)
        if len(c) < 2:
            raise ValueError("fewer than two upward crossings: the motion does not oscillate over this duration")
        return (c[-1] - c[0]) / (len(c) - 1)


def integrate(
    spring: JointSpring,
    inertia: float,
    *,
    q0: float,
    v0: float = 0.0,
    duration: float,
    dt: float,
    force: float = 0.0,
) -> Trajectory:
    """Integrate $I \\ddot q = -k q - c \\dot q + F$ from `q0`, `v0` for `duration` seconds in steps of `dt` (classical RK4).

    `force` is a constant applied force [N] or torque [N*m]: a weight for a vertical slider. q is measured from the spring's
    rest (the saved pose), so a constant force moves the equilibrium to `force / stiffness`. No limits, no contact: the one
    spring on the one inertia, which is the thing the closed forms describe.
    """
    if not (math.isfinite(inertia) and inertia > 0.0 and dt > 0.0 and duration > 0.0):
        raise ValueError("inertia, dt and duration must be positive numbers")
    k, c = spring.stiffness.value, spring.damping.value

    def accel(q: float, v: float) -> float:
        return (-k * q - c * v + force) / inertia

    n = round(duration / dt)
    ts, qs, vs = [0.0], [q0], [v0]
    q, v = q0, v0
    for i in range(n):
        k1q, k1v = v, accel(q, v)
        k2q, k2v = v + 0.5 * dt * k1v, accel(q + 0.5 * dt * k1q, v + 0.5 * dt * k1v)
        k3q, k3v = v + 0.5 * dt * k2v, accel(q + 0.5 * dt * k2q, v + 0.5 * dt * k2v)
        k4q, k4v = v + dt * k3v, accel(q + dt * k3q, v + dt * k3v)
        q += dt / 6.0 * (k1q + 2 * k2q + 2 * k3q + k4q)
        v += dt / 6.0 * (k1v + 2 * k2v + 2 * k3v + k4v)
        ts.append((i + 1) * dt)
        qs.append(q)
        vs.append(v)
    return Trajectory(dt=dt, t=tuple(ts), q=tuple(qs), v=tuple(vs))
