"""Joints and actuators of a body tree (X-01b): spring-dampers on sliders, motors on hinges, and what a motor draws.

    drives = compile_drives(tree)                       # Drives, or CompileError
    xml = to_mjcf(tree, drives=drives)                  # joints with stiffness/damping, one <motor> per motor actuator
    runtime = DriveRuntime(model, drives)               # per run: owns the supplies
    runtime.apply(data, {"m1": 1.0}, dt)                # before each mj_step: sets data.ctrl, draws energy

**Spring-dampers (B-03e).** A part with role `spring_damper` acts along the joint at one of its snap points: the one `slider`
joint whose `a` or `b` end is on that instance. Its `stiffness` [N/m] and `damping` [N*s/m] (the instance's values, or the
part's defaults) become the MuJoCo joint's `stiffness` and `damping`; the spring's force is 0 at joint coordinate 0, the saved
pose (MJCF `springref` 0, the model's reference pose). A spring-damper instance at no slider, at more than one, or at a hinge
(N/m is not a rotational rate) is a `CompileError`: it would act nowhere, twice, or in the wrong unit. A hinge or slider with
no spring-damper has neither.

**Motors (B-03b).** A motor actuator (`DesignSpec.actuators`, kind `motor`) on an instance whose part has role `motor` drives
its `hinge` joint. Its MJCF element is `<motor joint gear="1">` and `ctrl` is the joint torque [N*m], limited to the stall
torque; `DriveRuntime` writes it every step from the command and the joint speed. A motor on a part with no `torque_speed`
curve (no role) or on a slider (the curve is N*m against rad/s) is a `CompileError`.

What a command means (`motor_torque`): the curve is the torque limit at command 1, the part's rated voltage. A command `u` in
[-1, 1] is the fraction of that voltage with its sign (a PWM duty): a DC motor at a fraction `a = |u|` of its voltage has the
same torque-speed line scaled by `a` on both axes, so the torque is `u * T(s / a)`, where `T` is the curve and `s` the joint
speed in the commanded direction. For the linear curve of a DC motor that is exactly `T0 (u - omega / omega0)`. The no-load
speed at command `u` is `a * omega0`. Beyond it the torque is 0 (the curve ends at 0; the model has no braking quadrant, as
`parts.curves` says); driven backwards (`s < 0`) it is the stall torque, the curve's first point (no extrapolation past it);
command 0 is no torque (the motor coasts).

**Supply draw (B-03d).** A motor with `supply` draws electrical energy from that battery instance. The current of a DC motor is
linear in its torque, and the datasheet gives the two ends: `I = I0 + (Is - I0) |tau| / T0` (specs `no_load_current`,
`stall_current` [A] and the curve's stall torque `T0`), so a metered motor's part must carry both current specs. At command
`u` the battery gives `P = |u| V I` [W] (V the rated voltage, the PWM average), every step `P dt` from the one `Supply` per
battery instance. When it gives less (`Draw.satisfied < 1`) the torque that step is scaled by `satisfied`, and an empty
battery drives nothing. Motors that share a battery draw in actuator id order. Nothing is given back (no regeneration).

Not here: thrusters and tanks (X-01c), the planet's gravity and `<option>` (W-03a), contact parameters and friction
composition, a torsion spring on a hinge, the motor's rotor inertia and the battery's voltage sag (the torque curve is the
curve at the motor's rated voltage, whatever the battery's nominal voltage is).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from kinetra_core import ActuatorKind, JointKind, PartDef, PartRole, Quantity

from ..parts import Supply, battery_supply, motor_characteristics, motor_torque_limit, spring_damper_characteristics
from .bodytree import BodyTree, CompileError

MOTOR_NO_LOAD_CURRENT = "no_load_current"
MOTOR_STALL_CURRENT = "stall_current"
"""Spec names [A] a metered motor's part must carry (the datasheet's current at no load and at stall, rated voltage)."""


@dataclass(frozen=True)
class JointSpring:
    """Stiffness [N/m] and damping [N*s/m] on slider `joint`, from spring-damper instance `instance` of part `part`."""

    joint: str
    instance: str
    part: str
    stiffness: float
    damping: float


@dataclass(frozen=True)
class MotorDrive:
    """A motor actuator: `actuator` (its id is the control channel) on instance `instance` of `part`, driving hinge `joint`.

    `stall_torque` [N*m], `no_load_speed` [rad/s] and `rated_voltage` [V] are the part's (`motor_characteristics`). `supply`
    is the battery instance it draws from (`None`: not metered); then `no_load_current` and `stall_current` [A] are the part's
    specs, else `None`."""

    actuator: str
    joint: str
    instance: str
    part: PartDef
    stall_torque: float
    no_load_speed: float
    rated_voltage: float
    supply: str | None
    no_load_current: float | None
    stall_current: float | None

    def torque(self, command: float, speed: float) -> float:
        """Joint torque [N*m] at `command` in [-1, 1] and joint speed `speed` [rad/s] (see the module docstring)."""
        if not (math.isfinite(command) and -1.0 <= command <= 1.0):
            raise ValueError(f"motor {self.actuator!r}: a command is in [-1, 1], got {command}")
        if not math.isfinite(speed):
            raise ValueError(f"motor {self.actuator!r}: the joint speed must be finite, got {speed}")
        if command == 0.0:
            return 0.0
        a = abs(command)
        s = math.copysign(1.0, command) * speed  # speed in the commanded direction
        if s <= 0.0:
            full = self.stall_torque
        else:
            full = motor_torque_limit(self.part, s / a)  # 0 at and beyond the no-load speed
        return command * full

    def electrical_power(self, command: float, torque: float) -> float:
        """Power [W] the motor takes from its battery at `command` while giving `torque` [N*m]: `|u| V (I0 + (Is - I0) |tau| / T0)`."""
        if self.no_load_current is None or self.stall_current is None:
            raise ValueError(f"motor {self.actuator!r} is not metered")
        current = self.no_load_current + (self.stall_current - self.no_load_current) * abs(torque) / self.stall_torque
        return abs(command) * self.rated_voltage * current


@dataclass(frozen=True)
class Drives:
    """What `compile_drives` found: springs by joint id, motors by actuator id, and the batteries the motors draw from (instance
    id -> `Supply` at the start of a run), all in id order."""

    springs: tuple[JointSpring, ...]
    motors: tuple[MotorDrive, ...]
    supplies: tuple[tuple[str, Supply], ...]

    def spring(self, joint_id: str) -> JointSpring | None:
        return next((s for s in self.springs if s.joint == joint_id), None)


def _spec(part: PartDef, name: str) -> float | None:
    return next((s.value for s in part.specs if s.name == name), None)


def compile_drives(tree: BodyTree) -> Drives:
    """Springs, motors and supplies of `tree` (built by `build_body_tree`, which read the design in canonical order)."""
    design = tree.design
    parts = {p.id: p for p in design.parts}
    instances = {i.id: i for i in design.instances}
    joints = {j.id: j for j in design.joints}

    def params(instance_id: str) -> dict[str, Quantity]:
        return {p.name: p for p in instances[instance_id].parameters}

    springs: list[JointSpring] = []
    for inst in design.instances:
        part = parts[inst.part]
        if part.role is not PartRole.SPRING_DAMPER:
            continue
        moving = [j for j in design.joints if j.kind is not JointKind.FIXED and inst.id in (j.a.instance, j.b.instance)]
        if len(moving) != 1 or moving[0].kind is not JointKind.SLIDER:
            found = ", ".join(f"{j.kind.value} {j.id!r}" for j in moving) or "none"
            raise CompileError(
                f"spring-damper instance {inst.id!r} (part {part.id!r}) acts along exactly one slider joint at its snap points; "
                f"found {found}",
                instances=(inst.id,),
                joints=tuple(j.id for j in moving),
                parts=(part.id,),
            )
        joint = moving[0]
        if any(s.joint == joint.id for s in springs):
            raise CompileError(
                f"slider joint {joint.id!r} has a spring-damper at both ends ({joint.a.instance!r} and {joint.b.instance!r})",
                instances=(joint.a.instance, joint.b.instance),
                joints=(joint.id,),
            )
        c = spring_damper_characteristics(part, params(inst.id))
        springs.append(JointSpring(joint.id, inst.id, part.id, c.stiffness, c.damping))
    springs.sort(key=lambda s: s.joint)

    motors: list[MotorDrive] = []
    supplies: dict[str, Supply] = {}
    for act in design.actuators:
        if act.kind is not ActuatorKind.MOTOR:
            continue  # thrusters: X-01c
        assert act.joint is not None  # a motor names its joint (Actuator validation)
        part = parts[instances[act.instance].part]
        joint = joints[act.joint]
        ids = dict(instances=(act.instance,), joints=(joint.id,), parts=(part.id,))
        if part.role is not PartRole.MOTOR:
            raise CompileError(
                f"motor actuator {act.id!r}: part {part.id!r} of instance {act.instance!r} has no torque-speed curve (its role is "
                f"{'none' if part.role is None else repr(part.role.value)}, not 'motor')",
                **ids,
            )
        if joint.kind is not JointKind.HINGE:
            raise CompileError(
                f"motor actuator {act.id!r} drives {joint.kind.value} joint {joint.id!r}: a motor's curve is torque [N*m] against "
                "speed [rad/s], so it drives a hinge",
                **ids,
            )
        mc = motor_characteristics(part)
        i0 = i_s = None
        if act.supply is not None:
            i0, i_s = _spec(part, MOTOR_NO_LOAD_CURRENT), _spec(part, MOTOR_STALL_CURRENT)
            if i0 is None or i_s is None:
                raise CompileError(
                    f"motor actuator {act.id!r} draws from {act.supply!r}, but part {part.id!r} does not give the specs "
                    f"{MOTOR_NO_LOAD_CURRENT!r} and {MOTOR_STALL_CURRENT!r} [A] the draw is computed from",
                    **ids,
                )
            if act.supply not in supplies:
                source = instances[act.supply]
                supplies[act.supply] = battery_supply(parts[source.part], params(source.id))
        motors.append(MotorDrive(act.id, joint.id, act.instance, part, mc.stall_torque, mc.no_load_speed, mc.rated_voltage, act.supply, i0, i_s))
    return Drives(tuple(springs), tuple(motors), tuple(sorted(supplies.items())))


class DriveRuntime:
    """The motors of one run against a loaded model: writes `data.ctrl` before each step and keeps the batteries.

    `model` must be the MuJoCo model of `to_mjcf(tree, drives=drives)`. `supplies` overrides the starting `Supply` of some
    battery instances (default: `drives.supplies`)."""

    def __init__(self, model, drives: Drives, supplies: Mapping[str, Supply] | None = None) -> None:
        import mujoco

        self.drives = drives
        self.supplies: dict[str, Supply] = dict(drives.supplies) | dict(supplies or {})
        self._rows: list[tuple[MotorDrive, int, int]] = []
        for m in drives.motors:
            act = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, m.actuator)
            jnt = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, m.joint)
            if act < 0 or jnt < 0:
                raise ValueError(f"motor {m.actuator!r}: the model has no actuator or joint of that name (compile it with drives)")
            self._rows.append((m, act, int(model.jnt_dofadr[jnt])))
        self.energy: dict[str, float] = {m.actuator: 0.0 for m in drives.motors}
        """Energy [J] each metered motor has taken so far."""

    def apply(self, data, commands: Mapping[str, float], dt: float) -> None:
        """Set each motor's torque for the next step of `dt` seconds from its command (absent: 0) and its joint speed now, and
        draw that step's energy from its battery."""
        for m, act, dof in self._rows:
            u = commands.get(m.actuator, 0.0)
            tau = m.torque(u, float(data.qvel[dof]))
            if m.supply is not None:
                draw = self.supplies[m.supply].draw_rate(m.electrical_power(u, tau), dt)
                self.supplies[m.supply] = draw.supply
                self.energy[m.actuator] += draw.delivered
                tau *= draw.satisfied
            data.ctrl[act] = tau
