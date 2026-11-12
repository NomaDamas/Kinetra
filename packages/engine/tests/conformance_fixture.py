"""The writer of the client conformance cases (C-05c) in `kinetra_engine/protocol/conformance_cases/`.

    uv run python packages/engine/tests/conformance_fixture.py     # rewrites the cases (test_conformance.py fails when they are stale)

`hub` cases are recorded from the real `Hub` over a real local WebSocket, with a raw socket that sends what a conforming
client sends (not the reference client: the cases must not be written by the client they test). The expected state is
what the core's messages say, cross-checked against the Hub's own document after the recording. Each random `epoch`
is replaced by a label (`epoch-1`, `epoch-2`, in order of appearance) so the recording is the same every time.

`composed` cases are built from recorded ones:

- the run stream: the core has no run path yet (X-02), so after a recorded `subscribe` the core side is the C-05b
  frame fixture (`frame_fixture.py`: an analytic drop of the example car, NOT an engine run), sent as a live core
  would: `run_started`, binary frames, two JSON frames at the end (the last one the end frame at tick 130, off the
  8-tick grid, carrying the break of tick 129), `run_ended`;
- messages of a `type` added after the client was written, and a known message with a field added after (G5);
- broken cores, which the client must refuse (`expect.violation`).
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from pathlib import Path

from websockets.asyncio.client import connect

from frame_fixture import build as build_frames
from kinetra_core import PROTOCOL_VERSION, Frame, Project, ProjectChanges, Publish, RunEnded, RunStarted, apply_changes, encode_frame
from kinetra_engine.protocol import Hub
from kinetra_engine.protocol.conformance import CASES_DIR

ROOT = Path(__file__).resolve().parents[3]
PROJECT_ID = "four-wheel-car"
MOVE_TO_MOON = {"type": "select_planet", "planet": "moon"}
MOVE_TO_MARS = {"type": "select_planet", "planet": "mars"}
STAY_ON_EARTH = {"type": "select_planet", "planet": "earth"}  # the example is on earth: an edit that changes nothing
REMOVE_MISSING = {"type": "remove_instance", "id": "no-such-instance"}


def example_project() -> Project:
    path = ROOT / "schemas" / "examples" / "Project.four-wheel-car.json"
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


class Recorder:
    """Drives the real Hub with raw messages and records both directions; keeps the state a client would have."""

    def __init__(self):
        self.hub = Hub({PROJECT_ID: example_project()})
        self.steps: list[dict] = []
        self.labels: dict[str, str] = {}  # real epoch -> label
        self.ws = None
        self.served = None
        self.project: Project | None = None
        self.revision: int | None = None
        self.epoch: str | None = None  # a label
        self.verdict: str | None = None
        self.outcomes: dict[str, str] = {}

    def _label(self, real: str) -> str:
        return self.labels.setdefault(real, f"epoch-{len(self.labels) + 1}")

    def _real(self, label: str) -> str:
        return next((real for real, lab in self.labels.items() if lab == label), label)

    async def say(self, message: dict) -> None:
        self.steps.append({"client": message})
        real = {**message, "epoch": self._real(message["epoch"])} if message.get("epoch") else message
        await self.ws.send(json.dumps(real))

    async def hear(self) -> dict:
        message = json.loads(await asyncio.wait_for(self.ws.recv(), 10))
        if "epoch" in message:
            message["epoch"] = self._label(message["epoch"])
        self.steps.append({"core": message})
        match message["type"]:
            case "snapshot":
                self.project = Project.model_validate(message["project"])
                self.revision, self.epoch, self.verdict = message["revision"], message["epoch"], message["verdict"]
            case "applied":
                assert message["revision"] == self.revision + 1
                self.project = apply_changes(self.project, ProjectChanges.model_validate(message["changes"]))
                self.revision, self.verdict = message["revision"], message["verdict"]
            case "accepted" | "rejected":
                self.outcomes[message["id"]] = message["type"]
        return message

    async def connect(self) -> None:
        self.steps.append({"do": "connect"})
        self.served = self.hub.serve("127.0.0.1", 0, allowed_origins=[None])
        server = await self.served.__aenter__()
        self.ws = await connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        await self.say({"type": "hello", "protocol": PROTOCOL_VERSION})
        assert (await self.hear())["type"] == "hello"

    async def subscribe(self) -> None:
        self.steps.append({"do": "subscribe", "project": PROJECT_ID})
        message = {"type": "subscribe", "project": PROJECT_ID}
        if self.revision is not None:
            message |= {"after_revision": self.revision, "epoch": self.epoch}
        await self.say(message)
        head = await self.hear()
        if head["type"] == "resumed":
            for _ in range(head["revision"] - head["after_revision"]):
                await self.hear()

    async def edit(self, kind: str, cid: str, origin: str, **fields) -> None:
        self.steps.append({"do": kind, "id": cid, "origin": origin, **fields})
        message = {"type": kind, "id": cid, **fields, "origin": origin}
        if kind == "publish":
            message = {"type": "publish", "id": cid, "base_revision": self.revision, "command": fields["command"], "origin": origin}
        await self.say(message)
        while True:
            reply = await self.hear()
            if reply["type"] in ("accepted", "rejected") and reply["id"] == cid:
                return

    async def close(self) -> None:
        self.steps.append({"do": "close"})
        await self.ws.close()
        await self.served.__aexit__(None, None, None)

    def core_publish(self, cid: str, command: dict, origin: str) -> None:
        """Another publisher (the agent, in-process) edits while this client is away."""
        message = {"type": "publish", "id": cid, "base_revision": self.hub.documents[PROJECT_ID].revision, "command": command, "origin": origin}
        self.steps.append({"core_side": {"hub_publish": message}})
        assert self.hub.publish(PROJECT_ID, Publish.model_validate(message)).reply.type == "accepted"

    def core_restart(self) -> None:
        """The core process restarts: the document is opened again (a new epoch, the history is gone)."""
        self.steps.append({"core_side": {"restart": True}})
        self.hub = Hub({PROJECT_ID: example_project()})

    def expect(self) -> dict:
        document = self.hub.documents[PROJECT_ID]
        assert self.project == document.project and self.revision == document.revision  # the core's own document
        return {
            "revision": self.revision,
            "epoch": self.epoch,
            "verdict": self.verdict,
            "project": self.project.model_dump(mode="json"),
            "outcomes": self.outcomes,
            "ignored": [],
            "runs": [],
        }


def case(name: str, title: str, rules: list[str], source: str, steps: list[dict], expect: dict) -> dict:
    return {"case": name, "title": title, "rules": rules, "source": source, "steps": steps, "expect": expect}


async def record(script) -> tuple[list[dict], dict]:
    r = Recorder()
    await script(r)
    return r.steps, r.expect()


async def _open(r):
    await r.connect()
    await r.subscribe()
    await r.close()


async def _accepted(r):
    await r.connect()
    await r.subscribe()
    await r.edit("publish", "c1", "mouse", command=MOVE_TO_MOON)
    await r.close()


async def _rejected(r):
    await r.connect()
    await r.subscribe()
    await r.edit("publish", "c1", "mouse", command=REMOVE_MISSING)
    await r.close()


async def _unchanged(r):
    await r.connect()
    await r.subscribe()
    await r.edit("publish", "c1", "voice", command=STAY_ON_EARTH)
    await r.close()


async def _undo(r):
    await r.connect()
    await r.subscribe()
    await r.edit("publish", "c1", "mouse", command=MOVE_TO_MOON)
    await r.edit("request", "r1", "mouse", action="undo")
    await r.close()


async def _resume(r):
    await r.connect()
    await r.subscribe()
    await r.edit("publish", "c1", "mouse", command=MOVE_TO_MOON)
    await r.close()
    r.core_publish("c2", MOVE_TO_MARS, "agent")
    await r.connect()
    await r.subscribe()
    await r.close()


async def _restart(r):
    await r.connect()
    await r.subscribe()
    await r.edit("publish", "c1", "mouse", command=MOVE_TO_MOON)
    await r.close()
    r.core_restart()
    await r.connect()
    await r.subscribe()
    await r.close()


def _core_index(steps: list[dict], kind: str, nth: int = 0) -> int:
    return [i for i, s in enumerate(steps) if s.get("core", {}).get("type") == kind][nth]


def _run_stream() -> tuple[list[dict], dict, dict]:
    """The core side of one run (the C-05b fixture) as a live core sends it, and what a client keeps of it."""
    lines = [json.loads(line) for line in build_frames()["run.jsonl"].decode("utf-8").splitlines()]
    started = RunStarted.model_validate(lines[0])
    frames = [Frame.model_validate(m) for m in lines[1:-1]]
    ended = RunEnded.model_validate(lines[-1])
    ids = [b.id for b in started.bodies]
    steps = [{"core": lines[0]}]
    for i, frame in enumerate(frames):
        if i < len(frames) - 2:  # the live form; the last two go as JSON (both forms are the same frame)
            steps.append({"core_binary": base64.b64encode(encode_frame(frame, ids)).decode("ascii")})
        else:
            steps.append({"core": lines[1 + i]})
        if frame.tick == 64:
            steps.append({"core": {"type": "run_progress", "run_id": started.run_id, "fraction": 0.5}})
    steps.append({"core": lines[-1]})
    summary = {
        "run_id": started.run_id,
        "kind": str(started.kind),
        "ticks": [f.tick for f in frames],
        "last_tick": ended.last_tick,
        "end": ended.end.reason,
        "events": [[e.tick, e.kind] for f in frames for e in f.events],
        "last_frame": lines[-2],
    }
    return steps, summary, lines[-2]


async def build() -> dict[str, dict]:
    cases = []
    steps, expect = await record(_open)
    cases.append(case("01-open-snapshot", "hello, subscribe, the whole document as a snapshot", ["G5", "D1"], "hub", steps, expect))
    steps, expect = await record(_accepted)
    accepted = (steps, expect)
    cases.append(case("02-publish-accepted", "a publish: applied (next revision) then accepted", ["D2", "D3", "C1"], "hub", steps, expect))
    steps, expect = await record(_rejected)
    cases.append(case("03-publish-rejected", "a publish the core refuses: rejected with reasons, no revision", ["C2", "C3"], "hub", steps, expect))
    steps, expect = await record(_unchanged)
    cases.append(case("04-publish-unchanged", "an edit that changes nothing: accepted at the same revision, no applied", ["D2", "D5"], "hub", steps, expect))
    steps, expect = await record(_undo)
    cases.append(case("05-undo", "an undo request: applied (cause undo, the inverse command) then accepted", ["C1", "D3"], "hub", steps, expect))
    steps, expect = await record(_resume)
    resume = (steps, expect)
    cases.append(case("06-resume-same-epoch", "a reconnect with revision and epoch: resumed, then the missed applied in order", ["D6"], "hub", steps, expect))
    steps, expect = await record(_restart)
    cases.append(case("07-resume-after-restart", "a reconnect to a restarted core (another epoch): a fresh snapshot", ["D6"], "hub", steps, expect))

    # G5: a client ignores a message type it does not know, and a field it does not know
    steps, expect = copy.deepcopy(accepted)
    snapshot = _core_index(steps, "snapshot")
    applied = _core_index(steps, "applied")
    steps[applied]["core"]["future_field"] = {"added": "after this client"}
    steps.insert(applied + 1, {"core": {"type": "presence", "user": "someone", "cursor": [0, 0]}})
    steps.insert(snapshot + 1, {"core": {"type": "presence", "user": "someone", "cursor": [1, 2]}})
    expect["ignored"] = ["presence", "presence"]
    cases.append(case("08-unknown-type-ignored", "messages of an unknown type and an unknown field are ignored", ["G5"], "composed", steps, expect))

    # the run stream after a recorded subscription
    steps, expect = await record(_open)
    run_steps, summary, _ = _run_stream()
    close = steps.index({"do": "close"})
    steps[close:close] = [{"do": "receive_run"}, *run_steps]
    expect["runs"], expect["ignored"] = [summary], ["run_progress"]
    run_case = case(
        "09-run-stream",
        "run_started, binary and JSON frames, the end frame off the grid (tick 130, the break of tick 129), run_ended",
        ["F2", "F3", "F4", "G4", "G5"],
        "composed",
        steps,
        expect,
    )
    cases.append(run_case)

    # reconnects: what belonged to the old connection (a replay owed, a run going on) does not carry over
    steps, expect = copy.deepcopy(resume)
    first, second = [i for i, s in enumerate(steps) if s.get("do") == "connect"]
    hello = steps[first + 1 : first + 3]
    snapshot_step = steps[_core_index(steps, "snapshot")]
    resumed_step = steps[_core_index(steps, "resumed")]
    applied_1, applied_2 = steps[_core_index(steps, "applied", 0)], steps[_core_index(steps, "applied", 1)]
    sub = {"type": "subscribe", "project": PROJECT_ID}
    owed = {**resumed_step["core"], "after_revision": 0}
    steps = [
        {"do": "connect"}, *hello, {"do": "subscribe", "project": PROJECT_ID}, {"client": sub}, snapshot_step, {"do": "close"},
        {"do": "connect"}, *hello, {"do": "subscribe", "project": PROJECT_ID, "dropped": True},
        {"client": {**sub, "after_revision": 0, "epoch": "epoch-1"}}, {"core": owed}, applied_1, {"core_close": True},
        {"do": "connect"}, *hello, {"do": "subscribe", "project": PROJECT_ID},
        {"client": {**sub, "after_revision": 1, "epoch": "epoch-1"}}, resumed_step, applied_2, {"do": "close"},
    ]
    expect["outcomes"] = {}
    cases.append(case("14-reconnect-mid-replay", "the core drops the connection after 1 of the 2 applied owed; the client resumes from revision 1", ["D6"], "composed", steps, expect))

    steps, expect = copy.deepcopy((run_case["steps"], run_case["expect"]))
    receive = steps.index({"do": "receive_run"})
    cut = copy.deepcopy(steps[receive + 1 : receive + 4])  # run_started and two binary frames of a run that is cut
    cut[0]["core"]["run_id"] = "fixture-run-0"
    resumed_0 = {"type": "resumed", "project_id": PROJECT_ID, "epoch": "epoch-1", "after_revision": 0, "revision": 0}
    hello = steps[1:3]
    steps[receive:receive] = [
        {"do": "receive_run", "dropped": True}, *cut, {"core_close": True},
        {"do": "connect"}, *hello, {"do": "subscribe", "project": PROJECT_ID},
        {"client": {**sub, "after_revision": 0, "epoch": "epoch-1"}}, {"core": resumed_0},
    ]
    cases.append(case("15-reconnect-mid-run", "the connection closes during a run; after a reconnect a new run streams whole", ["F3", "F4", "D6"], "composed", steps, expect))

    # broken cores: the client must refuse them with the rule's code, at the message that breaks it
    steps = copy.deepcopy(accepted[0])
    for kind in ("applied", "accepted"):
        steps[_core_index(steps, kind)]["core"]["revision"] = 2
    cases.append(case("10-violation-applied-skips-a-revision", "an applied that is not the next revision", ["D2"], "composed", steps, violation(steps, _core_index(steps, "applied"), "revision_gap", "applied revision 2 after revision 0")))
    steps = copy.deepcopy(accepted[0])
    a, b = _core_index(steps, "applied"), _core_index(steps, "accepted")
    steps[a], steps[b] = steps[b], steps[a]
    cases.append(case("11-violation-accepted-before-applied", "accepted arrives before the applied of its edit", ["D2"], "composed", steps, violation(steps, a, "accepted_before_applied", "the publisher gets its applied before its accepted")))
    steps = copy.deepcopy(resume[0])
    steps[_core_index(steps, "resumed")]["core"]["epoch"] = "epoch-of-another-life"
    cases.append(case("12-violation-resumed-other-epoch", "resumed under another epoch than the client holds", ["D6"], "composed", steps, violation(steps, _core_index(steps, "resumed"), "resume_mismatch", "resumed continues another life of the document")))
    steps = copy.deepcopy(run_case["steps"])
    del steps[_core_index(steps, "frame", -1)]
    cases.append(case("13-violation-run-without-end-frame", "run_ended at tick 130 with no frame at tick 130", ["F3", "F4"], "composed", steps, violation(steps, _core_index(steps, "run_ended"), "run_stream", "the core always sends the end frame before run_ended")))
    return {f"{c['case']}.json": c for c in sorted(cases, key=lambda c: c["case"])}


def violation(steps: list[dict], index: int, code: str, why: str) -> dict:
    """The client must raise `code` while handling the core message at `steps[index]` (numbered over the case)."""
    at = sum(1 for s in steps[: index + 1] if "core" in s or "core_binary" in s)
    return {"violation": why, "code": code, "at_message": at}


def render(c: dict) -> str:
    """One step per line (a diff shows which message changed), compact inside a line."""

    def dump(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    head = ",\n".join(f" {dump(k)}: {dump(c[k])}" for k in ("case", "title", "rules", "source"))
    steps = ",\n".join(f"  {dump(s)}" for s in c["steps"])
    return f'{{\n{head},\n "steps": [\n{steps}\n ],\n "expect": {dump(c["expect"])}\n}}\n'


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    for old in CASES_DIR.glob("*.json"):
        old.unlink()
    for name, c in asyncio.run(build()).items():
        (CASES_DIR / name).write_text(render(c), encoding="utf-8")
        print(f"wrote {CASES_DIR / name}")


if __name__ == "__main__":
    main()
