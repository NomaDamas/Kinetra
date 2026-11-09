"""Verdict integration: how a calibration result changes a feasibility verdict.

Task: 360-degree pitch flip, stop upright (attitude.py success definition), with
  * controller designed on the assumptions' NOMINAL values (what the deterministic search does), then
  * Monte-Carlo over the assumptions' DISTRIBUTIONS -> p_success + Wilson 95% CI (what the Verdict reports).
BEFORE = the prior assumptions panel (llm_estimate, wide).  AFTER = calibration.json assumptions (narrow posterior).
Unmodelled disturbances common to both: per-thruster mismatch +-2%, sensor delay 0..30 ms, sensor noise.
The column "at hidden truth" is only available because the truth is synthetic; it is a sanity check, not a verdict input.
"""
from __future__ import annotations

import numpy as np

from . import calib
from .attitude import DISTURBANCE_SPEC, NOMINAL_SAMPLE, mc_eval, rollout, train, wilson
from .calib import HIDDEN_TRUTH, PARAM_KEYS, PRIORS

HW = {"ctrl_hi": 1.0, "extra_pair_arm": None, "article": "toy10"}


def prior_assumptions() -> list[dict]:
    out = []
    for k in PARAM_KEYS:
        mu, sd, lo, hi = PRIORS[k]
        from .article import PARAM_LABELS, PARAM_UNITS
        out.append({"key": k, "label": PARAM_LABELS[k], "value": mu, "unit": PARAM_UNITS[k],
                    "distribution": {"kind": "normal", "mean": mu, "std": sd, "clip_low": lo, "clip_high": hi},
                    "source": "llm_estimate", "confidence": "low", "editable": True})
    return out


def sample_from_assumptions(assumptions: list[dict], n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    by = {a["key"]: a for a in assumptions}
    out = []
    for _ in range(n):
        p = {}
        for k in PARAM_KEYS:
            d = by[k]["distribution"]
            if d["kind"] == "normal":
                v = rng.normal(d["mean"], d["std"])
                if d.get("clip_low") is not None:
                    v = max(v, d["clip_low"])
                if d.get("clip_high") is not None:
                    v = min(v, d["clip_high"])
            elif d["kind"] == "uniform":
                v = rng.uniform(d["low"], d["high"])
            else:
                v = by[k]["value"]
            p[k] = float(v)
        out.append({"params": p, "mismatch": rng.uniform(0.98, 1.02, 10).tolist(), "delay": int(rng.integers(0, 7)),
                    "noise_seed": int(rng.integers(0, 2**31 - 1)),
                    "sigma_theta": DISTURBANCE_SPEC["sigma_theta"], "sigma_omega": DISTURBANCE_SPEC["sigma_omega"]})
    return out


def nominal_params(assumptions: list[dict]) -> dict:
    return {a["key"]: a["value"] for a in assumptions}


def verdict_row(label: str, assumptions: list[dict], ctrl: dict, n_mc: int, seed: int, train_rollouts: int = 3000, hw: dict | None = None) -> dict:
    HW = hw or globals()['HW']
    nom = nominal_params(assumptions)
    c = dict(ctrl, model_params=nom)
    tr = train(HW, c, train_rollouts, seed)          # search on the assumptions' nominal values
    mc = mc_eval(HW, c, tr["params"], sample_from_assumptions(assumptions, n_mc, seed + 99))
    truth = dict(NOMINAL_SAMPLE, params=dict(HIDDEN_TRUTH), delay=2)
    at_truth = rollout(HW, c, tr["params"], truth)
    return {"label": label, "p": mc["success_rate"], "ci": (mc["ci_low"], mc["ci_high"]), "k": mc["k"], "n": mc["n"],
            "fuel": mc["fuel_mean"], "truth_ok": at_truth["ok"], "truth_err_deg": at_truth["e_theta_deg"],
            "nom_ok": rollout(HW, c, tr["params"], dict(NOMINAL_SAMPLE, params=nom))["ok"]}


def verdict_table(calib_assumptions: list[dict], n_mc: int = 200, seed: int = 31, t_end: float | None = None) -> tuple[str, list[dict]]:
    hw = dict(globals()['HW'], **({'t_end': t_end} if t_end else {}))
    base_ctrl = {"pd": {"kd_enabled": True}, "train_samples": 0, "cma_popsize": 12, "cma_sigma0": 0.25, "allocation": "saturated"}
    rows = []
    pri = prior_assumptions()
    for fam in ("schedule", "hybrid", "pd"):
        ctrl = dict(base_ctrl, family=fam)
        for lab, ass in (("before (prior panel)", pri), ("after (calibrated)", calib_assumptions)):
            r = verdict_row(lab, ass, ctrl, n_mc, seed, hw=hw)
            r["family"] = fam
            rows.append(r)
    lines = ["| controller | assumptions | p_success | Wilson 95% CI | CI width | at hidden truth | mean fuel (N*s) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['family']} | {r['label']} | {r['p']:.3f} ({r['k']}/{r['n']}) | [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}] | {r['ci'][1]-r['ci'][0]:.3f} | "
                     f"{'ok' if r['truth_ok'] else 'FAIL (%.0f deg off)' % r['truth_err_deg']} | {r['fuel']:.1f} |")
    return "\n".join(lines), rows
