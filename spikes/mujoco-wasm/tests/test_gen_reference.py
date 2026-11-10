# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""Offline checks for gen_reference.py: `uv run spikes/mujoco-wasm/tests/test_gen_reference.py`.
They assert the harness reproduces what it claims (legacy model hash, legacy hero schedule, repeatable run,
committed reference files match a regeneration). They do not assert any speed value."""
import hashlib
import json
import platform
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
        self.assertEqual(a.tobytes(), b.tobytes())  # bytes, not values: -0.0 == 0.0 and NaN != NaN would hide a difference
        self.assertGreater(a[-1, 0], 40.0)  # ~22 m/s for 4.5 s

    def test_committed_reference_matches_regeneration(self):
        manifest, blob = g.build()
        stored = json.loads((HERE / "reference" / "manifest.json").read_text())
        same_platform = platform.platform() == stored["platform"]
        if same_platform:
            # the machine class that wrote the reference: the whole trajectory must be bitwise the same
            self.assertEqual([e["qpos_sha256"] for e in stored["scenarios"]], [e["qpos_sha256"] for e in manifest["scenarios"]])
            self.assertEqual(hashlib.sha256((HERE / "reference" / "native_qpos.f64").read_bytes()).hexdigest(), hashlib.sha256(blob.tobytes()).hexdigest())
            return
        # Another platform (CI is Linux x86-64, the reference was written on macOS arm64). Two things differ there, both
        # numeric-library effects, not bugs: (1) numpy's seeded variants can differ in the last bit (FMA contraction on arm64),
        # so only `nominal` (no random numbers) has an identical control hash; (2) the same mujoco 4.0.0 wheel does not reproduce
        # the post-contact trajectory bitwise (contact makes tiny differences grow). So compare what must still agree: scenario
        # list, windows within 1e-9, the nominal control hash, and the flight before first contact within 1e-6.
        rows, nq = stored["rows_per_scenario"], stored["nq"]
        new = np.frombuffer(blob.tobytes(), dtype="<f8").reshape(len(manifest["scenarios"]), rows, nq)
        old = np.fromfile(HERE / "reference" / "native_qpos.f64", dtype="<f8").reshape(len(stored["scenarios"]), rows, nq)
        self.assertEqual([e["id"] for e in stored["scenarios"]], [e["id"] for e in manifest["scenarios"]])
        self.assertEqual(stored["scenarios"][0]["id"], "nominal")
        self.assertEqual(stored["scenarios"][0]["ctrl_sha256"], manifest["scenarios"][0]["ctrl_sha256"])
        for i, (s_, m_) in enumerate(zip(stored["scenarios"], manifest["scenarios"])):
            for ws, wm in zip(s_["windows"], m_["windows"]):
                for k in ("ts", "dur", "mag"):
                    self.assertAlmostEqual(ws[k], wm[k], delta=1e-9, msg=f"{s_['id']} window {ws['name']} {k}")
            fcs = [c for c in (s_["first_contact_step"], m_["first_contact_step"]) if c >= 0]
            pre = min(fcs) if fcs else rows
            self.assertLess(float(np.abs(old[i, :pre] - new[i, :pre]).max()), 1e-6, f"{s_['id']}: flight before first contact differs across platforms")

if __name__ == "__main__":
    unittest.main()
