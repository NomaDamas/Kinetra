"""Visual mesh of a part as glTF 2.0 (B-01c): the same recipe the mass comes from, tessellated, with a material slot.

    part_glb(part, material, parameters=None) -> bytes           # binary glTF (.glb), the format assets travel in
    part_gltf(part, material, parameters=None) -> (document, bin) # the JSON document and the BIN chunk it indexes

The mesh is for drawing only (A1 in `docs/architecture/client-adapter.md`): mass, inertia and the collision proxy do not
read it. Details and limits are in `docs/architecture/part-visual.md`:

- One node per added component under one root node; the component's position and orientation are the node's translation
  and rotation, so the vertex data of a component is its own primitive, tessellated deterministically (`_tessellate.py`).
- Vertex data is in the part-local frame of `kinetra_core.conventions` (right-handed, +Z up, metres). The root node
  carries the fixed rotation that turns that frame into glTF's +Y up, so the file stands upright in any glTF viewer; a
  client that works in the Project frame ignores the root rotation.
- Voids (`operation: subtract`) are NOT cut out of the drawing. Without a CAD kernel a boolean is not available (B-01a,
  `docs/architecture/part-mass.md`), so they are listed in `extras.kinetra.voids` and the file says `voids_cut: false`.
- The material slot is `materials[0]`: the four PBR slots of the catalog entry with this `Material.id` (B-07), or the
  neutral mid-grey fallback when the id is not in the catalog. `baseColorFactor` is linear RGB. A reflectance other than
  0.5 is written as `KHR_materials_ior`.

The output is a pure function of the arguments: the same recipe gives the same bytes.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Mapping
from typing import Any

from kinetra_core import Material, PartDef, PbrSlots, Quantity, load_material_catalog

from . import _tessellate as tess
from ._shape import ShapeError, resolve_shape

GENERATOR = "kinetra_engine.parts.visual"
FRAME_NOTE = (
    "vertex data and component poses: part-local frame, right-handed, +Z up, metres; "
    "the root node rotates it to glTF +Y up"
)

# Z-up to Y-up: rotation of -90 degrees about +x maps local +z to +y (glTF +Y) and local +y to -z.
_ROOT_ROTATION = (-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))

# Neutral look for a material that is not in the catalog (docs/architecture/materials.md, "찾는 법").
_FALLBACK_REF = (
    "neutral fallback look for a material without a catalog entry (docs/architecture/materials.md); "
    "a look, not a measurement"
)


def _fallback_slot(value: float) -> dict[str, Any]:
    return {"value": value, "unit": "1", "badge": "default", "source": {"ref": _FALLBACK_REF}}


FALLBACK_PBR = PbrSlots.model_validate(
    {
        "base_color": {"srgb": "#808080", "badge": "default", "source": {"ref": _FALLBACK_REF}},
        "metallic": _fallback_slot(0.0),
        "roughness": _fallback_slot(0.5),
        "reflectance": _fallback_slot(0.5),
    }
)

_REFLECTANCE_GLTF_CORE = 0.5  # Filament reflectance whose F0 (0.04, ior 1.5) glTF core fixes


def pbr_for(material: Material) -> tuple[PbrSlots, bool]:
    """The PBR slots of `material` (looked up by id) and whether they come from the catalog (False: the fallback)."""
    try:
        return load_material_catalog().get(material.id).pbr, True
    except KeyError:
        return FALLBACK_PBR, False


def srgb_to_linear(c: float) -> float:
    """sRGB component in [0, 1] to linear (IEC 61966-2-1)."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f32(x: float) -> float:
    """`x` rounded to the nearest float32 (a glTF renderer stores it so). It also keeps the JSON text the same on
    platforms whose `pow` differs from ours in the last bit of a double."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def linear_base_color(srgb: str) -> list[float]:
    """`#rrggbb` to the glTF `baseColorFactor`: linear RGB and alpha 1."""
    rgb = [int(srgb[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]
    return [_f32(srgb_to_linear(c)) for c in rgb] + [1.0]


def ior_from_reflectance(r: float) -> float:
    """Index of refraction that gives Filament's F0 = 0.16 r^2: ior = (1 + 0.4 r) / (1 - 0.4 r)."""
    return (1.0 + 0.4 * r) / (1.0 - 0.4 * r)


def _material_entry(material: Material) -> tuple[dict[str, Any], bool]:
    slots, from_catalog = pbr_for(material)
    entry: dict[str, Any] = {
        "name": material.id,
        "pbrMetallicRoughness": {
            "baseColorFactor": linear_base_color(slots.base_color.srgb),
            "metallicFactor": slots.metallic.value,
            "roughnessFactor": slots.roughness.value,
        },
        "extras": {
            "kinetra": {
                "pbr": slots.model_dump(mode="json", exclude_none=True),
                "pbr_from_catalog": from_catalog,
                "base_color_space": "factor is linear RGB; pbr.base_color.srgb is the sRGB value it was converted from",
            }
        },
    }
    uses_ior = slots.reflectance.value != _REFLECTANCE_GLTF_CORE
    if uses_ior:
        entry["extensions"] = {"KHR_materials_ior": {"ior": _f32(ior_from_reflectance(slots.reflectance.value))}}
    return entry, uses_ior


def _pad4(b: bytes, fill: bytes) -> bytes:
    return b + fill * (-len(b) % 4)


class _Binary:
    """Accumulates the BIN chunk, every view starting on a 4-byte boundary, and the views and accessors indexing it."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def add(self, payload: bytes, target: int, accessor: dict[str, Any]) -> int:
        offset = len(self.data)
        self.data += _pad4(payload, b"\x00")
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload), "target": target})
        self.accessors.append({"bufferView": len(self.views) - 1, "byteOffset": 0, **accessor})
        return len(self.accessors) - 1


_FLOAT, _USHORT, _UINT = 5126, 5123, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


def _add_mesh(binary: _Binary, mesh: tess.Mesh) -> dict[str, int]:
    pos = struct.pack(f"<{len(mesh.positions)}f", *mesh.positions)
    # min and max are those of the float32 values actually stored (the validator compares them to the data).
    stored = struct.unpack(f"<{len(mesh.positions)}f", pos)
    cols = [stored[k::3] for k in range(3)]
    count = mesh.vertex_count
    position = binary.add(
        pos,
        _ARRAY_BUFFER,
        {
            "componentType": _FLOAT,
            "count": count,
            "type": "VEC3",
            "min": [min(c) for c in cols],
            "max": [max(c) for c in cols],
        },
    )
    normal = binary.add(
        struct.pack(f"<{len(mesh.normals)}f", *mesh.normals),
        _ARRAY_BUFFER,
        {"componentType": _FLOAT, "count": count, "type": "VEC3"},
    )
    if count <= 0xFFFF:
        index_data, component = struct.pack(f"<{len(mesh.indices)}H", *mesh.indices), _USHORT
    else:
        index_data, component = struct.pack(f"<{len(mesh.indices)}I", *mesh.indices), _UINT
    index = binary.add(
        index_data,
        _ELEMENT_ARRAY_BUFFER,
        {"componentType": component, "count": len(mesh.indices), "type": "SCALAR"},
    )
    return {"POSITION": position, "NORMAL": normal, "indices": index}


def _unit_quaternion(q) -> list[float]:
    n = math.sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
    return [q.x / n, q.y / n, q.z / n, q.w / n]  # the model allows norm 1 +- 1e-6; glTF wants a unit rotation


def part_gltf(
    part: PartDef,
    material: Material,
    parameters: Mapping[str, Quantity] | None = None,
) -> tuple[dict[str, Any], bytes]:
    """The glTF JSON document of `part` made of `material` and the BIN chunk it indexes (`buffers[0]`, no uri).

    `parameters` overrides the part's defaults exactly as in `mass_properties`. Raises `ShapeError` for a part without
    a shape recipe, an unknown or out-of-range parameter, a dimension that is not above zero, or components that break
    the disjoint-sum rule (`kinetra_core.shape`): a recipe is drawn only if its mass can be computed.
    """
    resolved = resolve_shape(part, parameters)  # the same evaluation, and the same rejections, as mass and the proxy
    assert part.shape is not None

    binary = _Binary()
    meshes: list[dict[str, Any]] = []
    children: list[int] = []
    nodes: list[dict[str, Any]] = [{}]  # node 0 is the root, filled in below
    voids: list[dict[str, Any]] = []
    for placed in resolved.placed:
        comp, dims = placed.component, placed.dims
        if comp.operation == "subtract":
            voids.append(
                {
                    "id": comp.id,
                    "primitive": comp.primitive.kind,
                    "dimensions": dict(dims),
                    "center": list(placed.center),
                    "orientation": _unit_quaternion(comp.orientation),
                }
            )
            continue
        attributes = _add_mesh(binary, tess.tessellate(comp.primitive.kind, dims))
        meshes.append(
            {
                "name": comp.id,
                "primitives": [
                    {
                        "attributes": {"POSITION": attributes["POSITION"], "NORMAL": attributes["NORMAL"]},
                        "indices": attributes["indices"],
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        )
        nodes.append(
            {
                "name": comp.id,
                "mesh": len(meshes) - 1,
                "translation": list(placed.center),
                "rotation": _unit_quaternion(comp.orientation),
            }
        )
        children.append(len(nodes) - 1)
    quantities = resolved.quantities

    material_entry, uses_ior = _material_entry(material)
    nodes[0] = {
        "name": part.id,
        "rotation": list(_ROOT_ROTATION),
        "children": children,
        "extras": {
            "kinetra": {
                "part_id": part.id,
                "material_id": material.id,
                "frame": FRAME_NOTE,
                "parameters": {n: q.model_dump(mode="json", exclude_none=True) for n, q in quantities.items()},
                "shape": {"badge": part.shape.badge.value, "source": part.shape.source.model_dump(mode="json", exclude_none=True)},
                "voids_cut": False,
                "voids": voids,
                "tessellation": {
                    "cylinder_segments": tess.CYLINDER_SEGMENTS,
                    "sphere_segments": tess.SPHERE_SEGMENTS,
                    "sphere_stacks": tess.SPHERE_STACKS,
                    "note": "inscribed polygons: drawn volume of a cylinder or sphere is below the true volume",
                },
            }
        },
    }
    payload = bytes(binary.data)
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        **({"extensionsUsed": ["KHR_materials_ior"]} if uses_ior else {}),
        "scene": 0,
        "scenes": [{"name": part.id, "nodes": [0]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [material_entry],
        "accessors": binary.accessors,
        "bufferViews": binary.views,
        "buffers": [{"byteLength": len(payload)}],
    }
    return document, payload


_GLB_MAGIC, _GLB_VERSION, _CHUNK_JSON, _CHUNK_BIN = 0x46546C67, 2, 0x4E4F534A, 0x004E4942


def part_glb(
    part: PartDef,
    material: Material,
    parameters: Mapping[str, Quantity] | None = None,
) -> bytes:
    """`part_gltf` packed as one binary glTF (.glb): header, JSON chunk (space padded), BIN chunk (zero padded)."""
    document, payload = part_gltf(part, material, parameters)
    text = _pad4(json.dumps(document, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii"), b" ")
    total = 12 + 8 + len(text) + 8 + len(payload)
    return b"".join(
        (
            struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total),
            struct.pack("<II", len(text), _CHUNK_JSON),
            text,
            struct.pack("<II", len(payload), _CHUNK_BIN),
            payload,
        )
    )
