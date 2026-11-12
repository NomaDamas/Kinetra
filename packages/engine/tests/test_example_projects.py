"""Every committed example `Project` (`schemas/examples/Project.*.json`) compiles (`compile_project`, X-01), or is listed
below as not compilable with the compile error code it is refused with and why (#553).

A listed example must still be refused with exactly that code, so the list cannot go stale: an example that starts to
compile, or fails for another reason, fails this test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kinetra_core import Project
from kinetra_engine.compiler import CompileError, CompileErrorCode
from kinetra_engine.run.preview import compile_project

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"
PROJECTS = sorted(p.name for p in EXAMPLES.glob("Project.*.json"))

# example file -> (the code it is refused with, why it is not meant to compile)
NOT_COMPILABLE: dict[str, tuple[CompileErrorCode, str]] = {
    "Project.empty.json": (CompileErrorCode.NO_INSTANCE, "the empty project: no instance, nothing to compile"),
    "Project.four-wheel-car.json": (
        CompileErrorCode.PART,
        "C-01 data-model example: its parts (from DesignSpec.four-wheel-car) carry no shape recipe, so there is no geometry",
    ),
    "Project.rocket-car-skeleton.json": (
        CompileErrorCode.PART,
        "C-01 data-model skeleton: its parts carry no shape recipe, so there is no geometry",
    ),
}


def _load(name: str) -> Project:
    return Project.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))


def test_example_projects_the_list_names_only_committed_examples():
    assert "Project.drive-car.json" in PROJECTS
    assert set(NOT_COMPILABLE) <= set(PROJECTS)


@pytest.mark.parametrize("name", [n for n in PROJECTS if n not in NOT_COMPILABLE])
def test_example_projects_compile(name):
    model = compile_project(_load(name))
    assert {i.instance for i in model.tree.instances} == {i.id for i in _load(name).design.instances}


@pytest.mark.parametrize("name", sorted(NOT_COMPILABLE))
def test_example_projects_not_compilable_are_refused_for_their_stated_reason(name):
    code, why = NOT_COMPILABLE[name]
    assert why
    with pytest.raises(CompileError) as e:
        compile_project(_load(name))
    assert e.value.code is code
