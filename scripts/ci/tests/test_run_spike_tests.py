"""Offline tests for scripts/ci/run_spike_tests.py: `python3 -m unittest discover -s scripts/ci/tests`."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "run_spike_tests.py"
sys.path.insert(0, str(SCRIPT.parent))
import run_spike_tests as r  # noqa: E402


def make(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


class PlanTest(unittest.TestCase):
    def plan(self, files):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make(root, files)
            return {e["name"]: e for e in r.plan(root)}

    def test_python_tests_in_dir_and_tests_subdir(self):
        p = self.plan({"spikes/a/test_x.py": "", "spikes/a/test_y.py": "", "spikes/b/tests/test_z.py": "", "spikes/b/tests/helper.py": "", "spikes/a/scale.py": ""})
        self.assertEqual(p["a"]["steps"], [["uv", "run", "spikes/a/test_x.py"], ["uv", "run", "spikes/a/test_y.py"]])
        self.assertEqual(p["b"]["steps"], [["uv", "run", "spikes/b/tests/test_z.py"]])
        self.assertIsNone(p["a"]["skip"])

    def test_pnpm_spike_installs_then_runs_test_only(self):
        pkg = json.dumps({"scripts": {"test": "node --test", "test:browser": "x", "measure": "y", "dev": "z"}})
        p = self.plan({"spikes/w/package.json": pkg, "spikes/w/pnpm-lock.yaml": ""})
        self.assertEqual(p["w"]["steps"], [["pnpm", "--dir", "spikes/w", "install", "--frozen-lockfile"], ["pnpm", "--dir", "spikes/w", "test"]])

    def test_spike_without_tests_is_skipped_with_reason(self):
        p = self.plan({"spikes/c/notes.md": "", "spikes/d/package.json": json.dumps({"scripts": {"dev": "x"}})})
        for name in ("c", "d"):
            self.assertEqual(p[name]["steps"], [])
            self.assertIn("no test_*.py", p[name]["skip"])

    def test_pnpm_test_script_without_lockfile_is_an_error_not_a_skip(self):
        p = self.plan({"spikes/w/package.json": json.dumps({"scripts": {"test": "x"}})})
        self.assertIsNone(p["w"]["skip"])
        self.assertIn("pnpm-lock.yaml", p["w"]["errors"][0])

    def test_invalid_package_json_is_an_error(self):
        p = self.plan({"spikes/w/package.json": "{"})
        self.assertIn("not valid JSON", p["w"]["errors"][0])

    def test_no_spikes_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(r.plan(Path(d)), [])


class RunTest(unittest.TestCase):
    def run_script(self, files, *extra):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make(root, files)
            return subprocess.run([sys.executable, str(SCRIPT), "--root", d, *extra], capture_output=True, text=True)

    def test_plan_mode_runs_nothing_and_logs_skips(self):
        res = self.run_script({"spikes/a/test_x.py": "raise SystemExit(7)", "spikes/c/notes.md": ""}, "--plan")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PLAN a: uv run spikes/a/test_x.py", res.stdout)
        self.assertIn("SKIP c: no test_*.py", res.stdout)

    def test_only_skipped_spikes_pass(self):
        res = self.run_script({"spikes/c/notes.md": ""})
        self.assertEqual(res.returncode, 0)
        self.assertIn("SKIP c", res.stdout)

    def test_lockfile_error_fails_the_run(self):
        res = self.run_script({"spikes/w/package.json": json.dumps({"scripts": {"test": "x"}})})
        self.assertEqual(res.returncode, 1)
        self.assertIn("pnpm-lock.yaml", res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
