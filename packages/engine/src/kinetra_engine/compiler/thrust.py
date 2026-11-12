"""Thrusters and propellant mass in the engine model (X-01c).

    model = compile_thrust(project, cache=None, tolerance=None)   # ThrustModel; calls require_complete(project, "compile")
    mj_model = mujoco.MjModel.from_xml_string(to_mjcf(model.tree))
    mj_data = mujoco.MjData(mj_model)
    run = ThrustRun(model, mj_model, mj_data)                     # puts the tanks' propellant on their bodies
    step = run.step()                                             # thrust, propellant draw, mass update and one mj_step

**Thrust follows the control schedule.** A thruster actuator (`Actuator.kind = thruster`) fires during its schedule entries:
command `c` in [0, 1] over `[start, end)` gives `c x thrust(t - on)` newtons (`Thruster.thrust`, B-03c), where `on` is the time
the valve opened. Entries of one actuator that touch (`end` of one = `start` of the next) with a command above 0 on both sides
are one opening: the valve stays open and the curve does not start its ramp again. After a gap or a command-0 entry the next
entry opens the valve again and the ramp starts again. Outside every entry the thrust is 0.

**One step.** Over `[t, t + dt]` (`dt` = `mj_model.opt.timestep`) the impulse of each thruster is the exact integral of the
piecewise-linear thrust curve over the part of the step its entries cover (`burn`, trapezoids, not sampled), and the propellant
it asks for is `impulse x propellant_flow / rated_thrust`. The thrusters that draw on one tank ask together; when the tank has
less, every one of them gets the same fraction `Draw.satisfied` of its impulse in that step (B-03d: the caller scales the
output by `satisfied`). A thruster with no `supply` is not metered. The force put on the body is that impulse over `dt`,
constant through the step, along the nozzle's force direction turned by the body's orientation at the start of the step, at
the nozzle point: `mj_data.xfrc_applied` of the body gets the force and its moment about the body's centre of mass. So the
momentum a step gives is the impulse of the curve over that step, whatever `dt` is.

**Propellant mass (the decision the issue asks for).** legacy-v0 kept the vehicle's mass constant and only counted the
propellant (`legacy-v0:packages/engine/src/kinetra_engine/templates/rocket_car.py` docstring, "constant mass (fuel only
accounted)", and `fuel = impulse / (isp * G0)` there). That is not ported: a burn that empties a tank heavier than the dry
vehicle would be wrong by the whole mass ratio. Here the tank's propellant is mass on the tank's body, changed in place on
the compiled model between steps (no recompile). Every such change is followed by `mj_setConst`, MuJoCo's documented safe
update for `body_mass`, `body_ipos`, `body_inertia` and `body_iquat`: it propagates them to the body collision BVH (whose
local frame is the inertial frame), subtree masses and constraint weights. `mj_setConst` uses its `mjData` argument as
qpos0 scratch and clears contacts/constraints, so a dedicated scratch object preserves the live time, integrated state,
forces, warm start, contacts and sleeping state. The caller's `mj_kinematics`/`mj_step` refreshes pose-derived data:

- what the tank holds is spread evenly over its inside (the shape's `subtract` components), at density
  `remaining / inside volume`. So the propellant's centre of mass is the inside's centroid, it does not move as the tank
  empties, and its inertia about that point is `remaining x` the inside's inertia per kilogram. No sloshing, no settling;
- the body's mass, centre of mass and inertia are the dry body's (X-01a, `MassProperties` sums) plus the propellant of every
  tank in it (every `tank` instance, drawn on or not), by the parallel-axis theorem; MuJoCo's own `mju_eig3` turns the full
  inertia into `body_inertia` and `body_iquat`, as its compiler does for `fullinertia`;
- during a step the body carries the mean of the propellant before and after the step's draw, and after `mj_step` the
  amount left. For a steady flow the velocity a step gives then matches the rocket equation to second order in the mass the
  step burns (`J / (m - dm/2)` against `(J / dm) ln(m / (m - dm))`);
- velocities are not touched when the mass changes: the thrust already carries the momentum the exhaust takes away, so a
  body's velocity is continuous (the variable-mass equation `m dv/dt = F`).

What this does not do (the same list is in `docs/architecture/thrust.md`): the propellant does not move inside the tank
(no slosh, no settling under acceleration, no centre-of-mass travel as it empties); the thrust does not fall with the tank's
pressure (B-03c); the free joint's velocity is that of the body frame's origin, so a rotating body whose centre of mass moves in its frame does not get the small velocity correction
that would keep the centre of mass's velocity continuous. `to_mjcf(model.tree)` alone writes the dry masses: the propellant is
put on by `ThrustRun` before the first step.

Safety line (`docs/process/review-rubric.md` 1): a thruster is one acting force with a mass flow in proportion to it. No
propellant chemistry, combustion or nozzle flow is read or written here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco
import numpy as np

from kinetra_core import ActuatorKind, BlockedOperation, PartRole, Project, Quantity, require_complete
from kinetra_core import THRUSTER_NOZZLE

from ..parts import PartCache, Supply, Thruster, burn, tank_supply, thruster_from_part
from ..parts._shape import resolve_shape
from ..parts.mass import _principal_inertia
from .bodytree import BodyTree, CompiledInstance, Mat, Vec, _congruent, _parameter_values, build_body_tree, mtv, mv, qconj, qmul, qnorm, rot, vsub

Inertia6 = tuple[float, float, float, float, float, float]  # ixx iyy izz ixy ixz iyz


@dataclass(frozen=True)
class Opening:
    """One schedule entry of a thruster: command `command` over `[start, end)` seconds; `on` is when the valve opened, the
    time 0 of the thrust curve (the entry's own `start`, or an earlier one when entries touch with the command on)."""

    entry: str
    start: float
    end: float
    command: float
    on: float


@dataclass(frozen=True)
class CompiledThruster:
    """A thruster actuator in the model: its part read as a `Thruster`, the nozzle point and the force direction in the
    frame of the body the instance is in, the tank instance it draws on (`None`: not metered) and its schedule."""

    actuator: str
    instance: str
    body: str
    thruster: Thruster
    position: Vec
    direction: Vec
    supply: str | None
    openings: tuple[Opening, ...]

    def impulse(self, t0: float, t1: float) -> float:
        """Impulse [N s] the schedule asks for over `[t0, t1]` with unlimited propellant: the exact integral of the curve."""
        total = 0.0
        for o in self.openings:
            a, b = max(t0, o.start), min(t1, o.end)
            if b > a:
                total += o.command * (_curve_impulse(self.thruster, b - o.on) - _curve_impulse(self.thruster, a - o.on))
        return total


@dataclass(frozen=True)
class PropellantStore:
    """A tank instance and what it holds at the start (`supply`). `centroid` [m] is the centre of the tank's inside in the frame
    of the body the tank is in and `inertia_per_kg` [m^2] the inside's inertia about that point per kilogram of propellant,
    body axes (`ixx iyy izz ixy ixz iyz`)."""

    instance: str
    body: str
    supply: Supply
    centroid: Vec
    inertia_per_kg: Inertia6


@dataclass(frozen=True)
class ThrustModel:
    """The body tree (X-01a) with the thrusters (actuator id order) and the propellant of every tank instance (id order)."""

    tree: BodyTree
    thrusters: tuple[CompiledThruster, ...]
    stores: tuple[PropellantStore, ...]

    def mass_of(self, body: str, propellant: dict[str, float]) -> tuple[float, Vec, Inertia6]:
        """Mass [kg], centre of mass [m] and inertia about it [kg m^2] of `body` (its frame) with `propellant` kg in each
        tank instance named (tanks not named count as empty)."""
        b = self.tree.body(body)
        parts: list[tuple[float, Vec, Inertia6]] = [(b.mass, b.com, b.inertia)]
        for s in self.stores:
            p = propellant.get(s.instance, 0.0)
            if s.body == body and p > 0.0:
                parts.append((p, s.centroid, tuple(p * i for i in s.inertia_per_kg)))  # type: ignore[arg-type]
        mass = math.fsum(m for m, _, _ in parts)
        com = tuple(math.fsum(m * c[k] for m, c, _ in parts) / mass for k in range(3))
        entries: list[list[float]] = [[], [], [], [], [], []]
        for m, c, i in parts:
            d = vsub(c, com)  # type: ignore[arg-type]
            entries[0].append(i[0] + m * (d[1] * d[1] + d[2] * d[2]))
            entries[1].append(i[1] + m * (d[0] * d[0] + d[2] * d[2]))
            entries[2].append(i[2] + m * (d[0] * d[0] + d[1] * d[1]))
            entries[3].append(i[3] - m * d[0] * d[1])
            entries[4].append(i[4] - m * d[0] * d[2])
            entries[5].append(i[5] - m * d[1] * d[2])
        return mass, com, tuple(math.fsum(e) for e in entries)  # type: ignore[return-value]


def _curve_impulse(th: Thruster, x: float) -> float:
    """Integral of the thrust curve at command 1 from 0 to `x` seconds (0 for `x <= 0`)."""
    return 0.0 if x <= 0.0 else burn(th, x).impulse


def _openings(design, actuator: str) -> tuple[Opening, ...]:
    entries = sorted((e for e in design.schedule.actuations if e.actuator == actuator), key=lambda e: (e.start, e.id))
    out: list[Opening] = []
    for e in entries:
        if e.command == 0.0:
            continue  # off: no thrust, and the next entry opens the valve again
        prev = out[-1] if out else None
        on = prev.on if prev is not None and prev.end == e.start else e.start
        out.append(Opening(e.id, e.start, e.end, e.command, on))
    return tuple(out)


def _body_frame(tree: BodyTree, ci: CompiledInstance) -> tuple[Mat, Vec]:
    """Rotation and offset that take a point of the instance's frame into the frame of its body."""
    body_inst = next(c for c in tree.instances if c.instance == ci.body)  # a body's frame is its smallest instance's
    qrel = qnorm(qmul(qconj(body_inst.orientation), ci.orientation))
    return rot(qrel), mtv(rot(body_inst.orientation), vsub(ci.position, body_inst.position))


def _store(tree: BodyTree, ci: CompiledInstance, part, inst) -> PropellantStore:
    params = {p.name: p for p in inst.parameters}
    supply = tank_supply(part, params)
    inside = [pl for pl in resolve_shape(part, params).placed if pl.component.operation == "subtract"]
    volume = math.fsum(pl.volume for pl in inside)
    weights = [pl.volume / volume for pl in inside]
    c = tuple(math.fsum(w * pl.center[k] for w, pl in zip(weights, inside)) for k in range(3))
    acc = [[0.0] * 3 for _ in range(3)]
    for w, pl in zip(weights, inside):
        diag = _principal_inertia(pl.component.primitive, w, pl.dims)
        r = pl.rotation
        d = (pl.center[0] - c[0], pl.center[1] - c[1], pl.center[2] - c[2])
        dd = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        for i in range(3):
            for j in range(3):
                own = sum(r[i][k] * diag[k] * r[j][k] for k in range(3))
                acc[i][j] += own + w * ((dd if i == j else 0.0) - d[i] * d[j])
    r_body, p_body = _body_frame(tree, ci)
    i_body = _congruent(r_body, ((acc[0][0], acc[0][1], acc[0][2]), (acc[1][0], acc[1][1], acc[1][2]), (acc[2][0], acc[2][1], acc[2][2])))
    centroid = tuple(a + b for a, b in zip(mv(r_body, c), p_body))  # type: ignore[arg-type]
    return PropellantStore(
        ci.instance, ci.body, supply, centroid,  # type: ignore[arg-type]
        (i_body[0][0], i_body[1][1], i_body[2][2], i_body[0][1], i_body[0][2], i_body[1][2]),
    )


def compile_thrust(project: Project, cache: PartCache | None = None, tolerance: float | Quantity | None = None) -> ThrustModel:
    """The body tree of `project` with its thrusters, their schedule and the propellant of its tanks.

    Refuses a project with a missing definition (`require_complete`, `ProjectIncomplete`) and raises the `CompileError`s of
    `build_body_tree` (X-01d), among them `no_curve` for a thruster actuator on a part with no role. A part with another role
    never gets here: `DesignSpec` refuses a thruster actuator on it (B-03b), so every thruster read here has its curve."""
    require_complete(project, BlockedOperation.COMPILE)
    tree = build_body_tree(project, cache, tolerance)
    design = tree.design
    parts = {p.id: p for p in design.parts}
    by_id = {i.id: i for i in design.instances}
    compiled = {c.instance: c for c in tree.instances}

    thrusters: list[CompiledThruster] = []
    for act in design.actuators:  # canonical (id) order
        if act.kind is not ActuatorKind.THRUSTER:
            continue
        inst = by_id[act.instance]
        part = parts[inst.part]
        th = thruster_from_part(part)
        nozzle = next(s for s in part.snap_points if s.id == THRUSTER_NOZZLE)
        ci = compiled[inst.id]
        r_body, p_body = _body_frame(tree, ci)
        position = tuple(a + b for a, b in zip(mv(r_body, nozzle.position.evaluate(_parameter_values(part, inst))), p_body))
        thrusters.append(
            CompiledThruster(act.id, inst.id, ci.body, th, position, mv(r_body, th.direction), act.supply, _openings(design, act.id))  # type: ignore[arg-type]
        )

    stores = tuple(
        _store(tree, compiled[i.id], parts[i.part], i) for i in design.instances if parts[i.part].role is PartRole.TANK
    )
    return ThrustModel(tree, tuple(thrusters), stores)


@dataclass(frozen=True)
class ThrusterStep:
    """What one thruster did in one step: impulse [N s] given to the body, mean thrust [N] (= impulse / dt), propellant [kg]
    drawn from its tank (0 when not metered) and `satisfied`, the fraction of the asked impulse the tank could feed."""

    actuator: str
    impulse: float
    thrust: float
    propellant: float
    satisfied: float


@dataclass(frozen=True)
class ThrustStep:
    """One step `[time, time + dt]`: every thruster (actuator id order) and the propellant left in each tank after it [kg]."""

    time: float
    dt: float
    thrusters: tuple[ThrusterStep, ...]
    remaining: dict[str, float]


class ThrustRun:
    """Steps a compiled MuJoCo model of `model.tree` with the thrust of the schedule and the propellant mass of the tanks.

    The constructor puts the propellant every tank holds at the start on its body (`mj_model` is changed in place: give each
    run its own model). `step()` does one `mj_step`. A caller that owns the step loop (the run of X-02a, which also writes
    the motors' `ctrl` and other forces) calls `begin_step()`, then `mj_step` itself, then `end_step()`: `begin_step` draws
    the propellant, puts this step's mass on the bodies and adds the thrust into `xfrc_applied` (on top of whatever the
    caller put there), `end_step` takes the thrust out again (the rows go back to what they were before `begin_step`) and
    puts the mass left on the bodies. `supplies` is what each tank instance holds now."""

    def __init__(self, model: ThrustModel, mj_model: mujoco.MjModel, mj_data: mujoco.MjData):
        self.model = model
        self.supplies: dict[str, Supply] = {s.instance: s.supply for s in model.stores}
        self._k = {t.actuator: t.thruster.propellant_flow / t.thruster.rated_thrust for t in model.thrusters}
        self._loaded = sorted({s.body for s in model.stores})
        self._pending: tuple[dict[int, np.ndarray], dict[str, float], list[str]] | None = None
        self.rebind(mj_model, mj_data)

    def rebind(self, mj_model: mujoco.MjModel, mj_data: mujoco.MjData) -> None:
        """Step `mj_model` and `mj_data` from now on (a model compiled again from the same bodies after a joint broke, X-04b):
        the bodies are found by name and carry what the tanks hold now. Not between `begin_step` and `end_step`."""
        if self._pending is not None:
            raise RuntimeError("rebind between begin_step and end_step")
        rows: dict[str, int] = {}
        for b in self.model.tree.bodies:
            row = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_BODY, b.id)
            if row < 0:
                raise ValueError(f"the MuJoCo model has no body {b.id!r}: it was not compiled from this body tree")
            rows[b.id] = row
        self._m, self._d, self._row = mj_model, mj_data, rows
        self._const_data = mujoco.MjData(mj_model)  # never clear or rewind the live mjData in mj_setConst
        self._load({i: s.remaining for i, s in self.supplies.items()}, self._loaded)

    def body_mass(self, body: str) -> tuple[float, Vec, Inertia6]:
        """Mass, centre of mass and inertia of `body` with what the tanks hold now."""
        return self.model.mass_of(body, {i: s.remaining for i, s in self.supplies.items()})

    def _load(self, propellant: dict[str, float], bodies: list[str]) -> None:
        if not bodies:
            return
        m = self._m
        for body in bodies:
            mass, com, (ixx, iyy, izz, ixy, ixz, iyz) = self.model.mass_of(body, propellant)
            row = self._row[body]
            eigval, eigvec, quat = np.zeros(3), np.zeros(9), np.zeros(4)
            mujoco.mju_eig3(eigval, eigvec, quat, np.array([ixx, ixy, ixz, ixy, iyy, iyz, ixz, iyz, izz]))
            m.body_mass[row] = mass
            m.body_ipos[row] = com
            m.body_inertia[row] = eigval
            m.body_iquat[row] = quat
        # MuJoCo's body BVH is expressed in the inertial frame: changing ipos/iquat without this propagation leaves
        # the collision bounds in the old frame (#580). mj_setConst is the documented safe update for mass and inertia;
        # it also refreshes subtree masses and constraint weights. Its qpos0 computations overwrite data.qpos, clear
        # contacts/constraints and wake sleeping trees, so use dedicated scratch data. The live time, integrated state,
        # applied forces, warm start, contacts and constraints stay untouched; mj_kinematics/mj_step refresh derived data.
        mujoco.mj_setConst(m, self._const_data)

    def step(self) -> ThrustStep:
        record = self.begin_step()
        mujoco.mj_step(self._m, self._d)
        self.end_step()
        return record

    def begin_step(self, time_s: float | None = None) -> ThrustStep:
        """Everything of one step before `mj_step` (see the class docstring). Returns the step's record; call `end_step`
        after the `mj_step`, once per `begin_step`. `time_s` is the caller's absolute step-start clock; standalone callers
        default to MuJoCo's accumulated `data.time`."""
        if self._pending is not None:
            raise RuntimeError("begin_step called twice without end_step")
        m, d = self._m, self._d
        t, dt = (float(d.time) if time_s is None else time_s), float(m.opt.timestep)
        asked = {th.actuator: th.impulse(t, t + dt) for th in self.model.thrusters}

        satisfied: dict[str, float] = {}
        before = {i: s.remaining for i, s in self.supplies.items()}
        for tank in sorted({th.supply for th in self.model.thrusters if th.supply is not None}):
            request = math.fsum(asked[th.actuator] * self._k[th.actuator] for th in self.model.thrusters if th.supply == tank)
            draw = self.supplies[tank].draw(request)
            self.supplies[tank] = draw.supply
            satisfied[tank] = draw.satisfied
        after = {i: s.remaining for i, s in self.supplies.items()}
        changed = sorted({s.body for s in self.model.stores if before[s.instance] != after[s.instance]})
        if changed:
            self._load({i: 0.5 * (before[i] + after[i]) for i in before}, changed)

        records: list[ThrusterStep] = []
        forces: dict[int, np.ndarray] = {}
        mujoco.mj_kinematics(m, d)  # orientation and centre of mass at the start of the step, with this step's mass
        for th in self.model.thrusters:
            s = 1.0 if th.supply is None else satisfied[th.supply]
            impulse = asked[th.actuator] * s
            drawn = 0.0 if th.supply is None else impulse * self._k[th.actuator]
            records.append(ThrusterStep(th.actuator, impulse, impulse / dt, drawn, s))
            if impulse == 0.0:
                continue
            row = self._row[th.body]
            r = d.xmat[row].reshape(3, 3)
            f = (impulse / dt) * (r @ np.array(th.direction))
            point = d.xpos[row] + r @ np.array(th.position)
            wrench = forces.setdefault(row, np.zeros(6))
            wrench[:3] += f
            wrench[3:] += np.cross(point - d.xipos[row], f)

        saved = {row: d.xfrc_applied[row].copy() for row in forces}
        for row, w in forces.items():
            d.xfrc_applied[row] += w
        self._pending = (saved, after, changed)
        return ThrustStep(t, dt, tuple(records), after)

    def end_step(self) -> None:
        """Everything of one step after `mj_step`: the `xfrc_applied` rows the thrust used are restored, and the bodies
        whose tanks were drawn on carry what is left."""
        if self._pending is None:
            raise RuntimeError("end_step without begin_step")
        saved, after, changed = self._pending
        self._pending = None
        for row, w in saved.items():
            self._d.xfrc_applied[row] = w
        if changed:
            self._load(after, changed)
