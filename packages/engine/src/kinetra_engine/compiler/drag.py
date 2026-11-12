"""Lumped air drag of a body tree (W-03b): one drag area per rigid body, the planet's air density, a force we apply ourselves.

    drag = compile_drag(tree)                 # Drag: C_d*A per body [m^2] and the medium density function
    runtime = DragRuntime(model, drag)        # per run, against the model of to_mjcf(tree, ...)
    runtime.step(data)                        # mj_step1 -> xfrc_applied += drag -> mj_step2

**Force.** Every body gets `F = -1/2 rho(x) C_dA |v| v` at its centre of mass, where `v` is the world velocity of the centre of
mass, `x` its world position and `rho = medium_density(x)` [kg/m^3]. No torque, no lift, no wind (the issue's scope). One
isotropic `C_dA` per body is the "lumped" approximation: it does not depend on which way the body faces.

**Not MuJoCo's fluid model (the decision, `docs/research/fluids/mujoco-water.md` 7.1).** MuJoCo's medium (`opt.density`,
`opt.viscosity`) is one global number for every body, so air and a water region (S2) cannot share a scene, and its inertia-box
model has a fixed coefficient. So `to_mjcf` keeps the medium off (`planet.py`) and this module applies the force through
`xfrc_applied` between `mj_step1` and `mj_step2` (the force sees this step's positions and velocities; the path is part of the
trajectory hash, `docs/decisions/engine.md` 4.4). The density is read in one place, `Drag.medium_density(position)`: in S1 it is
the planet's surface atmosphere density everywhere (`planet_medium`); FL-03b swaps the function, not the force.

**Drag area of a shape (`geom_drag_area`).** Per collision-proxy geom, the mean over the geom's three axes of `C_d * A`, `A` the
projected area seen along that axis and `C_d` the table value for that view (Baker et al. 1983 via Aarønæs 2014, table 2-2;
reference area the projected area normal to the flow):

| geom | along each axis | `C_dA` |
|---|---|---|
| sphere r | 0.47, `pi r^2` | `0.47 pi r^2` (exact table case, `cite`) |
| box a x b x c (full) | cube face-on 1.05, the face area | `1.05 (ab + bc + ca) / 3` (`estimate`: the cube's value on any box) |
| cylinder r, length L | side-on (long rod) 1.20, `2 r L`, twice; end-on (rod) 0.82, `pi r^2` | `(2 * 1.20 * 2 r L + 0.82 pi r^2) / 3` (`estimate`) |

A body's `C_dA` is the sum over its geoms. Overlap and one geom shielding another are not subtracted, so a body of many geoms
gets more drag than it would (an upper bound of this model, not of reality).

**Moon.** Its atmosphere density is 0 (`data/bodies/moon.json`), so the force is 0 and `DragRuntime` adds nothing: the
trajectory is bit for bit the one without drag. The label is shown only where the medium density is above 0.

**Explicit force.** MuJoCo integrates `xfrc_applied` without its derivative, so drag is explicit in velocity. Linearised, one
step multiplies a velocity error by `1 - h rho C_dA |v| / m`: stable while `h rho C_dA |v| / m < 2` (for a falling free body at
its terminal speed `v_t`, `h < v_t / g`), without overshoot below half that. `test_drag.py` measures both sides of that limit.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from kinetra_core import Badge, Quantity, Source, Unit

from .bodytree import BodyGeom, BodyTree, Vec
from .planet import PlanetPhysics

DRAG_LABEL = "근사: 집중 항력"
"""The model label of the assumption table and the run's `model_labels`, present when the medium has density above 0."""

MediumDensity = Callable[[Vec], float]
"""`medium_density(world_position) -> kg/m^3`: the density of the fluid at a world point."""

_REF = (
    "Baker et al. 1983, Explosion Hazards and Evaluation (Elsevier), as reproduced in Aarønæs 2014, Chalmers master's thesis; "
    "reference area the projected area normal to the flow; accessed 2026-11-12"
)


def _cd(value: float, badge: Badge, why: str) -> Quantity:
    source = Source(
        ref=f"{why}. {_REF}",
        locator="Aarønæs 2014, section 2.3.2, table 2-2 (p. 9)",
        url="http://publications.lib.chalmers.se/records/fulltext/199998/199998.pdf",
    )
    return Quantity(value=value, unit=Unit.ONE, badge=badge, source=source)


SPHERE_CD = _cd(0.47, Badge.CITE, "Sphere, the table's value")
BOX_CD = _cd(
    1.05,
    Badge.ESTIMATE,
    "Cube face-on, the table's value, used for every view of any box; the table gives a cube edge-on 0.80 and a long "
    "rectangular member face-on 2.05, so a flat or long box has more drag than this",
)
CYLINDER_SIDE_CD = _cd(
    1.20,
    Badge.ESTIMATE,
    "Right circular cylinder (long rod) side-on, the table's value, used for any cylinder seen from the side",
)
CYLINDER_END_CD = _cd(
    0.82,
    Badge.ESTIMATE,
    "Rod end-on, the table's value, used for any cylinder seen along its axis; the table gives a disc face-on 1.17, so a "
    "short cylinder has more drag than this",
)


def geom_drag_area(geom: BodyGeom) -> float:
    """`C_d * A` [m^2] of one geom, the mean over its three axes (module docstring). `geom.size` is MuJoCo's: box half
    extents, cylinder (radius, half length), sphere radius."""
    if geom.type == "sphere":
        r = geom.size[0]
        return SPHERE_CD.value * math.pi * r * r
    if geom.type == "box":
        a, b, c = (2.0 * s for s in geom.size[:3])
        return BOX_CD.value * (a * b + b * c + c * a) / 3.0
    if geom.type == "cylinder":
        r, length = geom.size[0], 2.0 * geom.size[1]
        return (2.0 * CYLINDER_SIDE_CD.value * 2.0 * r * length + CYLINDER_END_CD.value * math.pi * r * r) / 3.0
    raise ValueError(f"geom {geom.name!r}: no drag coefficient for type {geom.type!r}")


def planet_medium(planet: PlanetPhysics) -> MediumDensity:
    """S1's medium: the planet's surface atmosphere density (`data/bodies`) at every point."""
    rho = float(planet.atmosphere_density.value)
    return lambda position: rho


@dataclass(frozen=True)
class BodyDrag:
    """`area`: the lumped `C_d * A` [m^2] of body `body`, the sum of its geoms' (`geom_drag_area`)."""

    body: str
    area: float


@dataclass(frozen=True)
class Drag:
    """The drag of a compile: one `BodyDrag` per body in tree order, and the one place the density is read."""

    bodies: tuple[BodyDrag, ...]
    medium_density: MediumDensity
    planet: PlanetPhysics

    def area(self, body_id: str) -> float:
        return next(b.area for b in self.bodies if b.body == body_id)


def compile_drag(tree: BodyTree, medium: MediumDensity | None = None) -> Drag:
    """The drag areas of `tree`'s bodies and the medium (default `planet_medium(tree.planet)`)."""
    bodies = tuple(BodyDrag(b.id, math.fsum(geom_drag_area(g) for g in b.geoms)) for b in tree.bodies)
    return Drag(bodies, medium if medium is not None else planet_medium(tree.planet), tree.planet)


def drag_force(density: float, area: float, velocity: Vec) -> Vec:
    """`-1/2 rho C_dA |v| v` [N]."""
    vx, vy, vz = velocity
    k = -0.5 * density * area * math.sqrt(vx * vx + vy * vy + vz * vz)
    return (k * vx, k * vy, k * vz)


class DragRuntime:
    """The drag of one run against a loaded model: `model` must be the MuJoCo model of `to_mjcf(tree, ...)` for the tree
    `drag` was compiled from (bodies are found by name).

    Per step: `mj_step1`, `apply`, `mj_step2`, `restore` (or `step`, which does the four). `apply` adds this step's drag into
    `xfrc_applied` and remembers the rows it touched as they were; `restore` puts exactly those rows back, so a force another
    writer keeps there (thrust, `ThrustRun.begin_step`/`end_step`) is neither cleared nor accumulated."""

    def __init__(self, model, drag: Drag) -> None:
        import mujoco

        self.model = model
        self.drag = drag
        self._rows: list[tuple[int, float]] = []
        for b in drag.bodies:
            i = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b.body)
            if i < 0:
                raise ValueError(f"body {b.body!r}: the model has no body of that name (compile it from the same tree)")
            self._rows.append((i, b.area))
        self._saved: list[tuple[int, object]] | None = None

    def apply(self, data) -> None:
        """Add each body's drag to `data.xfrc_applied` (force rows, world frame, at the centre of mass). Call it after
        `mj_step1`, so positions and velocities are this step's, and call `restore` after `mj_step2`. A body in a medium of
        density 0 gets nothing and its row is not touched."""
        import mujoco
        import numpy as np

        if self._saved is not None:
            raise RuntimeError("apply called twice without restore")
        saved: list[tuple[int, object]] = []
        res = np.zeros(6)
        for i, area in self._rows:
            x = data.xipos[i]
            rho = self.drag.medium_density((float(x[0]), float(x[1]), float(x[2])))
            if rho == 0.0:
                continue
            mujoco.mj_objectVelocity(self.model, data, mujoco.mjtObj.mjOBJ_BODY, i, res, 0)  # [angular; linear] at xipos, world
            f = drag_force(rho, area, (float(res[3]), float(res[4]), float(res[5])))
            saved.append((i, data.xfrc_applied[i, :3].copy()))
            data.xfrc_applied[i, 0] += f[0]
            data.xfrc_applied[i, 1] += f[1]
            data.xfrc_applied[i, 2] += f[2]
        self._saved = saved

    def restore(self, data) -> None:
        """Put back the `xfrc_applied` rows the last `apply` touched, as they were before it."""
        if self._saved is None:
            raise RuntimeError("restore called without apply")
        for i, row in self._saved:
            data.xfrc_applied[i, :3] = row
        self._saved = None

    def step(self, data) -> None:
        """One step with drag: `mj_step1`, `apply`, `mj_step2`, `restore`."""
        import mujoco

        mujoco.mj_step1(self.model, data)
        self.apply(data)
        mujoco.mj_step2(self.model, data)
        self.restore(data)
