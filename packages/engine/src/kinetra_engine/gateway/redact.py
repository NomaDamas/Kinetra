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


def mask_exact(obj, secrets: tuple[str, ...]):
    """Replace each exact secret value (4+ chars) in every string of a JSON-able value, dict keys included, and nothing else.

    Used where pattern masking would corrupt legitimate data (ledger lines, model replies): a project id like
    `desk-lamp-rocket` contains `sk-lamp-rocket`, which the key-shaped pattern would eat. Run it on the value
    *before* `json.dumps`, because serialising escapes quotes and backslashes and a key containing them no longer matches.
    """
    if isinstance(obj, str):
        for s in secrets:
            if len(s) >= 4:
                obj = obj.replace(s, "***")
        return obj
    if isinstance(obj, dict):
        return {mask_exact(k, secrets) if isinstance(k, str) else k: mask_exact(v, secrets) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_exact(v, secrets) for v in obj]
    return obj
