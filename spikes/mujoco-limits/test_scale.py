"""Offline checks for scale.py. Run from the repo root:

    uv run spikes/mujoco-limits/test_scale.py          (needs no network once deps are cached)

or  uv run --no-project --with mujoco==4.0.0 --with numpy==2.5.4 python -m unittest discover -s spikes/mujoco-limits

These assert that the harness measures what it claims. They do not assert any
speed or hash value.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
import argparse
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scale  # noqa: E402


def run(cps):
    return {"checkpoints": cps}


def tiny_args(sim_seconds):
    return argparse.Namespace(
        seed=0, timestep=0.002, integrator="Euler", sim_seconds=sim_seconds,
        wall_cap=120.0, hash_every=10,
    )


class CompareTest(unittest.TestCase):
    def test_identical(self):
        r = scale.compare([run(["a", "b", "c"]), run(["a", "b", "c"])])
        self.assertIs(r["identical"], True)
        self.assertEqual(r["checkpoints_compared"], 3)

    def test_common_prefix_identical(self):
        r = scale.compare([run(["a", "b", "c"]), run(["a", "b"])])
        self.assertIs(r["identical"], True)
        self.assertEqual(r["checkpoints_compared"], 2)

    def test_mismatch(self):
        r = scale.compare([run(["a", "b", "c"]), run(["a", "x", "c"])])
        self.assertIs(r["identical"], False)

    def test_single_run_not_comparable(self):
        self.assertIsNone(scale.compare([run(["a", "b"])])["identical"])

    def test_no_runs_not_comparable(self):
        self.assertIsNone(scale.compare([])["identical"])

    def test_empty_checkpoints_not_comparable(self):
        r = scale.compare([run([]), run([])])
        self.assertIsNone(r["identical"])
        self.assertEqual(r["checkpoints_compared"], 0)
        self.assertIsNone(scale.compare([run(["a"]), run([])])["identical"])


class SceneTest(unittest.TestCase):
    def test_pile_has_contacts_and_repeats_identically(self):
        a = scale.run_once(tiny_args(0.4), "pile", 20)
        b = scale.run_once(tiny_args(0.4), "pile", 20)
        self.assertEqual(a["n_bodies"], 20)
        self.assertGreater(a["ncon_max_sampled"], 0)
        self.assertTrue(a["finite"])
        self.assertIs(scale.compare([a, b])["identical"], True)

    def test_break_records_100_releases(self):
        r = scale.run_once(tiny_args(1.3), "break", 0)
        self.assertEqual(r["n_welds_total"], 100)
        self.assertEqual(r["n_welds_released"], 100)
        self.assertGreater(r["ncon_max_sampled"], 0)
        self.assertFalse(r["capped_by_wall"])


if __name__ == "__main__":
    unittest.main()
