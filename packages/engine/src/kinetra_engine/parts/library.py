"""The part library as a definition catalog (C-06): `library/<id>.json` files, each a `PartDef`, as definition hashes.

`kinetra_core.catalog_differences(project, library_hashes())` says which parts a project carries differently from the
library ("카탈로그와 다름"); the project's own definition stays the one in use. The directory is the one
`docs/process/add-part.md` names; this module reads it and adds nothing to it.
"""

from __future__ import annotations

from pathlib import Path

from kinetra_core import PartDef, definition_hash

LIBRARY_DIR = Path(__file__).parent / "library"


def library_parts(directory: Path = LIBRARY_DIR) -> tuple[PartDef, ...]:
    """Every part definition in the library directory, in file name order."""
    return tuple(PartDef.model_validate_json(f.read_text(encoding="utf-8")) for f in sorted(directory.glob("*.json")))


def library_hashes(directory: Path = LIBRARY_DIR) -> dict[tuple[str, str], str]:
    """`("part", id)` -> definition hash of each library part, the form `kinetra_core.catalog_differences` takes."""
    return {("part", p.id): definition_hash(p) for p in library_parts(directory)}
