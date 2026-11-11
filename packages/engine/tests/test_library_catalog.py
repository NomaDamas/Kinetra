"""C-06: the part library as a definition catalog for "카탈로그와 다름"."""

from __future__ import annotations

import json
from pathlib import Path

from kinetra_core import Project, catalog_differences, definition_hash, open_report
from kinetra_engine.parts import library_hashes, library_parts

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"


def test_library_hashes_one_entry_per_part_file():
    hashes = library_hashes()
    assert hashes and {k for k, _ in hashes} == {"part"}
    assert {i for _, i in hashes} == {p.id for p in library_parts()}
    assert all(h.startswith("sha256:") for h in hashes.values())


def test_library_a_project_part_equal_to_the_library_is_not_different_and_an_edited_one_is():
    wheel = next(p for p in library_parts() if p.id == "wheel")
    data = json.loads((EXAMPLES / "Project.empty.json").read_text(encoding="utf-8"))
    data["design"] = {"parts": [wheel.model_dump(mode="json")]}
    project = Project.model_validate(data)
    assert catalog_differences(project, library_hashes()) == ()

    edited = wheel.model_dump(mode="json")
    edited["name"] = "Wheel, edited"
    data["design"] = {"parts": [edited]}
    project = Project.model_validate(data)
    (diff,) = open_report(project, library_hashes()).differs_from_catalog
    assert (diff.kind, diff.id, diff.catalog_hash) == ("part", "wheel", definition_hash(wheel))
    assert diff.project_hash == definition_hash(project.design.parts[0]) != diff.catalog_hash
