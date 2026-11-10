"""오프라인 테스트: uv run --with pyyaml python -m unittest discover -s scripts/gh/tests -v"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import bootstrap  # noqa: E402

FIXTURE = HERE / "fixture.yaml"
REAL = HERE.parents[2] / "docs" / "plan" / "issues.yaml"


class PlanTests(unittest.TestCase):
    def test_real_issues_yaml_loads(self):
        labels, milestones = bootstrap.load_spec(REAL)
        self.assertGreater(len(labels), 0)
        self.assertGreater(len(milestones), 0)

    def test_plan_create_update_keep(self):
        labels, ms = bootstrap.load_spec(FIXTURE)
        have_l = [
            {"name": "type:a", "color": "1D76DB", "description": "A"},  # same (color case-insensitive)
            {"name": "area:b", "color": "000000", "description": "B"},  # name case-insensitive, color differs
        ]
        have_m = [{"number": 7, "title": "S0", "description": "zero"}, {"number": 8, "title": "S1", "description": "old"}]
        acts = [(a[0], a[1], a[2].get("name") or a[2]["title"]) for a in bootstrap.plan(labels, ms, have_l, have_m)]
        self.assertEqual(
            acts,
            [
                ("keep", "label", "type:a"),
                ("update", "label", "Area:B"),
                ("create", "label", "prio:P0"),
                ("keep", "milestone", "S0"),
                ("update", "milestone", "S1"),
                ("create", "milestone", "S2"),
            ],
        )

    def test_bad_color_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write('labels: [{name: x, color: "zzz", description: d}]\nmilestones: [{title: m}]\n')
        with self.assertRaises(bootstrap.SpecError):
            bootstrap.load_spec(Path(f.name))
        os.unlink(f.name)


class IdempotenceTests(unittest.TestCase):
    """bootstrap.py 를 실제 프로세스로 두 번 돌리고, PATH 의 fake gh 상태로 중복 없음을 확인한다."""

    def run_bootstrap(self, env, *extra):
        r = subprocess.run(
            [sys.executable, str(HERE.parent / "bootstrap.py"), "--file", str(FIXTURE), *extra],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_second_run_is_noop_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            shim = d / "gh"
            shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_gh.py"}" "$@"\n')
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            state = d / "state.json"
            state.write_text(json.dumps({
                "labels": [{"name": "bug", "color": "d73a4a", "description": "x"}, {"name": "type:a", "color": "ffffff", "description": "A"}],
                "milestones": [{"number": 1, "title": "S0", "description": "stale"}],
            }))
            env = {**os.environ, "PATH": f"{d}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_STATE": str(state)}

            dry = self.run_bootstrap(env, "--dry-run")
            self.assertIn("(dry-run)", dry)
            self.assertEqual(len(json.loads(state.read_text())["labels"]), 2, "dry-run 은 변경하면 안 된다")

            first = self.run_bootstrap(env)
            self.assertIn("labels create=2 update=1 keep=0", first)
            self.assertIn("milestones create=2 update=1 keep=0", first)
            after1 = json.loads(state.read_text())
            self.assertEqual(len(after1["labels"]), 4)  # bug + 3
            self.assertEqual(len(after1["milestones"]), 3)

            second = self.run_bootstrap(env)
            self.assertIn("labels create=0 update=0 keep=3", second)
            self.assertIn("milestones create=0 update=0 keep=3", second)
            self.assertEqual(json.loads(state.read_text()), after1)


if __name__ == "__main__":
    unittest.main()
