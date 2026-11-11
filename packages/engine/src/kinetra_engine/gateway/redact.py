"""Secret masking for the gateway's error text (G-01).

The rules are the ones `tools/review/common.py` uses for the review bot (P0-06), including the `Bearer` rule that masks only a
secret-shaped token (20+ token characters) and lets a source expression such as `self._key` through. That file is a dev
tool and not importable from a package, so the rules are repeated here; `tests/test_gateway.py::test_gateway_redact_matches_review_bot`
loads both and fails if their patterns or their output on a set of samples differ.

Ledger lines and model replies are not pattern-masked (see `mask_exact`): a hyphenated project id or word would be altered.
"""

from __future__ import annotations

import re

BEARER_MIN = 20
_BEARER = re.compile(r"(?i)\bBearer[ \t]+([A-Za-z0-9._~+/=\-]{%d,})" % BEARER_MIN)
_ATTR_ACCESS = re.compile(r"(?:self|cls|this|os|config|cfg|settings|secrets)(?:\.[A-Za-z_][A-Za-z0-9_]*)+")

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # OpenRouter / OpenAI shape
    _BEARER,
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),  # GitHub tokens (classic, OAuth, app, ...)
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
)


def _is_code(token: str) -> bool:
    """An attribute access on a well-known object name (`self._key`) is a source expression, not a secret."""
    return _ATTR_ACCESS.fullmatch(token) is not None


def _spans(text: str, secrets: tuple[str, ...]) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for secret in secrets:
        if len(secret) >= 4:
            found += [(m.start(), m.end()) for m in re.finditer(re.escape(secret), text)]
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            if pat is _BEARER and _is_code(m.group(1)):
                continue
            found.append((m.start(), m.end()))
    found.sort()
    merged: list[tuple[int, int]] = []
    for a, b in found:
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Replace each exact secret value (4+ chars) and anything key-shaped with `***`."""
    out: list[str] = []
    pos = 0
    for a, b in _spans(text, secrets):
        out += [text[pos:a], "***"]
        pos = b
    out.append(text[pos:])
    return "".join(out)


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
