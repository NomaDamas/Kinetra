"""Calibration autoresearch: the loop decides WHICH parameters to free and WHICH test motions to adopt,
judged by ONE scalar: held-out validation RMS (in sensor-noise units; 1.0 = at the noise floor).

Ground truth is a hidden perturbed model (calib.HIDDEN_TRUTH) + sensor noise. The fitter never sees it; it is used
only (a) to synthesise the "measured" CSV-equivalent traces and (b) after the fact, to check coverage of the posterior.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Optional

import numpy as np

from . import calib
from .calib import HIDDEN_TRUTH, PARAM_KEYS, PRIORS, SIGMA_POS, SIGMA_ROT, add_noise, simulate
from .excitation import BASELINE_TRIAL, P_, T_, MAX_TIME
from .ledger import EvalResult, Evaluator, Ledger, Proposal, Proposer, run_loop

# held-out validation motions: NOT part of any training campaign, different from every training trial
VAL_TRIALS = [
    T_("val_mixed", 3.0, pulses=[P_([1], 0.2, 0.5, 0.8), P_([3, 0], 1.2, 0.4, 1.0)]),
    T_("val_drop", 2.0, z0=1.2, pitch0=-0.4, pulses=[P_([4], 0.0, 0.3, 0.7)]),
]
DATA_SEED = 4242
VAL_SEED = 9191
MAX_FREE = 9

BASELINE = {
    "budget": {"max_time_s": MAX_TIME, "max_trials": 5},
    "metric": "heldout_val_rms_noise_units",
    "eval": {"val_seed": VAL_SEED, "data_seed": DATA_SEED},
    "excitation": {"trials": [BASELINE_TRIAL]},
    "fit": {"free": ["mass"], "method": "lsq"},
}


def make_data(trials: list[dict], seed: int, truth: dict | None = None) -> list[dict]:
    return [add_noise(simulate(e, truth or HIDDEN_TRUTH), seed + 17 * i) for i, e in enumerate(trials)]


class CalEvaluator(Evaluator):
    metric = "heldout_val_rms_noise_units"
    direction = "min"
    min_delta = 0.05  # parsimony: a change must beat the incumbent by > 0.05 noise-sigma to be kept
    budget = {"max_lsq_nfev": 40, "kind": "evals"}

    def __init__(self):
        self.val_data = make_data(VAL_TRIALS, VAL_SEED)

    def validate(self, c: dict) -> None:
        tr = c["excitation"]["trials"]
        assert 1 <= len(tr) <= c["budget"]["max_trials"] == 5
        assert sum(t["T"] for t in tr) <= c["budget"]["max_time_s"] == MAX_TIME, "test-time budget exceeded"
        assert 1 <= len(c["fit"]["free"]) <= MAX_FREE and set(c["fit"]["free"]) <= set(PARAM_KEYS)
        assert c["eval"]["val_seed"] == VAL_SEED and c["eval"]["data_seed"] == DATA_SEED, "eval contract is fixed"

    def evaluate(self, c: dict, seed: int) -> EvalResult:
        trials = c["excitation"]["trials"]
        datas = make_data(trials, c["eval"]["data_seed"])
        free = c["fit"]["free"]
        res = calib.fit(trials, datas, free, method=c["fit"]["method"], seed=seed)
        train_rms = calib.data_rms(trials, datas, res["p"])
        val_rms = calib.data_rms(VAL_TRIALS, self.val_data, res["p"])
        # diagnostic ONLY (hidden truth; never used for the decision)
        err = {k: (res["p"][k] - HIDDEN_TRUTH[k]) / PRIORS[k][1] for k in free}
        return EvalResult(val_rms, {"train_rms": train_rms, "free": free, "fit": res["p"], "nsim": res["nsim"],
                                    "diag_err_in_prior_sd": err}, {"nsim": res["nsim"], "test_time_s": sum(t["T"] for t in trials)})


def _rep(path, v):
    return {"op": "replace", "path": path, "value": v}


def _addfree(k):
    return lambda c: k not in c["fit"]["free"]


def _free_patch(c, ks):
    return [_rep("/fit/free", c["fit"]["free"] + [k for k in ks if k not in c["fit"]["free"]])]


class CalProposer(Proposer):
    """Rule proposer. Patches that depend on the incumbent are built lazily (callable patch)."""
    name = "rules"

    def __init__(self, recommended_trials: list[dict]):
        rec = recommended_trials
        self.q = [
            ("Free inertia_scale too (spin response is set by thrust-couple torque / inertia).", lambda c: _free_patch(c, ["inertia_scale"])),
            ("Free thrust_gain too.", lambda c: _free_patch(c, ["thrust_gain"])),
            ("Free rot_damping and lin_damping.", lambda c: _free_patch(c, ["rot_damping", "lin_damping"])),
            ("Free COM offset (com_x, com_z).", lambda c: _free_patch(c, ["com_x", "com_z"])),
            ("Free the contact parameters although the campaign has no ground contact (expect: no improvement => discard).",
             lambda c: _free_patch(c, ["contact_timeconst", "contact_dampratio"])),
            ("Cheat attempt: swap the validation seed to an easier set (evaluator contract; forbidden).", lambda c: [_rep("/eval/val_seed", 1)]),
            ("Greedy one-at-a-time freeing is path-dependent (mass/thrust-gain/inertia trade off). Free ALL 9 parameters at once on the current (couple-only) campaign.",
             lambda c: [_rep("/fit/free", list(PARAM_KEYS))]),
            ("Adopt the excitation-design loop's recommended campaign (5 trials, 12.5 s): single-thruster pulses, lateral pulse, tilted drop, +5 kg run.",
             lambda c: [_rep("/excitation/trials", rec)]),
            ("Free ALL 9 parameters on the recommended campaign.", lambda c: [_rep("/fit/free", list(PARAM_KEYS))]),
            ("Switch the fitter to CMA-ES global search followed by least squares.", lambda c: [_rep("/fit/method", "cma_lsq")]),
        ]

    def propose(self, ledger: Ledger, incumbent) -> Optional[Proposal]:
        if not self.q:
            return None
        h, f = self.q.pop(0)
        return Proposal(h, f(incumbent.config))


def run_calibration(ledger: Ledger, recommended_trials: list[dict], verbose: bool = True) -> dict:
    r = run_loop("cal", BASELINE, CalEvaluator(), CalProposer(recommended_trials), ledger, max_experiments=12, base_seed=5, verbose=verbose)
    return r["incumbent"]


def calibration_report(cfg: dict, source: str, boot_k: int = 12, seed: int = 11) -> dict:
    """Final fit with the incumbent config: Laplace posterior + SVD + bootstrap + Assumption JSON."""
    trials, free = cfg["excitation"]["trials"], cfg["fit"]["free"]
    datas = make_data(trials, cfg["eval"]["data_seed"])
    res = calib.fit(trials, datas, free, method=cfg["fit"]["method"], seed=seed)
    idn = calib.identifiability(trials, datas, res["theta"], free)
    assumptions, status = calib.to_assumptions(free, res["p"], idn, source)
    boot = calib.bootstrap(trials, datas, free, res, k=boot_k, seed=seed) if boot_k else None
    rms = calib.data_rms(trials, datas, res["p"])
    val_rms = calib.data_rms(VAL_TRIALS, make_data(VAL_TRIALS, VAL_SEED), res["p"])
    # coverage check against the HIDDEN truth (possible only because this is synthetic)
    cover = {}
    for a in assumptions:
        k = a["key"]
        d = a["distribution"]
        z = (HIDDEN_TRUTH[k] - d["mean"]) / max(d["std"], 1e-12)
        cover[k] = {"truth": HIDDEN_TRUTH[k], "mean": d["mean"], "std": d["std"], "z": z, "within_2sd": bool(abs(z) <= 2.0)}
    return {"fit": res["p"], "free": free, "train_rms": rms, "val_rms": val_rms, "idn": idn, "status": status, "assumptions": assumptions,
            "bootstrap": boot, "coverage": cover, "n_trials": len(trials), "test_time_s": sum(t["T"] for t in trials)}


def fmt_table(rep: dict) -> str:
    idn = rep["idn"]
    rows = ["| param | prior mean (sd) | fit | post sd | post/prior sd | verdict | hidden truth | z |", "|---|---|---|---|---|---|---|---|"]
    for i, k in enumerate(idn["params"]):
        mu, sd, _, _ = PRIORS[k]
        s = rep["status"][k]
        fit = "-" if s["fit"] is None else f"{s['fit']:.4g}"
        ps = "-" if s["post_sd"] is None else f"{s['post_sd']:.3g}"
        cv = rep["coverage"][k]
        rows.append(f"| {k} | {mu:g} ({sd:g}) | {fit} | {ps} | {s['contraction']:.3f} | {s['status']} | {HIDDEN_TRUTH[k]:g} | {cv['z']:+.1f} |")
    return "\n".join(rows)


def calibration_doc(rep: dict, design_name: str) -> dict:
    """JSON-able calibration result (Assumption-compatible `assumptions`, identifiability classes, residuals, truth)."""
    return {
        "kind": "calibration_result",
        "note": "SYNTHETIC ground truth (hidden perturbed model + sensor noise). Fitter model class == truth model class, "
                "so coverage is self-consistent, NOT sim-to-real validation.",
        "assumptions": rep["assumptions"],
        "identifiability": {k: dict(v) for k, v in rep["status"].items()},
        "residual_rms_noise_units": {"train": rep["train_rms"], "heldout_validation": rep["val_rms"]},
        "singular_values_of_whitened_jacobian": rep["idn"]["singular_values"].tolist(),
        "condition_number": rep["idn"]["cond"],
        "weakest_direction": rep["idn"]["weakest_dir"],
        "bootstrap": rep["bootstrap"],
        "coverage": rep["coverage"],
        "truth": {k: HIDDEN_TRUTH[k] for k in PARAM_KEYS},
        "prior": {k: {"mean": PRIORS[k][0], "sd": PRIORS[k][1]} for k in PARAM_KEYS},
        "campaign": design_name,
    }


def emit_json(path: str, rep: dict, design_name: str) -> None:
    with open(path, "w") as f:
        json.dump(calibration_doc(rep, design_name), f, indent=2, default=float)


def trajectory_compare(fit_p: dict, trial: dict | None = None, seed: int = VAL_SEED, max_pts: int = 200) -> dict:
    """Held-out trial replayed three ways: 'reference' (hidden truth + sensor noise = the 'measured' trace),
    'fitted' (calibrated parameters), 'prior' (prior means). Series: x, z [m], pitch_deg."""
    import math
    trial = trial or VAL_TRIALS[0]
    prior_p = {k: PRIORS[k][0] for k in PARAM_KEYS}
    ref = add_noise(simulate(trial, HIDDEN_TRUTH), seed)

    def series(tr):
        pitch = np.degrees(np.unwrap([2.0 * math.atan2(q[2], q[0]) for q in tr["quat"]]))
        return {"x": tr["pos"][:, 0], "z": tr["pos"][:, 2], "pitch_deg": pitch}

    out = {"trial": trial["name"], "t": ref["t"], "reference": series(ref),
           "fitted": series(simulate(trial, fit_p)), "prior": series(simulate(trial, prior_p))}
    n = len(ref["t"])
    step = max(1, math.ceil(n / max_pts))

    def cut(v):
        return [round(float(a), 5) for a in np.asarray(v)[::step]]

    return {"trial": out["trial"], "t": cut(out["t"]),
            **{k: {n_: cut(v) for n_, v in out[k].items()} for k in ("reference", "fitted", "prior")}}
