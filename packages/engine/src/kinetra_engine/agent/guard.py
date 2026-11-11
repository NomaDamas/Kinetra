"""Permission guard and out-of-catalog labels of the agent path (G-04).

    guard_tool("set_gravity")                             # `forbidden` reason of a tool that is not one and names what an agent cannot change
    guard_arguments(tool, raw)                            # `forbidden` reasons of the parsed JSON arguments, empty when the call may go on
    out_of_catalog(project, library)                      # what the project uses beyond the catalogs, per instance
    introduced(before, after, library)                    # what one call adds to that

`EditTools.run` (G-02a) calls `guard_tool` for a name that is not a tool and `guard_arguments` on the parsed JSON before the
tool's schema, and puts what an accepted call introduces in `ToolResult.out_of_catalog`; `HubEditTools.call` publishes such
a call only with the user's confirmation of exactly those findings. The MCP server (G-08) goes through `HubEditTools`, so it
gets the same guard.

**The guard (DoD 1): the agent path cannot change a planet constant, the material catalog or a verdict.** The
guarantee is structural and is not here: no tool schema has such a field (`extra="forbid"`), no tool builds a command that
carries one (the closed `Command` union), and `validate_command` (C-02c) refuses a catalog material with other numbers for
every origin. What this module adds is that an attempt is named as one (`forbidden`, with why) instead of reading as a typo
(`invalid_command`), so the agent stops instead of rephrasing it. Refused here, before the schema:

| attempt | e.g. |
|---|---|
| a tool that is not one and names a planet constant, the catalog, a verdict, a material or a material property | `set_gravity`, `edit_material_catalog`, `set_verdict`, `write_p_success`, `set_density`, `add_material` |
| a key, at any depth, that is a planet constant (`PLANET_CONSTANT_NAMES`), a verdict field (`VERDICT_FIELD_NAMES`) or a material property (`density`, `yield_strength`, `elastic_modulus`, `friction`), that contains a multi-word one of those (`max_air_density`), or that has a word of `FORBIDDEN_WORDS` | `{"gravity": 3.7}`, `place.joint.P_Success`, `surfaceGravity`, `parameters.g` |
| a definition where an id belongs: `part` or `material` given as an object or a list | `{"part": {"id": "mine", "specs": [...]}}` |
| a key that speaks for the user: `origin`, `badge`, any key with the word confirm/confirmed/confirmation | `{"origin": "mouse"}`, `{"badge": "cite"}`, `{"user_confirmed": true}` |

Names are compared after camelCase is split and every run of non-alphanumerics becomes `_`, case folded
(`surfaceGravity` -> `surface_gravity`; its words are `surface`, `gravity`). A one-word name inside a longer key is not
matched (a tank's `propellant_density` parameter is not a material's `density`). No tool field and no library parameter
trips the guard (`test_guard_no_tool_field_or_library_parameter_trips_the_guard`); a part parameter named like a planet
constant (`g`) would, and is refused. Values are not read: a `source` sentence is the user's words.

**Out of the catalog (DoD 2): labelled, and the user confirms.** The catalogs are the ones that exist; nothing new is
defined here. For each instance of the project, and the definitions it uses:

| what | catalog | label |
|---|---|---|
| a thruster's `rated_thrust` outside the cited range (B-03c) | `parts/thruster_catalog.json` (`catalog_finding`) | `catalog_finding(part).label`: `카탈로그 밖 · 사용자 선언` for a declared 8 kN |
| a part or material the project carries that differs from the catalog's with the same id (C-06) | part library (`library_hashes` form), material catalog (`material_catalog_hashes`) | `카탈로그와 다름` (`CatalogDifference.message`) |
| each spec of a part that is not in the part library (a thruster's rated thrust is judged by its range instead) | part library | `카탈로그 밖 · <badge of the spec>` |
| each property of a material that is not in the material catalog | material catalog (B-07) | `카탈로그 밖 · <badge of the property>` |

A finding is keyed by the instance that uses the definition, so a call that adds a second instance of an out-of-catalog
part introduces findings again, and a call that edits an instance that already had them introduces none. Values outside
a part's parameter range are not labelled: the validator refuses them (`invalid_project`), which is the other answer DoD 2
allows.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from kinetra_core import (
    BADGE_LABEL_KO,
    PLANET_CONSTANT_NAMES,
    Badge,
    PartDef,
    PartRole,
    Project,
    Reason,
    ReasonCode,
    catalog_differences,
    definition_hash,
    load_material_catalog,
    material_catalog_hashes,
)
from kinetra_core.partdef import THRUSTER_RATED_THRUST
from kinetra_core.validator import FORBIDDEN_WORDS, VERDICT_FIELD_NAMES

from kinetra_engine.parts import catalog_finding
from kinetra_engine.parts.thruster import OUT_OF_CATALOG_KO

MATERIAL_PROPERTY_NAMES = frozenset({"density", "yield_strength", "elastic_modulus", "friction"})
"""The numbers of a `Material` (the material catalog's values, B-07)."""

SPEAKS_FOR_THE_USER = frozenset({"origin", "badge"})
"""Keys an agent call cannot carry: who sent it is the history's (C-02b), the badge of a number is the tool's."""

_CONFIRM_WORDS = frozenset({"confirm", "confirmed", "confirmation"})
_TOOL_WORDS = FORBIDDEN_WORDS | {"density", "yield", "modulus", "friction", "material", "materials"}
_KEY_NAMES = PLANET_CONSTANT_NAMES | VERDICT_FIELD_NAMES | MATERIAL_PROPERTY_NAMES
_DEFINED_IN_PLACE = ("part", "material")

CATALOG_DIFFERS_KO = "카탈로그와 다름"
"""The C-06 label of a definition the project carries that differs from the catalog's (`CatalogDifference.message`)."""


def _normal(key: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", snake.casefold()).strip("_")


def _names_one(name: str, words: frozenset[str], *, whole_words: bool) -> bool:
    """Whether the normalised `name` is one of `_KEY_NAMES`, has a word of `words`, or has a run of words that is one of the
    multi-word `_KEY_NAMES` (`write_p_success`, `max_air_density`). With `whole_words` (tool names) a one-word name counts
    too (`set_g`, `set_density`); for keys it does not, so a tank's `propellant_density` is not a material's `density`."""
    padded = f"_{name}_"
    names = _KEY_NAMES if whole_words else {k for k in _KEY_NAMES if "_" in k}
    return name in _KEY_NAMES or bool(set(name.split("_")) & words) or any(f"_{k}_" in padded for k in names)


def _forbidden(message: str) -> Reason:
    return Reason(code=ReasonCode.FORBIDDEN, message=message)


def _key_reason(tool: str, path: str, key: str, value: Any) -> Reason | None:
    name = _normal(key)
    words = set(name.split("_"))
    if _names_one(name, FORBIDDEN_WORDS, whole_words=False):
        return _forbidden(
            f"{tool}: {path}: an agent cannot change a planet constant, the material catalog or a verdict. Planets are "
            "chosen by id and their constants are read from data/bodies; materials come from the catalog as they are or "
            "are the user's own; a verdict comes from the core's simulation and Monte Carlo"
        )
    if name in SPEAKS_FOR_THE_USER or words & _CONFIRM_WORDS:
        return _forbidden(
            f"{tool}: {path}: an agent call cannot say who sent it, which badge its numbers have or that the user "
            "confirmed it. The tool marks what the call states as declared; the user confirms out-of-catalog values"
        )
    if name in _DEFINED_IN_PLACE and isinstance(value, (Mapping, list, tuple)):
        return _forbidden(
            f"{tool}: {path}: an agent cannot define a {name}; it names one by id, from the project, the part library "
            "or the material catalog"
        )
    return None


def _walk(tool: str, data: Any, where: str, out: list[Reason]) -> None:
    if isinstance(data, Mapping):
        for key, value in data.items():
            path = f"{where}.{key}" if where else str(key)
            reason = _key_reason(tool, path, str(key), value)
            if reason is not None:
                out.append(reason)
            _walk(tool, value, path, out)
    elif isinstance(data, (list, tuple)):
        for n, item in enumerate(data):
            _walk(tool, item, f"{where}[{n}]", out)


def guard_tool(tool: str) -> tuple[Reason, ...]:
    """The `forbidden` reason of a tool name that is not a tool and names a planet constant, the catalog, a verdict, a
    material or a material property (`set_gravity`, `edit_material_catalog`, `set_verdict`); empty otherwise. Only called
    for a name that is not in `TOOL_NAMES`."""
    if _names_one(_normal(tool), _TOOL_WORDS, whole_words=True):
        return (
            _forbidden(
                f"there is no tool {tool!r}, and there never will be: an agent cannot change a planet constant, the "
                "material catalog or a verdict"
            ),
        )
    return ()


def guard_arguments(tool: str, arguments: Any) -> tuple[Reason, ...]:
    """The `forbidden` reasons of the parsed JSON arguments of one call, one per key; empty when the call may go on to the
    tool's schema."""
    out: list[Reason] = []
    _walk(tool, arguments, "", out)
    return tuple(out)


# --- out of the catalog ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutOfCatalog:
    """A value of a definition an instance uses that the catalogs do not cover, with the label its value badge shows.

    `kind`: `thrust` (B-03c range), `differs` (C-06 difference from the catalog's definition with the same id), `spec`
    (a spec of a part that is not in the part library), `material` (a property of a material that is not in the material
    catalog). `definition` is the part or material id, `field` the spec or property name (`""` for `differs`)."""

    kind: Literal["thrust", "differs", "spec", "material"]
    instance: str
    definition: str
    field: str
    label: str
    message: str

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "instance": self.instance,
            "definition": self.definition,
            "field": self.field,
            "label": self.label,
            "message": self.message,
        }


def _label(badge: Badge) -> str:
    return f"{OUT_OF_CATALOG_KO} · {BADGE_LABEL_KO[badge]}"


def _part_findings(inst: str, part: PartDef, in_library: bool) -> list[OutOfCatalog]:
    out = []
    if part.role is PartRole.THRUSTER:
        f = catalog_finding(part)
        if not f.in_catalog:
            out.append(
                OutOfCatalog(
                    "thrust",
                    inst,
                    part.id,
                    THRUSTER_RATED_THRUST,
                    f.label,
                    f"{f.label}: rated thrust {f.value:g} {f.unit.value} of part {part.id!r} is outside the cited "
                    f"catalog range {f.catalog_min:g}..{f.catalog_max:g} {f.unit.value}; the verdict is only as good as "
                    "this value",
                )
            )
    if in_library:
        return out
    for s in part.specs:
        if part.role is PartRole.THRUSTER and s.name == THRUSTER_RATED_THRUST:
            continue
        label = _label(s.badge)
        out.append(
            OutOfCatalog(
                "spec",
                inst,
                part.id,
                s.name,
                label,
                f"{label}: {s.name} = {s.value:g} {s.unit.value} of part {part.id!r}, which is not in the part library",
            )
        )
    return out


def _material_findings(inst: str, material) -> list[OutOfCatalog]:
    out = []
    for name in sorted(MATERIAL_PROPERTY_NAMES):
        q = getattr(material, name)
        label = _label(q.badge)
        out.append(
            OutOfCatalog(
                "material",
                inst,
                material.id,
                name,
                label,
                f"{label}: {name} = {q.value:g} {q.unit.value} of material {material.id!r}, which is not in the material catalog",
            )
        )
    return out


def out_of_catalog(project: Project, library: Mapping[str, PartDef]) -> frozenset[OutOfCatalog]:
    """Every out-of-catalog finding of `project` against the part library `library` and the material catalog, per instance
    (see the module docstring). Placeholders (C-06) have no definition and give none."""
    d = project.design
    parts = {p.id: p for p in d.parts}
    materials = {m.id: m for m in d.materials}
    catalog = {("part", i): definition_hash(p) for i, p in library.items()} | dict(material_catalog_hashes())
    differs = {(c.kind, c.id): c for c in catalog_differences(project, catalog)}
    material_ids = {e.material.id for e in load_material_catalog().entries}
    out: set[OutOfCatalog] = set()
    for inst in d.instances:
        part = parts.get(inst.part)
        if part is not None:
            out.update(_part_findings(inst.id, part, in_library=inst.part in library))
            if (c := differs.get(("part", part.id))) is not None:
                out.add(OutOfCatalog("differs", inst.id, part.id, "", CATALOG_DIFFERS_KO, c.message))
        material = materials.get(inst.material) if inst.material is not None else None
        if material is not None:
            if (c := differs.get(("material", material.id))) is not None:
                out.add(OutOfCatalog("differs", inst.id, material.id, "", CATALOG_DIFFERS_KO, c.message))
            elif material.id not in material_ids:
                out.update(_material_findings(inst.id, material))
    return frozenset(out)


def introduced(before: Project, after: Project, library: Mapping[str, PartDef]) -> tuple[OutOfCatalog, ...]:
    """The findings `after` has and `before` did not, in a stable order (instance, definition, field)."""
    new = out_of_catalog(after, library) - out_of_catalog(before, library)
    return tuple(sorted(new, key=lambda f: (f.instance, f.definition, f.field, f.kind)))
