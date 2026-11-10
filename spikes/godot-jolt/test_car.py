# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""Offline checks for spikes/godot-jolt/car.py (no Godot binary needed). Run from the repo root:

    uv run spikes/godot-jolt/test_car.py

They assert that the comparison measures what it claims; no trajectory-difference value is asserted.
"""
import json
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import car  # noqa: E402


def traj(rows):
    return np.array(rows, dtype=float)


class ParamsTest(unittest.TestCase):
    def test_committed_params_match_generator(self):
        self.assertEqual(car.load_params(), json.loads(json.dumps(car.make_params())))

    def test_slope_start_is_on_the_incline_with_clearance(self):
        p = car.load_params()
        s = p["scenes"]["slope"]
        # distance of the chassis center to the tilted plane through the origin, along its normal
        n = car.quat_rotate(s["ground_quat_wxyz"], [0, 0, 1])
        h = sum(a * b for a, b in zip(s["chassis_pos"], n))
        self.assertAlmostEqual(h, 0.2 + 0.0005, places=9)
        self.assertAlmostEqual(math.degrees(math.acos(n[2])), 10.0, places=6)


class MujocoSceneTest(unittest.TestCase):
    def test_drop_lands_and_stays_finite(self):
        p = car.load_params()
        p["scenes"]["drop"]["steps"] = 600
        t = car.run_mujoco(p, "drop")
        self.assertEqual(t.shape, (601, 7))
        self.assertTrue(np.isfinite(t).all())
        self.assertLess(t[-1, 2], 0.3)  # fell from 1.2 m to rest on the wheels (center ~0.2 m)
        self.assertGreater(t[-1, 0], 0.5)  # kept its 1 m/s forward speed

    def test_same_run_twice_is_identical(self):
        p = car.load_params()
        p["scenes"]["slope"]["steps"] = 200
        a, b = car.run_mujoco(p, "slope"), car.run_mujoco(p, "slope")
        self.assertTrue(np.array_equal(a, b))

    def test_drive_torque_moves_the_car_uphill(self):
        p = car.load_params()
        p["scenes"]["slope"]["steps"] = 500
        driven = car.run_mujoco(p, "slope")
        p["scenes"]["slope"]["drive_torque_per_wheel"] = 0.0
        free = car.run_mujoco(p, "slope")
        self.assertGreater(driven[-1, 0], free[-1, 0])


class DiffTest(unittest.TestCase):
    def test_identical_is_zero(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0], [1, 0, 0, 1, 0, 0, 0]])
        d = car.diff(a, a)
        self.assertEqual(d["pos_max_m"], 0.0)
        self.assertEqual(d["ang_max_rad"], 0.0)

    def test_position_and_rotation_difference(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0], [1, 0, 0, 1, 0, 0, 0]])
        half = math.sin(0.05)  # rotation of 0.1 rad about z
        b = traj([[0, 0, 0, 1, 0, 0, 0], [1, 0.25, 0, math.cos(0.05), 0, 0, half]])
        d = car.diff(a, b)
        self.assertAlmostEqual(d["pos_max_m"], 0.25)
        self.assertEqual(d["pos_max_step"], 1)
        self.assertAlmostEqual(d["ang_max_rad"], 0.1, places=9)
        self.assertAlmostEqual(d["path_length_m"], 1.0)

    def test_q_and_minus_q_are_the_same_rotation(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0]])
        b = traj([[0, 0, 0, -1, 0, 0, 0]])
        self.assertAlmostEqual(car.diff(a, b)["ang_max_rad"], 0.0, places=7)

    def test_truncated_trajectory_is_an_error(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0]] * 5)
        b = traj([[0, 0, 0, 1, 0, 0, 0]] * 3)
        with self.assertRaises(ValueError):
            car.diff(a, b)
        with self.assertRaises(ValueError):
            car.diff(b, a)

    def test_same_length_compares_every_row(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0]] * 3)
        self.assertEqual(car.diff(a, a)["rows"], 3)


class RequireFullTest(unittest.TestCase):
    def test_full_trajectory_passes(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0]] * 4)
        self.assertIs(car.require_full("t", a, 3), a)

    def test_short_or_long_is_an_error(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0]] * 3)
        with self.assertRaises(ValueError):
            car.require_full("t", a, 3)
        with self.assertRaises(ValueError):
            car.require_full("t", a, 1)

    def test_non_finite_is_an_error(self):
        a = traj([[0, 0, 0, 1, 0, 0, 0], [float("nan"), 0, 0, 1, 0, 0, 0]])
        with self.assertRaises(ValueError):
            car.require_full("t", a, 1)

    def test_committed_scene_step_counts_match_mujoco_rows(self):
        p = car.load_params()
        for scene in p["scenes"]:
            traj_ = car.run_mujoco(p, scene)
            car.require_full(scene, traj_, int(p["scenes"][scene]["steps"]))
            car.require_full(scene + " dt0.001", car.run_mujoco(p, scene, timestep=0.001)[::2], int(p["scenes"][scene]["steps"]))


class CsvTest(unittest.TestCase):
    def test_read_godot_csv(self, tmp=None):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("step,x,y,z,qw,qx,qy,qz\n0,1,2,3,1,0,0,0\n1,1.5,2,3,1,0,0,0\n")
            name = f.name
        try:
            r = car.read_godot_csv(car.Path(name))
        finally:
            os.unlink(name)
        self.assertEqual(r.shape, (2, 7))
        self.assertEqual(r[1, 0], 1.5)

    def _read(self, text):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(text)
            name = f.name
        try:
            return car.read_godot_csv(car.Path(name))
        finally:
            os.unlink(name)

    def test_missing_middle_row_is_an_error(self):
        with self.assertRaises(ValueError):
            self._read("step,x,y,z,qw,qx,qy,qz\n0,1,2,3,1,0,0,0\n2,1.5,2,3,1,0,0,0\n")

    def test_single_row_keeps_two_dimensions(self):
        self.assertEqual(self._read("step,x,y,z,qw,qx,qy,qz\n0,1,2,3,1,0,0,0\n").shape, (1, 7))


class WebSceneTest(unittest.TestCase):
    def test_world3d_is_held_as_a_member_for_the_scene_lifetime(self):
        src = (car.HERE / "web" / "main.gd").read_text()
        self.assertRegex(src, r"(?m)^var world: World3D")
        self.assertIn("world = World3D.new()", src)
        self.assertNotIn("var w := World3D.new()", src)


if __name__ == "__main__":
    unittest.main()
