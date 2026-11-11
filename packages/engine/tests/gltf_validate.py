"""Independent structural check of a glTF 2.0 binary, written from the specification, not from the writer's code.

It reads the .glb bytes back (container, JSON, buffers, accessors) and checks what the Khronos validator checks for the
subset this project writes (triangle meshes with POSITION, NORMAL, indices, one metallic-roughness material, node
transforms, KHR_materials_ior). The official validator (`gltf-validator`) runs on the same fixtures in
`tools/gltf-check` (web CI job); this file lets `uv run pytest packages/engine -k gltf` fail on a structural fault
without Node.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass

GLB_MAGIC, GLB_VERSION, CHUNK_JSON, CHUNK_BIN = 0x46546C67, 2, 0x4E4F534A, 0x004E4942
COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
KNOWN_EXTENSIONS = {"KHR_materials_ior"}


class GltfInvalid(AssertionError):
    pass


def need(cond: bool, message: str) -> None:
    if not cond:
        raise GltfInvalid(message)


@dataclass
class Glb:
    doc: dict
    bin: bytes


def parse_glb(data: bytes) -> Glb:
    need(len(data) >= 20 and len(data) % 4 == 0, "glb length must be a multiple of 4 and hold a header and a chunk")
    magic, version, length = struct.unpack_from("<III", data, 0)
    need(magic == GLB_MAGIC, "bad magic")
    need(version == GLB_VERSION, "glb container version must be 2")
    need(length == len(data), f"header length {length} != file length {len(data)}")
    offset, chunks = 12, []
    while offset < len(data):
        need(offset + 8 <= len(data), "truncated chunk header")
        size, kind = struct.unpack_from("<II", data, offset)
        need(size % 4 == 0, "chunk length must be a multiple of 4")
        need(offset + 8 + size <= len(data), "chunk runs past the end")
        chunks.append((kind, data[offset + 8 : offset + 8 + size]))
        offset += 8 + size
    need(chunks and chunks[0][0] == CHUNK_JSON, "first chunk must be JSON")
    need(len(chunks) <= 2 and (len(chunks) == 1 or chunks[1][0] == CHUNK_BIN), "chunks must be JSON then optional BIN")
    json_bytes = chunks[0][1]
    need(json_bytes.rstrip(b" ") == json_bytes.rstrip(b" ").strip(), "JSON must not start with whitespace")
    doc = json.loads(json_bytes.decode("utf-8"))
    return Glb(doc, chunks[1][1] if len(chunks) == 2 else b"")


def accessor_values(glb: Glb, index: int) -> list[tuple]:
    a = glb.doc["accessors"][index]
    view = glb.doc["bufferViews"][a["bufferView"]]
    fmt, size = COMPONENT[a["componentType"]]
    n = TYPE_COUNT[a["type"]]
    stride = view.get("byteStride", size * n)
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    out = []
    for i in range(a["count"]):
        out.append(struct.unpack_from("<" + fmt * n, glb.bin, start + i * stride))
    return out


def validate(data: bytes) -> Glb:
    glb = parse_glb(data)
    doc = glb.doc
    need(doc.get("asset", {}).get("version") == "2.0", "asset.version must be 2.0")
    used = set(doc.get("extensionsUsed", ()))
    need(used <= KNOWN_EXTENSIONS, f"unknown extensions declared: {used - KNOWN_EXTENSIONS}")
    need(not set(doc.get("extensionsRequired", ())), "this writer never requires an extension")

    buffers = doc["buffers"]
    need(len(buffers) == 1 and "uri" not in buffers[0], "one buffer without uri (the GLB BIN chunk)")
    need(buffers[0]["byteLength"] <= len(glb.bin) <= buffers[0]["byteLength"] + 3, "buffer.byteLength vs BIN chunk")
    for i, v in enumerate(doc["bufferViews"]):
        need(v["buffer"] == 0, f"bufferViews[{i}].buffer")
        need(v.get("byteOffset", 0) % 4 == 0, f"bufferViews[{i}] offset not 4-aligned")
        need(v["byteOffset"] + v["byteLength"] <= buffers[0]["byteLength"], f"bufferViews[{i}] outside the buffer")
        need(v.get("target") in (34962, 34963), f"bufferViews[{i}].target")

    for i, a in enumerate(doc["accessors"]):
        fmt, size = COMPONENT[a["componentType"]]
        n = TYPE_COUNT[a["type"]]
        need(a["count"] >= 1, f"accessors[{i}].count")
        view = doc["bufferViews"][a["bufferView"]]
        need(a.get("byteOffset", 0) % size == 0, f"accessors[{i}] offset not aligned to its component")
        need(a.get("byteOffset", 0) + a["count"] * size * n <= view["byteLength"], f"accessors[{i}] outside its view")
        vals = accessor_values(glb, i)
        if a["componentType"] == 5126:
            need(all(math.isfinite(x) for v in vals for x in v), f"accessors[{i}] has a non-finite value")
        if "min" in a or "max" in a:
            for k in range(n):
                col = [v[k] for v in vals]
                need(min(col) == a["min"][k] and max(col) == a["max"][k], f"accessors[{i}] min/max do not match the data")

    for m in doc["meshes"]:
        for p in m["primitives"]:
            need(p.get("mode", 4) == 4, "triangles only")
            pos, nor, idx = p["attributes"]["POSITION"], p["attributes"]["NORMAL"], p["indices"]
            pa, na, ia = (doc["accessors"][k] for k in (pos, nor, idx))
            need(pa["type"] == na["type"] == "VEC3" and pa["componentType"] == na["componentType"] == 5126, "POSITION/NORMAL type")
            need("min" in pa and "max" in pa, "POSITION accessor needs min and max")
            need(pa["count"] == na["count"], "POSITION and NORMAL counts differ")
            need(doc["bufferViews"][pa["bufferView"]]["target"] == 34962, "attribute view target")
            need(doc["bufferViews"][ia["bufferView"]]["target"] == 34963, "index view target")
            need(ia["type"] == "SCALAR" and ia["componentType"] in (5123, 5125), "index type")
            need(ia["count"] % 3 == 0, "index count not a multiple of 3")
            ind = [v[0] for v in accessor_values(glb, idx)]
            need(max(ind) < pa["count"], "index out of range")
            need(all(ind[i] != ind[i + 1] and ind[i] != ind[i + 2] and ind[i + 1] != ind[i + 2] for i in range(0, len(ind), 3)), "degenerate triangle")
            for v in accessor_values(glb, nor):
                need(abs(math.sqrt(sum(c * c for c in v)) - 1.0) < 1e-5, f"normal {v} is not unit length")
            need(0 <= p["material"] < len(doc["materials"]), "material index")

    for i, mat in enumerate(doc["materials"]):
        pbr = mat["pbrMetallicRoughness"]
        need(len(pbr["baseColorFactor"]) == 4 and all(0.0 <= c <= 1.0 for c in pbr["baseColorFactor"]), f"materials[{i}] baseColorFactor")
        need(0.0 <= pbr["metallicFactor"] <= 1.0 and 0.0 <= pbr["roughnessFactor"] <= 1.0, f"materials[{i}] factors")
        ext = mat.get("extensions", {})
        need(set(ext) <= used, f"materials[{i}] uses an extension not in extensionsUsed")
        if "KHR_materials_ior" in ext:
            need(ext["KHR_materials_ior"]["ior"] >= 1.0, "ior must be >= 1")
    declared = set()
    for mat in doc["materials"]:
        declared |= set(mat.get("extensions", {}))
    need(used == declared, f"extensionsUsed {used} is not what the materials use {declared}")

    nodes = doc["nodes"]
    parents: dict[int, int] = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", ()):
            need(0 <= c < len(nodes) and c not in parents, f"node {c} has a bad or second parent")
            parents[c] = i
        if "rotation" in n:
            need(abs(math.sqrt(sum(x * x for x in n["rotation"])) - 1.0) < 1e-6, f"nodes[{i}] rotation not unit")
        if "mesh" in n:
            need(0 <= n["mesh"] < len(doc["meshes"]), f"nodes[{i}].mesh")
    for i in range(len(nodes)):  # no cycles
        seen, k = set(), i
        while k in parents:
            need(k not in seen, "node cycle")
            seen.add(k)
            k = parents[k]
    for s in doc["scenes"]:
        for r in s["nodes"]:
            need(0 <= r < len(nodes) and r not in parents, "scene root must be a root node")
    need(0 <= doc["scene"] < len(doc["scenes"]), "scene index")
    return glb


def triangles(glb: Glb, mesh_index: int) -> tuple[list[tuple], list[tuple[int, int, int]]]:
    p = glb.doc["meshes"][mesh_index]["primitives"][0]
    pos = accessor_values(glb, p["attributes"]["POSITION"])
    ind = [v[0] for v in accessor_values(glb, p["indices"])]
    return pos, [(ind[i], ind[i + 1], ind[i + 2]) for i in range(0, len(ind), 3)]


def mesh_volume(pos: list[tuple], tris: list[tuple[int, int, int]]) -> float:
    """Signed volume by the divergence theorem: positive for outward (counter-clockwise from outside) winding."""
    v = 0.0
    for a, b, c in tris:
        pa, pb, pc = pos[a], pos[b], pos[c]
        v += (
            pa[0] * (pb[1] * pc[2] - pb[2] * pc[1])
            - pa[1] * (pb[0] * pc[2] - pb[2] * pc[0])
            + pa[2] * (pb[0] * pc[1] - pb[1] * pc[0])
        )
    return v / 6.0


def is_closed_manifold(pos: list[tuple], tris: list[tuple[int, int, int]]) -> bool:
    """Every undirected edge is shared by exactly two triangles that traverse it in opposite directions.

    Vertices that coincide in space (hard edges and flat-shaded faces are split) are welded by position first.
    """
    weld: dict[tuple, int] = {}
    ids = [weld.setdefault(tuple(round(c, 6) for c in p), len(weld)) for p in pos]
    directed: dict[tuple[int, int], int] = {}
    for a, b, c in tris:
        for u, v in ((ids[a], ids[b]), (ids[b], ids[c]), (ids[c], ids[a])):
            directed[(u, v)] = directed.get((u, v), 0) + 1
    return all(n == 1 and directed.get((v, u)) == 1 for (u, v), n in directed.items())
