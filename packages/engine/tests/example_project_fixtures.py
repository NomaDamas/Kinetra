"""Complete the two C-01 projects with geometry and the drive data needed by the X-01 compiler.

    uv run python packages/engine/tests/example_project_fixtures.py

The C-01 documents remain the source of the user-declared chassis, wheel diameter, poses, joints, schedules and 5 N
thruster rating. The wheel and motor use the shipped B-03 library definitions; the motor's shape is turned into the
example's local +Y shaft frame and gets an explicitly illustrative extension to its existing shaft snap. The rocket is
a small generic thrust source, not a propellant-system design. This script also refreshes the tracked ProjectFile
writer exemplar. It never touches the frozen v1 compatibility fixture.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from kinetra_core import Project, dump_project, export_json

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "schemas" / "examples"
LIBRARY = ROOT / "packages" / "engine" / "src" / "kinetra_engine" / "parts" / "library"
CAR = "Project.four-wheel-car.json"
ROCKET = "Project.rocket-car-skeleton.json"
PROJECT_FILE = "ProjectFile.four-wheel-car.json"
S = math.sqrt(0.5)
# Turn the library motor's local +Z shaft into this example's local +Y shaft.
MOTOR_SHAPE_Q = {"x": -S, "y": 0.0, "z": 0.0, "w": S}
# A generic thruster exhausts towards local -X, so its force on the rocket car is +X.
NOZZLE_Q = {"x": 0.0, "y": -S, "z": 0.0, "w": S}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _source(detail: str) -> dict:
    return {
        "ref": f"Kinetra schema example: illustrative {detail}, not a measured part",
        "declared_by": "kinetra-docs",
        "declared_at": "2026-11-11T00:00:00Z",
    }


def _quantity(value: float, unit: str, detail: str) -> dict:
    return {"value": value, "unit": unit, "badge": "declared", "source": _source(detail)}


def _expr(value: float) -> dict:
    return {"offset": value, "terms": []}


def _position(x: float, y: float, z: float) -> dict:
    return {"x": _expr(x), "y": _expr(y), "z": _expr(z)}


def _library(part_id: str) -> dict:
    return json.loads((LIBRARY / f"{part_id}.json").read_text(encoding="utf-8"))


def _chassis_shape() -> dict:
    return {
        "badge": "declared",
        "source": _source("0.12 m wide, 0.02 m thick box chassis; its length remains the existing length parameter"),
        "components": [
            {
                "id": "deck",
                "primitive": {
                    "kind": "box",
                    "size_x": {"offset": 0.0, "terms": [{"param": "length", "factor": 1.0}]},
                    "size_y": _expr(0.12),
                    "size_z": _expr(0.02),
                },
                "operation": "add",
                "position": _position(0.0, 0.0, 0.0),
                "orientation": IDENTITY,
            }
        ],
    }


def _wheel(old: dict) -> dict:
    """The real library wheel recipe and cited friction specs, with the example's declared diameter and hub interface."""
    wheel = _library("wheel")
    wheel["name"] = old["name"]
    library_width = next(p for p in wheel["parameters"] if p["name"] == "width")
    wheel["parameters"] = [copy.deepcopy(next(p for p in old["parameters"] if p["name"] == "diameter")), library_width]
    wheel["snap_points"] = copy.deepcopy(old["snap_points"])
    return wheel


def _negate(expr: dict) -> dict:
    return {
        "offset": -expr["offset"],
        "terms": [{"param": t["param"], "factor": -t["factor"]} for t in expr["terms"]],
    }


def _motor(old: dict) -> dict:
    """The cited 37D motor, turned to the C-01 shaft frame and extended to the existing 30 mm shaft snap.

    The extension is a fixture choice, so the combined shape is an estimate rather than a claim that the datasheet
    dimensioned that extension. The motor's mass, electrical specs and torque-speed curve remain the cited library data.
    """
    motor = _library("motor-37d-12v-50-1")
    motor["id"] = old["id"]
    motor["name"] = old["name"]
    motor["snap_points"] = copy.deepcopy(old["snap_points"])
    shape = motor["shape"]
    original_source = shape["source"]
    for component in shape["components"]:
        p = component["position"]
        component["position"] = {"x": p["x"], "y": p["z"], "z": _negate(p["y"])}
        component["orientation"] = copy.deepcopy(MOTOR_SHAPE_Q)
    shape["components"].append(
        {
            "id": "shaft_extension",
            "primitive": {"kind": "cylinder", "radius": _expr(0.003), "length": _expr(0.008)},
            "operation": "add",
            "position": _position(0.0, 0.026, 0.0),
            "orientation": copy.deepcopy(MOTOR_SHAPE_Q),
        }
    )
    shape["badge"] = "estimate"
    shape["source"] = {
        **original_source,
        "ref": "Kinetra schema example: illustrative 8 mm shaft extension to the existing 30 mm snap; "
        + original_source["ref"],
    }
    return motor


def _generic_thruster(old: dict) -> dict:
    """A safe generic 5 N force source with an explicit mass flow and opening ramp; no chemistry or nozzle-flow model."""
    rocket = copy.deepcopy(old)
    rocket["role"] = "thruster"
    rated = next(s for s in old["specs"] if s["name"] == "rated_thrust")
    rocket["specs"] = [
        rated,
        {"name": "propellant_flow", **_quantity(0.01, "kg/s", "generic thruster propellant mass flow at rated thrust")},
    ]
    rocket["snap_points"] = [copy.deepcopy(s) for s in old["snap_points"] if s["id"] != "nozzle"] + [
        {
            "id": "nozzle",
            "kind": "nozzle",
            "accepts": [],
            "position": _position(-0.1, 0.0, 0.0),
            "orientation": copy.deepcopy(NOZZLE_Q),
            "badge": "declared",
            "source": _source("generic thruster nozzle at the aft face; +Z is exhaust towards local -X"),
        }
    ]
    rocket["shape"] = {
        "badge": "declared",
        "source": _source("generic 0.1 m long, 0.01 m radius cylindrical thruster envelope aft of its mount"),
        "components": [
            {
                "id": "body",
                "primitive": {"kind": "cylinder", "radius": _expr(0.01), "length": _expr(0.1)},
                "operation": "add",
                "position": _position(-0.05, 0.0, 0.0),
                "orientation": copy.deepcopy(NOZZLE_Q),
            }
        ],
    }
    rocket["curves"] = [
        {
            "name": "thrust",
            "curve": {
                "badge": "declared",
                "source": _source("generic 0.05 s linear opening to the existing user-declared 5 N steady thrust"),
                "x_unit": "s",
                "y_unit": "N",
                "points": [{"x": 0.0, "y": 0.0}, {"x": 0.05, "y": rated["value"]}],
            },
        }
    ]
    return rocket


def _complete(name: str) -> Project:
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    parts = {p["id"]: p for p in data["design"]["parts"]}
    parts["chassis"]["shape"] = _chassis_shape()
    parts["wheel"] = _wheel(parts["wheel"])
    if name == CAR:
        parts["motor"] = _motor(parts["motor"])
    else:
        parts["rocket"] = _generic_thruster(parts["rocket"])
    data["design"]["parts"] = [parts[p["id"]] for p in data["design"]["parts"]]
    for instance in data["design"]["instances"]:
        if instance["part"] in {"wheel", "rocket"}:
            instance["material"] = "example-material"
    return Project.model_validate(data)


def build_projects() -> dict[str, Project]:
    """The two completed projects, deterministically rebuilt from their declared documents and shipped part data."""
    return {name: _complete(name) for name in (CAR, ROCKET)}


def main() -> None:
    projects = build_projects()
    for name, project in projects.items():
        (EXAMPLES / name).write_bytes(export_json(project))
        print(f"wrote {EXAMPLES / name}")
    (EXAMPLES / PROJECT_FILE).write_bytes(dump_project(projects[CAR]))
    print(f"wrote {EXAMPLES / PROJECT_FILE}")


if __name__ == "__main__":
    main()
