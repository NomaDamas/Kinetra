"""SPDX check in core matches the reviewed one in tools/assets/credits.py (drift test) and is used by Source.license."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinetra_core import Source
from kinetra_core import spdx

CREDITS = Path(__file__).resolve().parents[3] / "tools" / "assets" / "credits.py"


@pytest.fixture(scope="module")
def credits():
    spec = importlib.util.spec_from_file_location("kin_credits_for_drift_test", CREDITS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ACCEPT = [
    "MIT",
    "MIT OR Apache-2.0",
    "(MIT AND BSD-3-Clause)",
    "GPL-2.0-or-later WITH Classpath-exception-2.0",
    "MIT AND (Apache-2.0 OR BSD-2-Clause)",
    "CC-BY-4.0",
]
REJECT = [
    "Foo-1.0",
    "mit",
    "MIT AND",
    "",
    "(MIT",
    "MIT)",
    "MIT or Apache-2.0",
    "NONE",
    "NOASSERTION",
    "UNKNOWN",
    "MIT WITH Foo-exception",
    "CC-BY-NC-4.0",
    "LicenseRef-x",
    "MIT; DROP",
]


def test_allowlists_match_tools_assets_credits(credits):
    assert spdx.ALLOWED_LICENSES == credits.ALLOWED_LICENSES
    assert spdx.ALLOWED_EXCEPTIONS == credits.ALLOWED_EXCEPTIONS
    assert spdx.BANNED_TOKENS == credits.BANNED_TOKENS
    assert spdx.LICENSEREF_RE.pattern == credits.LICENSEREF_RE.pattern
    assert spdx.LICENSEREF_REASON_RE.pattern == credits.LICENSEREF_REASON_RE.pattern
    assert spdx.SPDX_TOKEN_RE.pattern == credits.SPDX_TOKEN_RE.pattern


@pytest.mark.parametrize("expr", ACCEPT + REJECT + ["LicenseRef-x", "(MIT OR Apache-2.0) AND ISC", "MIT AND AND ISC"])
@pytest.mark.parametrize("notes", ["", "LicenseRef 사유: vendor terms"])
def test_verdicts_match_tools_assets_credits(credits, expr, notes):
    def verdict(fn, err):
        try:
            fn(expr, notes)
        except err:
            return False
        return True

    assert verdict(spdx.check_spdx, spdx.SpdxError) == verdict(credits.check_spdx, credits.LedgerError)


@pytest.mark.parametrize("expr", ACCEPT)
def test_source_accepts_valid_spdx(expr):
    Source(ref="Some Handbook", locator="Table 1", license=expr)


@pytest.mark.parametrize("expr", REJECT)
def test_source_rejects_invalid_spdx(expr):
    with pytest.raises(ValidationError, match="source.license"):
        Source(ref="Some Handbook", locator="Table 1", license=expr)


def test_licenseref_needs_a_reason_in_ref():
    with pytest.raises(ValidationError, match="LicenseRef 사유"):
        Source(ref="Vendor sheet", locator="p. 2", license="LicenseRef-vendor")
    Source(ref="Vendor sheet. LicenseRef 사유: vendor terms allow use", locator="p. 2", license="LicenseRef-vendor")
