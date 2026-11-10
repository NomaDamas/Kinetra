"""가짜 측정값으로 차단·경고·통과를 단언한다. 실제 머신 값에 기대는 단언은 없다.

    uv run pytest tools/dev -q   (저장소 루트에서)
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import resource_guard as rg  # noqa: E402

CFG = rg.load_profile(rg.DEFAULT_CONFIG, "heavy")


def meas(**over):
    m = {"ssd_free_gb": 25.0, "ssd_path": "/x", "swap_used_gb": 4.0, "swap_total_gb": 8.0,
         "swap_used_pct": 50.0, "memory_pressure": "normal", "memory_pressure_detail": "fake"}
    m.update(over)
    return m


def run_main(args, m, measure=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = rg.main(args, measure=measure or (lambda path, cfg: m))
    return code, out.getvalue(), err.getvalue()


class ConfigTests(unittest.TestCase):
    def test_shipped_defaults_are_the_proposed_ones_with_badge(self):
        self.assertEqual(CFG["badge"], "기본값")
        self.assertEqual(CFG["ssd_free_gb_block_below"], 10)
        self.assertEqual(CFG["swap_used_pct_warn_at"], 90)
        self.assertEqual(CFG["memory_pressure_block_at"], "critical")

    def test_unknown_profile_and_missing_key(self):
        with self.assertRaises(rg.GuardError):
            rg.load_profile(rg.DEFAULT_CONFIG, "nope")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text('[profiles.heavy]\nbadge = "기본값"\n')
            with self.assertRaises(rg.GuardError):
                rg.load_profile(p, "heavy")

    def test_bad_level_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            text = rg.DEFAULT_CONFIG.read_text().replace('"critical"', '"severe"', 1)
            p.write_text(text)
            with self.assertRaises(rg.GuardError):
                rg.load_profile(p, "heavy")


class VerdictTests(unittest.TestCase):
    def verdict(self, **over):
        return rg.verdict(rg.evaluate(meas(**over), CFG))

    def test_pass(self):
        self.assertEqual(self.verdict(), "pass")

    def test_ssd_below_threshold_blocks(self):
        self.assertEqual(self.verdict(ssd_free_gb=9.99), "block")

    def test_ssd_exactly_at_threshold_passes(self):
        self.assertEqual(self.verdict(ssd_free_gb=10.0), "pass")

    def test_swap_at_90_warns_not_blocks(self):
        self.assertEqual(self.verdict(swap_used_pct=90.0), "warn")
        self.assertEqual(self.verdict(swap_used_pct=89.9), "pass")
        self.assertEqual(self.verdict(swap_used_pct=100.0), "warn")

    def test_memory_pressure_levels(self):
        self.assertEqual(self.verdict(memory_pressure="normal"), "pass")
        self.assertEqual(self.verdict(memory_pressure="warn"), "warn")
        self.assertEqual(self.verdict(memory_pressure="critical"), "block")

    def test_unmeasurable_pressure_is_never_a_silent_pass(self):
        self.assertEqual(self.verdict(memory_pressure="unknown"), "warn")

    def test_block_beats_warn(self):
        self.assertEqual(self.verdict(ssd_free_gb=1, swap_used_pct=99), "block")

    def test_no_swap_configured_is_zero_percent(self):
        self.assertEqual(self.verdict(swap_used_pct=0.0, swap_total_gb=0.0, swap_used_gb=0.0), "pass")


class MainExitCodeTests(unittest.TestCase):
    def test_pass_exits_0_and_prints_all_three_measurements_and_badge(self):
        code, out, _ = run_main([], meas())
        self.assertEqual(code, 0)
        for word in ("ssd_free", "swap_used", "memory_pressure", "기본값", "결과: 통과"):
            self.assertIn(word, out)

    def test_warn_exits_0_with_warning_line(self):
        code, out, _ = run_main([], meas(swap_used_pct=95.0))
        self.assertEqual(code, 0)
        self.assertIn("[경고] swap_used", out)
        self.assertIn("경고 있음", out)

    def test_block_exits_2(self):
        code, out, _ = run_main([], meas(ssd_free_gb=3.0))
        self.assertEqual(code, 2)
        self.assertIn("[차단] ssd_free", out)
        self.assertIn("결과: 차단", out)

    def test_critical_pressure_blocks(self):
        self.assertEqual(run_main([], meas(memory_pressure="critical"))[0], 2)

    def test_measurement_failure_exits_3(self):
        def boom(path, cfg):
            raise rg.GuardError("sysctl 실패")
        code, _, err = run_main([], None, measure=boom)
        self.assertEqual(code, 3)
        self.assertIn("sysctl 실패", err)

    def test_unknown_profile_exits_3(self):
        code, _, err = run_main(["--profile", "nope"], meas())
        self.assertEqual(code, 3)
        self.assertIn("nope", err)

    def test_json_output(self):
        code, out, _ = run_main(["--json"], meas(ssd_free_gb=3.0))
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["verdict"], "block")
        self.assertEqual(data["badge"], "기본값")
        self.assertEqual({r["item"] for r in data["rows"]}, {"ssd_free", "swap_used", "memory_pressure"})


class WrapCommandTests(unittest.TestCase):
    def test_blocked_command_is_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "ran"
            code, _, _ = run_main(["--", sys.executable, "-c", f"open({str(marker)!r}, 'w')"], meas(ssd_free_gb=1))
            self.assertEqual(code, 2)
            self.assertFalse(marker.exists())

    def test_passing_command_runs_and_exit_code_passes_through(self):
        code, out, _ = run_main(["--", sys.executable, "-c", "raise SystemExit(7)"], meas())
        self.assertEqual(code, 7)
        self.assertIn("종료 코드 7", out)
        self.assertIn("| SSD 여유 GB |", out)

    def test_table_reports_before_after_and_worst(self):
        seq = iter([meas(ssd_free_gb=20.0, swap_used_gb=1.0, swap_used_pct=10.0),
                    meas(ssd_free_gb=18.5, swap_used_gb=3.0, swap_used_pct=30.0)])
        code, out, _ = run_main(["--", sys.executable, "-c", "pass"], None, measure=lambda p, c: next(seq))
        self.assertEqual(code, 0)
        self.assertIn("| SSD 여유 GB | 20.00 | 18.50 | -1.50 | 18.50 |", out)
        self.assertIn("| 스왑 사용 GB | 1.00 | 3.00 | +2.00 | 3.00 |", out)

    def test_child_is_told_the_guard_already_passed(self):
        code, out, _ = run_main(["--", sys.executable, "-c",
                                 f"import os; raise SystemExit(0 if os.environ[{rg.WRAPPED_ENV!r}] == '1' else 9)"], meas())
        self.assertEqual(code, 0)

    def test_guard_or_exit_skips_when_already_wrapped(self):
        import os
        os.environ[rg.WRAPPED_ENV] = "1"
        try:
            rg.guard_or_exit("no-such-profile")  # 프로필을 읽기 전에 돌아온다
        finally:
            del os.environ[rg.WRAPPED_ENV]

    def test_guard_or_exit_raises_systemexit_with_guard_code(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            rg.guard_or_exit("no-such-profile")
        self.assertEqual(cm.exception.code, 3)

    def test_missing_command_exits_3(self):
        code, _, err = run_main(["--", "/no/such/binary-kinetra"], meas())
        self.assertEqual(code, 3)
        self.assertIn("명령을 시작하지 못했다", err)


class ParserTests(unittest.TestCase):
    def test_vm_swapusage_real_sample(self):
        used, total = rg.parse_vm_swapusage("total = 18432.00M  used = 17434.25M  free = 997.75M  (encrypted)")
        self.assertAlmostEqual(used / 2**20, 17434.25)
        self.assertAlmostEqual(total / 2**20, 18432.0)

    def test_vm_swapusage_zero_and_garbage(self):
        self.assertEqual(rg.parse_vm_swapusage("total = 0.00M  used = 0.00M  free = 0.00M"), (0.0, 0.0))
        with self.assertRaises(rg.GuardError):
            rg.parse_vm_swapusage("nope")

    def test_meminfo_swap(self):
        used, total = rg.parse_meminfo_swap("MemTotal: 1 kB\nSwapTotal:  2097152 kB\nSwapFree:  1048576 kB\n")
        self.assertEqual((used, total), (1048576 * 1024.0, 2097152 * 1024.0))
        with self.assertRaises(rg.GuardError):
            rg.parse_meminfo_swap("MemTotal: 1 kB\n")

    def test_psi(self):
        text = "some avg10=1.50 avg60=0.00 avg300=0.00 total=1\nfull avg10=7.25 avg60=0.00 avg300=0.00 total=1\n"
        psi = rg.parse_psi_memory(text)
        self.assertEqual(psi, {"some": 1.5, "full": 7.25})
        self.assertEqual(rg.classify_psi(psi["full"], CFG), "warn")
        self.assertEqual(rg.classify_psi(0.0, CFG), "normal")
        self.assertEqual(rg.classify_psi(20.0, CFG), "critical")
        with self.assertRaises(rg.GuardError):
            rg.parse_psi_memory("some avg10=1.0\n")


class RealMachineShapeTests(unittest.TestCase):
    def test_collect_returns_every_field_on_this_os(self):
        m = rg.collect(rg.REPO_ROOT, CFG)
        self.assertGreater(m["ssd_free_gb"], 0)
        self.assertGreaterEqual(m["swap_used_pct"], 0)
        self.assertIn(m["memory_pressure"], ("normal", "warn", "critical", "unknown"))


if __name__ == "__main__":
    unittest.main()
