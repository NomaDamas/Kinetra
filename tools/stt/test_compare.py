"""Offline test for the comparison tool's key redaction. Run: `uv run pytest tools/stt -q`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare import redact_body  # noqa: E402

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"


def test_key_straddling_the_cut_is_removed_before_truncating():
    prefix = "x" * (200 - 12)  # the 200-character cut falls 12 characters into the key
    body = (prefix + KEY + " tail").encode()
    old = body.decode()[:200].replace(KEY, "***")  # the previous behaviour: cut first, then replace
    assert KEY[:12] in old  # that leaked a key prefix
    out = redact_body(body, KEY)
    assert KEY[:6] not in out and "sk-or-v1" not in out and len(out) <= 200
    assert "***" in out  # the whole key was replaced by the mask, so no fragment of it is left


def test_key_anywhere_in_the_body_is_masked():
    out = redact_body(f'{{"error":"bad key {KEY}"}}'.encode(), KEY)
    assert KEY not in out and "***" in out


def test_no_key_leaves_text_alone_and_bad_bytes_do_not_crash():
    assert redact_body(b'{"error":"nope"}', KEY) == '{"error":"nope"}'
    assert "\ufffd" in redact_body(b"\xff\xfe", KEY)
