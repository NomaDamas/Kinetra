# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Offline checks for spikes/godot-jolt/scale.py (no Godot binary needed). Run from the repo root:

    uv run spikes/godot-jolt/test_scale.py

They assert that the driver compares and parses what it claims to; no speed or hash value is asserted.
"""
import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
