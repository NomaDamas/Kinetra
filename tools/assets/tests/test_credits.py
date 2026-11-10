"""uv run python -m unittest discover -s tools/assets/tests -v  (저장소 루트에서)"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import credits  # noqa: E402

EXAMPLE = HERE / "example_ledger.csv"
EXPECTED = HERE / "example_credits.md"
REAL_LEDGER = credits.DEFAULT_LEDGER
REAL_CREDITS = credits.DEFAULT_OUT


def good_row(**over):
    with open(EXAMPLE, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    row = dict(rows[0])
    row.update(over)
    return row


def write_ledger(path: Path, rows, header=None):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header or credits.COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in credits.COLUMNS])


class GoldenTests(unittest.TestCase):
    def test_two_example_rows_match_golden(self):
        self.assertEqual(len(credits.read_ledger(EXAMPLE)), 2)
        self.assertEqual(credits.generate(EXAMPLE), EXPECTED.read_text(encoding="utf-8"))

    def test_output_is_deterministic_and_order_independent(self):
        rows = credits.read_ledger(EXAMPLE)
        self.assertEqual(credits.render(rows), credits.render(list(reversed(rows))))
        self.assertEqual(credits.render(rows), credits.render(rows))

    def test_real_ledger_matches_committed_credits(self):
        self.assertEqual(credits.generate(REAL_LEDGER), REAL_CREDITS.read_text(encoding="utf-8"))

    def test_real_ledger_first_dependency_rows(self):
        got = {r["에셋 ID"]: (r["라이선스(SPDX)"], r["kind"]) for r in credits.read_ledger(REAL_LEDGER)}
        self.assertEqual(got["dep-pyyaml-6.0.3"], ("MIT", "dependency"))
        self.assertEqual(got["dep-mujoco-4.0.0"], ("Apache-2.0", "dependency"))
        self.assertEqual(got["dep-numpy-2.5.4"], ("BSD-3-Clause", "dependency"))


class CliTests(unittest.TestCase):
    def test_write_then_check(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "CREDITS.md"
            self.assertEqual(credits.main(["--ledger", str(EXAMPLE), "--out", str(out)]), 0)
            self.assertEqual(out.read_text(encoding="utf-8"), EXPECTED.read_text(encoding="utf-8"))
            self.assertEqual(credits.main(["--ledger", str(EXAMPLE), "--out", str(out), "--check"]), 0)
            out.write_text(out.read_text(encoding="utf-8") + "x", encoding="utf-8")
            self.assertEqual(credits.main(["--ledger", str(EXAMPLE), "--out", str(out), "--check"]), 1)
            self.assertEqual(credits.main(["--ledger", str(EXAMPLE), "--out", str(Path(d) / "none.md"), "--check"]), 1)


class ValidationTests(unittest.TestCase):
    def reject(self, row=None, rows=None, header=None, msg=""):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            write_ledger(p, rows if rows is not None else [row], header)
            with self.assertRaises(credits.LedgerError) as cm:
                credits.read_ledger(p)
            self.assertIn(msg, str(cm.exception))

    def test_rejections(self):
        self.reject(good_row(**{"저작자": ""}), msg="'저작자'이 비었다")
        self.reject(good_row(kind="tool"), msg="kind는")
        self.reject(good_row(**{"라이선스(SPDX)": "CC-BY-NC-4.0"}), msg="허용하지 않는")
        self.reject(good_row(**{"라이선스(SPDX)": "NOASSERTION"}), msg="허용하지 않는")
        self.reject(good_row(**{"원본 해시": "sha256:abc"}), msg="원본 해시")
        self.reject(good_row(**{"받은 날짜": "2026-13-01"}), msg="받은 날짜")
        self.reject(good_row(**{"용도": "a\nb"}), msg="줄바꿈")
        self.reject(good_row(**{"용도": " a"}), msg="공백")
        self.reject(rows=[good_row(), good_row()], msg="중복")
        self.reject(rows=[], header=credits.COLUMNS[:-1], msg="머리글")

    def test_allows_cc_by_and_compound_spdx(self):
        for lic in ("CC-BY-4.0", "BSD-3-Clause AND MIT", "CC0-1.0", "Apache-2.0"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "l.csv"
                write_ledger(p, [good_row(**{"라이선스(SPDX)": lic})])
                self.assertEqual(len(credits.read_ledger(p)), 1)

    def test_cli_error_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            write_ledger(p, [good_row(kind="tool")])
            self.assertEqual(credits.main(["--ledger", str(p), "--out", str(Path(d) / "c.md")]), 1)


if __name__ == "__main__":
    unittest.main()
