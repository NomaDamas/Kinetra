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

    def test_real_ledger_dependency_paths_exist(self):
        root = credits.ROOT
        for r in credits.read_ledger(REAL_LEDGER):
            with self.subTest(id=r["에셋 ID"]):
                self.assertTrue((root / r["경로"]).exists(), r["경로"])

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
        for bad in ("20260102", "2026-W01-5", "2026-1-2", "２０２６-01-02", "2026-01-02T00:00"):
            self.reject(good_row(**{"받은 날짜": bad}), msg="받은 날짜")
        self.reject(good_row(**{"용도": "a\nb"}), msg="줄바꿈")
        self.reject(good_row(**{"용도": " a"}), msg="공백")
        self.reject(rows=[good_row(), good_row()], msg="중복")
        self.reject(rows=[], header=credits.COLUMNS[:-1], msg="머리글")

    def test_spdx_valid(self):
        for lic in (
            "CC-BY-4.0",
            "CC0-1.0",
            "Apache-2.0",
            "BSD-3-Clause AND MIT",
            "MIT OR Apache-2.0",
            "(MIT OR Apache-2.0) AND Zlib",
            "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
            "GPL-2.0-or-later WITH Classpath-exception-2.0",
            "((MIT))",
        ):
            credits.check_spdx(lic)
        for lic in sorted(credits.ALLOWED_LICENSES):
            credits.check_spdx(lic)

    def test_spdx_invalid(self):
        cases = {
            "미확인": "허용 목록에 없는|쓸 수 없는",
            "garbage": "허용 목록",
            "": "끝났다",
            "mit": "허용 목록",
            "MIT AND": "끝났다",
            "AND MIT": "허용 목록",
            "MIT MIT": "끝까지",
            "MIT OR OR Zlib": "허용 목록",
            "(MIT": "끝났다",
            "MIT)": "끝까지",
            "()": "허용 목록",
            "MIT and Zlib": "끝까지",
            "MIT WITH": "끝났다",
            "MIT WITH Nonexistent-exception": "예외",
            "GPL-3.0": "허용 목록",
            "GPL-2.0+": "쓸 수 없는|허용 목록",
            "MIT, Zlib": "쓸 수 없는",
            "CC-BY-NC-4.0": "허용하지 않는",
            "CC-BY-NC-SA-4.0": "허용하지 않는",
            "MIT AND NOASSERTION": "허용하지 않는",
            "NONE": "허용하지 않는",
            "UNKNOWN": "허용하지 않는",
            "LicenseRef-NC-thing": "허용하지 않는",
            "LicenseRef-Foo": "LicenseRef 사유",
        }
        for expr, pattern in cases.items():
            with self.subTest(expr=expr):
                with self.assertRaisesRegex(credits.LedgerError, pattern):
                    credits.check_spdx(expr)

    def test_licenseref_needs_reason_in_notes(self):
        credits.check_spdx("LicenseRef-Vendor-EULA", "LicenseRef 사유: 벤더 약관, docs/x.md 참조")
        with self.assertRaises(credits.LedgerError):
            credits.check_spdx("LicenseRef-Vendor-EULA", "LicenseRef 사유:   ")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            write_ledger(p, [good_row(**{"라이선스(SPDX)": "LicenseRef-Vendor-EULA", "변경 내역": "LicenseRef 사유: 벤더 약관"})])
            self.assertEqual(len(credits.read_ledger(p)), 1)
            write_ledger(p, [good_row(**{"라이선스(SPDX)": "LicenseRef-Vendor-EULA"})])
            with self.assertRaises(credits.LedgerError):
                credits.read_ledger(p)

    def test_spdx_error_in_ledger_names_the_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            write_ledger(p, [good_row(**{"라이선스(SPDX)": "미확인"})])
            with self.assertRaisesRegex(credits.LedgerError, r"l\.csv:2: 라이선스\(SPDX\)"):
                credits.read_ledger(p)

    def test_cli_error_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            write_ledger(p, [good_row(kind="tool")])
            self.assertEqual(credits.main(["--ledger", str(p), "--out", str(Path(d) / "c.md")]), 1)


if __name__ == "__main__":
    unittest.main()
