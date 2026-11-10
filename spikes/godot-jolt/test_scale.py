# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Offline checks for spikes/godot-jolt/scale.py (no Godot binary needed). Run from the repo root:

    uv run spikes/godot-jolt/test_scale.py

They assert that the driver compares and parses what it claims to, and that the committed results/a0-03a-main.json
still carries the A0-03a DoD facts (scenes present, 100/100 breaks, hash flags, RTF with load average). No speed value is
asserted against a threshold and no new measurement is taken.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scale  # noqa: E402


def run(cps):
    return {"checkpoints": cps}


class CompareTest(unittest.TestCase):
    def test_identical(self):
        r = scale.compare([run(["a", "b", "c"]), run(["a", "b", "c"])])
        self.assertIs(r["identical"], True)
        self.assertEqual(r["checkpoints_compared"], 3)

    def test_common_prefix_only(self):
        r = scale.compare([run(["a", "b", "c"]), run(["a", "b"])])
        self.assertIs(r["identical"], True)
        self.assertEqual(r["checkpoints_compared"], 2)

    def test_difference_is_reported_with_first_index(self):
        r = scale.compare([run(["a", "b", "c"]), run(["a", "x", "c"])])
        self.assertIs(r["identical"], False)
        self.assertEqual(r["first_diff_checkpoint"], 1)

    def test_single_run_or_empty_is_not_comparable(self):
        self.assertIsNone(scale.compare([run(["a"])])["identical"])
        self.assertIsNone(scale.compare([run([]), run([])])["identical"])
        self.assertIsNone(scale.compare([])["identical"])


class ParseTest(unittest.TestCase):
    def test_last_result_line_wins(self):
        out = 'noise\nRESULT {"rtf": 1.5, "checkpoints": ["a"]}\nERROR: x\nRESULT {"rtf": 2.5, "checkpoints": []}\n'
        self.assertEqual(scale.parse_result(out)["rtf"], 2.5)

    def test_no_result_line(self):
        self.assertIsNone(scale.parse_result("Godot Engine v4\nERROR: boom\n"))


class CommandTest(unittest.TestCase):
    def test_scene_args(self):
        self.assertEqual(scale.scene_args("pile", 200), ["--scene", "pile", "--n", "200"])
        self.assertEqual(scale.scene_args("break", 1000), ["--scene", "break", "--pile", "1000"])

    def test_command_runs_headless_500hz_with_script(self):
        cmd = scale.godot_cmd(scale.Path("/g"), scale.Path("/p"), "pile", 200, 2.0, 60.0, 10, 0, [])
        self.assertIn("--headless", cmd)
        self.assertEqual(cmd[cmd.index("--fixed-fps") + 1], "500")
        self.assertTrue(cmd[cmd.index("--script") + 1].endswith("scale.gd"))
        self.assertEqual(cmd[cmd.index("--") + 1:cmd.index("--") + 5], ["--scene", "pile", "--n", "200"])

    def test_missing_godot_stops_with_exit_4(self):
        self.assertEqual(scale.main(["--godot", "/nonexistent/godot", "--bodies", "5", "--no-break"]), 4)

    def test_repeats_must_be_positive(self):
        with self.assertRaises(SystemExit):
            scale.main(["--repeats", "0"])


class HeavyThresholdTest(unittest.TestCase):
    """The heavy-run guard counts every simulated body (pile + the break scene's 100 cubes), not the larger of the two."""

    def test_total_bodies_adds_break_cubes(self):
        self.assertEqual(scale.total_bodies("pile", 900), 900)
        self.assertEqual(scale.total_bodies("break", 0), 100)
        self.assertEqual(scale.total_bodies("break", 900), 1000)

    def test_pile_900_plus_break_is_guarded(self):
        with tempfile.NamedTemporaryFile() as fake_godot, mock.patch.object(
                scale.resource_guard, "guard_or_exit", side_effect=SystemExit(3)) as guard:
            with self.assertRaises(SystemExit):
                scale.main(["--godot", fake_godot.name, "--bodies", "200", "--break-pile", "900"])
        guard.assert_called_once_with("heavy")

    def test_below_threshold_is_not_guarded(self):
        with tempfile.NamedTemporaryFile() as fake_godot, mock.patch.object(
                scale.resource_guard, "guard_or_exit") as guard, mock.patch.object(
                scale, "run_once", side_effect=RuntimeError("stop")):
            with self.assertRaises(RuntimeError):
                scale.main(["--godot", fake_godot.name, "--bodies", "200", "--break-pile", "899"])
        guard.assert_not_called()

    def test_godot_script_uses_the_same_total(self):
        src = (Path(scale.HERE) / "scale.gd").read_text()
        self.assertIn("n_pile + n_break >= HEAVY_BODIES", src)
        self.assertIn("n_break = 100", src)


class CommittedResultsTest(unittest.TestCase):
    """DoD facts of the committed full-matrix run (results/a0-03a-main.json): offline, reads the file only."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads((Path(scale.HERE) / "results" / "a0-03a-main.json").read_text())
        cls.entries = {e["label"]: e for e in cls.doc["results"]}

    def test_required_scenes_present(self):
        for label in ("pile-200", "pile-1000", "pile-5000", "break-0", "break-1000"):
            self.assertIn(label, self.entries)
        for label, n in (("pile-200", 200), ("pile-1000", 1000), ("pile-5000", 5000)):
            self.assertEqual({r["n_bodies"] for r in self.entries[label]["runs"]}, {n}, label)

    def test_every_break_run_processed_all_100_joints(self):
        for label in ("break-0", "break-1000"):
            e = self.entries[label]
            for r in [*e["runs"], e["threads1_run"]]:
                self.assertEqual((r["n_joints_total"], r["n_joints_released"], r["joints_alive"]), (100, 100, 0), label)
                self.assertEqual(r["n_break_cubes"], 100, label)
                self.assertTrue(r["finite"], label)
        self.assertEqual(self.entries["break-1000"]["runs"][0]["n_bodies"], 1100)

    def test_same_build_hash_flags_true(self):
        for label, e in self.entries.items():
            self.assertIs(e["determinism"]["identical"], True, label)
            self.assertGreater(e["determinism"]["checkpoints_compared"], 0, label)
            self.assertIs(e["determinism_threads1_vs_default"]["identical"], True, label)

    def test_rtf_recorded_with_load_average(self):
        for label, e in self.entries.items():
            for r in [*e["runs"], e["threads1_run"]]:
                self.assertGreater(r["rtf"], 0, label)
                self.assertEqual(len(r["loadavg_before"]), 3, label)
                self.assertEqual(len(r["loadavg_after"]), 3, label)


if __name__ == "__main__":
    unittest.main()
