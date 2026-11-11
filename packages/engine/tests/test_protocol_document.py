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
    again = doc.publish(publish("c1", move(x=0.9)))  # a resend, even with other content, is the same command (C6)
    assert again.reply == first.reply and again.applied is None and doc.revision == 1
    bad = doc.publish(publish("c2", {"type": "remove_instance", "id": "nope"}, base=1))
    assert doc.publish(publish("c2", move(), base=1)).reply == bad.reply and doc.revision == 1


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
    resumed, missed = doc.resume(1)
    assert (resumed.after_revision, resumed.revision) == (1, 2) and [a.revision for a in missed] == [2]
    assert doc.resume(2)[1] == () and doc.resume(0)[1] != ()
    assert doc.resume(3) is None  # the client is ahead of this core: a fresh snapshot


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
        await self.ws.send(message if isinstance(message, str) else json.dumps(message))

    async def recv(self):
        return SERVER.validate_json(await asyncio.wait_for(self.ws.recv(), 5))

    async def open(self, project="car", after=None):
        await self.send({"type": "hello", "protocol": PROTOCOL_VERSION})
        assert (await self.recv()).type == "hello"
        await self.send({"type": "subscribe", "project": project, **({} if after is None else {"after_revision": after})})


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
            await b.open(after=1)
            resumed = await b.recv()
            assert resumed.type == "resumed" and (resumed.after_revision, resumed.revision) == (1, 3)
            assert [(await b.recv()).revision for _ in range(2)] == [2, 3]
        async with dial() as wc:  # one that is ahead of the core gets a fresh snapshot
            c = Client(wc)
            await c.open(after=99)
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
