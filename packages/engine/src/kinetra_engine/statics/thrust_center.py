"""Resultant thrust, thrust line and torque about the centre of mass at one moment of the control schedule (X-06).

    thrust_center(model, t=None) -> ThrustCenter      # model: compile_thrust(project) (X-01c)

An L0 analytic number (`client-adapter.md`, "파생값(L0)"; `studio-plan.md` 정역학): no simulation, no verdict.

**Which thrusters.** With a schedule (any thruster actuator has an entry, whatever its command) the result is for the
moment `t` [s] and only the thrusters on then count: a thruster is on when one of its openings has `start <= t < end`
(`Opening`, X-01c: touching entries are one opening; a command-0 entry is off), and its thrust is `command x thrust(t - on)`
(`Thruster.thrust`, the part's curve, B-03c). A thruster whose tank is empty at `t` gives 0. The thrusters are never all
added up in place of the ones on: when none is on at `t` (or every entry commands 0) the resultant is 0. Only a design with
no thruster entry at all counts every thruster at the highest point of its thrust curve (command 1), and the result says
so (`basis = "max_thrust"`, `basis_note`).

**Propellant and centre of mass (X-01c's rule).** What a tank holds is mass on the tank's body, spread evenly over the
tank's inside (`ThrustModel.mass_of`). With a schedule each tank holds its start amount minus what its thrusters drew from
0 to `t`, the exact integral of their curves times `propellant_flow / rated_thrust` (`CompiledThruster.impulse`); thrusters
sharing a tank draw together and all stop when it is empty (B-03d: the same fraction for all), so the tank holds
`max(0, start - asked)`. Without a schedule the tanks hold their start amount and the result says "추진제 가득 기준".

**Forces.** Every body is at its stored pose (joints at coordinate 0), as in X-03a. A thruster's force is its thrust along
its nozzle's force direction at the nozzle point (X-01c, `CompiledThruster.position`, `.direction`), world frame. The
resultant is `F = sum f_i` and the torque about the centre of mass `c` is `tau = sum (p_i - c) x f_i`.

**Thrust line.** When `F` is not 0 the forces reduce to `F` along one line plus a couple along that line (the central axis
of the wrench). The line has direction `F / |F|` and passes through `center = c + F x tau / |F|^2`, its point nearest to
`c`; `moment_arm = |center - c|` and `axial_torque = (tau . F) F / |F|^2` (0 when the forces lie in one plane or are
parallel, as with nozzles all pointing one way). When `F` is 0 the forces are a pure couple: `center`, `direction` and
`moment_arm` are `None` and only `torque` stands. `F` counts as 0 when `|F| <= ZERO_FORCE_RATIO x sum |f_i|`.

**Badges.** The inputs keep their own. `ThrusterForce.badge` is the badge of what the thrust number was read from: on the
steady part of the curve (from its last point on, and the max-thrust basis when the curve tops out at the rated thrust) the
value is the rated thrust (`PartDef` makes the curve end there), so the `rated_thrust` spec's badge (`인용` for a datasheet
part, `사용자 선언` for one the user declared); on the opening ramp, the thrust curve's badge (the library parts' ramp shape is
`추정`). `ThrustCenter.input_badges` are the distinct ones of the thrusters counted, in `Badge` order. The result's grade is
L0 "해석 계산" (`GRADE`, `GRADE_LABEL_KO`).

Safety line (`docs/process/review-rubric.md` 1): game-level forces only; no propellant chemistry, combustion or nozzle flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from kinetra_core import BADGE_LABEL_KO, Badge, THRUSTER_CURVE, THRUSTER_RATED_THRUST

from ..compiler.bodytree import Vec, mv, rot, vadd, vsub
from ..compiler.thrust import CompiledThruster, ThrustModel

GRADE = "L0"
GRADE_LABEL_KO = "해석 계산"

ZERO_FORCE_RATIO = 1e-12
"""A numerical choice, not a physical value: a resultant this small against the sum of the thrusts it adds is rounding
(nozzle directions turned by stored quaternions carry ~1e-16 of error), so the forces are a pure couple."""

SCHEDULE_NOTE = "기준: 제어 스케줄 t = {t:g} s에 켜진 추력기만"
MAX_THRUST_NOTE = "스케줄 없음: 모든 추력기 최대 추력 기준"
PROPELLANT_DRAWN_NOTE = "추진제: 시작 채움에서 t까지 스케줄대로 소모한 양(X-01c 방식: 탱크 안쪽에 고르게 퍼짐)"
PROPELLANT_FULL_NOTE = "추진제 가득 기준: 탱크마다 설계의 시작 채움량, 소모 반영 없음"

ASSUMPTIONS = (
    "가정: 모든 결합은 저장된 자세(좌표 0)에 고정되고 추력 방향과 작용점도 그 자세의 값이다",
    "가정: 추진제는 탱크 안쪽에 고르게 퍼져 있고 탱크 안에서 움직이지 않는다(X-01c)",
    "가정: 추력은 탱크 압력과 주변 압력에 따라 줄지 않는다(B-03c)",
    "가정: 추력만 더한다. 중력, 접촉, 모터 토크, 항력은 들어 있지 않다",
)

Basis = Literal["schedule", "max_thrust"]


@dataclass(frozen=True)
class ThrusterForce:
    """One thruster counted: its actuator and instance, command (1 on the max-thrust basis), thrust [N], nozzle point [m]
    and unit force direction, world frame, the badge of the thrust value (module docstring), and whether its tank was empty."""

    actuator: str
    instance: str
    command: float
    thrust: float
    point: Vec
    direction: Vec
    badge: Badge
    tank_empty: bool

    @property
    def badge_ko(self) -> str:
        return BADGE_LABEL_KO[self.badge]


@dataclass(frozen=True)
class ThrustCenter:
    """See the module docstring. World frame; N, N m, m, kg, s."""

    time: float | None  # None on the max-thrust basis
    basis: Basis
    thrusters: tuple[ThrusterForce, ...]  # the ones counted, actuator id order
    mass: float
    center_of_mass: Vec
    propellant: dict[str, float]  # kg in each tank instance
    force: Vec
    torque: Vec  # about the centre of mass
    center: Vec | None  # point of the thrust line nearest the centre of mass; None for a pure couple
    direction: Vec | None  # unit, along the resultant
    moment_arm: float | None  # distance from the centre of mass to the thrust line
    axial_torque: Vec | None  # the part of `torque` along the line (the wrench's couple), None for a pure couple
    input_badges: tuple[Badge, ...]
    basis_note: str
    propellant_note: str
    grade: str = GRADE
    grade_label: str = GRADE_LABEL_KO
    assumptions: tuple[str, ...] = ASSUMPTIONS

    @property
    def couple_only(self) -> bool:
        return self.center is None


def thrust_center(model: ThrustModel, t: float | None = None) -> ThrustCenter:
    """The resultant thrust of the thrusters on at `t` [s] of the schedule, its line and its torque about the centre of mass
    (module docstring). Without a thruster schedule, every thruster at its highest thrust and `t` is not read. Raises
    `ValueError` for a design with a schedule and no `t`, or a `t` that is negative or not finite."""
    thruster_ids = {th.actuator for th in model.thrusters}
    scheduled = any(e.actuator in thruster_ids for e in model.tree.design.schedule.entries)
    if scheduled:
        if t is None:
            raise ValueError("the design has a thruster schedule: give the time t [s] to compute the thrust at")
        if not math.isfinite(t) or t < 0.0:
            raise ValueError(f"t must be finite and not negative, got {t}")
    tree = model.tree
    frames = {i.instance: (i.position, rot(i.orientation)) for i in tree.instances}
    parts = {p.id: p for p in tree.design.parts}
    part_of = {i.id: i.part for i in tree.design.instances}

    asked: dict[str, float] = {}
    if scheduled:
        for th in model.thrusters:
            if th.supply is not None:
                k = th.thruster.propellant_flow / th.thruster.rated_thrust
                asked[th.supply] = asked.get(th.supply, 0.0) + th.impulse(0.0, t) * k  # type: ignore[arg-type]
    propellant = {s.instance: max(0.0, s.supply.remaining - asked.get(s.instance, 0.0)) for s in model.stores}
    empty = {s.instance for s in model.stores if asked.get(s.instance, 0.0) >= s.supply.remaining}

    forces: list[ThrusterForce] = []
    for th in model.thrusters:
        on = _command(th, t) if scheduled else (1.0, None)
        if on is None:
            continue
        command, opened = on
        dry = th.supply is not None and th.supply in empty
        steady = max(th.thruster.thrusts) == th.thruster.rated_thrust if opened is None else t - opened >= th.thruster.times[-1]  # type: ignore[operator]
        if dry:
            thrust = 0.0
        elif opened is None:
            thrust = max(th.thruster.thrusts)
        else:
            thrust = th.thruster.thrust(t - opened, command)  # type: ignore[operator]
        tb, rb = frames[th.body]
        part = parts[part_of[th.instance]]
        badge = (next(s.badge for s in part.specs if s.name == THRUSTER_RATED_THRUST) if steady
                 else next(nc.curve.badge for nc in part.curves if nc.name == THRUSTER_CURVE))
        forces.append(ThrusterForce(th.actuator, th.instance, command, thrust, vadd(mv(rb, th.position), tb), mv(rb, th.direction), badge, dry))

    weighted: list[tuple[float, Vec]] = []
    for body in tree.bodies:
        m, com, _ = model.mass_of(body.id, propellant)
        tb, rb = frames[body.id]  # a body's frame is that of its smallest instance, whose id it carries
        weighted.append((m, vadd(mv(rb, com), tb)))
    mass = math.fsum(m for m, _ in weighted)
    c: Vec = tuple(math.fsum(m * p[k] for m, p in weighted) / mass for k in range(3))  # type: ignore[assignment]

    vecs = [tuple(f.thrust * d for d in f.direction) for f in forces]
    force: Vec = tuple(math.fsum(v[k] for v in vecs) for k in range(3))  # type: ignore[assignment]
    torque: Vec = tuple(math.fsum(_cross(vsub(f.point, c), v)[k] for f, v in zip(forces, vecs)) for k in range(3))  # type: ignore[arg-type,assignment]
    size = math.sqrt(math.fsum(x * x for x in force))
    center = direction = axial = None
    arm = None
    if size > ZERO_FORCE_RATIO * math.fsum(abs(f.thrust) for f in forces):
        f2 = size * size
        center = vadd(c, tuple(x / f2 for x in _cross(force, torque)))  # type: ignore[arg-type]
        direction = tuple(x / size for x in force)  # type: ignore[assignment]
        arm = math.dist(center, c)
        along = math.fsum(torque[k] * force[k] for k in range(3)) / f2
        axial = tuple(along * x for x in force)  # type: ignore[assignment]

    return ThrustCenter(
        time=t if scheduled else None,
        basis="schedule" if scheduled else "max_thrust",
        thrusters=tuple(forces),
        mass=mass,
        center_of_mass=c,
        propellant=propellant,
        force=force,
        torque=torque,
        center=center,
        direction=direction,
        moment_arm=arm,
        axial_torque=axial,
        input_badges=tuple(b for b in Badge if any(f.badge is b for f in forces)),
        basis_note=SCHEDULE_NOTE.format(t=t) if scheduled else MAX_THRUST_NOTE,
        propellant_note=PROPELLANT_DRAWN_NOTE if scheduled else PROPELLANT_FULL_NOTE,
    )


def _command(th: CompiledThruster, t: float | None) -> tuple[float, float] | None:
    """(command, time the valve opened) of the opening that covers `t`, or None when the thruster is off then."""
    for o in th.openings:
        if o.start <= t < o.end:  # type: ignore[operator]
            return o.command, o.on
    return None


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
