"""WebSocket transport of the document channel (C-05a): one JSON text frame per message, `kinetra_core.protocol`.

`Hub` holds the documents and the subscriptions; `Hub.serve` listens. Every connection has one outbound queue and one
writer task, and a message is put in a queue synchronously at the moment the document changes. So every subscriber
sees the `applied` messages in revision order and the publisher sees `applied` before its `accepted`, however slow
any one connection is (rule D2). The queue is not bounded: a bound would be a number the plan does not give, and a
client that cannot keep up is dropped by the transport's own ping timeout.

Security: a browser lets any web page open a WebSocket to `localhost`, so `serve` requires `allowed_origins` (the
`Origin` header values of the pages that may connect; `None` allows clients that send no header, which is every
non-browser client). There is no authentication: the S1 core is a local process. Accounts and sharing are not here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kinetra_core import (
    PROTOCOL_VERSION,
    ClientMessage,
    Hello,
    Project,
    ProtocolError,
    Publish,
    Reason,
    ReasonCode,
    Rejected,
    Request,
    ServerMessage,
    Subscribe,
)

from .document import Document, Outcome, refuse_unsubscribed

log = logging.getLogger(__name__)
_CLIENT_MESSAGE = TypeAdapter(ClientMessage)
_CLOSE = None  # sentinel: the writer stops after everything queued before it
_PROTOCOL_ERROR_CLOSE = 1002
_INTERNAL_ERROR_CLOSE = 1011


class _Connection:
    def __init__(self, ws: ServerConnection):
        self.ws = ws
        self.queue: asyncio.Queue[ServerMessage | None] = asyncio.Queue()
        self.said_hello = False
        self.document: Document | None = None

    def send(self, message: ServerMessage) -> None:
        self.queue.put_nowait(message)

    async def pump(self) -> None:
        while (message := await self.queue.get()) is not _CLOSE:
            try:
                await self.ws.send(message.model_dump_json())
            except ConnectionClosed:
                return


class Hub:
    """The documents of this core by project id, and who follows each."""

    def __init__(self, projects: Mapping[str, Project]):
        self.documents = {pid: Document(pid, project) for pid, project in projects.items()}
        self._subscribers: dict[str, set[_Connection]] = {pid: set() for pid in self.documents}

    def serve(self, host: str, port: int, *, allowed_origins: Sequence[str | None]):
        """`async with hub.serve(...) as server:`; `port` 0 picks a free one (`server.sockets[0].getsockname()`)."""
        return serve(self._handler, host, port, origins=list(allowed_origins))

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
            conn.send(ProtocolError(type="error", message="internal error", fatal=True))
            close_code = _INTERNAL_ERROR_CLOSE
        finally:
            self._unsubscribe(conn)
            conn.queue.put_nowait(_CLOSE)
            await writer
        await ws.close(close_code)

    # --- one received frame; returns False when the connection must close ------------------------------------

    def _receive(self, conn: _Connection, raw: str | bytes) -> bool:
        if isinstance(raw, bytes):
            return self._fail(conn, "binary frames are not part of the protocol; send JSON text", fatal=False)
        try:
            message = _CLIENT_MESSAGE.validate_json(raw)
        except ValidationError as e:
            return self._unreadable(conn, raw, e)
        if not conn.said_hello and not isinstance(message, Hello):
            return self._fail(conn, "send hello first", fatal=True)
        if isinstance(message, Hello):
            if message.protocol != PROTOCOL_VERSION:
                return self._fail(conn, f"protocol {message.protocol} is not served; this core speaks {PROTOCOL_VERSION}", fatal=True)
            if conn.said_hello:
                return self._fail(conn, "hello was already sent", fatal=False)
            conn.said_hello = True
            conn.send(Hello(type="hello", protocol=PROTOCOL_VERSION))
        elif isinstance(message, Subscribe):
            self._subscribe(conn, message)
        elif isinstance(message, (Publish, Request)):
            self._edit(conn, message)
        return True

    def _fail(self, conn: _Connection, text: str, *, fatal: bool) -> bool:
        conn.send(ProtocolError(type="error", message=text, fatal=fatal))
        return not fatal

    def _unreadable(self, conn: _Connection, raw: str, error: ValidationError) -> bool:
        """A frame that is not a valid client message. A `publish` or `request` that has an id is answered with a
        `rejected` for that id (C3: a command that cannot be read is a refused command, with the reason), anything
        else is an `error`."""
        try:
            data = json.loads(raw)
        except ValueError:
            return self._fail(conn, "the frame is not JSON", fatal=False)
        if isinstance(data, dict) and data.get("type") in ("publish", "request") and isinstance(data.get("id"), str) and data["id"]:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in error.errors(include_url=False, include_context=False, include_input=False)
            )
            reason = Reason(code=ReasonCode.INVALID_COMMAND, message=f"the message is not a valid {data['type']}: {problems}")
            conn.send(Rejected(type="rejected", id=data["id"], reasons=(reason,)))
            return True
        kind = data.get("type") if isinstance(data, dict) else None
        return self._fail(conn, f"not a client message (type {kind!r})", fatal=False)

    def _subscribe(self, conn: _Connection, message: Subscribe) -> None:
        document = self.documents.get(message.project)
        if document is None:
            self._fail(conn, f"no project {message.project!r}", fatal=False)
            return
        self._unsubscribe(conn)
        # Everything below is queued without a pause, and the connection joins the subscribers in the same step, so no
        # `applied` can fall between the snapshot (or the replay) and the first live message.
        resumed = None if message.after_revision is None else document.resume(message.after_revision)
        if resumed is None:
            conn.send(document.snapshot())
        else:
            head, missed = resumed
            conn.send(head)
            for applied in missed:
                conn.send(applied)
        conn.document = document
        self._subscribers[document.project_id].add(conn)

    def _unsubscribe(self, conn: _Connection) -> None:
        if conn.document is not None:
            self._subscribers[conn.document.project_id].discard(conn)
            conn.document = None

    def _edit(self, conn: _Connection, message: Publish | Request) -> None:
        document = conn.document
        if document is None:
            conn.send(refuse_unsubscribed(message.id))
            return
        outcome: Outcome = document.publish(message) if isinstance(message, Publish) else document.request(message)
        if outcome.applied is not None:
            for subscriber in self._subscribers[document.project_id]:
                subscriber.send(outcome.applied)
        conn.send(outcome.reply)
