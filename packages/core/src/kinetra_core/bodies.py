"""Planet data (W-01): gravity, atmosphere density, ground friction and insolation of Earth, Mars and the Moon.

The numbers live in `data/bodies/{earth,mars,moon}.json`, one file per planet, never in code. A wheel carries the same
files as package data (`kinetra_core/bodies_data/`, hatch `force-include` in `packages/core/pyproject.toml`), so a
non-editable install finds them; a source checkout reads `data/bodies` itself. Every constant is a
`Quantity` (value, unit, badge, `Source`), so a reviewer reads each number next to where it came from and the day it
was read (`accessed 2026-11-11` in `source.ref`). The engine reads planet constants only through `load_body`
(`docs/architecture/client-adapter.md` rule C4, P2); `tests/test_bodies.py` fails when engine or client code carries a
literal that looks like one of the three gravities.

Ground friction is not one number. It is an `Assumption` (C-01c): a nominal for the deterministic search and a
distribution Monte-Carlo samples. Both carry their own badge and source, and `confidence` says how much to trust
them. The distribution's bounds are an `estimate` unless a source prints a distribution; none does. The loader holds
the files to the same rules the tests state: badges only `cite`, `default` or `estimate` (a planet constant is never
`sim` or `declared`), the friction distribution is `uniform` or `normal`, and `editable` is `False` (the user does not
edit a planet; `docs/architecture/client-adapter.md` rule C4). That `Assumption` is not a row of the project's
`AssumptionTable`, which rejects planet keys; see `docs/architecture/bodies.md`, "Gravity and the verdict's table".

`unverified` lists the constants whose value is not a cited number (badge `estimate` or `default`): a value that is a
modelling choice, or a proxy for something no source measured. The loader requires the list to match the badges, so a
value cannot be weakened without saying so, and cannot be listed without a reason.

Not here: terrain elevation (out of scope of W-01), a time or place resolved atmosphere, wind, day/night. One uniform
gravity and one surface air density per planet is the model (W-06 labels it so in the assumption table).

`check_world_references` is the cross-reference rule C-01c could not check: a `World` names its planet and its terrain
props name materials, and both must exist.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assumption import Assumption
from .conventions import ID_PATTERN, Unit
from .provenance import Badge, Quantity
from .world import World

BODY_IDS = ("earth", "mars", "moon")
"""The three planets of S1, in the order the studio shows them."""

BODIES_DIR = Path(__file__).resolve().parents[4] / "data" / "bodies"
"""`data/bodies` of a source checkout. `packages/core/src/kinetra_core/bodies.py` sits four levels under the repo root."""

PACKAGED_DIR = "bodies_data"
"""Where an installed wheel keeps the same files (`kinetra_core/bodies_data/`)."""

_Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
_NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]

BodyItem = Literal["gravity", "atmosphere_density", "insolation", "ground_friction"]
_WEAK = frozenset({Badge.ESTIMATE, Badge.DEFAULT})
_ALLOWED_BADGES = frozenset({Badge.CITE, Badge.DEFAULT, Badge.ESTIMATE})


class Gravity(Quantity):
    """Uniform surface gravitational acceleration, m/s^2, > 0."""

    value: _Positive
    unit: Literal[Unit.M_PER_S2]


class AtmosphereDensity(Quantity):
    """Air density at the surface, kg/m^3. 0 is a vacuum (the Moon)."""

    value: _NonNegative
    unit: Literal[Unit.KG_PER_M3]


class Insolation(Quantity):
    """Solar irradiance at the planet's mean distance from the Sun, W/m^2 (above the atmosphere, not at the ground)."""

    value: _NonNegative
    unit: Literal[Unit.W_PER_M2]


class Unverified(BaseModel):
    """A constant that is not a cited number, and why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item: BodyItem
    reason: str = Field(min_length=1, max_length=1000)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    gravity: Gravity
    atmosphere_density: AtmosphereDensity
    insolation: Insolation
    ground_friction: Assumption
    unverified: tuple[Unverified, ...] = ()

    @model_validator(mode="after")
    def _badges_are_cite_default_or_estimate(self) -> "Body":
        """A planet constant is read from a source (`cite`), chosen by us with a reason (`default`) or weakly
        grounded (`estimate`). `sim` (computed by the engine) and `declared` (typed by the user) have no place here."""
        d = self.ground_friction.distribution
        items = {
            "gravity": self.gravity.badge,
            "atmosphere_density": self.atmosphere_density.badge,
            "insolation": self.insolation.badge,
            "ground_friction.value": self.ground_friction.value.badge,
        }
        if d.kind != "fixed":
            items["ground_friction.distribution"] = d.badge
        for name, badge in items.items():
            if badge not in _ALLOWED_BADGES:
                raise ValueError(f"{name}: a planet constant is cite, default or estimate, not {badge.value!r}")
        return self

    @model_validator(mode="after")
    def _ground_friction_is_a_coefficient(self) -> "Body":
        a = self.ground_friction
        if a.key != "ground_friction":
            raise ValueError(f"ground_friction.key must be 'ground_friction', got {a.key!r}")
        if a.editable:
            raise ValueError("ground_friction.editable must be false: the user does not edit a planet (rule C4)")
        if a.value.unit is not Unit.ONE:
            raise ValueError("ground_friction is a dimensionless coefficient: value.unit must be '1'")
        if a.value.value < 0:
            raise ValueError("ground_friction.value must be >= 0")
        d = a.distribution
        if d.kind == "fixed":
            raise ValueError("ground_friction needs a distribution (uniform or normal): a fixed one hides the spread")
        if d.kind == "uniform" and d.low < 0:
            raise ValueError("ground_friction distribution must not reach below 0")
        if d.kind == "normal" and (d.mean < 0 or d.clip_low is None or d.clip_low < 0):
            raise ValueError("ground_friction normal distribution needs mean >= 0 and a clip_low >= 0")
        return self

    @model_validator(mode="after")
    def _unverified_matches_badges(self) -> "Body":
        listed = [u.item for u in self.unverified]
        if len(set(listed)) != len(listed):
            raise ValueError("duplicate unverified item")
        d = self.ground_friction.distribution
        weak = {
            "gravity": self.gravity.badge in _WEAK,
            "atmosphere_density": self.atmosphere_density.badge in _WEAK,
            "insolation": self.insolation.badge in _WEAK,
            "ground_friction": self.ground_friction.value.badge in _WEAK
            or (d.kind != "fixed" and d.badge in _WEAK),
        }
        for item, is_weak in weak.items():
            if is_weak and item not in listed:
                raise ValueError(f"{item} is not a cited value (estimate or default) and must be listed in unverified")
            if not is_weak and item in listed:
                raise ValueError(f"{item} is cited but listed in unverified; remove it or weaken its badge")
        return self


def _read(path: Path | Traversable) -> Body:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"planet data file not found: {path}") from None
    body = Body.model_validate(json.loads(text))
    if f"{body.id}.json" != path.name:
        raise ValueError(f"{path.name}: id {body.id!r} must equal the file name {body.id + '.json'!r}")
    return body


@cache
def _load_default(body_id: str) -> Body:
    if BODIES_DIR.is_dir():
        return _read(BODIES_DIR / f"{body_id}.json")
    return _read(resources.files(__package__).joinpath(PACKAGED_DIR, f"{body_id}.json"))


def load_body(body_id: str, *, directory: Path | None = None) -> Body:
    """Read and validate `<directory>/<body_id>.json`; default `data/bodies`, or the wheel's package data when this
    is an installed copy. Any value without badge and source fails here."""
    if directory is None:
        if body_id not in BODY_IDS:
            raise KeyError(f"unknown planet {body_id!r}; known: {', '.join(BODY_IDS)}")
        return _load_default(body_id)
    return _read(directory / f"{body_id}.json")


def load_bodies(*, directory: Path | None = None) -> Mapping[str, Body]:
    """All three planets by id."""
    return {i: load_body(i, directory=directory) for i in BODY_IDS}


def check_world_references(world: World, *, planets: Iterable[str], materials: Iterable[str]) -> None:
    """Reject a `World` that names a planet that has no data, or a terrain prop whose material is not in `materials`.

    `materials` are the IDs of the project's own materials (`DesignSpec.materials`). A prop without a material stands on
    the planet's ground and needs none. Raises `ValueError` listing every problem.
    """
    known_planets, known_materials = set(planets), set(materials)
    problems = []
    if world.planet not in known_planets:
        problems.append(f"unknown planet {world.planet!r}; known: {', '.join(sorted(known_planets))}")
    for prop in world.terrain_props:
        if prop.material is not None and prop.material not in known_materials:
            problems.append(f"terrain prop {prop.id!r}: unknown material {prop.material!r}")
    if problems:
        raise ValueError("; ".join(problems))
