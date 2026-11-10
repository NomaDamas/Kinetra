#!/usr/bin/env python3
"""개발 자원 가드 (P0-09). 무거운 실행 전에 SSD 여유, 스왑 사용량, 메모리 압력을 재고 임계 미달이면 막는다.

    uv run python tools/dev/resource_guard.py --profile heavy; echo $?
    uv run python tools/dev/resource_guard.py --profile heavy -- <명령...>

종료 코드: 0 통과(경고 포함), 2 차단, 3 측정 실패(재지 못하면 돌리지 않는다).
`--` 뒤에 명령을 주면 가드를 통과했을 때만 그 명령을 돌리고, 실행 전·후·중 최악값을 표로 남긴다
(docs/process/dev-resources.md 의 측정 기록 양식). 명령의 종료 코드를 그대로 돌려준다.
(명령이 2나 3으로 끝나면 가드의 코드와 겹치므로, 차단 여부는 먼저 출력되는 `결과:` 줄로 가른다.)

임계값은 tools/dev/resource_guard.toml 에 있고 값 배지가 붙는다. 표준 라이브러리만 쓴다(Python 3.11+).
macOS: `sysctl vm.swapusage`, `sysctl kern.memorystatus_vm_pressure_level`. Linux: /proc/meminfo, /proc/pressure/memory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
# KINETRA_GUARD_CONFIG 는 테스트가 다른 임계를 넣는 자리다. 사람이 가드를 피하는 용도가 아니다.
DEFAULT_CONFIG = Path(os.environ.get("KINETRA_GUARD_CONFIG") or HERE / "resource_guard.toml")
REPO_ROOT = HERE.parents[1]

EXIT_PASS, EXIT_BLOCK, EXIT_ERROR = 0, 2, 3
GIB = 2**30
LEVELS = ("normal", "warn", "critical")  # 메모리 압력 단계, 낮은 쪽부터
MACOS_LEVELS = {1: "normal", 2: "warn", 4: "critical"}  # kern.memorystatus_vm_pressure_level
SAMPLE_SECONDS = 2.0
WRAPPED_ENV = "KINETRA_GUARD_PASSED"  # `-- 명령` 으로 가드를 통과해 시작한 자식에게 준다


class GuardError(Exception):
    """재지 못했거나 설정이 틀렸다. 종료 코드 3."""


# ---------- 측정 ----------

def parse_vm_swapusage(text: str) -> tuple[float, float]:
    """`vm.swapusage: total = 18432.00M  used = 17434.25M  free = 997.75M  (encrypted)` -> (used_bytes, total_bytes)"""
    units = {"K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}
    got = {k: float(v) * units[u] for k, v, u in re.findall(r"(total|used|free)\s*=\s*([\d.]+)([KMGT])", text)}
    if "total" not in got or "used" not in got:
        raise GuardError(f"vm.swapusage 를 읽지 못했다: {text!r}")
    return got["used"], got["total"]


def parse_meminfo_swap(text: str) -> tuple[float, float]:
    """/proc/meminfo -> (used_bytes, total_bytes). 스왑이 없으면 (0, 0)."""
    kb = {k: int(v) for k, v in re.findall(r"^(SwapTotal|SwapFree):\s+(\d+)\s*kB", text, re.M)}
    if "SwapTotal" not in kb or "SwapFree" not in kb:
        raise GuardError("/proc/meminfo 에 SwapTotal/SwapFree 가 없다")
    return (kb["SwapTotal"] - kb["SwapFree"]) * 1024.0, kb["SwapTotal"] * 1024.0


def parse_psi_memory(text: str) -> dict[str, float]:
    """/proc/pressure/memory -> {"some": avg10, "full": avg10}"""
    out = {k: float(v) for k, v in re.findall(r"^(some|full)\s+avg10=([\d.]+)", text, re.M)}
    if "full" not in out:
        raise GuardError(f"/proc/pressure/memory 를 읽지 못했다: {text!r}")
    return out


def classify_psi(psi_full_avg10: float, cfg: dict) -> str:
    if psi_full_avg10 >= cfg["linux_psi_full_avg10_critical"]:
        return "critical"
    if psi_full_avg10 >= cfg["linux_psi_full_avg10_warn"]:
        return "warn"
    return "normal"


def _run(*cmd: str) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GuardError(f"{' '.join(cmd)}: {e}") from e
    if p.returncode:
        raise GuardError(f"{' '.join(cmd)} 종료 코드 {p.returncode}: {p.stderr.strip()}")
    return p.stdout.strip()


def collect(path: Path, cfg: dict) -> dict:
    """실제 머신을 잰다. 반환: ssd_free_gb, swap_used_pct, swap_used_gb, swap_total_gb, memory_pressure, memory_pressure_detail"""
    try:
        du = shutil.disk_usage(path)
    except OSError as e:
        raise GuardError(f"디스크 여유를 읽지 못했다({path}): {e}") from e
    m = {"ssd_free_gb": du.free / GIB, "ssd_path": str(path)}
    if sys.platform == "darwin":
        used, total = parse_vm_swapusage(_run("sysctl", "-n", "vm.swapusage"))
        level = int(_run("sysctl", "-n", "kern.memorystatus_vm_pressure_level"))
        if level not in MACOS_LEVELS:
            raise GuardError(f"알 수 없는 kern.memorystatus_vm_pressure_level={level}")
        pressure, detail = MACOS_LEVELS[level], f"kern.memorystatus_vm_pressure_level={level}"
    elif sys.platform.startswith("linux"):
        try:
            used, total = parse_meminfo_swap(Path("/proc/meminfo").read_text())
        except OSError as e:
            raise GuardError(f"/proc/meminfo: {e}") from e
        try:
            psi = parse_psi_memory(Path("/proc/pressure/memory").read_text())
        except OSError:  # PSI 가 꺼진 커널. 못 재는 것을 통과로 치지 않고 경고로 남긴다.
            pressure, detail = "unknown", "/proc/pressure/memory 없음(PSI 꺼짐)"
        else:
            pressure, detail = classify_psi(psi["full"], cfg), f"psi full avg10={psi['full']}"
    else:
        raise GuardError(f"지원하지 않는 OS: {sys.platform}")
    m.update(
        swap_used_gb=used / GIB,
        swap_total_gb=total / GIB,
        swap_used_pct=(100.0 * used / total) if total else 0.0,
        memory_pressure=pressure,
        memory_pressure_detail=detail,
    )
    return m


# ---------- 판정 ----------

def load_profile(config: Path, name: str) -> dict:
    try:
        with open(config, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise GuardError(f"설정 파일을 읽지 못했다({config}): {e}") from e
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise GuardError(f"프로필 '{name}' 이 없다. 있는 것: {', '.join(sorted(profiles)) or '(없음)'}")
    cfg = dict(profiles[name])
    need = {"badge", "ssd_free_gb_block_below", "swap_used_pct_warn_at", "memory_pressure_warn_at",
            "memory_pressure_block_at", "linux_psi_full_avg10_warn", "linux_psi_full_avg10_critical"}
    if missing := need - cfg.keys():
        raise GuardError(f"프로필 '{name}' 에 키가 없다: {', '.join(sorted(missing))}")
    for k in ("memory_pressure_warn_at", "memory_pressure_block_at"):
        if cfg[k] not in LEVELS:
            raise GuardError(f"{k} 는 {LEVELS} 중 하나여야 한다: {cfg[k]!r}")
    return cfg


def evaluate(m: dict, cfg: dict) -> list[dict]:
    """측정값과 임계로 항목별 판정을 만든다. status: pass | warn | block"""
    rows = []
    free, floor = m["ssd_free_gb"], cfg["ssd_free_gb_block_below"]
    rows.append({"item": "ssd_free", "value": f"{free:.1f} GB 남음", "rule": f"{floor:g} GB 미만이면 차단",
                 "status": "block" if free < floor else "pass"})
    pct, warn_at = m["swap_used_pct"], cfg["swap_used_pct_warn_at"]
    rows.append({"item": "swap_used", "value": f"{pct:.1f}% ({m['swap_used_gb']:.1f}/{m['swap_total_gb']:.1f} GB)",
                 "rule": f"{warn_at:g}% 이상이면 경고", "status": "warn" if pct >= warn_at else "pass"})
    p = m["memory_pressure"]
    if p == "unknown":
        status = "warn"
    elif LEVELS.index(p) >= LEVELS.index(cfg["memory_pressure_block_at"]):
        status = "block"
    elif LEVELS.index(p) >= LEVELS.index(cfg["memory_pressure_warn_at"]):
        status = "warn"
    else:
        status = "pass"
    rows.append({"item": "memory_pressure", "value": f"{p} ({m['memory_pressure_detail']})",
                 "rule": f"{cfg['memory_pressure_block_at']} 이면 차단, {cfg['memory_pressure_warn_at']} 이상이면 경고",
                 "status": status})
    return rows


def verdict(rows: list[dict]) -> str:
    statuses = {r["status"] for r in rows}
    return "block" if "block" in statuses else "warn" if "warn" in statuses else "pass"


def render(rows: list[dict], cfg: dict, profile: str) -> str:
    mark = {"pass": "통과", "warn": "경고", "block": "차단"}
    lines = [f"자원 가드 profile={profile} 임계 배지=[{cfg['badge']}]"]
    for r in rows:
        lines.append(f"  [{mark[r['status']]}] {r['item']:<16} {r['value']}  ({r['rule']})")
    v = verdict(rows)
    lines.append({"pass": "결과: 통과", "warn": "결과: 통과(경고 있음). 경고 항목을 PR에 적는다",
                  "block": "결과: 차단. docs/process/dev-resources.md 의 정리 절차를 따른 뒤 다시 잰다"}[v])
    return "\n".join(lines)


# ---------- 실행 ----------

def run_around(cmd: list[str], path: Path, cfg: dict, before: dict, measure) -> tuple[int, str]:
    """명령을 돌리며 SSD 최저·스왑 최고를 표본한다. 반환: (명령 종료 코드, 전/후/최악 표)"""
    worst_free, worst_swap = before["ssd_free_gb"], before["swap_used_gb"]
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, env={**os.environ, WRAPPED_ENV: "1"})
    except OSError as e:
        raise GuardError(f"명령을 시작하지 못했다: {e}") from e
    while proc.poll() is None:
        try:
            proc.wait(timeout=SAMPLE_SECONDS)
        except subprocess.TimeoutExpired:
            s = measure(path, cfg)
            worst_free, worst_swap = min(worst_free, s["ssd_free_gb"]), max(worst_swap, s["swap_used_gb"])
    after = measure(path, cfg)
    worst_free, worst_swap = min(worst_free, after["ssd_free_gb"]), max(worst_swap, after["swap_used_gb"])
    table = "\n".join([
        f"측정 기록 (명령: {' '.join(cmd)}, 종료 코드 {proc.returncode}, {time.monotonic() - t0:.1f}초)",
        "| 항목 | 전 | 후 | 변화 | 실행 중 최악 |",
        "|---|---|---|---|---|",
        f"| SSD 여유 GB | {before['ssd_free_gb']:.2f} | {after['ssd_free_gb']:.2f} "
        f"| {after['ssd_free_gb'] - before['ssd_free_gb']:+.2f} | {worst_free:.2f} |",
        f"| 스왑 사용 GB | {before['swap_used_gb']:.2f} | {after['swap_used_gb']:.2f} "
        f"| {after['swap_used_gb'] - before['swap_used_gb']:+.2f} | {worst_swap:.2f} |",
        f"| 스왑 사용률 % | {before['swap_used_pct']:.1f} | {after['swap_used_pct']:.1f} "
        f"| {after['swap_used_pct'] - before['swap_used_pct']:+.1f} | |",
        f"| 메모리 압력 | {before['memory_pressure']} | {after['memory_pressure']} | | |",
    ])
    return proc.returncode, table


def guard_or_exit(profile: str = "heavy") -> None:
    """다른 진입점이 무거운 일을 시작하기 전에 부른다. 차단이면 가드의 종료 코드로 프로세스를 끝낸다.
    `resource_guard.py -- 명령` 이 이미 통과시킨 자식 프로세스에서는 같은 표를 다시 찍지 않는다."""
    if os.environ.get(WRAPPED_ENV) == "1":
        return
    code = main(["--profile", profile])
    if code:
        raise SystemExit(code)


def main(argv: list[str] | None = None, measure=collect) -> int:
    """measure 는 테스트가 가짜 측정값을 넣는 자리다. 명령줄로는 바꿀 수 없다."""
    argv = sys.argv[1:] if argv is None else argv
    around: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, around = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="heavy", help="resource_guard.toml 의 프로필 (기본 heavy)")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--path", type=Path, default=REPO_ROOT, help="SSD 여유를 잴 경로 (기본 저장소 루트)")
    ap.add_argument("--json", action="store_true", help="측정값과 판정을 JSON 으로 출력")
    args = ap.parse_args(argv)
    try:
        cfg = load_profile(args.config, args.profile)
        m = measure(args.path, cfg)
        rows = evaluate(m, cfg)
    except GuardError as e:
        print(f"자원 가드 실패: {e}", file=sys.stderr)
        return EXIT_ERROR
    v = verdict(rows)
    if args.json:
        print(json.dumps({"profile": args.profile, "badge": cfg["badge"], "measurements": m, "rows": rows,
                          "verdict": v}, ensure_ascii=False, indent=1))
    else:
        print(render(rows, cfg, args.profile))
    if v == "block":
        return EXIT_BLOCK
    if not around:  # `--` 뒤 명령이 없으면 측정만 한다
        return EXIT_PASS
    try:
        code, table = run_around(around, args.path, cfg, m, measure)
    except GuardError as e:
        print(f"자원 가드 실패: {e}", file=sys.stderr)
        return EXIT_ERROR
    print(table)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
