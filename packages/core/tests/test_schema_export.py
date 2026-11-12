"""C-01d: JSON Schema and TypeScript export (`packages/core/scripts/export_schemas.py`, `schema_to_ts.py`)."""

from __future__ import annotations

import copy
import json
import sys
import types
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

import kinetra_core

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "packages" / "core" / "scripts"
SCHEMAS = ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

import export_schemas as ex  # noqa: E402
import schema_to_ts as ts  # noqa: E402

EXAMPLES = sorted((SCHEMAS / "examples").glob("*.json"))


def exported_models():
    return [n for n in kinetra_core.__all__ if isinstance(getattr(kinetra_core, n), type) and issubclass(getattr(kinetra_core, n), BaseModel)]


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# --- generated files are the committed files ---------------------------------------------------------------


def test_committed_schemas_match_the_models():
    """Drift fails: the same check CI runs (`export_schemas.py --check`)."""
    assert ex.diff(SCHEMAS, ex.render(kinetra_core)) == []


def test_every_exported_model_and_enum_has_a_schema_file_and_a_type():
    rendered = ex.render(kinetra_core)
    types_ts = rendered["types.ts"]
    for name in exported_models() + ["Badge", "Unit", "Distribution", "TerrainProp"]:
        assert f"{name}.schema.json" in rendered, name
        assert f"export interface {name} " in types_ts or f"export type {name} = " in types_ts, name


def test_rendering_is_deterministic():
    assert ex.render(kinetra_core) == ex.render(kinetra_core)


def test_check_reports_missing_changed_and_stale_files(tmp_path):
    rendered = ex.render(kinetra_core)
    ex.write(tmp_path, rendered)
    assert ex.diff(tmp_path, rendered) == []
    (tmp_path / "Badge.schema.json").unlink()
    (tmp_path / "types.ts").write_text("// edited by hand\n", encoding="utf-8")
    (tmp_path / "Gone.schema.json").write_text("{}\n", encoding="utf-8")
    assert ex.diff(tmp_path, rendered) == [
        "missing: Badge.schema.json",
        "differs: types.ts",
        "stale (no model produces it): Gone.schema.json",
    ]
    ex.write(tmp_path, rendered)  # writing repairs all three, and removes the stale file
    assert ex.diff(tmp_path, rendered) == []
    assert not (tmp_path / "Gone.schema.json").exists()


def test_write_leaves_hand_written_files_alone(tmp_path):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "keep.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    ex.write(tmp_path, ex.render(kinetra_core))
    assert (tmp_path / "examples" / "keep.json").exists() and (tmp_path / "package.json").exists()


def test_check_cli_exit_codes(tmp_path):
    assert ex.main(["--check", "--out", str(SCHEMAS)]) == 0
    assert ex.main(["--check", "--out", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []  # --check writes nothing
    assert ex.main(["--out", str(tmp_path)]) == 0
    assert ex.main(["--check", "--out", str(tmp_path)]) == 0


# --- generic: a model added later is picked up without editing the generator -------------------------------


def fake_package(**members) -> types.ModuleType:
    mod = types.ModuleType("fake_core")
    for k, v in members.items():
        setattr(mod, k, v)
    mod.__all__ = list(members)
    return mod


class Colour(StrEnum):
    RED = "red"
    BLUE = "blue"


class Wheel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["wheel"]
    radius: float = Field(gt=0, description="Radius [m].")
    colour: Colour = Colour.RED
    tags: tuple[str, ...] = ()
    note: str | None = None


class Skid(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["skid"]
    length: float


Runner = Annotated[Wheel | Skid, Field(discriminator="kind")]


def test_models_enums_and_union_aliases_are_discovered_from_all():
    mod = fake_package(Wheel=Wheel, Skid=Skid, Colour=Colour, Runner=Runner, LIMIT=3, helper=lambda: None)
    rendered = ex.render(mod)
    assert sorted(rendered) == [
        "Colour.schema.json", "Runner.schema.json", "Skid.schema.json", "Wheel.schema.json", "types.ts",
    ]
    t = rendered["types.ts"]
    assert 'export type Colour = "red" | "blue";' in t
    assert "export type Runner = Wheel | Skid;" in t
    assert "/** Radius [m]. */\n  radius: number;" in t
    assert 'kind: "wheel";' in t
    assert "colour?: Colour;" in t  # a default makes the field optional on input
    assert "tags?: string[];" in t
    assert "note?: string | null;" in t
    wheel = json.loads(rendered["Wheel.schema.json"])
    assert wheel["$schema"] == ex.SCHEMA_DIALECT
    assert set(wheel["$defs"]) == {"Colour"}
    Draft202012Validator.check_schema(wheel)


def test_a_class_that_is_not_a_model_fails_the_export_instead_of_being_skipped():
    class Plain:
        pass

    with pytest.raises(ex.ExportError, match="not a pydantic model or enum"):
        ex.render(fake_package(Wheel=Wheel, Plain=Plain))


def test_generic_aliases_are_exported_not_skipped():
    mod = fake_package(Wheel=Wheel, Wheels=list[Wheel], ByName=dict[str, Wheel], Pair=tuple[float, float], LIMIT=3)
    rendered = ex.render(mod)
    assert {"Wheels.schema.json", "ByName.schema.json", "Pair.schema.json"} <= set(rendered)
    t = rendered["types.ts"]
    assert "export type Wheels = Wheel[];" in t
    assert "export type ByName = Record<string, Wheel>;" in t
    assert "export type Pair = [number, number];" in t


def test_an_unsupported_schema_is_a_clean_error_not_a_traceback(monkeypatch, capsys):
    import kinetra_core as core

    def boom(_module):
        raise ts.UnsupportedSchema("#/$defs/X: unsupported JSON Schema keyword(s) ['not']")

    monkeypatch.setattr(ex, "render", boom)
    assert ex.main(["--check", "--out", "/nonexistent"]) == 1
    assert "export_schemas: #/$defs/X: unsupported" in capsys.readouterr().err
    assert core  # the real package is untouched


def test_a_class_exported_under_another_name_fails():
    with pytest.raises(ex.ExportError, match="under its own name"):
        ex.render(fake_package(Alias=Wheel))


def test_two_different_models_with_one_name_fail():
    def make(field_type):
        class Same(BaseModel):
            x: field_type

        return Same

    class Holder(BaseModel):
        other: make(int)

    other = make(str)
    with pytest.raises(ex.ExportError, match="two different schemas are named 'Same'"):
        ex.render(fake_package(Holder=Holder, Same=other))


def test_nothing_to_export_fails():
    with pytest.raises(ex.ExportError, match="no schema-bearing names"):
        ex.render(fake_package(LIMIT=3))


class OptionalTag(BaseModel):
    kind: Literal["opt"] = "opt"  # the default makes the tag optional in the schema
    x: float


class RequiredTag(BaseModel):
    kind: Literal["req"]
    x: float


class UnionHolder(BaseModel):
    item: Annotated[OptionalTag | RequiredTag, Field(discriminator="kind")]


def test_a_discriminator_tag_with_a_default_fails_the_export():
    with pytest.raises(ex.ExportError, match=r"discriminator 'kind' must be a required field of OptionalTag"):
        ex.render(fake_package(UnionHolder=UnionHolder, OptionalTag=OptionalTag, RequiredTag=RequiredTag))
    Alias = Annotated[OptionalTag | RequiredTag, Field(discriminator="kind")]
    with pytest.raises(ex.ExportError, match="OptionalTag"):
        ex.render(fake_package(Alias=Alias))


def test_every_discriminated_union_member_of_the_real_models_requires_its_tag():
    files, defs, _ = ex.collect(kinetra_core)
    tags = {
        n: d["properties"]["kind"] for n, d in defs.items() if "kind" in d.get("properties", {}) and n.endswith(("Prop", "Distribution", "Box", "Cylinder", "Sphere"))
    }
    assert {"Box", "Cylinder", "Sphere", "RampProp", "StepProp"} <= set(tags)
    for n in tags:
        assert "kind" in defs[n]["required"], n
        assert "default" not in tags[n], n


def test_primitive_kind_is_required_in_the_schema():
    bad = {"id": "a", "primitive": {"radius": {"offset": 0.1}}, "position": {"x": {"offset": 0}, "y": {"offset": 0}, "z": {"offset": 0}}}
    assert list(validator("ShapeComponent").iter_errors(bad)) != []


# --- the converter -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "string"}, "string"),
        ({"type": "integer"}, "number"),
        ({"type": "boolean"}, "boolean"),
        ({"const": "kg/m^3", "type": "string"}, '"kg/m^3"'),
        ({"enum": [1, 2]}, "1 | 2"),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string | null"),
        ({"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "number"}]}}, "(string | number)[]"),
        ({"type": "array", "prefixItems": [{"type": "number"}, {"type": "string"}], "minItems": 2, "maxItems": 2}, "[number, string]"),
        ({"type": "object", "additionalProperties": {"type": "number"}}, "Record<string, number>"),
        ({"$ref": "#/$defs/Unit"}, "Unit"),
        ({"type": "object", "properties": {"a-b": {"type": "string"}}, "required": ["a-b"]}, '{ "a-b": string }'),
        ({"type": "object", "properties": {"a": {"type": "string"}}}, "{ a?: string }"),
        ({"type": "number", "minimum": 0, "title": "X", "description": "d"}, "number"),
        ({"type": "string", "format": "date-time"}, "string"),
    ],
)
def test_converter_maps_schema_to_ts(schema, expected):
    assert ts.type_expr(schema) == expected


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "contentEncoding": "base64"},
        {"not": {"type": "string"}},
        {"allOf": [{"type": "string"}]},
        {"$ref": "https://example.com/x.json"},
        {"type": "array", "items": {"type": "string"}, "contains": {"type": "string"}},
        {"type": "object", "properties": {"a": {"type": "string"}}, "patternProperties": {"x": {}}},
        {"type": "mystery"},
    ],
)
def test_converter_refuses_what_it_cannot_type(schema):
    with pytest.raises(ts.UnsupportedSchema):
        ts.type_expr(schema)


def test_converter_error_names_the_path():
    with pytest.raises(ts.UnsupportedSchema, match=r"#/\$defs/Bad/properties/x: unsupported JSON Schema keyword"):
        ts.render_declarations({"Bad": {"type": "object", "properties": {"x": {"type": "string", "not": {}}}}}, {})


# --- the schemas accept what the models accept and reject what they reject ---------------------------------


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_validate_against_the_schema_and_the_model(path):
    name = path.name.split(".")[0]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(validator(name).iter_errors(data)) == []
    getattr(kinetra_core, name).model_validate(data)


def test_there_are_at_least_three_examples_and_each_names_an_exported_model():
    assert len(EXAMPLES) >= 3
    for p in EXAMPLES:
        assert p.name.split(".")[0] in exported_models(), p.name


def example(name: str):
    return json.loads((SCHEMAS / "examples" / name).read_text(encoding="utf-8"))


def mutate(data, path, value):
    data = copy.deepcopy(data)
    cur = data
    for k in path[:-1]:
        cur = cur[k]
    if value is KeyError:
        del cur[path[-1]]
    else:
        cur[path[-1]] = value
    return data


CAR = "DesignSpec.four-wheel-car.json"
BLOCK = "PartDef.block-with-hole.json"


@pytest.mark.parametrize(
    ("file", "name", "path", "bad"),
    [
        (CAR, "DesignSpec", ["materials", 0, "density", "source"], KeyError),  # source is required
        (CAR, "DesignSpec", ["materials", 0, "density", "badge"], KeyError),  # badge is required
        (CAR, "DesignSpec", ["materials", 0, "density", "badge"], "measured"),  # closed vocabulary
        (CAR, "DesignSpec", ["materials", 0, "density", "unit"], "g/cm^3"),  # unit is fixed per field
        (CAR, "DesignSpec", ["materials", 0, "density", "value"], -1.0),  # range
        (CAR, "DesignSpec", ["materials", 0, "density", "value"], "1000"),  # a number, not a string
        (CAR, "DesignSpec", ["instances", 0, "pose", "orientation"], [0, 0, 0, 1]),  # object, not array
        (CAR, "DesignSpec", ["instances", 0, "colour"], "red"),  # extra field
        (CAR, "DesignSpec", ["joints", 0, "kind"], "ball"),
        (BLOCK, "PartDef", ["shape", "components", 0, "primitive", "kind"], KeyError),  # the union tag is required
        (BLOCK, "PartDef", ["shape", "components", 1, "primitive", "kind"], "torus"),
        (BLOCK, "PartDef", ["shape", "components", 0, "primitive", "size_x"], KeyError),
        (BLOCK, "PartDef", ["shape", "components", 0, "operation"], "intersect"),
        ("World.ramp-and-step.json", "World", ["terrain_props", 0, "kind"], KeyError),  # kind is required
        ("World.ramp-and-step.json", "World", ["planet"], "Mars"),  # ID pattern
        ("World.ramp-and-step.json", "World", ["gravity"], 3.7),  # a planet constant has no field
    ],
)
def test_schema_rejects_what_the_model_rejects(file, name, path, bad):
    data = mutate(example(file), path, bad)
    assert list(validator(name).iter_errors(data)) != [], "the JSON Schema accepted it"
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        getattr(kinetra_core, name).model_validate(data)


def test_union_alias_schemas_select_by_discriminator_value():
    ramp = example("World.ramp-and-step.json")["terrain_props"][0]
    assert list(validator("TerrainProp").iter_errors(ramp)) == []
    assert list(validator("TerrainProp").iter_errors({**ramp, "kind": "wall"})) != []
    fixed = {"kind": "fixed"}
    assert list(validator("Distribution").iter_errors(fixed)) == []
    assert list(validator("Distribution").iter_errors({"kind": "fixed", "low": 1})) != []
