#!/usr/bin/env python3
"""P0-04e: run every spike's offline tests (no browser, no measurement run). Standard library only.

    python3 scripts/ci/run_spike_tests.py            # plan + run, exit 1 if anything fails
    python3 scripts/ci/run_spike_tests.py --plan     # only print the plan (nothing is executed)
    python3 scripts/ci/run_spike_tests.py --root DIR # another repo tree (tests)

For each directory under `spikes/`:
  * Python tests: `test_*.py` directly in the spike dir or in its `tests/` dir. They carry a PEP 723 header, so
    they run as `uv run <file>` from the repo root (the spike's pinned dependencies, not the workspace's).
  * pnpm tests: a `package.json` with a `scripts.test` runs `pnpm --dir spikes/<name> install --frozen-lockfile`
    and then `pnpm --dir spikes/<name> test`. `test:browser` and the measurement scripts are never run here.
  * Nothing of the above: the spike is skipped and the reason is printed.
A spike whose `package.json` has a `scripts.test` but no lockfile, or whose Python test file is not a file, fails the
run instead of being skipped silently. Every step runs even after a failure; the summary lists all of them.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def plan(root: Path) -> list[dict]:
    """One entry per spike: {name, steps: [argv...], skip: reason | None, errors: [..]}."""
    out = []
    spikes = root / "spikes"
    for d in sorted(p for p in spikes.iterdir() if p.is_dir()) if spikes.is_dir() else []:
        rel = d.relative_to(root).as_posix()
        entry = {"name": d.name, "steps": [], "skip": None, "errors": []}
        py = sorted([*d.glob("test_*.py"), *(d / "tests").glob("test_*.py")]) if d.is_dir() else []
        for f in py:
            if f.is_file():
                entry["steps"].append(["uv", "run", f.relative_to(root).as_posix()])
        pkg = d / "package.json"
        if pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
            except json.JSONDecodeError as e:
                scripts = {}
                entry["errors"].append(f"{rel}/package.json is not valid JSON: {e}")
            if isinstance(scripts.get("test"), str) and scripts["test"].strip():
                if not (d / "pnpm-lock.yaml").is_file():
                    entry["errors"].append(f"{rel} has a `test` script but no pnpm-lock.yaml (cannot install --frozen-lockfile)")
                else:
                    entry["steps"] += [["pnpm", "--dir", rel, "install", "--frozen-lockfile"], ["pnpm", "--dir", rel, "test"]]
        if not entry["steps"] and not entry["errors"]:
            entry["skip"] = "no test_*.py (spike dir or tests/) and no package.json `test` script"
        out.append(entry)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--plan", action="store_true", help="print the plan, run nothing")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    entries = plan(root)
    if not entries:
        print("no spikes found under spikes/: nothing to run")
        return 0
    failed: list[str] = []
    summary: list[str] = []
    for e in entries:
        if e["skip"]:
            print(f"SKIP {e['name']}: {e['skip']}")
            summary.append(f"skip {e['name']}")
            continue
        for err in e["errors"]:
            print(f"FAIL {e['name']}: {err}")
            failed.append(f"{e['name']}: {err}")
        for cmd in e["steps"]:
            line = " ".join(cmd)
            if args.plan:
                print(f"PLAN {e['name']}: {line}")
                continue
            print(f"\n::group::{e['name']}: {line}", flush=True)
            t0 = time.perf_counter()
            rc = subprocess.run(cmd, cwd=root).returncode
            dt = time.perf_counter() - t0
            print("::endgroup::", flush=True)
            print(f"{'ok  ' if rc == 0 else 'FAIL'} {e['name']}: {line} ({dt:.1f}s, exit {rc})", flush=True)
            summary.append(f"{'ok' if rc == 0 else 'FAIL'} {e['name']}: {line} ({dt:.1f}s)")
            if rc != 0:
                failed.append(f"{e['name']}: {line} (exit {rc})")
                if cmd[:4] == ["pnpm", "--dir", cmd[2], "install"]:
                    break  # the test step cannot run without its install
    print("\nsummary:")
    for s in summary:
        print("  " + s)
    if failed:
        print(f"\n{len(failed)} failure(s):", file=sys.stderr)
        for f in failed:
            print("  " + f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
