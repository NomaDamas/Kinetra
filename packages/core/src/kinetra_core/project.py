"""`Project` (C-02a): the document that commands edit. A `DesignSpec` (what the user built), the `World` it sits in,
and the `AssumptionTable` of its verdict.

This is the unit a command is applied to and the unit a client holds a copy of (`client-adapter.md` D1). It has
no behaviour of its own: the checks inside each part stay in the part (`designspec.py`, `world.py`,
`assumption.py`), and `Project` adds the one reference that crosses them: a terrain prop's `material` must be a
material the project carries. Together that makes a dangling reference unconstructible: a `Project` that
validates has no instance without its part, no joint without its snap points, no actuator without its joint, no
schedule entry without its actuator, and no prop without its material.

`world` is required: a project sits on a planet from the start (a planet is chosen with `SelectPlanet`, never
absent). Not here: the file format, schema version and definition hashes (C-03), a missing-definitions state
(C-06), `planet` existing in `data/bodies` (W-01 data, validator C-02c).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .assumption import AssumptionTable
from .designspec import DesignSpec
from .refs import Ref, RefError, RefKind
from .world import World


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    design: DesignSpec = DesignSpec()
    world: World
    assumptions: AssumptionTable = AssumptionTable()

    @model_validator(mode="after")
    def _prop_materials_exist(self) -> "Project":
        materials = {m.id for m in self.design.materials}
        for prop in self.world.terrain_props:
            if prop.material is not None and prop.material not in materials:
                raise RefError(
                    f"world.terrain_props ({prop.id!r}): unknown material {prop.material!r}",
                    Ref(kind=RefKind.MATERIAL, id=prop.material),
                    Ref(kind=RefKind.PROP, id=prop.id),
                )
        return self
