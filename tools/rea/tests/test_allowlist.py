"""uv run python -m unittest discover -s tools/rea/tests -v  (저장소 루트에서)"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import check_allowlist as c  # noqa: E402

ROOT = HERE.parents[2]
GOOD = "allow | oss-permissive | https://github.com/x/y | MIT | https://github.com/x/y/blob/main/LICENSE | 2026-11-10 | 메모"


def edit(**kw):
    f = GOOD.split(" | ")
    idx = {"cls": 0, "kind": 1, "target": 2, "lic": 3, "url": 4, "date": 5}
    for k, v in kw.items():
        f[idx[k]] = v
    return " | ".join(f)


class RealListTest(unittest.TestCase):
    def test_committed_list_is_valid(self):
        self.assertEqual(c.check_text(c.DEFAULT.read_text(encoding="utf-8")), [])

    def test_policy_targets_are_present(self):
        text = c.DEFAULT.read_text(encoding="utf-8")
        for name in ("mujoco", "JoltPhysics", "godot", "three.js", "blender", "FreeCAD", "apps/studio"):
            self.assertIn(name, text)

    def test_copyleft_is_conditional_only(self):
        found = 0
        for line in c.DEFAULT.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                continue
            if " | oss-copyleft | " in line:
                self.assertTrue(line.startswith("conditional | "))
                found += 1
        self.assertEqual(found, 2)

    def test_template_and_policy_exist(self):
        self.assertTrue((ROOT / "docs/research/benchmarks/_template.md").is_file())
        self.assertTrue((ROOT / "docs/process/rea-policy.md").is_file())


class CheckTextTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(c.check_text(GOOD), [])

    def test_empty_is_error(self):
        self.assertTrue(c.check_text("# only comment\n"))

    def test_wrong_field_count(self):
        self.assertTrue(c.check_text("allow | oss-permissive | x"))

    def test_class_must_match_kind(self):
        self.assertTrue(c.check_text(edit(cls="allow", kind="oss-copyleft")))
        self.assertTrue(c.check_text(edit(cls="conditional", kind="oss-permissive")))

    def test_unknown_kind_and_class(self):
        self.assertTrue(c.check_text(edit(kind="proprietary-game")))
        self.assertTrue(c.check_text(edit(cls="forbid")))

    def test_bad_date(self):
        self.assertTrue(c.check_text(edit(date="2026-13-01")))
        self.assertTrue(c.check_text(edit(date="2026-1-1")))

    def test_url_must_be_https(self):
        self.assertTrue(c.check_text(edit(url="http://example.com")))

    def test_proprietary_games_rejected(self):
        for name in ("Kerbal Space Program", "Space Engineers", "https://store.steampowered.com/app/Besiege", "Juno New Origins"):
            self.assertTrue(c.check_text(edit(target=name)), name)

    def test_duplicate_target(self):
        self.assertTrue(c.check_text(GOOD + "\n" + GOOD))


if __name__ == "__main__":
    unittest.main()
