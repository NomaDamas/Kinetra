"""No tracked text file may contain a merge conflict marker (#506: a `>>>>>>> origin/main` line survived a README merge).

Only the two markers that cannot be anything else are looked for (a line that starts with seven `<` or seven `>` and
then a space or the end of the line); `=======` alone is a legitimate underline in Markdown and reStructuredText.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKER = re.compile(r"^(?:<{7}|>{7})(?: .*)?$")


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return [ROOT / n for n in out.decode("utf-8").split("\0") if n]


def markers_in(text: str) -> list[int]:
    return [i for i, line in enumerate(text.splitlines(), 1) if MARKER.match(line)]


def test_no_tracked_text_file_has_a_conflict_marker():
    found = []
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue  # binary
        found += [f"{path.relative_to(ROOT)}:{n}" for n in markers_in(text)]
    assert found == [], "merge conflict markers left in: " + ", ".join(found)


def test_the_check_sees_markers_and_ignores_setext_underlines():
    assert markers_in("a\n" + "<" * 7 + " HEAD\nb\n" + "=" * 7 + "\n" + ">" * 7 + " origin/main\n") == [2, 5]
    assert markers_in("<" * 7) == [1]
    assert markers_in("Title\n=======\n" + "<" * 8 + "\nx " + ">" * 7) == []
