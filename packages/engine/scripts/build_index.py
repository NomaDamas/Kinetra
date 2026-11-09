"""Rebuild apps/web/public/demo/index.json from the scenario directories present (idempotent, order-stable).

Run by every bundle builder after it writes its directory:  python scripts/build_index.py
Scans public/demo/*/scenario.json; adds the autoresearch entry iff autoresearch/*.json exist.
Scenario metadata (title/tagline/tier/hero) comes from optional keys in scenario.json, else the table below.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "apps/web/public/demo"

# fallbacks for scenario dirs that carry no metadata of their own
META = {
    "roadster": dict(title="Rocket roadster roll + pitch", tagline="Can a 1.3 t car roll AND pitch a full 360 deg off a ramp on cold-gas thrusters and land upright?", tier=1, hero=True),
    "g1_jump": dict(title="Humanoid jump", tagline="How high can a Unitree G1 jump and land?", tier=1, hero=False),
}
ORDER = ["roadster", "g1_jump"]
AUTORESEARCH = {"attitude_ledger": "ledger.json", "calibration": "calibration.json", "integration": "integration.json", "excitation": "excitation.json"}


def build(demo: Path = DEMO) -> dict:
    scen = []
    for p in sorted(demo.glob("*/scenario.json")):
        d = json.loads(p.read_text())
        sid = d.get("id", p.parent.name)
        m = {**META.get(sid, {}), **{k: d[k] for k in ("title", "tagline", "tier", "hero") if k in d}}
        scen.append(dict(id=sid, title=m.get("title", sid.replace("_", " ").title()), idea=d["idea"], template=d["template"],
                         tagline=m.get("tagline", ""), tier=int(m.get("tier", 1)), hero=bool(m.get("hero", False))))
    scen.sort(key=lambda s: (ORDER.index(s["id"]) if s["id"] in ORDER else len(ORDER), s["id"]))
    out: dict = {"scenarios": scen}
    ar = {k: f"autoresearch/{f}" for k, f in AUTORESEARCH.items() if (demo / "autoresearch" / f).exists()}
    if ar:
        out["autoresearch"] = ar
    return out


def main(argv: list[str]) -> None:
    demo = Path(argv[1]) if len(argv) > 1 else DEMO
    idx = build(demo)
    (demo / "index.json").write_text(json.dumps(idx, indent=1, ensure_ascii=False) + "\n")
    print(f"index.json: {[s['id'] for s in idx['scenarios']]} autoresearch={'autoresearch' in idx}")


if __name__ == "__main__":
    main(sys.argv)
