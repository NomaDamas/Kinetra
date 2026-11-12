"""Joints and actuators of a body tree (X-01b): spring-dampers on sliders, motors on hinges, and what a motor draws.

    drives = compile_drives(tree)                       # Drives, or CompileError
    xml = to_mjcf(tree, drives=drives)                  # joints with stiffness/damping, one <motor> per motor actuator
    runtime = DriveRuntime(model, drives)               # per run: owns the supplies
    runtime.apply(data, {"m1": 1.0}, dt)                # before each mj_step: sets data.ctrl, draws energy

**Spring-dampers (B-03e).** A part with role `spring_damper` acts along the joint at one of its snap points: the one `slider`
joint whose `a` or `b` end is on that instance. Its `stiffness` [N/m] and `damping` [N*s/m] (the instance's values, or the
part's defaults) become the MuJoCo joint's `stiffness` and `damping`; the spring's force is 0 at joint coordinate 0, the saved
pose (MJCF `springref` 0, the model's reference pose). A spring-damper instance at no slider, at more than one, or at a hinge
(N/m is not a rotational rate) is a `CompileError` `spring_joint`: it would act nowhere, twice, or in the wrong unit. A hinge or slider with
no spring-damper has neither.

**Motors (B-03b).** A motor actuator (`DesignSpec.actuators`, kind `motor`) on an instance whose part has role `motor` drives
its `hinge` joint. A motor on a slider (the curve is N*m against rad/s) is a `CompileError` `motor_joint`; one on a part with
no role (no curve) `build_body_tree` already refused (`no_curve`, X-01d).

What a command means (`MotorDrive.torque`): the curve is the torque at command 1, the part's rated voltage. A command `u` in
[-1, 1] is the fraction of that voltage with its sign (a PWM duty, `a = |u|`). A DC motor's torque is linear in voltage and
speed, `tau = u T0 - (T0 / omega0) omega` (stall torque `T0`, no-load speed `omega0`, the curve's two ends): at a fraction
`a` of the voltage the line is scaled by `a` on both axes, and the `-(T0 / omega0) omega` part is the back-EMF, the same at
every command. Inside the curve's range (`0 <= s <= a omega0`, `s` the joint speed in the commanded direction) the torque is
the curve, `u T(s / a)`; outside it the curve says nothing and the torque is that line: beyond the no-load speed it brakes,
driven backwards it exceeds the stall torque, and at command 0 (0 V, terminals shorted) it brakes as `-(T0 / omega0) omega`.
For the library's linear curves the curve and the line are one.

**Why the back-EMF is joint damping (#546).** The back-EMF is a viscous damping `T0 / omega0` [N*m*s/rad] on the joint, so the
MJCF gives the hinge `damping="T0/omega0"` (summed over the motors on it) and MuJoCo's Euler integrator applies it implicitly
(it integrates joint damping implicitly, `(M + h D) qacc = f`): a light body on the motor (a free root whose inertia about the
axis is tiny) settles at the no-load speed and does not overshoot it, whatever the time step. The actuator is
`<motor joint gear="1">` and `ctrl` is the rest, `tau + (T0 / omega0) omega` (`MotorDrive.ctrl`), which for a linear curve is
the constant `u T0`: nothing velocity-dependent is left explicit. Written as an explicit torque from the step's starting
speed instead, one step of stall torque on 3e-5 kg*m^2 gives ~137 rad/s on a 20.9 rad/s motor (#546). A `<general>`
actuator with a velocity bias would need the `implicitfast` integrator for the same effect, changing the integration of every
model; joint damping needs no change.

**Supply draw (B-03d).** A motor with `supply` draws electrical energy from that battery instance. The current of a DC motor is
linear in its torque, and the datasheet gives the two ends: `I = I0 + (Is - I0) tau_d / T0`, `tau_d` the torque in the
commanded direction, not below 0 (specs `no_load_current`, `stall_current` [A] and the curve's stall torque `T0`), so a
metered motor's part must carry both current specs (else `CompileError` `no_current`). At command `u` the battery gives
`P = |u| V I` [W] (V the rated voltage, the PWM average), every step `P dt` from the one `Supply` per battery instance. When it
gives less (`Draw.satisfied < 1`) the driving part (`ctrl`) that step is scaled by `satisfied`; the back-EMF damping stays (an
empty battery is 0 V). Motors that share a battery draw in actuator id order. Nothing is given back (no regeneration:
braking draws no current from the battery and puts none in).

Not here: thrusters and tanks (X-01c), the planet's gravity and `<option>` (W-03a), contact parameters and friction
composition, a torsion spring on a hinge, the motor's rotor inertia and the battery's voltage sag (the torque curve is the
curve at the motor's rated voltage, whatever the battery's nominal voltage is).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from kinetra_core import ActuatorKind, JointKind, PartDef, PartRole, Quantity

from ..parts import Supply, battery_supply, motor_characteristics, motor_torque_limit, spring_damper_characteristics
from .bodytree import BodyTree
from .errors import CompileError, CompileErrorCode

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

    @property
    def back_emf_damping(self) -> float:
        """`T0 / omega0` [N*m*s/rad]: the slope of the DC motor's line, the hinge `damping` this motor adds to the MJCF."""
        return self.stall_torque / self.no_load_speed

    def torque(self, command: float, speed: float) -> float:
        """Joint torque [N*m] at `command` in [-1, 1] and joint speed `speed` [rad/s]: the curve inside its range, the DC motor's
        line `u T0 - (T0 / omega0) speed` outside it (see the module docstring)."""
        if not (math.isfinite(command) and -1.0 <= command <= 1.0):
            raise ValueError(f"motor {self.actuator!r}: a command is in [-1, 1], got {command}")
        if not math.isfinite(speed):
            raise ValueError(f"motor {self.actuator!r}: the joint speed must be finite, got {speed}")
        line = command * self.stall_torque - self.back_emf_damping * speed
        a = abs(command)
        s = math.copysign(1.0, command) * speed  # speed in the commanded direction
        if a == 0.0 or not 0.0 <= s < a * self.no_load_speed:
            return line
        return command * motor_torque_limit(self.part, s / a)

    def ctrl(self, command: float, speed: float) -> float:
        """What the MJCF `<motor>` applies [N*m]: the torque less the back-EMF the hinge's damping applies, `tau + (T0/omega0) speed`.
        For a linear curve that is `u T0`, whatever the speed."""
        return self.torque(command, speed) + self.back_emf_damping * speed

    def electrical_power(self, command: float, torque: float) -> float:
        """Power [W] the motor takes from its battery at `command` while giving `torque` [N*m]: `|u| V (I0 + (Is - I0) tau_d / T0)`,
        `tau_d` the torque in the commanded direction, at least 0 (braking takes only the no-load current, gives nothing back)."""
        if self.no_load_current is None or self.stall_current is None:
            raise ValueError(f"motor {self.actuator!r} is not metered")
        driving = max(0.0, math.copysign(1.0, command) * torque)
        current = self.no_load_current + (self.stall_current - self.no_load_current) * driving / self.stall_torque
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

    def back_emf_damping(self, joint_id: str) -> float:
        """The hinge damping [N*m*s/rad] the motors on `joint_id` add (0 when none drives it)."""
        return math.fsum(m.back_emf_damping for m in self.motors if m.joint == joint_id)

    def without_joints(self, joints: Collection[str]) -> Drives:
        """These drives with the springs and motors on `joints` taken away (joints that broke, X-04b); supplies stay."""
        gone = set(joints)
        return Drives(
            tuple(s for s in self.springs if s.joint not in gone), tuple(m for m in self.motors if m.joint not in gone), self.supplies
        )


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
                code=CompileErrorCode.SPRING_JOINT,
                instances=(inst.id,),
                parts=(part.id,),
                joints=tuple(j.id for j in moving),
            )
        joint = moving[0]
        if any(s.joint == joint.id for s in springs):
            raise CompileError(
                f"slider joint {joint.id!r} has a spring-damper at both ends ({joint.a.instance!r} and {joint.b.instance!r})",
                code=CompileErrorCode.SPRING_JOINT,
                instances=(joint.a.instance, joint.b.instance),
                parts=tuple(dict.fromkeys(instances[i].part for i in (joint.a.instance, joint.b.instance))),
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
        part = parts[instances[act.instance].part]  # role `motor`: build_body_tree refused a role-less part (no_curve)
        joint = joints[act.joint]
        ids = dict(instances=(act.instance,), parts=(part.id,), joints=(joint.id,), actuators=(act.id,))
        if joint.kind is not JointKind.HINGE:
            raise CompileError(
                f"motor actuator {act.id!r} drives {joint.kind.value} joint {joint.id!r}: a motor's curve is torque [N*m] against "
                "speed [rad/s], so it drives a hinge",
                code=CompileErrorCode.MOTOR_JOINT,
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
                    code=CompileErrorCode.NO_CURRENT,
                    **ids,
                )
            if act.supply not in supplies:
                source = instances[act.supply]
                supplies[act.supply] = battery_supply(parts[source.part], params(source.id))
        motors.append(MotorDrive(act.id, joint.id, act.instance, part, mc.stall_torque, mc.no_load_speed, mc.rated_voltage, act.supply, i0, i_s))
    return Drives(tuple(springs), tuple(motors), tuple(sorted(supplies.items())))


@dataclass(frozen=True)
class MotorStep:
    """One motor's command demand and available torque [N*m] for J-06 observation; both are computed, not inferred later."""

    actuator: str
    required: float
    limit: float


class DriveRuntime:
    """The motors of one run against a loaded model: writes `data.ctrl` before each step and keeps the batteries.

    `model` must be the MuJoCo model of `to_mjcf(tree, drives=drives)`. `supplies` overrides the starting `Supply` of some
    battery instances (default: `drives.supplies`)."""

    def __init__(self, model, drives: Drives, supplies: Mapping[str, Supply] | None = None) -> None:
        self.drives = drives
        self.supplies: dict[str, Supply] = dict(drives.supplies) | dict(supplies or {})
        self._rows: list[tuple[MotorDrive, int, int]] = []
        self.energy: dict[str, float] = {m.actuator: 0.0 for m in drives.motors}
        """Energy [J] each metered motor has taken so far."""
        self.last_steps: tuple[MotorStep, ...] = ()
        """The demand/limit pairs written by the latest `apply`, in actuator id order (J-06)."""
        self.rebind(model, drives)

    def rebind(self, model, drives: Drives) -> None:
        """Drive `model` (compiled again after a joint broke, X-04b) with `drives` (`Drives.without_joints`), keeping the
        batteries and the energy taken so far. A motor not in `drives` writes nothing more and draws nothing more."""
        import mujoco

        rows = []
        for m in drives.motors:
            act = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, m.actuator)
            jnt = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, m.joint)
            if act < 0 or jnt < 0:
                raise ValueError(f"motor {m.actuator!r}: the model has no actuator or joint of that name (compile it with drives)")
            rows.append((m, act, int(model.jnt_dofadr[jnt])))
        self.drives = drives
        self._rows = rows

    def apply(self, data, commands: Mapping[str, float], dt: float) -> None:
        """Set each motor's `ctrl` for the next step of `dt` seconds from its command (absent: 0) and its joint speed now (the
        back-EMF is the hinge's damping, applied by MuJoCo), and draw that step's energy from its battery."""
        records = []
        for m, act, dof in self._rows:
            u = commands.get(m.actuator, 0.0)
            speed = float(data.qvel[dof])
            ctrl = m.ctrl(u, speed)
            torque = m.torque(u, speed)
            satisfied = 1.0
            if m.supply is not None:
                draw = self.supplies[m.supply].draw_rate(m.electrical_power(u, torque), dt)
                self.supplies[m.supply] = draw.supply
                self.energy[m.actuator] += draw.delivered
                satisfied = draw.satisfied
                ctrl *= satisfied
            data.ctrl[act] = ctrl
            records.append(MotorStep(m.actuator, abs(u) * m.stall_torque, abs(torque) * satisfied))
        self.last_steps = tuple(records)
