"""B-02c: payload, ballast weight and payload mount (`packages/engine/src/kinetra_engine/parts/library/`).

DoD: the mass the user declares is the mass the compiler computes. Expected numbers below are textbook formulas written out
by hand (box, cylinder, sphere volumes; parallel-axis theorem), not read back from the compiler. The parts' dimensions and
default values are our own choice (`기본값`), not a real product; the mass a user declares is `사용자 선언`.
"""

from __future__ import annotations

import json
import math

import pytest
from gltf_samples import LIBRARY, catalog_material, library_part
from gltf_validate import validate

from kinetra_core import Badge, PartDef, Quantity
from kinetra_engine.parts import PartCache, ShapeError, collision_proxy, mass_properties, part_glb
from kinetra_engine.parts.__main__ import main
from kinetra_engine.parts.visual import part_gltf

AL, STEEL = "al6061-t6", "steel-a36"
RHO_AL = 2700.0  # al6061-t6 in the B-07 catalog


def declared(value: float, unit: str = "kg") -> Quantity:
    return Quantity(
        value=value,
        unit=unit,
        badge=Badge.DECLARED,
        source={"ref": "B-02c test: the user states this value", "declared_by": "test", "declared_at": "2026-11-11T00:00:00Z"},
    )


def length(value: float) -> Quantity:
    return declared(value, "m")


PAYLOAD = library_part("payload")
BALLAST = library_part("ballast-weight")
MOUNT = library_part("payload-mount")


# ---- the DoD: declared mass == computed mass --------------------------------------------------------------------------


@pytest.mark.parametrize("part_id", ["payload", "ballast-weight"])
def test_payload_computed_mass_is_the_declared_mass_over_the_whole_range(part_id):
    part = library_part(part_id)
    p = next(p for p in part.parameters if p.name == "mass")
    for kg in (p.min.value, p.default.value, 0.123456789, 1.0, 77.7, p.max.value):
        result = mass_properties(part, None, {"mass": declared(kg)})
        assert result.mass.value == pytest.approx(kg, rel=1e-12)
        # The density that spreads it is mass over volume, so mass = density x volume holds in the derivation too.
        assert result.derivation.density.value * result.volume.value == pytest.approx(kg, rel=1e-12)
        assert sum(c.mass for c in result.derivation.components) == pytest.approx(kg, rel=1e-12)


def test_payload_the_default_mass_is_the_defaults_value():
    assert mass_properties(PAYLOAD, None).mass.value == pytest.approx(1.0, rel=1e-12)
    assert mass_properties(BALLAST, None).mass.value == pytest.approx(2.0, rel=1e-12)


def test_payload_mass_does_not_depend_on_the_material_or_on_the_dimensions():
    base = mass_properties(PAYLOAD, None, {"mass": declared(3.5)})
    for material in (catalog_material(AL), catalog_material(STEEL)):
        assert mass_properties(PAYLOAD, material, {"mass": declared(3.5)}) == base  # the material is not read
    big = mass_properties(PAYLOAD, None, {"mass": declared(3.5), "length": length(0.4), "width": length(0.3), "height": length(0.3)})
    assert big.mass.value == pytest.approx(3.5, rel=1e-12)  # 20x the volume, same declared mass
    assert big.volume.value > 10 * base.volume.value
    assert big.derivation.density.value < base.derivation.density.value / 10  # the effective density fell instead


def test_payload_centre_of_mass_and_inertia_match_the_hand_calculation():
    # Default payload: body 0.12 x 0.08 x 0.048 centred z = 0.024; lid 0.104 x 0.064 x 0.012 centred z = 0.054; boss
    # r = 0.016, length 0.02, centred z = 0.07. Declared mass 2.5 kg spread uniformly over the volume.
    mass = 2.5
    v_body, v_lid, v_boss = 0.12 * 0.08 * 0.048, 0.104 * 0.064 * 0.012, math.pi * 0.016**2 * 0.02
    v = v_body + v_lid + v_boss
    m_body, m_lid, m_boss = (mass * x / v for x in (v_body, v_lid, v_boss))
    zc = (m_body * 0.024 + m_lid * 0.054 + m_boss * 0.07) / mass
    result = mass_properties(PAYLOAD, None, {"mass": declared(mass)})
    assert result.volume.value == pytest.approx(v, rel=1e-12)
    assert result.center_of_mass.x == pytest.approx(0.0, abs=1e-15) and result.center_of_mass.y == pytest.approx(0.0, abs=1e-15)
    assert result.center_of_mass.z == pytest.approx(zc, rel=1e-12)

    def box_i(m, a, b):  # about the axis perpendicular to the a x b face
        return m * (a * a + b * b) / 12.0

    dz = lambda z: z - zc  # noqa: E731
    ixx = (
        box_i(m_body, 0.08, 0.048) + m_body * dz(0.024) ** 2
        + box_i(m_lid, 0.064, 0.012) + m_lid * dz(0.054) ** 2
        + m_boss * (3 * 0.016**2 + 0.02**2) / 12.0 + m_boss * dz(0.07) ** 2
    )
    iyy = (
        box_i(m_body, 0.12, 0.048) + m_body * dz(0.024) ** 2
        + box_i(m_lid, 0.104, 0.012) + m_lid * dz(0.054) ** 2
        + m_boss * (3 * 0.016**2 + 0.02**2) / 12.0 + m_boss * dz(0.07) ** 2
    )
    izz = box_i(m_body, 0.12, 0.08) + box_i(m_lid, 0.104, 0.064) + m_boss * 0.016**2 / 2.0
    assert result.inertia.ixx == pytest.approx(ixx, rel=1e-9)
    assert result.inertia.iyy == pytest.approx(iyy, rel=1e-9)
    assert result.inertia.izz == pytest.approx(izz, rel=1e-9)
    assert (result.inertia.ixy, result.inertia.ixz, result.inertia.iyz) == pytest.approx((0.0, 0.0, 0.0), abs=1e-15)


def test_payload_inertia_scales_with_the_declared_mass_and_the_centre_does_not_move():
    one = mass_properties(PAYLOAD, None, {"mass": declared(1.0)})
    four = mass_properties(PAYLOAD, None, {"mass": declared(4.0)})
    assert four.center_of_mass == one.center_of_mass
    for name in ("ixx", "iyy", "izz"):
        assert getattr(four.inertia, name) == pytest.approx(4.0 * getattr(one.inertia, name), rel=1e-12)


def test_payload_the_shape_moves_the_centre_of_mass_not_the_mass():
    low = mass_properties(PAYLOAD, None, {"height": length(0.03)})
    high = mass_properties(PAYLOAD, None, {"height": length(0.3)})
    assert low.mass.value == high.mass.value == pytest.approx(1.0, rel=1e-12)
    assert high.center_of_mass.z > 5 * low.center_of_mass.z  # a taller payload carries its mass higher


def test_ballast_weight_hand_calculation():
    # radius 0.05, thickness 0.03: disc r 0.05 x 0.03 centred z 0.015; neck r 0.01 x 0.02 centred z 0.04; knob sphere
    # r 0.0175 centred z 0.0675 (touching the neck's top face at z = 0.05). Declared 2 kg.
    mass = 2.0
    v_d, v_n, v_k = math.pi * 0.05**2 * 0.03, math.pi * 0.01**2 * 0.02, 4.0 / 3.0 * math.pi * 0.0175**3
    v = v_d + v_n + v_k
    m_d, m_n, m_k = (mass * x / v for x in (v_d, v_n, v_k))
    zc = (m_d * 0.015 + m_n * 0.04 + m_k * 0.0675) / mass
    result = mass_properties(BALLAST, None)
    assert result.mass.value == pytest.approx(mass, rel=1e-12)
    assert result.center_of_mass.z == pytest.approx(zc, rel=1e-12)
    izz = m_d * 0.05**2 / 2 + m_n * 0.01**2 / 2 + 0.4 * m_k * 0.0175**2
    assert result.inertia.izz == pytest.approx(izz, rel=1e-9)
    ixx = (
        m_d * (3 * 0.05**2 + 0.03**2) / 12 + m_d * (0.015 - zc) ** 2
        + m_n * (3 * 0.01**2 + 0.02**2) / 12 + m_n * (0.04 - zc) ** 2
        + 0.4 * m_k * 0.0175**2 + m_k * (0.0675 - zc) ** 2
    )
    assert result.inertia.ixx == pytest.approx(ixx, rel=1e-9)
    # A heavier, smaller weight: the disc grows with the radius, so the same 2 kg sits in less volume and lower.
    assert mass_properties(BALLAST, None, {"radius": declared(0.02, "m")}).mass.value == pytest.approx(2.0, rel=1e-12)


# ---- the declared mass is an input with its own badge ------------------------------------------------------------------


def test_payload_derivation_names_the_declared_mass_and_its_badge():
    d = mass_properties(PAYLOAD, None, {"mass": declared(2.0)}).derivation
    assert d.material_id is None
    mass_use = next(u for u in d.parameters if u.name == "mass")
    assert mass_use.value.badge is Badge.DECLARED and mass_use.value.value == 2.0
    assert d.density.badge is Badge.DECLARED  # the spread density is exactly as good as the declaration
    assert Badge.DECLARED in d.input_badges and "mass is declared (mass_parameter)" in d.assumptions[0]
    # The default is our placeholder: its badge says so (not a measurement of any real payload).
    d0 = mass_properties(PAYLOAD, None).derivation
    assert d0.density.badge is Badge.DEFAULT and "PLACEHOLDER" in next(u for u in d0.parameters if u.name == "mass").value.source.ref


def test_payload_effective_density_is_mass_over_volume():
    result = mass_properties(PAYLOAD, None, {"mass": declared(2.0)})
    assert result.derivation.density.value == pytest.approx(2.0 / result.volume.value, rel=1e-12)
    assert result.derivation.density.unit.value == "kg/m^3"


# ---- the mount is an ordinary material part -----------------------------------------------------------------------------


def test_payload_mount_mass_is_density_times_volume_and_needs_a_material():
    t, w = 0.006, 0.004  # base plate thickness, wall thickness (fixed in the definition)
    length_, width, h = 0.12, 0.08, 0.04
    v = (
        (length_ + 2 * w) * (width + 2 * w) * t  # plate
        + 2 * length_ * w * h  # two rails
        + 2 * w * (width + 2 * w) * (h / 2)  # two end walls
    )
    result = mass_properties(MOUNT, catalog_material(AL))
    assert result.volume.value == pytest.approx(v, rel=1e-12)
    assert result.mass.value == pytest.approx(RHO_AL * v, rel=1e-12)
    # The end walls are half as tall as the rails: a low cradle the payload can be lifted out of.
    xs = [c for c in result.derivation.components if c.id.startswith("end")]
    assert len(xs) == 2 and all(c.dimension("size_z") == pytest.approx(h / 2) for c in xs)
    with pytest.raises(ShapeError, match="needs a material"):
        mass_properties(MOUNT, None)


@pytest.mark.parametrize("name,lo,hi", [("length", 0.06, 0.4), ("width", 0.04, 0.3), ("wall_height", 0.02, 0.2)])
def test_payload_mount_dimension_change_changes_the_mass_as_the_formula_says(name, lo, hi):
    def volume(l, w, h, t=0.006, wall=0.004):
        return (l + 2 * wall) * (w + 2 * wall) * t + 2 * l * wall * h + 2 * wall * (w + 2 * wall) * (h / 2)

    base = {"length": 0.12, "width": 0.08, "wall_height": 0.04}
    for value in (lo, hi):
        dims = {**base, name: value}
        got = mass_properties(MOUNT, catalog_material(AL), {name: length(value)})
        assert got.mass.value == pytest.approx(RHO_AL * volume(dims["length"], dims["width"], dims["wall_height"]), rel=1e-12)


def test_payload_the_mount_holds_the_payload_it_is_sized_for():
    # Inside the cradle the payload's footprint must fit: the mount's inside length and width are the payload's defaults.
    assert next(p for p in MOUNT.parameters if p.name == "length").default.value == next(p for p in PAYLOAD.parameters if p.name == "length").default.value
    assert next(p for p in MOUNT.parameters if p.name == "width").default.value == next(p for p in PAYLOAD.parameters if p.name == "width").default.value


# ---- definition rules ---------------------------------------------------------------------------------------------------


def _with(part: PartDef, **change) -> dict:
    d = json.loads(part.model_dump_json(exclude_none=True))
    d.update(change)
    return d


def test_payload_definition_rejects_a_mass_parameter_that_is_not_a_positive_kg_parameter():
    with pytest.raises(ValueError, match="not a parameter"):
        PartDef.model_validate(_with(PAYLOAD, mass_parameter="weight"))
    with pytest.raises(ValueError, match="must be in 'kg'"):
        PartDef.model_validate(_with(PAYLOAD, mass_parameter="length"))
    d = _with(PAYLOAD)
    d["parameters"][0]["min"]["value"] = 0.0
    d["parameters"][0]["default"]["value"] = 0.0
    with pytest.raises(ValueError, match="above zero"):
        PartDef.model_validate(d)
    d = _with(PAYLOAD)
    del d["shape"]
    with pytest.raises(ValueError, match="needs a shape"):
        PartDef.model_validate(d)


def test_payload_mass_outside_the_range_or_in_the_wrong_unit_is_rejected():
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(PAYLOAD, None, {"mass": declared(0.001)})
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(PAYLOAD, None, {"mass": declared(1000.0)})
    with pytest.raises(ShapeError, match="need unit 'kg'"):
        mass_properties(PAYLOAD, None, {"mass": declared(1.0, "m")})
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(PAYLOAD, None, {"weight": declared(1.0)})


def test_payload_library_files_are_valid_and_every_number_has_an_honest_badge():
    files = sorted(p.stem for p in LIBRARY.glob("*.json"))
    assert {"payload", "ballast-weight", "payload-mount"} <= set(files)
    for part_id in ("payload", "ballast-weight", "payload-mount"):
        part = library_part(part_id)
        assert part.id == part_id and PartDef.model_validate_json(part.model_dump_json()) == part
        badges = {p.default.badge for p in part.parameters} | {p.min.badge for p in part.parameters} | {p.max.badge for p in part.parameters}
        badges |= {part.shape.badge} | {s.badge for s in part.snap_points}
        # We cite nothing here: there is no real product behind these dimensions or masses.
        assert badges == {Badge.DEFAULT}
        assert all("not a real product" in p.default.source.ref or "PLACEHOLDER" in p.default.source.ref for p in part.parameters)


# ---- snap points --------------------------------------------------------------------------------------------------------


def _snap(part: PartDef, id: str, **values):
    s = next(s for s in part.snap_points if s.id == id)
    v = {p.name: p.default.value for p in part.parameters} | values
    return s, s.position.evaluate(v)


def _normal(q) -> tuple[float, float, float]:
    """The snap frame's +z in the part frame: the third column of the rotation matrix."""
    return (2 * (q.x * q.z + q.y * q.w), 2 * (q.y * q.z - q.x * q.w), 1 - 2 * (q.x * q.x + q.y * q.y))


def test_payload_snap_points_follow_the_parameters_and_face_outwards():
    s, at = _snap(PAYLOAD, "top")
    assert at == pytest.approx((0.0, 0.0, 0.08))  # boss top: height 0.06 + boss length 0.02
    assert _snap(PAYLOAD, "top", height=0.3)[1][2] == pytest.approx(0.32)
    assert _normal(s.orientation) == pytest.approx((0, 0, 1), abs=1e-12)
    s, at = _snap(PAYLOAD, "base")
    assert at == (0.0, 0.0, 0.0) and _normal(s.orientation) == pytest.approx((0, 0, -1), abs=1e-12)

    s, at = _snap(BALLAST, "top")
    assert at == pytest.approx((0.0, 0.0, 0.02 + 0.03 + 0.7 * 0.05))  # knob top = thickness + neck + 2 x knob radius
    assert _snap(BALLAST, "top", radius=0.2, thickness=0.15)[1][2] == pytest.approx(0.02 + 0.15 + 0.14)

    s, at = _snap(MOUNT, "seat")
    assert at == (0.0, 0.0, 0.006) and _normal(s.orientation) == pytest.approx((0, 0, 1), abs=1e-12)
    left, at_l = _snap(MOUNT, "side-left")
    right, at_r = _snap(MOUNT, "side-right")
    assert at_l == pytest.approx((0.0, 0.004 + 0.04, 0.006 + 0.02)) and at_r == pytest.approx((0.0, -(0.004 + 0.04), 0.006 + 0.02))
    assert _normal(left.orientation) == pytest.approx((0, 1, 0), abs=1e-12)
    assert _normal(right.orientation) == pytest.approx((0, -1, 0), abs=1e-12)
    assert _snap(MOUNT, "side-left", width=0.3, wall_height=0.2)[1] == pytest.approx((0.0, 0.004 + 0.15, 0.006 + 0.1))


def test_payload_seat_and_base_are_a_matching_pair_of_tags():
    base = next(s for s in PAYLOAD.snap_points if s.id == "base")
    seat = next(s for s in MOUNT.snap_points if s.id == "seat")
    assert base.kind in seat.accepts and seat.kind in base.accepts  # B-04b matches `kind` against `accepts`, both ways
    assert next(s for s in BALLAST.snap_points if s.id == "base").kind == base.kind  # the weight sits in the cradle too


def test_payload_seated_payload_sits_on_the_mounts_plate():
    """Snap `base` (z = 0) on snap `seat` (z = plate thickness): the payload's body starts exactly where the plate ends."""
    plate = next(c for c in mass_properties(MOUNT, catalog_material(AL)).derivation.components if c.id == "plate")
    plate_top = plate.center[2] + plate.dimension("size_z") / 2
    assert plate_top == pytest.approx(_snap(MOUNT, "seat")[1][2], abs=1e-15)
    body = next(c for c in mass_properties(PAYLOAD, None).derivation.components if c.id == "body")
    assert body.center[2] - body.dimension("size_z") / 2 == pytest.approx(_snap(PAYLOAD, "base")[1][2], abs=1e-15)


# ---- collision proxy, visual, cache, command line -----------------------------------------------------------------------


@pytest.mark.parametrize("part_id", ["payload", "ballast-weight", "payload-mount"])
def test_payload_parts_have_an_exact_collision_proxy_and_a_valid_glb(part_id):
    part = library_part(part_id)
    material = catalog_material(AL) if part_id == "payload-mount" else None
    proxy = collision_proxy(part)
    assert proxy.volume_error.value == 0.0 and proxy.filled_voids == ()  # no holes: the proxy is the recipe
    assert len(proxy.geoms) == len(part.shape.components) >= 3  # not one box or one cylinder
    glb = validate(part_glb(part, material))
    assert len(glb.doc["meshes"]) == len(part.shape.components)


def test_payload_without_a_material_is_drawn_with_the_neutral_look_and_says_so():
    doc, _ = part_gltf(PAYLOAD, None)
    (mat,) = doc["materials"]
    assert mat["name"] == "unassigned" and mat["extras"]["kinetra"]["pbr_from_catalog"] is False
    assert doc["nodes"][0]["extras"]["kinetra"]["material_id"] is None
    # A material the user does assign only picks the look; the mass is still the declared one.
    steel, _ = part_gltf(PAYLOAD, catalog_material(STEEL))
    assert steel["materials"][0]["name"] == STEEL


def test_payload_cache_serves_every_material_from_one_declared_mass_entry():
    cache = PartCache(max_entries=8)
    a = cache.mass_properties(PAYLOAD, None)
    b = cache.mass_properties(PAYLOAD, catalog_material(AL))
    c = cache.mass_properties(PAYLOAD, catalog_material(STEEL))
    assert a is b is c and cache.stats().misses == 1 and cache.stats().hits == 2
    assert a == mass_properties(PAYLOAD, None)
    # A different declared mass is a different entry, with that mass.
    assert cache.mass_properties(PAYLOAD, None, {"mass": declared(9.0)}).mass.value == pytest.approx(9.0, rel=1e-12)
    # The mount reads its material, so materials are different entries.
    m1, m2 = cache.mass_properties(MOUNT, catalog_material(AL)), cache.mass_properties(MOUNT, catalog_material(STEEL))
    assert m1.mass.value != m2.mass.value
    assert cache.part_glb(PAYLOAD, None) == part_glb(PAYLOAD, None)


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, (json.loads(out.out) if out.out.strip() else None), out.err


def test_payload_check_command_needs_no_material_for_a_declared_mass(capsys, tmp_path):
    code, report, err = _run(capsys, LIBRARY / "payload.json", "--out", tmp_path)
    assert code == 0 and err == ""
    assert report["material"] is None and report["mass_declared_by"] == "mass"
    assert report["mass_kg"] == pytest.approx(1.0, rel=1e-12)
    assert report["input_badges"] == ["default"]
    validate((tmp_path / "payload.glb").read_bytes())


def test_payload_check_command_still_needs_a_material_for_any_other_part(capsys):
    code, report, err = _run(capsys, LIBRARY / "payload-mount.json")
    assert (code, report) == (1, None) and "--material is required" in err
    code, report, err = _run(capsys, LIBRARY / "payload-mount.json", "--material", AL)
    assert code == 0 and report["mass_declared_by"] is None
    assert report["mass_kg"] == pytest.approx(RHO_AL * report["volume_m3"], rel=1e-12)


def test_payload_an_instance_without_material_in_a_design_gets_its_declared_mass():
    """The path the studio takes: a DesignSpec instance of the payload with no material and its own `mass`, then the
    instance's parameter values go to the compiler. The instance's value is a `ParamValue`, a `사용자 선언` quantity."""
    from kinetra_core import DesignSpec, ParamValue

    mount_material = catalog_material(AL)
    pose = {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        "badge": "declared",
        "source": {"ref": "B-02c test pose", "declared_by": "test", "declared_at": "2026-11-11T00:00:00Z"},
    }
    mass = {"name": "mass", **json.loads(declared(7.25).model_dump_json())}
    design = DesignSpec.model_validate(
        {
            "materials": [json.loads(mount_material.model_dump_json())],
            "parts": [json.loads(PAYLOAD.model_dump_json()), json.loads(MOUNT.model_dump_json())],
            "instances": [
                {"id": "cargo-1", "part": "payload", "parameters": [mass], "pose": pose},  # no material
                {"id": "mount-1", "part": "payload-mount", "material": AL, "pose": pose},
            ],
        }
    )
    cargo = design.instances[0]
    assert cargo.material is None and isinstance(cargo.parameters[0], ParamValue)
    result = mass_properties(PAYLOAD, None, {p.name: p for p in cargo.parameters})
    assert result.mass.value == pytest.approx(7.25, rel=1e-12)
    assert next(u for u in result.derivation.parameters if u.name == "mass").value.badge is Badge.DECLARED  # the user's badge travels with the number
    total = result.mass.value + mass_properties(MOUNT, mount_material).mass.value
    assert total == pytest.approx(7.25 + RHO_AL * mass_properties(MOUNT, mount_material).volume.value, rel=1e-12)
