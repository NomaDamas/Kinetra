"""The wire messages of the document subscription and the command channel (C-05a; `client-adapter.md` 3.1, 3.2).

These are the *content* of the contract (rule G1: transport-neutral). The S1 transport is WebSocket, one JSON text
frame per message (`kinetra_engine.protocol`); a shared-link page or a headless client reads the same JSON. The models
live in `kinetra_core` so `export_schemas.py` turns them into JSON Schema and TypeScript types like everything else a
client sees.

Messages carry a literal `type` tag (required, so a union of them is a discriminated union; see the exporter's check).
Client to core: `hello`, `subscribe`, `publish`, `request`. Core to client: `hello`, `snapshot`, `resumed`, `applied`,
`accepted`, `rejected`, `error`, and the run stream `run_started`, `frame`, `run_ended` (`frames.py`, C-05b). `ClientMessage` and `ServerMessage` are the two unions.

Rules (read by C-05b, C-05c, B-05, B-05a, G-08):

- **Version (G5).** Both sides open with `hello` and the protocol number. Messages ignore fields they do not know, so an
  optional field can be added without a new number; a new required field, or a changed meaning, raises
  `PROTOCOL_VERSION`. (A `Command` inside a message is the opposite: it is strict and an unknown field refuses the
  whole command, because silently dropping a part of an edit is worse than refusing it.)
- **The document is the core's.** A client's copy changes only by `snapshot` and `applied` (D1). `applied` carries the
  command and what it changed, as whole replaced sections of the project (`ProjectChanges`): the client never runs the
  command applier (D3). `apply_changes` is the one line a client needs; it validates the result as a `Project`.
- **One revision number, kept by the core (D2).** It starts at 0 and goes up by one for every `applied`. A command that
  changes nothing (same planet, same pose; `History.execute` returns no entry) is `accepted` at the unchanged
  revision and nothing is broadcast: the document did not change, so the verdict stays valid (D5).
- **Who and why.** `Applied.origin` is the origin of whoever caused the change, `Applied.id` the command id (or request
  id) that caused it and `Applied.cause` how: a `publish`, or an `undo` / `redo` request (C1: those are the only ways
  the project changes). For an undo the `command` is the inverse that was applied, for a redo the command that was
  re-applied, so the `command` is always what was applied to the project.
- **Command ids (C6).** The publisher picks the id of a `publish` or `request`; a random UUID is the intended form. The
  core answers the same id twice with the same `accepted` or `rejected` and applies it once. Ids are unique per
  document, not per client.
- **Stale commands (C5).** `base_revision` is the revision the publisher had seen. Older than the document: the command
  is validated against the current document and refused if it does not apply; there is no merge in S1. Ahead of the
  document: refused (`invalid_command`).
- **Rejections (C3).** `rejected` always carries reasons: the `Reason` of C-02a (code, sentence, typed refs). A message
  the core cannot even read as a `publish` with an id is a connection-level `error`, not a `rejected`.
- **Resuming (D6).** `subscribe.after_revision` and `subscribe.epoch` are the last revision the client has and the
  `epoch` of the `snapshot` or `resumed` it got it from. The `epoch` names one life of one document: a random value the
  core picks when it opens the document, so a core that was restarted (and may have a different history under the same
  revision numbers) has another one. Only when the `epoch` matches and the core still holds every `applied` after
  `after_revision` (it keeps a bounded number: `kinetra_engine.protocol.document`), and replaying them is smaller than a
  snapshot, does it answer `resumed` and then the missed `applied` in order. In every other case, a first
  subscription, a client that is ahead, an unknown or other `epoch`, a gap, it answers a fresh `snapshot`. The client
  keeps whatever `snapshot` or `resumed` says: it replaces its copy by the snapshot and takes the new `epoch`.
- **Unknown messages (G5).** A client ignores a message whose `type` it does not know, so the core can add messages
  (C-05b's frames, for one) without a new `PROTOCOL_VERSION`. The core does not ignore: a message it cannot read is
  answered with `error` (or `rejected` for a `publish` or `request` that has an id).
- **Command ids are single-use.** An id names one command. The same id with the same content is the same command (the
  answer is repeated, C6). The same id with other content is `rejected`, never silently accepted: the publisher
  would otherwise believe an edit happened that did not. The core remembers a bounded number of recent ids
  (`REMEMBERED_COMMANDS_MAX`), so a resend of a very old id is not guaranteed to be recognised.
- The verdict (D5): `verdict` is `none` (no verdict yet), `valid`, or `invalid` (the document changed after it). It
  rides in `snapshot` and in every `applied`, so the client learns of an invalidation in the same message as the edit.

Not here: derived values and the definition hash in `snapshot` and `applied` (D4; the model-label and derived-value
leaves B-05 and C-03 add optional fields, G5), run and judge requests (`request.action` gains them with X-02 and the J
epic), the asset channel (3.4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .assumption import AssumptionTable
from .commands import Command, Reason
from .conventions import ID_PATTERN
from .designspec import ActuateEntry, Actuator, ControlSchedule, DesignSpec, Instance, Joint
from .frames import Frame, RunEnded, RunStarted
from .history import Origin
from .material import Material
from .partdef import PartDef
from .project import Project
from .world import World

PROTOCOL_VERSION = 1
"""The one protocol number this code speaks. Raised when a message gains a required field or changes meaning."""

_ProjectId = Annotated[str, Field(pattern=ID_PATTERN)]
MAX_COMMAND_ID_LENGTH = 128
"""Longest command id (characters). A UUID is 36; the cap only keeps the core's memory of ids small."""

_CommandId = Annotated[str, Field(min_length=1, max_length=MAX_COMMAND_ID_LENGTH)]
_Revision = Annotated[int, Field(strict=True, ge=0)]


class _Msg(BaseModel):
    """A message ignores fields it does not know (G5) and is immutable."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class VerdictState(StrEnum):
    NONE = "none"
    VALID = "valid"
    INVALID = "invalid"


class RequestAction(StrEnum):
    UNDO = "undo"
    REDO = "redo"


# --- both directions ------------------------------------------------------------------------------------------


class Hello(_Msg):
    """First message of each side: the protocol number it speaks. The core answers a `hello` it can serve with its
    own; with a number it cannot serve it answers `error` and closes."""

    type: Literal["hello"]
    protocol: Annotated[int, Field(strict=True, ge=1)]


# --- client -> core -------------------------------------------------------------------------------------------


class Subscribe(_Msg):
    """Follow a project. `after_revision` and `epoch` are the last revision the client holds and the `epoch` it came
    with (a reconnect); `None` for a first subscription. Both are needed to be resumed: with only one the core
    answers a `snapshot`. One subscription per connection; a second `subscribe` replaces it."""

    type: Literal["subscribe"]
    project: _ProjectId
    after_revision: _Revision | None = None
    epoch: Annotated[str, Field(min_length=1)] | None = None


class Publish(_Msg):
    """Send a command (one edit or a batch, all or nothing: C2). `id` is the publisher's command id (C6),
    `base_revision` the revision the publisher saw (C5), `origin` the input path (`client-adapter.md` 3.5)."""

    type: Literal["publish"]
    id: _CommandId
    base_revision: _Revision
    command: Command
    origin: Origin


class Request(_Msg):
    """Ask the core to do something to the history. `undo` and `redo` take back and redo the document's last
    entry, whoever made it (one linear history in S1; per-user undo is N-04)."""

    type: Literal["request"]
    id: _CommandId
    action: RequestAction
    origin: Origin


ClientMessage = Annotated[Union[Hello, Subscribe, Publish, Request], Field(discriminator="type")]
"""Anything a client sends."""


# --- core -> client -------------------------------------------------------------------------------------------


class Snapshot(_Msg):
    """The whole document at `revision`, of the document life `epoch`."""

    type: Literal["snapshot"]
    project_id: _ProjectId
    epoch: Annotated[str, Field(min_length=1)]
    revision: _Revision
    verdict: VerdictState
    project: Project


class Resumed(_Msg):
    """The core continues a subscription from `after_revision`: the `revision - after_revision` `applied` messages
    that follow, in order, bring the client's copy to `revision`."""

    type: Literal["resumed"]
    project_id: _ProjectId
    epoch: Annotated[str, Field(min_length=1)]
    after_revision: _Revision
    revision: _Revision


class ProjectChanges(_Msg):
    """The sections of the project a change replaced, each as its whole new value. A section that is `None` did not
    change. `materials`, `parts`, `instances`, `joints`, `actuators`, `schedule` are the parts of `Project.design`;
    `world` and `assumptions` are the project's. A change is at the grain of a section, not of an item: a client
    that needs finer grain reads `Applied.command`, but never needs to apply it (D3)."""

    materials: tuple[Material, ...] | None = None
    parts: tuple[PartDef, ...] | None = None
    instances: tuple[Instance, ...] | None = None
    joints: tuple[Joint, ...] | None = None
    actuators: tuple[Actuator, ...] | None = None
    schedule: ControlSchedule | None = None
    world: World | None = None
    assumptions: AssumptionTable | None = None


class Applied(_Msg):
    """Revision `revision` of the document exists: `command` (as applied) from `origin` changed it as `changes`
    says, and the verdict is now `verdict`. Sent to every subscriber, the publisher included, in revision order."""

    type: Literal["applied"]
    revision: _Revision
    id: _CommandId
    cause: Literal["publish", "undo", "redo"]
    origin: Origin
    command: Command
    changes: ProjectChanges
    verdict: VerdictState


class Accepted(_Msg):
    """To the publisher: `id` is done and the document is at `revision` (the new one, or the unchanged one when the
    command changed nothing). Comes after the `applied` of the same change."""

    type: Literal["accepted"]
    id: _CommandId
    revision: _Revision


class Rejected(_Msg):
    """To the publisher: `id` changed nothing, for these reasons (never empty: C3)."""

    type: Literal["rejected"]
    id: _CommandId
    reasons: Annotated[tuple[Reason, ...], Field(min_length=1)]


class ProtocolError(_Msg):
    """The connection broke the protocol (not a rejected command): bad JSON, a message that is no known message,
    a `publish` before `hello` or `subscribe`, an unknown project, a protocol number the core does not speak. A
    fatal error is followed by the core closing the connection."""

    type: Literal["error"]
    message: Annotated[str, Field(min_length=1)]
    fatal: bool


ServerMessage = Annotated[
    Union[Hello, Snapshot, Resumed, Applied, Accepted, Rejected, ProtocolError, RunStarted, Frame, RunEnded],
    Field(discriminator="type"),
]
"""Anything the core sends."""


def apply_changes(project: Project, changes: ProjectChanges) -> Project:
    """The client's side of `applied`: `project` with the replaced sections swapped in, validated as a `Project`.
    This is not the command applier; it only substitutes values the core already computed."""
    d = project.design
    design = DesignSpec(
        materials=d.materials if changes.materials is None else changes.materials,
        parts=d.parts if changes.parts is None else changes.parts,
        instances=d.instances if changes.instances is None else changes.instances,
        joints=d.joints if changes.joints is None else changes.joints,
        actuators=d.actuators if changes.actuators is None else changes.actuators,
        schedule=d.schedule if changes.schedule is None else changes.schedule,
    )
    return Project(
        design=design,
        world=project.world if changes.world is None else changes.world,
        assumptions=project.assumptions if changes.assumptions is None else changes.assumptions,
    )


def changes_between(old: Project, new: Project) -> ProjectChanges:
    """The `ProjectChanges` that take `old` to `new` (the core's side)."""
    a, b = old.design, new.design
    return ProjectChanges(
        materials=b.materials if a.materials != b.materials else None,
        parts=b.parts if a.parts != b.parts else None,
        instances=b.instances if a.instances != b.instances else None,
        joints=b.joints if a.joints != b.joints else None,
        actuators=b.actuators if a.actuators != b.actuators else None,
        schedule=b.schedule if a.schedule != b.schedule else None,
        world=new.world if old.world != new.world else None,
        assumptions=new.assumptions if old.assumptions != new.assumptions else None,
    )
