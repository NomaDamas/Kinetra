"""The document owner (C-05a): one project, its history and its revision number, with no transport in it.

`Document` is where `client-adapter.md` rules D1, D2, C1, C3, C5, C6 and D5 live. A transport (`server.py`, or a test)
hands it `Publish` and `Request` messages and gets back what to send: one `Applied` for every subscriber when the
document changed, and one `Accepted` or `Rejected` for whoever sent it. It never touches the network, so the same
object serves WebSocket, the headless reference client (C-05c) and the MCP server (G-08).

Everything that changes the project goes through `kinetra_core.History`, which goes through `apply_command`: a publisher
of any origin gets the same applier and the same checks (C1). Nothing here validates a command itself; the policy
checks of C-02c plug into that applier and arrive here for free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kinetra_core import (
    Accepted,
    Applied,
    Command,
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


@dataclass(frozen=True)
class Outcome:
    """What a `publish` or `request` produced. `applied` is for every subscriber (publisher included) and comes
    before `reply`, which is for the publisher only. `applied` is `None` when the document did not change."""

    reply: Accepted | Rejected
    applied: Applied | None


class Document:
    def __init__(self, project_id: str, project: Project, verdict: VerdictState = VerdictState.NONE):
        self.project_id = project_id
        self._project = project
        self._history = History()
        self._revision = 0
        self._verdict = verdict
        # `Applied` of every revision since the start, so any client can resume (D6). Not capped: nothing in the plan
        # names a number, and the history beside it is not capped either (C-03 decides how this is kept and saved).
        self._log: list[Applied] = []
        # The reply to every command id seen (C6): the same id gets the same reply and is applied once.
        self._replies: dict[str, Accepted | Rejected] = {}

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
            type="snapshot", project_id=self.project_id, revision=self._revision, verdict=self._verdict, project=self._project
        )

    def resume(self, after_revision: int) -> tuple[Resumed, tuple[Applied, ...]] | None:
        """The messages that bring a client holding `after_revision` to now, or `None` when the core cannot continue
        from there (the client is ahead of this document, e.g. the core restarted) and a fresh `snapshot` is due."""
        if after_revision > self._revision:
            return None
        resumed = Resumed(
            type="resumed", project_id=self.project_id, after_revision=after_revision, revision=self._revision
        )
        return resumed, tuple(self._log[after_revision:])

    def publish(self, message: Publish) -> Outcome:
        seen = self._replies.get(message.id)
        if seen is not None:
            return Outcome(reply=seen, applied=None)
        if message.base_revision > self._revision:
            return self._refuse(
                message.id,
                ReasonCode.INVALID_COMMAND,
                f"base_revision {message.base_revision} is ahead of the document (revision {self._revision})",
            )
        # A base revision behind the document is not refused for being old (C5): the command is validated against
        # the current document by the applier and refused there if it no longer applies.
        return self._run(
            message.id,
            "publish",
            message.origin,
            lambda: self._history.execute(self._project, message.command, message.origin),
            lambda result: message.command,
        )

    def request(self, message: Request) -> Outcome:
        seen = self._replies.get(message.id)
        if seen is not None:
            return Outcome(reply=seen, applied=None)
        undo = message.action is RequestAction.UNDO
        return self._run(
            message.id,
            message.action.value,
            message.origin,
            lambda: (self._history.undo if undo else self._history.redo)(self._project),
            # what was applied to the project: the inverse of the entry for an undo, the command for a redo
            lambda result: result.entry.inverse if undo else result.entry.command,
        )

    def _refuse(self, command_id: str, code: ReasonCode, message: str) -> Outcome:
        reply = Rejected(type="rejected", id=command_id, reasons=(Reason(code=code, message=message),))
        self._replies[command_id] = reply
        return Outcome(reply=reply, applied=None)

    def _run(
        self,
        command_id: str,
        cause: str,
        origin: Origin,
        edit: Callable[[], EditResult],
        applied_command: Callable[[EditResult], Command],
    ) -> Outcome:
        try:
            result = edit()
        except CommandRejected as e:
            reply = Rejected(type="rejected", id=command_id, reasons=e.reasons)
            self._replies[command_id] = reply
            return Outcome(reply=reply, applied=None)
        if self._project == result.project:
            # Nothing in the document changed (same planet, same pose, ...): no revision, nothing to broadcast, and the
            # verdict stays what it was (D5).
            reply = Accepted(type="accepted", id=command_id, revision=self._revision)
            self._replies[command_id] = reply
            return Outcome(reply=reply, applied=None)
        changes = changes_between(self._project, result.project)
        self._project, self._history = result.project, result.history
        self._revision += 1
        if self._verdict is VerdictState.VALID:
            self._verdict = VerdictState.INVALID  # D5: the document changed under the verdict
        applied = Applied(
            type="applied",
            revision=self._revision,
            id=command_id,
            cause=cause,
            origin=origin,
            command=applied_command(result),
            changes=changes,
            verdict=self._verdict,
        )
        self._log.append(applied)
        reply = Accepted(type="accepted", id=command_id, revision=self._revision)
        self._replies[command_id] = reply
        return Outcome(reply=reply, applied=applied)


def refuse_unsubscribed(command_id: str) -> Rejected:
    """The answer to a `publish` or `request` from a connection that has not subscribed. Not remembered: the same id
    may be sent again after subscribing."""
    reason = Reason(code=ReasonCode.INVALID_COMMAND, message="subscribe to a project before publishing")
    return Rejected(type="rejected", id=command_id, reasons=(reason,))
