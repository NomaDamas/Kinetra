"""Excitation-design autoresearch: the loop proposes which test motions to run next to maximise identifiability.

Config  = {"budget": {...fixed...}, "excitation": {"trials": [exc, ...]}, "fit": {...}}
Metric  = expected information gain over the 9 prior-scaled parameters:
              EIG = 1/2 * mean_over_prior_draws logdet(I + J^T J)        (Bayesian D-optimality, nats)
          J = Jacobian of the whitened residuals wrt prior-normalised parameters at 3 prior-drawn points.
Budget  (fixed, in evaluator.validate): total test time <= 14 s, <= 5 trials, <= 3 pulses/trial, thrust level <= 1.
The loop only ever recommends experiments; it does not run anything on hardware. Added mass / drops are rig actions
that a human performs, hence the recommendation is a human-review item (see docs/autoresearch.md).
"""
from __future__ import annotations

import copy
from typing import Optional

import numpy as np

import calib
from calib import PARAM_KEYS, PRIORS, Problem, SIGMA_POS, SIGMA_ROT, jac_fd, simulate
from loop import EvalResult, Evaluator, Ledger, Proposal, Proposer

MAX_TIME = 14.0
MAX_TRIALS = 5
EIG_DRAWS = 3

# Weak "what an engineer would do first" design: spin up / spin down with the pure thruster couple in free flight.
BASELINE_TRIAL = {"name": "couple_spin", "T": 3.0, "z0": 50.0, "pitch0": 0.0, "vx0": 0.0, "added_mass": 0.0,
                  "pulses": [{"thr": [0, 1], "t_on": 0.2, "dur": 0.6, "level": 1.0}, {"thr": [2, 3], "t_on": 1.2, "dur": 0.3, "level": 1.0}]}

BASELINE = {
    "budget": {"max_time_s": MAX_TIME, "max_trials": MAX_TRIALS, "eig_draws": EIG_DRAWS},
    "metric": "expected_information_gain_nats",
    "excitation": {"trials": [BASELINE_TRIAL]},
    "fit": {"method": "lsq"},
}


def design_jacobian(trials: list[dict], x: np.ndarray) -> np.ndarray:
    pr = Problem(trials, [None] * len(trials), PARAM_KEYS)
    ref = [simulate(e, pr.p_of(x)) for e in trials]

    def f(theta):
        p = pr.p_of(theta)
        out = []
        for e, r in zip(trials, ref):
            s = simulate(e, p)
            out.append(calib.residual(s, r, SIGMA_POS, SIGMA_ROT))  # residual wrt noise-free reference at x
        return np.concatenate(out)

    return jac_fd(f, x)


def eig_of(trials: list[dict], seed: int = 0) -> tuple[float, dict]:
    rng = np.random.default_rng(seed)
    pts = [np.zeros(len(PARAM_KEYS))] + [np.clip(rng.normal(0, 0.7, len(PARAM_KEYS)), -2, 2) for _ in range(EIG_DRAWS - 1)]
    vals, contr = [], []
    for x in pts:
        J = design_jacobian(trials, x)
        M = np.eye(len(PARAM_KEYS)) + J.T @ J
        vals.append(0.5 * np.linalg.slogdet(M)[1])
        contr.append(np.sqrt(np.diag(np.linalg.inv(M))))
    c = np.mean(contr, axis=0)
    return float(np.mean(vals)), {k: float(v) for k, v in zip(PARAM_KEYS, c)}


class ExcitationEvaluator(Evaluator):
    metric = "expected_information_gain_nats"
    direction = "max"
    min_delta = 0.25  # must buy > 0.25 nats of information to be worth adding to a test campaign
    budget = {"jacobians": EIG_DRAWS, "fd_sims_per_jac": 2 * len(PARAM_KEYS) * 1, "kind": "evals"}

    def validate(self, c: dict) -> None:
        tr = c["excitation"]["trials"]
        assert 1 <= len(tr) <= c["budget"]["max_trials"] == MAX_TRIALS
        assert sum(t["T"] for t in tr) <= c["budget"]["max_time_s"] == MAX_TIME, "test-time budget exceeded"
        for t in tr:
            assert len(t["pulses"]) <= 3 and 0.5 <= t["T"] <= 6.0
            assert all(0 < p["level"] <= 1.0 and 0 <= p["t_on"] and p["t_on"] + p["dur"] <= t["T"] for p in t["pulses"])
            assert 0.0 <= t.get("added_mass", 0.0) <= 10.0 and 0.05 <= t["z0"] <= 60.0

    def evaluate(self, c: dict, seed: int) -> EvalResult:
        trials = c["excitation"]["trials"]
        eig, contr = eig_of(trials, seed=7)  # same prior draws for every candidate (common random numbers)
        ident = [k for k, v in contr.items() if v < 0.5]
        return EvalResult(eig, {"contraction": contr, "identified": ident, "n_identified": len(ident),
                                "test_time_s": sum(t["T"] for t in trials), "n_trials": len(trials)},
                          {"jacobians": EIG_DRAWS})


def _add(trial: dict) -> list:
    return [{"op": "add", "path": "/excitation/trials/-", "value": trial}]


def _has(c: dict, name: str) -> bool:
    return any(t["name"] == name for t in c["excitation"]["trials"])


def _room(c: dict, T: float) -> bool:
    return (len(c["excitation"]["trials"]) < MAX_TRIALS and sum(t["T"] for t in c["excitation"]["trials"]) + T <= MAX_TIME)


def T_(name, T, z0=50.0, pitch0=0.0, vx0=0.0, added_mass=0.0, pulses=()):
    return {"name": name, "T": T, "z0": z0, "pitch0": pitch0, "vx0": vx0, "added_mass": added_mass, "pulses": list(pulses)}


def P_(thr, t_on, dur, level=1.0):
    return {"thr": thr, "t_on": t_on, "dur": dur, "level": level}


# (hypothesis, patch, guard)
EXCITATION_HYPOTHESES = [
    ("Add a single-thruster pulse (t0 only): net force AND torque, so mass/thrust-gain and COM-x separate from the pure couple.",
     _add(T_("single_t0", 2.5, pulses=[P_([0], 0.3, 0.8)])), lambda c: not _has(c, "single_t0") and _room(c, 2.5)),
    ("Add a lateral thruster pulse (t4 only, +x force at z=+0.15): torque arm depends on COM-z.",
     _add(T_("lateral_t4", 2.5, pulses=[P_([4], 0.3, 0.8)])), lambda c: not _has(c, "lateral_t4") and _room(c, 2.5)),
    ("Add a 2 m tilted drop onto the ground (no thrust): contact stiffness/damping and COM show up in the impact.",
     _add(T_("tilted_drop", 2.0, z0=2.0, pitch0=0.5)), lambda c: not _has(c, "tilted_drop") and _room(c, 2.0)),
    ("Add a coast with 3 m/s initial velocity: linear drag identifiable from decay.",
     _add(T_("coast_vx", 2.0, vx0=3.0)), lambda c: not _has(c, "coast_vx") and _room(c, 2.0)),
    ("Repeat the single-thruster pulse with a known +5 kg calibration mass: separates mass from thrust-gain (F/m vs gain/inertia).",
     _add(T_("single_t0_plus5kg", 2.5, added_mass=5.0, pulses=[P_([0], 0.3, 0.8)])), lambda c: _has(c, "single_t0") and not _has(c, "single_t0_plus5kg") and _room(c, 2.5)),
    ("Add a long spin-up then coast (rotational damping from rate decay).",
     _add(T_("spin_coast", 3.0, pulses=[P_([0, 1], 0.1, 0.8)])), lambda c: not _has(c, "spin_coast") and _room(c, 3.0)),
    ("Lengthen the baseline couple trial (cheap longer record).",
     [{"op": "replace", "path": "/excitation/trials/0/T", "value": 5.0}], lambda c: c["excitation"]["trials"][0]["T"] < 5.0),
    ("Cheat attempt: raise the test-time budget to 60 s (evaluator contract; forbidden).",
     [{"op": "replace", "path": "/budget/max_time_s", "value": 60.0}], lambda c: True),
]


class ExcitationProposer(Proposer):
    name = "rules"

    def __init__(self, hyps: Optional[list] = None):
        self.q = list(hyps if hyps is not None else EXCITATION_HYPOTHESES)

    def propose(self, ledger: Ledger, incumbent) -> Optional[Proposal]:
        while self.q:
            h, p, g = self.q.pop(0)
            if g(incumbent.config):
                return Proposal(h, copy.deepcopy(p))
        return None
