"""The document owner (C-05a): one project, its history and its revision number, with no transport in it.

`Document` is where `client-adapter.md` rules D1, D2, C1, C3, C5, C6 and D5 live. A transport (`server.py`, or a test)
hands it `Publish` and `Request` messages and gets back what to send: one `Applied` for every subscriber when the
document changed, and one `Accepted` or `Rejected` for whoever sent it. It never touches the network. Broadcasting to
subscribers is the `Hub`'s (`Hub.publish`), and a publisher inside the process (the agent, G-02; the MCP server,
G-08) must go through the `Hub`, not through a `Document` of its own, or the subscribers do not hear of the change.

Everything that changes the project goes through `kinetra_core.History`, which goes through `apply_command`: a publisher
of any origin gets the same applier and the same checks (C1). Nothing here validates a command itself; the policy
checks of C-02c plug into that applier and arrive here for free.

Two things are bounded, because a document stays open as long as the app does and an `Applied` carries whole changed
sections (the one measured in the #505 review: 76 KB for a 277 B command in a 207-instance project):

- the log of past `Applied` messages, for resuming a reconnecting client (D6): the newest `LOG_MAX_REVISIONS`
  revisions within `LOG_MAX_BYTES`. A client that missed more than that, or whose replay would be as big as a fresh
  `snapshot`, gets the `snapshot` (D6 allows exactly this).
- the memory of command ids, for answering a resend (C6): the newest `REMEMBERED_COMMANDS_MAX` ids.

Both limits are engineering choices, not measurements of any user (value badge: `기본값`, chosen here); they are
module constants so C-03 and the client leaves can move them with a measured reason.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Callable

from kinetra_core import (
    Accepted,
    Applied,
    CommandRejected,
    EditResult,
    History,
    Origin,
    Project,
    Publish,
    Reason,
    ReasonCode,
    Rejected,
    Request,
    RequestAction,
    Resumed,
    Snapshot,
    VerdictState,
    changes_between,
)

LOG_MAX_REVISIONS = 256
"""Most past `Applied` messages kept for resuming."""

LOG_MAX_BYTES = 8 * 1024 * 1024
"""Most bytes (JSON text) of past `Applied` messages kept for resuming."""

REMEMBERED_COMMANDS_MAX = 4096
"""Most recent command ids whose answer is remembered (C6). A resend of an older id is not recognised."""


@dataclass(frozen=True)
class Outcome:
    """What a `publish` or `request` produced. `applied` is for every subscriber (publisher included) and comes
    before `reply`, which is for the publisher only. `applied` is `None` when the document did not change.
    `applied_text` is `applied` serialized once, the text every subscriber is sent."""

    reply: Accepted | Rejected
    applied: Applied | None = None
    applied_text: str | None = None


def _fingerprint(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class Document:
    def __init__(self, project_id: str, project: Project, verdict: VerdictState = VerdictState.NONE):
        self.project_id = project_id
        # One life of this document: a client may only resume against the life it learned its revision from. A core
        # that restarts, or a document opened again, has a new one, because the same revision numbers can then mean a
        # different history.
        self.epoch = uuid.uuid4().hex
        self._project = project
        self._history = History()
        self._revision = 0
        self._verdict = verdict
        self._log: deque[tuple[int, str]] = deque()  # (revision, JSON text of its `Applied`), consecutive
        self._log_bytes = 0
        self._replies: dict[str, tuple[bytes, Accepted | Rejected]] = {}  # command id -> (content, answer), oldest first

    @property
    def project(self) -> Project:
        return self._project

    @property
    def history(self) -> History:
        return self._history

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def verdict(self) -> VerdictState:
        return self._verdict

    def snapshot(self) -> Snapshot:
        return Snapshot(
            type="snapshot",
            project_id=self.project_id,
            epoch=self.epoch,
            revision=self._revision,
            verdict=self._verdict,
            project=self._project,
        )

    def resume(self, after_revision: int, epoch: str | None) -> tuple[Resumed, tuple[str, ...]] | None:
        """The messages that bring a client holding `after_revision` of `epoch` to now: the `Resumed` and the JSON
        text of every missed `Applied`. `None` when the core cannot, or should not, continue from there and a fresh
        `snapshot` is due: no or another `epoch`, a client ahead of the document, a gap (the log no longer reaches back
        that far), or a replay at least as big as the snapshot."""
        if epoch != self.epoch or after_revision > self._revision:
            return None
        missed = ()
        if after_revision < self._revision:
            if not self._log or self._log[0][0] > after_revision + 1:
                return None
            missed = tuple(text for revision, text in self._log if revision > after_revision)
            if sum(len(t.encode()) for t in missed) >= len(self.snapshot().model_dump_json().encode()):
                return None
        resumed = Resumed(
            type="resumed", project_id=self.project_id, epoch=self.epoch, after_revision=after_revision, revision=self._revision
        )
        return resumed, missed

    # --- commands ------------------------------------------------------------------------------------------

    def publish(self, message: Publish) -> Outcome:
        seen = self._seen(message.id, message.model_dump_json())
        if seen is not None:
            return seen
        if message.base_revision > self._revision:
            return self._answer(
                message.id,
                message.model_dump_json(),
                Rejected(
                    type="rejected",
                    id=message.id,
                    reasons=(
                        Reason(
                            code=ReasonCode.INVALID_COMMAND,
                            message=f"base_revision {message.base_revision} is ahead of the document (revision {self._revision})",
                        ),
                    ),
                ),
            )
        # A base revision behind the document is not refused for being old (C5): the command is validated against
        # the current document by the applier and refused there if it no longer applies.
        return self._run(
            message.id,
            message.model_dump_json(),
            "publish",
            message.origin,
            lambda: self._history.execute(self._project, message.command, message.origin),
            lambda result: message.command,
        )

    def request(self, message: Request) -> Outcome:
        seen = self._seen(message.id, message.model_dump_json())
        if seen is not None:
            return seen
        match message.action:
            case RequestAction.UNDO:
                edit = lambda: self._history.undo(self._project)  # noqa: E731
                applied_command = lambda result: result.entry.inverse  # noqa: E731  (the inverse is what was applied)
            case RequestAction.REDO:
                edit = lambda: self._history.redo(self._project)  # noqa: E731
                applied_command = lambda result: result.entry.command  # noqa: E731
            case _:  # an action added to the enum before it is handled here: refused, nothing changes
                return self._answer(
                    message.id,
                    message.model_dump_json(),
                    self._rejected(message.id, ReasonCode.INVALID_COMMAND, f"the core does not do {str(message.action)!r} yet"),
                )
        return self._run(message.id, message.model_dump_json(), str(message.action), message.origin, edit, applied_command)

    def unreadable(self, command_id: str, raw: str, problems: str, kind: str) -> Outcome:
        """A `publish` or `request` that has an id but cannot be read: refused with the reason, and the id is
        remembered like any other (C6), so it cannot later be reused for a different command."""
        seen = self._seen(command_id, raw)
        if seen is not None:
            return seen
        return self._answer(
            command_id,
            raw,
            self._rejected(command_id, ReasonCode.INVALID_COMMAND, f"the message is not a valid {kind}: {problems}"),
        )

    # --- internals -----------------------------------------------------------------------------------------

    @staticmethod
    def _rejected(command_id: str, code: ReasonCode, text: str) -> Rejected:
        return Rejected(type="rejected", id=command_id, reasons=(Reason(code=code, message=text),))

    def _seen(self, command_id: str, content: str) -> Outcome | None:
        """The remembered answer to this command id, if there is one. The same id with other content is not the same
        command: it is refused (and the first answer stays), so the publisher never believes an edit happened that
        did not."""
        known = self._replies.get(command_id)
        if known is None:
            return None
        fingerprint, reply = known
        if fingerprint == _fingerprint(content):
            return Outcome(reply=reply)
        return Outcome(
            reply=self._rejected(
                command_id, ReasonCode.INVALID_COMMAND, f"command id {command_id!r} was already used for a different command"
            )
        )

    def _answer(self, command_id: str, content: str, reply: Accepted | Rejected) -> Outcome:
        self._replies[command_id] = (_fingerprint(content), reply)
        while len(self._replies) > REMEMBERED_COMMANDS_MAX:
            del self._replies[next(iter(self._replies))]
        return Outcome(reply=reply)

    def _run(
        self,
        command_id: str,
        content: str,
        cause: str,
        origin: Origin,
        edit: Callable[[], EditResult],
        applied_command: Callable[[EditResult], object],
    ) -> Outcome:
        try:
            result = edit()
        except CommandRejected as e:
            return self._answer(command_id, content, Rejected(type="rejected", id=command_id, reasons=e.reasons))
        if self._project == result.project:
            # Nothing in the document changed (same planet, same pose, ...): no revision, nothing to broadcast, and the
            # verdict stays what it was (D5).
            return self._answer(command_id, content, Accepted(type="accepted", id=command_id, revision=self._revision))
        revision = self._revision + 1
        verdict = VerdictState.INVALID if self._verdict is VerdictState.VALID else self._verdict  # D5
        # Everything that can fail is built before anything is changed: a failure leaves the document as it was.
        applied = Applied(
            type="applied",
            revision=revision,
            id=command_id,
            cause=cause,
            origin=origin,
            command=applied_command(result),
            changes=changes_between(self._project, result.project),
            verdict=verdict,
        )
        text = applied.model_dump_json()
        reply = Accepted(type="accepted", id=command_id, revision=revision)
        self._project, self._history, self._revision, self._verdict = result.project, result.history, revision, verdict
        self._remember(revision, text)
        outcome = self._answer(command_id, content, reply)
        return Outcome(reply=outcome.reply, applied=applied, applied_text=text)

    def _remember(self, revision: int, text: str) -> None:
        """Keep `text` (the JSON of the `Applied` of `revision`) for resuming, within the bounds. A revision that is
        alone bigger than `LOG_MAX_BYTES` is not kept, and the log is emptied, because a log with a hole in it cannot
        be replayed: `resume` then answers a snapshot to anyone who needs that revision."""
        size = len(text.encode())
        if size > LOG_MAX_BYTES:
            self._log.clear()
            self._log_bytes = 0
            return
        self._log.append((revision, text))
        self._log_bytes += size
        while len(self._log) > LOG_MAX_REVISIONS or self._log_bytes > LOG_MAX_BYTES:
            self._log_bytes -= len(self._log.popleft()[1].encode())


def refuse_unsubscribed(command_id: str) -> Rejected:
    """The answer to a `publish` or `request` from a connection that has not subscribed. Not remembered: the same id
    may be sent again after subscribing."""
    reason = Reason(code=ReasonCode.INVALID_COMMAND, message="subscribe to a project before publishing")
    return Rejected(type="rejected", id=command_id, reasons=(reason,))
