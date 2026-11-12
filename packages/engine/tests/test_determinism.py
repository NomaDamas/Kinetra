"""X-02d: the trajectory hash of a run, its platform tag and the comparison of two records (`engine.md` 5.4, H1 and H2).

    uv run pytest packages/engine -q -k determinism

Two projects drive the run through every force path the core has today: the 37D gearmotor rig with its battery
(`test_actuator.motor_rig`, X-01b: the motor's torque from the schedule, the battery drained) and a tank on a plate with
one thruster off the axis (`test_thrust.on_plate`, X-01c: thrust, propellant drawn, the mass falling, the body turning).
Their schedules are declared by this test. What is asserted is the observed range of H1: the same project, seed and
inputs give one hash on this build and this machine. That an equal tag gives an equal hash elsewhere is #432's.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from pydantic import ValidationError
from test_actuator import motor_rig
from test_thrust import entry, on_plate

from kinetra_core import (
    PlatformTag,
    Project,
    RunCompleted,
    TrajectoryComparison,
    TrajectoryEvidence,
    UntaggedTrajectory,
    check_run,
    compare_trajectories,
    project_hash,
    trajectory_evidence,
)
from kinetra_engine.run import PreviewRun

SRC = {"ref": "X-02d test fixture: value chosen by the test", "locator": "test_determinism.py"}
REPEATS = 10  # the issue's DoD
SEED = 7
DURATION_S = 0.2


def motor(command=1.0):
    """The motor rig with battery `b1`; actuator `drive` at `command` over [0, 0.1) s, then nothing."""
    data = motor_rig(supply=True).model_dump(mode="json")
    data["design"]["schedule"] = {"entries": [{"type": "actuate", "id": "spin", "actuator": "drive", "start": 0.0, "end": 0.1,
                                               "command": command, "badge": "declared", "source": SRC}]}
    return Project.model_validate(data)


def jet(command=1.0):
    """The tank on the plate with thruster `ja` under its +x end: the thrust lifts and turns the body."""
    return on_plate([("ja", "under-a")], [{"id": "main", "kind": "thruster", "instance": "ja", "supply": "tank"}],
                    [entry("burn", "main", 0.0, 0.15, command)])


PROJECTS = {"motor": motor, "thruster": jet}


def record(project, run_id="run"):
    """Run `project` to the end: the `run_started` and the trajectory evidence of its `run_ended`."""
    run = PreviewRun(project, run_id=run_id, project_id="p", revision=0, duration_s=DURATION_S, seed=SEED)
    *frames, ended = list(run)
    check_run(run.started, frames, ended)  # includes: the evidence is under the run's own platform tag
    assert isinstance(ended.end, RunCompleted)
    return run.started, ended.end.trajectory


@pytest.mark.parametrize("name", PROJECTS)
def test_determinism_ten_runs_of_one_project_seed_and_inputs_give_one_hash(name):
    """10 runs of the same project, seed and schedule in this process: one hash, one tag, each pair `match`."""
    project = PROJECTS[name]()
    records = [record(project, run_id=f"run-{i}")[1] for i in range(REPEATS)]
    assert len({r.hash for r in records}) == 1
    assert len({r.platform.model_dump_json() for r in records}) == 1
    assert all(compare_trajectories(records[0], r) is TrajectoryComparison.MATCH for r in records[1:])


def test_determinism_a_fresh_process_gives_the_same_hash(tmp_path):
    """The record of a run in a new Python process, read back from its `run_ended` JSON, matches this process's run: the
    hash depends on the project, seed and inputs, not on what the process did before."""
    project = jet()
    path = tmp_path / "project.json"
    path.write_text(project.model_dump_json(), encoding="utf-8")
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from kinetra_core import Project\n"
        "from kinetra_engine.run import PreviewRun\n"
        "project = Project.model_validate_json(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        f"run = PreviewRun(project, run_id='fresh', project_id='p', revision=0, duration_s={DURATION_S!r}, seed={SEED!r})\n"
        "print(list(run)[-1].model_dump_json())\n"
    )
    out = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, check=True).stdout
    fresh = json.loads(out.strip().splitlines()[-1])["end"]["trajectory"]
    assert compare_trajectories(record(project)[1], fresh) is TrajectoryComparison.MATCH


def test_determinism_the_same_project_in_another_document_order_gives_the_same_hash():
    """Same project: the instances, joints and parts listed in reverse are the same project (equal `project_hash`), and
    the compiler reads it in one order (`canonical_order`, #511), so the trajectory hash is the same."""
    project = motor()
    data = project.model_dump(mode="json")
    for key in ("instances", "joints", "parts", "materials"):
        data["design"][key].reverse()
    reordered = Project.model_validate(data)
    assert reordered.model_dump(mode="json") != project.model_dump(mode="json")
    assert project_hash(reordered) == project_hash(project)
    assert compare_trajectories(record(project)[1], record(reordered)[1]) is TrajectoryComparison.MATCH


@pytest.mark.parametrize("name", PROJECTS)
def test_determinism_another_input_under_the_same_tag_is_a_mismatch(name):
    """Half the command: the same tag (the inputs are not a tag component) and another hash, so `mismatch`."""
    full, half = record(PROJECTS[name](1.0))[1], record(PROJECTS[name](0.5))[1]
    assert full.platform == half.platform
    assert full.hash != half.hash
    assert compare_trajectories(full, half) is TrajectoryComparison.MISMATCH


@pytest.fixture(scope="module")
def evidence():
    return record(motor())[1]


def _changed(tag: PlatformTag, path: tuple[str, ...], value) -> PlatformTag:
    data = tag.model_dump(mode="json")
    node = data
    for key in path[:-1]:
        node = node[key]
    assert node[path[-1]] != value
    node[path[-1]] = value
    changed = PlatformTag.model_validate(data)
    assert changed != tag
    return changed


# One change per component of the eight (engine.md 5.4 table), each a value another machine or build could have; ② and
# ⑦ also by a single field inside them.
ONE_COMPONENT = {
    "os": (("os", "kernel_release"), "0.0.0-other"),
    "cpu.architecture": (("cpu", "architecture"), "other-arch"),
    "cpu.model": (("cpu", "model"), "another CPU model"),
    "image_digest": (("image_digest",), "sha256:" + "a" * 64),
    "engine": (("engine", "artifact_hash"), "sha256:" + "b" * 64),
    "runtime": (("runtime", "numpy"), "0.0.0"),
    "core_build": (("core_build", "commit"), "c" * 40),
    "compute.timestep_s": (("compute", "timestep_s"), 0.001),
    "compute.solver": (("compute", "solver", "iterations"), 1.0),
    "threads": (("threads", "solver"), 2),
}


@pytest.mark.parametrize("component", ONE_COMPONENT)
@pytest.mark.parametrize("same_hash", [True, False], ids=["same-hash", "other-hash"])
def test_determinism_tags_differing_in_one_component_are_not_comparable(evidence, component, same_hash):
    """Two records whose tags differ in one component only: `not_comparable`, whatever their hashes (they are not
    compared)."""
    path, value = ONE_COMPONENT[component]
    other = TrajectoryEvidence(hash=evidence.hash if same_hash else "sha256:" + "d" * 64,
                               platform=_changed(evidence.platform, path, value))
    assert compare_trajectories(evidence, other) is TrajectoryComparison.NOT_COMPARABLE
    assert compare_trajectories(other, evidence) is TrajectoryComparison.NOT_COMPARABLE


def test_determinism_a_record_without_its_tag_is_refused(evidence):
    """A hash without its platform tag is not evidence (H1): refused when read and when compared, never a result."""
    tagged = evidence.model_dump(mode="json")
    for untagged in ({"hash": evidence.hash}, {"hash": evidence.hash, "platform": None}):
        with pytest.raises(UntaggedTrajectory):
            trajectory_evidence(untagged)
        with pytest.raises(UntaggedTrajectory):
            compare_trajectories(tagged, untagged)
        with pytest.raises(UntaggedTrajectory):
            compare_trajectories(untagged, untagged)
    partial = json.loads(json.dumps(tagged))
    del partial["platform"]["threads"]  # a tag missing one of its eight components is not a tag
    with pytest.raises(ValidationError):
        compare_trajectories(tagged, partial)
    with pytest.raises(TypeError):
        compare_trajectories(evidence, evidence.hash)


def test_determinism_the_recorded_json_compares_as_the_record(evidence):
    """The trajectory of a `run_ended` written as JSON and read back is the same record: `match`."""
    written = json.loads(evidence.model_dump_json())
    assert trajectory_evidence(written) == evidence
    assert compare_trajectories(written, evidence) is TrajectoryComparison.MATCH


def test_determinism_results_have_the_three_names_of_h2():
    assert [(r.value, r.label_ko) for r in TrajectoryComparison] == [
        ("match", "일치"), ("mismatch", "불일치"), ("not_comparable", "비교 불가")]
