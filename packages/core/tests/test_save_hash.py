"""C-03: the project file (save, open, JSON export) and the canonical hash of a `Project` and its definitions.

Fixtures are the committed example projects (declared values, not real part data)."""

from __future__ import annotations

import copy
import json
import os
import random
import sys
import types
import typing
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

import kinetra_core
from kinetra_core import (
    CanonicalError,
    PartDef,
    Project,
    ProjectFile,
    ProjectFileError,
    ProjectFileErrorCode,
    canonical_json,
    definition_hash,
    dump_project,
    export_json,
    open_project,
    parse_project,
    project_file,
    project_hash,
    save_project,
)
from kinetra_core import canonical

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "schemas" / "examples"
SCHEMAS = ROOT / "schemas"
CAR = "Project.four-wheel-car.json"
ROCKET = "Project.rocket-car-skeleton.json"
EMPTY = "Project.empty.json"
FILE_EXAMPLE = "ProjectFile.four-wheel-car.json"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def project_of(data: dict) -> Project:
    return Project.model_validate(data)


@pytest.fixture(params=[CAR, ROCKET, EMPTY])
def example(request) -> Project:
    return project_of(load(request.param))


@pytest.fixture
def car() -> Project:
    return project_of(load(CAR))


def schema_validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8")))


# --- the number text -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("x", "text"),
    [
        (0.0, "0"), (-0.0, "0"), (1.0, "1"), (-1.0, "-1"), (0.1, "0.1"), (4.5, "4.5"), (100.0, "100"),
        (333333333.33333329, "333333333.3333333"), (1e20, "100000000000000000000"), (1e21, "1e+21"),
        (1.5e300, "1.5e+300"), (0.000001, "0.000001"), (1e-7, "1e-7"), (1.5e-7, "1.5e-7"),
        (5e-324, "5e-324"), (1.7976931348623157e308, "1.7976931348623157e+308"),
        (123456789012345680000.0, "123456789012345680000"), (9007199254740992.0, "9007199254740992"),
        (0.30000000000000004, "0.30000000000000004"), (-3.25, "-3.25"),
    ],
)
def test_hash_numbers_are_written_as_ecmascript_writes_them(x, text):
    """RFC 8785 3.2.2.3. The vectors are `String(x)` in a JavaScript engine (Bun), so a TypeScript client that
    hashes the same document gets the same bytes."""
    assert canonical._number(x) == text


def test_hash_number_text_reads_back_to_the_same_double():
    rng = random.Random(8785)
    for _ in range(3000):
        x = rng.uniform(-1, 1) * 10 ** rng.randint(-40, 40)
        assert float(canonical._number(x)) == x


# --- canonical form -----------------------------------------------------------------------------------------


def test_hash_canonical_form_has_sorted_keys_no_whitespace_and_leaves_out_defaults():
    p = project_of({"world": {"planet": "earth"}})
    assert canonical_json(p) == '{"world":{"planet":"earth"}}'
    explicit = project_of({"world": {"planet": "earth", "terrain_props": []}, "design": {"materials": []}, "assumptions": {"assumptions": []}})
    assert canonical_json(explicit) == canonical_json(p) and project_hash(explicit) == project_hash(p)


def test_hash_of_the_empty_project_is_pinned():
    # sha256 of the 28 bytes {"world":{"planet":"earth"}}: any other value means the canonical rules changed,
    # which needs a new file `version` (projectfile.py) and a new pinned value here.
    assert project_hash(project_of(load(EMPTY))) == "sha256:05fa3753cc2a73f77b4f54392164543d7d8893750e230551f799dbacc013133f"


def test_hash_of_the_example_projects_is_pinned():
    assert project_hash(project_of(load(CAR))) == "sha256:4c3283f83994dcb269b7fb6350aed31c841b60cc02ac3409de0e81e0ee30c66d"
    assert project_hash(project_of(load(ROCKET))) == "sha256:5f6f172996fa79cc910c6d28aa44a892af7f9b0e0b46160c5ea4cafa3c5dec13"


def test_hash_is_a_sha256_of_the_canonical_text(example):
    import hashlib

    assert project_hash(example) == "sha256:" + hashlib.sha256(canonical_json(example).encode("utf-8")).hexdigest()


def test_hash_text_is_utf8_unescaped_and_not_normalised():
    d = load(CAR)
    d["design"]["materials"][0]["name"] = "철 합금 \u00e9 \U0001f680"
    text = canonical_json(project_of(d))
    assert '"name":"철 합금 \u00e9 \U0001f680"' in text
    d2 = copy.deepcopy(d)
    d2["design"]["materials"][0]["name"] = "철 합금 e\u0301 \U0001f680"  # same look, different code points
    assert project_hash(project_of(d)) != project_hash(project_of(d2))


# --- the hash does not depend on display ----------------------------------------------------------------------


def _shuffle_lists(node, rng: random.Random):
    """Reorder every list in a JSON tree. Every list in a Project is a collection, none is a coordinate."""
    if isinstance(node, dict):
        return {k: _shuffle_lists(v, rng) for k, v in node.items()}
    if isinstance(node, list):
        out = [_shuffle_lists(v, rng) for v in node]
        rng.shuffle(out)
        return out
    return node


def _shuffle_keys(node, rng: random.Random):
    if isinstance(node, dict):
        keys = list(node)
        rng.shuffle(keys)
        return {k: _shuffle_keys(node[k], rng) for k in keys}
    if isinstance(node, list):
        return [_shuffle_keys(v, rng) for v in node]
    return node


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("name", [CAR, ROCKET])
def test_hash_does_not_depend_on_the_order_of_any_collection(name, seed):
    data = load(name)
    base = project_of(data)
    shuffled = project_of(_shuffle_lists(data, random.Random(seed)))
    assert project_hash(shuffled) == project_hash(base)
    assert canonical_json(shuffled) == canonical_json(base)


def test_hash_shuffling_really_reordered_the_example():
    data = load(CAR)
    assert project_of(_shuffle_lists(data, random.Random(0))) != project_of(data)


@pytest.mark.parametrize("seed", range(4))
def test_hash_does_not_depend_on_key_order_or_whitespace(seed):
    data = load(CAR)
    rng = random.Random(seed)
    text = json.dumps(_shuffle_keys(data, rng), indent=rng.choice([None, 0, 1, 4, "\t"]), separators=rng.choice([None, (",", ":"), (" , ", "  :  ")]))
    read = Project.model_validate_json(text)
    assert project_hash(read) == project_hash(project_of(data))


def test_hash_does_not_depend_on_how_a_number_is_written():
    data = load(CAR)
    text = json.dumps(data)
    assert "0.2" in text or "1.0" in text
    variants = [text.replace("1.0,", "1,").replace("1.0}", "1}"), text.replace("1.0,", "1.00,").replace("0.05,", "5e-2,")]
    for t in variants:
        assert project_hash(Project.model_validate_json(t)) == project_hash(project_of(data))


def test_hash_does_not_depend_on_the_utc_offset_of_a_timestamp():
    data = load(CAR)
    moved = copy.deepcopy(data)
    seen = 0

    def walk(node):
        nonlocal seen
        if isinstance(node, dict):
            if node.get("declared_at") == "2026-11-11T00:00:00Z":
                node["declared_at"] = "2026-11-11T09:00:00+09:00"
                seen += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(moved)
    assert seen > 10
    assert project_hash(project_of(moved)) == project_hash(project_of(data))
    one_second_later = json.loads(json.dumps(moved).replace("2026-11-11T09:00:00+09:00", "2026-11-11T09:00:01+09:00", 1))
    assert project_hash(project_of(one_second_later)) != project_hash(project_of(data))


def test_hash_timestamp_text_is_utc_without_trailing_fraction_zeros():
    from datetime import datetime, timedelta, timezone

    assert canonical._utc(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)) == "2026-01-02T03:04:05Z"
    assert canonical._utc(datetime(2026, 1, 2, 3, 4, 5, 500000, tzinfo=timezone(timedelta(hours=-5)))) == "2026-01-02T08:04:05.5Z"
    assert canonical._utc(datetime(2026, 1, 2, 3, 4, 5, 120, tzinfo=timezone.utc)) == "2026-01-02T03:04:05.00012Z"


# --- the hash does depend on everything else -------------------------------------------------------------------


def _leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, path + (i,))
    else:
        yield path, node


def _set(data, path, value):
    out = copy.deepcopy(data)
    cur = out
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    return out


def _changed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value * 1.5 + 0.0625 if value else 0.0625
    return value + "x"


@pytest.mark.parametrize("name", [CAR, ROCKET])
def test_hash_changes_when_any_single_value_changes(name):
    """Change each leaf of the document in turn. When the model still accepts the result, the hash differs."""
    data = load(name)
    base = project_hash(project_of(data))
    accepted = 0
    seen = {base}
    for path, value in _leaves(data):
        if value is None:
            continue
        try:
            changed = project_of(_set(data, path, _changed(value)))
        except ValueError:
            continue
        accepted += 1
        h = project_hash(changed)
        assert h != base, path
        seen.add(h)
    assert accepted > 100  # the walk covers most of the document, not a handful of leaves
    assert len(seen) == accepted + 1  # and no two different edits collide


def test_hash_depends_on_what_the_order_does_not_decide(car):
    """A joint's `a` is the parent and `b` the child: swapping them is a different joint, not a different display."""
    data = load(CAR)
    j = data["design"]["joints"][0]
    j["a"], j["b"] = j["b"], j["a"]
    assert project_hash(project_of(data)) != project_hash(car)


def test_hash_depends_on_the_quaternion_components_and_the_unit_text():
    data = load(CAR)
    base = project_hash(project_of(data))
    pose = data["design"]["instances"][0]["pose"]["orientation"]
    pose["x"], pose["w"] = pose["w"], pose["x"]
    assert project_hash(project_of(data)) != base


def test_hash_does_not_see_the_default_it_was_written_with():
    """A value equal to the field's default is the same document as the field left out (G5: fields can be added)."""
    data = load(CAR)
    for instance in data["design"]["instances"]:
        instance["material"] = instance.get("material")  # explicit None is the default
    data["design"]["schedule"] = data["design"].get("schedule", {"entries": []})
    assert project_hash(project_of(data)) == project_hash(project_of(load(CAR)))


def test_hash_of_a_shape_component_ignores_the_written_identity_orientation():
    part = PartDef.model_validate(load("PartDef.block-with-hole.json"))
    data = part.model_dump(mode="json")
    for comp in data["shape"]["components"]:
        comp["orientation"] = {"x": 0, "y": 0, "z": 0, "w": 1}
    assert definition_hash(PartDef.model_validate(data)) == definition_hash(part)


def test_hash_unknown_collection_has_no_canonical_order(monkeypatch):
    p = project_of(load(CAR))
    monkeypatch.delitem(canonical._ORDER, (kinetra_core.DesignSpec, "joints"))
    with pytest.raises(CanonicalError, match="no canonical order for DesignSpec.joints"):
        project_hash(p)


def _members(tp):
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        yield from _members(typing.get_args(tp)[0])
    elif origin in (typing.Union, types.UnionType):
        for arg in typing.get_args(tp):
            yield from _members(arg)
    elif origin is tuple:
        for arg in typing.get_args(tp):
            if arg is not Ellipsis:
                yield from _members(arg)
    else:
        yield tp


def _is_tuple_field(tp) -> bool:
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        return _is_tuple_field(typing.get_args(tp)[0])
    if origin in (typing.Union, types.UnionType):
        return any(_is_tuple_field(a) for a in typing.get_args(tp))
    return origin is tuple


def ordered_fields(root: type[BaseModel]) -> set[tuple[type, str]]:
    """Every (model, field) reachable from `root` whose type is a tuple: a collection that needs a canonical order."""
    seen: set[type] = set()
    stack = [root]
    found: set[tuple[type, str]] = set()
    while stack:
        model = stack.pop()
        if model in seen:
            continue
        seen.add(model)
        for name, hint in typing.get_type_hints(model, include_extras=True).items():
            if name.startswith("model_"):
                continue
            if _is_tuple_field(hint):
                found.add((model, name))
            stack.extend(m for m in _members(hint) if isinstance(m, type) and issubclass(m, BaseModel))
    return found


def test_hash_every_collection_of_the_project_model_has_a_canonical_order():
    """A leaf that adds a tuple field to a model reachable from `Project` fails here until it registers the field
    in `canonical._ORDER`, and a field whose order means something (a route of ids) must not be registered at all:
    the guard is per field, so a `tuple[str, ...]` is not sorted just because `SnapPoint.accepts` is."""
    fields = ordered_fields(Project)
    assert len(fields) >= 12
    assert sorted(f"{m.__name__}.{n}" for m, n in fields - set(canonical._ORDER)) == []
    assert sorted(f"{m.__name__}.{n}" for m, n in set(canonical._ORDER) - fields) == []  # nothing listed that holds no collection


class _Route(BaseModel):
    stops: tuple[str, ...]


class _Holder(BaseModel):
    route: _Route


class _Terms(BaseModel):
    accepts: tuple[str, ...]


def test_hash_a_new_tuple_field_on_a_scratch_model_is_not_sorted_silently():
    assert (_Route, "stops") in ordered_fields(_Holder)
    assert (_Route, "stops") not in canonical._ORDER
    with pytest.raises(CanonicalError, match=r"no canonical order for _Route\.stops"):
        canonical._plain(_Route(stops=("c", "a", "b")))
    # a field NAME that is registered on another model (SnapPoint.accepts) is no licence either
    with pytest.raises(CanonicalError, match=r"_Terms\.accepts"):
        canonical._plain(_Terms(accepts=("b", "a")))


def test_hash_collection_keys_are_unique_inside_a_collection(car):
    """The order is total only if the key is unique; the model checks that for every collection that has an id/name."""
    for field in ("materials", "parts", "instances", "joints", "actuators"):
        ids = [i.id for i in getattr(car.design, field)]
        assert len(ids) == len(set(ids)), field


# --- definition hashes --------------------------------------------------------------------------------------


def test_hash_of_a_definition_is_independent_of_the_project_around_it(car):
    wheel = next(p for p in car.design.parts if p.id == "wheel")
    other = project_of({"design": {"parts": [wheel.model_dump(mode="json")]}, "world": {"planet": "mars"}})
    assert definition_hash(other.design.parts[0]) == definition_hash(wheel)
    assert definition_hash(wheel).startswith("sha256:") and len(definition_hash(wheel)) == len("sha256:") + 64
    assert definition_hash(wheel) != definition_hash(next(p for p in car.design.parts if p.id != "wheel"))


def test_hash_of_a_definition_ignores_the_order_of_its_collections():
    part = PartDef.model_validate(load("PartDef.block-with-hole.json"))
    for seed in range(5):
        shuffled = PartDef.model_validate(_shuffle_lists(part.model_dump(mode="json"), random.Random(seed)))
        assert definition_hash(shuffled) == definition_hash(part)
    car = project_of(load(CAR))
    for p in car.design.parts:
        again = PartDef.model_validate(_shuffle_lists(p.model_dump(mode="json"), random.Random(3)))
        assert definition_hash(again) == definition_hash(p)


def test_hash_of_a_material_and_a_part_with_the_same_id_differ(car):
    material = car.design.materials[0]
    assert definition_hash(material) != definition_hash(car.design.parts[0])
    with pytest.raises(TypeError):
        definition_hash(car.world)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        project_hash(car.design)  # type: ignore[arg-type]


def test_hash_definitions_in_the_file_are_the_definitions_of_the_project(car):
    f = project_file(car)
    assert [(d.kind, d.id) for d in f.definitions] == [("material", m.id) for m in car.design.materials] + [("part", p.id) for p in car.design.parts]
    for d in f.definitions:
        source = next(m for m in car.design.materials if m.id == d.id) if d.kind == "material" else next(p for p in car.design.parts if p.id == d.id)
        assert d.hash == definition_hash(source)
    assert f.project_hash == project_hash(car)


# --- save and open ----------------------------------------------------------------------------------------


def test_save_open_save_is_byte_identical(example, tmp_path):
    first = tmp_path / "a.kinetra.json"
    second = tmp_path / "b.kinetra.json"
    save_project(example, first)
    opened = open_project(first)
    assert opened.project == example  # the same Project, the order of every collection included
    save_project(opened.project, second)
    assert first.read_bytes() == second.read_bytes()
    opened_again = open_project(second)
    assert opened_again == opened
    assert dump_project(opened_again.project) == first.read_bytes()


def test_save_open_save_is_byte_identical_for_a_project_that_was_edited():
    """The state a user saves is the result of commands, not a hand-written example."""
    from kinetra_core import MoveInstance, SelectPlanet, apply_command

    p = project_of(load(CAR))
    moved = apply_command(p, MoveInstance(type="move_instance", id=p.design.instances[2].id, pose=p.design.instances[2].pose.model_copy(update={"position": p.design.instances[2].pose.position.model_copy(update={"x": 0.1 + 0.2})}))).project
    moved = apply_command(moved, SelectPlanet(type="select_planet", planet="moon")).project
    data = dump_project(moved)
    again = parse_project(data)
    assert again.project == moved
    assert dump_project(again.project) == data


def test_save_keeps_the_order_the_user_has_and_the_hash_does_not_care(tmp_path):
    data = load(CAR)
    reversed_ = copy.deepcopy(data)
    for field in ("materials", "parts", "instances", "joints", "actuators"):
        reversed_["design"][field].reverse()
    a, b = project_of(data), project_of(reversed_)
    assert a != b
    save_project(b, tmp_path / "b.json")
    assert open_project(tmp_path / "b.json").project == b  # opened in the order it was saved
    assert [i.id for i in open_project(tmp_path / "b.json").project.design.instances] == [i.id for i in b.design.instances]
    assert dump_project(a) != dump_project(b)
    assert project_file(a).project_hash == project_file(b).project_hash


def test_save_is_deterministic_and_writes_utf8_json_with_one_trailing_newline(car, tmp_path):
    assert dump_project(car) == dump_project(project_of(load(CAR)))
    data = dump_project(car)
    assert data.endswith(b"}\n") and not data.endswith(b"\n\n")
    text = data.decode("utf-8")
    assert json.loads(text)["format"] == "kinetra-project" and json.loads(text)["version"] == 1
    assert text.startswith('{\n  "format": "kinetra-project",\n  "version": 1,\n  "project": {')


def test_save_writes_non_ascii_text_as_utf8(tmp_path):
    d = load(CAR)
    d["design"]["materials"][0]["name"] = "철 \U0001f680"
    p = project_of(d)
    path = tmp_path / "k.kinetra.json"
    save_project(p, path)
    assert "철 \U0001f680".encode("utf-8") in path.read_bytes()
    assert open_project(path).project == p


def test_save_is_atomic_a_failed_write_leaves_the_old_file_and_no_temporary(car, tmp_path, monkeypatch):
    path = tmp_path / "p.kinetra.json"
    save_project(project_of({"world": {"planet": "earth"}}), path)
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        save_project(car, path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["p.kinetra.json"]


def test_save_replaces_an_existing_file_whole(car, tmp_path):
    path = tmp_path / "p.kinetra.json"
    save_project(car, path)
    small = project_of({"world": {"planet": "earth"}})
    save_project(small, path)
    assert open_project(path).project == small
    assert [p.name for p in tmp_path.iterdir()] == ["p.kinetra.json"]


def test_save_returns_what_it_wrote(car, tmp_path):
    f = save_project(car, tmp_path / "x.kinetra.json")
    assert f == open_project(tmp_path / "x.kinetra.json") and isinstance(f, ProjectFile)


def test_save_open_reads_a_file_with_other_whitespace_and_key_order(car):
    """A file another program wrote (compact, keys shuffled) opens; its hashes are checked against the canonical form."""
    raw = json.loads(dump_project(car))
    text = json.dumps(_shuffle_keys(raw, random.Random(1)), separators=(",", ":"))
    f = parse_project(text)
    assert f.project == car and f.project_hash == project_hash(car)
    assert dump_project(f.project) == dump_project(car)  # normalised on the way out, then stable


def test_save_open_reads_a_file_whose_collections_are_in_another_order(car):
    raw = json.loads(dump_project(car))
    raw["project"] = _shuffle_lists(raw["project"], random.Random(5))
    raw["definitions"].reverse()
    f = parse_project(json.dumps(raw))
    assert f.project != car and project_hash(f.project) == project_hash(car)  # same thing, shown in another order


# --- JSON export ------------------------------------------------------------------------------------------


def test_save_export_json_is_the_project_without_the_envelope(example):
    data = export_json(example)
    assert Project.model_validate_json(data) == example
    assert "project_hash" not in json.loads(data) and "format" not in json.loads(data)
    assert list(schema_validator("Project").iter_errors(json.loads(data))) == []
    assert export_json(Project.model_validate_json(data)) == data


def test_save_file_validates_against_the_committed_json_schema(example):
    assert list(schema_validator("ProjectFile").iter_errors(json.loads(dump_project(example)))) == []


def test_save_the_committed_file_example_is_what_the_writer_writes():
    """`schemas/examples/ProjectFile.four-wheel-car.json` is the file for `Project.four-wheel-car.json`. When the
    model changes on purpose, rewrite it with `dump_project` (and bump the file version if the rules changed)."""
    expected = dump_project(project_of(load(CAR)))
    assert (EXAMPLES / FILE_EXAMPLE).read_bytes() == expected
    assert parse_project((EXAMPLES / FILE_EXAMPLE).read_bytes()).project == project_of(load(CAR))


# --- refusing what is not a project file ---------------------------------------------------------------------


def refused(data, code):
    with pytest.raises(ProjectFileError) as e:
        parse_project(data)
    assert e.value.code is code, str(e.value)
    return str(e.value)


def written(project=None) -> dict:
    return json.loads(dump_project(project or project_of(load(CAR))))


def test_save_open_refuses_text_that_is_not_json():
    for data in (b"", b"{", b"\xff\xfe", b"[1,", "not json"):
        refused(data, ProjectFileErrorCode.NOT_JSON)


def test_save_open_refuses_duplicate_keys_and_non_finite_numbers():
    ok = json.dumps(written())
    assert "duplicate key" in refused(ok.replace('"version": 1', '"version": 1, "version": 1'), ProjectFileErrorCode.NOT_JSON)
    assert "NaN" in refused(ok.replace('"planet": "earth"', '"planet": "earth", "x": NaN'), ProjectFileErrorCode.NOT_JSON)
    assert "Infinity" in refused(ok.replace('"version": 1', '"version": Infinity'), ProjectFileErrorCode.NOT_JSON)


def test_save_open_refuses_what_is_not_a_project_file():
    refused("[]", ProjectFileErrorCode.NOT_A_PROJECT_FILE)
    refused("{}", ProjectFileErrorCode.NOT_A_PROJECT_FILE)
    refused(json.dumps(load(CAR)), ProjectFileErrorCode.NOT_A_PROJECT_FILE)  # a bare Project is the export, not the file
    refused(json.dumps({**written(), "format": "other"}), ProjectFileErrorCode.NOT_A_PROJECT_FILE)
    for key in ("project", "project_hash", "definitions"):
        d = written()
        del d[key]
        refused(json.dumps(d), ProjectFileErrorCode.NOT_A_PROJECT_FILE if key != "project" else ProjectFileErrorCode.INVALID_PROJECT)
    refused(json.dumps({**written(), "extra": 1}), ProjectFileErrorCode.NOT_A_PROJECT_FILE)
    refused(json.dumps({**written(), "project_hash": "md5:00"}), ProjectFileErrorCode.NOT_A_PROJECT_FILE)


@pytest.mark.parametrize("version", [0, 2, "1", 1.5, True, None])
def test_save_open_refuses_a_version_it_does_not_read(version):
    msg = refused(json.dumps({**written(), "version": version}), ProjectFileErrorCode.UNSUPPORTED_VERSION)
    assert "this reader opens version 1" in msg


def test_save_open_refuses_an_invalid_project_with_the_validators_sentence():
    d = written()
    d["project"]["design"]["joints"][0]["a"]["instance"] = "no-such-instance"
    assert "no-such-instance" in refused(json.dumps(d), ProjectFileErrorCode.INVALID_PROJECT)
    d = written()
    d["project"]["design"]["instances"][0]["pose"].pop("source")
    refused(json.dumps(d), ProjectFileErrorCode.INVALID_PROJECT)


def test_save_open_refuses_a_file_edited_after_it_was_saved():
    d = written()
    d["project"]["design"]["materials"][0]["density"]["value"] += 1.0
    msg = refused(json.dumps(d), ProjectFileErrorCode.HASH_MISMATCH)
    assert "project_hash" in msg and f"material {d['project']['design']['materials'][0]['id']!r}" in msg


def test_save_open_refuses_a_file_whose_definition_hashes_do_not_match():
    d = written()
    d["definitions"][1]["hash"] = "sha256:" + "0" * 64
    assert "file says sha256:000" in refused(json.dumps(d), ProjectFileErrorCode.HASH_MISMATCH)
    d = written()
    d["definitions"].pop()
    assert "has no hash for" in refused(json.dumps(d), ProjectFileErrorCode.HASH_MISMATCH)
    d = written()
    d["definitions"].append({"kind": "part", "id": "ghost", "hash": "sha256:" + "1" * 64})
    assert "which the project does not carry" in refused(json.dumps(d), ProjectFileErrorCode.HASH_MISMATCH)
    d = written()
    d["definitions"].append(d["definitions"][0])
    assert "twice" in refused(json.dumps(d), ProjectFileErrorCode.HASH_MISMATCH)


def test_save_open_refuses_a_truncated_file(car, tmp_path):
    path = tmp_path / "p.kinetra.json"
    save_project(car, path)
    data = path.read_bytes()
    for cut in (len(data) // 2, len(data) - 2, 1):
        path.write_bytes(data[:cut])
        with pytest.raises(ProjectFileError) as e:
            open_project(path)
        assert e.value.code is ProjectFileErrorCode.NOT_JSON


def test_save_open_of_a_missing_file_is_an_os_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_project(tmp_path / "nope.kinetra.json")


def test_save_open_the_hash_says_same_or_different_not_who_wrote_it():
    """A file with a changed value and the matching hash is a valid file of another project: the hash is not a
    signature (it says same-or-different, not who wrote it)."""
    d = written()
    d["project"]["design"]["materials"][0]["density"]["value"] += 1.0
    changed = project_of(d["project"])
    d["project_hash"] = project_hash(changed)
    d["definitions"] = json.loads(dump_project(changed))["definitions"]
    assert parse_project(json.dumps(d)).project == changed


# --- the defaults the hash leaves out are pinned --------------------------------------------------------------


OMITTED_DEFAULTS = {
    "Actuator.joint": None,
    "Actuator.supply": None,
    "Assumption.binding": None,
    "Assumption.distribution": {"kind": "fixed"},
    "Assumption.editable": True,
    "AssumptionTable.assumptions": [],
    "AxisExpr.terms": [],
    "ControlSchedule.entries": [],
    "DesignSpec.actuators": [],
    "DesignSpec.instances": [],
    "DesignSpec.joints": [],
    "DesignSpec.materials": [],
    "DesignSpec.parts": [],
    "DesignSpec.schedule": {"entries": []},
    "Instance.material": None,
    "Instance.parameters": [],
    "Joint.axis": None,
    "Joint.break_threshold": None,
    "Joint.limits": None,
    "NormalDistribution.clip_high": None,
    "NormalDistribution.clip_low": None,
    "PartDef.curves": [],
    "PartDef.mass_parameter": None,
    "PartDef.role": None,
    "PartDef.parameters": [],
    "PartDef.shape": None,
    "PartDef.snap_points": [],
    "PartDef.specs": [],
    "Project.assumptions": {"assumptions": []},
    "Project.design": {"materials": [], "parts": [], "instances": [], "joints": [], "actuators": [], "schedule": {"entries": []}},
    "RampProp.material": None,
    "ShapeComponent.operation": "add",
    "ShapeComponent.orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    "SnapPoint.accepts": [],
    "Source.declared_at": None,
    "Source.declared_by": None,
    "Source.license": None,
    "Source.locator": None,
    "Source.url": None,
    "StepProp.material": None,
    "World.terrain_props": [],
}


def test_hash_omitted_defaults_are_pinned():
    """The canonical text leaves out every optional field that holds its default, so each default is part of the
    rules: a changed default changes what an omitted field means and what a file hashes to. This table is the rule.
    A failure here means CHANGING A MODEL DEFAULT IS A CHANGE OF THE FILE FORMAT: bump `projectfile.VERSION`, keep
    reading the older version by its own rules and migrate (project-model.md, "저장·열기와 정의 해시"), and only then
    edit this table."""
    from pydantic import TypeAdapter

    actual = {}
    for model, name in sorted(_walk_models(Project), key=lambda mn: (mn[0].__name__, mn[1])):
        field = model.model_fields[name]
        if field.is_required():
            continue
        default = field.get_default(call_default_factory=True)
        actual[f"{model.__name__}.{name}"] = None if default is None else TypeAdapter(type(default)).dump_python(default, mode="json")
    assert actual == OMITTED_DEFAULTS


def _walk_models(root):
    seen, stack = set(), [root]
    while stack:
        model = stack.pop()
        if model in seen:
            continue
        seen.add(model)
        for name, hint in typing.get_type_hints(model, include_extras=True).items():
            if name.startswith("model_"):
                continue
            yield model, name
            stack.extend(m for m in _members(hint) if isinstance(m, type) and issubclass(m, BaseModel))


def test_hash_of_a_part_with_a_shape_is_pinned():
    """`block-with-hole` has a shape with an omitted `orientation` and a default `operation`."""
    part = PartDef.model_validate(load("PartDef.block-with-hole.json"))
    assert definition_hash(part) == "sha256:50a101681253c56d230d115e76b26965a8ac9dd4359ba7d275228236d706930a"


def test_hash_a_shape_component_with_its_operation_written_out_is_the_same_definition():
    data = PartDef.model_validate(load("PartDef.block-with-hole.json")).model_dump(mode="json")
    assert any(c["operation"] == "add" for c in data["shape"]["components"])  # model_dump writes the default
    assert definition_hash(PartDef.model_validate(data)) == definition_hash(PartDef.model_validate(load("PartDef.block-with-hole.json")))


# --- the frozen v1 file -------------------------------------------------------------------------------------

V1_FILE = Path(__file__).parent / "fixtures" / "project-file-v1.kinetra.json"
V1_PROJECT_HASH = "sha256:6500512c2dd957e47b65b737c9b289779e3ac09ed1cb76a44c7918b02e3c6124"


def test_save_open_reads_the_frozen_v1_file():
    """`fixtures/project-file-v1.kinetra.json` is a file written by the first release of the format. It is NEVER
    regenerated (unlike `schemas/examples/ProjectFile.*`, which tracks the writer): a later change that makes it
    unreadable, or that changes its hash or the bytes the writer gives for it, breaks users' saved files. The way out
    is a new `version` that still reads this one by its own rules, not an edit of this file or of the pins."""
    raw = V1_FILE.read_bytes()
    opened = parse_project(raw)
    assert opened.version == 1 and opened.project_hash == V1_PROJECT_HASH == project_hash(opened.project)
    assert any(p.shape is not None for p in opened.project.design.parts)  # it covers a shape, the omitted-default case
    # The writer writes every field, so a field a later build adds (B-02c's `PartDef.mass_parameter`: optional, default
    # None) appears in what it writes and not in this old file: the bytes may differ, the project and its hash may not.
    again = parse_project(dump_project(opened.project))
    assert again.project == opened.project and again.project_hash == V1_PROJECT_HASH
    assert dump_project(again.project) == dump_project(opened.project)
    old, new = json.loads(raw), json.loads(dump_project(opened.project))
    assert old["project_hash"] == new["project_hash"] and old["definitions"] == new["definitions"]


# --- save: concurrency, links, permissions ---------------------------------------------------------------------


def test_save_concurrent_saves_of_one_path_leave_one_whole_file(car, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "p.kinetra.json"
    small = project_of({"world": {"planet": "mars"}})
    projects = [car, small, project_of(load(ROCKET)), project_of({"world": {"planet": "earth"}})]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(save_project, projects[i % 4], path) for i in range(160)]
        for f in futures:
            f.result()  # none raises
    assert open_project(path).project in projects  # one whole file, not a mix
    assert [p.name for p in tmp_path.iterdir()] == ["p.kinetra.json"]  # no temporary left


def test_save_does_not_follow_a_link_planted_at_a_predictable_temporary_name(car, tmp_path, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    path = tmp_path / "p.kinetra.json"
    # even if an attacker guessed the name, O_EXCL refuses the link instead of writing through it
    monkeypatch.setattr("secrets.token_hex", lambda n: "00" * n)
    (tmp_path / ".kinetra-0000000000000000.tmp").symlink_to(victim)
    with pytest.raises(FileExistsError):
        save_project(car, path)
    assert victim.read_text() == "keep me" and not path.exists()


def test_save_through_a_symlink_updates_the_real_file_and_keeps_the_link(car, tmp_path):
    real_dir = tmp_path / "sync"
    real_dir.mkdir()
    real = real_dir / "real.kinetra.json"
    save_project(project_of({"world": {"planet": "earth"}}), real)
    link = tmp_path / "link.kinetra.json"
    link.symlink_to(real)
    save_project(car, link)
    assert link.is_symlink() and os.readlink(link) == str(real)
    assert open_project(real).project == car
    assert sorted(p.name for p in real_dir.iterdir()) == ["real.kinetra.json"]


@pytest.mark.skipif(os.name != "posix", reason="permission bits")
def test_save_keeps_the_permission_bits_of_the_file_it_replaces(car, tmp_path):
    path = tmp_path / "p.kinetra.json"
    save_project(project_of({"world": {"planet": "earth"}}), path)
    os.chmod(path, 0o600)
    save_project(car, path)
    assert (path.stat().st_mode & 0o777) == 0o600
    os.chmod(path, 0o640)
    save_project(car, path)
    assert (path.stat().st_mode & 0o777) == 0o640


def test_save_a_new_file_gets_the_default_permissions(car, tmp_path):
    path = tmp_path / "new.kinetra.json"
    save_project(car, path)
    assert open_project(path).project == car


def test_save_asks_the_device_to_flush(car, tmp_path, monkeypatch):
    calls = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real_fsync(fd))[1])
    if sys.platform == "darwin":
        import fcntl

        real_fcntl = fcntl.fcntl
        monkeypatch.setattr(fcntl, "fcntl", lambda fd, op, *a: (calls.append(op), real_fcntl(fd, op, *a))[1])
        save_project(car, tmp_path / "p.kinetra.json")
        assert fcntl.F_FULLFSYNC in calls
    else:
        save_project(car, tmp_path / "p.kinetra.json")
        assert calls


# --- values the model accepts but cannot be written, and hostile input -----------------------------------------


@pytest.mark.parametrize("stamp", ["0001-01-01T00:00:00+09:00", "9999-12-31T23:59:59-01:00"])
def test_hash_a_timestamp_that_overflows_utc_is_a_canonical_error_not_an_overflow(stamp, tmp_path):
    data = load(CAR)
    walk_stamp = []

    def walk(node):
        if isinstance(node, dict):
            if "declared_at" in node:
                node["declared_at"] = stamp
                walk_stamp.append(1)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data["design"]["materials"][0])
    assert walk_stamp
    p = project_of(data)  # the model accepts it
    with pytest.raises(CanonicalError, match="outside the years 1 to 9999"):
        project_hash(p)
    with pytest.raises(CanonicalError):
        save_project(p, tmp_path / "x.kinetra.json")
    assert list(tmp_path.iterdir()) == []
    text = json.dumps({"format": "kinetra-project", "version": 1, "project": data, "project_hash": "sha256:" + "0" * 64, "definitions": []})
    assert refused(text, ProjectFileErrorCode.INVALID_PROJECT)


def test_save_open_refuses_json_nested_too_deeply_as_not_json():
    for depth in (300_000,):
        msg = refused("[" * depth, ProjectFileErrorCode.NOT_JSON)
        assert msg
    nested = '{"format":"kinetra-project","version":1,"project":' + "[" * 200_000 + "]" * 200_000 + "}"
    refused(nested, ProjectFileErrorCode.NOT_JSON)


@pytest.mark.skipif(os.name != "posix", reason="permission bits")
def test_save_the_temporary_file_is_never_more_permissive_than_the_target(car, tmp_path, monkeypatch):
    """Check the mode of the temporary file right after it is created and at every `chmod`, for a 0600 target."""
    path = tmp_path / "p.kinetra.json"
    save_project(project_of({"world": {"planet": "earth"}}), path)
    os.chmod(path, 0o600)
    modes = []
    real_open, real_chmod = os.open, os.chmod

    def spy_open(p, flags, mode=0o777, **kw):
        fd = real_open(p, flags, mode, **kw)
        if str(p).endswith(".tmp"):
            modes.append(("created", os.fstat(fd).st_mode & 0o777))
        return fd

    def spy_chmod(p, mode, **kw):
        modes.append(("chmod", mode & 0o777))
        return real_chmod(p, mode, **kw)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "chmod", spy_chmod)
    old = os.umask(0)  # the loosest umask: only the explicit mode can keep the temporary file private
    try:
        save_project(car, path)
    finally:
        os.umask(old)
    assert modes and modes[0] == ("created", 0o600)
    assert all(m & ~0o600 == 0 for _, m in modes)
    assert (path.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="permission bits")
def test_save_a_new_file_gets_the_default_mode_of_the_umask(car, tmp_path):
    old = os.umask(0o027)
    try:
        save_project(car, tmp_path / "new.kinetra.json")
    finally:
        os.umask(old)
    assert ((tmp_path / "new.kinetra.json").stat().st_mode & 0o777) == 0o640


def test_canonical_order_sorts_every_collection_keeps_the_value_and_reads_one_project_one_way():
    """#511: `canonical_order` is the one reading order of the compiler. It is the order `canonical_json` writes, all the way
    down, so projects with one `project_hash` become equal values."""
    from kinetra_core import canonical_order

    project = Project.model_validate_json((EXAMPLES / "Project.four-wheel-car.json").read_text(encoding="utf-8"))
    data = project.model_dump(mode="json")
    data["design"]["instances"].reverse()
    data["design"]["joints"].reverse()
    data["design"]["parts"].reverse()
    for p in data["design"]["parts"]:
        p["snap_points"].reverse()
        p["parameters"].reverse()
    shuffled = Project.model_validate(data)
    assert shuffled != project and project_hash(shuffled) == project_hash(project)
    ordered = canonical_order(shuffled)
    assert ordered == canonical_order(project)
    assert [i.id for i in ordered.design.instances] == sorted(i.id for i in project.design.instances)
    assert [j.id for j in ordered.design.joints] == sorted(j.id for j in project.design.joints)
    assert canonical_json(ordered) == canonical_json(shuffled) and project_hash(ordered) == project_hash(project)
    assert shuffled.design.instances[0].id != ordered.design.instances[0].id  # the input is not changed
    with pytest.raises(TypeError):
        canonical_order("not a model")  # type: ignore[type-var]
