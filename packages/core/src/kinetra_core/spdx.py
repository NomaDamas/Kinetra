"""SPDX license expression check (V5). A copy of `check_spdx` in `tools/assets/credits.py`.

Same allowlist, same grammar: single ids or `AND` / `OR` / `WITH` / parentheses (operators upper case, AND binds
tighter than OR), `WITH` only with the allowed exceptions, `LicenseRef-<name>` only when `notes` carries
`LicenseRef 사유: <내용>`, and NC / NOASSERTION / NONE / UNKNOWN are rejected anywhere.

The copy exists because `kinetra_core` must not import from `tools/`. `tests/test_spdx.py` loads `credits.py` and
fails if the allowlists or the verdicts drift apart.
"""

from __future__ import annotations

import re

ALLOWED_LICENSES = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC-BY-3.0",
        "CC-BY-4.0",
        "CC-BY-SA-3.0",
        "CC-BY-SA-4.0",
        "CC0-1.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "ISC",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MIT",
        "MPL-2.0",
        "OFL-1.1",
        "PSF-2.0",
        "Python-2.0",
        "Unlicense",
        "Zlib",
    }
)
ALLOWED_EXCEPTIONS = frozenset({"Classpath-exception-2.0", "GCC-exception-3.1", "LLVM-exception"})
LICENSEREF_RE = re.compile(r"LicenseRef-[A-Za-z0-9.\-]+")
LICENSEREF_REASON_RE = re.compile(r"LicenseRef 사유: *\S")
BANNED_TOKENS = frozenset({"NC", "NOASSERTION", "NONE", "UNKNOWN"})
SPDX_TOKEN_RE = re.compile(r"\s*(\(|\)|[A-Za-z0-9.\-]+)")


class SpdxError(ValueError):
    pass


def _spdx_tokens(expr: str) -> list[str]:
    tokens, pos = [], 0
    while pos < len(expr):
        m = SPDX_TOKEN_RE.match(expr, pos)
        if not m:
            if expr[pos:].strip() == "":
                break
            raise SpdxError(f"SPDX 표현식에 쓸 수 없는 문자: {expr!r}")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


def check_spdx(expr: str, notes: str = "") -> None:
    """Raise `SpdxError` unless `expr` is an SPDX expression over the allowlist."""
    if any(t.upper() in BANNED_TOKENS for t in re.split(r"[^A-Za-z0-9]+", expr)):
        raise SpdxError(f"허용하지 않는 라이선스(NC, NOASSERTION, NONE, UNKNOWN): {expr!r}")
    tokens = _spdx_tokens(expr)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        if pos >= len(tokens):
            raise SpdxError(f"SPDX 표현식이 끝났다: {expr!r}")
        pos += 1
        return tokens[pos - 1]

    def term() -> None:
        tok = take()
        if tok == "(":
            disjunction()
            if take() != ")":
                raise SpdxError(f"SPDX 표현식에서 ')'가 필요하다: {expr!r}")
            return
        if LICENSEREF_RE.fullmatch(tok):
            if not LICENSEREF_REASON_RE.search(notes):
                raise SpdxError(f"{tok}는 변경 내역에 'LicenseRef 사유: <내용>'이 있어야 한다")
        elif tok not in ALLOWED_LICENSES:
            raise SpdxError(f"허용 목록에 없는 라이선스 식별자 {tok!r}: {expr!r}")
        if peek() == "WITH":
            take()
            exc = take()
            if exc not in ALLOWED_EXCEPTIONS:
                raise SpdxError(f"허용 목록에 없는 라이선스 예외 {exc!r}: {expr!r}")

    def conjunction() -> None:
        term()
        while peek() == "AND":
            take()
            term()

    def disjunction() -> None:
        conjunction()
        while peek() == "OR":
            take()
            conjunction()

    disjunction()
    if pos != len(tokens):
        raise SpdxError(f"SPDX 표현식을 끝까지 읽지 못했다({tokens[pos]!r}에서 멈춤): {expr!r}")
