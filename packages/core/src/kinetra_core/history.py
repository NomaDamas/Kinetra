"""Undo, redo and the edit history (C-02b), built on the pair `apply_command` returns (`commands.py`).

`History` is an immutable value: a list of `HistoryEntry` and a cursor. `History.execute(project, command, origin)`,
`.undo(project)` and `.redo(project)` return an `EditResult(project, history, entry)` and never touch their input,
like `apply_command`. The project and the history belong together: a history is only valid for the project it
has been executing against (the document owner, C-05a, keeps the two as one thing; `client-adapter.md` C1 says
`publish` and undo are the only ways the project changes).

Rules (read by C-05a, B-05b, XR-02d, the agent proposals of G-02):

- **One entry is one `Command`.** A single edit is one entry; a `CommandBatch` is one entry however many edits it
  holds, so undo takes the whole batch back and redo does it again (`client-adapter.md` C2, I4: one entry is one
  confirmed user action). A gizmo drop that moves an assembly, a radial copy, an accepted agent proposal are one
  batch each. The sender groups; there is no separate "group" call and no way to merge two entries afterwards.
- **The origin is in the record, not in the command.** `HistoryEntry.origin` is one of `Origin` (mouse, agent,
  voice, xr, mcp; `client-adapter.md` 3.5). It says which input path sent the command and nothing else: the same
  command from any origin is the same edit and goes through the same applier and the same checks (I1, C1). The
  history does not decide what an origin may do (C-02c) and does not trust it for anything. An undo or a redo is
  not a new entry and keeps the origin of the entry it replays.
- **An entry is the command as sent and the inverse the applier computed for it**, so undo applies the stored
  inverse and redo applies the stored command. Both are applied to exactly the state they were computed against
  (a linear history), which is why they apply: the inverse restores an equal project, order of every collection
  included (C-02a).
- **A command that changes nothing leaves no entry.** If the applied project equals the input (same planet, same
  pose, same material, a batch that moves a part away and back), the command is accepted, the history is returned
  as it was (an entry would be an undo step that does nothing, and it would cut off the redo tail) and
  `EditResult.entry` is `None`. C-05a uses `entry is None` to keep the verdict valid and to skip a revision
  (`client-adapter.md` D5): nothing in the document changed.
- **A new edit cuts the redo tail.** After `undo`, `execute` with a command that changes something drops the undone
  entries, as every editor does; they would not apply to the new state.
- **A rejected command changes nothing**: `CommandRejected` is raised with the project and the history untouched.
  `undo` with nothing to undo and `redo` with nothing to redo raise it too (`nothing_to_undo`,
  `nothing_to_redo`), so the request path of 3.2 answers both with the same `rejected` message.
- The history has no size cap: nothing in the plan or the issues names a number, and a number here would be
  invented. It holds two commands per entry; a cap (or saving it with the project) is a decision for C-03 and C-05a
  when they have to keep it.

Not here: revision numbers and the `applied` message (C-05a), the saved form of a history and its hash (C-03),
the per-user undo of several editors (N-04; stored inverses carry absolute positions, see `project-model.md`),
what an origin may send (C-02c), timestamps (wall-clock time has no place in a deterministic document).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .commands import Command, CommandRejected, Reason, ReasonCode, apply_command
from .project import Project
from .validator import validate_command


class Origin(StrEnum):
    """Which input path sent a command (`client-adapter.md` 3.5): the person's mouse or keyboard, the agent's
    accepted proposal, a confirmed voice sentence, an XR hand or controller, the MCP server."""

    MOUSE = "mouse"
    AGENT = "agent"
    VOICE = "voice"
    XR = "xr"
    MCP = "mcp"


class HistoryEntry(BaseModel):
    """One undo step: `command` as it was applied, its `inverse`, and the `origin` it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    origin: Origin
    command: Command
    inverse: Command


class History(BaseModel):
    """`entries[:cursor]` are applied, `entries[cursor:]` were undone and can be redone."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[HistoryEntry, ...] = ()
    cursor: int = Field(default=0, strict=True, ge=0)

    @model_validator(mode="after")
    def _cursor_is_inside(self) -> History:
        if self.cursor > len(self.entries):
            raise ValueError(f"cursor {self.cursor} is past the last of {len(self.entries)} entries")
        return self

    @property
    def can_undo(self) -> bool:
        return self.cursor > 0

    @property
    def can_redo(self) -> bool:
        return self.cursor < len(self.entries)

    def execute(self, project: Project, command: Command, origin: Origin) -> EditResult:
        """Apply `command` from `origin` through the validator (`validate_command`, C-02c: structure, policy and
        placement). Raises `CommandRejected` (project and history unchanged) when it refuses. `undo` and `redo` go back
        to states that were accepted and use `apply_command` only (`project-model.md`, "검증기")."""
        applied = validate_command(project, command)
        if applied.project == project:
            return EditResult(project=project, history=self, entry=None)
        entry = HistoryEntry(origin=origin, command=command, inverse=applied.inverse)
        history = History(entries=self.entries[: self.cursor] + (entry,), cursor=self.cursor + 1)
        return EditResult(project=applied.project, history=history, entry=entry)

    def undo(self, project: Project) -> EditResult:
        """Take back the last applied entry whole (a batch is one step)."""
        if not self.can_undo:
            raise _nothing(ReasonCode.NOTHING_TO_UNDO, "There is nothing to undo.")
        entry = self.entries[self.cursor - 1]
        undone = apply_command(project, entry.inverse)
        return EditResult(project=undone.project, history=History(entries=self.entries, cursor=self.cursor - 1), entry=entry)

    def redo(self, project: Project) -> EditResult:
        """Do the last undone entry again."""
        if not self.can_redo:
            raise _nothing(ReasonCode.NOTHING_TO_REDO, "There is nothing to redo.")
        entry = self.entries[self.cursor]
        redone = apply_command(project, entry.command)
        return EditResult(project=redone.project, history=History(entries=self.entries, cursor=self.cursor + 1), entry=entry)


class EditResult(BaseModel):
    """What `execute`, `undo` and `redo` return. `entry` is the entry that was added (`execute`), taken back
    (`undo`) or replayed (`redo`); it is `None` only when `execute` was given a command that changes nothing, in
    which case `project` equals the input and `history` is the input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project: Project
    history: History
    entry: HistoryEntry | None


def _nothing(code: ReasonCode, message: str) -> CommandRejected:
    return CommandRejected((Reason(code=code, message=message),))
