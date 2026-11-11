# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""Offline checks for gen_replay.py: `uv run spikes/web-client/tests/test_gen_replay.py`.
They assert the committed bundle is what the generator makes from the committed native trajectory. No speed values."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import gen_replay as g  # noqa: E402

bundle = json.loads((HERE / "replay" / "bundle.json").read_text())
poses_bytes = (HERE / "replay" / "poses.bin").read_bytes()
poses = np.frombuffer(poses_bytes, dtype="<f4").reshape(bundle["n_frames"], len(bundle["bodies"]), 7)


class BundleTest(unittest.TestCase):
    def test_committed_bytes_match_their_declared_hash_and_size(self):
        self.assertEqual(hashlib.sha256(poses_bytes).hexdigest(), bundle["poses_sha256"])
        self.assertEqual(len(poses_bytes), bundle["poses_bytes"])
        self.assertEqual(len(poses_bytes), bundle["n_frames"] * len(bundle["bodies"]) * 28)
        self.assertEqual(bundle["n_frames"], 1126)  # 1,125 steps + the state before step 0

    def test_inputs_are_the_documented_ones(self):
        p = bundle["provenance"]
        self.assertEqual(p["model_sha256"], p["legacy_model_hash"])
        self.assertEqual(hashlib.sha256(g.WASM.joinpath("model", "rocket_car.xml").read_bytes()).hexdigest(), p["model_sha256"])
        self.assertEqual(p["mujoco"], "4.0.0")
        self.assertEqual(bundle["label"], "1회 실행. 판정이 아닙니다")

    def test_regeneration_matches_committed_within_float32_noise(self):
        # Same platform: identical bytes. Another platform: the recorded qpos is the committed file, only mj_kinematics runs,
        # so differences are at most a float32 rounding step.
        data, b = g.build()
        again = np.frombuffer(data, dtype="<f4").reshape(poses.shape)
        self.assertLess(float(np.max(np.abs(again - poses))), 1e-5)
        self.assertEqual(b["provenance"]["source_qpos_sha256"], bundle["provenance"]["source_qpos_sha256"])

    def test_poses_are_finite_unit_quaternions_and_start_state_is_the_legacy_one(self):
        self.assertTrue(np.all(np.isfinite(poses)))
        q = np.linalg.norm(poses[..., 3:], axis=-1)
        self.assertLess(float(np.max(np.abs(q - 1))), 1e-6)
        np.testing.assert_allclose(poses[0, 0, :3], [0, 0, 2.2], atol=1e-6)  # ramp end height 2.2 m (gen_reference.py qpos0)
        # wheels sit at the body-frame offsets (1.3, +-0.85, -0.28) from the car at frame 0
        car = poses[0, 0, :3]
        from math import cos, sin, radians
        th = radians(-25)
        R = np.array([[cos(th), 0, sin(th)], [0, 1, 0], [-sin(th), 0, cos(th)]])  # qpos0 quaternion (cos, 0, -0.2164, 0) = -25 deg about y
        np.testing.assert_allclose(poses[0, 1, :3] - car, R @ np.array([1.3, 0.85, -0.28]), atol=1e-4)

    def test_geoms_cover_the_five_bodies_and_the_ground(self):
        shapes = [(x["body"], x["shape"]) for x in bundle["geoms"]]
        self.assertIn(("world", "plane"), shapes)
        self.assertIn(("car", "box"), shapes)
        self.assertEqual(sum(1 for _, s in shapes if s == "cylinder"), 4)


if __name__ == "__main__":
    unittest.main()
