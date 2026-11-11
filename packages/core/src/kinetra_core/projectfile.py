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
  `ensure_ascii` off, one trailing newline, Python's shortest round-trip number text; `-0.0` is the one value whose
  text differs between two projects that compare equal, and it round-trips), and `open` then `save` gives back the
  bytes that were saved. A file written by another program is read, not preserved byte for byte: its first save
  through here is normalised, and from then on it is stable.
- `save_project` replaces the file whole or not at all against a failed write or an interrupted process: it
  writes a new file beside the real target (a symbolic link at `path` is followed, so the file it points to is the
  one updated and the link stays), under a random name created exclusively (`O_EXCL`, so two saves of one path
  never share a temporary file and a link planted at the name is never followed), copies the target's permission
  bits, flushes it to the device (`fsync`; on macOS `F_FULLFSYNC`, which is what asks the drive to empty its cache)
  and renames it over the target (`os.replace`). Two saves of the same path at once each write a whole file and
  the last rename wins; neither can produce a mix. Not promised: that the directory entry survives a power cut
  before the OS writes it (the directory is not synced), and that Windows can replace a file another process holds
  open (it fails, and the old file stays).
- `export_json` is the same `Project` without the envelope: what `schemas/Project.schema.json` describes, for tools
  that want the document and not the file. It validates against that schema and opens with
  `Project.model_validate_json`.

Duplicate keys and `NaN`/`Infinity` are refused when reading (JSON text that two readers would read differently has
no one meaning to hash), and so is JSON nested too deeply for the reader to hold (`not_json`).

Decisions:

- The edit history (C-02b) is not saved. A stored inverse carries absolute list positions and is valid only for the
  state it was computed against, so a history without exactly its project is worse than none. A reopened project
  starts with an empty `History`.
- No revision number, issuer or timestamp: a saved file is a document, not an event (C-05a keeps revisions;
  `client-adapter.md` F2 gives wall-clock time no meaning).
- The file `version` is the version of the envelope, of the canonical rules AND of the model: changing any of the
  three bumps it. That includes a model default (the hash leaves out a field that holds its default, so a changed
  default changes what a file means and what it hashes to), a field added to a model, and the order table. There is
  one version, 1. An older reader refuses a newer file (`unsupported_version`); a newer reader keeps the rules of
  every version it still opens: a v1 file is checked against the v1 rules and then migrated, which this module will
  carry when there is a version 2 (`test_save_open_reads_the_frozen_v1_file` holds a v1 file that is never
  regenerated).
- **Forward compatibility is not a thing in v1.** Every model is `extra="forbid"` and the writer writes every
  field (including `null` ones), so a file written by a build that added an optional field is refused by an older
  build as `invalid_project` ("Extra inputs are not permitted") even though its `version` is 1. This is decided,
  not overlooked: adding a field is a model change, so it bumps `version` (above), and a file with a version
  this reader does not know is refused by `version` first, with the right reason. `client-adapter.md` G5 (unknown
  optional fields are ignored) is a rule of the wire protocol, not of this file. C-06 (#455) changes `Project`
  validation to let a project carry missing definitions; it must keep this rule (no silently ignored fields) and
  carry the migration that its change of `Project` needs.

Not here: cloud storage and accounts (out of scope), missing definitions (C-06), copying an assembly between
projects (L-01b), publishing a bundle (H-03a).
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import stat
import sys
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
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise ProjectFileError(ProjectFileErrorCode.NOT_JSON, f"not a JSON document: {type(e).__name__}: {str(e)[:200]}") from None
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
    except (ValidationError, RecursionError) as e:
        if isinstance(e, RecursionError):
            raise ProjectFileError(ProjectFileErrorCode.NOT_JSON, "the document is nested too deeply") from None
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


def _flush_to_device(fd: int) -> None:
    """`fsync`; on macOS plain `fsync` leaves the data in the drive's cache and `F_FULLFSYNC` is what empties it."""
    if sys.platform == "darwin":
        import fcntl

        with contextlib.suppress(OSError):  # a file system that cannot do it (a network share) falls back to fsync
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return
    os.fsync(fd)


def _default_mode() -> int:
    """0666 minus the umask: what `open(path, "w")` would give a new file."""
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def save_project(project: Project, path: str | os.PathLike[str]) -> ProjectFile:
    """Write the project file to `path`, replacing it whole or not at all. Returns what was written."""
    target = Path(os.path.realpath(path))
    file = project_file(project)
    data = _dumps(file.model_dump(mode="json"))
    tmp = target.with_name(f".kinetra-{secrets.token_hex(8)}.tmp")
    # Created owner-only, so the data is never readable by more than the target allows at any moment; the target's
    # own permission bits (wider or equal) are applied only after the content is written, and a new file gets the
    # usual default (0666 minus the umask) the same way.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            _flush_to_device(out.fileno())
            try:
                mode = stat.S_IMODE(target.stat().st_mode)
            except FileNotFoundError:
                mode = _default_mode()
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return file


def open_project(path: str | os.PathLike[str]) -> ProjectFile:
    """Read and check the project file at `path` (`parse_project`). `OSError` if it cannot be read."""
    return parse_project(Path(path).read_bytes())
