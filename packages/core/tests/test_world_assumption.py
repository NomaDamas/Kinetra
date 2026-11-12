"""C-01c: World and the assumption table. Numbers are fixtures declared by the test (`사용자 선언`), not real data."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from kinetra_core import (
    PLANET_CONSTANT_NAMES,
    Assumption,
    AssumptionTable,
    Confidence,
    FixedDistribution,
    NormalDistribution,
    Quantity,
    UniformDistribution,
    World,
)

SRC = {"ref": "unit-test fixture", "locator": "test_world_assumption.py"}
FAKE = 1.0  # a stand-in number; the tests never use a real planet value


def q(value, unit, badge="declared", source=None):
    return {"value": value, "unit": unit, "badge": badge, "source": source or SRC}


def placement(**over):
    return {"x": 2.0, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": SRC, **over}


def prop(kind="ramp", **over):
    d = {
        "kind": kind,
        "id": "prop-a",
        "material": "test-material",
        "placement": placement(),
        "length": q(3.0, "m"),
        "width": q(1.0, "m"),
    }
    d.update({"ramp": {"incline": q(0.3, "rad")}, "step": {"height": q(0.2, "m")}}[kind])
    d.update(over)
    return d


def world_dict():
    return {"planet": "mars", "terrain_props": [prop("ramp"), prop("step", id="prop-b")]}


def assumption_dict(**over):
    d = {
        "key": "vehicle_mass",
        "label": "Vehicle mass",
        "value": q(1300.0, "kg"),
        "distribution": {
            "kind": "normal",
            "mean": 1300.0,
            "std": 50.0,
            "clip_low": 1000.0,
            "badge": "estimate",
            "source": {"ref": "test estimate"},
        },
        "confidence": "med",
    }
    d.update(over)
    return d


def uniform_dict(**over):
    return {"kind": "uniform", "low": 1.0, "high": 2.0, "badge": "default", "source": {"ref": "test default"}, **over}


# ---------------------------------------------------------------- World


def test_world_valid_and_roundtrips():
    w = World.model_validate(world_dict())
    assert w.planet == "mars"
    assert [p.kind for p in w.terrain_props] == ["ramp", "step"]
    assert World.model_validate_json(w.model_dump_json()) == w
    assert hash(w) == hash(World.model_validate(world_dict()))
    with pytest.raises(ValidationError):
        w.planet = "moon"  # frozen


def test_world_without_props_is_valid():
    assert World.model_validate({"planet": "moon"}).terrain_props == ()


def test_world_references_planet_by_id_only():
    assert set(World.model_fields) == {"planet", "terrain_props"}
    assert World.model_fields["planet"].annotation is str
    for bad in ("Mars", "mars planet", "", "9mars", {"id": "mars"}, 1):
        with pytest.raises(ValidationError):
            World.model_validate({"planet": bad})


@pytest.mark.parametrize("name", sorted(PLANET_CONSTANT_NAMES))
def test_project_gravity_and_planet_constants_are_rejected(name):
    """DoD: putting a gravity value (or any planet constant) into the project is rejected."""
    for value in (FAKE, q(FAKE, "m/s^2"), q(FAKE, "m/s^2", "cite", {"ref": "x", "url": "https://example.com/g"})):
        d = world_dict()
        d[name] = value
        with pytest.raises(ValidationError, match="planet constants do not belong to the project"):
            World.model_validate(d)


def test_gravity_in_a_prop_and_unknown_world_fields_are_rejected():
    d = world_dict()
    d["terrain_props"][0]["gravity"] = q(FAKE, "m/s^2")  # props have no planet-constant field either
    with pytest.raises(ValidationError, match="Extra inputs"):
        World.model_validate(d)
    d = world_dict()
    d["terrain_props"][1]["something_else"] = 1
    with pytest.raises(ValidationError, match="Extra inputs"):
        World.model_validate(d)
    d = world_dict()
    d["surface_gravity_m_s2"] = FAKE  # a name the list does not know is still an unknown field
    with pytest.raises(ValidationError, match="Extra inputs"):
        World.model_validate(d)


def test_world_error_names_where_constants_live():
    d = world_dict()
    d["gravity"] = FAKE
    with pytest.raises(ValidationError, match="data/bodies"):
        World.model_validate(d)


@pytest.mark.parametrize(
    ("field", "bad", "match"),
    [
        ("length", q(3.0, "mm"), "unit"),
        ("length", q(3.0, "rad"), "unit"),
        ("length", q(0.0, "m"), "greater than 0"),
        ("length", q(-1.0, "m"), "greater than 0"),
        ("width", q(0.0, "m"), "greater than 0"),
        ("length", {"value": 3.0, "unit": "m"}, "badge"),
        ("length", {"value": 3.0, "unit": "m", "badge": "declared"}, "source"),
        ("length", q(3.0, "m", "cite", {"ref": "a book"}), "locator or source.url"),
        ("length", q("3", "m"), "valid number"),
        ("length", q(float("nan"), "m"), "finite"),
        ("placement", {"x": 1.0, "y": 0.0, "yaw": 0.0}, "badge"),
        ("placement", placement(x="1"), "valid number"),
        ("placement", placement(x=float("inf")), "finite"),
        ("placement", placement(yaw=None), "valid number"),
        ("placement", placement(z=0.0), "Extra inputs"),
        ("placement", placement(badge="cite", source={"ref": "a book"}), "locator or source.url"),
    ],
)
def test_prop_numbers_need_badge_source_and_the_right_unit(field, bad, match):
    d = world_dict()
    d["terrain_props"][0][field] = bad
    with pytest.raises(ValidationError, match=match):
        World.model_validate(d)


def test_step_height_must_be_positive_metres():
    d = world_dict()
    d["terrain_props"][1]["height"] = q(0.0, "m")
    with pytest.raises(ValidationError, match="greater than 0"):
        World.model_validate(d)


def test_placement_is_one_pose_with_one_badge_and_source():
    w = World.model_validate(world_dict())
    p = w.terrain_props[0].placement
    assert (p.x, p.y, p.yaw, p.badge.value) == (2.0, 0.0, 0.0, "declared")
    d = world_dict()
    d["terrain_props"][0]["x"] = q(2.0, "m")  # no separate per-axis quantities
    with pytest.raises(ValidationError, match="Extra inputs"):
        World.model_validate(d)


@pytest.mark.parametrize("bad", [0.0, -0.1, math.pi / 2, 1.6, 45.0])
def test_ramp_incline_is_strictly_between_zero_and_a_right_angle(bad):
    d = world_dict()
    d["terrain_props"][0]["incline"] = q(bad, "rad")
    with pytest.raises(ValidationError, match="greater than 0|less than"):
        World.model_validate(d)


def test_ramp_incline_accepts_inside_the_range():
    d = world_dict()
    d["terrain_props"][0]["incline"] = q(1.5, "rad")
    World.model_validate(d)


def test_prop_kind_is_required_and_closed_and_ramp_has_no_height():
    d = world_dict()
    d["terrain_props"][0]["kind"] = "wall"
    with pytest.raises(ValidationError, match="union_tag_invalid|does not match any of the expected tags"):
        World.model_validate(d)
    d = world_dict()
    del d["terrain_props"][0]["kind"]  # no default: a missing kind is an error
    with pytest.raises(ValidationError, match="Unable to extract tag|union_tag_not_found|kind"):
        World.model_validate(d)
    d = world_dict()
    d["terrain_props"][0]["height"] = q(1.0, "m")  # a ramp's rise is derived from length and incline
    with pytest.raises(ValidationError, match="Extra inputs"):
        World.model_validate(d)
    d = world_dict()
    del d["terrain_props"][1]["height"]
    with pytest.raises(ValidationError, match="height"):
        World.model_validate(d)


def test_prop_material_is_optional_id_none_means_planet_ground():
    d = world_dict()
    del d["terrain_props"][0]["material"]
    w = World.model_validate(d)
    assert w.terrain_props[0].material is None
    assert World.model_validate_json(w.model_dump_json()) == w
    d["terrain_props"][0]["material"] = {"density": q(FAKE, "kg/m^3")}  # a material is referenced, not embedded
    with pytest.raises(ValidationError, match="string"):
        World.model_validate(d)
    d["terrain_props"][0]["material"] = "Not An Id"
    with pytest.raises(ValidationError, match="pattern"):
        World.model_validate(d)


def test_prop_ids_are_unique():
    d = world_dict()
    d["terrain_props"][1]["id"] = d["terrain_props"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate terrain prop id"):
        World.model_validate(d)


def test_world_validates_from_json_text():
    import json

    assert World.model_validate_json(json.dumps(world_dict())).planet == "mars"
    bad = world_dict()
    bad["gravity"] = FAKE
    with pytest.raises(ValidationError, match="planet constants do not belong"):
        World.model_validate_json(json.dumps(bad))


def test_world_json_schema_carries_ids_units_and_required_kinds():
    s = World.model_json_schema()
    defs = s["$defs"]
    assert set(s["properties"]) == {"planet", "terrain_props"}
    assert s["properties"]["planet"]["pattern"] == "^[a-z][a-z0-9_-]{0,63}$"
    assert set(defs["RampProp"]["required"]) >= {"kind", "id", "placement", "length", "width", "incline"}
    assert "material" not in defs["RampProp"]["required"]
    assert set(defs["StepProp"]["required"]) >= {"kind", "height"}
    assert defs["PropSize"]["properties"]["unit"]["const"] == "m"
    assert defs["PropSize"]["properties"]["value"]["exclusiveMinimum"] == 0
    assert defs["Incline"]["properties"]["unit"]["const"] == "rad"
    assert s["properties"]["terrain_props"]["items"]["discriminator"]["propertyName"] == "kind"


# ---------------------------------------------------------------- assumption table


# Field names and identifiers of the legacy `SpecSheet` assumption structure (legacy-v0:schemas/spec_sheet.schema.json).
LEGACY_ASSUMPTION_FIELDS = {"key", "label", "value", "unit", "distribution", "source", "confidence", "editable"}
LEGACY_DISTRIBUTION_KINDS = {"fixed", "uniform", "normal"}
LEGACY_NORMAL_FIELDS = {"kind", "mean", "std", "clip_low", "clip_high"}


def test_assumption_structure_is_the_legacy_one_with_value_unit_source_in_a_quantity():
    # legacy value, unit and source (free text) became one Quantity: value, unit, badge, source
    assert set(Assumption.model_fields) == LEGACY_ASSUMPTION_FIELDS - {"unit", "source"}
    assert Assumption.model_fields["value"].annotation is Quantity
    assert {c.value for c in Confidence} == {"low", "med", "high"}
    defs = AssumptionTable.model_json_schema()["$defs"]
    assert set(defs["NormalDistribution"]["properties"]) >= LEGACY_NORMAL_FIELDS
    assert set(defs["UniformDistribution"]["properties"]) >= {"kind", "low", "high", "badge", "source"}
    assert {"kind", "low", "high", "badge", "source"} <= set(defs["UniformDistribution"]["required"])
    mapping = defs["Assumption"]["properties"]["distribution"]["discriminator"]["mapping"]
    assert set(mapping) == LEGACY_DISTRIBUTION_KINDS
    for name in ("FixedDistribution", "UniformDistribution", "NormalDistribution"):
        assert "kind" in defs[name]["required"]  # no default on the discriminator
    assert Assumption.model_validate(assumption_dict()).editable is True


def test_assumption_roundtrips_and_defaults_to_fixed():
    d = assumption_dict()
    del d["distribution"]
    a = Assumption.model_validate(d)
    assert a.distribution == FixedDistribution(kind="fixed")
    assert a.value.badge.value == "declared"
    n = Assumption.model_validate(assumption_dict())
    assert isinstance(n.distribution, NormalDistribution)
    assert Assumption.model_validate_json(n.model_dump_json()) == n
    t = AssumptionTable.model_validate({"assumptions": [assumption_dict(), assumption_dict(key="thrust")]})
    assert AssumptionTable.model_validate_json(t.model_dump_json()) == t
    assert hash(t) == hash(AssumptionTable.model_validate(t.model_dump()))


def test_distribution_kind_is_required():
    for dist in ({}, {"low": 1.0, "high": 2.0, "badge": "default", "source": SRC}, {"mean": 1.0, "std": 0.1}):
        with pytest.raises(ValidationError, match="Unable to extract tag|union_tag_not_found|kind"):
            Assumption.model_validate(assumption_dict(distribution=dist))
    with pytest.raises(ValidationError, match="does not match any of the expected tags|union_tag_invalid"):
        Assumption.model_validate(assumption_dict(distribution={"kind": "lognormal", "badge": "default", "source": SRC}))


def test_uniform_bounds_and_fields():
    a = Assumption.model_validate(assumption_dict(value=q(1.5, "kg"), distribution=uniform_dict()))
    d = a.distribution
    assert isinstance(d, UniformDistribution)
    assert (d.kind, d.low, d.high, d.badge.value, d.source.ref) == ("uniform", 1.0, 2.0, "default", "test default")
    Assumption.model_validate(assumption_dict(value=q(2.0, "kg"), distribution=uniform_dict(low=2.0)))  # low == high
    with pytest.raises(ValidationError, match="low must be <= high"):
        Assumption.model_validate(assumption_dict(value=q(1.5, "kg"), distribution=uniform_dict(low=3.0)))
    for bad in (float("inf"), float("nan"), "1"):
        with pytest.raises(ValidationError, match="finite|valid number"):
            Assumption.model_validate(assumption_dict(value=q(1.5, "kg"), distribution=uniform_dict(high=bad)))


def test_normal_bounds_and_fields():
    nrm = assumption_dict()["distribution"]
    a = Assumption.model_validate(assumption_dict())
    d = a.distribution
    assert isinstance(d, NormalDistribution)
    assert (d.mean, d.std, d.clip_low, d.clip_high) == (1300.0, 50.0, 1000.0, None)
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Assumption.model_validate(assumption_dict(distribution={**nrm, "std": -1.0}))
    Assumption.model_validate(assumption_dict(distribution={**nrm, "std": 0.0}))
    with pytest.raises(ValidationError, match="clip_low must be <= clip_high"):
        Assumption.model_validate(assumption_dict(distribution={**nrm, "clip_low": 5.0, "clip_high": 1.0}))


def test_nominal_must_lie_inside_the_distribution_support():
    with pytest.raises(ValidationError, match="outside the uniform range"):
        Assumption.model_validate(assumption_dict(value=q(5.0, "kg"), distribution=uniform_dict()))
    with pytest.raises(ValidationError, match="outside the uniform range"):
        Assumption.model_validate(assumption_dict(value=q(0.5, "kg"), distribution=uniform_dict()))
    Assumption.model_validate(assumption_dict(value=q(1.0, "kg"), distribution=uniform_dict()))  # edges are inside
    Assumption.model_validate(assumption_dict(value=q(2.0, "kg"), distribution=uniform_dict()))
    nrm = assumption_dict()["distribution"]
    with pytest.raises(ValidationError, match="below clip_low"):
        Assumption.model_validate(assumption_dict(value=q(900.0, "kg"), distribution=nrm))
    with pytest.raises(ValidationError, match="above clip_high"):
        Assumption.model_validate(assumption_dict(value=q(1300.0, "kg"), distribution={**nrm, "clip_high": 1200.0}))
    Assumption.model_validate(assumption_dict(value=q(1000.0, "kg"), distribution=nrm))  # on the clip
    # an unclipped normal has unbounded support; the nominal need not equal the mean
    Assumption.model_validate(assumption_dict(value=q(-5.0, "kg"), distribution={**nrm, "clip_low": None}))


def test_a_spread_without_badge_and_source_is_rejected():
    for dist in (
        {"kind": "uniform", "low": 1.0, "high": 2.0},
        {"kind": "normal", "mean": 1.0, "std": 0.1},
        {"kind": "normal", "mean": 1.0, "std": 0.1, "badge": "estimate"},
    ):
        with pytest.raises(ValidationError, match="badge|source"):
            Assumption.model_validate(assumption_dict(value=q(1.0, "kg"), distribution=dist))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Assumption.model_validate(assumption_dict(distribution={"kind": "fixed", "std": 1.0}))


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        ({"value": 1.0, "unit": "kg"}, "badge"),
        (q(1.0, "g"), "unit"),
        (q(1.0, "kg", "cite", {"ref": "a book"}), "locator or source.url"),
        (q(1.0, "kg", "estimate", {"ref": "TBD"}), "placeholder"),
        (q("1.0", "kg"), "valid number"),
        (1.0, "valid dictionary|Quantity"),
    ],
)
def test_assumption_value_needs_badge_source_and_si_unit(bad, match):
    with pytest.raises(ValidationError, match=match):
        Assumption.model_validate(assumption_dict(value=bad, distribution={"kind": "fixed"}))


@pytest.mark.parametrize(
    ("badge", "source"),
    [
        ("sim", {"ref": "run 42"}),
        ("cite", {"ref": "Handbook", "url": "https://example.com/t"}),
        ("default", {"ref": "round number chosen for the demo"}),
        ("declared", SRC),
        ("estimate", {"ref": "ratio of two catalog masses"}),
    ],
)
def test_assumption_value_accepts_each_badge_with_its_own_rule(badge, source):
    a = Assumption.model_validate(assumption_dict(value=q(1.0, "kg", badge, source), distribution={"kind": "fixed"}))
    assert a.value.badge.value == badge


@pytest.mark.parametrize(
    ("field", "bad", "match"),
    [
        ("key", "Vehicle Mass", "pattern"),
        ("key", "vehicle-mass", "pattern"),
        ("key", "", "pattern"),
        ("label", "", "at least 1 character"),
        ("label", "   ", "label must not be blank"),
        ("label", "x" * 101, "at most 100 characters"),
        ("confidence", "medium", "Input should be"),
        ("confidence", "MED", "Input should be"),
        ("editable", "yes", "valid boolean"),
        ("editable", 1, "valid boolean"),
    ],
)
def test_assumption_key_label_confidence_editable_are_checked(field, bad, match):
    with pytest.raises(ValidationError, match=match):
        Assumption.model_validate(assumption_dict(**{field: bad}))


def test_assumption_confidence_and_editable_values():
    for c in ("low", "med", "high"):
        Assumption.model_validate(assumption_dict(confidence=c))
    assert Assumption.model_validate(assumption_dict(editable=False)).editable is False


@pytest.mark.parametrize("key", sorted(PLANET_CONSTANT_NAMES))
def test_planet_constant_keys_are_rejected_by_the_table_only(key):
    """A courtesy at table level; a standalone Assumption is not checked (the guarantee is the engine reading only
    data/bodies, W-03a, and the validator, C-02c)."""
    entry = assumption_dict(key=key, value=q(FAKE, "m/s^2"), distribution={"kind": "fixed"})
    assert Assumption.model_validate(entry).key == key
    with pytest.raises(ValidationError, match="planet constant"):
        AssumptionTable.model_validate({"assumptions": [entry]})


def test_assumption_table_rejects_duplicate_keys_and_unknown_fields():
    with pytest.raises(ValidationError, match="duplicate assumption key"):
        AssumptionTable.model_validate({"assumptions": [assumption_dict(), assumption_dict(label="Other")]})
    with pytest.raises(ValidationError, match="Extra inputs"):
        AssumptionTable.model_validate({"assumptions": [], "gravity": FAKE})
    with pytest.raises(ValidationError, match="Extra inputs"):
        Assumption.model_validate(assumption_dict(unit="kg"))  # the unit is the value's, not the assumption's
    with pytest.raises(ValidationError, match="Extra inputs"):
        Assumption.model_validate(assumption_dict(source="user"))  # the source is the value's, structured
    assert AssumptionTable().assumptions == ()


def test_order_of_assumptions_is_preserved():
    a, b = assumption_dict(key="b_key"), assumption_dict(key="a_key")
    t = AssumptionTable.model_validate({"assumptions": [a, b]})
    assert [x.key for x in t.assumptions] == ["b_key", "a_key"]
