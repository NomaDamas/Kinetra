"""C-05a: the document subscription and command channel. `Document` (revision, history, verdict) is tested without a
network; the WebSocket tests open real connections on a free local port and play two clients against one core."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.client import connect

from kinetra_core import (
    PROTOCOL_VERSION,
    Applied,
    ClientMessage,
    Origin,
    Project,
    ProjectChanges,
    Publish,
    ReasonCode,
    Request,
    ServerMessage,
    Snapshot,
    VerdictState,
    apply_changes,
)
from kinetra_engine.protocol import Document, Hub

EXAMPLES = Path(__file__).resolve().parents[3] / "schemas" / "examples"
SERVER = TypeAdapter(ServerMessage)
CLIENT = TypeAdapter(ClientMessage)


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def project():
    return Project.model_validate(
        {
            "design": load("DesignSpec.four-wheel-car.json"),
            "world": load("World.ramp-and-step.json"),
            "assumptions": load("AssumptionTable.vehicle-mass.json"),
        }
    )


def pose(x=0.2):
    return {
        "position": {"x": x, "y": 0.1, "z": 0.05},
        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        "badge": "declared",
        "source": {"ref": "unit-test fixture", "declared_by": "test_protocol_document", "declared_at": "2026-11-12T00:00:00Z"},
    }


def move(ident="wheel-fl", x=0.2):
    return {"type": "move_instance", "id": ident, "pose": pose(x)}


def publish(cid, command, base=0, origin="mouse"):
    return Publish.model_validate({"type": "publish", "id": cid, "base_revision": base, "command": command, "origin": origin})


# --- Document: the rules of 3.1 and 3.2 without a transport ---------------------------------------------------


def test_protocol_document_publish_bumps_the_revision_and_names_what_changed(project):
    doc = Document("car", project)
    out = doc.publish(publish("c1", move(), origin="agent"))
    assert out.reply.type == "accepted" and out.reply.revision == 1 and doc.revision == 1
    a = out.applied
    assert (a.revision, a.id, a.cause, a.origin) == (1, "c1", "publish", Origin.AGENT)
    assert a.command.type == "move_instance"
    assert a.changes.instances is not None  # only the section that changed is carried
    assert all(getattr(a.changes, f) is None for f in ("materials", "parts", "joints", "actuators", "schedule", "world", "assumptions"))
    assert apply_changes(project, a.changes) == doc.project


def test_protocol_document_rejection_carries_reasons_and_changes_nothing(project):
    doc = Document("car", project)
    out = doc.publish(publish("c1", {"type": "remove_instance", "id": "nope"}))
    assert out.applied is None and out.reply.type == "rejected" and doc.revision == 0 and doc.project == project
    (reason,) = out.reply.reasons
    assert reason.code is ReasonCode.UNKNOWN_ID and reason.message
    assert [(r.kind.value, r.id) for r in reason.ids] == [("instance", "nope")]


def test_protocol_document_a_batch_is_all_or_nothing(project):
    doc = Document("car", project)
    out = doc.publish(publish("c1", {"type": "batch", "commands": [move(), {"type": "remove_instance", "id": "nope"}]}))
    assert out.reply.type == "rejected" and doc.project == project and doc.revision == 0
    assert "commands[1]" in out.reply.reasons[0].message


def test_protocol_document_the_same_command_id_applies_once(project):
    doc = Document("car", project)
    first = doc.publish(publish("c1", move()))
    again = doc.publish(publish("c1", move()))  # a resend is the same command (C6)
    assert again.reply == first.reply and again.applied is None and doc.revision == 1
    bad = doc.publish(publish("c2", {"type": "remove_instance", "id": "nope"}, base=1))
    assert doc.publish(publish("c2", {"type": "remove_instance", "id": "nope"}, base=1)).reply == bad.reply


def test_protocol_document_an_id_reused_for_another_command_is_rejected_not_silently_accepted(project):
    doc = Document("car", project)
    doc.publish(publish("c1", move()))
    other = doc.publish(publish("c1", move(x=0.9)))
    assert other.reply.type == "rejected" and "already used" in other.reply.reasons[0].message and other.applied is None
    assert doc.revision == 1
    assert doc.publish(publish("c1", move())).reply.type == "accepted"  # the first command's id still answers it


def test_protocol_document_a_stale_base_revision_is_checked_against_the_current_document(project):
    doc = Document("car", project)
    doc.publish(publish("c1", {"type": "remove_instance", "id": "wheel-fl"}))
    stale = doc.publish(publish("c2", move("wheel-fl"), base=0))  # made before the removal; no longer applies
    assert stale.reply.type == "rejected" and stale.reply.reasons[0].code is ReasonCode.UNKNOWN_ID
    fine = doc.publish(publish("c3", move("wheel-fr"), base=0))  # made before it, still applies
    assert fine.reply.type == "accepted" and fine.reply.revision == 2


def test_protocol_document_a_base_revision_ahead_of_the_document_is_rejected(project):
    out = Document("car", project).publish(publish("c1", move(), base=5))
    assert out.reply.type == "rejected" and out.reply.reasons[0].code is ReasonCode.INVALID_COMMAND


def test_protocol_document_a_command_that_changes_nothing_makes_no_revision_and_keeps_the_verdict(project):
    doc = Document("car", project, VerdictState.VALID)
    same = {"type": "select_planet", "planet": project.world.planet}
    out = doc.publish(publish("c1", same))
    assert out.reply.type == "accepted" and out.reply.revision == 0 and out.applied is None
    assert doc.revision == 0 and doc.verdict is VerdictState.VALID


def test_protocol_document_an_edit_invalidates_a_valid_verdict_in_the_same_applied(project):
    doc = Document("car", project, VerdictState.VALID)
    assert doc.publish(publish("c1", move())).applied.verdict is VerdictState.INVALID
    assert doc.verdict is VerdictState.INVALID
    none = Document("car", project)
    assert none.publish(publish("c1", move())).applied.verdict is VerdictState.NONE  # nothing to invalidate


def test_protocol_document_undo_and_redo_are_the_only_other_way_to_change_the_project(project):
    doc = Document("car", project)
    doc.publish(publish("c1", move(), origin="xr"))
    undo = doc.request(Request.model_validate({"type": "request", "id": "r1", "action": "undo", "origin": "mouse"}))
    assert doc.project == project and undo.applied.revision == 2 and undo.applied.cause == "undo"
    assert undo.applied.command.type == "move_instance"  # the inverse that was applied
    assert apply_changes(doc.project, undo.applied.changes) == doc.project
    redo = doc.request(Request.model_validate({"type": "request", "id": "r2", "action": "redo", "origin": "mouse"}))
    assert redo.applied.cause == "redo" and doc.revision == 3 and doc.project != project
    nothing = doc.request(Request.model_validate({"type": "request", "id": "r3", "action": "redo", "origin": "mouse"}))
    assert nothing.reply.type == "rejected" and nothing.reply.reasons[0].code is ReasonCode.NOTHING_TO_REDO


def test_protocol_document_resume_replays_only_what_the_client_missed(project):
    doc = Document("car", project)
    doc.publish(publish("c1", move()))
    doc.publish(publish("c2", move("wheel-fr"), base=1))
    resumed, missed = doc.resume(1, doc.epoch)
    assert (resumed.after_revision, resumed.revision, resumed.epoch) == (1, 2, doc.epoch)
    assert [json.loads(t)["revision"] for t in missed] == [2]
    assert doc.resume(2, doc.epoch)[1] == ()
    assert doc.resume(3, doc.epoch) is None  # the client is ahead of this core: a fresh snapshot


def test_protocol_document_a_client_following_applied_holds_the_same_document(project):
    doc, copy = Document("car", project), project
    commands = [move(), {"type": "select_planet", "planet": "moon"}, {"type": "remove_instance", "id": "motor-l"}]
    for n, command in enumerate(commands):
        copy = apply_changes(copy, doc.publish(publish(f"c{n}", command, base=n)).applied.changes)
    assert copy == doc.project


def test_protocol_document_messages_ignore_unknown_fields_but_commands_do_not(project):
    msg = CLIENT.validate_python({"type": "subscribe", "project": "car", "future_field": 1})
    assert msg.project == "car"
    with pytest.raises(ValidationError):
        CLIENT.validate_python({"type": "publish", "id": "c", "base_revision": 0, "origin": "mouse", "command": {**move(), "extra": 1}})
    with pytest.raises(ValidationError):  # a publish without an origin or an id is not a publish
        CLIENT.validate_python({"type": "publish", "base_revision": 0, "command": move()})
    with pytest.raises(ValidationError):
        CLIENT.validate_python({"type": "hello", "protocol": 0})


def test_protocol_document_a_rejected_message_must_have_reasons():
    with pytest.raises(ValidationError):
        SERVER.validate_python({"type": "rejected", "id": "c1", "reasons": []})


# --- WebSocket: two clients, one core ---------------------------------------------------------------------------


class Client:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, message):
        await self.ws.send(message if isinstance(message, (str, bytes)) else json.dumps(message))

    async def recv(self):
        return SERVER.validate_json(await asyncio.wait_for(self.ws.recv(), 5))

    async def open(self, project="car", after=None):
        await self.send({"type": "hello", "protocol": PROTOCOL_VERSION})
        assert (await self.recv()).type == "hello"
        extra = {} if after is None else {"after_revision": after[0], "epoch": after[1]}
        await self.send({"type": "subscribe", "project": project, **extra})


def run_with_core(project, scenario):
    async def main():
        hub = Hub({"car": project})
        async with hub.serve("127.0.0.1", 0, allowed_origins=[None]) as server:
            port = server.sockets[0].getsockname()[1]
            await scenario(hub, lambda: connect(f"ws://127.0.0.1:{port}"))

    asyncio.run(main())


def wire_publish(cid, command, base=0, origin="mouse"):
    return {"type": "publish", "id": cid, "base_revision": base, "command": command, "origin": origin}


def test_protocol_document_two_clients_stay_in_sync(project):
    async def scenario(hub, dial):
        async with dial() as wa, dial() as wb:
            a, b = Client(wa), Client(wb)
            await a.open()
            await b.open()
            sa, sb = await a.recv(), await b.recv()
            assert isinstance(sa, Snapshot) and sa == sb and sa.revision == 0 and sa.project == project
            copy_a, copy_b = sa.project, sb.project

            # A and B publish at once, from the same base revision
            await a.send(wire_publish("a1", move("wheel-fl"), origin="mouse"))
            await b.send(wire_publish("b1", move("wheel-fr", 0.7), origin="agent"))
            # each client gets both applied (in revision order) and the reply to its own command: three messages
            seen = {"a": [await a.recv() for _ in range(3)], "b": [await b.recv() for _ in range(3)]}
            applied = {who: [m for m in ms if isinstance(m, Applied)] for who, ms in seen.items()}
            assert [m.revision for m in applied["a"]] == [m.revision for m in applied["b"]] == [1, 2]  # same order for both (D2)
            assert applied["a"] == applied["b"]
            for m in applied["a"]:
                copy_a = apply_changes(copy_a, m.changes)
            for m in applied["b"]:
                copy_b = apply_changes(copy_b, m.changes)
            assert copy_a == copy_b == hub.documents["car"].project != project
            replies = {who: [m for m in ms if m.type == "accepted"] for who, ms in seen.items()}
            assert [r.id for r in replies["a"]] == ["a1"] and [r.id for r in replies["b"]] == ["b1"]
            # the publisher sees applied before its own accepted
            for ms in seen.values():
                assert [m.type for m in ms].index("applied") < [m.type for m in ms].index("accepted")
            # who did it is on every applied
            assert {m.id: m.origin for m in applied["a"]} == {"a1": Origin.MOUSE, "b1": Origin.AGENT}

    run_with_core(project, scenario)


def test_protocol_document_a_rejected_command_comes_back_only_to_its_publisher(project):
    async def scenario(hub, dial):
        async with dial() as wa, dial() as wb:
            a, b = Client(wa), Client(wb)
            await a.open()
            await b.open()
            await a.recv(), await b.recv()
            await a.send(wire_publish("a1", {"type": "remove_instance", "id": "nope"}))
            r = await a.recv()
            assert r.type == "rejected" and r.id == "a1" and r.reasons[0].code is ReasonCode.UNKNOWN_ID
            await a.send(wire_publish("a2", move()))  # B must see the next thing as revision 1: nothing was applied by a1
            assert (await b.recv()).revision == 1

    run_with_core(project, scenario)


def test_protocol_document_undo_request_reaches_every_subscriber(project):
    async def scenario(hub, dial):
        async with dial() as wa, dial() as wb:
            a, b = Client(wa), Client(wb)
            await a.open()
            await b.open()
            await a.recv(), await b.recv()
            await a.send(wire_publish("a1", move()))
            await b.recv()
            await b.send({"type": "request", "id": "b1", "action": "undo", "origin": "voice"})
            ma = await a.recv()
            while not (ma.type == "applied" and ma.cause == "undo"):
                ma = await a.recv()
            assert ma.origin is Origin.VOICE and hub.documents["car"].project == project

    run_with_core(project, scenario)


def test_protocol_document_reconnect_resumes_after_the_last_revision(project):
    async def scenario(hub, dial):
        async with dial() as wa:
            a = Client(wa)
            await a.open()
            await a.recv()
            for n, who in enumerate(("wheel-fl", "wheel-fr", "wheel-rl")):
                await a.send(wire_publish(f"a{n}", move(who), base=n))
        async with dial() as wb:  # a client that saw revision 1 comes back
            b = Client(wb)
            await b.open(after=(1, hub.documents["car"].epoch))
            resumed = await b.recv()
            assert resumed.type == "resumed" and (resumed.after_revision, resumed.revision) == (1, 3)
            assert [(await b.recv()).revision for _ in range(2)] == [2, 3]
        async with dial() as wc:  # one that is ahead of the core gets a fresh snapshot
            c = Client(wc)
            await c.open(after=(99, hub.documents["car"].epoch))
            assert (await c.recv()).type == "snapshot"

    run_with_core(project, scenario)


def test_protocol_document_a_command_sent_twice_over_the_wire_applies_once(project):
    async def scenario(hub, dial):
        async with dial() as wa:
            a = Client(wa)
            await a.open()
            await a.recv()
            for _ in range(2):
                await a.send(wire_publish("a1", move()))
            types = [(await a.recv()).type for _ in range(3)]
            assert types == ["applied", "accepted", "accepted"] and hub.documents["car"].revision == 1
            await a.send(wire_publish("a1", move(x=0.9)))  # the same id for another command: refused
            assert (await a.recv()).type == "rejected"

    run_with_core(project, scenario)


def test_protocol_document_bad_input_is_answered_not_crashed(project):
    async def scenario(hub, dial):
        async with dial() as ws:
            c = Client(ws)
            await c.send({"type": "subscribe", "project": "car"})  # before hello: fatal, then the core closes
            e = await c.recv()
            assert e.type == "error" and e.fatal
        async with dial() as ws:
            c = Client(ws)
            await c.open()
            await c.recv()
            await c.send("not json")
            assert (await c.recv()).type == "error"
            await c.send({"type": "teleport"})
            assert (await c.recv()).type == "error"
            # a publish that has an id but a command the core cannot read is a refused command, with the reason (C3)
            await c.send(wire_publish("c1", {"type": "move_instance", "id": "wheel-fl"}))
            r = await c.recv()
            assert r.type == "rejected" and r.id == "c1" and r.reasons[0].code is ReasonCode.INVALID_COMMAND
            await c.send({"type": "subscribe", "project": "nowhere"})
            assert (await c.recv()).type == "error"
            await c.send(wire_publish("c2", move()))  # the connection is still usable
            assert (await c.recv()).type == "applied"
        async with dial() as ws:
            c = Client(ws)
            await c.send({"type": "hello", "protocol": PROTOCOL_VERSION + 1})
            e = await c.recv()
            assert e.type == "error" and e.fatal and "protocol" in e.message
        async with dial() as ws:
            c = Client(ws)  # publish without subscribing
            await c.send({"type": "hello", "protocol": PROTOCOL_VERSION})
            await c.recv()
            await c.send(wire_publish("c3", move()))
            r = await c.recv()
            assert r.type == "rejected" and r.id == "c3"
        assert hub.documents["car"].revision == 1

    run_with_core(project, scenario)


def test_protocol_document_a_browser_page_from_another_origin_is_refused(project):
    async def main():
        hub = Hub({"car": project})
        async with hub.serve("127.0.0.1", 0, allowed_origins=["http://localhost:5173"]) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async with connect(url, origin="http://localhost:5173"):
                pass
            with pytest.raises(Exception, match="403"):
                async with connect(url, origin="http://evil.example"):
                    pass

    asyncio.run(main())


# --- review of #505: epochs, bounded memory, slow subscribers, in-process publishing, limits ---------------------


def test_protocol_document_a_restarted_core_does_not_resume_a_client_of_its_earlier_life(project):
    """Same revision numbers, other history: the client keeps moon from the first life, the second life never had it."""
    first = Document("car", project)
    first.publish(publish("c1", {"type": "select_planet", "planet": "moon"}))
    held = (first.revision, first.epoch)  # what the client kept
    second = Document("car", project)  # the core restarted from the original
    second.publish(publish("x1", move()))
    second.publish(publish("x2", move("wheel-fr"), base=1))
    assert second.epoch != first.epoch
    assert second.resume(held[0], held[1]) is None  # a snapshot, not "resumed 1 -> 2"
    assert second.resume(held[0], None) is None  # a client that did not say which life it comes from
    assert second.resume(1, second.epoch) is not None


def test_protocol_document_over_the_wire_an_unknown_epoch_gets_a_snapshot(project):
    async def scenario(hub, dial):
        async with dial() as ws:
            c = Client(ws)
            await c.open()
            snap = await c.recv()
            assert snap.epoch == hub.documents["car"].epoch
            await c.send(wire_publish("a1", move()))
            await c.recv(), await c.recv()
        async with dial() as ws:
            c = Client(ws)
            await c.open(after=(1, "0" * 32))  # an epoch of another life
            m = await c.recv()
            assert m.type == "snapshot" and m.revision == 1
            await c.send({"type": "subscribe", "project": "car", "after_revision": 1})  # no epoch at all
            assert (await c.recv()).type == "snapshot"

    run_with_core(project, scenario)


def test_protocol_document_the_log_is_bounded_and_resume_falls_back_to_a_snapshot(project, monkeypatch):
    from kinetra_engine.protocol import document as document_module

    monkeypatch.setattr(document_module, "LOG_MAX_REVISIONS", 3)
    doc = Document("car", project)
    for n in range(6):
        doc.publish(publish(f"c{n}", move(x=0.1 * (n + 1)), base=n))
    assert len(doc._log) == 3
    assert doc.resume(6, doc.epoch)[1] == ()  # nothing missed
    assert [json.loads(t)["revision"] for t in doc.resume(5, doc.epoch)[1]] == [6]  # inside the log
    assert doc.resume(1, doc.epoch) is None  # revision 2 is no longer held: out of range
    assert doc.resume(2, doc.epoch) is None  # revision 3 is the first missed one and it is gone too
    assert [t for t in doc._log] and doc._log[0][0] == 4


def test_protocol_document_a_replay_bigger_than_a_snapshot_is_not_sent(project):
    doc = Document("car", project)
    for n in range(8):
        doc.publish(publish(f"c{n}", move(x=0.1 * (n + 1)), base=n))  # each applied carries the whole instances section
    assert sum(len(t) for t in doc.resume(7, doc.epoch)[1]) < len(doc.snapshot().model_dump_json())
    assert doc.resume(0, doc.epoch) is None  # 8 whole sections are more than one snapshot


def test_protocol_document_the_log_is_also_bounded_by_bytes(project, monkeypatch):
    from kinetra_engine.protocol import document as document_module

    probe = Document("car", project)
    probe.publish(publish("c0", move(x=0.1)))
    one = len(probe._log[0][1].encode())
    monkeypatch.setattr(document_module, "LOG_MAX_BYTES", 2 * one + one // 2)  # room for two revisions, not three
    doc = Document("car", project)
    for n in range(4):
        doc.publish(publish(f"c{n}", move(x=0.1 * (n + 1)), base=n))
    assert [r for r, _ in doc._log] == [3, 4] and doc._log_bytes <= document_module.LOG_MAX_BYTES


def test_protocol_document_remembered_command_ids_are_bounded(project, monkeypatch):
    from kinetra_engine.protocol import document as document_module

    monkeypatch.setattr(document_module, "REMEMBERED_COMMANDS_MAX", 2)
    doc = Document("car", project)
    for n in range(4):
        doc.publish(publish(f"c{n}", move(x=0.1 * (n + 1)), base=n))
    assert list(doc._replies) == ["c2", "c3"]


def test_protocol_document_a_command_id_has_a_length_cap():
    from kinetra_core import MAX_COMMAND_ID_LENGTH

    CLIENT.validate_python(wire_publish("x" * MAX_COMMAND_ID_LENGTH, move()))
    with pytest.raises(ValidationError):
        CLIENT.validate_python(wire_publish("x" * (MAX_COMMAND_ID_LENGTH + 1), move()))


def test_protocol_document_applied_is_serialized_once_for_everyone(project):
    out = Document("car", project).publish(publish("c1", move()))
    assert out.applied_text == out.applied.model_dump_json()


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_protocol_document_an_action_the_core_does_not_handle_is_rejected_and_changes_nothing(project):
    doc = Document("car", project)
    # an action the enum does not have yet, as if X-02 added it to `RequestAction` and forgot the core's `match`
    out = doc.request(Request.model_construct(type="request", id="r1", action="run", origin=Origin.MOUSE))
    assert out.reply.type == "rejected" and out.applied is None and doc.revision == 0 and doc.project == project
    assert doc._log_bytes == 0 and len(doc._log) == 0


def test_protocol_document_a_failure_while_building_applied_leaves_the_document_untouched(project, monkeypatch):
    from kinetra_engine.protocol import document as document_module

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(document_module, "changes_between", boom)
    doc = Document("car", project)
    with pytest.raises(RuntimeError):
        doc.publish(publish("c1", move()))
    assert doc.revision == 0 and doc.project == project and len(doc._log) == 0 and not doc._replies


def test_protocol_document_hub_publish_reaches_every_subscriber_from_inside_the_process(project):
    async def scenario(hub, dial):
        async with dial() as wa:
            a = Client(wa)
            await a.open()
            await a.recv()
            out = hub.publish("car", publish("agent-1", move(), origin="agent"))  # no connection of its own
            assert out.reply.type == "accepted"
            m = await a.recv()
            assert m.type == "applied" and m.origin is Origin.AGENT and m.id == "agent-1"
            with pytest.raises(KeyError):
                hub.publish("nowhere", publish("agent-2", move()))

    run_with_core(project, scenario)


def test_protocol_document_hub_project_ids_must_be_valid(project):
    with pytest.raises(ValueError):
        Hub({"Car": project})


def test_protocol_document_serve_listens_on_loopback_only_unless_told_otherwise(project):
    async def main():
        hub = Hub({"car": project})
        for host in ("0.0.0.0", "", "192.168.1.5", "example.com"):
            with pytest.raises(ValueError, match="allow_remote"):
                hub.serve(host, 0, allowed_origins=[None])
        async with hub.serve(allowed_origins=[None]) as server:  # the default is the loopback address
            assert server.sockets[0].getsockname()[0] == "127.0.0.1"
        async with hub.serve("::1", 0, allowed_origins=[None]):
            pass

    asyncio.run(main())


def test_protocol_document_an_oversized_frame_closes_the_connection_with_1009(project):
    async def main():
        hub = Hub({"car": project})
        async with hub.serve("127.0.0.1", 0, allowed_origins=[None], max_size=2048) as server:
            async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                c = Client(ws)
                await c.open()
                await c.recv()
                await ws.send("x" * 4096)
                with pytest.raises(Exception) as info:
                    await asyncio.wait_for(ws.recv(), 5)
                assert getattr(info.value.rcvd, "code", None) == 1009

    asyncio.run(main())


def test_protocol_document_hostile_frames_get_an_error_not_a_crash(project):
    async def scenario(hub, dial):
        async with dial() as ws:
            c = Client(ws)
            await ws.send("[" * 200000)  # before hello: fatal, no traceback
            e = await c.recv()
            assert e.type == "error" and e.fatal
        async with dial() as ws:
            c = Client(ws)
            await c.open()
            await c.recv()
            await ws.send("[" * 200000)
            e = await c.recv()
            assert e.type == "error" and not e.fatal
            await c.send({"type": "t" * 5000})
            e = await c.recv()
            assert e.type == "error" and len(e.message) < 200  # the echo of an unknown type is cut
            await c.send(wire_publish("x" * 129, move()))  # an id over the cap is no command id: error
            assert (await c.recv()).type == "error"
            await c.send({"type": "request", "id": "r1", "action": "run", "origin": "mouse"})  # unknown action
            r = await c.recv()
            assert r.type == "rejected" and r.id == "r1" and hub.documents["car"].revision == 0
            await c.send(b"\x00\x01")
            assert (await c.recv()).type == "error"

    run_with_core(project, scenario)


def test_protocol_document_an_unreadable_publish_keeps_its_id(project):
    async def scenario(hub, dial):
        async with dial() as ws:
            c = Client(ws)
            await c.open()
            await c.recv()
            await c.send({"type": "subscribe", "project": "car"})
            await c.recv()
            await c.send(wire_publish("u1", {"type": "move_instance", "id": "wheel-fl"}))  # unreadable
            assert (await c.recv()).type == "rejected"
            await c.send(wire_publish("u1", move()))  # the id is spent: not applied
            r = await c.recv()
            assert r.type == "rejected" and "already used" in r.reasons[0].message and hub.documents["car"].revision == 0
            await c.send(wire_publish("u2", move()))
            await c.recv(), await c.recv()  # applied, accepted
            await c.send(wire_publish("u2", {"type": "move_instance", "id": "wheel-fl"}))  # broken resend of a done id
            assert (await c.recv()).type == "rejected" and hub.documents["car"].revision == 1

    run_with_core(project, scenario)


def test_protocol_document_a_queue_that_overflows_drops_the_subscriber_whatever_the_socket_buffers_are(project, monkeypatch):
    """The bound is on the core's own queue, so it does not depend on the kernel: a burst of `applied` published in
    one event-loop tick cannot be drained by the writer task in between, however much the socket would accept."""
    from kinetra_engine.protocol import server as server_module

    monkeypatch.setattr(server_module, "QUEUE_MAX_MESSAGES", 8)

    async def scenario(hub, dial):
        async with dial() as slow_ws, dial() as busy_ws:
            slow, busy = Client(slow_ws), Client(busy_ws)
            await slow.open()
            await busy.open()
            await slow.recv(), await busy.recv()
            assert len(hub._subscribers["car"]) == 2
            for n in range(20):  # no await: nothing is written to any socket until the burst is queued
                hub.publish("car", publish(f"burst-{n}", move(x=0.001 * (n + 1)), base=n, origin="mcp"))
            assert hub.documents["car"].revision == 20  # the document took all of them: a subscriber never slows it
            assert len(hub._subscribers["car"]) == 0  # both queues held 8; the 9th message dropped each
            for ws in (slow_ws, busy_ws):
                await asyncio.wait_for(ws.wait_closed(), 5)  # the core aborted the sockets
            async with dial() as again:  # a dropped client reconnects and is brought up to date (D6)
                c = Client(again)
                await c.open(after=(0, hub.documents["car"].epoch))
                m = await c.recv()
                assert m.type == "snapshot" and m.revision == 20  # 20 big replays are more than one snapshot
                assert len(hub._subscribers["car"]) == 1

    run_with_core(project, scenario)


def test_protocol_document_the_queue_bound_counts_bytes_once_there_is_a_message_waiting(monkeypatch):
    from kinetra_engine.protocol import server as server_module

    monkeypatch.setattr(server_module, "QUEUE_MAX_BYTES", 100)

    class FakeWs:
        pass

    conn = server_module._Connection(FakeWs())
    assert conn.enqueue("x" * 500)  # an empty queue takes one message however big (a snapshot)
    assert not conn.enqueue("y")  # but then nothing more fits
    assert conn.queue.qsize() == 1


def test_protocol_document_a_send_that_does_not_finish_drops_the_connection(monkeypatch):
    from kinetra_engine.protocol import server as server_module

    monkeypatch.setattr(server_module, "SEND_TIMEOUT_S", 0.05)

    class Transport:
        aborted = False

        def abort(self):
            self.aborted = True

    class StuckWs:
        transport = Transport()

        async def send(self, text):
            await asyncio.Event().wait()  # the peer is not reading: the write never finishes

    async def main():
        ws = StuckWs()
        conn = server_module._Connection(ws)
        conn.enqueue("{}")
        await asyncio.wait_for(conn.pump(), 5)  # returns by itself once the send times out
        assert ws.transport.aborted and conn.dropped

    asyncio.run(main())


def test_protocol_document_shutdown_does_not_wait_for_a_subscriber_that_never_reads(project):
    import time

    async def main():
        hub = Hub({"car": project})
        async with hub.serve("127.0.0.1", 0, allowed_origins=[None]) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                c = Client(ws)
                await c.open()
                await c.recv()  # one read, then never again
                started = time.monotonic()
        # leaving the server (it closes its connections) is quick: the idle subscriber has nothing queued
        assert time.monotonic() - started < 5

    asyncio.run(main())


# --- second review of #505: one big revision, bytes not characters, binary hello --------------------------------


def test_protocol_document_one_revision_bigger_than_the_byte_budget_is_not_kept(project, monkeypatch):
    from kinetra_engine.protocol import document as document_module

    doc = Document("car", project)
    doc.publish(publish("c0", move(x=0.1)))
    one = len(json.dumps(json.loads(doc._log[0][1])).encode())
    monkeypatch.setattr(document_module, "LOG_MAX_BYTES", one // 2)  # every revision alone is over the budget
    for n in range(1, 4):
        doc.publish(publish(f"c{n}", move(x=0.1 * (n + 1)), base=n))
    assert len(doc._log) == 0 and doc._log_bytes == 0 and doc.revision == 4
    assert doc.resume(3, doc.epoch) is None  # the revision it needs is not held: a snapshot, not a replay with a hole
    assert doc.resume(4, doc.epoch) is not None  # nothing to replay
    monkeypatch.setattr(document_module, "LOG_MAX_BYTES", 10 * one)  # back to normal: later revisions are kept again
    doc.publish(publish("c9", move(x=0.9), base=4))
    assert doc.resume(4, doc.epoch)[1] != () and doc.resume(3, doc.epoch) is None  # revision 4 stayed out


def test_protocol_document_byte_limits_count_utf8_bytes_not_characters(project, monkeypatch):
    from kinetra_engine.protocol import document as document_module
    from kinetra_engine.protocol.server import _Connection

    text = "한" * 100  # 100 characters, 300 bytes
    monkeypatch.setattr("kinetra_engine.protocol.server.QUEUE_MAX_BYTES", 400)

    class FakeWs:
        pass

    conn = _Connection(FakeWs())
    assert conn.enqueue(text) and conn.pending_bytes == 300  # an empty queue takes one message of any size
    assert not conn.enqueue("한" * 40)  # 120 bytes: 420 > 400 (by characters it would be 140 <= 400 and fit)
    assert conn.enqueue("a" * 100) and conn.pending_bytes == 400

    doc = Document("car", project)  # the log counts bytes too: a revision whose text has multibyte characters in it
    korean = move()
    korean["pose"]["source"]["ref"] = "단위 시험의 값 " * 20
    doc.publish(publish("c0", korean))
    text = doc._log[0][1]
    assert len(text.encode()) > len(text) and doc._log_bytes == len(text.encode())
    probe = Document("car", project)
    probe.publish(publish("c0", korean))
    monkeypatch.setattr(document_module, "LOG_MAX_BYTES", len(text))  # fits by characters, not by bytes
    other = Document("car", project)
    other.publish(publish("c0", korean))
    assert len(other._log) == 0


def test_protocol_document_a_binary_first_frame_is_refused_before_it_is_parsed(project):
    async def scenario(hub, dial):
        async with dial() as ws:
            hello = json.dumps({"type": "hello", "protocol": PROTOCOL_VERSION}).encode()
            await ws.send(hello)  # valid JSON, but a binary frame: the protocol is text only
            e = SERVER.validate_json(await asyncio.wait_for(ws.recv(), 5))
            assert e.type == "error" and e.fatal and "binary" in e.message

    run_with_core(project, scenario)
