"""Necessary-condition screen (J-01b; `docs/architecture/necessary-screen.md`).

    necessary_screen(project, goal) -> NecessaryScreen      # INFEASIBLE_NECESSARY_CONDITION, or None (nothing proven)

Each check is an upper bound, in continuous physics of the model the engine runs, on what any control schedule could achieve, derived from a
success condition of the goal (J-02a) and the design (X-01a body tree, X-01b motors and batteries, W-03b drag). A check
fails only when the condition needs more than the bound times `1 + NUMERIC_MARGIN` (a `default` allowance for what soft
contacts and time steps can add, not a measured one) at the favourable end of every assumption the bound reads; then the
screen says `INFEASIBLE_NECESSARY_CONDITION`. Passing proves
nothing (a passed bound is not a way to meet the goal).

| check | kind | from | needs | bound |
|---|---|---|---|---|
| `energy_height` | energy | `reach` above the start | work to lift the reference instance's centre of mass to the box | motor work + potential energy the rest can give up |
| `energy_rotation` | energy | `rotation` + `time_limit` | angle by `seconds` | `seconds * sqrt(2 E / I_min)`: the body's spin can hold at most all the energy |
| `impulse_horizontal` | impulse | `reach` + `time_limit` | horizontal travel of the centre of mass | ground friction impulse `mu * integral N` + drag impulse bound |
| `static_torque` | static torque | every motor-driven hinge of a design with a `reach` or `rotation` | the gravity moment about the hinge axis at the stored pose (X-03b `axis_load`) | the motors' stall torque |

`static_torque` is a **warning, never `INFEASIBLE`**: a motor weaker than the static gravity moment cannot lift its side
quasi-statically, but a run can still swing (pump) it up with energy gathered over several swings, so it is not a
necessary condition of multibody dynamics (V1: no false "impossible").

Motor work is bounded twice: by the batteries (energy x the motor model's highest ratio of shaft power to battery power)
and, with a time limit, by the motors' highest shaft power x the time. A design whose energy this screen cannot bound
(a thruster, a separator with a push, a motor with no battery and no time limit) gets `not_applicable` with the reason,
never a guessed bound. Only the planet's ground friction is an assumption the model reads (W-03c); the project's rows are
not bound to design values yet and are listed as not applied.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from enum import StrEnum
from typing import Literal

import numpy as np
from kinetra_core import ActuatorKind, Assumption, Badge, PartRole, Project, Quantity, Source, Unit
from kinetra_core.assumption import NormalDistribution, UniformDistribution
from kinetra_engine.compiler import Body, BodyTree, MotorDrive, build_body_tree, compile_drag, compile_drives
from kinetra_engine.compiler.bodytree import mv, rot, vadd
from kinetra_engine.parts import separator_from_part
from kinetra_engine.statics import LoadStatus, TipoverError, static_loads
from pydantic import BaseModel, ConfigDict

from .goal import Goal, ReachCondition, RotationCondition, TimeLimitCondition

INFEASIBLE = "INFEASIBLE_NECESSARY_CONDITION"
FRICTION_KEY = "ground_friction"
"""The one assumption the engine reads today (W-03c): the planet's ground friction."""

STATIC_TORQUE_LABEL = (
    "정적 토크는 경고다: 저장된 자세에서 모터 정지 토크가 축 둘레 중력 모멘트보다 작으면 준정적으로는 들 수 없지만, "
    "흔들어 에너지를 모으면 들 수 있어 불가능의 증거가 아니다"
)
NUMERIC_MARGIN = Quantity(
    value=0.05,
    unit=Unit.ONE,
    badge=Badge.DEFAULT,
    source=Source(
        ref="Kinetra default for J-01b, not measured: the relative allowance between the continuous-physics bounds and what the "
        "engine's soft contacts and time steps can add. In the test scenes the mechanical energy never rose above the motor-work "
        "bound (largest gain / bound 0.429, test_necessary_engine_energy_stays_under_the_bound)"
    ),
)
"""A check fails only when the condition needs more than `(1 + NUMERIC_MARGIN) x` its bound: the bounds are continuous physics,
and the engine's soft contacts and discrete steps can add or remove a little energy (`docs/architecture/necessary-screen.md`)."""

SCREEN_LABEL = (
    f"연속 물리 상한 + 수치 여유 {NUMERIC_MARGIN.value:.0%}(기본값, 잰 값이 아니다)의 필요조건 검사다. "
    "실패는 필요량이 상한에 여유를 더한 것보다 크다는 뜻이고, 통과는 된다는 뜻이 아니다"
)
FAVORABLE_LABEL = "가정은 분포 지지의 양 끝에서 모두 계산하고 유리한 쪽(상한이 큰 쪽)으로 판단한다"
MOTOR_LABEL = "모터 일의 상한은 연속 시간의 모터 식(X-01b 토크 곡선, 데이터시트 두 전류의 직선)에서 낸다. 한 스텝 안의 이산화 차이는 셈하지 않는다"
GROUND_LABEL = "지면은 z = 0이고 인스턴스의 무게중심은 그 아래로 내려가지 않는다고 본다(소프트 접촉의 파고듦은 셈하지 않는다)"


def unapplied_label(key: str) -> str:
    return f"미적용: 가정 {key}는 모델에 바인딩되지 않아 흔들지 않았다"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"  # static torque only: evidence on the card, never a verdict
    NOT_APPLICABLE = "not_applicable"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NecessaryCheck(_Strict):
    """One bound on one condition. `required` and `available` are in `unit`; `available` is at the favourable end of the
    assumptions in `favorable` (key -> value used) and `nominal_available` at their nominal values. `reason`: one Korean
    sentence. A `not_applicable` check has no numbers and says why."""

    name: Literal["energy_height", "energy_rotation", "impulse_horizontal", "static_torque"]
    kind: Literal["energy", "impulse", "static_torque"]
    condition: str | None  # None: a static torque warning, which is about a hinge (`joint`), not one condition
    joint: str | None = None
    status: CheckStatus
    required: float | None
    available: float | None
    nominal_available: float | None
    unit: str
    favorable: dict[str, float]
    reason: str


class NecessaryScreen(_Strict):
    """`verdict` is `INFEASIBLE_NECESSARY_CONDITION` when a check failed, else `None` (the screen proved nothing). `labels`
    are the screen's model assumptions and the assumptions it did not apply."""

    verdict: Literal["INFEASIBLE_NECESSARY_CONDITION"] | None
    checks: tuple[NecessaryCheck, ...]
    labels: tuple[str, ...]


# --- the design's numbers ---------------------------------------------------------------------------------------------


def _segments(m: MotorDrive) -> list[tuple[float, float, float, float]]:
    """The torque-speed curve as (x0, x1, alpha, beta): `T(x) = alpha + beta x` on `[x0, x1]`."""
    curve = next(c.curve for c in m.part.curves if c.name == "torque_speed")
    out = []
    for a, b in zip(curve.points, curve.points[1:]):
        beta = (b.y - a.y) / (b.x - a.x)
        out.append((a.x, b.x, a.y - beta * a.x, beta))
    return out


def _sup_on(lo: float, hi: float, f: Callable[[float], float], roots: list[float]) -> float:
    return max(f(x) for x in [lo, hi, *(r for r in roots if lo < r < hi)])


def motor_peak_power(m: MotorDrive) -> float:
    """The highest shaft power [W] the motor gives: `max x T(x)` over the curve (command 1; a command `a` gives `a^2 x T(x)`,
    and outside the curve the motor brakes, X-01b)."""
    best = 0.0
    for x0, x1, alpha, beta in _segments(m):
        roots = [-alpha / (2.0 * beta)] if beta != 0.0 else []
        best = max(best, _sup_on(x0, x1, lambda x: x * (alpha + beta * x), roots))
    return best


def motor_efficiency_bound(m: MotorDrive) -> float:
    """The highest ratio of shaft power to battery power of a metered motor in the model (X-01b): shaft `a^2 x T(x)`, battery
    `a V (I0 + (Is - I0) a T(x) / T0)` at command `a`, speed `a x`. The ratio grows with `a`, so its supremum is at `a = 1`:
    `x T(x) / (V (I0 + (Is - I0) T(x) / T0))` over the curve, solved exactly on each straight segment. `inf` when the model
    gives shaft power for no battery power (a datasheet with no current at a torque)."""
    v, i0, i_s, t0 = m.rated_voltage, m.no_load_current, m.stall_current, m.stall_torque
    best = 0.0
    for x0, x1, alpha, beta in _segments(m):
        d0, d1 = v * i0 + v * (i_s - i0) * alpha / t0, v * (i_s - i0) * beta / t0  # battery power = d0 + d1 x

        def ratio(x: float) -> float:
            shaft = x * (alpha + beta * x)
            if shaft <= 0.0:
                return 0.0
            battery = d0 + d1 * x
            return math.inf if battery <= 0.0 else shaft / battery

        # d/dx [x (alpha + beta x) / (d0 + d1 x)] = 0  <=>  beta d1 x^2 + 2 beta d0 x + alpha d0 = 0
        a2, a1, a0 = beta * d1, 2.0 * beta * d0, alpha * d0
        roots: list[float] = []
        if a2 != 0.0:
            disc = a1 * a1 - 4.0 * a2 * a0
            if disc >= 0.0:
                roots = [(-a1 + s * math.sqrt(disc)) / (2.0 * a2) for s in (1.0, -1.0)]
        elif a1 != 0.0:
            roots = [-a0 / a1]
        best = max(best, _sup_on(x0, x1, ratio, roots))
    return best


class _Design:
    """What the checks read from a compiled project, computed once."""

    def __init__(self, project: Project, bodies_directory=None):
        self.tree: BodyTree = build_body_tree(project, bodies_directory=bodies_directory)
        tree = self.tree
        self.g = float(tree.planet.gravity.value)
        self.friction: Assumption = tree.planet.ground_friction
        self.instances = {ci.instance: ci for ci in tree.instances}
        self.com = {i: vadd(ci.position, mv(rot(ci.orientation), _vec(ci.properties.center_of_mass))) for i, ci in self.instances.items()}
        self.mass = {i: float(ci.properties.mass.value) for i, ci in self.instances.items()}
        self.total_mass = math.fsum(self.mass.values())
        self.potential = math.fsum(self.mass[i] * self.g * self.com[i][2] for i in self.instances)
        parts = {p.id: p for p in tree.design.parts}
        design = tree.design
        self.separators = [i.id for i in design.instances if parts[i.part].role is PartRole.SEPARATOR]
        self.pushing_separators = [
            i.id for i in design.instances
            if parts[i.part].role is PartRole.SEPARATOR
            and separator_from_part(parts[i.part], {p.name: p for p in i.parameters}).impulse.value > 0.0
        ]
        self.thrusters = [a.id for a in design.actuators if a.kind is ActuatorKind.THRUSTER]
        self.breakable = [j.id for j in design.joints if j.break_threshold is not None]
        self.terrain = bool(project.world.terrain_props)
        self.density = float(tree.planet.atmosphere_density.value)
        drives = compile_drives(tree)
        self.motors = drives.motors
        self.unmetered = [m.actuator for m in drives.motors if m.supply is None]
        self.peak_power = math.fsum(motor_peak_power(m) for m in drives.motors)
        stock = dict(drives.supplies)
        self.battery_work = math.fsum(
            max(motor_efficiency_bound(m) for m in drives.motors if m.supply == b) * stock[b].remaining
            for b in sorted({m.supply for m in drives.motors if m.supply is not None})
        )
        self.drag_area = {b.body: b.area for b in compile_drag(tree).bodies}

    def motor_work(self, seconds: float | None) -> float:
        """Upper bound [J] of the work all motors can do by `seconds` (`None`: ever). `inf` when unbounded."""
        by_battery = math.inf if self.unmetered else self.battery_work
        return by_battery if seconds is None else min(by_battery, self.peak_power * seconds)

    def unbounded_energy(self, seconds: float | None) -> str | None:
        """Why this screen cannot bound the design's energy, or None."""
        if self.thrusters:
            return f"추력기({', '.join(self.thrusters)})의 일은 이 스크린이 묶지 못한다"
        if self.pushing_separators:
            return f"분리 충격량이 있는 분리기({', '.join(self.pushing_separators)})의 일은 이 스크린이 묶지 못한다"
        if seconds is None and self.unmetered:
            return f"배터리 없는 모터({', '.join(self.unmetered)})는 시간 한도가 없으면 일이 묶이지 않는다"
        return None

    def splittable(self, body: Body) -> bool:
        """Whether the piece the body moves with can change in a run: a separator in it (X-08) or any joint with a break
        threshold (X-04b, X-13). Then the screen takes each candidate instance alone (the lightest piece that holds it)."""
        return bool(self.breakable) or any(i in self.separators for i in body.instances)

    def body_world(self, body: Body) -> tuple[tuple[float, float, float], tuple]:
        ci = self.instances[body.id]  # a body's frame is its smallest instance's (X-01a)
        return ci.position, rot(ci.orientation)

    def world_point(self, body: Body, p) -> tuple[float, float, float]:
        t, r = self.body_world(body)
        return vadd(t, mv(r, p))


def _vec(v) -> tuple[float, float, float]:
    return (v.x, v.y, v.z)


def _dist(a, b) -> float:
    return math.dist(a, b)


def _min_inertia(inertia: tuple[float, float, float, float, float, float]) -> float:
    ixx, iyy, izz, ixy, ixz, iyz = inertia
    return float(np.linalg.eigvalsh(np.array([[ixx, ixy, ixz], [ixy, iyy, iyz], [ixz, iyz, izz]]))[0])


def _support(a: Assumption) -> tuple[float, ...]:
    """The ends of an assumption's distribution (`inf` for an open end): the values the favourable end is chosen from."""
    d = a.distribution
    if isinstance(d, UniformDistribution):
        return (d.low, d.high)
    if isinstance(d, NormalDistribution):
        return (-math.inf if d.clip_low is None else d.clip_low, math.inf if d.clip_high is None else d.clip_high)
    return (a.value.value,)


def _instance_of(design: _Design, condition) -> str:
    if condition.instance not in design.instances:
        raise ValueError(f"condition {condition.id!r} names instance {condition.instance!r}, which is not in the design")
    return condition.instance


def _check(name, kind, c, status, reason, required=None, available=None, nominal=None, unit="", favorable=None) -> NecessaryCheck:
    return NecessaryCheck(
        name=name,
        kind=kind,
        condition=None if c is None else c.id,
        status=status,
        required=required,
        available=available,
        nominal_available=nominal,
        unit=unit,
        favorable=favorable or {},
        reason=reason,
    )


def _verdict(name, kind, c, required, available, unit, pass_reason, fail_reason, nominal=None, favorable=None) -> NecessaryCheck:
    """A bound decided: failed only when the condition needs more than the favourable bound times `1 + NUMERIC_MARGIN`."""
    status = CheckStatus.FAILED if required > available * (1.0 + NUMERIC_MARGIN.value) else CheckStatus.PASSED
    return _check(name, kind, c, status, fail_reason if status is CheckStatus.FAILED else pass_reason, required, available, nominal, unit, favorable)


# --- checks -----------------------------------------------------------------------------------------------------------


def _energy_height(c: ReachCondition, d: _Design, seconds: float | None) -> NecessaryCheck:
    """The body of the instance is followed and its reference point is its smallest instance's origin (J-02a). That
    instance `P` is one of the body's instances with an id at most the condition's (a separator can split the body, X-08);
    without a separator in the body it is the body's own. `P`'s origin at `region.min.z` puts the centre of mass of the
    piece it moves with at least `region.min.z - r` high (`r` its distance from that origin), which takes `m g (rise)` of
    work; the motors give at most `motor_work`, and every other instance at most its potential energy above z = 0."""
    name, kind = "energy_height", "energy"
    x = _instance_of(d, c)
    why = d.unbounded_energy(seconds)
    if why:
        return _check(name, kind, c, CheckStatus.NOT_APPLICABLE, why)
    body = d.tree.body_of(x)
    height = c.region.min.z
    work = d.motor_work(seconds)
    options = []  # (need, available, reference) per piece the reference can move with
    if d.splittable(body):
        pieces = [(p, (p,)) for p in body.instances if p <= x]
    else:
        pieces = [(body.id, body.instances)]
    for ref, members in pieces:
        m = math.fsum(d.mass[i] for i in members)
        com = tuple(math.fsum(d.mass[i] * d.com[i][k] for i in members) / m for k in range(3))
        origin = d.instances[ref].position
        need = m * d.g * (height - _dist(origin, com) - com[2])
        others = math.fsum(d.mass[i] * d.g * d.com[i][2] for i in d.instances if i not in members)
        options.append((need, work + others, ref))
    need, available, ref = min(options, key=lambda o: o[0] - o[1])
    return _verdict(
        name, kind, c, need, available, "J",
        f"기준 인스턴스 {ref}를 목표 높이로 올리는 일이 모터 일과 나머지 부품의 위치에너지 상한 안이다",
        f"기준 인스턴스 {ref}를 목표 높이로 올리는 데 드는 일이 모터 일과 나머지 부품의 위치에너지를 모두 써도 모자란다",
    )


def _energy_rotation(c: RotationCondition, d: _Design, seconds: float) -> NecessaryCheck:
    """By `seconds` the energy of the design is at most `E = motor_work(seconds) + potential energy above z = 0`, so the body
    spins at most `sqrt(2 E / I_min)` (its rotational kinetic energy is part of `E`) and turns at most `seconds` times that.
    `I_min` is the body's smallest principal moment; a body a separator can split gives the instance's own (a piece that
    holds the instance has at least the instance's inertia)."""
    name, kind = "energy_rotation", "energy"
    x = _instance_of(d, c)
    why = d.unbounded_energy(seconds)
    if why:
        return _check(name, kind, c, CheckStatus.NOT_APPLICABLE, why)
    body = d.tree.body_of(x)
    if d.splittable(body):
        i = d.instances[x].properties.inertia
        inertia = (i.ixx, i.iyy, i.izz, i.ixy, i.ixz, i.iyz)
    else:
        inertia = body.inertia
    energy = d.motor_work(seconds) + d.potential
    available = math.degrees(seconds * math.sqrt(2.0 * energy / _min_inertia(inertia)))
    return _verdict(
        name, kind, c, c.angle_deg, available, "deg",
        "시간 한도 안에 낼 수 있는 회전 각의 에너지 상한 안이다",
        "모든 에너지가 그 몸의 회전에 들어가도 시간 한도 안에 목표 각도만큼 돌 수 없다",
    )


def _region_distance_xy(c: ReachCondition, p) -> float:
    dx = max(c.region.min.x - p[0], 0.0, p[0] - c.region.max.x)
    dy = max(c.region.min.y - p[1], 0.0, p[1] - c.region.max.y)
    return math.hypot(dx, dy)


def _reach_radius(d: _Design, ref_body: Body, origin) -> float | str:
    """An upper bound [m] of the distance from the reference origin to the design's centre of mass in any pose the joints
    allow: `sum_b (m_b / M) rho_b`, `rho_b` the length of the chain origin -> joint anchors -> body b's centre of mass (each
    segment is fixed in one body; a slider adds its travel). A reason (str) when there is none: a slider without limits, or a
    body no joint chain reaches (a tree with several free bodies)."""
    by_id = {b.id: b for b in d.tree.bodies}
    links: dict[str, list[tuple[str, tuple[float, float, float], float]]] = {b.id: [] for b in d.tree.bodies}
    for b in d.tree.bodies:
        if b.parent is None:
            continue
        j = b.joint
        travel = 0.0
        if j.kind.value == "slider":
            if j.range is None:
                return "한계가 없는 슬라이더가 있어 기준점과 무게중심의 거리가 묶이지 않는다"
            travel = max(abs(j.range[0]), abs(j.range[1]))
        anchor = d.world_point(b, j.pos)
        links[b.id].append((b.parent, anchor, travel))
        links[b.parent].append((b.id, anchor, travel))
    rho: dict[str, float] = {}
    stack = [(ref_body.id, origin, 0.0)]
    seen = {ref_body.id}
    while stack:
        bid, point, length = stack.pop()
        rho[bid] = length + _dist(point, d.world_point(by_id[bid], by_id[bid].com))
        for other, anchor, travel in links[bid]:
            if other not in seen:
                seen.add(other)
                stack.append((other, anchor, length + _dist(point, anchor) + travel))
    loose = [b.id for b in d.tree.bodies if b.id not in rho]
    if loose:
        return f"결합 사슬로 이어지지 않은 몸({', '.join(loose)})이 있어 기준점과 무게중심의 거리가 묶이지 않는다"
    return math.fsum(b.mass * rho[b.id] for b in d.tree.bodies) / d.total_mass


def _impulse_horizontal(c: ReachCondition, d: _Design, seconds: float) -> NecessaryCheck:
    """With no thruster the only horizontal forces on the whole design are ground friction and drag. Friction is at most
    `mu` times the normal force (elliptic cone, the pair's `mu` is at most the ground's, X-01e), and the normal impulse by
    `t` is `M g t + M v_z(t) - (drag impulse up)`. So the centre of mass moves at most
    `mu (g T^2 / 2 + dz) + (1 + mu) K T^2 / (2 M)` horizontally by `T`: `dz <= motor_work(T) / (M g)` is how high the centre
    of mass can climb, and `K = sum_b rho C_dA_b E / m_b` bounds the drag force from `|v_b|^2 <= 2 E / m_b`. The reference
    origin is within `_reach_radius` of the centre of mass."""
    name, kind = "impulse_horizontal", "impulse"
    x = _instance_of(d, c)
    why = d.unbounded_energy(seconds)
    if why is None and d.terrain:
        why = "지형 소품의 접촉력에는 수평 성분이 있어 이 스크린이 묶지 못한다"
    if why is None and (d.separators or d.breakable):
        why = "분리되거나 끊어지는 결합이 있으면 조각이 날아가 기준점과 무게중심의 거리가 묶이지 않는다"
    if why:
        return _check(name, kind, c, CheckStatus.NOT_APPLICABLE, why)
    body = d.tree.body_of(x)
    origin = d.instances[body.id].position
    radius = _reach_radius(d, body, origin)
    if isinstance(radius, str):
        return _check(name, kind, c, CheckStatus.NOT_APPLICABLE, radius)
    m_total = d.total_mass
    com = tuple(math.fsum(d.mass[i] * d.com[i][k] for i in d.instances) / m_total for k in range(3))
    need = _region_distance_xy(c, com) - radius
    work = d.motor_work(seconds)
    energy = work + d.potential
    k = math.fsum(d.density * d.drag_area[b.id] * energy / b.mass for b in d.tree.bodies)
    climb = work / (m_total * d.g)

    def available(mu: float) -> float:
        if math.isinf(mu):
            return math.inf
        return mu * (d.g * seconds**2 / 2.0 + climb) + (1.0 + mu) * k * seconds**2 / (2.0 * m_total)

    ends = [mu for mu in _support(d.friction) if mu >= 0.0]
    mu_fav = max(ends, key=available)
    return _verdict(
        name, kind, c, need, available(mu_fav), "m",
        "시간 한도 안의 수평 이동이 지면 마찰 충격량의 상한 안이다",
        "지면 마찰을 분포의 유리한 끝으로 두어도 시간 한도 안에 그만큼 수평으로 갈 충격량이 없다",
        nominal=available(d.friction.value.value),
        favorable={FRICTION_KEY: mu_fav},
    )


def _static_torque(d: _Design) -> list[NecessaryCheck]:
    """Per motor-driven hinge: the stall torque of its motors (sum) against the static gravity moment about its axis at the
    stored pose (X-03b `axis_load` of the side that hangs). Over it is a `warning`, never a failed check."""
    try:
        loads = static_loads(d.tree)
    except TipoverError as e:
        return [
            NecessaryCheck(name="static_torque", kind="static_torque", condition=None, joint=j, status=CheckStatus.NOT_APPLICABLE,
                           required=None, available=None, nominal_available=None, unit="N*m", favorable={},
                           reason=f"정역학 검사를 할 수 없다: {e}")
            for j in sorted({m.joint for m in d.motors})
        ]
    out = []
    for j in sorted({m.joint for m in d.motors}):
        stall = math.fsum(m.stall_torque for m in d.motors if m.joint == j)
        jl = loads.joint(j)
        common = dict(name="static_torque", kind="static_torque", condition=None, joint=j, unit="N*m", favorable={}, nominal_available=None)
        if jl.status is not LoadStatus.HANGING:
            out.append(NecessaryCheck(**common, status=CheckStatus.NOT_APPLICABLE, required=None, available=None,
                                      reason=f"이 결합의 정지 하중이 정해지지 않는다({jl.status.value}): {jl.reason}"))
            continue
        moment = abs(jl.axis_load)
        status = CheckStatus.WARNING if moment > stall else CheckStatus.PASSED
        reason = (
            "모터 정지 토크가 저장된 자세의 축 둘레 중력 모멘트보다 작다: 준정적으로는 들 수 없다(흔들어 올리는 길은 남아 불가능은 아니다)"
            if status is CheckStatus.WARNING
            else "모터 정지 토크가 저장된 자세의 축 둘레 중력 모멘트 이상이다"
        )
        out.append(NecessaryCheck(**common, status=status, required=moment, available=stall, reason=reason))
    return out


def necessary_screen(project: Project, goal: Goal, *, bodies_directory=None) -> NecessaryScreen:
    """Every check the goal's conditions give for `project`. Raises `CompileError` when the project does not compile and
    `ValueError` when a condition names an instance that is not in the design."""
    d = _Design(project, bodies_directory)
    limit = next((c.seconds for c in goal.conditions if isinstance(c, TimeLimitCondition)), None)
    checks: list[NecessaryCheck] = []
    for c in goal.conditions:
        if isinstance(c, ReachCondition):
            checks.append(_energy_height(c, d, limit))
            if limit is not None:
                checks.append(_impulse_horizontal(c, d, limit))
        elif isinstance(c, RotationCondition) and limit is not None:
            checks.append(_energy_rotation(c, d, limit))
    if d.motors and any(isinstance(c, (ReachCondition, RotationCondition)) for c in goal.conditions):
        checks += _static_torque(d)
    labels = [SCREEN_LABEL, FAVORABLE_LABEL, GROUND_LABEL]
    if d.motors:
        labels += [MOTOR_LABEL, STATIC_TORQUE_LABEL]
    labels += [unapplied_label(a.key) for a in project.assumptions.assumptions]
    failed = any(ch.status is CheckStatus.FAILED for ch in checks)
    return NecessaryScreen(verdict=INFEASIBLE if failed else None, checks=tuple(checks), labels=tuple(labels))
