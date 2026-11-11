"""B-01a: the shape recipe inside `PartDef`. Fixture numbers are declared by the test (`사용자 선언`), not real part data."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kinetra_core import MassProperties, PartDef, Shape

SRC = {"ref": "unit-test fixture", "locator": "test_shape.py"}


def q(value, unit="m"):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(offset=0.0, terms=()):
    return {"offset": offset, "terms": [{"param": p, "factor": f} for p, f in terms]}


def param(name="w", unit="m", default=0.2, lo=0.1, hi=0.5):
    return {"name": name, "unit": unit, "default": q(default, unit), "min": q(lo, unit), "max": q(hi, unit)}


def component(id="b", size_x=None, **kw):
    return {
        "id": id,
        "primitive": {"kind": "box", "size_x": size_x or ax(0.1), "size_y": ax(0.1), "size_z": ax(0.1)},
        "position": {"x": ax(), "y": ax(), "z": ax()},
        **kw,
    }


def partdef_dict(components=None, parameters=None):
    return {
        "id": "test-part",
        "name": "Test part",
        "parameters": parameters if parameters is not None else [param()],
        "shape": {"badge": "declared", "source": SRC, "components": components if components is not None else [component()]},
    }


def test_partdef_without_a_shape_is_still_valid():
    p = PartDef.model_validate({"id": "no-shape", "name": "No shape"})
    assert p.shape is None


def test_shape_round_trips_through_json_and_is_hashable():
    p = PartDef.model_validate(partdef_dict())
    assert PartDef.model_validate_json(p.model_dump_json()) == p
    assert hash(p) == hash(PartDef.model_validate(partdef_dict()))
    assert isinstance(p.shape, Shape)
    assert p.shape.components[0].orientation.w == 1.0  # default: identity


@pytest.mark.parametrize("missing", ["badge", "source"])
def test_shape_requires_badge_and_source(missing):
    d = partdef_dict()
    del d["shape"][missing]
    with pytest.raises(ValidationError, match=missing):
        PartDef.model_validate(d)


def test_shape_rejects_placeholder_source():
    d = partdef_dict()
    d["shape"]["source"] = {"ref": "TBD"}
    with pytest.raises(ValidationError, match="placeholder"):
        PartDef.model_validate(d)


def test_shape_rejects_empty_duplicate_and_void_only_recipes():
    d = partdef_dict(components=[])
    with pytest.raises(ValidationError, match="at least 1"):
        PartDef.model_validate(d)
    with pytest.raises(ValidationError, match="duplicate component id"):
        PartDef.model_validate(partdef_dict(components=[component("a"), component("a")]))
    with pytest.raises(ValidationError, match="at least one added component"):
        PartDef.model_validate(partdef_dict(components=[component("a", operation="subtract")]))


def test_shape_rejects_unknown_primitive_operation_and_fields():
    d = partdef_dict()
    d["shape"]["components"][0]["primitive"]["kind"] = "torus"
    with pytest.raises(ValidationError):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["shape"]["components"][0]["operation"] = "union"
    with pytest.raises(ValidationError):
        PartDef.model_validate(d)
    d = partdef_dict()
    d["shape"]["components"][0]["primitive"]["radius"] = ax(0.1)
    with pytest.raises(ValidationError):
        PartDef.model_validate(d)


def test_shape_rejects_a_dimension_missing_for_the_primitive():
    d = partdef_dict()
    del d["shape"]["components"][0]["primitive"]["size_z"]
    with pytest.raises(ValidationError, match="size_z"):
        PartDef.model_validate(d)


def test_shape_rejects_unknown_and_non_length_parameters():
    with pytest.raises(ValidationError, match="unknown parameter 'nope'"):
        PartDef.model_validate(partdef_dict([component(size_x=ax(0.0, [("nope", 1.0)]))]))
    with pytest.raises(ValidationError, match="'mass' is not a length"):
        PartDef.model_validate(
            partdef_dict([component(size_x=ax(0.0, [("mass", 1.0)]))], [param("mass", "kg", 1.0, 0.5, 2.0)])
        )


def test_shape_dimension_must_stay_positive_over_the_whole_parameter_range():
    # size_x = w - 0.1 with w in [0.1, 0.5] reaches 0 at the low end of the range.
    with pytest.raises(ValidationError, match="above zero over the whole parameter range"):
        PartDef.model_validate(partdef_dict([component(size_x=ax(-0.1, [("w", 1.0)]))]))
    # With w in [0.2, 0.5] the same expression stays above 0.1.
    PartDef.model_validate(partdef_dict([component(size_x=ax(-0.1, [("w", 1.0)]))], [param(lo=0.2)]))
    # A negative factor is checked at the other end: size_x = 0.6 - w reaches 0.1 at w = 0.5, fine; 0.5 - w reaches 0.
    PartDef.model_validate(partdef_dict([component(size_x=ax(0.6, [("w", -1.0)]))]))
    with pytest.raises(ValidationError, match="above zero"):
        PartDef.model_validate(partdef_dict([component(size_x=ax(0.5, [("w", -1.0)]))]))
    # Two terms of the same parameter are summed before the range is applied: w - w + 0.1 is the constant 0.1.
    PartDef.model_validate(partdef_dict([component(size_x=ax(0.1, [("w", 1.0), ("w", -1.0)]))]))


def test_shape_error_names_the_component_and_field():
    with pytest.raises(ValidationError) as e:
        PartDef.model_validate(partdef_dict([component("lid", size_x=ax(-0.1, [("w", 1.0)]))]))
    assert "component 'lid' primitive.size_x" in str(e.value)


def test_shape_position_may_be_negative_but_not_nan():
    c = component()
    c["position"]["x"] = ax(-0.3)
    PartDef.model_validate(partdef_dict([c]))
    c["position"]["x"] = ax(float("nan"))
    with pytest.raises(ValidationError):
        PartDef.model_validate(partdef_dict([c]))


def test_shape_orientation_must_be_a_unit_quaternion():
    c = component(orientation={"x": 1.0, "y": 1.0, "z": 0.0, "w": 0.0})
    with pytest.raises(ValidationError, match="unit norm"):
        PartDef.model_validate(partdef_dict([c]))


def test_shape_is_immutable():
    p = PartDef.model_validate(partdef_dict())
    with pytest.raises(ValidationError):
        p.shape.components[0].operation = "subtract"  # type: ignore[misc]


def test_json_schema_carries_the_shape_and_the_result_model():
    s = PartDef.model_json_schema()
    assert "shape" in s["properties"]
    blob = json.dumps(s)
    assert "cylinder" in blob and "subtract" in blob
    r = MassProperties.model_json_schema()
    assert {"volume", "mass", "center_of_mass", "inertia", "derivation"} <= set(r["properties"])
    assert "analytic-primitives" in json.dumps(r)
