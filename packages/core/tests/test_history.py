"""C-02b: undo, redo and the history. The fixture is the committed four-wheel-car example (declared values, not
real part data) on the example World and assumption table."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from kinetra_core import (
    Command,
    CommandBatch,
    CommandRejected,
    EditResult,
    History,
    HistoryEntry,
    Origin,
    Pose,
    Project,
    ReasonCode,
    apply_command,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"
SRC = {"ref": "unit-test fixture", "locator": "test_history.py"}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def car():
    return {
        "design": load("DesignSpec.four-wheel-car.json"),
        "world": load("World.ramp-and-step.json"),
        "assumptions": load("AssumptionTable.vehicle-mass.json"),
    }


@pytest.fixture
def project():
    """The car's parts without their joints: the history tests move single instances, and the validator (C-02c,
    which `History.execute` goes through) refuses to tear a joined pair apart."""
    data = car()
    data["design"] = {**data["design"], "joints": [], "actuators": [], "schedule": {"entries": []}}
    return Project.model_validate(data)


@pytest.fixture
def jointed_car():
    return Project.model_validate(car())


def cmd(**d):
    return TypeAdapter(Command).validate_python(d)


def pose(x=0.0, y=0.0, z=0.0):
    return {"position": {"x": x, "y": y, "z": z}, "orientation": IDENTITY, "badge": "declared", "source": SRC}


def move(id, x):
    return cmd(type="move_instance", id=id, pose=pose(x, 0.0, 0.05))


def pose_of(project, id):
    return next(i for i in project.design.instances if i.id == id).pose


def batch(*commands):
    return CommandBatch(type="batch", commands=tuple(commands))


def test_command_epic_add_move_join_then_three_undos_restore_the_original_project(project):
    """C-02 integration: a consumer uses only History.execute/undo; every new edit goes through validate_command."""
    spare = next(i for i in project.design.instances if i.id == "wheel-fl").model_dump(mode="json")
    spare.update(id="spare", pose=pose(1.0, 2.0, 0.05))
    axle_pose = pose_of(project, "wheel-fl").model_dump(mode="json")
    joint = {
        "id": "spare-hub",
        "kind": "hinge",
        "a": {"instance": "chassis-1", "snap_point": "axle-fl"},
        "b": {"instance": "spare", "snap_point": "hub"},
    }
    steps = [
        (cmd(type="add_instance", instance=spare), Origin.MOUSE),
        (cmd(type="move_instance", id="spare", pose=axle_pose), Origin.AGENT),
        (cmd(type="add_joint", joint=joint), Origin.XR),
    ]

    current = EditResult(project=project, history=History(), entry=None)
    for command, origin in steps:
        current = current.history.execute(current.project, command, origin)
        assert current.entry is not None
    assert [entry.command for entry in current.history.entries] == [command for command, _ in steps]
    assert current.project.design.joints[-1].id == "spare-hub"

    without_joint = current.history.undo(current.project)
    assert without_joint.project.design.joints == ()
    before_move = without_joint.history.undo(without_joint.project)
    assert pose_of(before_move.project, "spare") == Pose.model_validate(spare["pose"])
    restored = before_move.history.undo(before_move.project)

    assert restored.project == project
    assert restored.history.entries == current.history.entries
    assert restored.history.cursor == 0
    assert not restored.history.can_undo and restored.history.can_redo


def forbidden_rejection_log(project):
    """Emit the reproducible C-02 rejection log while asserting one policy for all five consumer origins."""
    forbidden = cmd(
        type="add_assumption",
        assumption={
            "key": "gravity",
            "label": "Gravity",
            "value": {"value": 1.62, "unit": "m/s^2", "badge": "declared", "source": SRC},
            "confidence": "low",
            "editable": True,
        },
    )
    expected = None
    records = []
    for origin in Origin:
        with pytest.raises(CommandRejected) as caught:
            History().execute(project, forbidden, origin)
        error = caught.value
        assert error.reasons[0].code is ReasonCode.FORBIDDEN
        assert expected is None or error.reasons == expected
        expected = error.reasons
        record = {
            "origin": origin.value,
            "command": forbidden.type,
            "reasons": [reason.model_dump(mode="json") for reason in error.reasons],
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    assert len(records) == len(Origin) == 5
    return records


def test_command_epic_forbidden_command_rejection_log_is_the_same_for_every_origin(project):
    forbidden_rejection_log(project)


def test_history_starts_empty():
    h = History()
    assert (h.entries, h.cursor, h.can_undo, h.can_redo) == ((), 0, False, False)


def test_history_execute_records_command_inverse_and_origin(project):
    command = move("wheel-fl", 0.2)
    r = History().execute(project, command, Origin.XR)
    assert pose_of(r.project, "wheel-fl") != pose_of(project, "wheel-fl")
    assert r.entry == HistoryEntry(origin=Origin.XR, command=command, inverse=apply_command(project, command).inverse)
    assert r.history.entries == (r.entry,) and r.history.cursor == 1
    assert r.history.can_undo and not r.history.can_redo


def test_history_undo_then_redo_restores_exactly(project):
    h0 = History()
    a = h0.execute(project, move("wheel-fl", 0.2), Origin.MOUSE)
    undone = a.history.undo(a.project)
    assert undone.project == project
    assert undone.entry == a.entry
    assert undone.history.can_redo and not undone.history.can_undo
    redone = undone.history.redo(undone.project)
    assert redone.project == a.project
    assert redone.history == a.history


def test_history_batch_is_one_entry_and_undone_whole(project):
    """The DoD test: a batch of several edits (two moves, a planet change, an assumption removal) is one history
    step: one undo takes all of it back, one redo does all of it again."""
    group = batch(
        move("wheel-fl", 0.2),
        move("wheel-fr", 0.3),
        cmd(type="select_planet", planet="moon"),
        cmd(type="remove_assumption", key="vehicle_mass"),
    )
    a = History().execute(project, group, Origin.AGENT)
    assert len(a.history.entries) == 1
    assert a.project != project
    assert a.project.world.planet == "moon"

    undone = a.history.undo(a.project)
    assert undone.project == project
    assert undone.history.cursor == 0 and len(undone.history.entries) == 1

    redone = undone.history.redo(undone.project)
    assert redone.project == a.project
    assert redone.history.cursor == 1


def test_history_batch_undo_is_one_step_among_single_edits(project):
    h = History()
    p = project
    steps = [
        (move("wheel-rl", 0.1), Origin.MOUSE),
        (batch(move("wheel-fl", 0.2), move("wheel-fr", 0.3)), Origin.XR),
        (cmd(type="select_planet", planet="moon"), Origin.VOICE),
    ]
    states = [p]
    for command, origin in steps:
        r = h.execute(p, command, origin)
        h, p = r.history, r.project
        states.append(p)
    assert len(h.entries) == 3
    for expected in reversed(states[:-1]):
        r = h.undo(p)
        h, p = r.history, r.project
        assert p == expected
    assert not h.can_undo
    for expected in states[1:]:
        r = h.redo(p)
        h, p = r.history, r.project
        assert p == expected
    assert not h.can_redo


def test_history_keeps_the_origin_of_every_entry_and_replay_keeps_it(project):
    h, p = History(), project
    for command, origin in [
        (move("wheel-fl", 0.1), Origin.MOUSE),
        (move("wheel-fl", 0.2), Origin.AGENT),
        (move("wheel-fl", 0.3), Origin.VOICE),
        (move("wheel-fl", 0.4), Origin.XR),
        (move("wheel-fl", 0.5), Origin.MCP),
    ]:
        r = h.execute(p, command, origin)
        h, p = r.history, r.project
    assert [e.origin for e in h.entries] == [Origin.MOUSE, Origin.AGENT, Origin.VOICE, Origin.XR, Origin.MCP]
    assert {o.value for o in Origin} == {"mouse", "agent", "voice", "xr", "mcp"}
    r = h.undo(p)
    assert r.entry.origin is Origin.MCP
    r = r.history.redo(r.project)
    assert r.entry.origin is Origin.MCP
    assert [e.origin for e in r.history.entries] == [e.origin for e in h.entries]


def test_history_origin_is_not_part_of_the_command(project):
    """The same command from two origins is the same edit: same project, same inverse. Only the record differs."""
    command = move("wheel-fl", 0.2)
    a = History().execute(project, command, Origin.MOUSE)
    b = History().execute(project, command, Origin.MCP)
    assert a.project == b.project
    assert a.entry.command == b.entry.command and a.entry.inverse == b.entry.inverse
    assert a.entry.origin != b.entry.origin
    assert "origin" not in command.model_dump()


def test_history_unknown_origin_is_rejected(project):
    with pytest.raises(ValidationError):
        HistoryEntry(origin="telepathy", command=move("wheel-fl", 0.2), inverse=move("wheel-fl", 0.0))
    with pytest.raises(ValueError):
        Origin("telepathy")


def test_history_new_edit_after_undo_cuts_the_redo_tail(project):
    a = History().execute(project, move("wheel-fl", 0.2), Origin.MOUSE)
    b = a.history.execute(a.project, move("wheel-fr", 0.3), Origin.MOUSE)
    u = b.history.undo(b.project)
    assert u.history.can_redo
    c = u.history.execute(u.project, cmd(type="select_planet", planet="moon"), Origin.VOICE)
    assert not c.history.can_redo
    assert [e.command.type for e in c.history.entries] == ["move_instance", "select_planet"]
    assert c.history.cursor == 2
    with pytest.raises(CommandRejected) as e:
        c.history.redo(c.project)
    assert e.value.reasons[0].code is ReasonCode.NOTHING_TO_REDO


def test_history_nothing_to_undo_or_redo_is_a_rejection_with_a_reason(project):
    with pytest.raises(CommandRejected) as e:
        History().undo(project)
    assert e.value.reasons[0].code is ReasonCode.NOTHING_TO_UNDO
    with pytest.raises(CommandRejected) as e:
        History().redo(project)
    assert e.value.reasons[0].code is ReasonCode.NOTHING_TO_REDO


def test_history_a_command_that_changes_nothing_leaves_no_entry(project):
    a = History().execute(project, move("wheel-fl", 0.2), Origin.MOUSE)
    undone = a.history.undo(a.project)  # redo tail is there
    same_planet = cmd(type="select_planet", planet=project.world.planet)
    same_pose = cmd(type="move_instance", id="wheel-fl", pose=pose_of(project, "wheel-fl").model_dump(mode="json"))
    there_and_back = batch(move("wheel-fr", 0.4), cmd(type="move_instance", id="wheel-fr", pose=pose_of(project, "wheel-fr").model_dump(mode="json")))
    for noop in (same_planet, same_pose, there_and_back):
        r = undone.history.execute(undone.project, noop, Origin.AGENT)
        assert r.entry is None
        assert r.project == undone.project
        assert r.history == undone.history  # nothing recorded, redo tail kept
        assert r.history.can_redo


def test_history_rejected_command_changes_nothing(project):
    a = History().execute(project, move("wheel-fl", 0.2), Origin.MOUSE)
    bad = batch(move("wheel-fr", 0.3), cmd(type="remove_instance", id="no-such-instance"))
    with pytest.raises(CommandRejected) as e:
        a.history.execute(a.project, bad, Origin.AGENT)
    assert e.value.reasons[0].code is ReasonCode.UNKNOWN_ID
    # the inputs are values: they are what they were
    assert a.history.cursor == 1 and len(a.history.entries) == 1
    assert pose_of(a.project, "wheel-fr") == pose_of(project, "wheel-fr")


def test_history_execute_undo_redo_do_not_mutate_their_inputs(project):
    h = History()
    a = h.execute(project, move("wheel-fl", 0.2), Origin.MOUSE)
    assert h == History() and a.history is not h
    before = (a.project, a.history)
    a.history.undo(a.project)
    assert (a.project, a.history) == before
    u = a.history.undo(a.project)
    before = (u.project, u.history)
    u.history.redo(u.project)
    assert (u.project, u.history) == before


def test_history_cascading_removal_is_one_step(jointed_car):
    """`remove_instance` takes joints, actuators and schedule entries with it (C-02a): still one history step."""
    r = History().execute(jointed_car, cmd(type="remove_instance", id="motor-l"), Origin.XR)
    assert len(r.history.entries) == 1
    assert len(r.project.design.joints) < len(jointed_car.design.joints)
    u = r.history.undo(r.project)
    assert u.project == jointed_car


def test_history_cursor_must_be_inside_the_entries():
    with pytest.raises(ValidationError):
        History(entries=(), cursor=1)
    with pytest.raises(ValidationError):
        History(entries=(), cursor=-1)


def test_history_value_round_trips_through_json(project):
    a = History().execute(project, batch(move("wheel-fl", 0.2), move("wheel-fr", 0.3)), Origin.MCP)
    u = a.history.undo(a.project)
    again = History.model_validate_json(u.history.model_dump_json())
    assert again == u.history
    assert again.redo(u.project).project == a.project
    assert isinstance(a, EditResult)
