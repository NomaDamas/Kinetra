"""C-01a: Material and PartDef. Test values are fixtures declared by the test (`사용자 선언`), not real material data."""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from kinetra_core import BADGE_LABEL_KO, Badge, Material, PartDef, Quantity, Unit

SRC = {"ref": "unit-test fixture", "locator": "test_material_partdef.py"}


def q(value, unit, badge="declared", source=None):
    return {"value": value, "unit": unit, "badge": badge, "source": source or SRC}


def material_dict():
    return {
        "id": "test-material",
        "name": "Test material",
        "density": q(1000.0, "kg/m^3"),
        "yield_strength": q(1.0e7, "Pa"),
        "elastic_modulus": q(1.0e9, "Pa"),
        "friction": q(0.5, "1", "default", {"ref": "test default"}),
    }


def axis(offset=0.0, terms=()):
    return {"offset": offset, "terms": list(terms)}


def partdef_dict():
    return {
        "id": "test-beam",
        "name": "Test beam",
        "parameters": [
            {
                "name": "length",
                "unit": "m",
                "default": q(1.0, "m"),
                "min": q(0.1, "m"),
                "max": q(2.0, "m"),
            }
        ],
        "snap_points": [
            {
                "id": "end-a",
                "kind": "beam_end",
                "accepts": ["beam_end", "plate_edge"],
                "position": {"x": axis(), "y": axis(), "z": axis(0.0, [{"param": "length", "factor": 0.5}])},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                "badge": "declared",
                "source": SRC,
            }
        ],
        "specs": [{"name": "rated_load", **q(100.0, "N", "estimate", {"ref": "test estimate"})}],
    }


def test_material_valid_round_trips_through_json():
    m = Material.model_validate(material_dict())
    again = Material.model_validate_json(m.model_dump_json())
    assert again == m
    assert m.density.badge is Badge.DECLARED


@pytest.mark.parametrize("field", ["density", "yield_strength", "elastic_modulus", "friction"])
def test_material_rejects_value_without_source(field):
    d = material_dict()
    del d[field]["source"]
    with pytest.raises(ValidationError, match="source"):
        Material.model_validate(d)


@pytest.mark.parametrize("field", ["density", "yield_strength", "elastic_modulus", "friction"])
def test_material_rejects_value_without_badge(field):
    d = material_dict()
    del d[field]["badge"]
    with pytest.raises(ValidationError, match="badge"):
        Material.model_validate(d)


def test_material_rejects_bare_number():
    d = material_dict()
    d["density"] = 1000.0
    with pytest.raises(ValidationError):
        Material.model_validate(d)


@pytest.mark.parametrize(
    "ref",
    ["", "   ", "TBD", "TBD.", "tbd later", "n/a", "N/A.", "없음", "Unknown", "...", ".", "???", "미정", "출처 없음",
     "todo: cite", "TODO", "-", "\t\n"],
)
def test_material_rejects_placeholder_source(ref):
    d = material_dict()
    d["density"]["source"] = {"ref": ref}
    with pytest.raises(ValidationError):
        Material.model_validate(d)


def test_real_sources_that_merely_resemble_placeholders_pass():
    d = material_dict()
    d["density"]["source"] = {"ref": "Handbook of Nothing Special, 3rd ed.", "locator": "Table 2.1"}
    Material.model_validate(d)


def test_material_rejects_unknown_badge():
    d = material_dict()
    d["density"]["badge"] = "trust-me"
    with pytest.raises(ValidationError, match="badge"):
        Material.model_validate(d)


def test_material_cited_value_needs_a_place_in_the_source():
    d = material_dict()
    d["density"]["badge"] = "cite"
    d["density"]["source"] = {"ref": "Some Handbook"}
    with pytest.raises(ValidationError, match="locator or source.url"):
        Material.model_validate(d)
    d["density"]["source"] = {"ref": "Some Handbook", "locator": "Table 3"}
    Material.model_validate(d)


@pytest.mark.parametrize(
    "field,unit",
    [("density", "kg/m^3"), ("yield_strength", "Pa"), ("elastic_modulus", "Pa"), ("friction", "1")],
)
def test_material_rejects_wrong_unit(field, unit):
    d = material_dict()
    d[field]["unit"] = "N" if unit != "N" else "m"
    with pytest.raises(ValidationError, match="unit"):
        Material.model_validate(d)


def test_material_rejects_non_si_unit_strings():
    d = material_dict()
    d["density"]["unit"] = "g/cm^3"
    with pytest.raises(ValidationError, match="unit"):
        Material.model_validate(d)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_material_rejects_non_positive_density_and_strength(bad):
    for field in ("density", "yield_strength", "elastic_modulus"):
        d = material_dict()
        d[field]["value"] = bad
        with pytest.raises(ValidationError, match="greater than 0"):
            Material.model_validate(d)


def test_material_friction_may_be_zero_not_negative():
    d = material_dict()
    d["friction"]["value"] = 0.0
    Material.model_validate(d)
    d["friction"]["value"] = -0.1
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Material.model_validate(d)


@pytest.mark.parametrize("bad", ["1000", True, None])
def test_material_rejects_non_numeric_value(bad):
    d = material_dict()
    d["density"]["value"] = bad
    with pytest.raises(ValidationError):
        Material.model_validate(d)


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_material_rejects_nan_and_infinity(bad):
    with pytest.raises(ValidationError):
        Material.model_validate_json(json.dumps(material_dict()).replace("1000.0", bad))


def test_material_rejects_unknown_fields_and_bad_id():
    d = material_dict()
    d["gravity"] = 9.81
    with pytest.raises(ValidationError, match="gravity"):
        Material.model_validate(d)
    d = material_dict()
    d["id"] = "Bad Id"
    with pytest.raises(ValidationError):
        Material.model_validate(d)


def test_material_is_immutable():
    m = Material.model_validate(material_dict())
    with pytest.raises(ValidationError):
        m.name = "other"


def test_partdef_valid_round_trips_through_json():
    p = PartDef.model_validate(partdef_dict())
    assert PartDef.model_validate_json(p.model_dump_json()) == p
    assert p.snap_points[0].position.z.terms[0].param == "length"
    assert p.specs[0].unit is Unit.N


def test_partdef_empty_is_valid():
    PartDef.model_validate({"id": "empty", "name": "Empty"})


def test_partdef_rejects_parameter_value_without_source():
    d = partdef_dict()
    del d["parameters"][0]["max"]["source"]
    with pytest.raises(ValidationError, match="source"):
        PartDef.model_validate(d)


def test_partdef_rejects_spec_without_badge_or_source():
    for missing in ("badge", "source"):
        d = partdef_dict()
        del d["specs"][0][missing]
        with pytest.raises(ValidationError, match=missing):
            PartDef.model_validate(d)


def test_partdef_rejects_snap_point_without_source():
    d = partdef_dict()
    del d["snap_points"][0]["source"]
    with pytest.raises(ValidationError, match="source"):
        PartDef.model_validate(d)


def test_partdef_rejects_snap_point_without_badge():
    d = partdef_dict()
    del d["snap_points"][0]["badge"]
    with pytest.raises(ValidationError, match="badge"):
        PartDef.model_validate(d)


def test_partdef_rejects_placeholder_source_on_spec():
    d = partdef_dict()
    d["specs"][0]["source"] = {"ref": "?"}
    with pytest.raises(ValidationError, match="source.ref"):
        PartDef.model_validate(d)


def test_partdef_parameter_range_must_order():
    d = partdef_dict()
    d["parameters"][0]["default"]["value"] = 5.0
    with pytest.raises(ValidationError, match="min <= default <= max"):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["parameters"][0]["min"]["value"] = 3.0
    with pytest.raises(ValidationError, match="min <= default <= max"):
        PartDef.model_validate(d)


def test_partdef_parameter_values_must_use_the_parameter_unit():
    d = partdef_dict()
    d["parameters"][0]["max"]["unit"] = "kg"
    with pytest.raises(ValidationError, match="like the parameter"):
        PartDef.model_validate(d)


def test_partdef_rejects_duplicate_parameter_and_snap_ids():
    d = partdef_dict()
    d["parameters"].append(copy.deepcopy(d["parameters"][0]))
    with pytest.raises(ValidationError, match="duplicate parameter"):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["snap_points"].append(copy.deepcopy(d["snap_points"][0]))
    with pytest.raises(ValidationError, match="duplicate snap point"):
        PartDef.model_validate(d)


def test_partdef_snap_point_must_reference_an_existing_length_parameter():
    d = partdef_dict()
    d["snap_points"][0]["position"]["z"]["terms"][0]["param"] = "width"
    with pytest.raises(ValidationError, match="unknown parameter"):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["parameters"][0] = {
        "name": "length",
        "unit": "kg",
        "default": q(1.0, "kg"),
        "min": q(0.1, "kg"),
        "max": q(2.0, "kg"),
    }
    with pytest.raises(ValidationError, match="not a length"):
        PartDef.model_validate(d)


def test_partdef_quaternion_must_be_unit_and_named():
    d = partdef_dict()
    d["snap_points"][0]["orientation"] = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 2.0}
    with pytest.raises(ValidationError, match="unit norm"):
        PartDef.model_validate(d)
    d["snap_points"][0]["orientation"] = [0.0, 0.0, 0.0, 1.0]
    with pytest.raises(ValidationError):
        PartDef.model_validate(d)
    d["snap_points"][0]["orientation"] = {"x": 0.0, "y": 0.0, "z": 0.7071067811865476, "w": 0.7071067811865476}
    PartDef.model_validate(d)


def test_partdef_rejects_bad_accepts_tags():
    d = partdef_dict()
    d["snap_points"][0]["accepts"] = ["beam_end", "beam_end"]
    with pytest.raises(ValidationError, match="duplicate"):
        PartDef.model_validate(d)
    d["snap_points"][0]["accepts"] = ["Beam End"]
    with pytest.raises(ValidationError, match="String should match pattern"):
        PartDef.model_validate(d)


def test_partdef_rejects_unknown_fields():
    d = partdef_dict()
    d["mjcf"] = "<geom/>"
    with pytest.raises(ValidationError, match="mjcf"):
        PartDef.model_validate(d)


def test_every_badge_has_its_korean_label():
    assert {b: BADGE_LABEL_KO[b] for b in Badge} == {
        Badge.SIM: "시뮬",
        Badge.CITE: "인용",
        Badge.DEFAULT: "기본값",
        Badge.DECLARED: "사용자 선언",
        Badge.ESTIMATE: "추정",
    }


def test_conventions_are_si_right_handed_z_up_with_named_quaternion():
    from kinetra_core import COORDINATE_FRAME, QUATERNION_COMPONENTS

    assert COORDINATE_FRAME == "right-handed, +Z up"
    assert QUATERNION_COMPONENTS == ("x", "y", "z", "w")
    assert {Unit.M.value, Unit.KG.value, Unit.S.value, Unit.RAD.value} == {"m", "kg", "s", "rad"}


@pytest.mark.parametrize(
    "url", ["https://", "http://", "https:///path", "ftp://example.org/x", "example.org", "https://exa mple.org",
            "https://example.org/a\tb", "https://example.org/\n", "https://:80/x"]
)
def test_source_url_must_be_http_with_host_and_no_whitespace(url):
    d = material_dict()
    d["density"]["source"] = {"ref": "Some Handbook", "url": url}
    with pytest.raises(ValidationError, match="url"):
        Material.model_validate(d)


def test_source_url_with_host_passes():
    d = material_dict()
    d["density"]["source"] = {"ref": "Some Handbook", "url": "https://example.org/handbook#t3"}
    Material.model_validate(d)


def test_quaternion_huge_components_are_a_validation_error_not_overflow():
    d = partdef_dict()
    d["snap_points"][0]["orientation"] = {"x": 1e200, "y": 0.0, "z": 0.0, "w": 0.0}
    with pytest.raises(ValidationError, match="unit norm"):
        PartDef.model_validate(d)


def test_partdef_is_immutable_and_hashable():
    p = PartDef.model_validate(partdef_dict())
    assert isinstance(p.specs, tuple) and isinstance(p.parameters, tuple) and isinstance(p.snap_points, tuple)
    with pytest.raises(AttributeError):
        p.specs.append(p.specs[0])
    with pytest.raises(ValidationError):
        p.specs[0].value = 1.0
    assert hash(p) == hash(PartDef.model_validate(partdef_dict()))


def test_partdef_spec_names_are_unique_and_named():
    d = partdef_dict()
    d["specs"].append(copy.deepcopy(d["specs"][0]))
    with pytest.raises(ValidationError, match="duplicate spec name"):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["specs"][0]["name"] = "Rated Load"
    with pytest.raises(ValidationError, match="String should match pattern"):
        PartDef.model_validate(d)
    d = partdef_dict()
    del d["specs"][0]["name"]
    with pytest.raises(ValidationError, match="name"):
        PartDef.model_validate(d)


def test_partdef_snap_id_or_spec_name_may_not_collide_with_a_parameter():
    d = partdef_dict()
    d["snap_points"][0]["id"] = "length"
    with pytest.raises(ValidationError, match="collides with a parameter"):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["specs"][0]["name"] = "length"
    with pytest.raises(ValidationError, match="collides with a parameter"):
        PartDef.model_validate(d)


def test_material_reports_every_bad_field_with_its_location():
    d = material_dict()
    d["density"]["unit"] = "Pa"
    d["yield_strength"]["value"] = -1.0
    d["friction"]["value"] = -0.5
    with pytest.raises(ValidationError) as e:
        Material.model_validate(d)
    locs = {err["loc"] for err in e.value.errors()}
    assert locs == {("density", "unit"), ("yield_strength", "value"), ("friction", "value")}


def test_parameter_unit_mismatch_points_at_the_field():
    d = partdef_dict()
    d["parameters"][0]["max"]["unit"] = "kg"
    with pytest.raises(ValidationError) as e:
        PartDef.model_validate(d)
    assert [err["loc"] for err in e.value.errors()] == [("parameters", 0, "max")]


def test_json_schema_carries_the_constraints():
    ms = Material.model_json_schema()
    defs = ms["$defs"]
    assert ms["properties"]["density"]["$ref"].endswith("/Density")
    assert defs["Density"]["properties"]["unit"]["const"] == "kg/m^3"
    assert defs["Density"]["properties"]["value"]["exclusiveMinimum"] == 0
    assert defs["Friction"]["properties"]["value"]["minimum"] == 0
    assert {"value", "unit", "badge", "source"} <= set(defs["Density"]["required"])
    ps = PartDef.model_json_schema()["$defs"]
    assert {"name", "value", "unit", "badge", "source"} <= set(ps["SpecDef"]["required"])
    assert ps["SnapPoint"]["properties"]["accepts"]["items"]["pattern"] == "^[a-z][a-z0-9_]{0,63}$"
    assert set(ps["Badge"]["enum"]) == {"sim", "cite", "default", "declared", "estimate"}


def test_license_only_on_cited_and_declared_fields_only_on_declared():
    d = material_dict()
    d["density"]["source"] = {"ref": "Some Handbook", "locator": "Table 3", "license": "CC-BY-4.0"}
    with pytest.raises(ValidationError, match="license is only for cited"):
        Material.model_validate(d)
    d["density"]["badge"] = "cite"
    Material.model_validate(d)
    d["density"]["source"]["license"] = "NOASSERTION"
    with pytest.raises(ValidationError, match="source.license"):
        Material.model_validate(d)
    d = material_dict()
    d["density"]["source"] = {"ref": "founder", "declared_by": "Min", "declared_at": "2026-11-11T09:00:00+09:00"}
    Material.model_validate(d)
    d["density"]["source"]["declared_at"] = "2026-11-11T09:00:00"  # naive time is ambiguous
    with pytest.raises(ValidationError):
        Material.model_validate(d)
    d["density"]["badge"] = "estimate"
    d["density"]["source"]["declared_at"] = "2026-11-11T09:00:00+09:00"
    with pytest.raises(ValidationError, match="only for declared"):
        Material.model_validate(d)
