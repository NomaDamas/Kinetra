"""Offline checks for recompile.py. Run from the repo root:

    uv run spikes/mujoco-limits/test_recompile.py

They assert that the harness measures what it claims on a tiny assembly (3 parts): the model has
the expected size, every MjSpec operation it reports as working really changed the model, the old
state survived, and the CLI rejects bad counts. They do not assert any time value.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recompile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class AssemblyTest(unittest.TestCase):
    def test_build_has_two_bodies_per_part_and_seven_dofs(self):
        model = recompile.build(3, 0).compile()
        self.assertEqual(model.nbody, 1 + 2 * 3)
        self.assertEqual(model.nv, 7 * 3)
        self.assertEqual(model.nmesh, 3)

    def test_parts_do_not_overlap_at_start(self):
        model = recompile.build(9, 0).compile()
        data = recompile.mujoco.MjData(model)
        recompile.mujoco.mj_forward(model, data)
        self.assertEqual(data.ncon, 0)

    def test_build_is_seeded(self):
        a = recompile.build(2, 5).to_xml()
        b = recompile.build(2, 5).to_xml()
        c = recompile.build(2, 6).to_xml()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class RunOnceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = recompile.run_once(3, 0)

    def test_all_api_calls_worked(self):
        failed = {k: v for k, v in self.r["api"].items() if not v["ok"]}
        self.assertEqual(failed, {})
        self.assertIn("recompile(add part)", self.r["api"])
        self.assertIn("recompile(remove part)", self.r["api"])

    def test_recompiles_changed_the_model_as_claimed(self):
        self.assertTrue(self.r["edit_size_applied"])
        self.assertTrue(self.r["edit_nbody_ok"])
        self.assertTrue(self.r["add_nbody_ok"])
        self.assertTrue(self.r["remove_nbody_ok"])
        self.assertTrue(self.r["xml_nbody_matches"])
        self.assertTrue(self.r["recompile_returns_new_objects"])
        self.assertTrue(self.r["old_model_unchanged"])

    def test_state_survives_recompile(self):
        for k in ("edit_state_kept", "add_state_kept", "remove_state_kept"):
            self.assertTrue(self.r[k], k)

    def test_timings_are_positive(self):
        for k in recompile.TIMED:
            self.assertGreater(self.r[k], 0, k)

    def test_records_load_and_swap(self):
        for k in ("load_before", "load_after"):
            self.assertEqual(len(self.r[k]["loadavg"]), 3)
            self.assertIn("total", self.r[k]["swap"])


class KeepStateTest(unittest.TestCase):
    def test_detects_changed_state(self):
        np = recompile.np
        model = recompile.build(1, 0).compile()
        d = recompile.mujoco.MjData(model)
        old = recompile.snapshot(d)
        self.assertTrue(recompile.keep_state(old, d, model.nq, model.nv))
        d.qpos[0] += 1.0
        self.assertFalse(recompile.keep_state(old, d, model.nq, model.nv))
        d.qpos[:] = old["qpos"]
        d.time = 1.0
        self.assertFalse(recompile.keep_state(old, d, model.nq, model.nv))
        self.assertIsNotNone(np)


class CliTest(unittest.TestCase):
    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "recompile.py"), *extra], capture_output=True, text=True
        )

    def test_rejects_zero_repeats_and_parts(self):
        self.assertNotEqual(self.run_cli("--repeats", "0").returncode, 0)
        self.assertNotEqual(self.run_cli("--parts", "0").returncode, 0)


if __name__ == "__main__":
    unittest.main()
