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
    Hello,
    Project,
    ProtocolError,
    Publish,
    Request,
    Subscribe,
)
from kinetra_core.conventions import ID_PATTERN

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
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.pending_bytes = 0
        self.said_hello = False
        self.document: Document | None = None
        self.dropped = False

    def full(self, size: int) -> bool:
        waiting = self.queue.qsize()
        return waiting >= QUEUE_MAX_MESSAGES or (waiting > 0 and self.pending_bytes + size > QUEUE_MAX_BYTES)

    def enqueue(self, text: str) -> bool:
        """Queue a serialized message. `False` (and nothing queued) when the connection is full."""
        if self.dropped:
            return True
        if self.full(len(text)):
            return False
        self.pending_bytes += len(text)
        self.queue.put_nowait(text)
        return True

    def abort(self) -> None:
        self.dropped = True
        self.ws.transport.abort()

    async def pump(self) -> None:
        while (text := await self.queue.get()) is not _CLOSE:
            self.pending_bytes -= len(text)
            if self.dropped:
                return
            try:
                async with asyncio.timeout(SEND_TIMEOUT_S):
                    await self.ws.send(text)
            except ConnectionClosed:
                return
            except TimeoutError:
                log.warning("document channel: a subscriber is not reading; dropped")
                self.abort()
                return


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
        return True

    def _receive_hello(self, conn: _Connection, raw: str | bytes) -> bool:
        """Before `hello` the only valid frame is a `hello` for a protocol we speak; anything else is fatal."""
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
        id is remembered like any other command id (C6). Anything else is an `error`."""
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            return self._fail(conn, "the frame is not JSON", fatal=False)
        kind = data.get("type") if isinstance(data, dict) else None
        command_id = data.get("id") if isinstance(data, dict) else None
        if kind in ("publish", "request") and isinstance(command_id, str) and 0 < len(command_id) <= MAX_COMMAND_ID_LENGTH:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in error.errors(include_url=False, include_context=False, include_input=False)
            )
            if conn.document is None:
                self._send(conn, refuse_unsubscribed(command_id))
                return True
            outcome = conn.document.unreadable(command_id, raw, problems[:1000], kind)
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


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
