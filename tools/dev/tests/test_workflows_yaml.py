"""Every workflow file under .github/workflows is valid YAML with the shape GitHub needs.

A step name like `Part glTF (B-01c: loader)` with an unquoted `: ` is a YAML mapping error: GitHub then reports "workflow
file issue", runs nothing, and the PR shows no checks (#492 hit exactly this). A real YAML parser (PyYAML, the same
dev dependency `scripts/gh` uses) catches it before the push.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[3] / ".github" / "workflows").glob("*.yml"))


def test_workflows_exist():
    assert WORKFLOWS, "no workflow files found"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml_with_jobs_and_named_steps(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name} is not a YAML mapping"
    assert doc.get("name"), f"{path.name}: no name"
    assert True in doc or "on" in doc, f"{path.name}: no trigger (PyYAML reads the key `on` as True)"
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path.name}: no jobs"
    for job_id, job in jobs.items():
        steps = job.get("steps")
        assert isinstance(steps, list) and steps, f"{path.name}: job {job_id} has no steps"
        for step in steps:
            assert isinstance(step, dict) and ("run" in step or "uses" in step), f"{path.name}: step without run/uses: {step}"
            assert isinstance(step.get("name", ""), str), f"{path.name}: step name is not text: {step.get('name')!r}"


def test_screenshots_workflow_runs_the_part_gltf_capture_and_uploads_its_output():
    doc = yaml.safe_load((WORKFLOWS[0].parent / "screenshots.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["screenshots"]["steps"]
    runs = [s.get("run", "") for s in steps]
    assert any("@kinetra/gltf-check capture" in r for r in runs)
    assert any("@kinetra/gltf-check test:browser" in r for r in runs)
    check = next(s["run"] for s in steps if "Artifact content check" in s.get("name", ""))
    assert "out/gltf-check/parts-gltf.png" in check and "out/gltf-check/result.json" in check
