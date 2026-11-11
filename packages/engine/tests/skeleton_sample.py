"""B-02 epic integration: the structural skeleton, a `Project` built from library parts (beam, plate, shell, payload, mount).

    uv run python packages/engine/tests/skeleton_sample.py     # rewrites the example, the glb per instance and the manifest

Writes (and `test_structural.py` checks they are current):

- `schemas/examples/Project.structural-skeleton.json`: the project.
- `packages/engine/tests/fixtures/skeleton/<instance>.glb`: the glb of each instance (its part, material and parameters).
- `packages/engine/tests/fixtures/skeleton/manifest.json`: per instance the part, material, pose, parameters and the mass
  `assembly_mass` computed, and the total. `tools/gltf-check` places each glb by its pose and prints these masses.

Every instance is placed by solving the joints (the world position of the parent's snap point minus the local position of the
child's snap point; every orientation is the identity), so no coordinate below is typed in twice. Dimensions are `사용자 선언`
choices of this example, not a real vehicle's; the two payload masses are declarations, not measurements.
"""

from __future__ import annotations

import json
from pathlib import Path

from kinetra_core import DesignSpec, PartDef, Project, export_json, load_material_catalog
from kinetra_engine.parts import assembly_mass, part_glb

ROOT = Path(__file__).resolve().parents[3]
LIBRARY = ROOT / "packages" / "engine" / "src" / "kinetra_engine" / "parts" / "library"
EXAMPLE = ROOT / "schemas" / "examples" / "Project.structural-skeleton.json"
FIXTURES = Path(__file__).parent / "fixtures" / "skeleton"
MANIFEST = FIXTURES / "manifest.json"
MATERIAL = "al6061-t6"

DECLARED_BY = "kinetra-b02-skeleton"
DECLARED_AT = "2026-11-12T00:00:00Z"
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _source(ref: str) -> dict:
    return {"ref": ref, "declared_by": DECLARED_BY, "declared_at": DECLARED_AT}


def _param(name: str, value: float, unit: str = "m") -> dict:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "badge": "declared",
        "source": _source(f"B-02 skeleton example: {name} chosen by the example, not a measured part"),
    }


# instance id -> (part id, material, parameters the instance sets). The rest are the part's defaults.
INSTANCES: dict[str, tuple[str, str | None, dict[str, tuple[float, str]]]] = {
    "keel-beam": ("beam", MATERIAL, {"length": (0.4, "m")}),
    "deck-plate": ("plate", MATERIAL, {"length": (0.5, "m"), "width": (0.3, "m")}),
    "body-shell": ("shell", MATERIAL, {}),
    "payload-main": ("payload", None, {"mass": (3.0, "kg")}),
    "payload-mount": ("payload-mount", MATERIAL, {}),
    "payload-sensor": ("payload", None, {"mass": (0.75, "kg"), "length": (0.1, "m"), "width": (0.07, "m"), "height": (0.05, "m")}),
    "boom-beam": ("beam", MATERIAL, {"length": (0.3, "m")}),
}

# (joint id, parent instance, parent snap, child instance, child snap): all fixed. The order is the placement order: a
# child's parent is placed first. `keel-beam` is the root and lies on the ground.
JOINTS = (
    ("keel-deck", "keel-beam", "top", "deck-plate", "bottom"),
    ("deck-shell", "deck-plate", "top", "body-shell", "underside"),
    ("shell-payload", "body-shell", "bed", "payload-main", "base"),
    ("payload-mount", "payload-main", "top", "payload-mount", "bottom"),
    ("mount-sensor", "payload-mount", "seat", "payload-sensor", "base"),
    ("deck-boom", "deck-plate", "edge-xp", "boom-beam", "end-a"),
)


def library_part(part_id: str) -> PartDef:
    return PartDef.model_validate_json((LIBRARY / f"{part_id}.json").read_text(encoding="utf-8"))


def local_snap(part: PartDef, values: dict[str, float], snap_id: str) -> tuple[float, float, float]:
    """A snap point's position in the part's own frame for the given parameter values (offset + sum factor x value)."""
    s = next(s for s in part.snap_points if s.id == snap_id)
    return tuple(a.offset + sum(t.factor * values[t.param] for t in a.terms) for a in (s.position.x, s.position.y, s.position.z))  # type: ignore[return-value]


def build_project() -> Project:
    parts = {pid: library_part(pid) for pid in dict.fromkeys(p for p, _, _ in INSTANCES.values())}
    values = {
        iid: {p.name: p.default.value for p in parts[pid].parameters} | {n: v for n, (v, _) in params.items()}
        for iid, (pid, _, params) in INSTANCES.items()
    }
    position = {"keel-beam": (0.0, 0.0, values["keel-beam"]["height"] / 2)}  # the root's bottom flange is on the ground
    for _, parent, parent_snap, child, child_snap in JOINTS:
        pa = local_snap(parts[INSTANCES[parent][0]], values[parent], parent_snap)
        pb = local_snap(parts[INSTANCES[child][0]], values[child], child_snap)
        base = position[parent]  # identity orientations: world = position + local
        position[child] = tuple(base[k] + pa[k] - pb[k] for k in range(3))
    instances = []
    for iid, (pid, material, params) in INSTANCES.items():
        x, y, z = position[iid]
        instances.append(
            {
                "id": iid,
                "part": pid,
                "material": material,
                "parameters": [_param(n, v, u) for n, (v, u) in params.items()],
                "pose": {
                    "position": {"x": x, "y": y, "z": z},
                    "orientation": IDENTITY,
                    "badge": "declared",
                    "source": _source("B-02 skeleton example: placed by solving the joints so that joined snap points meet"),
                },
            }
        )
    joints = [
        {"id": jid, "kind": "fixed", "a": {"instance": a, "snap_point": sa}, "b": {"instance": b, "snap_point": sb}}
        for jid, a, sa, b, sb in JOINTS
    ]
    return Project.model_validate(
        {
            "design": {
                "materials": [load_material_catalog().get(MATERIAL).material.model_dump(mode="json")],
                "parts": [p.model_dump(mode="json") for p in parts.values()],
                "instances": instances,
                "joints": joints,
            },
            "world": {"planet": "earth"},
        }
    )


def glb_name(instance_id: str) -> str:
    return f"{instance_id}.glb"


def instance_glb(design: DesignSpec, instance_id: str) -> bytes:
    inst = next(i for i in design.instances if i.id == instance_id)
    part = next(p for p in design.parts if p.id == inst.part)
    material = next((m for m in design.materials if m.id == inst.material), None)
    return part_glb(part, material, {p.name: p for p in inst.parameters})


def manifest(project: Project) -> dict:
    """What the browser page needs: no number in it is computed outside the engine (`assembly_mass`)."""
    design = project.design
    result = assembly_mass(design)
    rows = []
    for inst, row in zip(design.instances, result.instances):
        pos, q = inst.pose.position, inst.pose.orientation
        rows.append(
            {
                "id": inst.id,
                "part": inst.part,
                "material": inst.material,
                "glb": glb_name(inst.id),
                "mass_kg": row.mass,
                "mass_input_badges": [b.value for b in row.properties.derivation.input_badges],
                "pose": {"position": {"x": pos.x, "y": pos.y, "z": pos.z}, "orientation": {"x": q.x, "y": q.y, "z": q.z, "w": q.w}},
                "parameters": {p.name: {"value": p.value, "unit": p.unit.value} for p in inst.parameters},
            }
        )
    return {
        "project": EXAMPLE.name,
        "planet": project.world.planet,
        "instances": rows,
        "total_kg": result.total.value,
        "total_rule": "total = sum of the per-instance masses (math.fsum), nothing else: joints and poses add no mass",
        "input_badges": [b.value for b in result.input_badges],
    }


def main() -> None:
    project = build_project()
    EXAMPLE.write_bytes(export_json(project))
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for inst in project.design.instances:
        (FIXTURES / glb_name(inst.id)).write_bytes(instance_glb(project.design, inst.id))
    MANIFEST.write_text(json.dumps(manifest(project), indent=2) + "\n", encoding="utf-8")
    print("wrote", EXAMPLE, MANIFEST, "and", len(project.design.instances), "glb files")


if __name__ == "__main__":
    main()
