"""WebSocket transport of the document channel (C-05a): one JSON text frame per message, `kinetra_core.protocol`.

`Hub` holds the documents and the subscriptions; `Hub.serve` listens. Every connection has one outbound queue and one
writer task, and a message is put in a queue synchronously at the moment the document changes. So every subscriber
sees the `applied` messages in revision order and the publisher sees `applied` before its `accepted`, however slow
any one connection is (rule D2).

A subscriber that cannot keep up is dropped, not waited for (D6 brings it back: it reconnects and is resumed or sent a
fresh `snapshot`). A connection is dropped (removed from the subscribers and its socket aborted) when
- its queue holds `QUEUE_MAX_MESSAGES` messages, or `QUEUE_MAX_BYTES` bytes with more than one message in it, or
- one send does not finish in `SEND_TIMEOUT_S` seconds (the peer is not reading).
The library's own keepalive does not do this: with a full write buffer its `ping()` waits for the buffer too, so its
timeout never starts. The limits are engineering choices (value badge: `기본값`), not measurements: constants here so
C-05b, which puts frames on the same connections, can move them with a measured reason.

Anyone who changes a document from inside the process (the agent of G-02, the MCP server of G-08, a test) calls
`Hub.publish`, which applies the message and broadcasts the `applied` to every subscriber, whoever sent it.

A `run` (X-02a) compiles the subscribed document as it is and streams one run to the asking connection only: a
`run_started` text message, one binary message per frame (`encode_frame`, `client-adapter.md` 3.3) and a `run_ended`.
One run at a time per connection, because a binary frame names no run. A frame waits for the connection's queue to be
empty before it is queued, so a slow client slows the run down instead of being dropped by the queue limits; the
trajectory does not depend on it (`kinetra_engine.run.preview`).

Security: a browser lets any web page open a WebSocket to `localhost`, so `serve` requires `allowed_origins` (the
`Origin` header values of the pages that may connect; `None` allows clients that send no header, which is every
non-browser client). `serve` listens on the loopback address only and refuses another `host` unless `allow_remote` is
set. There is no authentication: the S1 core is a local process; accounts and sharing are not here. A headset
browser needs `wss`, so `ssl` is passed through. Incoming messages are at most `MAX_MESSAGE_BYTES`; a longer one closes
the connection with code 1009 (the library refuses it before any of our code sees it, so no `error` message can be sent).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import ssl as ssl_module
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, TypeAdapter, ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kinetra_core import (
    MAX_COMMAND_ID_LENGTH,
    PROTOCOL_VERSION,
    ClientMessage,
    Frame,
    Hello,
    Project,
    ProjectIncomplete,
    ProtocolError,
    Publish,
    Reason,
    ReasonCode,
    Ref,
    RefKind,
    Rejected,
    RunEnded,
    RunFailed,
    Request,
    RunRequest,
    Subscribe,
    encode_frame,
)
from kinetra_core.conventions import ID_PATTERN

from ..compiler import CompileError, CompileErrorCode
from ..run import PreviewRun
from .document import Document, Outcome, refuse_unsubscribed

log = logging.getLogger(__name__)
_CLIENT_MESSAGE = TypeAdapter(ClientMessage)

MAX_MESSAGE_BYTES = 2**20
"""Longest incoming message (bytes). This is the websockets library's own default, written down."""

QUEUE_MAX_MESSAGES = 512
"""Most messages waiting for one connection (above the `LOG_MAX_REVISIONS` of a resume, so a resume fits)."""

QUEUE_MAX_BYTES = 16 * 1024 * 1024
"""Most bytes waiting for one connection, counted when there is already a message waiting (one message, a snapshot
however big, is always accepted into an empty queue)."""

SEND_TIMEOUT_S = 10.0
"""How long one send to a connection may take before the peer is treated as not reading."""

_PROTOCOL_ERROR_CLOSE = 1002
_INTERNAL_ERROR_CLOSE = 1011
_ECHO_LIMIT = 64
_CLOSE = None  # sentinel: the writer stops after everything queued before it


def _dump(message: BaseModel) -> str:
    return message.model_dump_json()


def _echo(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _ECHO_LIMIT else text[: _ECHO_LIMIT - 1] + "…"


class _Connection:
    def __init__(self, ws: ServerConnection):
        self.ws = ws
        self.queue: asyncio.Queue[str | bytes | None] = asyncio.Queue()
        self.pending_bytes = 0
        self.said_hello = False
        self.document: Document | None = None
        self.dropped = False
        self.idle = asyncio.Event()  # set while nothing waits to be sent (a run waits for it before its next frame)
        self.idle.set()
        self.run: asyncio.Task | None = None  # the run streaming on this connection (one at a time: a binary frame has no run id)

    def full(self, size: int) -> bool:
        """Would a message of `size` bytes (UTF-8) not fit?"""
        waiting = self.queue.qsize()
        return waiting >= QUEUE_MAX_MESSAGES or (waiting > 0 and self.pending_bytes + size > QUEUE_MAX_BYTES)

    def enqueue(self, message: str | bytes) -> bool:
        """Queue a serialized message (JSON text, or a binary run frame). `False` (and nothing queued) when the
        connection is full."""
        if self.dropped:
            return True
        size = _size(message)
        if self.full(size):
            return False
        self.pending_bytes += size
        self.idle.clear()
        self.queue.put_nowait(message)
        return True

    def abort(self) -> None:
        self.dropped = True
        self.ws.transport.abort()

    async def pump(self) -> None:
        while (message := await self.queue.get()) is not _CLOSE:
            self.pending_bytes -= _size(message)
            if self.dropped:
                return
            try:
                async with asyncio.timeout(SEND_TIMEOUT_S):
                    await self.ws.send(message)
            except ConnectionClosed:
                return
            except TimeoutError:
                log.warning("document channel: a subscriber is not reading; dropped")
                self.abort()
                return
            if self.queue.empty():
                self.idle.set()


def _size(message: str | bytes) -> int:
    return len(message) if isinstance(message, bytes) else len(message.encode())


def _refuse(request_id: str, code: ReasonCode, text: str, ids: tuple[Ref, ...] = ()) -> Rejected:
    return Rejected(type="rejected", id=request_id, reasons=(Reason(code=code, message=text, ids=ids),))


_COMPILE_REASONS = {CompileErrorCode.SNAP_MISMATCH: ReasonCode.INVALID_SNAP, CompileErrorCode.FLOATING: ReasonCode.FLOATING}
"""The compile errors that are the validator's own rules (`check_placement`, `body-tree.md`) keep the validator's reason
code; every other compile error is `invalid_project`. The `CompileErrorCode` itself leads the sentence (`<code>: ...`)."""


def _compile_refused(request_id: str, error: CompileError) -> Rejected:
    ids = (
        tuple(Ref(kind=RefKind.INSTANCE, id=i) for i in error.instances)
        + tuple(Ref(kind=RefKind.PART, id=p) for p in error.parts)
        + tuple(Ref(kind=RefKind.JOINT, id=j) for j in error.joints)
        + tuple(Ref(kind=RefKind.ACTUATOR, id=a) for a in error.actuators)
    )
    code = _COMPILE_REASONS.get(error.code, ReasonCode.INVALID_PROJECT)
    return _refuse(request_id, code, f"{error.code.value}: the design does not compile: {error}", ids)


class Hub:
    """The documents of this core by project id, and who follows each."""

    def __init__(self, projects: Mapping[str, Project]):
        for pid in projects:
            if not re.fullmatch(ID_PATTERN, pid):
                raise ValueError(f"project id {pid!r} does not match {ID_PATTERN}")
        self.documents = {pid: Document(pid, project) for pid, project in projects.items()}
        self._subscribers: dict[str, set[_Connection]] = {pid: set() for pid in self.documents}

    def serve(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        allowed_origins: Sequence[str | None],
        allow_remote: bool = False,
        ssl: ssl_module.SSLContext | None = None,
        max_size: int = MAX_MESSAGE_BYTES,
    ):
        """`async with hub.serve(...) as server:`; `port` 0 picks a free one (`server.sockets[0].getsockname()`).
        `host` must be a loopback address (or `localhost`) unless `allow_remote` is set: the channel has no
        authentication."""
        if not allow_remote and not _is_loopback(host):
            raise ValueError(
                f"{host!r} is not a loopback address: the document channel has no authentication; pass allow_remote=True to listen there"
            )
        return serve(self._handler, host, port, origins=list(allowed_origins), ssl=ssl, max_size=max_size)

    def publish(self, project_id: str, message: Publish | Request) -> Outcome:
        """Apply `message` to the document and tell every subscriber, the sender's own connection included, about the
        change. The one way into a document from inside the process. Raises `KeyError` for an unknown project."""
        document = self.documents[project_id]
        outcome = document.publish(message) if isinstance(message, Publish) else document.request(message)
        self._broadcast(project_id, outcome)
        return outcome

    def _broadcast(self, project_id: str, outcome: Outcome) -> None:
        if outcome.applied_text is None:
            return
        for subscriber in tuple(self._subscribers[project_id]):  # one serialization, queued for each, no await between
            if not subscriber.enqueue(outcome.applied_text):
                self._drop(subscriber)

    def _drop(self, conn: _Connection) -> None:
        log.warning("document channel: a subscriber cannot keep up; dropped")
        self._unsubscribe(conn)
        conn.abort()

    async def _handler(self, ws: ServerConnection) -> None:
        conn = _Connection(ws)
        writer = asyncio.create_task(conn.pump())
        close_code = 1000
        try:
            async for raw in ws:
                if not self._receive(conn, raw):
                    close_code = _PROTOCOL_ERROR_CLOSE
                    break
        except ConnectionClosed:
            pass
        except Exception:
            log.exception("document channel: internal error")
            self._send(conn, ProtocolError(type="error", message="internal error", fatal=True))
            close_code = _INTERNAL_ERROR_CLOSE
        finally:
            if conn.run is not None:
                conn.run.cancel()  # the stream has nowhere to go; a step already in a worker thread finishes and is dropped
            self._unsubscribe(conn)
            conn.queue.put_nowait(_CLOSE)
            await writer
        await ws.close(close_code)

    def _send(self, conn: _Connection, message: BaseModel) -> None:
        if not conn.enqueue(_dump(message)):
            self._drop(conn)

    # --- one received frame; returns False when the connection must close ------------------------------------

    def _receive(self, conn: _Connection, raw: str | bytes) -> bool:
        if not conn.said_hello:
            return self._receive_hello(conn, raw)
        if isinstance(raw, bytes):
            return self._fail(conn, "binary frames are not part of the protocol; send JSON text", fatal=False)
        try:
            message = _CLIENT_MESSAGE.validate_json(raw)
        except ValidationError as e:
            return self._unreadable(conn, raw, e)
        except RecursionError:
            return self._fail(conn, "the message is nested too deeply", fatal=False)
        if isinstance(message, Hello):
            return self._fail(conn, "hello was already sent", fatal=False)
        if isinstance(message, Subscribe):
            self._subscribe(conn, message)
        elif isinstance(message, (Publish, Request)):
            self._edit(conn, message)
        elif isinstance(message, RunRequest):
            self._start_run(conn, message)
        return True

    def _receive_hello(self, conn: _Connection, raw: str | bytes) -> bool:
        """Before `hello` the only valid frame is a text `hello` for a protocol we speak; anything else is fatal
        (a binary frame included: the protocol is text-only, so it is refused before it is parsed)."""
        if isinstance(raw, bytes):
            return self._fail(conn, "binary frames are not part of the protocol; send JSON text", fatal=True)
        try:
            message = _CLIENT_MESSAGE.validate_json(raw)
        except (ValidationError, RecursionError):
            return self._fail(conn, "send hello first", fatal=True)
        if not isinstance(message, Hello):
            return self._fail(conn, "send hello first", fatal=True)
        if message.protocol != PROTOCOL_VERSION:
            return self._fail(conn, f"protocol {message.protocol} is not served; this core speaks {PROTOCOL_VERSION}", fatal=True)
        conn.said_hello = True
        self._send(conn, Hello(type="hello", protocol=PROTOCOL_VERSION))
        return True

    def _fail(self, conn: _Connection, text: str, *, fatal: bool) -> bool:
        self._send(conn, ProtocolError(type="error", message=text, fatal=fatal))
        return not fatal

    def _unreadable(self, conn: _Connection, raw: str, error: ValidationError) -> bool:
        """A frame that is not a valid client message. A `publish` or `request` that has an id is answered with a
        `rejected` for that id (C3: a command that cannot be read is a refused command, with the reason), and the
        id is remembered like any other command id (C6). A `run` that has an id is refused for that id (nothing to
        remember: a run changes no document). Anything else is an `error`."""
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            return self._fail(conn, "the frame is not JSON", fatal=False)
        kind = data.get("type") if isinstance(data, dict) else None
        command_id = data.get("id") if isinstance(data, dict) else None
        if kind in ("publish", "request", "run") and isinstance(command_id, str) and 0 < len(command_id) <= MAX_COMMAND_ID_LENGTH:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in error.errors(include_url=False, include_context=False, include_input=False)
            )[:1000]
            if kind == "run":
                self._send(conn, _refuse(command_id, ReasonCode.INVALID_COMMAND, f"the message is not a valid run: {problems}"))
                return True
            if conn.document is None:
                self._send(conn, refuse_unsubscribed(command_id))
                return True
            outcome = conn.document.unreadable(command_id, raw, problems, kind)
            self._send(conn, outcome.reply)
            return True
        return self._fail(conn, f"not a client message (type {_echo(kind)})", fatal=False)

    def _subscribe(self, conn: _Connection, message: Subscribe) -> None:
        document = self.documents.get(message.project)
        if document is None:
            self._fail(conn, f"no project {_echo(message.project)}", fatal=False)
            return
        self._unsubscribe(conn)
        # Everything below is queued without a pause, and the connection joins the subscribers in the same step, so no
        # `applied` can fall between the snapshot (or the replay) and the first live message.
        resumed = None
        if message.after_revision is not None:
            resumed = document.resume(message.after_revision, message.epoch)
        if resumed is None:
            self._send(conn, document.snapshot())
        else:
            head, missed = resumed
            self._send(conn, head)
            for text in missed:
                if not conn.enqueue(text):
                    self._drop(conn)
                    return
        if conn.dropped:
            return
        conn.document = document
        self._subscribers[document.project_id].add(conn)

    def _unsubscribe(self, conn: _Connection) -> None:
        if conn.document is not None:
            self._subscribers[conn.document.project_id].discard(conn)
            conn.document = None

    def _edit(self, conn: _Connection, message: Publish | Request) -> None:
        document = conn.document
        if document is None:
            self._send(conn, refuse_unsubscribed(message.id))
            return
        outcome = self.publish(document.project_id, message)
        self._send(conn, outcome.reply)

    # --- runs (X-02a) ----------------------------------------------------------------------------------------

    def _start_run(self, conn: _Connection, message: RunRequest) -> None:
        """Compile and run the subscribed document as it is now, streaming to this connection only (C7: a run changes
        no document, so no other subscriber hears of it)."""
        document = conn.document
        if document is None:
            self._send(conn, _refuse(message.id, ReasonCode.INVALID_COMMAND, "subscribe to a project before asking for a run"))
            return
        if conn.run is not None and not conn.run.done():
            self._send(
                conn,
                _refuse(
                    message.id,
                    ReasonCode.INVALID_COMMAND,
                    "a run is going on on this connection: one run at a time, because a binary frame names no run",
                ),
            )
            return
        conn.run = asyncio.create_task(self._stream_run(conn, document.project_id, document.project, document.revision, message))

    async def _stream_run(self, conn: _Connection, project_id: str, project: Project, revision: int, message: RunRequest) -> None:
        """`run_started`, the frames as binary messages, `run_ended`. The engine steps in a worker thread, one frame's
        ticks at a time, so the event loop keeps serving every connection. Two things may hold a frame back, and
        neither changes it: the `speed` pace (a frame of simulated time `t` goes out no earlier than `t / speed` after
        the start) and the connection (the next frame waits until everything queued before it was sent, so a slow
        client slows the run down instead of piling frames up: `client-adapter.md` 4.1).

        An internal error after `run_started` (making, checking or encoding a frame) still ends the stream: the last
        frame sent becomes the end frame, a `run_ended` `failed` at its tick follows (a whole stream for `check_run`),
        then a non-fatal `error` whose text names the run and not the exception (it is logged here, not sent).
        `run_started` goes out together with the first frame, so a run that fails before it has one opened no stream
        and gets only the `error`. Either way the task ends, which frees the connection's one run slot."""
        open_stream = False
        last_sent: Frame | None = None
        try:
            try:
                run = await asyncio.to_thread(
                    PreviewRun,
                    project,
                    run_id=message.id,
                    project_id=project_id,
                    revision=revision,
                    duration_s=message.duration_s,
                    seed=message.seed,
                )
            except ProjectIncomplete as e:
                self._send(conn, Rejected(type="rejected", id=message.id, reasons=e.reasons))
                return
            except CompileError as e:
                self._send(conn, _compile_refused(message.id, e))
                return
            except ValueError as e:  # a duration longer than a run can count
                self._send(conn, _refuse(message.id, ReasonCode.INVALID_COMMAND, str(e)))
                return
            bodies = [b.id for b in run.started.bodies]
            loop = asyncio.get_running_loop()
            start = loop.time()
            stream = iter(run)
            while (item := await asyncio.to_thread(next, stream, None)) is not None:
                if not isinstance(item, Frame):
                    self._send(conn, item)  # run_ended (after at least one frame: the run always yields one first)
                    open_stream = False  # the stream is whole
                    continue
                if message.speed > 0:
                    delay = start + item.sim_time_s / message.speed - loop.time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                binary = encode_frame(item, bodies)
                await conn.idle.wait()
                if not open_stream:  # announced with its first frame, so a run that cannot make one leaves no open stream
                    self._send(conn, run.started)
                    open_stream = True
                if not conn.enqueue(binary):
                    self._drop(conn)
                    return
                last_sent = item
        except Exception:
            log.exception("run %r: internal error", message.id)
            if open_stream and last_sent is not None:  # a stream is open: close it with its last frame
                self._send(
                    conn,
                    RunEnded(type="run_ended", run_id=message.id, last_tick=last_sent.tick, end=RunFailed(reason="failed")),
                )
            self._send(conn, ProtocolError(type="error", message=f"internal error: the core could not run {message.id!r}", fatal=False))


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
