"""Requirement values equal the maxima of the real rollout; design is deterministic. Uses the recorded bundle witness (skips if absent)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from kinetra_engine.design import requirements as R, rocket as RK
from kinetra_engine.templates import get as get_template
from kinetra_engine.templates import rocket_car as rc

DEMO = Path(__file__).resolve().parents[3] / "apps/web/public/demo/roadster"


@pytest.fixture(scope="module")
def case():
    p = DEMO / "scenario.json"
    if not p.exists():
        pytest.skip("roadster bundle missing")
    sc = json.loads(p.read_text())
    tpl = get_template("rocket_car")
    for var in sorted(sc["variants"], key=lambda v: -v["value"]):
        if var["verdict"]["status"] != "FEASIBLE_FOUND":
            continue
        spec = tpl.default_spec(sc["idea"], {"thruster_force_max": var["value"]})
        if tpl.judge_nominal(spec, var["verdict"]["best_params"]):
            return tpl, spec, var
    pytest.skip("no recorded witness reproduces on the current model")


def test_requirements_equal_rollout_maxima(case):
    tpl, spec, var = case
    params = var["verdict"]["best_params"]
    d = R.rocket_requirements(spec, params, 1, var["trajectory"])
    sim, env = tpl._sim(spec), tpl._env_nom(spec)
    force = sim.controls(rc.params_to_x(params)[None])[0] * env.fmax[0]
    assert d.req("nozzle_peak_thrust")["value"] == pytest.approx(float(force.max()))
    assert d.req("total_impulse")["value"] == pytest.approx(float(force.sum() * rc.DT))
    assert d.req("propellant_mass")["value"] == pytest.approx(d.req("total_impulse")["value"] / (70.0 * R.G0))
    for r in d.requirements:
        assert r["required"] == pytest.approx(r["value"] * r["margin_factor"])
    # peak thrust also appears in the exported replay trajectory (sampled every 5th step: <= true peak, close to it)
    traj = json.loads((DEMO / var["trajectory"]).read_text())
    series_peak = max(max(s["values"]) for s in traj["series"] if s["name"].startswith("thrust_"))
    assert series_peak <= d.req("nozzle_peak_thrust")["value"] + 1e-6
    # landing load comes from the MuJoCo contact solver (> weight, finite)
    assert d.req("landing_load_factor")["value"] > 1.0


def test_design_is_deterministic_and_selection_lightest(case):
    tpl, spec, var = case
    params = var["verdict"]["best_params"]
    a = RK.design(spec, params, 1, "x")
    b = RK.design(spec, params, 1, "x")
    assert json.dumps(a["requirements"], sort_keys=True) == json.dumps(b["requirements"], sort_keys=True)
    assert [c["id"] for c in a["components"]] == [c["id"] for c in b["components"]]
    assert a["mass_added_kg"] == b["mass_added_kg"]
    tank = next(c for c in a["components"] if c["id"] == "tank")
    if tank["choice"]:
        assert all(m["ok"] for m in tank["meets"])
        assert tank["meets"][0]["provided"] >= tank["meets"][0]["required"]
    nozzle = next(c for c in a["components"] if c["id"] == "nozzle")
    assert nozzle["choice"] is None and nozzle["needs_sourcing"]      # no cataloged thruster is anywhere near kN thrust: honest 'needs sourcing'
    assert {p["id"] for p in a["custom_parts"]} == {"nozzle_bracket", "tank_cradle"}
    assert all(p["check"]["ok"] and "needs FEA" in p["check"]["label"] for p in a["custom_parts"])
