"""Typed references to things in a `Project`, for rejection reasons (C-02a).

An id is unique only inside its own collection (`designspec.py`): a part `wheel` and an instance `wheel` can both
exist. A reason that says "wheel" is therefore ambiguous, so a reason names what it is about as `Ref(kind, id)`.
`RefError` is a `ValueError` that carries the refs of the thing a validator refused, so the command applier can
report the offending id of a dangling reference (pydantic keeps the exception in the error's `ctx`).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RefKind(StrEnum):
    INSTANCE = "instance"
    JOINT = "joint"
    ACTUATOR = "actuator"
    PART = "part"
    MATERIAL = "material"
    SNAP_POINT = "snap_point"
    SCHEDULE_ENTRY = "schedule_entry"
    ASSUMPTION = "assumption"
    PARAMETER = "parameter"
    PLANET = "planet"
    PROP = "prop"


class Ref(BaseModel):
    """`id` of a `kind`. A snap point is `<instance>/<snap point>`, a parameter `<instance>/<parameter>`:
    those two ids are only unique inside their owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RefKind
    id: str = Field(min_length=1)


class RefError(ValueError):
    """A validation failure about specific things. `refs` are those things."""

    def __init__(self, message: str, *refs: Ref):
        super().__init__(message)
        self.refs = refs
