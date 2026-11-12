"""G-02b: the agent's query tools read the project in numbers, and every number is what the core computes.

Each query is compared with the core function it reads (`assembly_mass`, `mass_properties`, `compile_thrust`, `tipover`, the
run stream of `PreviewRun`) and, where the fixture has one, with the hand calculation its own test already makes (the cart
and the overhang of `test_tipover.py`, the rocket's dry and tank masses of `test_thrust.py`). Fixtures are those tests'
(values declared by the tests, `사용자 선언`).
"""

from __future__ import annotations

import json
import math

import pytest
from test_body_tree import RHO, box, instance, joint, part, project, snap
from test_simulate_stream import run_of, split, tower
from test_thrust import CAPACITY, M_TANK, M_THRUSTER, TANK_ON_JET_Z, rocket
from test_tipover import WHEEL_R, WHEEL_W, cart

from kinetra_core import PLANET_CONSTANT_NAMES, Project, project_hash
from kinetra_core.bodies import load_body
from kinetra_core.validator import VERDICT_FIELD_NAMES
from kinetra_engine.agent import (
    QUERY_TOOL_NAMES,
    ROLLOUT_NOTICE,
    STATICS_LABEL,
    TOOL_NAMES,
    HubEditTools,
    HubQueryTools,
    QueryTools,
    query_specs,
    summarize_rollout,
)
from kinetra_engine.compiler import build_body_tree, compile_thrust
from kinetra_engine.parts import assembly_mass, mass_properties, tank_supply
from kinetra_engine.protocol import Hub
from kinetra_engine.statics import tipover


def ask(project, tool, args=None, tools=None):
    result = (tools or QueryTools()).run(project, tool, json.dumps(args or {}))
    assert result.ok, result.reasons
    return result.data


def refused(project, tool, args, tools=None):
    result = (tools or QueryTools()).run(project, tool, args)
    assert not result.ok and result.data is None
    return [r.code.value for r in result.reasons], result


def xyz(d):
    return (d["x"], d["y"], d["z"])


# --- the tools ---------------------------------------------------------------------------------------------------------


def test_query_tools_specs_are_function_tools_with_no_field_to_set_anything():
    specs = query_specs()
    assert tuple(s["function"]["name"] for s in specs) == QUERY_TOOL_NAMES == ("list_parts", "mass_properties", "statics_check", "rollout_summary")
    assert not set(QUERY_TOOL_NAMES) & set(TOOL_NAMES)  # read tools are not edit tools
    names = set()
    for s in specs:
        assert s["type"] == "function" and s["function"]["parameters"]["type"] == "object"
        assert s["function"]["parameters"]["additionalProperties"] is False
        names |= set(s["function"]["parameters"].get("properties", {}))
    assert names == {"run_id"}  # the one argument any query takes; nothing that could carry a value to write
    assert not (set(PLANET_CONSTANT_NAMES) | set(VERDICT_FIELD_NAMES)) & names


# --- parts list ----------------------------------------------------------------------------------------------------------


def test_query_tools_list_parts_is_the_project_as_it_holds_it():
    proj = cart()
    data = ask(proj, "list_parts")
    design = proj.design
    parts = {p.id: p for p in design.parts}
    assert [i["id"] for i in data["instances"]] == [i.id for i in design.instances]
    for row, inst in zip(data["instances"], design.instances, strict=True):
        assert row["part"] == inst.part and row["material"] == inst.material
        assert row["snap_points"] == [s.id for s in parts[inst.part].snap_points]
        assert xyz(row["pose"]["position"]) == (inst.pose.position.x, inst.pose.position.y, inst.pose.position.z)
        assert row["pose"]["badge"] == inst.pose.badge.value
        assert "missing_definition" not in row
    assert [(j["id"], j["kind"], j["a"]["instance"], j["b"]["snap_point"]) for j in data["joints"]] == [
        (j.id, j.kind.value, j.a.instance, j.b.snap_point) for j in design.joints
    ]
    assert data["planet"] == "earth" and data["actuators"] == [] and data["schedule"] == []


def test_query_tools_list_parts_carries_actuators_schedule_and_parameters_with_their_badges():
    entries = [{"type": "actuate", "id": "burn", "actuator": "main", "start": 0.5, "end": 2.0, "command": 0.25, "badge": "declared",
                "source": {"ref": "G-02b test fixture"}}]
    proj = rocket(entries, tank_params=[("initial_fill", 0.5, "1")])
    data = ask(proj, "list_parts")
    assert data["actuators"] == [{"id": "main", "kind": "thruster", "instance": "jet", "joint": None, "supply": "tank"}]
    assert data["schedule"] == [{"id": "burn", "actuator": "main", "start_s": 0.5, "end_s": 2.0, "command": 0.25, "badge": "declared"}]
    tank = next(i for i in data["instances"] if i["id"] == "tank")
    assert tank["role"] == "tank" and tank["parameters"] == [{"name": "initial_fill", "value": 0.5, "unit": "1", "badge": "declared"}]


def test_query_tools_list_parts_names_a_placeholder_and_invents_nothing_for_it():
    data = rocket([]).model_dump(mode="json")
    data["design"]["parts"] = [p for p in data["design"]["parts"] if p["id"] != "thruster-vacco-48003040"]
    proj = Project.model_validate(data)
    jet = next(i for i in ask(proj, "list_parts")["instances"] if i["id"] == "jet")
    assert jet["missing_definition"] == ["part"] and jet["snap_points"] == [] and jet["part_name"] is None
    codes, _ = refused(proj, "mass_properties", "{}")  # a mass needs the part: C-06's reason, nothing made up
    assert codes == ["missing_definition"]


# --- mass and centre of mass ---------------------------------------------------------------------------------------------


def test_query_tools_mass_and_centre_of_mass_match_the_core_and_the_hand_sum():
    proj = cart()
    data = ask(proj, "mass_properties")
    core = assembly_mass(proj.design)
    assert data["dry"]["mass_kg"] == pytest.approx(core.total.value, rel=1e-15)
    t = tipover(build_body_tree(proj))
    assert xyz(data["dry"]["center_of_mass_m"]) == pytest.approx(t.center_of_mass, rel=1e-12, abs=1e-15)
    # the hand sum of test_tipover: chassis 60 kg at z 0.25, payload 8 kg at (0.3, 0.2, 0.4), four wheels at z 0.15
    m_chassis, m_payload, m_wheel = 1.0 * 0.6 * 0.1 * RHO, 0.2**3 * RHO, math.pi * WHEEL_R**2 * WHEEL_W * RHO
    total = m_chassis + m_payload + 4 * m_wheel
    com = (m_payload * 0.3 / total, m_payload * 0.2 / total, (m_chassis * 0.25 + m_payload * 0.4 + 4 * m_wheel * 0.15) / total)
    assert data["dry"]["mass_kg"] == pytest.approx(total, rel=1e-12)
    assert xyz(data["dry"]["center_of_mass_m"]) == pytest.approx(com, rel=1e-12)
    parts, materials = {p.id: p for p in proj.design.parts}, {m.id: m for m in proj.design.materials}
    for row, inst in zip(data["instances"], proj.design.instances, strict=True):
        own = mass_properties(parts[inst.part], materials[inst.material], {})
        assert row["instance"] == inst.id and row["mass_kg"] == own.mass.value
        assert row["input_badges"] == [b.value for b in own.derivation.input_badges]
    assert next(r for r in data["instances"] if r["instance"] == "payload")["center_of_mass_m"] == pytest.approx({"x": 0.3, "y": 0.2, "z": 0.4})
    assert data["badge"] == "sim" and data["input_badges"] == ["declared"]
    assert data["propellant"] == [] and data["with_propellant"] == data["dry"]


def test_query_tools_mass_with_propellant_is_the_tank_supply_on_the_dry_design():
    proj = rocket([])
    data = ask(proj, "mass_properties")
    tank = next(p for p in proj.design.parts if p.id == "tank")
    supply = tank_supply(tank)
    assert data["propellant"] == [{"tank": "tank", "body": "jet", "mass_kg": supply.remaining, "capacity_kg": supply.capacity.value,
                                   "input_badges": [b.value for b in supply.input_badges]}]
    assert supply.remaining == pytest.approx(CAPACITY, rel=1e-12)
    assert data["dry"]["mass_kg"] == pytest.approx(M_TANK + M_THRUSTER, rel=1e-12)  # test_thrust's hand masses
    assert data["with_propellant"]["mass_kg"] == pytest.approx(M_TANK + M_THRUSTER + CAPACITY, rel=1e-12)
    model = compile_thrust(proj)
    assert data["with_propellant"]["mass_kg"] == model.mass_of("jet", {"tank": supply.remaining})[0]
    # the propellant sits at the tank's inside centre, the tank origin (0, 0, TANK_ON_JET_Z): a weighted sum with the dry centre
    dry, wet = data["dry"], data["with_propellant"]
    hand_z = (dry["mass_kg"] * dry["center_of_mass_m"]["z"] + CAPACITY * TANK_ON_JET_Z) / wet["mass_kg"]
    assert xyz(wet["center_of_mass_m"]) == pytest.approx((0.0, 0.0, hand_z), rel=1e-12, abs=1e-12)


# --- static check ----------------------------------------------------------------------------------------------------------


def test_query_tools_statics_check_is_x03a_tipover():
    proj = cart()
    data = ask(proj, "statics_check")
    t = tipover(build_body_tree(proj))
    assert data["label"] == STATICS_LABEL
    # the badges of what the check was computed from (X-07's rows): the test's declared shapes, density and poses, the cited gravity
    assert data["inputs"] == [{"input": "mass", "badges": ["declared"]}, {"input": "pose", "badges": ["declared"]}, {"input": "gravity", "badges": ["cite"]}]
    assert load_body("earth").gravity.badge.value == "cite"
    assert data["badge"] == "declared"  # the weakest input, never `sim` over declared inputs
    assert data["support"] == t.kind == "polygon" and data["stable"] is t.stable is True
    assert data["margin_m"] == t.margin and data["tipover_angle_rad"] == t.tipover_angle
    assert data["tipover_angle_deg"] == math.degrees(t.tipover_angle)
    assert data["com_height_m"] == t.com_height and xyz(data["center_of_mass_m"]) == t.center_of_mass
    assert [(p["instance"], p["geom"], xyz(p)) for p in data["polygon"]] == [(s.instance, s.geom, s.point) for s in t.polygon]
    assert [(e["distance_m"], e["angle_rad"]) for e in data["edges"]] == [(e.distance, e.angle) for e in t.edges]
    assert data["support_points"] == len(t.contacts) and data["assumptions"] == list(t.assumptions)


def test_query_tools_statics_check_input_badges_follow_the_inputs():
    # a library tank in the catalog's aluminium and a thruster in its steel: the inputs' own badges, not the test's
    proj = rocket([])
    data = ask(proj, "statics_check")
    tree = compile_thrust(proj).tree
    mass = {b.value for ci in tree.instances for b in ci.properties.derivation.input_badges}
    rows = {r["input"]: r["badges"] for r in data["inputs"]}
    assert set(rows["mass"]) == mass and rows["pose"] == ["declared"] and rows["gravity"] == [load_body("earth").gravity.badge.value]
    strength = ["sim", "cite", "default", "declared", "estimate"]  # X-07's BADGE_STRENGTH
    assert data["badge"] == max((b for bs in rows.values() for b in bs), key=strength.index)


def test_query_tools_statics_check_reports_an_overhang_as_not_stable():
    # test_tipover's overhang: centre of mass (0.18, 0, 0.11), 0.08 m beyond the base edge x = 0.1
    parts = [part("base", [box("b", 0.2, 0.2, 0.1)], [snap("top", (0, 0, 0.05))]), part("arm", [box("a", 0.6, 0.1, 0.1)], [snap("s1", (-0.3, 0, -0.05))])]
    proj = project(parts, [instance("base", "base", (0, 0, 0.05)), instance("arm", "arm", (0.3, 0, 0.15))], [joint("weld", "fixed", ("base", "top"), ("arm", "s1"))])
    data = ask(proj, "statics_check")
    assert data["stable"] is False
    assert data["margin_m"] == pytest.approx(-0.08, rel=1e-9) and data["tipover_angle_rad"] == pytest.approx(math.atan2(-0.08, 0.11), rel=1e-9)


def test_query_tools_a_design_that_does_not_compile_or_is_in_the_ground_is_refused_with_the_cores_reason():
    floating = project([part("blk", [box("b", 0.1, 0.1, 0.1)])], [instance("i", "blk", (0, 0, 1.0))])
    for tool in ("mass_properties", "statics_check"):
        codes, result = refused(floating, tool, "{}")
        assert codes == ["floating"] and result.reasons[0].message.startswith("floating: ")
        assert [(r.kind.value, r.id) for r in result.reasons[0].ids] == [("instance", "i"), ("part", "blk")]
    buried = project([part("blk", [box("b", 0.1, 0.1, 0.1)])], [instance("i", "blk", (0, 0, 0.01))])
    codes, result = refused(buried, "statics_check", "{}")
    assert codes == ["overlap"] and [r.id for r in result.reasons[0].ids] == ["i"]
    assert ask(floating, "list_parts")["instances"][0]["id"] == "i"  # the list needs no compile


# --- rollout summary ---------------------------------------------------------------------------------------------------------


def test_query_tools_rollout_summary_is_the_run_stream():
    proj = tower()
    run = run_of(proj, duration_s=0.25)
    frames, ended = split(run)
    tools = QueryTools()
    recorded = tools.record(run.started, frames, ended)
    recorded["bodies"][0]["end_m"]["z"] = 99.0  # a caller changing what it was given cannot change the record
    data = ask(proj, "rollout_summary", {"run_id": "run-1"}, tools)
    data["bodies"].clear()
    data["model_labels"].append("changed")
    data = ask(proj, "rollout_summary", {"run_id": "run-1"}, tools)
    assert data["notice"] == ROLLOUT_NOTICE and data["badge"] == "sim" and data["kind"] == "preview"
    assert data["end"] == ended.end.reason == "completed" and data["last_tick"] == ended.last_tick
    assert data["trajectory_hash"] == ended.end.trajectory.hash
    assert data["frames"] == len(frames) and data["end_time_s"] == frames[-1].sim_time_s
    assert data["definition_hash"] == project_hash(proj) and data["current_design"] is True
    assert data["model_labels"] == list(run.started.model_labels)
    (body,) = data["bodies"]
    poses = [f.poses[0] for f in frames]
    first, last = poses[0].position, poses[-1].position
    assert xyz(body["start_m"]) == (first.x, first.y, first.z) and xyz(body["end_m"]) == (last.x, last.y, last.z)
    assert xyz(body["displacement_m"]) == (last.x - first.x, last.y - first.y, last.z - first.z)
    assert body["lowest_z_m"] == min(p.position.z for p in poses) and body["highest_z_m"] == max(p.position.z for p in poses)
    ticks = [f.tick for f in frames]
    assert body["lowest_at_tick"] == ticks[[p.position.z for p in poses].index(body["lowest_z_m"])]
    assert body["highest_at_tick"] == ticks[[p.position.z for p in poses].index(body["highest_z_m"])]
    assert body["horizontal_distance_m"] == math.hypot(last.x - first.x, last.y - first.y)
    assert data["events"] == {} and data["breaks"] == [] and data["conditions_met"] == []


def test_query_tools_rollout_tilt_is_the_angle_the_up_axis_turned():
    proj = tower()
    run = run_of(proj, duration_s=0.01)
    frames, ended = split(run)
    a = 0.4  # turn the last pose by 0.4 rad about x: the body has tipped 0.4 rad, whatever it was before
    q0 = frames[0].poses[0].orientation
    turn = (math.cos(a / 2), math.sin(a / 2), 0.0, 0.0)  # w, x, y, z
    w, x, y, z = turn[0] * q0.w - turn[1] * q0.x, turn[0] * q0.x + turn[1] * q0.w, turn[0] * q0.y - turn[1] * q0.z, turn[0] * q0.z + turn[1] * q0.y
    last = frames[-1].model_dump(mode="json")
    last["poses"][0]["orientation"] = {"x": x, "y": y, "z": z, "w": w}
    frames[-1] = type(frames[-1]).model_validate(last)
    body = summarize_rollout(run.started, frames, ended)["bodies"][0]
    assert body["end_tilt_deg"] == pytest.approx(math.degrees(a), rel=1e-9) and body["max_tilt_deg"] == body["end_tilt_deg"]


def test_query_tools_a_rollout_is_a_whole_stream_and_says_when_the_design_has_changed():
    proj = tower()
    run = run_of(proj, duration_s=0.25)
    frames, ended = split(run)
    with pytest.raises(ValueError):
        summarize_rollout(run.started, frames[:-1], ended)  # no end frame: not a whole run
    tools = QueryTools()
    codes, result = refused(proj, "rollout_summary", "{}", tools)
    assert codes == ["unknown_id"] and "no run has been recorded" in result.reasons[0].message
    tools.record(run.started, frames, ended)
    second = run_of(proj, duration_s=0.05, run_id="run-2")
    tools.record(second.started, *split(second))
    assert ask(proj, "rollout_summary", {}, tools)["run_id"] == "run-2"  # omitted: the newest
    codes, _ = refused(proj, "rollout_summary", {"run_id": "run-9"}, tools)
    assert codes == ["unknown_id"]
    moved = proj.model_dump(mode="json")
    moved["design"]["materials"][0]["density"]["value"] = 2000.0
    other = Project.model_validate(moved)
    result = tools.run(other, "rollout_summary", {"run_id": "run-1"})
    assert result.ok and result.data["current_design"] is False and "another version" in result.summary


# --- checks on the call, and nothing is written -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "code"),
    [
        ("list_part", "{}", "invalid_command"),
        ("list_parts", "not json", "invalid_command"),
        ("list_parts", "[]", "invalid_command"),
        ("list_parts", '{"instance": "chassis"}', "invalid_command"),
        ("rollout_summary", '{"run_id": 7}', "invalid_command"),
        ("rollout_summary", '{"run_id": "no spaces allowed"}', "invalid_command"),
        ("set_gravity", "{}", "forbidden"),
        ("write_verdict", "{}", "forbidden"),
        ("statics_check", '{"gravity": 1.62}', "forbidden"),
        ("mass_properties", '{"density": 1}', "forbidden"),
        ("list_parts", '{"p_success": 1}', "forbidden"),
    ],
)
def test_query_tools_a_bad_call_is_refused_like_an_edit_tool_call(tool, arguments, code):
    codes, _ = refused(cart(), tool, arguments)
    assert codes == [code]


def test_query_tools_on_a_hub_read_the_document_and_publish_nothing():
    hub = Hub({"desk": cart()})
    doc = hub.documents["desk"]
    before, revision = doc.project, doc.revision
    queries = HubQueryTools(hub, "desk")
    for tool in QUERY_TOOL_NAMES[:3]:
        assert queries.call(tool, {}).ok
    assert doc.revision == revision and doc.project == before
    # the next query reads the document as an edit left it
    edit = HubEditTools(hub, "desk").call("add_part", {"part": "plate", "material": "al6061-t6", "place": {"type": "on_ground", "x": 3.0, "y": 3.0}})
    assert edit.ok and doc.revision == revision + 1
    listed = queries.call("list_parts", {}).data["instances"]
    assert [i["id"] for i in listed] == [i.id for i in doc.project.design.instances] and "plate-1" in [i["id"] for i in listed]
    with pytest.raises(KeyError):
        HubQueryTools(hub, "nope")
