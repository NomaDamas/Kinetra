"""Value badges and sources (V5, A0-04 rule G6).

A physical number in the Project model is never bare. It is a `Quantity`: value, unit, one of five badges
(`시뮬` `인용` `기본값` `사용자 선언` `추정`) and a `Source`. Both badge and source are required; a quantity
without them fails validation (C-01a DoD).

The model checks that a source is *present and not a placeholder*. It cannot check that the source says what
the value says; that is review's job (`docs/process/review-rubric.md`, item 4).

Badge wire ids follow the approved design system (`design/exports/design-system/tokens.css`):
`sim`, `cite`, `default`, `declared`, `estimate`. Korean labels are `BADGE_LABEL_KO`.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .conventions import Unit

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
"""A finite JSON number. Strict: strings and booleans are not numbers."""


class Badge(StrEnum):
    SIM = "sim"
    CITE = "cite"
    DEFAULT = "default"
    DECLARED = "declared"
    ESTIMATE = "estimate"


BADGE_LABEL_KO: dict[Badge, str] = {
    Badge.SIM: "시뮬",
    Badge.CITE: "인용",
    Badge.DEFAULT: "기본값",
    Badge.DECLARED: "사용자 선언",
    Badge.ESTIMATE: "추정",
}

# Compared after casefolding and collapsing every run of punctuation/whitespace to one space ("N/A." -> "n a").
_PLACEHOLDER_PHRASES = frozenset(
    {"n a", "na", "none", "null", "nil", "unknown", "not available", "no source", "source missing", "missing",
     "없음", "모름", "미정", "출처 없음", "출처 미정", "해당 없음"}
)
_PLACEHOLDER_LEADING = frozenset({"tbd", "tba", "todo", "fixme", "xxx", "미정"})


def _text(v: str, what: str) -> str:
    """Reject text that says nothing: no letter or digit, a known placeholder, or one that starts with TBD/TODO."""
    v = v.strip()
    norm = re.sub(r"[\W_]+", " ", v.casefold()).strip()
    if not norm:
        raise ValueError(f"{what} must contain a letter or digit, got {v!r}")
    if norm in _PLACEHOLDER_PHRASES or norm.split(" ", 1)[0] in _PLACEHOLDER_LEADING:
        raise ValueError(f"{what} must say something real, got placeholder {v!r}")
    return v


_SPDX_ID = r"[A-Za-z0-9][A-Za-z0-9.+\-]*"
_SPDX_RE = re.compile(rf"{_SPDX_ID}(?: (?:AND|OR|WITH) {_SPDX_ID})*")
_SPDX_BANNED = frozenset({"NONE", "NOASSERTION", "UNKNOWN"})


class Source(BaseModel):
    """Where a value comes from.

    `ref` is what was cited, declared or run: a document, a datasheet, a run id, or the reason a default was chosen
    (for an estimate: the method and its inputs). `locator` is where inside it (table, page, section). `url` is a
    link when there is one. `license` (SPDX expression) and `declared_by` / `declared_at` feed the badge popover
    (`ValueBadges`, 인용 and 사용자 선언); `Provenance` allows each only on its own badge.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=1, max_length=500)
    locator: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    license: str | None = Field(default=None, max_length=200)
    declared_by: str | None = Field(default=None, max_length=200)
    declared_at: AwareDatetime | None = None

    @field_validator("ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _text(v, "source.ref")

    @field_validator("locator", "declared_by")
    @classmethod
    def _optional_text(cls, v: str | None, info) -> str | None:
        return None if v is None else _text(v, f"source.{info.field_name}")

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(c.isspace() for c in v):
            raise ValueError(f"source.url must not contain whitespace, got {v!r}")
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"source.url must be an http(s) URL with a host, got {v!r}")
        return v

    @field_validator("license")
    @classmethod
    def _license(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _SPDX_RE.fullmatch(v) or any(t in _SPDX_BANNED for t in v.split()):
            raise ValueError(f"source.license must be an SPDX expression (not NONE/NOASSERTION/UNKNOWN), got {v!r}")
        return v


class Provenance(BaseModel):
    """Badge and source, both required.

    A cited (`cite`) value must say where in the source (locator or url). `license` belongs to cited values only;
    `declared_by` and `declared_at` belong to declared values only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    badge: Badge
    source: Source

    @model_validator(mode="after")
    def _badge_matches_source(self) -> "Provenance":
        s = self.source
        if self.badge is Badge.CITE and not (s.locator or s.url):
            raise ValueError("a cited (인용) value needs source.locator or source.url, not just a name")
        if s.license is not None and self.badge is not Badge.CITE:
            raise ValueError("source.license is only for cited (인용) values")
        if (s.declared_by is not None or s.declared_at is not None) and self.badge is not Badge.DECLARED:
            raise ValueError("source.declared_by / declared_at are only for declared (사용자 선언) values")
        return self


class Quantity(Provenance):
    """One physical number with its unit, badge and source."""

    value: Number
    unit: Unit
