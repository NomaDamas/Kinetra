# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""A0-03a driver: runs spikes/godot-jolt/scale.gd for the 200 / 1,000 / 5,000-body and 100-joint-release scenes, each
scene repeated in separate Godot processes, and compares the hash chains. Measurement only. Standard library only.

    uv run python tools/dev/resource_guard.py --profile heavy -- uv run spikes/godot-jolt/scale.py --json spikes/godot-jolt/results/a0-03a-main.json
    uv run spikes/godot-jolt/scale.py --bodies 200 --no-break --repeats 2 --sim-seconds 0.48     # quick

The Godot binary lives outside the repository (`--godot`, env `GODOT`, default ~/.cache/kinetra-godot/Godot.app/...).
Without it this script stops with exit code 4 and says where to get it (spikes/godot-jolt/REPORT.md, "Godot binary").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dev"))
import resource_guard  # noqa: E402

HEAVY_BODIES = 1000
DEFAULT_GODOT = Path.home() / ".cache" / "kinetra-godot" / "Godot.app" / "Contents" / "MacOS" / "Godot"


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def machine_spec(godot: Path) -> dict:
    return {
        "cpu": sh("sysctl -n machdep.cpu.brand_string") or platform.processor(),
        "cores_logical": os.cpu_count(),
        "cores_physical": sh("sysctl -n hw.physicalcpu") or None,
        "ram_gib": round(int(sh("sysctl -n hw.memsize") or 0) / 2**30, 1),
        "os": platform.platform(),
        "python": platform.python_version(),
        "godot_version": sh(f'"{godot}" --version'),
        "godot_binary_sha256": file_sha256(godot),
    }


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_result(stdout: str) -> dict | None:
    """The last `RESULT {json}` line of a scale.gd run, or None if the run never printed one."""
    found = None
    for line in stdout.splitlines():
        if line.startswith("RESULT "):
            found = json.loads(line[len("RESULT "):])
    return found


def compare(runs: list[dict]) -> dict:
    """Compare the chained-hash checkpoints over the common prefix. identical is True/False, or None (not
    comparable: fewer than two runs or no common checkpoint). None is never reported as a match."""
    k = min((len(r["checkpoints"]) for r in runs), default=0)
    if len(runs) < 2 or k == 0:
        return {"checkpoints_compared": k, "identical": None}
    same = all(r["checkpoints"][:k] == runs[0]["checkpoints"][:k] for r in runs)
    first_diff = None
    if not same:
        for i in range(k):
            if any(r["checkpoints"][i] != runs[0]["checkpoints"][i] for r in runs):
                first_diff = i
                break
    return {"checkpoints_compared": k, "identical": same, "first_diff_checkpoint": first_diff}


def scene_args(scene: str, n: int) -> list[str]:
    """pile -> N free cubes; break -> the 100-weld columns plus N free cubes (0 = alone)."""
    return ["--scene", scene, "--n", str(n)] if scene == "pile" else ["--scene", "break", "--pile", str(n)]


def godot_cmd(godot: Path, project: Path, scene: str, n: int, sim_seconds: float, wall_cap: float, hash_every: int,
              seed: int, extra: list[str]) -> list[str]:
    return [str(godot), "--headless", "--fixed-fps", "500", "--path", str(project), "--script", str(HERE / "scale.gd"), "--",
            *scene_args(scene, n), "--sim-seconds", str(sim_seconds), "--wall-cap", str(wall_cap),
            "--hash-every", str(hash_every), "--seed", str(seed), *extra]


def run_once(cmd: list[str], timeout: float) -> dict:
    env = {**os.environ, "KINETRA_GUARD_PASSED": os.environ.get("KINETRA_GUARD_PASSED", "1")}
    before = os.getloadavg()
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    res = parse_result(p.stdout)
    if res is None:
        raise RuntimeError(f"no RESULT line (exit {p.returncode}): {p.stderr[-400:]} {p.stdout[-400:]}")
    res["exit_code"] = p.returncode
    res["process_wall_s"] = round(time.time() - t0, 2)
    res["loadavg_before"] = [round(x, 1) for x in before]
    res["loadavg_after"] = [round(x, 1) for x in os.getloadavg()]
    return res


def positive_int(text: str) -> int:
    v = int(text)
    if v < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {v}")
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--godot", type=Path, default=Path(os.environ.get("GODOT") or DEFAULT_GODOT))
    ap.add_argument("--bodies", type=int, nargs="+", default=[200, 1000, 5000])
    ap.add_argument("--break-pile", type=int, nargs="*", default=[0, 1000],
                    help="free cubes sharing the world with the 100-weld break scene (0 = break alone)")
    ap.add_argument("--no-break", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sim-seconds", type=float, default=2.0)
    ap.add_argument("--wall-cap", type=float, default=60.0, help="stop a run after this many stepping seconds")
    ap.add_argument("--hash-every", type=positive_int, default=10)
    ap.add_argument("--repeats", type=positive_int, default=2, help="separate Godot processes per scene (>= 2 to compare)")
    ap.add_argument("--threads1", action="store_true",
                    help="also run each scene once with a 1-thread worker pool (spikes/godot-jolt/threads1) and compare")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--json", help="write full results to this file")
    args = ap.parse_args(argv)

    if not args.godot.is_file():
        print(f"Godot binary not found: {args.godot}. Download the official macOS build into ~/.cache/kinetra-godot "
              "(spikes/godot-jolt/REPORT.md, 'Godot binary') or pass --godot / env GODOT.", file=sys.stderr)
        return 4
    if max([*args.bodies, *([] if args.no_break else args.break_pile)], default=0) >= HEAVY_BODIES:
        resource_guard.guard_or_exit("heavy")

    spec = machine_spec(args.godot)
    print(json.dumps({"machine": spec, "argv": sys.argv, "loadavg_start": os.getloadavg()}, indent=1), flush=True)
    scenes = [("pile", n) for n in args.bodies] + ([] if args.no_break else [("break", n) for n in args.break_pile])
    results = []
    for scene, n in scenes:
        runs = []
        for rep in range(args.repeats):
            r = run_once(godot_cmd(args.godot, HERE, scene, n, args.sim_seconds, args.wall_cap, args.hash_every,
                                   args.seed, []), args.timeout)
            r["repeat"], r["variant"] = rep, "threads-default"
            runs.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "checkpoints"}), flush=True)
        entry = {"label": f"{scene}-{n}", "runs": runs, "determinism": compare(runs)}
        if args.threads1:
            t1 = run_once(godot_cmd(args.godot, HERE / "threads1", scene, n, args.sim_seconds, args.wall_cap,
                                    args.hash_every, args.seed, []), args.timeout)
            t1["repeat"], t1["variant"] = 0, "threads-1"
            print(json.dumps({k: v for k, v in t1.items() if k != "checkpoints"}), flush=True)
            entry["threads1_run"] = t1
            entry["determinism_threads1_vs_default"] = compare([runs[0], t1])
        verdict = entry["determinism"]["identical"]
        print(f"HASH {entry['label']}: {'NOT COMPARABLE' if verdict is None else verdict} over "
              f"{entry['determinism']['checkpoints_compared']} checkpoints (final {(runs[0]['final_hash'] or 'none')[:16]})",
              flush=True)
        if args.threads1:
            v1 = entry["determinism_threads1_vs_default"]["identical"]
            print(f"HASH {entry['label']} threads1-vs-default: {'NOT COMPARABLE' if v1 is None else v1} over "
                  f"{entry['determinism_threads1_vs_default']['checkpoints_compared']} checkpoints", flush=True)
        results.append(entry)

    if args.json:
        Path(args.json).write_text(json.dumps({"machine": spec, "argv": sys.argv, "results": results}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
