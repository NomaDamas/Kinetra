"""Attitude-control autoresearch: evaluator + rule-based hypothesis list + baseline config, per article preset."""
from __future__ import annotations

import copy

from .attitude import (CONFIRM_SEED, DISTURBANCE_SPEC, EVAL_SEED, FUEL_TIEBREAK, NOMINAL_SAMPLE, mc_eval,
                       rollout, sample_disturbances, train)
from .article import PRESETS
from .ledger import EvalResult, Evaluator, Ledger, run_loop
from .proposers import RuleProposer, maybe_llm_proposer, rep

TRAIN_ROLLOUTS = 3000   # fixed per-experiment budget (CMA-ES rollouts)
N_MC = 40               # >= 30 disturbed samples per decision


def baseline_config(article: str = "toy10") -> dict:
    return {
        "article": article,
        "budget": {"train_rollouts": TRAIN_ROLLOUTS},
        "eval": {"n_mc": N_MC, "seed": EVAL_SEED},
        "metric": "mc_success_rate - 1e-4*fuel_Ns(toy-normalised)",
        "disturbance": {k: (list(v) if isinstance(v, tuple) else v) for k, v in DISTURBANCE_SPEC.items()},
        "hw": {"ctrl_hi": 1.0, "extra_pair_arm": None},
        "ctrl": {
            "family": "schedule",             # schedule | pd | hybrid
            "allocation": "saturated",        # saturated | bangbang
            "pd": {"kd_enabled": True},
            "train_samples": 0,               # 0 = tune on the nominal model only
            "cma_popsize": 12,
            "cma_sigma0": 0.25,
        },
    }


def hw_of(c: dict) -> dict:
    return dict(c["hw"], article=c["article"])


def _spec(c: dict) -> dict:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in c["disturbance"].items()}


class AttitudeEvaluator(Evaluator):
    metric = "mc_success_rate_minus_fuel_tiebreak"
    direction = "max"
    min_delta = 0.0

    def __init__(self, article: str = "toy10"):
        self.article = article
        self.budget = {"train_rollouts": TRAIN_ROLLOUTS, "mc_samples": N_MC, "kind": "evals", "article": article}

    def validate(self, c: dict) -> None:
        ct = c["ctrl"]
        assert c["article"] == self.article and c["article"] in PRESETS, "article is fixed by the harness"
        assert ct["family"] in ("schedule", "pd", "hybrid"), ct["family"]
        assert ct["allocation"] in ("saturated", "bangbang")
        assert 0 <= ct["train_samples"] <= 32
        assert 4 <= ct["cma_popsize"] <= 48
        assert 1.0 <= c["hw"]["ctrl_hi"] <= 2.0
        assert c["budget"]["train_rollouts"] == TRAIN_ROLLOUTS, "budget is fixed by the harness"
        assert c["eval"]["n_mc"] == N_MC and c["eval"]["seed"] == EVAL_SEED, "eval contract is fixed by the harness"

    def evaluate(self, c: dict, seed: int) -> EvalResult:
        hw = hw_of(c)
        tr = train(hw, c["ctrl"], c["budget"]["train_rollouts"], seed)
        samples = sample_disturbances(c["eval"]["seed"], c["eval"]["n_mc"], _spec(c), c["article"])
        mc = mc_eval(hw, c["ctrl"], tr["params"], samples)
        nom = rollout(hw, c["ctrl"], tr["params"], NOMINAL_SAMPLE)
        details = {"mc": mc, "params": tr["params"], "train_cost": tr["train_cost"], "nominal_ok": nom["ok"],
                   "nominal_fuel": nom["fuel"], "generations": tr["generations"]}
        return EvalResult(mc["metric"], details, {"train_rollouts": tr["rollouts_used"], "mc_samples": mc["n"]})


def confirm(c: dict, params: dict, n: int = 200) -> dict:
    """Fresh held-out MC set, never used for any keep/discard decision."""
    return mc_eval(hw_of(c), c["ctrl"], params, sample_disturbances(CONFIRM_SEED, n, _spec(c), c["article"]))


# ---------------------------------------------------------------- hypotheses

always = lambda c: True
is_fam = lambda f: (lambda c: c["ctrl"]["family"] == f)


def hypotheses(article: str = "toy10") -> list:
    arm = PRESETS[article].extra_arm_hyp
    return [
        ("Open-loop schedule is brittle because it was tuned on the nominal model; tune it on 8 disturbed samples (robust open-loop).",
         [rep("/ctrl/train_samples", 8)], is_fam("schedule")),
        ("Cheat attempt: shrinking the thrust-gain disturbance to +-2% would raise success (physical assumption; needs human).",
         [rep("/disturbance/thrust_gain", ["uniform", 0.98, 1.02])], always),
        ("Cheat attempt: fewer MC samples would be faster (evaluator contract; forbidden).",
         [rep("/eval/n_mc", 5)], always),
        ("Replace open-loop with attitude feedback: P-only saturated allocation (expect unstable ringing without damping).",
         [rep("/ctrl/family", "pd"), rep("/ctrl/pd/kd_enabled", False), rep("/ctrl/train_samples", 0)], is_fam("schedule")),
        ("Add derivative gain (rate damping) to the PD attitude feedback.",
         [rep("/ctrl/family", "pd"), rep("/ctrl/pd/kd_enabled", True), rep("/ctrl/train_samples", 0)], always),
        ("Try schedule+PD hybrid (feedforward flip + feedback correction) tuned on nominal.",
         [rep("/ctrl/family", "hybrid"), rep("/ctrl/allocation", "saturated")], always),
        ("Bang-bang (deadband) thruster allocation instead of proportional/saturated.",
         [rep("/ctrl/allocation", "bangbang")], always),
        ("Tune the incumbent controller on 8 disturbed samples (robust training).",
         [rep("/ctrl/train_samples", 8)], lambda c: c["ctrl"]["train_samples"] == 0),
        ("Hybrid on 8 disturbed samples with saturated allocation.",
         [rep("/ctrl/family", "hybrid"), rep("/ctrl/allocation", "saturated"), rep("/ctrl/train_samples", 8)], always),
        ("Widen thrust ctrlrange 1.0 -> 1.5 (hardware change; needs human).",
         [rep("/hw/ctrl_hi", 1.5)], always),
        (f"Add a second thruster pair at +-{arm} m lever arm (hardware change; needs human).",
         [rep("/hw/extra_pair_arm", arm)], always),
    ]


def hw_hypotheses(article: str = "toy10") -> list:
    return [h for h in hypotheses(article) if h[1][0]["path"].startswith("/hw")]


LLM_PATHS = ("/ctrl/family (schedule|pd|hybrid), /ctrl/allocation (saturated|bangbang), /ctrl/pd/kd_enabled, "
             "/ctrl/train_samples (0..32), /ctrl/cma_popsize (4..48), /ctrl/cma_sigma0, /hw/ctrl_hi, /hw/extra_pair_arm")


def run_attitude(ledger: Ledger, article: str = "toy10", prefix: str = "att", verbose: bool = True) -> dict:
    """Phase 1: autonomous (no approvals). Phase 2: a human approves the hardware class and the gated hardware
    proposals are re-run from the phase-1 incumbent. Everything goes into the same ledger.
    The 'approval' is a dict entry, not a UI."""
    ev = AttitudeEvaluator(article)
    r1 = run_loop(prefix, baseline_config(article), ev, RuleProposer(hypotheses(article)), ledger,
                  max_experiments=40, base_seed=1, approvals={}, verbose=verbose)
    r2 = run_loop(f"{prefix}-hw", r1["incumbent"].config, ev, RuleProposer(hw_hypotheses(article)), ledger,
                  max_experiments=10, base_seed=2, approvals={"approval:hardware": "human:demo-reviewer"},
                  verbose=verbose, baseline_seed=r1["incumbent"].seed)
    return {"phase1": r1["incumbent"], "phase2": r2["incumbent"]}


def run_attitude_llm(ledger: Ledger, start, article: str = "toy10", steps: int = 3, verbose: bool = True):
    """Optional (UNTESTED): continue from `start` with the LLM proposer. Returns None unless enabled by env."""
    p = maybe_llm_proposer(LLM_PATHS, "attitude flip controller", lambda c: {"ctrl": c["ctrl"], "hw": c["hw"]})
    if p is None:
        return None
    return run_loop("att-llm", start.config, AttitudeEvaluator(article), p, ledger, max_experiments=steps,
                    base_seed=3, verbose=verbose, baseline_seed=start.seed)["incumbent"]
