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
    m = {"ssd_free_gib": 25.0, "ssd_path": "/x", "swap_used_gib": 4.0, "swap_total_gib": 8.0,
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
        self.assertEqual(CFG["ssd_free_gib_block_below"], 10)
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
        self.assertEqual(self.verdict(ssd_free_gib=9.99), "block")

    def test_ssd_exactly_at_threshold_passes(self):
        self.assertEqual(self.verdict(ssd_free_gib=10.0), "pass")

    def test_swap_at_90_warns_not_blocks(self):
        self.assertEqual(self.verdict(swap_used_pct=90.0), "warn")
        self.assertEqual(self.verdict(swap_used_pct=89.9), "pass")
        self.assertEqual(self.verdict(swap_used_pct=100.0), "warn")

    def test_memory_pressure_levels(self):
        self.assertEqual(self.verdict(memory_pressure="normal"), "pass")
        self.assertEqual(self.verdict(memory_pressure="warn"), "warn")
        self.assertEqual(self.verdict(memory_pressure="critical"), "block")

    def test_block_beats_warn(self):
        self.assertEqual(self.verdict(ssd_free_gib=1, swap_used_pct=99), "block")

    def test_no_swap_configured_is_zero_percent(self):
        self.assertEqual(self.verdict(swap_used_pct=0.0, swap_total_gib=0.0, swap_used_gib=0.0), "pass")


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
        code, out, _ = run_main([], meas(ssd_free_gib=3.0))
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
        code, out, _ = run_main(["--json"], meas(ssd_free_gib=3.0))
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["verdict"], "block")
        self.assertEqual(data["badge"], "기본값")
        self.assertEqual({r["item"] for r in data["rows"]}, {"ssd_free", "swap_used", "memory_pressure"})


def _alive(pid):
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 좀비(거두지 않은 종료 프로세스)는 살아 있는 것이 아니다
    import subprocess
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


class WrapCommandTests(unittest.TestCase):
    def test_blocked_command_is_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "ran"
            code, _, _ = run_main(["--", sys.executable, "-c", f"open({str(marker)!r}, 'w')"], meas(ssd_free_gib=1))
            self.assertEqual(code, 2)
            self.assertFalse(marker.exists())

    def test_passing_command_runs_and_exit_code_passes_through(self):
        code, out, _ = run_main(["--", sys.executable, "-c", "raise SystemExit(7)"], meas())
        self.assertEqual(code, 7)
        self.assertIn("종료 코드 7", out)
        self.assertIn("| SSD 여유 GiB |", out)

    def test_table_reports_before_after_and_worst(self):
        seq = iter([meas(ssd_free_gib=20.0, swap_used_gib=1.0, swap_used_pct=10.0),
                    meas(ssd_free_gib=18.5, swap_used_gib=3.0, swap_used_pct=30.0)])
        code, out, _ = run_main(["--", sys.executable, "-c", "pass"], None, measure=lambda p, c: next(seq))
        self.assertEqual(code, 0)
        self.assertIn("| SSD 여유 GiB | 20.00 | 18.50 | -1.50 | 18.50 |", out)
        self.assertIn("| 스왑 사용 GiB | 1.00 | 3.00 | +2.00 | 3.00 |", out)

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

    def test_measurement_failure_while_running_terminates_child_group_and_exits_3(self):
        import os
        import time
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "pids"
            # 부모 셸이 손자(sleep)를 띄운다. 프로세스 그룹째 끝나야 한다.
            script = f"sleep 300 & echo $$ $! > {pidfile}; wait"
            calls = {"n": 0}

            def flaky(path, cfg):
                calls["n"] += 1
                if calls["n"] >= 2:
                    raise rg.GuardError("두 번째 측정 실패")
                return meas()

            old = rg.SAMPLE_SECONDS
            rg.SAMPLE_SECONDS = 0.3
            try:
                code, out, err = run_main(["--", "sh", "-c", script], None, measure=flaky)
            finally:
                rg.SAMPLE_SECONDS = old
            self.assertEqual(code, 3)
            self.assertIn("두 번째 측정 실패", err)
            self.assertNotIn("측정 기록", out)
            pids = [int(x) for x in pidfile.read_text().split()]
            deadline = time.time() + 5
            alive = pids
            while alive and time.time() < deadline:
                alive = [p for p in pids if _alive(p)]
                time.sleep(0.05)
            self.assertEqual(alive, [], "자식 또는 손자 프로세스가 남았다")

    def test_missing_command_exits_3(self):
        code, _, err = run_main(["--", "/no/such/binary-kinetra"], meas())
        self.assertEqual(code, 3)
        self.assertIn("명령을 시작하지 못했다", err)


def write_cfg(d, **over):
    """기본 설정에서 한 줄(키 = 값)을 바꾼 설정 파일을 만든다."""
    import re
    text = rg.DEFAULT_CONFIG.read_text(encoding="utf-8")
    for k, v in over.items():
        text, n = re.subn(rf"^{k} = .*$", f"{k} = {v}", text, flags=re.M)
        assert n == 1, k
    p = Path(d) / "c.toml"
    p.write_text(text, encoding="utf-8")
    return p


class ThresholdValidationTests(unittest.TestCase):
    def assert_rejected(self, **over):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(rg.GuardError, msg=over):
                rg.load_profile(write_cfg(d, **over), "heavy")

    def test_nan_inf_string_bool_negative_rejected(self):
        self.assert_rejected(ssd_free_gib_block_below="nan")
        self.assert_rejected(ssd_free_gib_block_below="inf")
        self.assert_rejected(ssd_free_gib_block_below='"10"')
        self.assert_rejected(ssd_free_gib_block_below="true")
        self.assert_rejected(ssd_free_gib_block_below="-1")
        self.assert_rejected(swap_used_pct_warn_at="nan")
        self.assert_rejected(swap_used_pct_warn_at="101")
        self.assert_rejected(swap_used_pct_warn_at='"90%"')
        self.assert_rejected(linux_psi_full_avg10_warn="nan")
        self.assert_rejected(linux_psi_full_avg10_critical='"x"')

    def test_inverted_psi_and_pressure_order_rejected(self):
        self.assert_rejected(linux_psi_full_avg10_warn="30.0")  # warn 30 > critical 20
        self.assert_rejected(memory_pressure_warn_at='"critical"', memory_pressure_block_at='"warn"')

    def test_blank_badge_rejected(self):
        self.assert_rejected(badge='""')

    def test_bad_config_exits_3_and_never_runs_child(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = write_cfg(d, swap_used_pct_warn_at="nan")
            marker = Path(d) / "ran"
            code, _, err = run_main(["--config", str(cfg), "--", sys.executable, "-c", f"open({str(marker)!r}, 'w')"], meas())
            self.assertEqual(code, 3)
            self.assertIn("swap_used_pct_warn_at", err)
            self.assertFalse(marker.exists())


class LinuxCollectTests(unittest.TestCase):
    """Linux 경로를 이 머신(macOS)에서도 돌려 보도록 플랫폼과 /proc 읽기를 가짜로 바꾼다."""

    def collect_linux(self, files):
        from unittest import mock
        real_read = Path.read_text

        def fake_read(self, *a, **k):
            if str(self) in files:
                v = files[str(self)]
                if isinstance(v, Exception):
                    raise v
                return v
            return real_read(self, *a, **k)

        with mock.patch.object(rg.sys, "platform", "linux"), mock.patch.object(Path, "read_text", fake_read):
            return rg.collect(rg.REPO_ROOT, CFG)

    MEMINFO = "SwapTotal:  2097152 kB\nSwapFree:  1048576 kB\n"
    PSI = "some avg10=1.00 avg60=0 avg300=0 total=1\nfull avg10=7.25 avg60=0 avg300=0 total=1\n"

    def test_reads_swap_and_psi(self):
        m = self.collect_linux({"/proc/meminfo": self.MEMINFO, "/proc/pressure/memory": self.PSI})
        self.assertAlmostEqual(m["swap_used_pct"], 50.0)
        self.assertAlmostEqual(m["swap_total_gib"], 2.0)
        self.assertEqual(m["memory_pressure"], "warn")

    def test_missing_psi_file_is_a_measurement_failure(self):
        with self.assertRaises(rg.GuardError) as cm:
            self.collect_linux({"/proc/meminfo": self.MEMINFO, "/proc/pressure/memory": FileNotFoundError("nope")})
        self.assertIn("/proc/pressure/memory", str(cm.exception))

    def test_unreadable_psi_file_is_a_measurement_failure(self):
        with self.assertRaises(rg.GuardError):
            self.collect_linux({"/proc/meminfo": self.MEMINFO, "/proc/pressure/memory": PermissionError("denied")})

    def test_unreadable_meminfo_is_a_measurement_failure(self):
        with self.assertRaises(rg.GuardError):
            self.collect_linux({"/proc/meminfo": PermissionError("denied"), "/proc/pressure/memory": self.PSI})

    def test_failure_exits_3_and_child_never_starts(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "ran"
            with mock.patch.object(rg.sys, "platform", "linux"), mock.patch.object(
                    Path, "read_text", side_effect=FileNotFoundError("x")):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = rg.main(["--", sys.executable, "-c", f"open({str(marker)!r}, 'w')"])
            self.assertEqual(code, 3)
            self.assertFalse(marker.exists())


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
        self.assertGreater(m["ssd_free_gib"], 0)
        self.assertGreaterEqual(m["swap_used_pct"], 0)
        self.assertIn(m["memory_pressure"], ("normal", "warn", "critical"))


if __name__ == "__main__":
    unittest.main()
