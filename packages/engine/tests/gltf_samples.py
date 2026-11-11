"""Sample parts of the B-01c tests, and the writer of the committed fixtures in `tests/fixtures/gltf/`.

    uv run python packages/engine/tests/gltf_samples.py     # rewrites the fixtures (test_gltf.py fails when they are stale)

The fixtures are what `tools/gltf-check` hands to the official Khronos validator and draws in a browser. Dimensions and
densities here are test declarations (`사용자 선언`), not real part data; the materials are catalog ids (B-07).
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest import mock

from kinetra_core import Material, PartDef, load_material_catalog
from kinetra_engine.parts import part_glb

FIXTURES = Path(__file__).parent / "fixtures" / "gltf"
SRC = {"ref": "B-01c test fixture: dimensions declared by the test", "locator": "gltf_samples.py"}
S2 = math.sqrt(0.5)
ROT_X90 = {"x": S2, "y": 0.0, "z": 0.0, "w": S2}


def q(value, unit="m"):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(offset=0.0, terms=()):
    return {"offset": offset, "terms": [{"param": p, "factor": f} for p, f in terms]}


def pos(x=0.0, y=0.0, z=0.0):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def box(id, sx, sy, sz, at=(0, 0, 0), op="add", quat=None):
    sizes = [s if isinstance(s, dict) else ax(s) for s in (sx, sy, sz)]
    return {
        "id": id,
        "operation": op,
        "primitive": {"kind": "box", "size_x": sizes[0], "size_y": sizes[1], "size_z": sizes[2]},
        "position": pos(*at),
        **({"orientation": quat} if quat else {}),
    }


def cyl(id, radius, length, at=(0, 0, 0), op="add", quat=None):
    return {
        "id": id,
        "operation": op,
        "primitive": {"kind": "cylinder", "radius": ax(radius), "length": ax(length)},
        "position": pos(*at),
        **({"orientation": quat} if quat else {}),
    }


def sphere(id, radius, at=(0, 0, 0), op="add"):
    return {"id": id, "operation": op, "primitive": {"kind": "sphere", "radius": ax(radius)}, "position": pos(*at)}


def width_param(default=0.1):
    return {"name": "width", "unit": "m", "default": q(default), "min": q(0.1), "max": q(0.2)}


def part(id, components, parameters=()):
    return PartDef.model_validate(
        {
            "id": id,
            "name": id,
            "parameters": list(parameters),
            "shape": {"badge": "declared", "source": SRC, "components": components},
        }
    )


def catalog_material(material_id: str) -> Material:
    return load_material_catalog().get(material_id).material


def user_material(material_id="user-grey") -> Material:
    """A declared material that is not in the catalog: the fallback look applies."""
    return Material.model_validate(
        {
            "id": material_id,
            "name": "User material",
            "density": q(1000.0, "kg/m^3"),
            "yield_strength": q(1.0e7, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"),
            "friction": q(0.5, "1"),
        }
    )


def mounting_plate() -> PartDef:
    """A plate with a blind bore (a void: not cut out of the drawing) and a boss; width follows a parameter."""
    return part(
        "mounting-plate",
        [
            box("plate", ax(0.0, [("width", 1.0)]), 0.2, 0.02, at=(0, 0, 0)),
            box("rib", 0.03, 0.2, 0.04, at=(0, 0, 0.03)),
            cyl("bore", 0.02, 0.01, at=(0.035, 0, 0.005), op="subtract"),
        ],
        parameters=[width_param(0.12)],
    )


def drive_shaft() -> PartDef:
    """A shaft with a hub on each end: a cylinder lying along +x (rotated), a sphere cap and a block."""
    return part(
        "drive-shaft",
        [
            cyl("shaft", 0.015, 0.4, at=(0, 0, 0), quat=ROT_X90),
            sphere("cap", 0.03, at=(0.0, 0.235, 0.0)),
            box("hub", 0.05, 0.05, 0.05, at=(0.0, -0.23, 0.0)),
        ],
    )


def sensor_mast() -> PartDef:
    return part(
        "sensor-mast",
        [cyl("mast", 0.01, 0.3, at=(0, 0, 0.15)), sphere("head", 0.025, at=(0, 0, 0.325))],
    )


def reflectance_ior_glb() -> bytes:
    """Aluminium plate with the catalog look but reflectance 0.35, so the file carries `KHR_materials_ior`.

    No catalog entry has a reflectance other than 0.5, so the slot is replaced for this fixture only."""
    base = load_material_catalog().get("al6061-t6").pbr
    odd = base.model_copy(update={"reflectance": base.reflectance.model_copy(update={"value": 0.35})})
    with mock.patch("kinetra_engine.parts.visual.pbr_for", lambda material: (odd, True)):
        return part_glb(mounting_plate(), catalog_material("al6061-t6"))


SAMPLES = {
    "mounting-plate-al6061": (mounting_plate, "al6061-t6"),
    "drive-shaft-steel": (drive_shaft, "steel-a36"),
    "sensor-mast-user-material": (sensor_mast, None),
    "reflectance-ior": (mounting_plate, "al6061-t6"),
}


def sample_material(name: str) -> Material:
    material_id = SAMPLES[name][1]
    return catalog_material(material_id) if material_id else user_material()


def sample_glb(name: str) -> bytes:
    if name == "reflectance-ior":
        return reflectance_ior_glb()
    return part_glb(SAMPLES[name][0](), sample_material(name))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name in SAMPLES:
        (FIXTURES / f"{name}.glb").write_bytes(sample_glb(name))
        print("wrote", FIXTURES / f"{name}.glb")


if __name__ == "__main__":
    main()
