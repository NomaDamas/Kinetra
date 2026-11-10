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
import subprocess
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
        self.assertIs(r["identical"], False)  # DEMO: deliberately broken (P0-04e), never merge
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

    def test_completed_scene_accounting(self):
        args = tiny_args(0.1)
        r = scale.run_once(args, "pile", 5)
        self.assertFalse(r["capped_by_wall"])
        self.assertEqual(r["steps"], r["steps_target"])
        self.assertEqual(r["steps_target"], round(0.1 / args.timestep))
        self.assertAlmostEqual(r["sim_s"], r["steps"] * args.timestep, places=6)
        self.assertGreater(r["wall_s"], 0)
        # wall_s is rounded to 4 decimals before reporting, so rtf (computed from the
        # unrounded wall time, then rounded to 4 decimals) must lie in the interval
        # implied by wall_s +- 0.00005.
        lo = r["sim_s"] / (r["wall_s"] + 5e-5) - 1e-4
        hi = r["sim_s"] / (r["wall_s"] - 5e-5) + 1e-4
        self.assertTrue(lo <= r["rtf"] <= hi, (lo, r["rtf"], hi))

    def test_break_records_100_releases(self):
        r = scale.run_once(tiny_args(1.3), "break", 0)
        self.assertEqual(r["n_welds_total"], 100)
        self.assertEqual(r["n_welds_released"], 100)
        self.assertGreater(r["ncon_max_sampled"], 0)
        self.assertFalse(r["capped_by_wall"])


class CliTest(unittest.TestCase):
    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scale.py"), *extra],
            capture_output=True, text=True,
        )

    def test_repeats_zero_rejected(self):
        p = self.run_cli("--bodies", "5", "--no-break", "--repeats", "0")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--repeats", p.stderr)

    def test_repeats_negative_rejected(self):
        self.assertNotEqual(self.run_cli("--repeats", "-1").returncode, 0)

    def run_guarded(self, *extra):
        # 어떤 머신에서도 차단되도록 SSD 여유 임계를 비현실적으로 높인 설정 (P0-09)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "g.toml")
            src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "dev", "resource_guard.toml")
            with open(src, encoding="utf-8") as f:
                text = f.read()
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(text.replace("ssd_free_gib_block_below = 10", "ssd_free_gib_block_below = 100000000"))
            env = dict(os.environ, KINETRA_GUARD_CONFIG=cfg)
            return subprocess.run(
                [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scale.py"), *extra],
                capture_output=True, text=True, env=env,
            )

    def test_heavy_run_is_blocked_by_resource_guard_before_any_work(self):
        p = self.run_guarded("--bodies", "1000", "--no-break")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("결과: 차단", p.stdout)
        self.assertNotIn('"machine"', p.stdout)  # 측정 시작 전에 끝났다

    def test_heavy_break_pile_is_also_guarded(self):
        p = self.run_guarded("--bodies", "5", "--break-pile", "1000")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_light_run_does_not_call_the_guard(self):
        p = self.run_guarded("--bodies", "5", "--no-break", "--repeats", "1", "--sim-seconds", "0.02")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("자원 가드", p.stdout)


if __name__ == "__main__":
    unittest.main()
