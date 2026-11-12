"""The headless reference client (C-05c; `client-adapter.md` 3.1-3.3 and "적합성").

A second client of the boundary, with no web code and no core code: it speaks only the protocol. It imports the message
models of `kinetra_core` (the same models `export_schemas.py` turns into the JSON Schema every other client reads) and a
WebSocket library, nothing of `kinetra_engine` (a test checks the imports). What it does is what any client must do:

- open with `hello`, `subscribe` to a project, keep a read-only copy that changes only by `snapshot` and `applied`
  (D1, D3: `apply_changes`, never the command applier), and on a reconnect send the last revision and `epoch` it holds
  so the core can resume it (D6);
- `publish` a command or `request` an undo/redo and wait for its `accepted` or `rejected`;
- receive a run stream (`run_started`, `frame` as JSON or binary, `run_ended`) and check it (`check_frame` on every
  frame, `check_run` at the end: the end frame rule of 3.3);
- ignore a message whose `type` it does not know (G5), and ignore unknown fields of the messages it knows.

It also checks the ordering rules the core promises, and raises `ProtocolViolation` when the core breaks one: an
`applied` that is not the next revision, an `accepted` before its `applied`, a `resumed` that does not continue what
the client holds, a run stream that `check_run` refuses. A client that silently papers over these would hide a core bug.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, get_args

from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.client import ClientConnection, connect

from kinetra_core import (
    PROTOCOL_VERSION,
    Accepted,
    Applied,
    Frame,
    FrameDecodeError,
    Hello,
    Origin,
    Project,
    ProtocolError,
    Rejected,
    RequestAction,
    Resumed,
    RunEnded,
    RunStarted,
    ServerMessage,
    Snapshot,
    VerdictState,
    apply_changes,
    check_frame,
    check_run,
    decode_frame,
)

_SERVER = TypeAdapter(ServerMessage)
KNOWN_TYPES = frozenset(
    get_args(model.model_fields["type"].annotation)[0] for model in get_args(get_args(ServerMessage)[0])
)
"""The `type` tags of `ServerMessage`. A text message with another `type` is ignored (G5)."""


class ProtocolViolation(Exception):
    """The core sent something a conforming core never sends. `code` names the rule (the conformance cases expect a
    code at a message): `revision_gap` (an `applied` that is not the next revision, D2), `accepted_before_applied`
    (D2), `resume_mismatch` (a `resumed` that does not continue what the client holds, D6), `replay_incomplete`
    (another message before the `applied` owed after `resumed`), `run_stream` (`check_run` refuses the stream, 3.3),
    `frame` (a frame that is not a frame of its run), `binary_frame` (does not decode), `run_overlap` (a run starts
    before the previous one ended), `no_run` (a run message with no run going on), `schema` (a known `type` that does
    not match its schema), `not_json`, `handshake` (no or a second `hello`), `snapshot_project` (a snapshot of another
    project)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class CoreError(Exception):
    """The core answered with an `error` (the connection broke the protocol, or the project is unknown)."""

    def __init__(self, error: ProtocolError):
        super().__init__(error.message)
        self.error = error


@dataclass
class RunRecord:
    """A run as the client received it. `ended` is `None` while the run is going on."""

    started: RunStarted
    frames: list[Frame] = field(default_factory=list)
    ended: RunEnded | None = None


class ReferenceClient:
    """One client: its copy of one project, which survives reconnects (that is what makes a resume possible)."""

    def __init__(self, url: str, *, open_timeout_s: float = 10.0):
        self.url = url
        self.open_timeout_s = open_timeout_s
        self.ws: ClientConnection | None = None
        self.project_id: str | None = None
        self.project: Project | None = None
        self.revision: int | None = None
        self.epoch: str | None = None
        self.verdict: VerdictState | None = None
        self.outcomes: dict[str, Accepted | Rejected] = {}
        self.ignored: list[str] = []  # the unknown `type`s received, in order
        self.errors: list[ProtocolError] = []  # non-fatal `error`s
        self.runs: list[RunRecord] = []  # runs whose stream this client received from `run_started` on
        self.interrupted_runs: list[RunRecord] = []  # runs whose connection closed before their `run_ended`
        self.received = 0  # messages received from the core, all connections (the conformance cases count them)
        self._replay = 0  # `applied` still owed after a `resumed`
        self._delivered_runs = 0  # runs already returned by `receive_run`
        self._greeted = False  # the core's hello of this connection came

    # --- connection --------------------------------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the socket and exchange `hello` (G5). The copy of the project (revision, epoch) is kept from an earlier
        connection; what belonged to the old connection is not: a replay owed after a `resumed` (the new `subscribe`
        asks again from the revision actually reached) and a run whose stream was cut (its frames are gone with the
        connection; it moves to `interrupted_runs`)."""
        self._replay = 0
        if self.runs and self.runs[-1].ended is None:
            self.interrupted_runs.append(self.runs.pop())
        self.ws = await connect(self.url, open_timeout=self.open_timeout_s)
        self._greeted = False
        await self._send({"type": "hello", "protocol": PROTOCOL_VERSION})
        message = await self._next()
        if not isinstance(message, Hello) or message.protocol != PROTOCOL_VERSION:
            raise ProtocolViolation("handshake", f"the core answered hello with {message!r}")

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def subscribe(self, project_id: str) -> str:
        """Follow `project_id`. When the client holds a revision of it from an earlier connection, it asks to resume
        (D6). Returns `"snapshot"` or `"resumed"`; on return the copy is at the core's revision as of the reply."""
        message: dict[str, Any] = {"type": "subscribe", "project": project_id}
        if project_id == self.project_id and self.revision is not None:
            message |= {"after_revision": self.revision, "epoch": self.epoch}
        else:
            self.project_id, self.project, self.revision, self.epoch, self.verdict = project_id, None, None, None, None
        await self._send(message)
        while True:
            reply = await self._next()
            if isinstance(reply, Snapshot):
                return "snapshot"
            if isinstance(reply, Resumed):
                while self._replay:
                    await self._next()
                return "resumed"

    # --- edits -------------------------------------------------------------------------------------------------

    async def publish(self, command: Any, origin: Origin | str, command_id: str | None = None) -> Accepted | Rejected:
        """Publish `command` (a `Command` or its JSON form) against the revision the client holds; wait for its
        answer. The `applied` it caused, if any, has been applied to the copy when this returns."""
        cid = command_id or str(uuid.uuid4())
        body = command.model_dump(mode="json") if hasattr(command, "model_dump") else command
        await self._send(
            {"type": "publish", "id": cid, "base_revision": self.revision, "command": body, "origin": str(origin)}
        )
        return await self._answer(cid)

    async def request(self, action: RequestAction | str, origin: Origin | str, request_id: str | None = None):
        """Ask for an undo or a redo; wait for its answer, like `publish`."""
        rid = request_id or str(uuid.uuid4())
        await self._send({"type": "request", "id": rid, "action": str(action), "origin": str(origin)})
        return await self._answer(rid)

    async def _answer(self, cid: str) -> Accepted | Rejected:
        self.outcomes.pop(cid, None)
        while cid not in self.outcomes:
            await self._next()
        return self.outcomes[cid]

    # --- run stream --------------------------------------------------------------------------------------------

    async def receive_run(self) -> RunRecord:
        """Receive until the next run ends; the run has passed `check_run`."""
        while self._delivered_runs == sum(1 for r in self.runs if r.ended is not None):
            await self._next()
        self._delivered_runs += 1
        return self.runs[self._delivered_runs - 1]

    async def receive(self) -> None:
        """Receive and handle one message (for a client that only follows the document)."""
        await self._next()

    # --- receiving ---------------------------------------------------------------------------------------------

    async def _send(self, message: dict) -> None:
        assert self.ws is not None, "connect() first"
        await self.ws.send(json.dumps(message))

    async def _next(self):
        """Receive one message, apply it to the client's state and return it (`None` for an ignored one)."""
        assert self.ws is not None, "connect() first"
        raw = await self.ws.recv()
        self.received += 1
        if isinstance(raw, bytes):
            return self._binary_frame(raw)
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise ProtocolViolation("not_json", f"a text message that is not JSON: {e}") from e
        kind = data.get("type") if isinstance(data, dict) else None
        if not isinstance(kind, str):
            raise ProtocolViolation("schema", "a message without a string `type`")
        if kind not in KNOWN_TYPES:
            self.ignored.append(kind)  # G5: a message added after this client was written
            return None
        try:
            message = _SERVER.validate_python(data)
        except ValidationError as e:
            raise ProtocolViolation("schema", f"a {kind} message that does not match its schema: {e}") from e
        self._handle(message)
        return message

    def _handle(self, message) -> None:
        if self._replay and not isinstance(message, Applied):
            raise ProtocolViolation("replay_incomplete", f"{message.type} arrived before the {self._replay} applied owed after resumed")
        match message:
            case ProtocolError(fatal=True):
                raise CoreError(message)
            case ProtocolError():
                self.errors.append(message)
                raise CoreError(message)
            case Snapshot():
                if message.project_id != self.project_id:
                    raise ProtocolViolation("snapshot_project", f"snapshot of {message.project_id!r}, subscribed to {self.project_id!r}")
                self.project, self.revision, self.epoch, self.verdict = (
                    message.project,
                    message.revision,
                    message.epoch,
                    message.verdict,
                )
            case Resumed():
                if message.project_id != self.project_id or message.epoch != self.epoch:
                    raise ProtocolViolation("resume_mismatch", "resumed names another project or another epoch than the client holds")
                if message.after_revision != self.revision or message.revision < message.after_revision:
                    raise ProtocolViolation("resume_mismatch", f"resumed after {message.after_revision}, the client holds {self.revision}")
                self._replay = message.revision - message.after_revision
            case Applied():
                if self.project is None or message.revision != self.revision + 1:
                    raise ProtocolViolation("revision_gap", f"applied revision {message.revision} after revision {self.revision}")
                self.project = apply_changes(self.project, message.changes)
                self.revision, self.verdict = message.revision, message.verdict
                self._replay = max(0, self._replay - 1)
            case Accepted():
                if message.revision != self.revision:
                    raise ProtocolViolation(
                        "accepted_before_applied",
                        f"accepted {message.id!r} at revision {message.revision}, the client holds {self.revision}"
                        " (the applied of an edit comes before its accepted)"
                    )
                self.outcomes[message.id] = message
            case Rejected():
                self.outcomes[message.id] = message
            case Hello():
                if self._greeted:
                    raise ProtocolViolation("handshake", "a second hello")
                self._greeted = True
            case RunStarted():
                if self.runs and self.runs[-1].ended is None:
                    raise ProtocolViolation("run_overlap", f"run {message.run_id!r} started before run {self.runs[-1].started.run_id!r} ended")
                self.runs.append(RunRecord(message))
            case Frame():
                self._frame(message)
            case RunEnded():
                run = self._live_run(message.run_id)
                try:
                    check_run(run.started, run.frames, message)
                except ValueError as e:
                    raise ProtocolViolation("run_stream", f"the run stream breaks 3.3: {e}") from e
                run.ended = message

    def _live_run(self, run_id: str | None = None) -> RunRecord:
        if not self.runs or self.runs[-1].ended is not None:
            raise ProtocolViolation("no_run", "a run stream message with no run going on")
        run = self.runs[-1]
        if run_id is not None and run_id != run.started.run_id:
            raise ProtocolViolation("no_run", f"a message of run {run_id!r}, the run going on is {run.started.run_id!r}")
        return run

    def _frame(self, frame: Frame) -> Frame:
        run = self._live_run(frame.run_id)
        try:
            # every frame may be the last one; the grid of all but the last is checked by check_run at the end
            check_frame(run.started, frame, final=True)
        except ValueError as e:
            raise ProtocolViolation("frame", f"a frame that is not a frame of its run: {e}") from e
        run.frames.append(frame)
        return frame

    def _binary_frame(self, data: bytes) -> Frame:
        run = self._live_run()  # a binary frame belongs to the latest run_started of the connection
        try:
            frame = decode_frame(data, run.started.run_id, [b.id for b in run.started.bodies])
        except FrameDecodeError as e:
            raise ProtocolViolation("binary_frame", f"a binary frame that does not decode: {e}") from e
        return self._frame(frame)
