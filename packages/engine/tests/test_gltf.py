"""B-01c: the visual glTF of a part and its PBR material slot.

Expected values are written out from the glTF 2.0 specification, the sRGB standard and the B-07 catalog data, not read
back from the code under test. The structural check in `gltf_validate.py` reads the bytes independently of the writer;
the official Khronos validator runs on the committed fixtures in `tools/gltf-check`.
"""

from __future__ import annotations

import json
import math
import struct

import pytest
from gltf_samples import (
    FIXTURES,
    SAMPLES,
    ROT_X90,
    ax,
    box,
    catalog_material,
    cyl,
    drive_shaft,
    mounting_plate,
    part,
    q,
    sample_glb,
    sample_material,
    sensor_mast,
    sphere,
    user_material,
    width_param,
)
from gltf_validate import GltfInvalid, is_closed_manifold, mesh_volume, parse_glb, triangles, validate

from kinetra_core import Quantity, load_material_catalog
from kinetra_engine.parts import ShapeError, mass_properties, part_glb, part_gltf, pbr_for
from kinetra_engine.parts import _tessellate as tess
from kinetra_engine.parts.visual import FALLBACK_PBR, ior_from_reflectance, linear_base_color, srgb_to_linear

ALU = "al6061-t6"


def glb_of(p, material_id=ALU, parameters=None):
    return part_glb(p, catalog_material(material_id), parameters)


# --- the file is valid glTF ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_gltf_samples_pass_the_structural_validator(name):
    glb = validate(sample_glb(name))
    assert glb.doc["asset"]["version"] == "2.0"
    assert len(glb.doc["materials"]) == 1


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_gltf_committed_fixtures_are_current(name):
    # The Khronos validator and the browser page read these files: they must be what the code writes today.
    assert (FIXTURES / f"{name}.glb").read_bytes() == sample_glb(name), "run: uv run python packages/engine/tests/gltf_samples.py"


def test_gltf_validator_rejects_a_broken_file():
    good = bytearray(sample_glb("sensor-mast-user-material"))
    bad_len = bytes(good[:8]) + struct.pack("<I", len(good) + 4) + bytes(good[12:])
    with pytest.raises(GltfInvalid, match="length"):
        validate(bad_len)
    doc, payload = part_gltf(sensor_mast(), user_material())
    doc["meshes"][0]["primitives"][0]["indices"] = 99
    with pytest.raises(IndexError):  # an index into a missing accessor is not a valid file either
        validate(_repack(doc, payload))
    doc, payload = part_gltf(sensor_mast(), user_material())
    doc["accessors"][0]["min"][0] -= 1.0
    with pytest.raises(GltfInvalid, match="min/max"):
        validate(_repack(doc, payload))
    doc, payload = part_gltf(sensor_mast(), user_material())
    doc["extensionsUsed"] = ["KHR_materials_ior"]
    with pytest.raises(GltfInvalid, match="extensionsUsed"):
        validate(_repack(doc, payload))


def _repack(doc, payload):
    text = json.dumps(doc).encode()
    text += b" " * (-len(text) % 4)
    return (
        struct.pack("<III", 0x46546C67, 2, 28 + len(text) + len(payload))
        + struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(payload), 0x004E4942)
        + payload
    )


# --- tessellation: closed, outward, deterministic, volume as computed by hand ----------------------------------------------


def test_gltf_box_is_exact():
    glb = validate(glb_of(part("b", [box("b", 0.2, 0.1, 0.3)])))
    pos, tris = triangles(glb, 0)
    assert len(pos) == 24 and len(tris) == 12
    assert is_closed_manifold(pos, tris)
    assert mesh_volume(pos, tris) == pytest.approx(0.2 * 0.1 * 0.3, rel=1e-6)
    xs, ys, zs = zip(*pos)
    assert (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)) == pytest.approx((-0.1, 0.1, -0.05, 0.05, -0.15, 0.15))


def test_gltf_cylinder_volume_is_the_inscribed_polygon_prism():
    r, h, n = 0.05, 0.4, tess.CYLINDER_SEGMENTS
    pos, tris = triangles(validate(glb_of(part("c", [cyl("c", r, h)]))), 0)
    assert is_closed_manifold(pos, tris)
    # Regular n-gon of circumradius r has area n/2 r^2 sin(2 pi / n); the prism is that times h.
    expected = n / 2 * r * r * math.sin(2 * math.pi / n) * h
    assert mesh_volume(pos, tris) == pytest.approx(expected, rel=1e-6)
    true_volume = math.pi * r * r * h
    assert expected < true_volume and expected > 0.99 * true_volume  # inscribed, and close for n = 64


def test_gltf_sphere_volume_is_the_inscribed_solid_of_revolution_sum():
    r, n, k = 0.1, tess.SPHERE_SEGMENTS, tess.SPHERE_STACKS
    pos, tris = triangles(validate(glb_of(part("s", [sphere("s", r)]))), 0)
    assert is_closed_manifold(pos, tris)
    # Vertices lie on the sphere (radius r).
    assert all(math.sqrt(x * x + y * y + z * z) == pytest.approx(r, rel=1e-5) for x, y, z in pos)
    # Each latitude band between polar angles a and b is a frustum of an n-gon pyramid: V = n/6 sin(2pi/n) *
    # (cone volume sum). Closed form: sum over bands of the n-gon frustum with ring radii r sin(a), r sin(b), heights
    # r cos(a), r cos(b); poles are cones.
    area = lambda rho: n / 2 * rho * rho * math.sin(2 * math.pi / n)
    expected = 0.0
    angles = [math.pi * i / k for i in range(k + 1)]
    for a, b in zip(angles, angles[1:]):
        ra, rb = r * math.sin(a), r * math.sin(b)
        za, zb = r * math.cos(a), r * math.cos(b)
        h = za - zb
        expected += h / 3 * (area(ra) + area(rb) + math.sqrt(area(ra) * area(rb)))
    assert mesh_volume(pos, tris) == pytest.approx(expected, rel=1e-5)
    true_volume = 4 / 3 * math.pi * r**3
    assert 0.99 * true_volume < expected < true_volume


def test_gltf_normals_point_outward_and_triangles_wind_counter_clockwise():
    for comp in (box("b", 0.2, 0.1, 0.3), cyl("c", 0.05, 0.4), sphere("s", 0.1)):
        glb = validate(glb_of(part("p", [comp])))
        pos, tris = triangles(glb, 0)
        nor = [v for v in __import__("gltf_validate").accessor_values(glb, glb.doc["meshes"][0]["primitives"][0]["attributes"]["NORMAL"])]
        for a, b, c in tris:
            pa, pb, pc = (pos[i] for i in (a, b, c))
            e1 = tuple(pb[k] - pa[k] for k in range(3))
            e2 = tuple(pc[k] - pa[k] for k in range(3))
            face = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            vn = tuple(sum(nor[i][k] for i in (a, b, c)) for k in range(3))
            assert sum(face[k] * vn[k] for k in range(3)) > 0  # winding agrees with the stored normals
        assert mesh_volume(pos, tris) > 0  # and those normals face away from the inside


def test_gltf_is_deterministic_bytes():
    assert glb_of(mounting_plate()) == glb_of(mounting_plate())
    assert glb_of(drive_shaft()) == glb_of(drive_shaft())
    assert tess.sphere(1.0) == tess.sphere(1.0)


def test_gltf_small_meshes_use_16_bit_indices():
    doc, _ = part_gltf(part("s", [sphere("s", 0.1)]), catalog_material(ALU))
    assert doc["accessors"][0]["count"] == 2 + 23 * 48  # poles + 23 latitude rings of 48 = 1106 vertices
    assert doc["accessors"][2]["componentType"] == 5123  # UNSIGNED_SHORT, since 1106 <= 65535


# --- same definition: the recipe, parameters, voids ----------------------------------------------------------------------


def test_gltf_follows_the_recipe_and_its_parameters():
    p = mounting_plate()
    default = validate(glb_of(p))
    wide = validate(glb_of(p, parameters={"width": Quantity.model_validate(q(0.2))}))
    plate = [i for i, m in enumerate(default.doc["meshes"]) if m["name"] == "plate"][0]
    for glb, width in ((default, 0.12), (wide, 0.2)):
        pos, _ = triangles(glb, plate)
        xs = [v[0] for v in pos]
        assert max(xs) - min(xs) == pytest.approx(width, rel=1e-6)
    # the recipe's own mass on the same parameters: drawn box volume equals the closed-form box volume
    r = mass_properties(p, catalog_material(ALU), {"width": Quantity.model_validate(q(0.2))})
    plate_c = next(c for c in r.derivation.components if c.id == "plate")
    assert plate_c.volume == pytest.approx(mesh_volume(*triangles(wide, plate)), rel=1e-6)


def test_gltf_one_node_per_added_component_with_the_recipe_pose():
    glb = validate(glb_of(drive_shaft()))
    nodes = glb.doc["nodes"]
    root, kids = nodes[0], [nodes[i] for i in nodes[0]["children"]]
    assert [k["name"] for k in kids] == ["shaft", "cap", "hub"]
    assert kids[0]["translation"] == [0.0, 0.0, 0.0] and kids[0]["rotation"] == pytest.approx([ROT_X90["x"], 0, 0, ROT_X90["w"]])
    assert kids[1]["translation"] == pytest.approx([0.0, 0.235, 0.0])
    assert kids[2]["translation"] == pytest.approx([0.0, -0.23, 0.0])
    # root: the part-local frame (+Z up) turned into glTF +Y up: local +z maps to +y, local +y to -z.
    x, y, z, w = root["rotation"]
    rot = lambda v: (  # rotate v by the unit quaternion (x, y, z, w)
        (1 - 2 * (y * y + z * z)) * v[0] + 2 * (x * y - z * w) * v[1] + 2 * (x * z + y * w) * v[2],
        2 * (x * y + z * w) * v[0] + (1 - 2 * (x * x + z * z)) * v[1] + 2 * (y * z - x * w) * v[2],
        2 * (x * z - y * w) * v[0] + 2 * (y * z + x * w) * v[1] + (1 - 2 * (x * x + y * y)) * v[2],
    )
    assert rot((0, 0, 1)) == pytest.approx((0, 1, 0), abs=1e-12)
    assert rot((0, 1, 0)) == pytest.approx((0, 0, -1), abs=1e-12)
    assert rot((1, 0, 0)) == pytest.approx((1, 0, 0), abs=1e-12)


def test_gltf_voids_are_not_cut_and_say_so():
    glb = validate(glb_of(mounting_plate()))
    assert [m["name"] for m in glb.doc["meshes"]] == ["plate", "rib"]  # the bore is not a mesh
    extras = glb.doc["nodes"][0]["extras"]["kinetra"]
    assert extras["voids_cut"] is False
    (void,) = extras["voids"]
    assert void["id"] == "bore" and void["primitive"] == "cylinder" and void["dimensions"] == {"radius": 0.02, "length": 0.01}
    assert extras["part_id"] == "mounting-plate" and extras["material_id"] == ALU
    assert extras["shape"]["badge"] == "declared"
    assert extras["parameters"]["width"]["value"] == 0.12 and extras["parameters"]["width"]["badge"] == "declared"


def test_gltf_rejects_what_mass_properties_rejects_for_one_part():
    no_shape = part("p", [box("b", 1, 1, 1)]).model_copy(update={"shape": None})
    with pytest.raises(ShapeError, match="no shape"):
        part_glb(no_shape, catalog_material(ALU))
    with pytest.raises(ShapeError, match="unknown parameters"):
        glb_of(mounting_plate(), parameters={"nope": Quantity.model_validate(q(0.1))})
    with pytest.raises(ShapeError, match="outside the allowed range"):
        glb_of(mounting_plate(), parameters={"width": Quantity.model_validate(q(0.5))})
    with pytest.raises(ShapeError, match="need unit"):
        glb_of(mounting_plate(), parameters={"width": Quantity.model_validate(q(0.15, "kg"))})


def test_gltf_rejects_a_recipe_whose_components_overlap_like_mass_does():
    overlapping = part("p", [box("a", 0.2, 0.2, 0.2), sphere("b", 0.1, at=(0.1, 0, 0))])
    with pytest.raises(ShapeError, match="overlap"):
        glb_of(overlapping)
    with pytest.raises(ShapeError, match="overlap"):
        mass_properties(overlapping, catalog_material(ALU))


# --- the PBR material slot ----------------------------------------------------------------------------------------------


def test_gltf_srgb_to_linear_known_values():
    assert srgb_to_linear(0.0) == 0.0 and srgb_to_linear(1.0) == pytest.approx(1.0)
    assert srgb_to_linear(0.04045) == pytest.approx(0.04045 / 12.92)  # linear toe
    assert srgb_to_linear(0.5) == pytest.approx(0.2140411404, rel=1e-9)  # the standard's mid grey
    assert linear_base_color("#808080") == pytest.approx([0.2158605] * 3 + [1.0], rel=1e-6)  # 128/255 -> 0.2158605
    assert linear_base_color("#ff0000") == [1.0, 0.0, 0.0, 1.0]


@pytest.mark.parametrize("material_id", [e.material.id for e in load_material_catalog().entries])
def test_gltf_material_slot_is_the_catalog_entry_with_a_linear_color(material_id):
    entry = load_material_catalog().get(material_id)
    glb = validate(glb_of(mounting_plate(), material_id))
    (mat,) = glb.doc["materials"]
    srgb = entry.pbr.base_color.srgb
    expected = [int(srgb[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    expected_linear = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in expected]
    got = mat["pbrMetallicRoughness"]
    assert got["baseColorFactor"][:3] == pytest.approx(expected_linear, rel=1e-6) and got["baseColorFactor"][3] == 1.0
    assert got["metallicFactor"] == entry.pbr.metallic.value and got["roughnessFactor"] == entry.pbr.roughness.value
    # B-07 reflectance is 0.5 for all five: glTF core's fixed F0 is exact, so no extension is written.
    assert entry.pbr.reflectance.value == 0.5 and "extensions" not in mat and "extensionsUsed" not in glb.doc
    # badges and sources travel with the slot (V5)
    k = mat["extras"]["kinetra"]
    assert k["pbr_from_catalog"] is True and k["pbr"]["base_color"]["srgb"] == srgb
    assert k["pbr"]["base_color"]["badge"] == entry.pbr.base_color.badge.value
    assert k["pbr"]["roughness"]["source"]["ref"] == entry.pbr.roughness.source.ref


def test_gltf_aluminium_is_not_the_srgb_number_written_unconverted():
    # #e8eaea is 232/255 = 0.9098 sRGB; the linear factor is 0.807. Writing 0.9098 would draw it far too bright.
    (mat,) = validate(glb_of(mounting_plate(), ALU)).doc["materials"]
    r = mat["pbrMetallicRoughness"]["baseColorFactor"][0]
    assert r == pytest.approx(0.8069523, rel=1e-6) and abs(r - 232 / 255) > 0.1


def test_gltf_unknown_material_gets_the_neutral_fallback_not_another_look():
    glb = validate(sample_glb("sensor-mast-user-material"))
    (mat,) = glb.doc["materials"]
    assert mat["name"] == "user-grey"
    assert mat["pbrMetallicRoughness"]["baseColorFactor"] == pytest.approx([0.2158605] * 3 + [1.0], rel=1e-6)  # #808080
    assert (mat["pbrMetallicRoughness"]["metallicFactor"], mat["pbrMetallicRoughness"]["roughnessFactor"]) == (0.0, 0.5)
    k = mat["extras"]["kinetra"]
    assert k["pbr_from_catalog"] is False and k["pbr"]["base_color"]["badge"] == "default"
    slots, from_catalog = pbr_for(user_material())
    assert slots is FALLBACK_PBR and not from_catalog
    assert pbr_for(catalog_material(ALU))[1] is True
    # a user material whose id is a catalog id's look-alike is still not in the catalog
    assert pbr_for(user_material("al6061-t6-custom"))[1] is False


def test_gltf_reflectance_other_than_half_is_written_as_khr_materials_ior(monkeypatch):
    base = load_material_catalog().get(ALU).pbr
    odd = base.model_copy(update={"reflectance": base.reflectance.model_copy(update={"value": 0.35})})
    monkeypatch.setattr("kinetra_engine.parts.visual.pbr_for", lambda m: (odd, True))
    glb = validate(glb_of(mounting_plate()))
    assert glb.doc["extensionsUsed"] == ["KHR_materials_ior"]
    ior = glb.doc["materials"][0]["extensions"]["KHR_materials_ior"]["ior"]
    assert ior == pytest.approx((1 + 0.4 * 0.35) / (1 - 0.4 * 0.35), rel=1e-6)  # 1.3256
    # round trip: the F0 that ior gives equals Filament's 0.16 r^2
    assert ((ior - 1) / (ior + 1)) ** 2 == pytest.approx(0.16 * 0.35**2, rel=1e-5)
    assert ior_from_reflectance(0.5) == pytest.approx(1.5)


def test_gltf_uses_no_texture_images_or_external_files():
    for name in SAMPLES:
        doc = parse_glb(sample_glb(name)).doc
        assert not {"images", "textures", "samplers"} & set(doc)
        assert all("uri" not in b for b in doc["buffers"])
