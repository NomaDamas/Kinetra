"""Thrust-to-weight ratio on each planet and burn time per thruster, before a run (X-07).

    thrust_to_weight(design, cache=None, bodies_directory=None) -> ThrustToWeight

An L0 analytic calculation ("해석 계산", `studio-plan.md` 정역학; `client-adapter.md` 파생값(L0)): closed formulas, no
simulation, no verdict. A ratio above 1 does not say the design lifts off (B-14 must not say so either).

**Thrust-to-weight** on planet p = sum of the thrusters' maximum thrust [N] / (total mass [kg] x g_p [m/s^2]), for every
planet in `BODY_IDS` (earth, mars, moon). g_p is the data file's gravity read through `load_body` (`data/bodies`), never a
number in code.

- **Thrusters** are the design's thruster actuators (`ActuatorKind.THRUSTER`, one per instance, `DesignSpec`). A thruster
  part with no actuator never fires and is not counted. A thruster's maximum thrust is the largest point of its `thrust` curve
  at command 1 (the curve is piecewise linear, so its maximum is a point). When that is the steady end of the curve it is the
  `rated_thrust` spec (equal to the last point, `PartDef`) and carries that spec's badge; a curve that overshoots its steady
  value gives its peak with the curve's badge.
- **Total mass** = every instance's mass (`assembly_mass`, B-02: the B-01a `mass_properties` of each, dry tanks) + every
  tank instance's capacity (`tank_supply`, B-03d, at the instance's parameters), drawn on or not, as `ThrustRun` loads them
  (`thrust.md`, rule 2). Full tanks: the tank parameter `initial_fill` is not read (assumption 1).

**Burn time** [s] per thruster actuator = what its tank holds when full [kg] / the mass flow at maximum thrust [kg/s] of every
thruster actuator that draws on that tank (`Actuator.supply`). The flow at a thrust is `thrust x propellant_flow /
rated_thrust` (B-03c), so at the rated thrust it is the `propellant_flow` spec. Thrusters that share a tank empty it together
and get the same time. A thruster with no tank (`supply` is `None`) is not metered: it gets no time and the reason
`no_propellant`. `propellant_flow` cannot be missing or 0: `PartDef` requires it positive on a thruster part.

**Badges (the weakest input).** Every value carries the badges of its inputs, by input (`InputBadges`): gravity (the data
file's), mass (the B-01a `Derivation.input_badges` of every instance and the tank capacities' `Supply.input_badges`: shape,
density, parameters, propellant density; a declared mass shows as `declared`), thrust (the spec's or the curve's), propellant
and propellant flow. The value's `badge` is the weakest of all of them, in `BADGE_STRENGTH` order. A computed value is never
better than its weakest input, so the result does not take the badge `sim` that would hide them.

**Assumptions** (`ASSUMPTIONS`, on the result so they reach the user with the number): full propellant, maximum thrust, no
change of thrust with the atmosphere, uniform gravity on flat ground, and all thrust along one line against gravity (the
magnitudes are added; directions are X-06's).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from kinetra_core import ActuatorKind, Badge, DesignSpec, PartDef, PartRole, Quantity, Unit
from kinetra_core.bodies import BODY_IDS, Gravity, load_body
from kinetra_core.partdef import THRUSTER_CURVE, THRUSTER_PROPELLANT_FLOW, THRUSTER_RATED_THRUST

from ..parts import PartCache, assembly_mass, tank_supply

GRADE = "L0"
GRADE_LABEL = "해석 계산"

BADGE_STRENGTH: tuple[Badge, ...] = (Badge.SIM, Badge.CITE, Badge.DEFAULT, Badge.DECLARED, Badge.ESTIMATE)
"""Strongest first; the weakest input is the one furthest down. Cited (read from a source with its locator) is above
default (chosen by us, with the reason in the source), which is above declared (the user's word; a result is only as good as
that declaration), which is above estimate (a weakly founded judgement, `project-model.md`). `sim` would only be an input if a
part wrote a computed number as its spec; it ranks first, as its own inputs are not visible here. Same order as `Badge`."""

ASSUMPTIONS = (
    "가정: 추진제 가득(모든 탱크 인스턴스가 용량만큼 찼다. 시작 채움 initial_fill은 읽지 않는다)",
    "가정: 최대 추력(모든 추력기가 명령 1에서 추력 곡선의 최댓값을 낸다)",
    "가정: 대기에 따른 추력 변화 없음",
    "가정: 평지의 균일 중력(행성마다 data/bodies의 g 하나)",
    "가정: 모든 추력이 중력 반대쪽 한 선 위에 있다(크기를 더한다. 방향과 추력중심은 보지 않는다)",
)


class NoValue(StrEnum):
    """Why a value is not given (no 0 or stand-in number takes its place)."""

    NO_THRUSTER = "no_thruster"  # the design has no thruster actuator: no thrust, so no ratio
    NO_PROPELLANT = "no_propellant"  # the thruster draws on no tank (`Actuator.supply` is None): nothing to burn


REASON_KO: dict[NoValue, str] = {
    NoValue.NO_THRUSTER: "추력기 액추에이터가 없다",
    NoValue.NO_PROPELLANT: "추력기에 연결된 탱크가 없다(추진제 없음)",
}


def _ordered(badges: Iterable[Badge]) -> tuple[Badge, ...]:
    return tuple(sorted(set(badges), key=BADGE_STRENGTH.index))


def weakest(badges: Iterable[Badge]) -> Badge:
    """The weakest of `badges` in `BADGE_STRENGTH` order. Raises `ValueError` for none."""
    ranked = _ordered(badges)
    if not ranked:
        raise ValueError("no input badge to rank")
    return ranked[-1]


@dataclass(frozen=True)
class InputBadges:
    """The distinct badges of one input of a value (strongest first)."""

    input: str  # "gravity", "mass", "dry_mass", "propellant", "thrust", "propellant_flow"
    badges: tuple[Badge, ...]


@dataclass(frozen=True)
class AnalyticValue:
    """A number computed by a closed formula: L0, not simulated. `badge` is the weakest badge of `inputs`."""

    value: float
    unit: Unit
    badge: Badge
    inputs: tuple[InputBadges, ...]
    grade: str = GRADE


def _value(value: float, unit: Unit, inputs: Iterable[tuple[str, Iterable[Badge]]]) -> AnalyticValue:
    """`inputs` may name one input more than once (two thrusters' thrust): the rows are merged by name, first seen first."""
    merged: dict[str, set[Badge]] = {}
    for name, badges in inputs:
        merged.setdefault(name, set()).update(badges)
    rows = tuple(InputBadges(name, _ordered(b)) for name, b in merged.items())
    return AnalyticValue(value, unit, weakest(b for r in rows for b in r.badges), rows)


@dataclass(frozen=True)
class PlanetRatio:
    """Thrust-to-weight on one planet, with the gravity it used (the data file's `Quantity`)."""

    planet: str
    gravity: Gravity
    ratio: AnalyticValue


@dataclass(frozen=True)
class ThrusterBurn:
    """One thruster actuator: its maximum thrust [N] and the flow there [kg/s], and its burn time on full propellant or the
    reason there is none. `shared_with` are the other thruster actuators on the same tank (they burn for the same time)."""

    actuator: str
    instance: str
    max_thrust: AnalyticValue
    mass_flow: AnalyticValue
    tank: str | None
    shared_with: tuple[str, ...]
    burn_time: AnalyticValue | None
    reason: NoValue | None


@dataclass(frozen=True)
class ThrustToWeight:
    """See the module docstring. `ratios` is empty and `reason` is `no_thruster` when the design has no thruster actuator;
    then `thrust` is `None` too."""

    mass: AnalyticValue
    thrust: AnalyticValue | None
    ratios: tuple[PlanetRatio, ...]
    burns: tuple[ThrusterBurn, ...]
    reason: NoValue | None
    assumptions: tuple[str, ...] = ASSUMPTIONS
    grade: str = GRADE
    grade_label: str = GRADE_LABEL


def _max_thrust(part: PartDef) -> tuple[float, tuple[Badge, ...]]:
    """Largest thrust of the part's curve at command 1 [N] and the badges it is read from."""
    curve = next(c.curve for c in part.curves if c.name == THRUSTER_CURVE)  # PartDef requires it on a thruster
    rated = next(s for s in part.specs if s.name == THRUSTER_RATED_THRUST)
    peak = max(p.y for p in curve.points)
    if peak <= curve.points[-1].y:
        return rated.value, (rated.badge,)  # the steady end is the maximum: the rated thrust spec
    return peak, (curve.badge,)


def thrust_to_weight(
    design: DesignSpec, cache: PartCache | None = None, bodies_directory: Path | None = None
) -> ThrustToWeight:
    """Thrust-to-weight on earth, mars and moon and burn time per thruster actuator of `design` (module docstring).
    Raises what `assembly_mass` and `load_body` raise (`ShapeError` naming the instance; a planet file that does not load)."""
    parts = {p.id: p for p in design.parts}
    instances = {i.id: i for i in design.instances}

    dry = assembly_mass(design, cache)
    capacities: dict[str, Quantity] = {}
    propellant_badges: dict[str, tuple[Badge, ...]] = {}
    for inst in design.instances:
        part = parts[inst.part]
        if part.role is PartRole.TANK:
            supply = tank_supply(part, {p.name: p for p in inst.parameters})
            capacities[inst.id] = supply.capacity
            propellant_badges[inst.id] = supply.input_badges
    mass_inputs: list[tuple[str, Iterable[Badge]]] = [("dry_mass", dry.input_badges)]
    if capacities:
        mass_inputs.append(("propellant", (b for bs in propellant_badges.values() for b in bs)))
    mass = _value(math.fsum([dry.total.value, *(c.value for c in capacities.values())]), Unit.KG, mass_inputs)

    thrusters = [a for a in design.actuators if a.kind is ActuatorKind.THRUSTER]
    peaks: dict[str, tuple[float, tuple[Badge, ...]]] = {}
    flows: dict[str, AnalyticValue] = {}
    for a in thrusters:
        part = parts[instances[a.instance].part]
        peak, peak_badges = _max_thrust(part)
        specs = {s.name: s for s in part.specs}
        flow, rated = specs[THRUSTER_PROPELLANT_FLOW], specs[THRUSTER_RATED_THRUST]
        peaks[a.id] = (peak, peak_badges)
        if peak == rated.value:  # the steady end is the maximum: the flow there is the spec itself
            flows[a.id] = _value(flow.value, Unit.KG_PER_S, [("propellant_flow", (flow.badge,))])
        else:
            flows[a.id] = _value(
                peak * flow.value / rated.value,
                Unit.KG_PER_S,
                [("thrust", (*peak_badges, rated.badge)), ("propellant_flow", (flow.badge,))],
            )

    burns: list[ThrusterBurn] = []
    for a in thrusters:
        peak, peak_badges = peaks[a.id]
        on_tank = [b for b in thrusters if a.supply is not None and b.supply == a.supply]
        burn_time: AnalyticValue | None = None
        if a.supply is not None:
            flow_total = math.fsum(flows[b.id].value for b in on_tank)
            burn_time = _value(
                capacities[a.supply].value / flow_total,
                Unit.S,
                [("propellant", propellant_badges[a.supply]), *((r.input, r.badges) for b in on_tank for r in flows[b.id].inputs)],
            )
        burns.append(
            ThrusterBurn(
                actuator=a.id,
                instance=a.instance,
                max_thrust=_value(peak, Unit.N, [("thrust", peak_badges)]),
                mass_flow=flows[a.id],
                tank=a.supply,
                shared_with=tuple(b.id for b in on_tank if b.id != a.id),
                burn_time=burn_time,
                reason=None if burn_time is not None else NoValue.NO_PROPELLANT,
            )
        )

    if not thrusters:
        return ThrustToWeight(mass=mass, thrust=None, ratios=(), burns=(), reason=NoValue.NO_THRUSTER)

    thrust = _value(
        math.fsum(peaks[a.id][0] for a in thrusters), Unit.N, [("thrust", (b for a in thrusters for b in peaks[a.id][1]))]
    )
    mass_badges = tuple(b for r in mass.inputs for b in r.badges)
    ratios = []
    for planet in BODY_IDS:
        g = load_body(planet, directory=bodies_directory).gravity
        ratios.append(
            PlanetRatio(
                planet,
                g,
                _value(thrust.value / (mass.value * g.value), Unit.ONE, [("gravity", (g.badge,)), ("mass", mass_badges), ("thrust", thrust.inputs[0].badges)]),
            )
        )
    return ThrustToWeight(mass=mass, thrust=thrust, ratios=tuple(ratios), burns=tuple(burns), reason=None)


__all__ = [
    "ASSUMPTIONS",
    "AnalyticValue",
    "BADGE_STRENGTH",
    "GRADE",
    "GRADE_LABEL",
    "InputBadges",
    "NoValue",
    "PlanetRatio",
    "REASON_KO",
    "ThrustToWeight",
    "ThrusterBurn",
    "thrust_to_weight",
    "weakest",
]
