"""Closed-loop logic with a stub pipeline (no MuJoCo): mass monotone, converges < 1 %, stops on lost witness, records p drops."""
from __future__ import annotations

import pytest

from physlab_core.schemas import Feasibility, HumanReview, Reproducibility, Verdict, VerdictStatus

from kinetra_engine import pipeline
from kinetra_engine.base import Budget
from kinetra_engine.design import closedloop as CL


def verdict(status=VerdictStatus.FEASIBLE_FOUND, p=0.4, params=None):
    f = Feasibility(p_success=p, ci_low=max(0, p - 0.05), ci_high=min(1, p + 0.05), n_samples=100) if status == VerdictStatus.FEASIBLE_FOUND else \
        Feasibility(p_success=0.0, ci_low=0.0, ci_high=1.0, n_samples=0)
    return Verdict(status=status, summary="s", feasibility=f, best_params=params or ({"a": 1.0} if status == VerdictStatus.FEASIBLE_FOUND else {}),
                   human_review=HumanReview(required=False), reproducibility=Reproducibility(seed=1, versions={}, search_budget={}),
                   necessary_checks=[])


class FakeRun:
    def __init__(self, v):
        self.verdict, self.cache_hit = v, False


def make(monkeypatch, design_fn, results):
    calls = []

    def fake_run(idea, tid, ov, seed, budget, **kw):
        calls.append(dict(ov))
        return FakeRun(results(len(calls), ov))
    monkeypatch.setattr(pipeline, "run", fake_run)
    ls = CL.LoopSpec(idea="i", template_id="t", seed=1, budget=Budget(10, 1.0, 10), base_overrides={"c": 5.0}, mass_key="m", base_mass=1000.0,
                     mass_note="mass", design_mass=design_fn, log=lambda s: None)
    return ls, calls


def test_converges_and_mass_is_monotone(monkeypatch):
    # designed mass depends on the witness: 40.0 kg (w=0), 40.2 kg (w>=1) -> the redesign after iteration 1 differs by 0.2 kg < 1 % of 1040 kg
    ls, calls = make(monkeypatch, lambda p, ov: 40.0 if p["w"] == 0.0 else 40.2, lambda n, ov: verdict(p=0.3 - 0.01 * n, params={"w": float(n)}))
    out = CL.run_loop(ls, verdict(p=0.4, params={"w": 0.0}), {"w": 0.0})
    rows = out["rows"]
    masses = [r["mass_kg"] for r in rows]
    assert masses == sorted(masses) and rows[0]["mass_kg"] == 1000.0 and rows[1]["mass_kg"] == pytest.approx(1040.0)
    assert out["converged"] and len(rows) <= 1 + CL.MAX_ITER
    assert rows[1]["assumption_overrides"] == {"c": 5.0, "m": pytest.approx(1040.0)}
    assert calls[0] == {"c": 5.0, "m": pytest.approx(1040.0)}
    assert rows[-1]["p_success"] < rows[0]["p_success"]        # the drop is recorded, not hidden


def test_stops_at_max_iter_when_mass_keeps_changing(monkeypatch):
    ls, _ = make(monkeypatch, lambda p, ov: 10.0 * (1 + p["w"]) * 3, lambda n, ov: verdict(params={"w": float(n)}))
    out = CL.run_loop(ls, verdict(params={"w": 0.0}), {"w": 0.0})
    assert len(out["rows"]) == 1 + CL.MAX_ITER and not out["converged"] and "limit" in out["stop_reason"]


def test_lost_witness_stops_loop_and_is_recorded(monkeypatch):
    ls, _ = make(monkeypatch, lambda p, ov: 30.0, lambda n, ov: verdict(status=VerdictStatus.NOT_FOUND_IN_BUDGET))
    out = CL.run_loop(ls, verdict(), {"w": 1.0})
    assert len(out["rows"]) == 2 and out["rows"][1]["status"] == "NOT_FOUND_IN_BUDGET" and not out["converged"]
    assert "no witness" in out["stop_reason"]
