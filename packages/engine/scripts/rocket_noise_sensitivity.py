"""Sensitivity row for the roadster: p_success of each recorded FEASIBLE_FOUND witness re-judged with per-nozzle thrust noise.

    packages/engine/.venv/bin/python packages/engine/scripts/rocket_noise_sensitivity.py [--n 500]

Same witness schedules and same Monte-Carlo seed as the bundle; only `thrust_spread` (half-range of an independent uniform per-nozzle thrust
error) changes from 0 to 0.03 / 0.10. Prints a JSON blob and writes apps/web/public/demo/roadster/sensitivity.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "src"))

from kinetra_engine import mc as mclib  # noqa: E402
from kinetra_engine.templates import get as get_template  # noqa: E402

OUT = REPO / "apps/web/public/demo/roadster"


def main() -> None:
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 500
    sc = json.loads((OUT / "scenario.json").read_text())
    tpl = get_template("rocket_car")
    seed = int(sc["build"]["seed"])
    rows = []
    for v in sc["variants"]:
        vd = v["verdict"]
        if vd["status"] != "FEASIBLE_FOUND":
            continue
        for spread in (0.0, 0.03, 0.10):
            spec = tpl.default_spec(sc["idea"], {"thruster_force_max": v["value"], "thrust_spread": spread})
            r = tpl.monte_carlo(spec, vd["best_params"], mclib.derive_seed(seed, "mc"), n)
            lo, hi = mclib.wilson_ci(r.n_success, r.n)
            rows.append(dict(thruster_force_max=v["value"], thrust_spread=spread, n=r.n, n_success=r.n_success, p_success=r.n_success / r.n,
                             ci_low=lo, ci_high=hi, failed_checks=r.binding.get("failed_checks", {}) if r.binding else {}))
            print(rows[-1], flush=True)
    (OUT / "sensitivity.json").write_text(json.dumps(dict(note="same witness + MC seed as the bundle; only per-nozzle thrust noise differs", n=n, rows=rows), indent=1) + "\n")


if __name__ == "__main__":
    main()
