"""C-05c: the headless reference client and the client conformance suite (`client-adapter.md` "3.1~3.3 적합성").

Every client in `CLIENTS` must pass every case of `kinetra_engine/protocol/conformance_cases/`. The cases are a
recording of the real Hub (and, for the run stream, the C-05b frame fixture); the first test fails when the Hub no
longer says what the cases say. The last tests show the suite has teeth: a client that breaks a rule fails it."""

from __future__ import annotations

import ast
import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

import conformance_fixture
from kinetra_core import ClientMessage, Frame, Origin, Project, RunEnded, decode_frame
from kinetra_engine.protocol import Hub
from kinetra_engine.protocol import client as client_module
from kinetra_engine.protocol.client import KNOWN_TYPES, ProtocolViolation, ReferenceClient
from kinetra_engine.protocol.conformance import CASES_DIR, iter_messages, load_cases, run_case

ROOT = Path(__file__).resolve().parents[3]
CASES = load_cases()
CLIENTS = {"reference": ReferenceClient}
"""Every client of the core that runs in Python. A client in another language runs the same cases through
`python -m kinetra_engine.protocol.conformance serve` (see `test_conformance_a_client_in_another_process_...`)."""


def by_name(name: str) -> dict:
    return next(c for c in CASES if c["case"] == name)


# --- the cases ------------------------------------------------------------------------------------------------


def test_conformance_cases_are_what_the_hub_and_the_frame_fixture_say_today():
    built = asyncio.run(conformance_fixture.build())
    on_disk = {p.name: p.read_text(encoding="utf-8") for p in CASES_DIR.glob("*.json")}
    assert set(on_disk) == set(built)
    for name, case in built.items():
        assert on_disk[name] == conformance_fixture.render(case), f"{name} is stale: run packages/engine/tests/conformance_fixture.py"


def test_conformance_cases_cover_the_rules_of_the_issue():
    """hello/subscribe/resume(epoch)/publish/accepted/rejected/applied ordering, the frame stream with the end frame,
    the unknown-type rule, and a broken core for each ordering rule the client checks."""
    names = {c["case"] for c in CASES}
    assert {
        "01-open-snapshot",
        "02-publish-accepted",
        "03-publish-rejected",
        "05-undo",
        "06-resume-same-epoch",
        "07-resume-after-restart",
        "08-unknown-type-ignored",
        "09-run-stream",
        "13-violation-run-without-end-frame",
    } <= names
    kinds = {m["type"] for c in CASES for m in iter_messages(c)}
    assert {"hello", "subscribe", "snapshot", "resumed", "publish", "request", "applied", "accepted", "rejected"} <= kinds
    assert {"run_started", "frame", "run_ended"} <= kinds
    run = by_name("09-run-stream")
    assert any("core_binary" in s for s in run["steps"]) and run["expect"]["runs"][0]["ticks"][-2:] == [128, 130]
    assert [129, "break"] in run["expect"]["runs"][0]["events"]  # only the end frame carries it


def test_conformance_every_message_of_the_cases_is_a_protocol_message():
    """The cases are the schema's messages: a client built from the JSON Schema alone reads them. Messages of an
    unknown `type` are the only exception, on purpose (G5)."""
    client = TypeAdapter(ClientMessage)
    server_schema = json.loads((ROOT / "schemas" / "ServerMessage.schema.json").read_text(encoding="utf-8"))
    client_schema = json.loads((ROOT / "schemas" / "ClientMessage.schema.json").read_text(encoding="utf-8"))
    server_v, client_v = Draft202012Validator(server_schema), Draft202012Validator(client_schema)
    unknown = 0
    for case in CASES:
        for step in case["steps"]:
            if "client" in step:
                client.validate_python(step["client"])
                assert not list(client_v.iter_errors(step["client"])), (case["case"], step)
            elif "core" in step and step["core"]["type"] in KNOWN_TYPES:
                assert not list(server_v.iter_errors(step["core"])), (case["case"], step["core"]["type"])
            elif "core" in step:
                unknown += 1
                assert case["case"] in ("08-unknown-type-ignored", "09-run-stream", "13-violation-run-without-end-frame")
    assert unknown == 4  # two presence, and run_progress in the run stream and its broken copy


def test_conformance_no_engine_term_crosses_the_boundary():
    """F1/G2 over everything a client sees in the cases (keys and string values)."""
    banned = ("qpos", "qvel", "geom", "mjcf", "mujoco", "xpos", "xquat", "mjdata", "mjmodel")
    text = "\n".join(p.read_text(encoding="utf-8").lower() for p in CASES_DIR.glob("*.json"))
    assert not [t for t in banned if t in text]


# --- every client passes every case ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_name", sorted(CLIENTS))
@pytest.mark.parametrize("case", CASES, ids=[c["case"] for c in CASES])
def test_conformance_client_passes(client_name, case):
    assert asyncio.run(run_case(case, CLIENTS[client_name])) == []


# --- the reference client ---------------------------------------------------------------------------------------


def test_conformance_reference_client_speaks_only_the_protocol():
    """No web code and no core code: the client imports the message models of `kinetra_core` (what the JSON Schema
    says), a WebSocket library and the standard library. Nothing of `kinetra_engine` (Hub, Document, applier)."""
    tree = ast.parse(Path(client_module.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    roots = {m.split(".")[0] for m in modules if m}
    assert roots <= {"__future__", "json", "uuid", "dataclasses", "typing", "pydantic", "websockets", "kinetra_core"}
    assert "kinetra_engine" not in roots
    assert "History" not in Path(client_module.__file__).read_text(encoding="utf-8")  # no applier (D3)


def example_project() -> Project:
    return conformance_fixture.example_project()


def test_conformance_reference_client_against_the_live_hub():
    """Open the project, publish, see another client's edits, resume after a reconnect: the reference client's copy is
    the core's document at every step."""

    async def main():
        hub = Hub({"car": example_project()})
        async with hub.serve("127.0.0.1", 0, allowed_origins=[None]) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            a, b = ReferenceClient(url), ReferenceClient(url)
            for c in (a, b):
                await c.connect()
                assert await c.subscribe("car") == "snapshot"
            answer = await a.publish({"type": "select_planet", "planet": "moon"}, Origin.MOUSE)
            assert answer.type == "accepted" and answer.revision == 1
            await b.receive()  # the applied of a's edit
            assert a.project == b.project == hub.documents["car"].project and b.revision == 1
            refused = await a.publish({"type": "remove_instance", "id": "nope"}, Origin.AGENT)
            assert refused.type == "rejected" and refused.reasons
            await a.close()
            await b.publish({"type": "select_planet", "planet": "mars"}, Origin.VOICE)
            await b.request("undo", Origin.MOUSE)
            await a.connect()
            assert await a.subscribe("car") == "resumed"  # same epoch, the two missed applied replayed in order
            assert a.revision == b.revision == hub.documents["car"].revision == 3
            assert a.project == b.project == hub.documents["car"].project
            await a.close()
            await b.close()

    asyncio.run(main())


def test_conformance_reference_client_reads_both_frame_encodings_as_the_same_frame():
    """The run stream case sends the frames as binary and the last two as JSON; the decoded binary frames have the
    recorded ticks and events (poses are float32 there, so the JSON end frame is the exact one)."""
    case = by_name("09-run-stream")
    started = next(s["core"] for s in case["steps"] if s.get("core", {}).get("type") == "run_started")
    ids = [b["id"] for b in started["bodies"]]
    binary = [decode_frame(base64.b64decode(s["core_binary"]), started["run_id"], ids) for s in case["steps"] if "core_binary" in s]
    assert [f.tick for f in binary] == case["expect"]["runs"][0]["ticks"][: len(binary)]
    last = Frame.model_validate(case["expect"]["runs"][0]["last_frame"])
    ended = RunEnded.model_validate(next(s["core"] for s in case["steps"] if s.get("core", {}).get("type") == "run_ended"))
    assert last.tick == ended.last_tick == 130 and 130 % started["frame_every_ticks"]


# --- the suite has teeth: clients that break a rule fail ----------------------------------------------------------


class IgnoresNothing(ReferenceClient):
    """Treats a message of an unknown type as an error (G5 broken)."""

    async def _next(self):
        message = await super()._next()
        if self.ignored:
            raise ProtocolViolation(f"unknown type {self.ignored[-1]}")
        return message


class TrustsTheRunEnd(ReferenceClient):
    """Takes `run_ended` without checking the stream (the end frame rule of 3.3 not checked)."""

    def _handle(self, message):
        if isinstance(message, RunEnded):
            self._live_run(message.run_id).ended = message
            return
        super()._handle(message)


class ForgetsTheEpoch(ReferenceClient):
    """Asks to resume with a revision but no epoch (D6 broken: the core would answer a snapshot)."""

    async def _send(self, message):
        message.pop("epoch", None)
        await super()._send(message)


class AppliesOutOfOrder(ReferenceClient):
    """Applies whatever `applied` comes, without checking it is the next revision (D2 broken)."""

    def _handle(self, message):
        from kinetra_core import Applied, apply_changes

        if isinstance(message, Applied):
            self.project, self.revision = apply_changes(self.project, message.changes), message.revision
            return
        super()._handle(message)


@pytest.mark.parametrize(
    ("client", "case"),
    [
        (IgnoresNothing, "08-unknown-type-ignored"),
        (IgnoresNothing, "09-run-stream"),
        (TrustsTheRunEnd, "13-violation-run-without-end-frame"),
        (ForgetsTheEpoch, "06-resume-same-epoch"),
        (AppliesOutOfOrder, "10-violation-applied-skips-a-revision"),
    ],
)
def test_conformance_a_client_that_breaks_a_rule_fails(client, case):
    problems = asyncio.run(run_case(by_name(case), client))
    assert problems, f"{client.__name__} passed {case}"


def test_conformance_a_client_in_another_process_runs_the_cases_through_the_cli():
    """What a web, XR or Godot client does: the CLI plays the core side and checks every message the client sends."""
    path = CASES_DIR / "06-resume-same-epoch.json"
    proc = subprocess.Popen(
        [sys.executable, "-m", "kinetra_engine.protocol.conformance", "serve", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        url = proc.stdout.readline().strip()
        assert url.startswith("ws://127.0.0.1:")

        async def client():
            from kinetra_engine.protocol.conformance import drive

            c = ReferenceClient(url)
            await drive(c, json.loads(path.read_text(encoding="utf-8")))
            await c.close()
            return c

        c = asyncio.run(client())
        assert proc.wait(timeout=10) == 0, proc.stderr.read()
        assert c.revision == 2 and c.epoch == "epoch-1"
    finally:
        proc.kill()
        proc.wait()

    broken = subprocess.Popen(
        [sys.executable, "-m", "kinetra_engine.protocol.conformance", "serve", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        url = broken.stdout.readline().strip()

        async def forgetful():
            c = ForgetsTheEpoch(url)
            await c.connect()
            await c.subscribe("four-wheel-car")
            await c.publish({"type": "select_planet", "planet": "moon"}, "mouse", "c1")
            await c.close()
            await c.connect()
            await c.subscribe("four-wheel-car")  # sends no epoch: the CLI reports it and exits 1

        with pytest.raises(Exception):
            asyncio.run(asyncio.wait_for(forgetful(), 5))
        assert broken.wait(timeout=10) == 1 and "epoch" in broken.stderr.read()
    finally:
        broken.kill()
        broken.wait()
