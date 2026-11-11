"""The five S1 materials with sourced properties and PBR slots (B-07).

The data is `material_catalog.json` next to this file: one entry per material, each a `Material` (C-01a) plus
`PbrSlots`. Numbers live in the data file, never in code, so a reviewer reads each value beside its source. Every
property is a `Quantity` with a badge and a `Source`; the per-material choices, ranges and caveats are in
`docs/architecture/materials.md`.

`friction` is the dry kinetic Coulomb coefficient of the material sliding against steel. That convention is the
same for all five, so the numbers are comparable; how two parts' coefficients combine at a contact is the
compiler's decision (X-01).

Out of scope: more materials (a material database, S2), pairwise friction tables, anisotropy.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from pydantic import BaseModel, ConfigDict, model_validator

from .material import Material
from .pbr import PbrSlots

CATALOG_FILE = "material_catalog.json"


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    material: Material
    pbr: PbrSlots


class MaterialCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[CatalogEntry, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> "MaterialCatalog":
        ids = [e.material.id for e in self.entries]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"material ids must be unique, repeated: {dupes}")
        return self

    def get(self, material_id: str) -> CatalogEntry:
        for e in self.entries:
            if e.material.id == material_id:
                return e
        raise KeyError(material_id)


@cache
def load_material_catalog() -> MaterialCatalog:
    """Read and validate the packaged catalog. Any property without badge and source fails here."""
    text = resources.files(__package__).joinpath(CATALOG_FILE).read_text(encoding="utf-8")
    return MaterialCatalog.model_validate(json.loads(text))
