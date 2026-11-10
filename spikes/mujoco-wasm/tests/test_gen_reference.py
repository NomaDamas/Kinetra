# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""Offline checks for gen_reference.py: `uv run spikes/mujoco-wasm/tests/test_gen_reference.py`.
They assert the harness reproduces what it claims (legacy model hash, legacy hero schedule, repeatable run,
committed reference files match a regeneration). They do not assert any speed value."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import gen_reference as g  # noqa: E402


class ReferenceTest(unittest.TestCase):
    def test_model_hash_is_the_legacy_one(self):
        self.assertEqual(hashlib.sha256(g.MODEL_XML.read_bytes()).hexdigest(), g.LEGACY_MODEL_SHA256)

    def test_controls_follow_the_legacy_windows(self):
        sc = g.scenarios()[0]
        ctrl = g.controls(sc["windows"])
        self.assertEqual(ctrl.shape, (g.NSTEP, 18))
        k_on = int(round(1.35485 / g.DT))  # pitch_fwd_outer opens at 1.35485 s -> thrusters 0, 1 (group 0)
        self.assertEqual(ctrl[k_on - 2, 0], 0.0)
        self.assertAlmostEqual(ctrl[k_on + 2, 0], 0.96476)
        self.assertAlmostEqual(ctrl[k_on + 2, 1], 0.96476)
        self.assertTrue(np.all(ctrl >= 0) and np.all(ctrl <= 1.0 + 1e-12))

    def test_scenarios_are_seeded(self):
        a, b = g.scenarios(), g.scenarios()
        self.assertEqual(json.dumps(a), json.dumps(b))
        self.assertEqual(len(a), 1 + g.N_VARIANTS)

    def test_initial_state_is_the_ramp_lip(self):
        q, v = g.initial_state()
        self.assertEqual(list(q[:3]), [0.0, 0.0, 2.2])
        self.assertAlmostEqual(np.linalg.norm(v[:3]), 22.0)
        self.assertAlmostEqual(float(np.linalg.norm(q[3:7])), 1.0)

    def test_short_run_is_bitwise_repeatable_and_leaves_the_ramp(self):
        sc = g.scenarios()[0]
        ctrl = g.controls(sc["windows"])
        q0, v0 = g.initial_state()
        a, _ = g.run(ctrl, q0, v0)
        b, _ = g.run(ctrl, q0, v0)
        self.assertTrue(np.array_equal(a, b))
        self.assertGreater(a[-1, 0], 40.0)  # ~22 m/s for 4.5 s

    def test_committed_reference_matches_regeneration(self):
        manifest, blob = g.build()
        stored = json.loads((HERE / "reference" / "manifest.json").read_text())
        self.assertEqual([e["qpos_sha256"] for e in stored["scenarios"]], [e["qpos_sha256"] for e in manifest["scenarios"]])
        self.assertEqual(hashlib.sha256((HERE / "reference" / "native_qpos.f64").read_bytes()).hexdigest(), hashlib.sha256(blob.tobytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
