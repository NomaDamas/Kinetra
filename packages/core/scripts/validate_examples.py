"""Validate every example project under `schemas/examples/` (C-01 epic integration, #60).

    uv run python packages/core/scripts/validate_examples.py            # all of schemas/examples/*.json
    uv run python packages/core/scripts/validate_examples.py FILE...    # only these files

An example is `<Name>.<description>.json` where `<Name>` is an exported `kinetra_core` model. Each example must pass
BOTH validators, because they are two independent implementations of the same contract and a drift between them is a
bug in one of them:

  1. the JSON Schema `schemas/<Name>.schema.json` (draft 2020-12, `jsonschema`), which is what a TypeScript or any
     other client reads, and
  2. the Pydantic model `kinetra_core.<Name>.model_validate`, which also carries the cross checks a schema cannot say
     (closed references, unit quaternions, placeholder sources, licence expressions).

A `Project` example is also checked against the planet data: its `world.planet` must be one of `data/bodies`
(`check_world_references`; the model does not look at the data, see `project.py`).

The set of examples that the epic requires (a four-wheel car, a rocket-car skeleton with a thruster, an empty
project) is `REQUIRED`; deleting one fails this script. Exit code 0 when every example passes, 1 otherwise; every
problem is printed with the file name.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

import kinetra_core
from kinetra_core import ActuatorKind, Project, check_world_references, load_bodies

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "schemas"
EXAMPLES = SCHEMAS / "examples"

# C-01 DoD: "예시 프로젝트 3개(4륜차, 로켓 자동차 뼈대, 빈 프로젝트)".
REQUIRED = (
    "Project.four-wheel-car.json",
    "Project.rocket-car-skeleton.json",
    "Project.empty.json",
)


def model_name(path: Path) -> str:
    return path.name.split(".")[0]


def validate_file(path: Path) -> list[str]:
    """Every problem with one example, empty when it is valid under both validators."""
    name = model_name(path)
    model = getattr(kinetra_core, name, None)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        return [f"{path.name}: {name!r} is not an exported kinetra_core model (file name is <Model>.<description>.json)"]
    schema_file = SCHEMAS / f"{name}.schema.json"
    if not schema_file.is_file():
        return [f"{path.name}: {schema_file.relative_to(ROOT)} does not exist (run export_schemas.py)"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"{path.name}: not JSON: {e}"]

    problems: list[str] = []
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    for err in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        problems.append(f"{path.name}: JSON Schema: {where}: {err.message}")
    try:
        validated = model.model_validate(data)
    except (ValidationError, ValueError) as e:
        problems.append(f"{path.name}: {name} model: {e}")
        return problems
    if isinstance(validated, Project):
        try:
            check_world_references(
                validated.world,
                planets=load_bodies().keys(),
                materials=(m.id for m in validated.design.materials),
            )
        except ValueError as e:
            problems.append(f"{path.name}: planet data: {e}")
    return problems


def check_required(files: list[Path]) -> list[str]:
    have = {p.name for p in files}
    return [f"{name}: required example is missing from {EXAMPLES.relative_to(ROOT)}" for name in REQUIRED if name not in have]


def check_rocket_car_has_a_thruster(files: list[Path]) -> list[str]:
    """The rocket-car skeleton exists to show a thruster actuator (C-01b): it must have one, scheduled."""
    path = next((p for p in files if p.name == "Project.rocket-car-skeleton.json"), None)
    if path is None:
        return []
    try:
        project = Project.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, ValueError, json.JSONDecodeError):
        return []  # reported by validate_file
    thrusters = {a.id for a in project.design.actuators if a.kind == ActuatorKind.THRUSTER}
    scheduled = {e.actuator for e in project.design.schedule.entries}
    if not thrusters:
        return [f"{path.name}: has no thruster actuator"]
    if not thrusters & scheduled:
        return [f"{path.name}: no thruster has a schedule entry"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help="example files (default: every schemas/examples/*.json)")
    args = parser.parse_args(argv)

    files = sorted(args.files) if args.files else sorted(EXAMPLES.glob("*.json"))
    problems: list[str] = []
    if not args.files:
        problems += check_required(files)
        if not files:
            problems.append(f"no examples under {EXAMPLES}")
    for path in files:
        problems += validate_file(path)
    if not args.files:
        problems += check_rocket_car_has_a_thruster(files)

    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s) in {len(files)} example(s)", file=sys.stderr)
        return 1
    print(f"ok: {len(files)} example(s) pass the JSON Schema and the model: " + ", ".join(p.name for p in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
