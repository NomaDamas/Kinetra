"""Planet constants of a compiled model (W-03a): gravity and atmosphere density, read from `data/bodies` and nowhere else.

    planet_physics(planet_id, directory=None) -> PlanetPhysics

The project names its planet (`World.planet`) and never carries a constant (`World` rejects them, C-01c). The compiler
reads the constants through `kinetra_core.load_body` only, so the numbers keep the badge and source of the data file
(`docs/architecture/bodies.md`). `build_body_tree` calls this for `project.world.planet` and keeps the result on the tree;
`to_mjcf` writes it as the model's `<option>`.

**Gravity** is one uniform vector `(0, 0, -g)`: +Z is up (`bodytree.py`, "Frames") and `g` is the planet's surface gravity.
One g per planet is the model (W-06 labels it in the assumption table).

**Atmosphere density** is carried here as the planet's `Quantity`, and the MJCF sets MuJoCo's own medium to zero
(`density="0" viscosity="0"`). MuJoCo's medium is one global number for every body and its inertia-box drag is a fixed
model nobody labels (`docs/research/fluids/mujoco-water.md` 3.1 and 7.1). Drag is W-03b's: a force per body from this
density, labelled "근사: 집중 항력". Writing the density into `<option>` as well would add a second, unlabelled drag.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kinetra_core.bodies import AtmosphereDensity, Gravity, load_body


@dataclass(frozen=True)
class PlanetPhysics:
    """The planet constants a compiled model runs with. `gravity` and `atmosphere_density` are the data file's
    `Quantity`s (value, unit, badge, source), unchanged."""

    planet: str
    gravity: Gravity
    atmosphere_density: AtmosphereDensity

    @property
    def gravity_vector(self) -> tuple[float, float, float]:
        """World gravity [m/s^2], +Z up."""
        return (0.0, 0.0, -self.gravity.value)


def planet_physics(planet_id: str, directory: Path | None = None) -> PlanetPhysics:
    """The constants of `planet_id` from `<directory>/<planet_id>.json` (default `data/bodies`, see `load_body`).
    Raises what `load_body` raises: `KeyError` for an unknown planet, `FileNotFoundError`, or a validation error."""
    body = load_body(planet_id, directory=directory)
    return PlanetPhysics(body.id, body.gravity, body.atmosphere_density)
