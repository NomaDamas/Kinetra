"""G-04: the permission guard of the agent path and the out-of-catalog labels.

    uv run pytest packages/engine -q -k guard

Five bypass attempts (`test_guard_bypass_1..5`), each through `EditTools.run` and through the `Hub` (`HubEditTools`, the path the
MCP server G-08 takes): nothing changes, the reason is `forbidden` and says why. Then the catalog: a value beyond the catalogs is
labelled with the existing labels (B-03c `catalog_finding`, C-06 `카탈로그와 다름`) and published only with the user's confirmation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import kinetra_engine.agent.edit_tools as edit_tools_module
from kinetra_core import (
    AddMaterialDef,
    AddPartDef,
    Material,
    Origin,
    PartDef,
    Project,
    Publish,
    ReasonCode,
    ReplaceMaterialDef,
    apply_command,
    load_material_catalog,
)
from kinetra_core.protocol import VerdictState
from kinetra_engine.agent import EditTools, HubEditTools, guard_arguments, load_library, out_of_catalog, specs
from kinetra_engine.parts import catalog_finding
from kinetra_engine.protocol import Hub

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "schemas" / "examples"
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
GROUND = {"type": "on_ground"}
DECLARED_8KN = PartDef.model_validate_json((EXAMPLES / "PartDef.thruster-declared-8kn.json").read_text(encoding="utf-8"))
OWN_MATERIAL = Material.model_validate_json((EXAMPLES / "Material.example.json").read_text(encoding="utf-8"))


def empty():
    return Project.model_validate({"world": {"planet": "mars"}})


def snap(point, instance, target_point):
    return {"type": "snap_to", "snap_point": point, "target": {"instance": instance, "snap_point": target_point}, "facing": "opposed"}


@pytest.fixture(scope="module")
def tools():
    return EditTools(clock=lambda: NOW)


def codes(result):
    return [r.code for r in result.reasons]


@pytest.fixture
def desk(tools):
    """A plate on the ground; the project also carries the user's own declared 8 kN thruster and own material, unused."""
    p = tools.run(empty(), "add_part", {"part": "plate", "place": GROUND, "material": "al6061-t6"}).project
    p = apply_command(p, AddPartDef(type="add_part_def", part=DECLARED_8KN)).project
    return apply_command(p, AddMaterialDef(type="add_material_def", material=OWN_MATERIAL)).project


def hub_of(project):
    hub = Hub({"desk": project})
    return hub, hub.documents["desk"]


def assert_refused_everywhere(tools, project, tool, args, monkeypatch):
    """Refused as `forbidden` by the pure tools without reaching the validator, and through the Hub nothing is published."""
    seen = []
    monkeypatch.setattr(edit_tools_module, "validate_command", lambda *a, **k: seen.append(a))
    r = tools.run(project, tool, json.dumps(args))
    assert not r.ok and r.command is None and r.project is None and not seen
    assert r.reasons and set(codes(r)) == {ReasonCode.FORBIDDEN}, r.reasons
    monkeypatch.undo()
    hub, doc = hub_of(project)
    h = HubEditTools(hub, "desk", tools=tools).call(tool, args)
    assert not h.ok and set(codes(h)) == {ReasonCode.FORBIDDEN}
    assert doc.revision == 0 and doc.project == project and doc.verdict is VerdictState.NONE and not doc.history.entries
    return r


# --- 1. a tool that is not one, named for what an agent cannot change --------------------------------------------


@pytest.mark.parametrize(
    "tool", ["set_gravity", "setPlanetConstants", "set_atmosphere", "edit_material_catalog", "set_density", "add_material", "set_verdict", "write_p_success"]
)
def test_guard_bypass_1_a_tool_named_for_a_planet_constant_the_catalog_or_a_verdict(tools, desk, monkeypatch, tool):
    r = assert_refused_everywhere(tools, desk, tool, {"value": 1.0}, monkeypatch)
    assert "there is no tool" in r.reasons[0].message and "planet constant" in r.reasons[0].message


def test_guard_bypass_1_an_unknown_tool_without_such_a_word_is_still_a_schema_violation(tools):
    assert codes(tools.run(empty(), "teleport_part", "{}")) == [ReasonCode.INVALID_COMMAND]


# --- 2. a planet constant or a verdict smuggled into a real tool -------------------------------------------------


@pytest.mark.parametrize(
    "args,where",
    [
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "gravity": 3.72}, "gravity"),
        ({"part": "beam", "place": {**snap("bottom", "plate-1", "top"), "joint": {"kind": "fixed", "Gravity": 1}}}, "place.joint.Gravity"),
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "surfaceGravity": 3.72}, "surfaceGravity"),  # camelCase
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "parameters": {"g": 1.62}}, "parameters.g"),  # as a "parameter"
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "air-density": 0.02}, "air-density"),
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "P_Success": 0.99}, "P_Success"),
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "meta": [{"verdict": "FEASIBLE_FOUND"}]}, "meta[0].verdict"),
        ({"part": "beam", "place": snap("bottom", "plate-1", "top"), "confidenceInterval": [0.9, 1]}, "confidenceInterval"),
    ],
)
def test_guard_bypass_2_a_planet_constant_or_a_verdict_inside_a_real_tool(tools, desk, monkeypatch, args, where):
    r = assert_refused_everywhere(tools, desk, "add_part", args, monkeypatch)
    assert any(x.message.startswith(f"add_part: {where}:") for x in r.reasons)
    assert "data/bodies" in r.reasons[0].message


# --- 3. the material catalog ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        {"instance": "plate-1", "material": {"id": "al6061-t6", "density": {"value": 1.0, "unit": "kg/m^3"}}},  # a definition for an id
        {"instance": "plate-1", "material": "al6061-t6", "density": 1.0},
        {"instance": "plate-1", "material": "al6061-t6", "yieldStrength": 9e9},
        {"instance": "plate-1", "material": "al6061-t6", "catalog_entry": {"friction": 0.01}},
    ],
)
def test_guard_bypass_3_the_material_catalog_cannot_be_changed_by_a_tool(tools, desk, monkeypatch, args):
    before = load_material_catalog()
    assert_refused_everywhere(tools, desk, "set_material", args, monkeypatch)
    assert load_material_catalog() == before


def test_guard_bypass_3_a_raw_command_published_as_the_agent_meets_the_same_validator(desk):
    """The way around the tools, a `Publish` of a hand-made command with origin agent, is refused by the validator (C-02c):
    the catalog's id with other numbers, or the catalog's citation on another id with other numbers."""
    catalog = load_material_catalog()
    al = catalog.get("al6061-t6").material
    cheat = al.model_copy(update={"density": al.density.model_copy(update={"value": 1.0})})
    renamed = cheat.model_copy(update={"id": "al-light", "name": "light aluminium"})
    hub, doc = hub_of(desk)
    for n, command in enumerate(
        (ReplaceMaterialDef(type="replace_material_def", material=cheat), AddMaterialDef(type="add_material_def", material=renamed))
    ):
        message = Publish(type="publish", id=f"cheat{n}", base_revision=doc.revision, command=command, origin=Origin.AGENT)
        reply = hub.publish("desk", message).reply
        assert reply.type == "rejected" and [r.code for r in reply.reasons] == [ReasonCode.FORBIDDEN]
    assert doc.revision == 0 and doc.project == desk and load_material_catalog() == catalog


# --- 4. a part the agent invents -----------------------------------------------------------------------------------


def test_guard_bypass_4_a_part_cannot_be_invented(tools, desk, monkeypatch):
    invented = json.loads(DECLARED_8KN.model_dump_json()) | {"id": "thruster-6500n"}
    for args in (
        {"part": invented, "place": snap("mount", "plate-1", "top")},
        {"part": "thruster-6500n", "place": snap("mount", "plate-1", "top"), "material": [OWN_MATERIAL.id]},
    ):
        assert_refused_everywhere(tools, desk, "add_part", args, monkeypatch)
    # by id only: an id that is neither the project's nor the library's is unknown, and nothing is made up for it
    r = tools.run(desk, "add_part", {"part": "thruster-6500n", "place": snap("mount", "plate-1", "top")})
    assert codes(r) == [ReasonCode.UNKNOWN_ID] and r.reasons[0].ids[0].id == "thruster-6500n"
    assert load_library() == tools._library


# --- 5. the agent cannot speak for the user ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        {"part": "thruster-declared-8kn", "place": snap("mount", "plate-1", "top"), "origin": "mouse"},
        {"part": "thruster-declared-8kn", "place": snap("mount", "plate-1", "top"), "confirmed": True},
        {"part": "thruster-declared-8kn", "place": snap("mount", "plate-1", "top"), "userConfirmation": "yes"},
        {"part": "beam", "place": {**snap("bottom", "plate-1", "top"), "joint": {"kind": "fixed", "break_threshold": 50, "badge": "cite"}}},
    ],
)
def test_guard_bypass_5_a_call_cannot_say_who_sent_it_its_badge_or_that_the_user_confirmed(tools, desk, monkeypatch, args):
    r = assert_refused_everywhere(tools, desk, "add_part", args, monkeypatch)
    assert "the user confirms out-of-catalog values" in r.reasons[0].message


def test_guard_bypass_5_an_out_of_catalog_call_waits_for_the_user_not_the_agent(tools, desk):
    hub, doc = hub_of(desk)
    agent = HubEditTools(hub, "desk", tools=tools)
    args = {"part": "thruster-declared-8kn", "place": snap("mount", "plate-1", "top")}
    pending = agent.call("add_part", args)
    assert not pending.ok and pending.needs_confirmation and pending.out_of_catalog and doc.revision == 0
    assert pending.to_json()["needs_confirmation"] is True and "카탈로그 밖 · 사용자 선언" in pending.summary
    # a confirmation of other findings (another instance) does not carry over
    other = tools.run(desk, "add_part", {**args, "instance_id": "other-1"}).out_of_catalog
    assert other and not set(other) & set(pending.out_of_catalog)
    assert agent.call("add_part", args, confirmed=other).needs_confirmation and doc.revision == 0
    done = agent.call("add_part", args, confirmed=pending.out_of_catalog)
    assert done.ok and done.revision == 1 and doc.history.entries[0].origin is Origin.AGENT
    assert done.out_of_catalog == pending.out_of_catalog and doc.project == done.project


# --- out of the catalog: labelled with the labels that exist ---------------------------------------------------------


def test_guard_a_declared_8kn_thruster_is_labelled_with_the_b03c_catalog_finding(tools, desk):
    r = tools.run(desk, "add_part", {"part": "thruster-declared-8kn", "place": snap("mount", "plate-1", "top")})
    assert r.ok and r.project is not None
    (thrust,) = [f for f in r.out_of_catalog if f.kind == "thrust"]
    assert thrust.label == catalog_finding(DECLARED_8KN).label == "카탈로그 밖 · 사용자 선언"
    assert (thrust.instance, thrust.definition, thrust.field) == ("thruster-declared-8kn-1", "thruster-declared-8kn", "rated_thrust")
    assert "8000 N" in thrust.message and "0.01..8.89644" in thrust.message
    # the part is not in the library: its other specs are outside it too, each with its own badge
    assert {(f.field, f.label) for f in r.out_of_catalog if f.kind == "spec"} == {
        (s.name, "카탈로그 밖 · 사용자 선언") for s in DECLARED_8KN.specs if s.name != "rated_thrust"
    }
    j = r.to_json()["out_of_catalog"]
    assert {x["label"] for x in j} == {"카탈로그 밖 · 사용자 선언"} and len(j) == len(r.out_of_catalog)


def test_guard_a_library_part_and_a_catalog_material_need_no_confirmation(tools, desk):
    hub, doc = hub_of(desk)
    r = HubEditTools(hub, "desk", tools=tools).call("add_part", {"part": "thruster-vacco-48003040", "place": snap("mount", "plate-1", "top")})
    assert r.ok and r.revision == 1 and r.out_of_catalog == () and "out_of_catalog" not in r.to_json()
    assert catalog_finding(load_library()["thruster-vacco-48003040"]).in_catalog


def test_guard_the_users_own_material_is_labelled_per_property_with_its_badge(tools, desk):
    r = tools.run(desk, "set_material", {"instance": "plate-1", "material": OWN_MATERIAL.id})
    assert r.ok and {(f.kind, f.definition) for f in r.out_of_catalog} == {("material", "example-material")}
    assert {f.field: f.label for f in r.out_of_catalog} == {
        "density": "카탈로그 밖 · 사용자 선언",
        "yield_strength": "카탈로그 밖 · 사용자 선언",
        "elastic_modulus": "카탈로그 밖 · 사용자 선언",
        "friction": "카탈로그 밖 · 기본값",
    }
    assert tools.run(desk, "set_material", {"instance": "plate-1", "material": "steel-a36"}).out_of_catalog == ()


def test_guard_a_definition_that_differs_from_the_library_has_the_c06_label(tools):
    plate = load_library()["plate"]
    mine = plate.model_copy(update={"name": "plate, my edit"})
    p = apply_command(empty(), AddPartDef(type="add_part_def", part=mine)).project
    r = tools.run(p, "add_part", {"part": "plate", "place": GROUND})
    assert r.ok
    (f,) = r.out_of_catalog
    assert (f.kind, f.definition, f.label) == ("differs", "plate", "카탈로그와 다름") and f.message.startswith("카탈로그와 다름: part 'plate'")


def test_guard_findings_are_per_instance_and_a_call_reports_only_what_it_introduces(tools, desk):
    one = tools.run(desk, "add_part", {"part": "thruster-declared-8kn", "place": snap("mount", "plate-1", "top")})
    assert one.out_of_catalog and out_of_catalog(one.project, load_library()) == frozenset(one.out_of_catalog)
    # a change elsewhere introduces nothing; the project's findings stay
    moved = tools.run(one.project, "set_material", {"instance": "plate-1", "material": "steel-a36"})
    assert moved.ok and moved.out_of_catalog == ()
    # a second instance of the same part introduces its own findings
    p = tools.run(one.project, "add_part", {"part": "plate", "place": {"type": "on_ground", "x": 1.0}}).project
    two = tools.run(p, "add_part", {"part": "thruster-declared-8kn", "place": snap("mount", "plate-2", "top")})
    assert two.ok and {f.instance for f in two.out_of_catalog} == {"thruster-declared-8kn-2"}
    assert {f.field for f in two.out_of_catalog} == {f.field for f in one.out_of_catalog}
    # removing it introduces nothing
    gone = tools.run(one.project, "remove_part", {"instance": "thruster-declared-8kn-1"})
    assert gone.ok and gone.out_of_catalog == () and out_of_catalog(gone.project, load_library()) == frozenset()


def test_guard_a_value_outside_a_parts_range_is_refused_not_labelled(tools, desk):
    r = tools.run(desk, "set_parameter", {"instance": "plate-1", "name": "length", "value": 1e6})
    assert not r.ok and r.out_of_catalog == () and r.reasons


# --- a confirmation is of these exact numbers ------------------------------------------------------------------------


def test_guard_a_finding_has_a_stable_id_bound_to_the_definition(tools, desk):
    args = {"instance": "plate-1", "material": OWN_MATERIAL.id}
    a, b = tools.run(desk, "set_material", args), tools.run(desk, "set_material", args)
    assert [f.id for f in a.out_of_catalog] == [f.id for f in b.out_of_catalog]
    assert len({f.id for f in a.out_of_catalog}) == len(a.out_of_catalog) == 4
    assert [x["id"] for x in a.to_json()["out_of_catalog"]] == [f.id for f in a.out_of_catalog]


def test_guard_a_value_changed_after_the_confirmation_needs_a_new_one(tools, desk):
    """The user confirms the own material's numbers; then (in another client) its density changes. The old confirmation
    is of the old numbers: the same call waits again, and the new findings are published only once they are confirmed."""
    hub, doc = hub_of(desk)
    agent = HubEditTools(hub, "desk", tools=tools)
    args = {"instance": "plate-1", "material": OWN_MATERIAL.id}
    seen = agent.call("add_part", {"part": "plate", "place": {"type": "on_ground", "x": 1.0}})  # unrelated, published
    assert seen.ok and doc.revision == 1
    pending = agent.call("set_material", args)
    assert pending.needs_confirmation and doc.revision == 1
    heavier = OWN_MATERIAL.model_copy(update={"density": OWN_MATERIAL.density.model_copy(update={"value": 7800.0})})
    edit = Publish(type="publish", id="user-edit", base_revision=doc.revision, command=ReplaceMaterialDef(type="replace_material_def", material=heavier), origin=Origin.MOUSE)
    assert hub.publish("desk", edit).reply.type == "accepted" and doc.revision == 2
    again = agent.call("set_material", args, confirmed=pending.out_of_catalog)
    assert again.needs_confirmation and doc.revision == 2
    assert not {f.id for f in again.out_of_catalog} & {f.id for f in pending.out_of_catalog}
    assert any("7800" in f.message for f in again.out_of_catalog)
    # confirming by id (what a UI sends back) works the same way
    done = agent.call("set_material", args, confirmed=[f.id for f in again.out_of_catalog])
    assert done.ok and doc.revision == 3


# --- input the guard cannot be made to choke on ----------------------------------------------------------------------


def test_guard_100k_levels_of_nesting_are_refused_never_raised(tools, desk):
    from kinetra_engine.agent.guard import MAX_ARGUMENT_DEPTH

    deep: dict = {}
    node = deep
    for _ in range(100_000):
        node["a"] = {}
        node = node["a"]
    text = '{"part": ' + "[" * 100_000 + "]" * 100_000 + "}"
    for arguments in (deep, text, {"part": "plate", "place": GROUND, "meta": deep}):
        r = tools.run(desk, "add_part", arguments)
        assert not r.ok and codes(r) == [ReasonCode.INVALID_COMMAND] and f"{MAX_ARGUMENT_DEPTH} levels" in r.reasons[0].message
    hub, doc = hub_of(desk)
    assert not HubEditTools(hub, "desk", tools=tools).call("add_part", text).ok and doc.revision == 0
    # the text scan is the same bound on every platform, and brackets inside strings are not nesting
    from kinetra_engine.agent.guard import json_too_deep

    assert json_too_deep("[" * (MAX_ARGUMENT_DEPTH + 1) + "]" * (MAX_ARGUMENT_DEPTH + 1))
    assert not json_too_deep("[" * MAX_ARGUMENT_DEPTH + "]" * MAX_ARGUMENT_DEPTH)
    quoted = json.dumps({"part": "plate", "place": {"type": "on_ground", "x": 1.0}, "source": "[{" * 100 + ' "quoted"'})
    assert not json_too_deep(quoted) and tools.run(desk, "add_part", quoted).ok
    # just past the bound, a forbidden key above it is still named, and nothing below it is read
    nested = {"gravity": 1, "x": {}}
    node = nested["x"]
    for _ in range(MAX_ARGUMENT_DEPTH):
        node["x"] = {}
        node = node["x"]
    assert {x.code for x in guard_arguments("add_part", nested)} == {ReasonCode.FORBIDDEN, ReasonCode.INVALID_COMMAND}


# --- the guard does not trip on what the tools are -------------------------------------------------------------------


def test_guard_no_tool_field_or_library_parameter_trips_the_guard():
    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    yield from value
                yield from keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    fields = set(keys(specs())) - {"part", "material"}  # these two are ids: refused only as an object or a list
    assert not guard_arguments("t", {k: 0 for k in fields})
    assert not guard_arguments("t", {"part": "plate", "material": "steel-a36", "material_id": None})
    params = {p.name for part in load_library().values() for p in part.parameters}
    assert params and not guard_arguments("t", {"parameters": {name: 0.1 for name in params}})
