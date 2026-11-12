"""#571: typed assumption bindings, target validation and immutable sampled compile inputs.

All numbers are declared by this test; no catalog value or citation is used.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinetra_core import Project, apply_assumption_values

SRC = {"ref": "#571 test fixture: value declared by the test", "locator": "test_assumption_binding.py"}


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def project_data():
    material = {
        "id": "test-material",
        "name": "Test material",
        "density": q(1000.0, "kg/m^3"),
        "yield_strength": q(1.0e8, "Pa"),
        "elastic_modulus": q(1.0e9, "Pa"),
        "friction": q(0.5, "1"),
    }
    mass = {"name": "mass", "unit": "kg", "default": q(10.0, "kg"), "min": q(0.1, "kg"), "max": q(30.0, "kg")}
    part = {"id": "payload", "name": "Payload", "parameters": [mass], "specs": [{"name": "rating", **q(0.5, "N")}]}
    instance = {
        "id": "payload-1",
        "part": "payload",
        "pose": {
            "badge": "declared",
            "source": SRC,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
    }
    return {
        "design": {"materials": [material], "parts": [part], "instances": [instance]},
        "world": {"planet": "earth"},
    }


def row(key, unit, binding):
    return {
        "key": key,
        "label": key,
        "value": q(10.0 if unit == "kg" else 0.5, unit),
        "distribution": {"kind": "uniform", "low": 1.0, "high": 20.0, "badge": "estimate", "source": SRC}
        if unit == "kg"
        else {"kind": "uniform", "low": 0.1, "high": 1.0, "badge": "estimate", "source": SRC},
        "confidence": "med",
        "binding": binding,
    }


INSTANCE_TARGET = {"kind": "instance_parameter", "instance": "payload-1", "parameter": "mass"}
FRICTION_TARGET = {"kind": "material_property", "material": "test-material", "property": "friction"}
SPEC_TARGET = {"kind": "part_spec", "part": "payload", "spec": "rating"}


def with_rows(*rows):
    data = project_data()
    data["assumptions"] = {"assumptions": list(rows)}
    return data


def test_binding_accepts_existing_instance_parameter_material_property_and_part_spec():
    project = Project.model_validate(with_rows(
        row("vehicle_mass", "kg", INSTANCE_TARGET),
        row("surface_friction", "1", FRICTION_TARGET),
        row("part_rating", "N", SPEC_TARGET),
    ))
    mass, friction, rating = project.assumptions.assumptions
    assert mass.binding.kind == "instance_parameter" and mass.binding.instance == "payload-1"
    assert friction.binding.kind == "material_property" and friction.binding.property == "friction"
    assert rating.binding.kind == "part_spec" and rating.binding.spec == "rating"


@pytest.mark.parametrize(
    ("target", "match"),
    [
        ({"kind": "instance_parameter", "instance": "ghost", "parameter": "mass"}, "unknown instance 'ghost'"),
        ({"kind": "instance_parameter", "instance": "payload-1", "parameter": "ghost"}, "has no parameter 'ghost'"),
        ({"kind": "material_property", "material": "ghost", "property": "friction"}, "unknown material 'ghost'"),
        ({"kind": "part_spec", "part": "ghost", "spec": "rating"}, "unknown part 'ghost'"),
        ({"kind": "part_spec", "part": "payload", "spec": "ghost"}, "has no spec 'ghost'"),
    ],
)
def test_binding_rejects_a_target_that_does_not_exist(target, match):
    unit = {"material_property": "1", "part_spec": "N"}.get(target["kind"], "kg")
    with pytest.raises(ValidationError, match=match):
        Project.model_validate(with_rows(row("bad_target", unit, target)))


def test_binding_rejects_a_parameter_whose_part_definition_is_missing():
    data = with_rows(row("vehicle_mass", "kg", INSTANCE_TARGET))
    data["design"]["parts"] = []  # C-06 permits the placeholder instance, but its parameter is not a known target.
    with pytest.raises(ValidationError, match="unknown part 'payload'"):
        Project.model_validate(data)


@pytest.mark.parametrize(
    ("unit", "target", "match"),
    [
        ("m", INSTANCE_TARGET, "binding target is in 'kg'"),
        ("kg", FRICTION_TARGET, "binding target is in '1'"),
        ("kg", SPEC_TARGET, "binding target is in 'N'"),
    ],
)
def test_binding_rejects_a_unit_mismatch(unit, target, match):
    with pytest.raises(ValidationError, match=match):
        Project.model_validate(with_rows(row("wrong_unit", unit, target)))


def test_binding_rejects_two_rows_for_one_design_value():
    data = with_rows(row("mass_a", "kg", INSTANCE_TARGET), row("mass_b", "kg", INSTANCE_TARGET))
    with pytest.raises(ValidationError, match="bind the same design value"):
        Project.model_validate(data)


def test_binding_is_a_closed_typed_union():
    with pytest.raises(ValidationError):
        Project.model_validate(with_rows(row("free_form", "kg", {"kind": "json_pointer", "path": "/design/mass"})))


def test_apply_assumption_values_changes_only_the_returned_compile_input():
    original = Project.model_validate(
        with_rows(row("vehicle_mass", "kg", INSTANCE_TARGET), row("surface_friction", "1", FRICTION_TARGET))
    )
    sampled = apply_assumption_values(original, {"vehicle_mass": 20.0, "surface_friction": 0.25})
    assert sampled is not original
    assert original.design.instances[0].parameters == ()  # the base still takes the part's 10 kg default
    assert original.design.materials[0].friction.value == 0.5
    (mass,) = sampled.design.instances[0].parameters  # an omitted parameter is materialized at its sampled value
    assert (mass.name, mass.value, mass.unit.value) == ("mass", 20.0, "kg")
    assert sampled.design.materials[0].friction.value == 0.25
    assert mass.badge.value == "estimate" and sampled.design.materials[0].friction.badge.value == "estimate"
    assert SRC["ref"] in mass.source.ref and "nominal evidence" in mass.source.ref


def test_apply_assumption_values_replaces_an_explicit_parameter_and_requires_every_bound_value():
    data = with_rows(row("vehicle_mass", "kg", INSTANCE_TARGET))
    data["design"]["instances"][0]["parameters"] = [{"name": "mass", **q(12.0, "kg")}]
    original = Project.model_validate(data)
    sampled = apply_assumption_values(original, {"vehicle_mass": 15.0})
    assert len(sampled.design.instances[0].parameters) == 1
    assert sampled.design.instances[0].parameters[0].value == 15.0
    assert original.design.instances[0].parameters[0].value == 12.0
    with pytest.raises(ValueError, match="vehicle_mass"):
        apply_assumption_values(original, {})


def test_apply_assumption_values_changes_a_part_spec_without_mutating_the_definition():
    original = Project.model_validate(with_rows(row("part_rating", "N", SPEC_TARGET)))
    sampled = apply_assumption_values(original, {"part_rating": 0.75})
    assert sampled.design.parts[0].specs[0].value == 0.75
    assert sampled.design.parts[0].specs[0].badge.value == "estimate"
    assert original.design.parts[0].specs[0].value == 0.5


def test_apply_assumption_values_scales_a_thruster_curve_with_sampled_rated_thrust():
    data = with_rows(row("thrust_rating", "N", {"kind": "part_spec", "part": "payload", "spec": "rated_thrust"}))
    data["assumptions"]["assumptions"][0]["value"] = q(4.0, "N")
    data["assumptions"]["assumptions"][0]["distribution"] = {
        "kind": "uniform", "low": 2.0, "high": 8.0, "badge": "estimate", "source": SRC,
    }
    part = data["design"]["parts"][0]
    part["role"] = "thruster"
    part["specs"] = [
        {"name": "rated_thrust", **q(4.0, "N")},
        {"name": "propellant_flow", **q(0.1, "kg/s")},
    ]
    part["curves"] = [{
        "name": "thrust",
        "curve": {
            "badge": "declared", "source": SRC, "x_unit": "s", "y_unit": "N",
            "points": [{"x": 0.0, "y": 0.0}, {"x": 0.1, "y": 2.0}, {"x": 0.2, "y": 4.0}],
        },
    }]
    axis = {"offset": 0.0, "terms": []}
    part["snap_points"] = [{
        "id": "nozzle", "kind": "exhaust", "badge": "declared", "source": SRC,
        "position": {"x": axis, "y": axis, "z": axis},
        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    }]
    original = Project.model_validate(data)
    sampled = apply_assumption_values(original, {"thrust_rating": 8.0})
    rated = next(s for s in sampled.design.parts[0].specs if s.name == "rated_thrust")
    curve = sampled.design.parts[0].curves[0].curve
    assert rated.value == 8.0 and rated.badge.value == "estimate"
    assert [p.y for p in curve.points] == [0.0, 4.0, 8.0]
    assert curve.badge.value == "estimate" and "thrust_rating" in curve.source.ref
    assert original.design.parts[0].curves[0].curve.badge.value == "declared"
    assert [p.y for p in original.design.parts[0].curves[0].curve.points] == [0.0, 2.0, 4.0]


@pytest.mark.parametrize("spread_badge", ["estimate", "default", "declared", "cite"])
def test_sample_provenance_follows_distribution_not_cited_nominal(spread_badge):
    data = with_rows(row("vehicle_mass", "kg", INSTANCE_TARGET))
    assumption = data["assumptions"]["assumptions"][0]
    assumption["value"]["badge"] = "cite"
    assumption["value"]["source"] = {"ref": "Measured nominal mass evidence", "locator": "measurement table"}
    assumption["distribution"]["badge"] = spread_badge
    assumption["distribution"]["source"] = {"ref": "Spread evidence", "locator": "spread declaration"}
    original = Project.model_validate(data)
    sampled = apply_assumption_values(original, {"vehicle_mass": 15.0})
    quantity = sampled.design.instances[0].parameters[0]
    assert quantity.badge.value == ("estimate" if spread_badge == "cite" else spread_badge)
    assert "Spread evidence" in quantity.source.ref and "Measured nominal mass evidence" in quantity.source.ref
    assert original.assumptions.assumptions[0].value.badge.value == "cite"


def test_unbound_rows_do_not_force_a_compile_input_copy():
    data = project_data()
    data["assumptions"] = {"assumptions": [{**row("vehicle_mass", "kg", INSTANCE_TARGET), "binding": None}]}
    project = Project.model_validate(data)
    assert apply_assumption_values(project, {}) is project
