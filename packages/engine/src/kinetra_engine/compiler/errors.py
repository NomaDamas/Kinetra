"""Compile errors (X-01d): why a project cannot be turned into an engine model, named by part, instance, joint and actuator.

Every refusal of the compiler is one `CompileError` with a `code` (what kind of problem, a closed list below), a sentence
(`str(error)`) and the ids it is about: `instances`, `parts` (the parts of those instances, or the part itself), `joints`
and `actuators`. Each id is only unique inside its own collection. A missing definition is not a compile error: compiling
a project with a placeholder is refused before anything is read, by `require_complete` (`ProjectIncomplete`, C-06).

| code | when |
|---|---|
| `planet` | `world.planet` has no readable data in `data/bodies` (W-03a) |
| `no_instance` | the design has no instance |
| `part` | a part cannot be compiled at an instance's parameters (shape recipe, mass) |
| `no_curve` | an actuator sits on an instance whose part has no role, so it has no curve to drive by |
| `snap_mismatch` | a joint's two snap points do not accept each other's kind, or do not meet at the stored poses |
| `axis_mismatch` | a hinge or slider axis, read in the frame of each of its two snap points, is not one line in the world |
| `fixed_loop` | a fixed joint closes a loop of fixed joints |
| `welded_joint` | a hinge or slider joins two instances that fixed joints already weld into one rigid body |
| `loop` | the hinges and sliders close a loop between bodies |
| `not_one_piece` | the assembly is two or more pieces with no joint between them |
| `floating` | the assembly touches neither the ground nor a terrain prop |
| `spring_joint` | a spring-damper instance is not at exactly one slider, or a slider has one at both ends (`compile_drives`, X-01b) |
| `motor_joint` | a motor actuator drives a slider: its curve is torque against angular speed (`compile_drives`, X-01b) |
| `no_current` | a motor that draws from a battery is a part without the specs `no_load_current` and `stall_current` (`compile_drives`, X-01b) |
"""

from __future__ import annotations

from enum import StrEnum


class CompileErrorCode(StrEnum):
    PLANET = "planet"
    NO_INSTANCE = "no_instance"
    PART = "part"
    NO_CURVE = "no_curve"
    SNAP_MISMATCH = "snap_mismatch"
    AXIS_MISMATCH = "axis_mismatch"
    FIXED_LOOP = "fixed_loop"
    WELDED_JOINT = "welded_joint"
    LOOP = "loop"
    NOT_ONE_PIECE = "not_one_piece"
    FLOATING = "floating"
    SPRING_JOINT = "spring_joint"
    MOTOR_JOINT = "motor_joint"
    NO_CURRENT = "no_current"


class CompileError(ValueError):
    """The project cannot be compiled. `code` is the kind of problem; `instances`, `parts`, `joints` and `actuators` are
    the ids the reason is about (each is only unique inside its own collection), in a fixed order."""

    def __init__(
        self,
        message: str,
        *,
        code: CompileErrorCode,
        instances: tuple[str, ...] = (),
        parts: tuple[str, ...] = (),
        joints: tuple[str, ...] = (),
        actuators: tuple[str, ...] = (),
    ):
        super().__init__(message)
        self.code = code
        self.instances = instances
        self.parts = parts
        self.joints = joints
        self.actuators = actuators
