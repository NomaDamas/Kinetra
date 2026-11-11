"""B-15: the separator part `separator` (`packages/engine/src/kinetra_engine/parts/library/separator.json`).

DoD: a declared-mass coupling with a declared separation impulse [N*s] (0 allowed, badge `사용자 선언` or `기본값`); no field for an
energy source; the total mass and centre of mass before release are the sum of the parts'; a negative impulse or a missing or
wrong badge is rejected. Expected numbers are textbook formulas written out by hand (cylinder volume and inertia, the
parallel-axis theorem, the centroid of a stack), not read back from the code. Dimensions and default values are our own choice
(`기본값`), not a real product; the mass and impulse a user states are `사용자 선언`.
"""

from __future__ import annotations

import copy
import json
import math

import pytest
from gltf_samples import LIBRARY, catalog_material, library_part
from gltf_validate import validate
from pydantic import ValidationError

from kinetra_core import (
    Badge,
    Confidence,
    DesignSpec,
    ParamValue,
    PartDef,
    PartRole,
    Quantity,
)
from kinetra_engine.parts import (
    SEPARATION_ASSUMPTION_LABEL,
    PartCache,
    SeparatorError,
    ShapeError,
    collision_proxy,
    mass_properties,
    part_glb,
    separation_assumption,
    separator_from_part,
)
from kinetra_engine.parts.__main__ import main

SEPARATOR = library_part("separator")
PAYLOAD = library_part("payload")
PATH = LIBRARY / "separator.json"
SRC = {"ref": "B-15 test: the user states this value", "declared_by": "test", "declared_at": "2026-11-12T00:00:00Z"}

# defaults of the separator (library file): mass 0.5 kg, radius 0.05 m, length 0.04 m, impulse 0 N*s
M, R, L = 0.5, 0.05, 0.04
LOWER_TOP = 0.02 + 0.06  # z of the payload's `top` snap point at the default height 0.06 m


def declared(value: float, unit: str) -> Quantity:
    return Quantity(value=value, unit=unit, badge=Badge.DECLARED, source=SRC)


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def param(d: dict, name: str) -> dict:
    return next(p for p in d["parameters"] if p["name"] == name)


def with_impulse(d: dict, **fields) -> dict:
    for key in ("default", "min", "max"):
        if key in fields:
            param(d, "separation_impulse")[key] = {**param(d, "separation_impulse")[key], **fields[key]}
    return d


# ---- the part: declared mass, dimensions, hand-calculated shape --------------------------------------------------------------


def test_separator_is_the_separator_role_with_a_declared_mass_and_no_material():
    assert SEPARATOR.role is PartRole.SEPARATOR and SEPARATOR.mass_parameter == "mass"
    assert mass_properties(SEPARATOR, None).mass.value == pytest.approx(M, rel=1e-12)


def test_separator_computed_mass_is_the_declared_mass_over_the_whole_range():
    p = next(p for p in SEPARATOR.parameters if p.name == "mass")
    for kg in (p.min.value, p.default.value, 0.123456789, 12.5, p.max.value):
        result = mass_properties(SEPARATOR, None, {"mass": declared(kg, "kg")})
        assert result.mass.value == pytest.approx(kg, rel=1e-12)
        assert next(u for u in result.derivation.parameters if u.name == "mass").value.badge is Badge.DECLARED


def test_separator_mass_does_not_depend_on_the_material_or_the_dimensions():
    base = mass_properties(SEPARATOR, None, {"mass": declared(3.5, "kg")})
    assert mass_properties(SEPARATOR, catalog_material("al6061-t6"), {"mass": declared(3.5, "kg")}) == base  # not read
    big = mass_properties(SEPARATOR, None, {"mass": declared(3.5, "kg"), "radius": declared(0.3, "m"), "length": declared(0.2, "m")})
    assert big.mass.value == pytest.approx(3.5, rel=1e-12)
    assert big.volume.value > 100 * base.volume.value


def test_separator_volume_centre_and_inertia_match_the_hand_calculation():
    # Three coaxial cylinders along z: lower flange r = R, length 0.2 L, centred z = -0.4 L; waist r = 0.8 R, length 0.6 L,
    # centred z = 0; upper flange r = R, length 0.2 L, centred z = +0.4 L. Declared mass 2.5 kg spread uniformly.
    mass = 2.5
    v_flange, v_waist = math.pi * R**2 * 0.2 * L, math.pi * (0.8 * R) ** 2 * 0.6 * L
    v = 2 * v_flange + v_waist
    m_flange, m_waist = mass * v_flange / v, mass * v_waist / v
    result = mass_properties(SEPARATOR, None, {"mass": declared(mass, "kg")})
    assert result.volume.value == pytest.approx(v, rel=1e-12)
    # Symmetric about the origin: the centre of mass is the origin.
    assert (result.center_of_mass.x, result.center_of_mass.y, result.center_of_mass.z) == pytest.approx((0.0, 0.0, 0.0), abs=1e-15)

    def cyl_ixx(m, r, h):  # about a diameter through the centre
        return m * (3 * r * r + h * h) / 12.0

    ixx = 2 * (cyl_ixx(m_flange, R, 0.2 * L) + m_flange * (0.4 * L) ** 2) + cyl_ixx(m_waist, 0.8 * R, 0.6 * L)
    izz = 2 * m_flange * R**2 / 2.0 + m_waist * (0.8 * R) ** 2 / 2.0
    assert result.inertia.ixx == pytest.approx(ixx, rel=1e-9)
    assert result.inertia.iyy == pytest.approx(ixx, rel=1e-9)
    assert result.inertia.izz == pytest.approx(izz, rel=1e-9)
    assert (result.inertia.ixy, result.inertia.ixz, result.inertia.iyz) == pytest.approx((0.0, 0.0, 0.0), abs=1e-15)


def test_separator_dimension_changes_reach_the_volume_and_the_faces():
    for radius, length in ((0.02, 0.02), (0.3, 0.2), (0.12, 0.07)):
        values = {"radius": declared(radius, "m"), "length": declared(length, "m")}
        v = 2 * math.pi * radius**2 * 0.2 * length + math.pi * (0.8 * radius) ** 2 * 0.6 * length
        assert mass_properties(SEPARATOR, None, values).volume.value == pytest.approx(v, rel=1e-12)
        sep = separator_from_part(SEPARATOR, values)
        assert sep.position_a == pytest.approx((0.0, 0.0, 0.5 * length), abs=1e-15)
        assert sep.position_b == pytest.approx((0.0, 0.0, -0.5 * length), abs=1e-15)


def test_separator_out_of_range_and_unknown_parameters_are_rejected():
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(SEPARATOR, None, {"radius": declared(0.001, "m")})
    with pytest.raises(ShapeError, match="outside the allowed range"):
        separator_from_part(SEPARATOR, {"separation_impulse": declared(1e6, "N*s")})
    with pytest.raises(ShapeError, match="unknown parameters"):
        separator_from_part(SEPARATOR, {"charge": declared(1.0, "kg")})


# ---- the DoD test: total mass and centre of mass before release are the sum of the parts' -------------------------------------


def world_com(part: PartDef, instance_mass: float, z0: float):
    """(mass, COM z in the world) of an instance of `part` placed upright at height z0, from the compiler."""
    r = mass_properties(part, None, {"mass": declared(instance_mass, "kg")})
    return r.mass.value, z0 + r.center_of_mass.z


POSE = {
    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    "badge": "declared",
    "source": SRC,
}


def stack(separator_overrides=(), joint_kind="fixed", extra_joint=None) -> DesignSpec:
    """Lower payload, separator, upper payload, stacked: the lower payload's `top` face (z = 0.06) joined to the separator's
    `face_b` (local z = -0.02), the separator's `face_a` (local z = +0.02) joined to the upper payload's `base`. The payload's `top`
    snap is at z = 0.02 + height = 0.08 m (the library file), so the separator's origin is at 0.10 and the upper payload's base at 0.12."""
    def inst(id, part, z, params=()):
        pose = {**POSE, "position": {"x": 0.0, "y": 0.0, "z": z}}
        return {"id": id, "part": part, "parameters": list(params), "pose": pose}

    mass = lambda v: {"name": "mass", **json.loads(declared(v, "kg").model_dump_json())}  # noqa: E731
    joints = [
        {"id": "hold-lower", "kind": joint_kind, "a": {"instance": "lower", "snap_point": "top"}, "b": {"instance": "sep", "snap_point": "face_b"}},
        {"id": "hold-upper", "kind": "fixed", "a": {"instance": "sep", "snap_point": "face_a"}, "b": {"instance": "upper", "snap_point": "base"}},
    ]
    return DesignSpec.model_validate(
        {
            "parts": [json.loads(PAYLOAD.model_dump_json()), json.loads(SEPARATOR.model_dump_json())],
            "instances": [
                inst("lower", "payload", 0.0, [mass(3.0)]),
                inst("sep", "separator", LOWER_TOP + 0.5 * L, [mass(0.5), *separator_overrides]),
                inst("upper", "payload", LOWER_TOP + L, [mass(2.0)]),
            ],
            "joints": joints + ([extra_joint] if extra_joint else []),
        }
    )


def test_separator_total_mass_and_centre_of_mass_before_release_are_the_sum_of_the_parts():
    design = stack()
    # Hand: the payload's centre of mass above its base is (v_body 0.024 + v_lid 0.054 + v_boss 0.07 weighted by volume) / v.
    v_body, v_lid, v_boss = 0.12 * 0.08 * 0.048, 0.104 * 0.064 * 0.012, math.pi * 0.016**2 * 0.02
    zc = (v_body * 0.024 + v_lid * 0.054 + v_boss * 0.07) / (v_body + v_lid + v_boss)
    masses, zs = (3.0, 0.5, 2.0), (zc, LOWER_TOP + 0.5 * L, LOWER_TOP + L + zc)  # lower payload, separator (centre is its origin), upper payload
    total, com_z = sum(masses), sum(m * z for m, z in zip(masses, zs)) / sum(masses)
    assert total == pytest.approx(5.5, rel=1e-15)

    got = [
        world_com(PAYLOAD, 3.0, design.instances[0].pose.position.z),
        world_com(SEPARATOR, 0.5, design.instances[1].pose.position.z),
        world_com(PAYLOAD, 2.0, design.instances[2].pose.position.z),
    ]
    assert sum(m for m, _ in got) == pytest.approx(total, rel=1e-12)
    assert sum(m * z for m, z in got) / sum(m for m, _ in got) == pytest.approx(com_z, rel=1e-12)


def test_separator_stack_faces_meet_where_the_joints_say():
    """At the stored poses the joined snap points coincide, with opposite outward normals (+z of `face_a`, -z of `face_b`)."""
    design = stack()
    sep = separator_from_part(SEPARATOR)
    z = {i.id: i.pose.position.z for i in design.instances}
    lower_top = z["lower"] + next(s for s in PAYLOAD.snap_points if s.id == "top").position.z.evaluate({"height": 0.06})
    assert lower_top == pytest.approx(LOWER_TOP, abs=1e-15)
    assert z["sep"] + sep.position_b[2] == pytest.approx(lower_top, abs=1e-15)
    assert z["sep"] + sep.position_a[2] == pytest.approx(z["upper"] + 0.0, abs=1e-15)  # the upper payload's `base` is its origin
    assert sep.direction_a == pytest.approx((0.0, 0.0, 1.0), abs=1e-15)
    assert sep.direction_b == pytest.approx((0.0, 0.0, -1.0), abs=1e-15)


# ---- the separation impulse: badge, sign, zero ---------------------------------------------------------------------------------


def test_separator_default_impulse_is_zero_with_the_default_badge():
    sep = separator_from_part(SEPARATOR)
    assert sep.impulse.value == 0.0 and sep.impulse.unit.value == "N*s" and sep.impulse.badge is Badge.DEFAULT


@pytest.mark.parametrize("value", [0.0, 1e-9, 12.5, 1000.0])
def test_separator_a_declared_impulse_travels_with_its_badge(value):
    sep = separator_from_part(SEPARATOR, {"separation_impulse": declared(value, "N*s")})
    assert sep.impulse.value == value and sep.impulse.badge is Badge.DECLARED
    assert sep.impulse.source.declared_by == "test"  # the user's source, not the definition's


def test_separator_zero_impulse_is_allowed_in_the_definition_and_in_a_design():
    d = with_impulse(load(), default={"value": 0.0}, min={"value": 0.0})
    assert PartDef.model_validate(d).role is PartRole.SEPARATOR
    stack([{"name": "separation_impulse", **json.loads(declared(0.0, "N*s").model_dump_json())}])  # validates


@pytest.mark.parametrize("field", ["default", "min"])
@pytest.mark.parametrize("value", [-1e-12, -1.0])
def test_separator_definition_with_a_negative_impulse_is_rejected(field, value):
    d = with_impulse(load(), **{field: {"value": value}})
    with pytest.raises(ValidationError):
        PartDef.model_validate(d)


def test_separator_negative_impulse_on_an_instance_is_rejected_by_the_design():
    bad = {"name": "separation_impulse", **json.loads(declared(-0.001, "N*s").model_dump_json())}
    with pytest.raises(ValidationError, match="outside the part's range"):
        stack([bad])
    with pytest.raises(ShapeError, match="outside the allowed range"):
        separator_from_part(SEPARATOR, {"separation_impulse": declared(-0.001, "N*s")})


def test_separator_impulse_without_a_badge_or_source_is_rejected():
    d = load()
    del param(d, "separation_impulse")["default"]["badge"]
    with pytest.raises(ValidationError, match="badge"):
        PartDef.model_validate(d)
    d = load()
    del param(d, "separation_impulse")["max"]["source"]
    with pytest.raises(ValidationError, match="source"):
        PartDef.model_validate(d)
    with pytest.raises(ValidationError):
        Quantity.model_validate({"value": 1.0, "unit": "N*s"})
    bare = {"name": "separation_impulse", "value": 1.0, "unit": "N*s"}
    with pytest.raises(ValidationError):
        stack([bare])


@pytest.mark.parametrize("badge", ["cite", "estimate", "sim"])
def test_separator_impulse_badges_other_than_declared_and_default_are_rejected(badge):
    extra = {"locator": "p. 1"} if badge == "cite" else {}
    d = with_impulse(load(), default={"badge": badge, "source": {"ref": "somewhere", **extra}})
    with pytest.raises(ValidationError, match="'declared' or 'default'"):
        PartDef.model_validate(d)
    for key in ("min", "max"):
        d = with_impulse(load(), **{key: {"badge": badge, "source": {"ref": "somewhere", **extra}}})
        with pytest.raises(ValidationError, match="'declared' or 'default'"):
            PartDef.model_validate(d)
    on_instance = {"name": "separation_impulse", "value": 1.0, "unit": "N*s", "badge": badge, "source": {"ref": "somewhere", **extra}}
    with pytest.raises(ValidationError, match="declared or a default"):
        stack([on_instance])
    with pytest.raises(SeparatorError, match="only 'declared' or 'default'"):
        separator_from_part(SEPARATOR, {"separation_impulse": Quantity(value=1.0, unit="N*s", badge=badge, source={"ref": "somewhere", **extra})})


def test_separator_impulse_unit_must_be_newton_seconds_and_nothing_non_finite():
    d = load()
    p = param(d, "separation_impulse")
    p["unit"] = "N"
    for key in ("default", "min", "max"):
        p[key]["unit"] = "N"
    with pytest.raises(ValidationError, match="impulse in 'N\\*s'"):
        PartDef.model_validate(d)
    with pytest.raises(ValidationError):
        declared(math.nan, "N*s")
    with pytest.raises(ValidationError):
        declared(math.inf, "N*s")


def test_separator_definition_needs_its_impulse_mass_and_both_faces():
    d = load()
    d["parameters"] = [p for p in d["parameters"] if p["name"] != "separation_impulse"]
    with pytest.raises(ValidationError, match="needs the parameter 'separation_impulse'"):
        PartDef.model_validate(d)
    d = load()
    del d["mass_parameter"]
    with pytest.raises(ValidationError, match="needs a mass_parameter"):
        PartDef.model_validate(d)
    for face in ("face_a", "face_b"):
        d = load()
        d["snap_points"] = [s for s in d["snap_points"] if s["id"] != face]
        with pytest.raises(ValidationError, match=f"needs the snap point '{face}'"):
            PartDef.model_validate(d)


# ---- no energy source: nothing in the schema, the part or the result can carry one ---------------------------------------------

FORBIDDEN = ("explos", "pyro", "powder", "charge", "igni", "propell", "fuel", "gas", "chem", "detonat", "spring", "energy", "bolt", "squib", "burn", "combust")


def field_names(schema: dict) -> set[str]:
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            out.update(o.get("properties", {}))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(schema)
    return out


def test_separator_the_schema_and_the_result_have_no_field_for_an_energy_source():
    from dataclasses import fields

    from kinetra_engine.parts import Separator

    for name in field_names(PartDef.model_json_schema()) | {f.name for f in fields(Separator)}:
        assert not any(word in name for word in FORBIDDEN), name
    assert "separation_impulse" in {p.name for p in SEPARATOR.parameters}


def test_separator_the_definition_has_no_specs_no_curves_and_only_mass_dimensions_and_impulse():
    assert SEPARATOR.specs == () and SEPARATOR.curves == ()
    assert [(p.name, p.unit.value) for p in SEPARATOR.parameters] == [("mass", "kg"), ("radius", "m"), ("length", "m"), ("separation_impulse", "N*s")]
    text = PATH.read_text(encoding="utf-8").lower()
    for word in FORBIDDEN:
        # the part's own text mentions what it does not model; the only allowed hits are those statements and the part's own name
        for hit in (i for i in range(len(text)) if text.startswith(word, i)):
            line = text[text.rfind("\n", 0, hit) + 1 : text.find("\n", hit)]
            assert "no energy source" in line or "not modelled" in line, (word, line)


def test_separator_adding_a_spec_a_curve_or_a_foreign_parameter_is_rejected():
    d = load()
    d["specs"] = [{"name": "stored_energy", **json.loads(declared(5.0, "J").model_dump_json())}]
    with pytest.raises(ValidationError, match="no specs"):
        PartDef.model_validate(d)
    d = load()
    d["parameters"].append(copy.deepcopy({**param(d, "mass"), "name": "stored_energy", "unit": "J"}))
    p = d["parameters"][-1]
    for key in ("default", "min", "max"):
        p[key] = {**p[key], "unit": "J"}
    with pytest.raises(ValidationError, match="'stored_energy' is in 'J'"):
        PartDef.model_validate(d)
    d = load()
    d["curves"] = [{"name": "push", "curve": {"x_unit": "s", "y_unit": "N", "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}], **{"badge": "declared", "source": SRC}}}]
    with pytest.raises(ValidationError, match="no curves"):
        PartDef.model_validate(d)


def test_separator_is_not_a_versus_part_and_has_no_export_policy_field():
    # HW-02a (S2) decides `export_policy`; this part neither has the field nor a value for it.
    assert "export_policy" not in PartDef.model_json_schema()["properties"]
    assert "export_policy" not in load() and not hasattr(SEPARATOR, "export_policy")
    with pytest.raises(ValidationError):
        PartDef.model_validate({**load(), "export_policy": "free"})


# ---- the assumption table row -------------------------------------------------------------------------------------------------


def test_separator_assumption_row_says_simplified_model_declared_separation_impulse():
    assert SEPARATION_ASSUMPTION_LABEL == "단순화 모델: 선언 분리 충격량"
    default_row = separation_assumption(separator_from_part(SEPARATOR))
    assert default_row.label == "단순화 모델: 선언 분리 충격량" and default_row.value.badge is Badge.DEFAULT
    assert default_row.confidence is Confidence.LOW and default_row.distribution.kind == "fixed"
    row = separation_assumption(separator_from_part(SEPARATOR, {"separation_impulse": declared(8.0, "N*s")}))
    assert row.value.value == 8.0 and row.value.badge is Badge.DECLARED and row.confidence is Confidence.MED
    assert row.value.source.declared_by == "test"


# ---- the joints at a separator are fixed -------------------------------------------------------------------------------------


def test_separator_is_held_by_fixed_joints_only():
    assert [j.kind.value for j in stack().joints] == ["fixed", "fixed"]
    with pytest.raises(ValidationError, match="holds its two parts with fixed joints"):
        stack(joint_kind="hinge")
    with pytest.raises(ValidationError, match="holds its two parts with fixed joints"):
        stack(joint_kind="slider")


def test_separator_other_roles_are_still_rejected_without_their_requirements():
    with pytest.raises(ValidationError, match="needs the curve 'thrust'"):
        PartDef.model_validate({**load(), "role": "thruster"})


# ---- the usual part checks: glb, collision proxy, cache, the check command ----------------------------------------------------


def test_separator_compiles_to_a_valid_glb_and_a_voidless_proxy():
    glb = validate(part_glb(SEPARATOR, None))
    assert len(glb.doc["meshes"]) >= 1
    proxy = collision_proxy(SEPARATOR)
    assert proxy.volume_error.value == 0.0 and proxy.filled_voids == ()


def test_separator_results_come_out_of_the_cache_unchanged_and_the_impulse_changes_the_key():
    cache = PartCache(max_entries=8)
    assert cache.mass_properties(SEPARATOR, None) == mass_properties(SEPARATOR, None)
    assert cache.part_glb(SEPARATOR, None) == part_glb(SEPARATOR, None)
    other = PartDef.model_validate(with_impulse(load(), default={"value": 3.0}, max={"value": 1000.0}))
    cache.mass_properties(other, None)
    assert cache.stats().misses >= 2


def test_separator_snap_points_carry_a_pose_with_a_badge_and_a_tag():
    assert {s.id for s in SEPARATOR.snap_points} == {"face_a", "face_b"}
    assert all(s.badge is Badge.DEFAULT and s.accepts and s.kind == "surface" for s in SEPARATOR.snap_points)


def test_separator_check_command_reports_the_part(capsys, tmp_path):
    code = main([str(PATH), "--out", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["part"] == "separator"
    assert report["mass_kg"] == pytest.approx(M, rel=1e-12)
    validate((tmp_path / "separator.glb").read_bytes())


def test_separator_schema_example_is_the_library_file():
    from pathlib import Path

    example = Path(__file__).parents[3] / "schemas" / "examples" / "PartDef.separator.json"
    assert example.read_bytes() == PATH.read_bytes()
