"""Compile one part definition file: the check step of `docs/process/add-part.md` (B-01d).

    uv run python -m kinetra_engine.parts PART.json --material al6061-t6 [--out DIR]
    uv run python -m kinetra_engine.parts PAYLOAD.json [--out DIR]          # a part with a `mass_parameter` needs no material

Reads a `PartDef` JSON file, the material by id from the B-07 catalog (not needed, not read, for a part whose mass is
declared by its `mass_parameter`; a given one only picks the look), and compiles mass, collision proxy and glb exactly
as the studio does (default parameter values). Prints one JSON report on stdout: mass, centre of mass, inertia, proxy volume
error, filled and undrawn voids, glb size, and the milliseconds each step took. With `--out DIR` it also writes
`DIR/<part id>.glb`. Exit code 0 when all three compile, 1 with the reason on stderr when the definition is rejected
(a file that is not a `PartDef`, an unknown material, a recipe the compiler refuses).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from kinetra_core import PartDef, load_material_catalog

from ._shape import ShapeError
from .collision import collision_proxy
from .mass import mass_properties
from .visual import part_glb


def _timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - start) * 1000.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kinetra_engine.parts", description=__doc__.split("\n\n")[0])
    parser.add_argument("part", type=Path, help="PartDef JSON file")
    parser.add_argument(
        "--material",
        help="material id in the B-07 catalog (kinetra_core.load_material_catalog); required unless the part has a mass_parameter",
    )
    parser.add_argument("--out", type=Path, help="directory to write <part id>.glb into")
    args = parser.parse_args(argv)

    try:
        part = PartDef.model_validate_json(args.part.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"{args.part}: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"{args.part}: not a valid PartDef:\n{e}", file=sys.stderr)
        return 1
    material = None
    if args.material is not None:
        try:
            material = load_material_catalog().get(args.material).material
        except KeyError:
            ids = [e.material.id for e in load_material_catalog().entries]
            print(f"unknown material {args.material!r}; the catalog has {ids}", file=sys.stderr)
            return 1
    elif part.mass_parameter is None:
        print(f"{part.id}: --material is required (this part has no mass_parameter, so its mass is density x volume)", file=sys.stderr)
        return 1

    try:
        mass, t_mass = _timed(lambda: mass_properties(part, material))
        proxy, t_proxy = _timed(lambda: collision_proxy(part))
        glb, t_glb = _timed(lambda: part_glb(part, material))
    except ShapeError as e:
        print(f"{part.id}: rejected by the part compiler: {e}", file=sys.stderr)
        return 1

    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{part.id}.glb").write_bytes(glb)
    report = {
        "part": part.id,
        "material": material.id if material is not None else None,
        "mass_declared_by": part.mass_parameter,
        "mass_kg": mass.mass.value,
        "volume_m3": mass.volume.value,
        "center_of_mass_m": [mass.center_of_mass.x, mass.center_of_mass.y, mass.center_of_mass.z],
        "inertia_kg_m2": mass.inertia.model_dump(mode="json", include={"ixx", "iyy", "izz", "ixy", "ixz", "iyz"}),
        "input_badges": [b.value for b in mass.derivation.input_badges],
        "proxy_geoms": len(proxy.geoms),
        "proxy_volume_error": proxy.volume_error.value,
        "filled_voids": [v.id for v in proxy.filled_voids],
        "undrawn_voids": [c.id for c in part.shape.components if c.operation == "subtract"] if part.shape else [],
        "glb_bytes": len(glb),
        "milliseconds": {"mass": round(t_mass, 3), "proxy": round(t_proxy, 3), "glb": round(t_glb, 3)},
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
