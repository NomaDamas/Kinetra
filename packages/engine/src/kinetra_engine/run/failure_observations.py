"""Observed threshold crossings for J-06, computed from the actual public-tick engine state.

These are run events, not failure causes and not a verdict. `kinetra_judge.failure_cause` decides later whether a failed
goal makes any of them a cause. In particular an airborne overturn observation retains `grounded=False`, and an empty tank
whose scheduled burn completed exactly retains `unmet=False`.

The watcher is called at tick 0 after collision detection and after each completed public tick. It does not step, release,
or otherwise mutate the simulation. Support geometry reuses X-03a's convex-hull and signed-margin formulas; contact forces
come from `mj_contactForce`, motor demand/availability from `DriveRuntime.last_steps`, and tank/thrust values from the
`ThrustStep` returned by `ThrustRun.begin_step`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import mujoco
import numpy as np

from ..compiler import GROUND_GEOM, PROP_GEOM_PREFIX
from ..compiler.drives import MotorStep
from ..compiler.thrust import ThrustStep
from ..statics.tipover import SupportPoint, _hull, _line_distance, _segment_distance, _xy

Pair = tuple[str, str, str]
"""Body id, other kind (`ground`, `prop`, `body`), other id (empty for ground)."""


def _target(kind: str, ident: str) -> dict:
    return {"kind": "ground"} if kind == "ground" else {"kind": kind, "id": ident}


def _margin(p: tuple[float, float], hull: list[SupportPoint]) -> float | None:
    """X-03a's signed distance: positive inside, negative outside, None without support."""
    if not hull:
        return None
    if len(hull) == 1:
        return -math.dist(p, _xy(hull[0]))
    if len(hull) == 2:
        return -_segment_distance(p, _xy(hull[0]), _xy(hull[1]))
    pairs = list(zip(hull, hull[1:] + hull[:1]))
    distances = [_line_distance(p, _xy(a), _xy(b)) for a, b in pairs]
    if min(distances) >= 0.0:
        return min(distances)
    return -min(_segment_distance(p, _xy(a), _xy(b)) for a, b in pairs)


def _reference_length(p: tuple[float, float], hull: list[SupportPoint]) -> float:
    """Measured scale for the dimensionless overturn margin: support diameter or COM offset, whichever is larger."""
    points = [_xy(s) for s in hull]
    centre = tuple(math.fsum(q[k] for q in points) / len(points) for k in range(2))
    diameter = max((math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1 :]), default=0.0)
    return max(diameter, math.dist(p, centre))


class FailureObservationWatch:
    """Threshold-crossing state for one run; only public events are emitted, never per-substep guesses."""

    def __init__(self) -> None:
        self._last_support: list[SupportPoint] = []
        self._outside: tuple[bool, bool] | None = None  # (outside, grounded)
        self._slipping: set[Pair] = set()
        self._short: set[str] = set()
        self._empty: dict[str, tuple[bool, bool]] = {}  # actuator -> (empty, unmet request active)

    def events(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        tick: int,
        *,
        motor_steps: Sequence[MotorStep] = (),
        thrust_step: ThrustStep | None = None,
    ) -> list[dict]:
        ground_points: list[SupportPoint] = []
        contacts: dict[Pair, list[float]] = {}
        force = np.zeros(6)
        for index in range(data.ncon):
            contact = data.contact[index]
            if contact.dist > 0.0:
                continue
            g1, g2 = int(contact.geom1), int(contact.geom2)
            names = (model.geom(g1).name, model.geom(g2).name)
            body_rows = (int(model.geom_bodyid[g1]), int(model.geom_bodyid[g2]))
            body_names = tuple(model.body(row).name if row > 0 else "" for row in body_rows)
            pair: Pair | None = None
            if GROUND_GEOM in names:
                side = names.index(GROUND_GEOM)
                other = 1 - side
                if body_rows[other] > 0:
                    pair = (body_names[other], "ground", "")
                    ground_points.append(SupportPoint(body_names[other], "contact", tuple(float(v) for v in contact.pos)))
            elif any(name.startswith(PROP_GEOM_PREFIX) for name in names):
                side = next(i for i, name in enumerate(names) if name.startswith(PROP_GEOM_PREFIX))
                other = 1 - side
                if body_rows[other] > 0:
                    pair = (body_names[other], "prop", names[side][len(PROP_GEOM_PREFIX) :])
            elif body_rows[0] > 0 and body_rows[1] > 0 and body_rows[0] != body_rows[1]:
                a, b = sorted(body_names)
                pair = (a, "body", b)
            if pair is None:
                continue
            mujoco.mj_contactForce(model, data, index, force)
            normal = max(0.0, float(force[0]))
            tangential = math.hypot(float(force[1]), float(force[2]))
            row = contacts.setdefault(pair, [0.0, 0.0])
            row[0] += tangential
            row[1] += max(0.0, float(contact.friction[0])) * normal

        out = self._overturn(model, data, tick, ground_points)
        # A Coulomb solver caps the delivered force at the cone boundary instead of returning the larger force that
        # sticking would require. Reaching that boundary with a nonzero tangential force is therefore the observable
        # slip event; a solver overshoot is included by the same `>=` rule.
        slipping = {pair for pair, (tangential, limit) in contacts.items() if tangential > 0.0 and tangential >= limit}
        for body, kind, ident in sorted(slipping):
            if (body, kind, ident) in self._slipping:
                continue
            tangential, limit = contacts[(body, kind, ident)]
            out.append(
                {
                    "kind": "slip",
                    "tick": tick,
                    "body": body,
                    "other": _target(kind, ident),
                    "tangential": {"value": tangential, "unit": "N"},
                    "friction_limit": {"value": limit, "unit": "N"},
                }
            )
        self._slipping = slipping

        short = {step.actuator for step in motor_steps if step.required > step.limit}
        by_actuator = {step.actuator: step for step in motor_steps}
        for actuator in sorted(short - self._short):
            step = by_actuator[actuator]
            out.append(
                {
                    "kind": "torque_shortage",
                    "tick": tick,
                    "actuator": actuator,
                    "required": {"value": step.required, "unit": "N*m"},
                    "limit": {"value": step.limit, "unit": "N*m"},
                }
            )
        self._short = short

        if thrust_step is not None:
            out.extend(self._propellant(thrust_step, tick))
        return out

    def _overturn(self, model: mujoco.MjModel, data: mujoco.MjData, tick: int, ground_points: list[SupportPoint]) -> list[dict]:
        if ground_points:
            self._last_support = _hull(ground_points, 0.0)
            hull = self._last_support
            grounded = True
        else:
            hull = self._last_support
            grounded = False
        if not hull:
            self._outside = None
            return []
        masses = np.asarray(model.body_mass[1:], dtype=float)
        if not len(masses) or math.fsum(masses) <= 0.0:
            self._outside = None
            return []
        rotations = np.asarray(data.xmat[1:], dtype=float).reshape((-1, 3, 3))
        centres = np.asarray(data.xpos[1:], dtype=float) + np.einsum("nij,nj->ni", rotations, model.body_ipos[1:])
        com = np.sum(centres * masses[:, None], axis=0) / math.fsum(masses)
        p = (float(com[0]), float(com[1]))
        margin = _margin(p, hull)
        if margin is None or margin >= 0.0:
            self._outside = None
            return []
        state = (True, grounded)
        if state == self._outside:
            return []
        self._outside = state
        reference = _reference_length(p, hull)
        return [
            {
                "kind": "overturn",
                "tick": tick,
                "grounded": grounded,
                "margin": {"value": margin, "unit": "m"},
                "reference_length": {"value": reference, "unit": "m"},
            }
        ]

    def _propellant(self, step: ThrustStep, tick: int) -> list[dict]:
        out = []
        active: dict[str, tuple[bool, bool]] = {}
        for thruster in step.thrusters:
            if thruster.supply is None:
                continue
            empty = step.remaining[thruster.supply] == 0.0
            unmet = thruster.requested > 0.0 and thruster.satisfied < 1.0
            state = (empty, unmet)
            active[thruster.actuator] = state
            previous = self._empty.get(thruster.actuator, (False, False))
            if empty and (not previous[0] or unmet and not previous[1]):
                out.append(
                    {
                        "kind": "propellant_depleted",
                        "tick": tick,
                        "actuator": thruster.actuator,
                        "tank": thruster.supply,
                        "requested": {"value": thruster.requested, "unit": "N"},
                        "available": {"value": thruster.thrust, "unit": "N"},
                        "remaining": {"value": step.remaining[thruster.supply], "unit": "kg"},
                        "unmet": unmet,
                    }
                )
        self._empty = active
        return out
