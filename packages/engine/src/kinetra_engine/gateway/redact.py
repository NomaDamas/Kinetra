"""Secret masking for everything the gateway writes or raises (ledger lines, error messages).

The patterns are the ones `tools/review/common.py` uses for the review bot (P0-06). That file is a dev tool and not
importable from a package, so the list is repeated here; `tests/test_gateway.py::test_redact_patterns_match_review_bot`
fails if the two drift apart.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # OpenRouter / OpenAI shape
    re.compile(r"(?i)\bBearer\s+[^\s\"']+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),  # GitHub tokens (classic, OAuth, app, ...)
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
)


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Replace each exact secret value (4+ chars) and anything key-shaped with `***`."""
    for secret in secrets:
        if len(secret) >= 4:
            text = text.replace(secret, "***")
    for pat in _SECRET_PATTERNS:
        text = pat.sub("***", text)
    return text
