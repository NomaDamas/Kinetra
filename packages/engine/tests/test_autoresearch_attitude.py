import copy
import os

os.environ.setdefault("KINETRA_AR_WORKERS", "0")

import pytest

from kinetra_engine.autoresearch import attitude as att, attitude_loop as al
from kinetra_engine.autoresearch.article import Article, PRESETS
from kinetra_engine.autoresearch.ledger import Ledger, run_loop
from kinetra_engine.autoresearch.proposers import RuleProposer


def _cfg(article, family, **ctrl):
    c = al.baseline_config(article)
    c["ctrl"]["family"] = family
    c["ctrl"].update(ctrl)
    return c


def test_roadster_article_scale():
    a = Article("roadster")
    assert a.m.body_mass[a.body] == 1300.0
    assert abs(a.inertia_y_nominal - 2085.368) < 1e-3
    assert max(abs(t["pos"][0]) for t in a.layout) == 2.1
    assert a.fmax == 5000.0
    assert PRESETS["toy10"].mass == 10.0


@pytest.mark.parametrize("article", ["toy10", "roadster"])
def test_pd_flips_open_loop_brittle(article):
    n = 40
    res = {}
    for fam in ("schedule", "pd"):
        c = _cfg(article, fam)
        tr = att.train(al.hw_of(c), c["ctrl"], 1200, 5)
        m = att.mc_eval(al.hw_of(c), c["ctrl"], tr["params"], att.sample_disturbances(att.CONFIRM_SEED, n, al._spec(c), article))
        res[fam] = m["success_rate"]
    assert res["pd"] >= 0.9
    assert res["schedule"] < 0.5


def test_attitude_determinism_and_worker_independence():
    c = _cfg("toy10", "pd")
    hw = al.hw_of(c)
    s = att.sample_disturbances(11, 8, al._spec(c), "toy10")
    t1 = att.train(hw, c["ctrl"], 240, 3)
    t2 = att.train(hw, c["ctrl"], 240, 3)
    assert t1["params"] == t2["params"]
    m1 = att.mc_eval(hw, c["ctrl"], t1["params"], s)
    m2 = att.mc_eval(hw, c["ctrl"], t1["params"], s)
    assert m1 == m2


def test_attitude_loop_gates_cheats(monkeypatch):
    monkeypatch.setattr(al, "TRAIN_ROLLOUTS", 240)
    ev = al.AttitudeEvaluator("toy10")
    base = al.baseline_config("toy10")
    base["budget"]["train_rollouts"] = 240
    ev_budget = {"train_rollouts": 240}
    # contract values are module constants; the evaluator checks them against the same module attribute
    hyps = [h for h in al.hypotheses("toy10") if h[0].startswith("Cheat") or "Add derivative" in h[0] or "Widen" in h[0]]
    led = Ledger()
    run_loop("att", base, ev, RuleProposer(hyps), led, 10, base_seed=1, verbose=False)
    by = {e.hypothesis[:12]: e for e in led.entries[1:]}
    assert led.verify_chain()
    gates = {e.gate for e in led.entries if e.decision == "gated"}
    assert gates == {"approval:physical_assumption", "forbidden", "approval:hardware"}
    assert all(e.value is None for e in led.entries if e.decision == "gated")
