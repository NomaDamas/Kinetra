"""The project file (C-03): save a `Project` to a local file, open it again, and know it is the same one.

The file is one JSON document, UTF-8, `.kinetra.json` by convention (`PROJECT_FILE_SUFFIX`). `ProjectFile` is its
shape (`schemas/ProjectFile.schema.json`):

```
{"format": "kinetra-project", "version": 1,
 "project": { ...the Project, in the order the user has it... },
 "project_hash": "sha256:...",
 "definitions": [{"kind": "material", "id": "...", "hash": "sha256:..."}, {"kind": "part", ...}]}
```

- `project` keeps the document order of every collection (order is part of the value, `project-model.md`), so a
  saved project opens as an equal `Project` and the order a user arranged is not lost.
- `project_hash` is the hash of the whole project in canonical form (`canonical.py`), `definitions` the hash of
  each material and part definition the project carries, in the project's order (materials, then parts). The
  hashes do not depend on the order or on whitespace; they say "same thing". The plan puts the definitions in the
  project "with a definition hash" (5.3): C-06 compares a definition's hash with the catalog's to say "differs
  from the catalog" and to open a project whose definitions are missing.
- Opening checks the hashes against the project it read. A file that was edited by hand, cut off, or written by
  something that does not follow `canonical.py` is refused as `hash_mismatch` with what differs, never opened
  quietly. (A file written for a different `version` is refused before anything else is read.)
- Saving is deterministic: the same `Project` gives the same bytes (field order of the models, two-space indent,
  `ensure_ascii` off, one trailing newline, Python's shortest round-trip number text), and `open` then `save` gives
  back the bytes that were saved. A file written by another program is read, not preserved byte for byte: its
  first save through here is normalised, and from then on it is stable. `save_project` writes to a temporary file
  beside the target and renames it over it, so a crash or a full disk cannot leave half a project where a good
  one was.
- `export_json` is the same `Project` without the envelope: what `schemas/Project.schema.json` describes, for tools
  that want the document and not the file. It validates against that schema and opens with
  `Project.model_validate_json`.

Duplicate keys and `NaN`/`Infinity` are refused when reading (JSON text that two readers would read differently has
no one meaning to hash).

Decisions:

- The edit history (C-02b) is not saved. A stored inverse carries absolute list positions and is valid only for the
  state it was computed against, so a history without exactly its project is worse than none. A reopened project
  starts with an empty `History`.
- No revision number, issuer or timestamp: a saved file is a document, not an event (C-05a keeps revisions;
  `client-adapter.md` F2 gives wall-clock time no meaning).
- The file `version` is the version of the envelope AND of the canonical rules: changing either bumps it. There
  is one version, 1; an older reader must refuse a newer file and the opposite is a migration this module will
  carry when there is a version 2.

Not here: cloud storage and accounts (out of scope), missing definitions (C-06), copying an assembly between
projects (L-01b), publishing a bundle (H-03a).
"""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .canonical import CanonicalError, definition_hash, project_hash
from .conventions import ID_PATTERN
from .project import Project

FORMAT = "kinetra-project"
VERSION = 1
PROJECT_FILE_SUFFIX = ".kinetra.json"

_Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class DefinitionHash(BaseModel):
    """The hash of one definition the project carries (a `PartDef` or a `Material`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["material", "part"]
    id: str = Field(pattern=ID_PATTERN)
    hash: _Sha256


class ProjectFile(BaseModel):
    """What is in a project file. Building one with `project_file` gives hashes that match `project`; reading one
    with `parse_project` checks that they do."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["kinetra-project"]
    version: Literal[1]
    project: Project
    project_hash: _Sha256
    definitions: tuple[DefinitionHash, ...]


class ProjectFileErrorCode(StrEnum):
    NOT_JSON = "not_json"
    NOT_A_PROJECT_FILE = "not_a_project_file"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_PROJECT = "invalid_project"
    HASH_MISMATCH = "hash_mismatch"


class ProjectFileError(Exception):
    """The bytes are not a project file this reader can open. `code` says why, the message says where."""

    def __init__(self, code: ProjectFileErrorCode, message: str):
        self.code = code
        super().__init__(f"[{code.value}] {message}")


def project_file(project: Project) -> ProjectFile:
    d = project.design
    entries = (
        *(DefinitionHash(kind="material", id=m.id, hash=definition_hash(m)) for m in d.materials),
        *(DefinitionHash(kind="part", id=p.id, hash=definition_hash(p)) for p in d.parts),
    )
    return ProjectFile(format=FORMAT, version=VERSION, project=project, project_hash=project_hash(project), definitions=entries)


def _dumps(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def dump_project(project: Project) -> bytes:
    """The bytes of the project file. Same project, same bytes."""
    return _dumps(project_file(project).model_dump(mode="json"))


def export_json(project: Project) -> bytes:
    """The `Project` alone as JSON (no envelope, no hashes), in document order, formatted like the file."""
    return _dumps(project.model_dump(mode="json"))


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")


def _differences(file: ProjectFile) -> list[str]:
    expected = project_file(file.project)
    problems: list[str] = []
    if file.project_hash != expected.project_hash:
        problems.append(f"project_hash is {file.project_hash}, the project in the file hashes to {expected.project_hash}")
    want = {(e.kind, e.id): e.hash for e in expected.definitions}
    have = {(e.kind, e.id): e.hash for e in file.definitions}
    if len(have) != len(file.definitions):
        problems.append("definitions lists the same definition twice")
    for key in sorted(want.keys() - have.keys()):
        problems.append(f"definitions has no hash for {key[0]} {key[1]!r}")
    for key in sorted(have.keys() - want.keys()):
        problems.append(f"definitions has a hash for {key[0]} {key[1]!r}, which the project does not carry")
    for key in sorted(want.keys() & have.keys()):
        if want[key] != have[key]:
            problems.append(f"{key[0]} {key[1]!r}: file says {have[key]}, the definition in the file hashes to {want[key]}")
    return problems


def parse_project(data: bytes | str) -> ProjectFile:
    """Read a project file and check it. Raises `ProjectFileError`; the result's `project` is a valid `Project`
    whose hashes are the ones the file states."""
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        raw = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError) as e:
        raise ProjectFileError(ProjectFileErrorCode.NOT_JSON, f"not a JSON document: {e}") from None
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ProjectFileError(ProjectFileErrorCode.NOT_A_PROJECT_FILE, f"expected an object with \"format\": \"{FORMAT}\"")
    version = raw.get("version")
    if type(version) is not int or version != VERSION:
        raise ProjectFileError(
            ProjectFileErrorCode.UNSUPPORTED_VERSION,
            f"file version is {version!r}, this reader opens version {VERSION}",
        )
    try:
        file = ProjectFile.model_validate(raw)
    except ValidationError as e:
        project_invalid = any(err["loc"][:1] == ("project",) for err in e.errors())
        code = ProjectFileErrorCode.INVALID_PROJECT if project_invalid else ProjectFileErrorCode.NOT_A_PROJECT_FILE
        raise ProjectFileError(code, str(e)) from None
    try:
        problems = _differences(file)
    except CanonicalError as e:
        raise ProjectFileError(ProjectFileErrorCode.INVALID_PROJECT, f"the project has no canonical form: {e}") from None
    if problems:
        raise ProjectFileError(
            ProjectFileErrorCode.HASH_MISMATCH,
            "the file was changed after it was saved (or was not written by a conforming writer): " + "; ".join(problems),
        )
    return file


def save_project(project: Project, path: str | os.PathLike[str]) -> ProjectFile:
    """Write the project file to `path`, replacing it whole or not at all. Returns what was written."""
    target = Path(path)
    file = project_file(project)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as out:
            out.write(_dumps(file.model_dump(mode="json")))
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return file


def open_project(path: str | os.PathLike[str]) -> ProjectFile:
    """Read and check the project file at `path` (`parse_project`). `OSError` if it cannot be read."""
    return parse_project(Path(path).read_bytes())
