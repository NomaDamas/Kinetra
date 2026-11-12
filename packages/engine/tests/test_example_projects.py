"""Every committed example `Project` (`schemas/examples/Project.*.json`) compiles (`compile_project`, X-01), or is listed
below as not compilable with the compile error code it is refused with and why (#553).

The former schema-only four-wheel and rocket cars are real X-01 integration demos (#122): the actual MuJoCo loader's
total mass and initial world centre of mass must agree with explicit per-instance sums. Run this file with `-s` to show
the per-part and total acceptance logs. A listed refusal must keep exactly its stated code, so the list cannot go stale.
"""

from __future__ import annotations

import math
from pathlib import Path

import mujoco
import pytest
from example_project_fixtures import CAR, ROCKET, build_projects

from kinetra_core import Project, export_json
from kinetra_engine.compiler import CompileError, CompileErrorCode
from kinetra_engine.parts import assembly_mass
from kinetra_engine.run.preview import compile_project

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"
PROJECTS = sorted(p.name for p in EXAMPLES.glob("Project.*.json"))
INTEGRATION_DEMOS = (CAR, ROCKET)

# example file -> (the code it is refused with, why it is not meant to compile)
NOT_COMPILABLE: dict[str, tuple[CompileErrorCode, str]] = {
    "Project.empty.json": (CompileErrorCode.NO_INSTANCE, "the empty project: no instance, nothing to compile"),
}


def _load(name: str) -> Project:
    return Project.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))


def test_example_projects_the_list_names_only_committed_examples():
    assert "Project.drive-car.json" in PROJECTS
    assert set(INTEGRATION_DEMOS) <= set(PROJECTS) - set(NOT_COMPILABLE)
    assert set(NOT_COMPILABLE) <= set(PROJECTS)


@pytest.mark.parametrize("name", INTEGRATION_DEMOS)
def test_completed_example_projects_match_their_generator(name):
    assert (EXAMPLES / name).read_bytes() == export_json(build_projects()[name])


@pytest.mark.parametrize("name", [n for n in PROJECTS if n not in NOT_COMPILABLE])
def test_example_projects_compile(name):
    project = _load(name)
    model = compile_project(project)
    assert {i.instance for i in model.tree.instances} == {i.id for i in project.design.instances}


def _rotate(q, v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Independent quaternion rotation for the hand sum (the model's quaternion fields are x, y, z, w)."""
    norm = math.sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
    x, y, z, w = q.x / norm, q.y / norm, q.z / norm, q.w / norm
    vx, vy, vz = v
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


def _per_part_hand_sum(project: Project):
    rows = assembly_mass(project.design).instances
    parts = []
    for instance, row in zip(project.design.instances, rows):
        local = row.properties.center_of_mass
        rotated = _rotate(instance.pose.orientation, (local.x, local.y, local.z))
        p = instance.pose.position
        world = (p.x + rotated[0], p.y + rotated[1], p.z + rotated[2])
        parts.append((instance.id, row.mass, world))
    total = math.fsum(mass for _, mass, _ in parts)
    com = tuple(math.fsum(mass * world[k] for _, mass, world in parts) / total for k in range(3))
    return parts, total, com


@pytest.mark.parametrize("name", INTEGRATION_DEMOS)
def test_compile_demos_mujoco_mass_and_world_com_match_per_part_hand_sums(name):
    """X-01 epic acceptance: this is the real compile_project and MuJoCo XML loader, not a body-tree-only check."""
    project = _load(name)
    compiled = compile_project(project)
    data = mujoco.MjData(compiled.model)
    mujoco.mj_kinematics(compiled.model, data)

    parts, hand_mass, hand_com = _per_part_hand_sum(project)
    mj_mass = math.fsum(float(compiled.model.body_mass[b]) for b in range(1, compiled.model.nbody))
    mj_com = tuple(
        math.fsum(float(compiled.model.body_mass[b]) * float(data.xipos[b, k]) for b in range(1, compiled.model.nbody)) / mj_mass
        for k in range(3)
    )

    assert mj_mass == pytest.approx(hand_mass, rel=1e-12, abs=1e-12)
    assert mj_com == pytest.approx(hand_com, rel=1e-12, abs=1e-12)
    print(f"X-01 {name}: {len(parts)} parts")
    for instance, mass, world in parts:
        print(f"  part {instance}: mass_kg={mass:.17g} world_com_m={[round(v, 17) for v in world]}")
    print(f"  hand_sum total_mass_kg={hand_mass:.17g} world_com_m={list(hand_com)}")
    print(f"  mujoco   total_mass_kg={mj_mass:.17g} world_com_m={list(mj_com)}")


@pytest.mark.parametrize("name", sorted(NOT_COMPILABLE))
def test_example_projects_not_compilable_are_refused_for_their_stated_reason(name):
    code, why = NOT_COMPILABLE[name]
    assert why
    with pytest.raises(CompileError) as e:
        compile_project(_load(name))
    assert e.value.code is code
