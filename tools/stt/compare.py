"""I-01a: compare Korean dictation systems on the same clips and write `docs/decisions/stt-results.json`.

    uv run python tools/dev/resource_guard.py --profile heavy -- \
        uv run python tools/stt/compare.py --cases /tmp/stt-eval/cases.json --out docs/decisions/stt-results.json

`--cases` is a JSON list of `{"id", "group", "reference", "file", "source"}`. Audio files are read from disk and never copied
into the output. Systems measured:

    local-faster-whisper-small   the implementation in `kinetra_engine.stt` (offline, CPU int8), timed per clip
    api:<model>                  OpenRouter `/audio/transcriptions` for each `--api-model`; the key comes from OPENROUTER_API_KEY in
                                 the environment, goes only into the Authorization header and is masked in anything printed. The
                                 cost is the provider-reported `usage.cost`.

This is a measurement tool, not product code: the product path is the local one and holds no key.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dev"))
import resource_guard  # noqa: E402

API = "https://openrouter.ai/api/v1/audio/transcriptions"
KEY_ENV = "OPENROUTER_API_KEY"


def api_transcribe(model: str, wav: bytes, key: str) -> tuple[str, float | None, float]:
    body = json.dumps({"model": model, "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}, "language": "ko"}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # https URL above
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{model}: HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace').replace(key, '***')}") from None
    wall = time.perf_counter() - t0
    cost = d.get("usage", {}).get("cost")
    return d["text"].strip(), cost if isinstance(cost, (int, float)) else None, wall


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--api-model", action="append", default=[])
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)
    resource_guard.guard_or_exit("heavy")

    from kinetra_engine.stt import MODEL_REPO, MODEL_REVISION, Transcriber

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    base = args.cases.parent
    t = Transcriber()
    systems: dict[str, dict] = {"local-faster-whisper-small": {"texts": {}, "wall_s": {}}}
    t.transcribe(base / cases[0]["file"])  # warm-up: the first call pays for page-in of the model
    for c in cases:
        t0 = time.perf_counter()
        out = t.transcribe(base / c["file"])
        systems["local-faster-whisper-small"]["wall_s"][c["id"]] = round(time.perf_counter() - t0, 3)
        systems["local-faster-whisper-small"]["texts"][c["id"]] = out.text
        c["duration_s"] = round(out.duration_s, 2)
    key = os.environ.get(KEY_ENV, "").strip()
    if args.api_model and not key:
        raise SystemExit(f"{KEY_ENV} is not set")
    for m in args.api_model:
        s = systems[f"api:{m}"] = {"texts": {}, "wall_s": {}, "cost_usd": {}}
        for c in cases:
            text, cost, wall = api_transcribe(m, (base / c["file"]).read_bytes(), key)
            s["texts"][c["id"]], s["wall_s"][c["id"]], s["cost_usd"][c["id"]] = text, round(wall, 3), cost
    import faster_whisper

    data = {
        "date": time.strftime("%Y-%m-%d"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "local": {"repo": MODEL_REPO, "revision": MODEL_REVISION, "faster_whisper": faster_whisper.__version__, "device": "cpu", "compute_type": "int8", "beam_size": 5, "temperature": 0.0, "vad_filter": True},
        "note": args.note,
        "cases": [{k: c[k] for k in ("id", "group", "reference", "source", "duration_s")} for c in cases],
        "systems": systems,
    }
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
