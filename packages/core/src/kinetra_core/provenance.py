"""Value badges and sources (V5, A0-04 rule G6).

A physical number in the Project model is never bare. It is a `Quantity`: value, unit, one of five badges
(`시뮬` `인용` `기본값` `사용자 선언` `추정`) and a `Source`. Both badge and source are required; a quantity
without them fails validation (C-01a DoD).

The model checks that a source is *present and not a placeholder*. It cannot check that the source says what
the value says; that is review's job (`docs/process/review-rubric.md`, item 4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .conventions import Unit

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
"""A finite JSON number. Strict: strings and booleans are not numbers."""


class Badge(StrEnum):
    """Value badge. The JSON carries the ASCII id; `BADGE_LABEL_KO` is what the UI prints."""

    SIMULATED = "simulated"
    CITED = "cited"
    DEFAULT = "default"
    USER_DECLARED = "user_declared"
    ESTIMATED = "estimated"


BADGE_LABEL_KO: dict[Badge, str] = {
    Badge.SIMULATED: "시뮬",
    Badge.CITED: "인용",
    Badge.DEFAULT: "기본값",
    Badge.USER_DECLARED: "사용자 선언",
    Badge.ESTIMATED: "추정",
}

_PLACEHOLDERS = frozenset({"", "-", "--", "?", "n/a", "na", "none", "null", "unknown", "tbd", "todo", "없음", "모름"})


def _text(v: str, what: str) -> str:
    v = v.strip()
    if v.casefold() in _PLACEHOLDERS:
        raise ValueError(f"{what} must say something real, got placeholder {v!r}")
    return v


class Source(BaseModel):
    """Where a value comes from.

    `ref` is what was cited, declared or run: a document, a datasheet, "founder", a run id, or the reason a default
    was chosen. `locator` is where inside it (table, page, section). `url` is a link when there is one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=1, max_length=500)
    locator: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)

    @field_validator("ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _text(v, "source.ref")

    @field_validator("locator")
    @classmethod
    def _locator(cls, v: str | None) -> str | None:
        return None if v is None else _text(v, "source.locator")

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _text(v, "source.url")
        if not v.startswith(("http://", "https://")) or " " in v:
            raise ValueError(f"source.url must be an http(s) URL, got {v!r}")
        return v


class Provenance(BaseModel):
    """Badge and source, both required. A `인용` (cited) value must also say where in the source (locator or url)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    badge: Badge
    source: Source

    @model_validator(mode="after")
    def _cited_needs_a_place(self) -> "Provenance":
        if self.badge is Badge.CITED and not (self.source.locator or self.source.url):
            raise ValueError("a cited (인용) value needs source.locator or source.url, not just a name")
        return self


class Quantity(Provenance):
    """One physical number with its unit, badge and source."""

    value: Number
    unit: Unit


def require_unit(q: Quantity, expected: Unit, field: str) -> None:
    if q.unit is not expected:
        raise ValueError(f"{field} must be in {expected.value!r}, got {q.unit.value!r}")
