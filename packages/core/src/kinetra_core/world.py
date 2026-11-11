"""`World` (C-01c): which planet the project sits on, and the terrain props on its flat ground.

The planet is referenced by ID only. Gravity, atmosphere density, ground friction and insolation are the planet's
constants; they live in `data/bodies/*.json` (W-01) and only the engine reads them. `World` has no field for them,
and a name that looks like one (`PLANET_CONSTANT_NAMES`) is rejected with a message that says why. That list is a
courtesy on top of `extra="forbid"`, which rejects every unknown field. The guarantee that a project's numbers
never reach the physics as planet constants is structural: the engine reads them only from `data/bodies` (W-03a)
and the validator refuses commands that try (C-02c, `docs/architecture/client-adapter.md` rule C4).

Terrain props are the two MVP shapes, ramp and step (`docs/plan/studio-plan.md` section 9). A prop's `placement`
(x, y, yaw) is one declared pose: one badge and source cover it, like a `SnapPoint` pose (C-01a). Its sizes
(`length`, `width`, `incline`, `height`) are each a `Quantity`. `material` names the `Material` of the prop's
surface (the friction is the material's); `None` means the planet's ground, whose friction comes from the planet data.

Frame: the ground is the plane z = 0 (right-handed, +Z up, `conventions.py`). A prop's footprint is a
`length` x `width` rectangle centred on (`x`, `y`) [m], turned by `yaw` [rad] about +Z. `length` runs along the
prop's local x axis and `width` along local y. A ramp rises along local +x from z = 0 and its `length` is the
horizontal run, so its rise is `length * tan(incline)` (derived, not stored). A step is a box `height` tall.

Not here: planet data and the loader (W-01), prop geometry and MJCF (W-05, X-01), editing commands (C-02a), and
checks that need the rest of the Project. That `planet` exists in `data/bodies` (W-01 data, validator #68) and that
`material` names a material of the project (validator #68; with C-01d's cross-reference rules #76) are not
checked by `World` alone, which cannot know them.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import ID_PATTERN, Unit
from .provenance import Number, Provenance, Quantity

PLANET_CONSTANT_NAMES = frozenset(
    {
        "gravity",
        "gravitational_acceleration",
        "g",
        "atmosphere_density",
        "air_density",
        "ground_friction",
        "solar_irradiance",
        "insolation",
    }
)
"""Field and key names that would carry a planet constant. Rejected with an explanation by `World` and
`AssumptionTable`. A courtesy, not a list of what is allowed."""


class PropSize(Quantity):
    """A prop dimension in metres, > 0."""

    value: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
    unit: Literal[Unit.M]


class Incline(Quantity):
    """Slope angle above the ground in radians, strictly between 0 and pi/2."""

    value: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, lt=math.pi / 2)]
    unit: Literal[Unit.RAD]


class Placement(Provenance):
    """Where a prop stands on the ground: centre `x`, `y` [m] and rotation `yaw` [rad] about +Z (counter-clockwise
    seen from above). One badge and source cover the whole placement."""

    x: Number
    y: Number
    yaw: Number


class _Prop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    material: str | None = Field(
        default=None,
        pattern=ID_PATTERN,
        description="ID of the Material of the prop's surface; None is the planet's ground.",
    )
    placement: Placement
    length: PropSize
    width: PropSize


class RampProp(_Prop):
    """Rises along local +x. `length` is the horizontal run."""

    kind: Literal["ramp"]
    incline: Incline


class StepProp(_Prop):
    """A box `height` tall (턱)."""

    kind: Literal["step"]
    height: PropSize


TerrainProp = Annotated[RampProp | StepProp, Field(discriminator="kind")]


class World(BaseModel):
    """`planet` is an ID (same pattern as every other ID); `terrain_props` sit on that planet's flat ground."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    planet: str = Field(pattern=ID_PATTERN)
    terrain_props: tuple[TerrainProp, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _no_planet_constants(cls, data: Any) -> Any:
        if isinstance(data, dict):
            sent = sorted(PLANET_CONSTANT_NAMES.intersection(data))
            if sent:
                raise ValueError(
                    f"planet constants do not belong to the project (got {', '.join(sent)}): reference the planet "
                    "by id; its constants are read from data/bodies"
                )
        return data

    @model_validator(mode="after")
    def _unique_prop_ids(self) -> "World":
        ids = [p.id for p in self.terrain_props]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate terrain prop id")
        return self
