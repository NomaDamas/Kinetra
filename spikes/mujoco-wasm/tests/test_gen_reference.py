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


# Cross-platform bounds on max |qpos difference| (m, rad) vs the committed macOS arm64 reference. MEASURED on the CI runner;
# the values and the run link are recorded in REPORT.md.
PRE_CONTACT_BOUND = 1e-9  # measured worst 1.73e-12 (Linux x86-64 CI), ~600x headroom
FULL_BOUND = 5e-3         # measured worst 7.69e-4 (the nominal-with-1e-12-nudge control), 6.5x headroom; see REPORT.md


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
        # Another platform (CI is Linux x86-64, the reference was written on macOS arm64). Bitwise equality with the committed
        # reference cannot be asserted there (see REPORT.md, "Linux x86-64 vs macOS arm64"), so assert instead:
        # (a) within-platform determinism: a second regeneration here is BITWISE identical to the first (trajectories, control
        #     and trajectory hashes), so a real regression cannot hide behind "another platform";
        # (b) the full trajectory (all 1126 rows, all scenarios) stays within the measured cross-platform bound of the committed
        #     reference, and the flight before first contact within PRE_CONTACT_BOUND.
        manifest2, blob2 = g.build()
        self.assertEqual(blob.tobytes(), blob2.tobytes(), "regeneration on this platform is not bitwise repeatable")
        self.assertEqual([e["ctrl_sha256"] for e in manifest["scenarios"]], [e["ctrl_sha256"] for e in manifest2["scenarios"]])
        self.assertEqual([e["qpos_sha256"] for e in manifest["scenarios"]], [e["qpos_sha256"] for e in manifest2["scenarios"]])
        rows, nq = stored["rows_per_scenario"], stored["nq"]
        new = np.frombuffer(blob.tobytes(), dtype="<f8").reshape(len(manifest["scenarios"]), rows, nq)
        old = np.fromfile(HERE / "reference" / "native_qpos.f64", dtype="<f8").reshape(len(stored["scenarios"]), rows, nq)
        # platform-independent integrity of the committed files: every scenario slice of native_qpos.f64 hashes to the
        # committed manifest's qpos_sha256 (same hash as gen_reference.sha256_bytes), and the blob has exactly that many rows
        self.assertEqual(old.size * 8, (HERE / "reference" / "native_qpos.f64").stat().st_size)
        for i, s_ in enumerate(stored["scenarios"]):
            self.assertEqual(g.sha256_bytes(old[i]), s_["qpos_sha256"], f"{s_['id']}: committed blob slice vs manifest hash")
        self.assertEqual([e["id"] for e in stored["scenarios"]], [e["id"] for e in manifest["scenarios"]])
        self.assertEqual(stored["scenarios"][0]["id"], "nominal")
        self.assertEqual(stored["scenarios"][0]["ctrl_sha256"], manifest["scenarios"][0]["ctrl_sha256"])
        worst_full, worst_pre = 0.0, 0.0
        for i, (s_, m_) in enumerate(zip(stored["scenarios"], manifest["scenarios"])):
            for ws, wm in zip(s_["windows"], m_["windows"]):
                for k in ("ts", "dur", "mag"):
                    self.assertAlmostEqual(ws[k], wm[k], delta=1e-9, msg=f"{s_['id']} window {ws['name']} {k}")
            fcs = [c for c in (s_["first_contact_step"], m_["first_contact_step"]) if c >= 0]
            pre = min(fcs) if fcs else rows
            d = np.abs(old[i] - new[i])
            full, pre_d = float(d.max()), float(d[:pre].max())
            print(f"CROSS-PLATFORM {s_['id']}: first_contact old/new {s_['first_contact_step']}/{m_['first_contact_step']} max|dqpos| full={full:.3e} pre-contact={pre_d:.3e}")
            worst_full, worst_pre = max(worst_full, full), max(worst_pre, pre_d)
            self.assertLess(pre_d, PRE_CONTACT_BOUND, f"{s_['id']}: flight before first contact")
            self.assertLess(full, FULL_BOUND, f"{s_['id']}: full trajectory")
        print(f"CROSS-PLATFORM worst: full={worst_full:.3e} pre-contact={worst_pre:.3e} (bounds {FULL_BOUND:g} / {PRE_CONTACT_BOUND:g}) on {platform.platform()}")

if __name__ == "__main__":
    unittest.main()
