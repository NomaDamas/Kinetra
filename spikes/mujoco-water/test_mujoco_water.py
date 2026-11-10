"""Offline checks for mujoco_water.py. Run from the repo root:

    uv run spikes/mujoco-water/test_mujoco_water.py

or  uv run --no-project --with mujoco==4.0.0 --with numpy==2.5.4 python -m unittest discover -s spikes/mujoco-water

These assert that the harness measures what it claims (clipping geometry, equilibrium draft within the issue's
1% bound, hash equality of repeated runs, MuJoCo's medium being position-independent). They assert no speed.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mujoco_water as mw  # noqa: E402

EYE = np.eye(3).ravel()
UNIT = np.array([0.5, 0.5, 0.5])


class ClipTest(unittest.TestCase):
    def setUp(self):
        self.w = mw.Water(0, 2, 0, 2, -1.0, 0.0)

    def test_closed_form_cases(self):
        for row in mw.clip_checks()[:-1]:
            self.assertAlmostEqual(row["volume"], row["volume_expected"], places=12, msg=row["case"])
            if row["centroid_err_m"] is not None:
                self.assertLess(row["centroid_err_m"], 1e-12, row["case"])

    def test_tilted_box_matches_grid_within_one_percent(self):
        row = mw.clip_checks()[-1]
        self.assertLess(row["volume_abs_err"] / row["volume_expected"], 0.01)
        self.assertLess(row["centroid_err_m"], 0.005)

    def test_no_water_outside_body(self):
        for ctr in ([1, 1, 1.0], [1, 1, -2.5], [5, 1, -0.5], [-3, 1, -0.5], [1, 5, -0.5]):
            v, c = mw.submerged_box(self.w, np.array(ctr, float), EYE, UNIT)
            self.assertEqual((v, c), (0.0, None), ctr)


class MediumTest(unittest.TestCase):
    def test_mujoco_medium_is_global_and_has_no_buoyancy(self):
        f = mw.medium_facts()
        self.assertTrue(f["box_force_equal_at_z+5_and_z-5"])  # same drag above and below any "surface"
        self.assertEqual(f["at_rest"]["qfrc_fluid_absmax"], 0.0)  # no buoyancy: nothing at rest
        self.assertTrue(f["ellipsoid_force_equal_at_z+5_and_z-5"])
        self.assertEqual(f["at_rest"]["qacc_z"], [-9.81] * 4)  # free fall unchanged in a dense medium: no buoyancy,
        # and no -m_a*a added-mass term even for the ellipsoid sphere (m_a = m here)
        self.assertEqual(f["density_type"], "float")


class DraftTest(unittest.TestCase):
    def test_equilibrium_draft_within_one_percent_both_paths(self):
        water = mw.Water(-5, 5, -5, 5, -3.0, 0.0)
        box = {"half": (0.2, 0.2, 0.1), "density": 400.0, "pos": (0, 0, 0.1), "quat": (1, 0, 0, 0)}
        for path in ("xfrc", "xfrc_step12", "passive"):
            r = mw.run_boxes([box], water, path, 0.002, 4000)
            draft = -(r["data"].qpos[2] - 0.1)
            self.assertLess(abs(draft - 0.08) / 0.08, 0.01, path)

    def test_repeat_run_hash_equal(self):
        water = mw.Water(-1, 1, -1, 1, -1.0, 0.0)
        boxes = mw.nbox_scene(4, 0)
        for path in ("xfrc", "xfrc_step12", "passive"):
            a = mw.run_boxes(boxes, water, path, 0.002, 200, floor_z=-1.0)["hash"]
            b = mw.run_boxes(boxes, water, path, 0.002, 200, floor_z=-1.0)["hash"]
            self.assertEqual(a, b, path)

    def test_step12_path_sees_current_poses_like_passive(self):
        water = mw.Water(-1, 1, -1, 1, -1.0, 0.0)
        boxes = mw.nbox_scene(6, 0)
        q = {p: mw.run_boxes(boxes, water, p, 0.002, 150, floor_z=-1.0)["qpos"] for p in ("xfrc_step12", "passive")}
        self.assertLess(np.abs(q["xfrc_step12"] - q["passive"]).max(), 1e-9)

    def test_added_mass_acceleration_matches_theory_when_stable(self):
        r = mw.sphere_run("twopass", 0.75, 0.002, 100, sample=(50, 100))
        a = (r["v"][100] - r["v"][50]) / (50 * 0.002)
        a_exp = mw.G * (1 - 0.75) / (0.75 + mw.ADDED_MASS_SPHERE)
        self.assertLess(abs(a - a_exp) / a_exp, 0.01)


if __name__ == "__main__":
    unittest.main()
