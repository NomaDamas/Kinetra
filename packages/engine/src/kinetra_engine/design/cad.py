"""CAD export for the custom parts: build123d (STL + STEP) if importable, else trimesh primitives (STL only, cad_step = null).

``write_part(part_kind, params, out_dir, name)`` returns {"stl": rel, "step": rel|None, "kernel": "build123d"|"trimesh", "volume_mm3": float}.
Binary STL is written in millimetres.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def kernel() -> str:
    try:
        import build123d  # noqa: F401
        return "build123d"
    except Exception:
        return "trimesh"


def _bracket_b123(p):
    from build123d import Box, Cylinder, Pos, Part, Align, Location
    W, H, D, t = p["width_mm"], p["height_mm"], p["depth_mm"], p["plate_t_mm"]
    plate = Pos(0, -D / 2 + t / 2, H / 2 + t) * Box(W, t, H, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    base = Pos(0, 0, t / 2) * Box(W, D, t)
    solid = base + plate
    bolts = p["n_bolts"]
    xs = [-W / 2 + 12.0, W / 2 - 12.0]
    ys = [D / 2 - 14.0, -D / 2 + t + 14.0 + 8.0]
    k = 0
    for x in xs:
        for y in ys:
            if k >= bolts:
                break
            solid = solid - Pos(x, y, t / 2) * Cylinder(p["bolt_d_mm"] / 2, t * 2)
            k += 1
    return solid


def _cradle_b123(p):
    from build123d import Box, Cylinder, Pos, Rot
    W, L, t, r = p["width_mm"], p["length_mm"], p["plate_t_mm"], p["tank_radius_mm"]
    solid = Box(L, t, W)                                   # plate in XZ, thickness along Y; saddle top edge at +Z
    cut = Pos(0, 0, W / 2) * Rot(90, 0, 0) * Cylinder(r, t * 3)
    return solid - cut


def _tube_b123(p):
    from build123d import Box, Pos
    a, b, w, L = p["outer_w_mm"], p["outer_d_mm"], p["wall_mm"], p["length_mm"]
    return Box(a, b, L) - Box(a - 2 * w, b - 2 * w, L * 2)


_B123 = {"nozzle_bracket": _bracket_b123, "tank_cradle": _cradle_b123, "shank_link": _tube_b123}


def _trimesh_solid(kind: str, p):
    import trimesh
    if kind == "nozzle_bracket":
        W, H, D, t = p["width_mm"], p["height_mm"], p["depth_mm"], p["plate_t_mm"]
        base = trimesh.creation.box((W, D, t)); base.apply_translation((0, 0, t / 2))
        plate = trimesh.creation.box((W, t, H)); plate.apply_translation((0, -D / 2 + t / 2, H / 2 + t))
        return trimesh.util.concatenate([base, plate])
    if kind == "tank_cradle":
        return trimesh.creation.box((p["length_mm"], p["plate_t_mm"], p["width_mm"]))
    a, b, w, L = p["outer_w_mm"], p["outer_d_mm"], p["wall_mm"], p["length_mm"]
    parts = []
    for (sx, sy, dx, dy) in ((a, w, 0, (b - w) / 2), (a, w, 0, -(b - w) / 2), (w, b - 2 * w, (a - w) / 2, 0), (w, b - 2 * w, -(a - w) / 2, 0)):
        bx = trimesh.creation.box((sx, sy, L)); bx.apply_translation((dx, dy, 0)); parts.append(bx)
    return trimesh.util.concatenate(parts)


def write_part(kind: str, params: dict[str, float], out_dir: Path, name: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stl, step = out_dir / f"{name}.stl", out_dir / f"{name}.step"
    k = kernel()
    if k == "build123d":
        from build123d import export_step, export_stl
        solid = _B123[kind](params)
        export_stl(solid, str(stl), tolerance=0.05, angular_tolerance=0.2)
        export_step(solid, str(step))
        vol = float(solid.volume)
        return dict(stl=f"cad/{name}.stl", step=f"cad/{name}.step", kernel=k, volume_mm3=vol)
    m = _trimesh_solid(kind, params)
    m.export(str(stl))
    step.unlink(missing_ok=True)
    return dict(stl=f"cad/{name}.stl", step=None, kernel=k, volume_mm3=float(m.volume))
