"""`python -m kinetra_engine.stt fetch` downloads the pinned model; `... transcribe FILE` prints the recognised text.

`fetch` is the only command that uses the network and a heavy one (a 462 MiB download, then a hash). Run it under the resource guard:

    uv run python tools/dev/resource_guard.py --profile heavy -- uv run python -m kinetra_engine.stt fetch

Started outside the guard it refuses (exit 2), like the other heavy entry points in `docs/process/dev-resources.md`.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import SttError, Transcriber, fetch_model

GUARD_ENV = "KINETRA_GUARD_PASSED"  # set to 1 by `resource_guard.py -- <command>` for the command it wraps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kinetra_engine.stt", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download and verify the pinned model (network, once)")
    t = sub.add_parser("transcribe", help="recognise one audio file (offline)")
    t.add_argument("file")
    t.add_argument("--language", default="ko")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "fetch":
            if os.environ.get(GUARD_ENV) != "1" and os.environ.get("CI") != "true":
                print("refusing to start outside the resource guard: uv run python tools/dev/resource_guard.py --profile heavy -- <this command>", file=sys.stderr)
                return 2
            print(fetch_model())
        else:
            out = Transcriber().transcribe(args.file, language=args.language)
            print(out.text)
    except SttError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
