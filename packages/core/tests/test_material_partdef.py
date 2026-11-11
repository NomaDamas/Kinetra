"""C-01a: Material and PartDef. Test values are fixtures declared by the test (`사용자 선언`), not real material data."""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from kinetra_core import BADGE_LABEL_KO, Badge, Material, PartDef, Quantity, Unit

SRC = {"ref": "unit-test fixture", "locator": "test_material_partdef.py"}


def q(value, unit, badge="user_declared", source=None):
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
                "badge": "user_declared",
                "source": SRC,
            }
        ],
        "specs": {"rated_load": q(100.0, "N", "estimated", {"ref": "test estimate"})},
    }


def test_material_valid_round_trips_through_json():
    m = Material.model_validate(material_dict())
    again = Material.model_validate_json(m.model_dump_json())
    assert again == m
    assert m.density.badge is Badge.USER_DECLARED


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


@pytest.mark.parametrize("ref", ["", "   ", "TBD", "n/a", "없음", "Unknown"])
def test_material_rejects_placeholder_source(ref):
    d = material_dict()
    d["density"]["source"] = {"ref": ref}
    with pytest.raises(ValidationError, match="source.ref"):
        Material.model_validate(d)


def test_material_rejects_unknown_badge():
    d = material_dict()
    d["density"]["badge"] = "trust-me"
    with pytest.raises(ValidationError, match="badge"):
        Material.model_validate(d)


def test_material_cited_value_needs_a_place_in_the_source():
    d = material_dict()
    d["density"]["badge"] = "cited"
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
    with pytest.raises(ValidationError, match=f"{field} must be in"):
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
        with pytest.raises(ValidationError, match="> 0"):
            Material.model_validate(d)


def test_material_friction_may_be_zero_not_negative():
    d = material_dict()
    d["friction"]["value"] = 0.0
    Material.model_validate(d)
    d["friction"]["value"] = -0.1
    with pytest.raises(ValidationError, match=">= 0"):
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
    assert p.specs["rated_load"].unit is Unit.N


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
        del d["specs"]["rated_load"][missing]
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
    d["specs"]["rated_load"]["source"] = {"ref": "?"}
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
    with pytest.raises(ValidationError, match="length.max must be in"):
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
    with pytest.raises(ValidationError, match="accepts tag"):
        PartDef.model_validate(d)


def test_partdef_rejects_unknown_fields():
    d = partdef_dict()
    d["mjcf"] = "<geom/>"
    with pytest.raises(ValidationError, match="mjcf"):
        PartDef.model_validate(d)


def test_quantity_requires_badge_and_source_in_json_schema():
    schema = Quantity.model_json_schema()
    assert {"value", "unit", "badge", "source"} <= set(schema["required"])
    assert set(schema["$defs"]["Badge"]["enum"]) == {b.value for b in Badge}
    assert "$defs" in Material.model_json_schema() and "$defs" in PartDef.model_json_schema()


def test_every_badge_has_its_korean_label():
    assert {b: BADGE_LABEL_KO[b] for b in Badge} == {
        Badge.SIMULATED: "시뮬",
        Badge.CITED: "인용",
        Badge.DEFAULT: "기본값",
        Badge.USER_DECLARED: "사용자 선언",
        Badge.ESTIMATED: "추정",
    }


def test_conventions_are_si_right_handed_z_up_with_named_quaternion():
    from kinetra_core import COORDINATE_FRAME, QUATERNION_COMPONENTS

    assert COORDINATE_FRAME == "right-handed, +Z up"
    assert QUATERNION_COMPONENTS == ("x", "y", "z", "w")
    assert {Unit.M.value, Unit.KG.value, Unit.S.value, Unit.RAD.value} == {"m", "kg", "s", "rad"}
