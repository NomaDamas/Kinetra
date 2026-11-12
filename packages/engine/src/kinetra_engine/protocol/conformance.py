"""The client conformance suite (C-05c; `client-adapter.md` "3.1~3.3 적합성").

Every client of the core (the headless reference client, the web client, XR, a Godot client: GD-01) must pass the
same recorded cases, in `conformance_cases/*.json`. A case is language-neutral JSON:

    {"case": name, "title": what it shows, "rules": ["D6", ...], "source": "hub" | "composed",
     "steps": [...], "expect": {...}}

`steps`, in order, are of four kinds:

- `{"do": "connect"}`, `{"do": "subscribe", "project": id}`, `{"do": "publish", "id", "command", "origin"}`,
  `{"do": "request", "id", "action", "origin"}`, `{"do": "receive_run"}`, `{"do": "receive", "count": n}` (handle n
  messages), `{"do": "close"}`: what the client is told to do (by its test harness). The command id is given so the
  wire can be compared; a client lets its caller pick it. A `do` with `"dropped": true` is cut short by the core
  closing the connection: the client loses the connection there (not a `ProtocolViolation`) and goes on with the next
  `do`.
- `{"client": message}`: the message a conforming client sends at this point (compared as a `ClientMessage`: field
  order, an omitted optional field and an explicit `null` are the same).
- `{"core": message}` / `{"core_binary": base64}`: what the core sends (text JSON, or one binary frame of 3.3).
  `{"core_close": true}`: the core closes the connection (a restart, a dropped subscriber).
- `{"core_side": ...}`: what happened inside the core while no client was connected (another publisher, a restart).
  Only the recorder acts on it; a player skips it.

`expect` is the client's state after the last step: `revision`, `epoch`, `verdict`, `project` (the whole Project JSON),
`outcomes` (command id -> `accepted` / `rejected`), `ignored` (the unknown `type`s it skipped, in order), `runs` (per
run received whole: `run_id`, `kind`, `ticks`, `last_tick`, `end`, `events` as `[tick, kind]`, `last_frame`; a run
cut by a closed connection is not one of them). Or it is `{"violation": why, "code": rule, "at_message": n}`: the
core in this case breaks a rule and the client must refuse it with exactly that `ProtocolViolation.code`, while
handling the `n`-th message the core sent in the case (counting every `core` and `core_binary` step from the first
connection on). A refusal for another reason or at another message fails the case: it would pass a client that refuses
the wrong thing.

`source: hub` cases are a recording of the real `Hub` (`packages/engine/tests/conformance_fixture.py` writes them; a
test fails when the Hub no longer says the same), with each random `epoch` replaced by a label. `composed` cases are
built from recorded ones: the run stream (the core has no run path yet, X-02; the frames are the C-05b fixture, which
is analytic, not an engine run), messages of a `type` added after the client was written (G5), and broken cores.

How a client runs it:

- A Python client with the methods of `ReferenceClient` (`connect`, `subscribe`, `publish`, `request`,
  `receive_run`, `close`, and the state attributes) passes when `run_case(case, make_client)` returns no problems; the
  pytest suite `packages/engine/tests/test_conformance.py` does this for every client in its `CLIENTS` list.
- Any other client: `uv run python -m kinetra_engine.protocol.conformance serve CASE.json` plays the core side of
  the case on a local port (it prints the URL) and checks every message the client sends; it exits 0 when the client
  sent exactly the expected messages. The client's own harness performs the `do` steps against that URL and compares
  its state with `expect`.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kinetra_core import ClientMessage, Frame, Project

from .client import CoreError, ProtocolViolation, ReferenceClient

CASES_DIR = Path(__file__).resolve().parent / "conformance_cases"
CASE_TIMEOUT_S = 10.0
"""How long one case may take (`기본값`, chosen: the cases are a few dozen local messages)."""

_CLIENT = TypeAdapter(ClientMessage)


def load_cases(directory: Path = CASES_DIR) -> list[dict]:
    """Every case, by file name."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def _segments(case: dict) -> list[list[dict]]:
    """The wire steps of each connection, in order (a segment starts at each `connect`)."""
    segments: list[list[dict]] = []
    for step in case["steps"]:
        if step.get("do") == "connect":
            segments.append([])
        elif "client" in step or "core" in step or "core_binary" in step or "core_close" in step:
            segments[-1].append(step)
    return segments


class ScriptedCore:
    """The core side of one case: sends the recorded `core` messages and checks every message the client sends."""

    def __init__(self, case: dict):
        self.case = case
        self.segments = _segments(case)
        self.problems: list[str] = []
        self.connections = 0  # connections opened so far
        self.finished = 0  # connections that got through their whole segment
        self.active = 0
        self.idle = asyncio.Event()
        self.idle.set()

    def done(self) -> bool:
        """Nothing more will happen: every connection came and went, or one ended short of its segment (a client that
        refused the core, or a broken client: either way the later connections will not come)."""
        return self.idle.is_set() and (self.connections >= len(self.segments) or self.connections > self.finished)

    async def handler(self, ws: ServerConnection) -> None:
        n, self.connections = self.connections, self.connections + 1
        self.active += 1
        self.idle.clear()
        try:
            if n >= len(self.segments):
                self.problems.append(f"connection {n + 1}: the case has {len(self.segments)} connections")
                return
            for i, step in enumerate(self.segments[n]):
                where = f"connection {n + 1}, wire step {i + 1}"
                if "client" in step:
                    raw = await ws.recv()
                    problem = _compare_client(step["client"], raw)
                    if problem:
                        self.problems.append(f"{where}: {problem}")
                        return
                elif "core" in step:
                    await ws.send(json.dumps(step["core"]))
                elif "core_binary" in step:
                    await ws.send(base64.b64decode(step["core_binary"]))
                else:
                    self.finished += 1
                    await ws.close()
                    return
            self.finished += 1
            async for raw in ws:  # the script is over: anything more the client sends is not in the case
                self.problems.append(f"connection {n + 1}: a message after the end of the case: {raw!r:.120}")
        except ConnectionClosed:
            pass
        finally:
            self.active -= 1
            if not self.active:
                self.idle.set()


def _compare_client(expected: dict, raw: str | bytes) -> str | None:
    if isinstance(raw, bytes):
        return "the client sent a binary message; client -> core messages are JSON text"
    try:
        got = _CLIENT.validate_json(raw)
    except ValidationError as e:
        return f"the client sent a message that is not a client message: {raw[:200]!r} ({e.error_count()} errors)"
    want = _CLIENT.validate_python(expected)
    if got != want:
        return f"expected {json.dumps(expected)[:300]}, the client sent {raw[:300]}"
    return None


async def drive(client: Any, case: dict) -> None:
    """Perform the case's `do` steps on a client with the `ReferenceClient` methods."""
    for step in case["steps"]:
        if step.get("dropped"):
            try:
                await _do(client, case, step)
            except (ProtocolViolation, CoreError):
                raise
            except Exception:  # noqa: BLE001 - the connection is gone, as the case says; the client carries on
                continue
            raise ProtocolViolation("dropped", f"{step['do']} completed although the core closed the connection")
        await _do(client, case, step)


async def _do(client: Any, case: dict, step: dict) -> None:
    match step.get("do"):
        case "connect":
            await client.connect()
        case "subscribe":
            await client.subscribe(step["project"])
        case "publish":
            await client.publish(step["command"], step["origin"], step["id"])
        case "request":
            await client.request(step["action"], step["origin"], step["id"])
        case "receive_run":
            await client.receive_run()
        case "receive":
            for _ in range(step["count"]):
                await client.receive()
        case "close":
            await client.close()
        case None:
            pass
        case other:
            raise ValueError(f"unknown step {other!r} in case {case['case']}")


def run_summary(run: Any) -> dict:
    """What `expect.runs` holds of one received run."""
    return {
        "run_id": run.started.run_id,
        "kind": str(run.started.kind),
        "ticks": [f.tick for f in run.frames],
        "last_tick": run.ended.last_tick,
        "end": run.ended.end.reason,
        "events": [[e.tick, e.kind] for f in run.frames for e in f.events],
        "last_frame": run.frames[-1].model_dump(mode="json"),
    }


def check_state(case: dict, client: Any, raised: BaseException | None) -> list[str]:
    """Compare the client's state (or its refusal) with `expect`."""
    expect = case["expect"]
    if "violation" in expect:
        want = f"ProtocolViolation {expect['code']!r} at core message {expect['at_message']}"
        if not isinstance(raised, ProtocolViolation):
            how = f"raised {raised!r}" if raised else "accepted it"
            return [f"the core breaks a rule ({expect['violation']}); the client must raise {want}, it {how}"]
        got = f"ProtocolViolation {raised.code!r} at core message {client.received}"
        return [] if got == want else [f"the core breaks a rule ({expect['violation']}); expected {want}, the client raised {got}: {raised}"]
    if raised is not None:
        return [f"the client raised {raised!r}"]
    problems = []
    for key in ("revision", "epoch"):
        if getattr(client, key) != expect[key]:
            problems.append(f"{key}: expected {expect[key]!r}, the client has {getattr(client, key)!r}")
    if str(client.verdict) != expect["verdict"]:
        problems.append(f"verdict: expected {expect['verdict']}, the client has {client.verdict}")
    if client.project != Project.model_validate(expect["project"]):
        problems.append("project: the client's copy is not the core's document")
    outcomes = {cid: answer.type for cid, answer in client.outcomes.items()}
    if outcomes != expect["outcomes"]:
        problems.append(f"outcomes: expected {expect['outcomes']}, the client has {outcomes}")
    if client.ignored != expect["ignored"]:
        problems.append(f"ignored: expected {expect['ignored']}, the client ignored {client.ignored}")
    runs = [run_summary(r) for r in client.runs]
    for run in runs:
        run["last_frame"] = Frame.model_validate(run["last_frame"])
    want = [{**r, "last_frame": Frame.model_validate(r["last_frame"])} for r in expect["runs"]]
    if runs != want:
        problems.append(f"runs: expected {expect['runs']!r:.300}, the client has {runs!r:.300}")
    return problems


async def run_case(case: dict, make_client: Callable[[str], Any] = ReferenceClient) -> list[str]:
    """Play `case` against a client made by `make_client(url)`; the problems found (none: the client passes)."""
    core = ScriptedCore(case)
    raised: BaseException | None = None
    async with serve(core.handler, "127.0.0.1", 0) as server:
        client = make_client(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        try:
            async with asyncio.timeout(CASE_TIMEOUT_S):
                await drive(client, case)
        except TimeoutError:
            raised = TimeoutError(f"the case did not finish in {CASE_TIMEOUT_S} s")
        except Exception as e:  # noqa: BLE001 - the client's refusal is part of what is checked
            raised = e
        finally:
            await client.close()
        try:
            async with asyncio.timeout(2):
                await core.idle.wait()
        except TimeoutError:
            pass
    problems = list(core.problems)
    if "violation" not in case["expect"] and core.finished < len(core.segments):
        problems.append(f"the client completed {core.finished} of {len(core.segments)} connections of the case")
    return problems + check_state(case, client, raised)


def iter_messages(case: dict) -> Iterator[dict]:
    """Every JSON message of a case, both directions."""
    for step in case["steps"]:
        for key in ("client", "core"):
            if key in step:
                yield step[key]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kinetra_engine.protocol.conformance", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve_cmd = sub.add_parser("serve", help="play the core side of one case for a client in any language")
    serve_cmd.add_argument("case", type=Path)
    serve_cmd.add_argument("--port", type=int, default=0)
    sub.add_parser("list", help="the cases and the rules each one checks")
    args = parser.parse_args(argv)
    if args.command == "list":
        for case in load_cases():
            print(f"{case['case']}\t{','.join(case['rules'])}\t{case['title']}")
        return 0
    case = json.loads(args.case.read_text(encoding="utf-8"))

    async def play() -> list[str]:
        core = ScriptedCore(case)
        async with serve(core.handler, "127.0.0.1", args.port) as server:
            print(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", flush=True)
            while not core.done():
                await asyncio.sleep(0.05)
        if "violation" not in case["expect"] and core.finished < len(core.segments):
            core.problems.append(f"the client completed {core.finished} of {len(core.segments)} connections of the case")
        return core.problems

    problems = asyncio.run(play())
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
