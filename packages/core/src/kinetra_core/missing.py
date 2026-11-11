"""Missing definitions (C-06, #455): what a project names and does not carry, and where it differs from a catalog.

A `DesignSpec` carries the `PartDef`s and `Material`s its instances use. A project that is opened (a file someone
shared, an old file, a file written by a tool that left a definition out) can name a part or a material the project
does not carry. That used to make the whole file unopenable. The file is the user's work, so it now opens, and an
instance whose definition is missing stays as a **placeholder**: the instance exactly as it was stored (id, part id,
parameter values, pose, material id) with the joints, actuators and schedule entries that refer to it. A placeholder
is not a new kind of record and has no field of its own: it is an `Instance` whose `part` (or `material`) is not
among the project's definitions, so a save and an open give it back unchanged and the file format does not change
(`projectfile.py`). It has no mass, no inertia, no shape and no collision geometry, and none is made up: the
placement checks (`validator.py`) skip it like a part without a shape, and the mass and geometry code takes a
`PartDef`, which a placeholder does not have.

This module is the data of the rule (`docs/architecture/missing-definitions.md`):

- `missing_definitions(project)`: the definitions that are missing, each with the instances that use it.
- `catalog_differences(project, catalog)`: the definitions the project carries whose id is in a catalog with another
  definition hash ("카탈로그와 다름"). The project's own definition is the one in use; a catalog is never swapped in.
  `material_catalog_hashes()` is the material catalog (B-07) in that form, `kinetra_engine.parts.library_hashes()` the
  part library.

- `open_report(project, catalog)`: both findings of an opened project in one value (`OpenReport`).

Around it: `commands.py` (an edit never creates a placeholder; `relink_instance`, `remove_instance` and `add_part_def`
are the ways out, all commands), `validator.py` (`require_complete`, the gate of compile, run, verdict and Halo
export, which raises `ProjectIncomplete` with the ids of what is missing; and the placement checks skip a
placeholder).

Not here: fetching a missing definition from anywhere, plugin or mod folders, other products' file formats (all out
of scope), the screen of a placeholder (C-07).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .canonical import definition_hash
from .conventions import ID_PATTERN
from .material_catalog import load_material_catalog
from .project import Project

DefinitionCatalog = Mapping[tuple[str, str], str]
"""`(kind, id)` -> definition hash (`canonical.definition_hash`) of what a catalog holds. `kind` is `"material"` or
`"part"`."""


class MissingDefinition(BaseModel):
    """A definition the project does not carry, and the instances that use it (in project order)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["material", "part"]
    id: str = Field(pattern=ID_PATTERN)
    instances: tuple[str, ...] = Field(min_length=1)


class CatalogDifference(BaseModel):
    """A definition the project carries that differs from the catalog's definition with the same id. The project's
    one is used."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["material", "part"]
    id: str = Field(pattern=ID_PATTERN)
    project_hash: str
    catalog_hash: str

    @property
    def message(self) -> str:
        return (
            f"카탈로그와 다름: {self.kind} {self.id!r} in this project hashes to {self.project_hash}, the catalog's "
            f"{self.id!r} to {self.catalog_hash}. The definition the project carries is used."
        )


class BlockedOperation(StrEnum):
    """What a project with a missing definition cannot do."""

    COMPILE = "compile"
    RUN = "run"
    VERDICT = "verdict"
    EXPORT_HALO = "export_halo"


def missing_users(project: Project) -> frozenset[tuple[str, str, str]]:
    """`(kind, definition id, instance id)` for every instance that names a definition the project does not carry."""
    d = project.design
    parts = {p.id for p in d.parts}
    materials = {m.id for m in d.materials}
    out = set()
    for inst in d.instances:
        if inst.part not in parts:
            out.add(("part", inst.part, inst.id))
        if inst.material is not None and inst.material not in materials:
            out.add(("material", inst.material, inst.id))
    return frozenset(out)


def missing_definitions(project: Project) -> tuple[MissingDefinition, ...]:
    """The part and material definitions that instances name and the project does not carry: parts first, then
    materials, each in the order of its first user. Empty when the project is complete."""
    d = project.design
    parts = {p.id for p in d.parts}
    materials = {m.id for m in d.materials}
    users: dict[tuple[str, str], list[str]] = {}
    for inst in d.instances:
        if inst.part not in parts:
            users.setdefault(("part", inst.part), []).append(inst.id)
    for inst in d.instances:
        if inst.material is not None and inst.material not in materials:
            users.setdefault(("material", inst.material), []).append(inst.id)
    return tuple(MissingDefinition(kind=k, id=i, instances=tuple(v)) for (k, i), v in users.items())  # type: ignore[arg-type]


def material_catalog_hashes() -> DefinitionCatalog:
    """The material catalog (`load_material_catalog`, B-07) as definition hashes."""
    return {("material", e.material.id): definition_hash(e.material) for e in load_material_catalog().entries}


def catalog_differences(project: Project, catalog: DefinitionCatalog) -> tuple[CatalogDifference, ...]:
    """The definitions the project carries (materials, then parts, in project order) whose id is in `catalog` with a
    different definition hash. A definition the catalog does not have is the user's own and is not a difference. A
    definition the project does not carry is not listed here (`missing_definitions`)."""
    out = []
    d = project.design
    for kind, items in (("material", d.materials), ("part", d.parts)):
        for item in items:
            want = catalog.get((kind, item.id))
            have = definition_hash(item)
            if want is not None and want != have:
                out.append(CatalogDifference(kind=kind, id=item.id, project_hash=have, catalog_hash=want))  # type: ignore[arg-type]
    return tuple(out)


class OpenReport(BaseModel):
    """What to tell the user after a project is opened: what is missing and what differs from the catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    missing: tuple[MissingDefinition, ...] = ()
    differs_from_catalog: tuple[CatalogDifference, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing


def open_report(project: Project, catalog: DefinitionCatalog | None = None) -> OpenReport:
    """The missing definitions of `project` and its differences from `catalog` (default: the material catalog)."""
    return OpenReport(
        missing=missing_definitions(project),
        differs_from_catalog=catalog_differences(project, material_catalog_hashes() if catalog is None else catalog),
    )
