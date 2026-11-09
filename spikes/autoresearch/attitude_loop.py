"""Attitude-control autoresearch: evaluator + rule-based proposer + baseline config."""
from __future__ import annotations

import copy
import json
from typing import Callable, Optional

from attitude import (CONFIRM_SEED, DISTURBANCE_SPEC, EVAL_SEED, FUEL_TIEBREAK, NOMINAL_SAMPLE, mc_eval,
                      rollout, sample_disturbances, train)
from loop import EvalResult, Evaluator, Ledger, Proposal, Proposer, run_loop

TRAIN_ROLLOUTS = 3000   # fixed per-experiment budget (CMA-ES rollouts)
N_MC = 40               # >= 30 disturbed samples per decision

BASELINE = {
    "budget": {"train_rollouts": TRAIN_ROLLOUTS},
    "eval": {"n_mc": N_MC, "seed": EVAL_SEED},
    "metric": "mc_success_rate - 1e-4*fuel_Ns",
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


class AttitudeEvaluator(Evaluator):
    metric = "mc_success_rate_minus_fuel_tiebreak"
    direction = "max"
    min_delta = 0.0
    budget = {"train_rollouts": TRAIN_ROLLOUTS, "mc_samples": N_MC, "kind": "evals"}

    def validate(self, c: dict) -> None:
        ct = c["ctrl"]
        assert ct["family"] in ("schedule", "pd", "hybrid"), ct["family"]
        assert ct["allocation"] in ("saturated", "bangbang")
        assert 0 <= ct["train_samples"] <= 32
        assert 4 <= ct["cma_popsize"] <= 48
        assert 1.0 <= c["hw"]["ctrl_hi"] <= 2.0
        assert c["budget"]["train_rollouts"] == TRAIN_ROLLOUTS, "budget is fixed by the harness"
        assert c["eval"]["n_mc"] == N_MC and c["eval"]["seed"] == EVAL_SEED, "eval contract is fixed by the harness"

    def evaluate(self, c: dict, seed: int) -> EvalResult:
        tr = train(c["hw"], c["ctrl"], c["budget"]["train_rollouts"], seed)
        samples = sample_disturbances(c["eval"]["seed"], c["eval"]["n_mc"], _spec(c))
        mc = mc_eval(c["hw"], c["ctrl"], tr["params"], samples)
        nom = rollout(c["hw"], c["ctrl"], tr["params"], NOMINAL_SAMPLE)
        details = {"mc": mc, "params": tr["params"], "train_cost": tr["train_cost"], "nominal_ok": nom["ok"],
                   "nominal_fuel": nom["fuel"], "generations": tr["generations"]}
        return EvalResult(mc["metric"], details, {"train_rollouts": tr["rollouts_used"], "mc_samples": mc["n"]})


def _spec(c: dict) -> dict:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in c["disturbance"].items()}


def confirm(c: dict, params: dict, n: int = 200) -> dict:
    """Fresh held-out MC set, never used for any keep/discard decision."""
    return mc_eval(c["hw"], c["ctrl"], params, sample_disturbances(CONFIRM_SEED, n, _spec(c)))


# ---------------------------------------------------------------- proposers


def _rep(path, value):
    return {"op": "replace", "path": path, "value": value}


class RuleProposer(Proposer):
    """Hand-written hypothesis list. Each entry has an `applies(cfg)` guard so it is skipped when moot."""
    name = "rules"

    def __init__(self, hypotheses: Optional[list] = None):
        self.queue = list(hypotheses if hypotheses is not None else DEFAULT_HYPOTHESES)

    def propose(self, ledger: Ledger, incumbent) -> Optional[Proposal]:
        while self.queue:
            hyp, patch, applies = self.queue.pop(0)
            if applies(incumbent.config):
                return Proposal(hyp, copy.deepcopy(patch))
        return None


always: Callable = lambda c: True
is_fam = lambda f: (lambda c: c["ctrl"]["family"] == f)

DEFAULT_HYPOTHESES = [
    ("Open-loop schedule is brittle because it was tuned on the nominal model; tune it on 8 disturbed samples (robust open-loop).",
     [_rep("/ctrl/train_samples", 8)], is_fam("schedule")),
    ("Cheat attempt: shrinking the thrust-gain disturbance to +-2% would raise success (physical assumption; needs human).",
     [_rep("/disturbance/thrust_gain", ["uniform", 0.98, 1.02])], always),
    ("Cheat attempt: fewer MC samples would be faster (evaluator contract; forbidden).",
     [_rep("/eval/n_mc", 5)], always),
    ("Replace open-loop with attitude feedback: P-only saturated allocation (expect unstable ringing without damping).",
     [_rep("/ctrl/family", "pd"), _rep("/ctrl/pd/kd_enabled", False), _rep("/ctrl/train_samples", 0)], is_fam("schedule")),
    ("Add derivative gain (rate damping) to the PD attitude feedback.",
     [_rep("/ctrl/family", "pd"), _rep("/ctrl/pd/kd_enabled", True), _rep("/ctrl/train_samples", 0)], always),
    ("Try schedule+PD hybrid (feedforward flip + feedback correction) tuned on nominal.",
     [_rep("/ctrl/family", "hybrid"), _rep("/ctrl/allocation", "saturated")], always),
    ("Bang-bang (deadband) thruster allocation instead of proportional/saturated.",
     [_rep("/ctrl/allocation", "bangbang")], always),
    ("Tune the incumbent controller on 8 disturbed samples (robust training).",
     [_rep("/ctrl/train_samples", 8)], lambda c: c["ctrl"]["train_samples"] == 0),
    ("Hybrid on 8 disturbed samples with saturated allocation.",
     [_rep("/ctrl/family", "hybrid"), _rep("/ctrl/allocation", "saturated"), _rep("/ctrl/train_samples", 8)], always),
    ("Widen thrust ctrlrange 1.0 -> 1.5 (hardware change; needs human).",
     [_rep("/hw/ctrl_hi", 1.5)], always),
    ("Add a second thruster pair at +-0.7 m lever arm (hardware change; needs human).",
     [_rep("/hw/extra_pair_arm", 0.7)], always),
]


class LLMProposer(Proposer):
    """OPTIONAL. Reads the ledger tail and asks an LLM for ONE hypothesis + JSON patch.

    UNTESTED against a live API in this spike (no key was used). It is only constructed when
    ANTHROPIC_API_KEY or OPENAI_API_KEY is set. The LLM proposes structure only; its patch passes the same
    gate (forbidden/approval/auto) and the same fixed-budget evaluator as any rule-based proposal.
    """
    name = "llm"

    def __init__(self, model: Optional[str] = None):
        import os
        self.anthropic = os.environ.get("ANTHROPIC_API_KEY")
        self.openai = os.environ.get("OPENAI_API_KEY")
        if not (self.anthropic or self.openai):
            raise RuntimeError("no LLM API key in environment")
        self.model = model or ("claude-sonnet-4-5" if self.anthropic else "gpt-4o")

    def _prompt(self, ledger: Ledger, inc) -> str:
        tail = [{"id": e.id, "hypothesis": e.hypothesis, "change": e.change, "value": e.value, "decision": e.decision}
                for e in ledger.tail(8)]
        return (
            "You are the proposer in an autoresearch loop for a spacecraft-style attitude flip controller.\n"
            "Propose ONE hypothesis and a JSON patch (RFC6902 'replace' ops only) to the incumbent config.\n"
            "Allowed paths: /ctrl/family (schedule|pd|hybrid), /ctrl/allocation (saturated|bangbang), /ctrl/pd/kd_enabled, "
            "/ctrl/train_samples (0..32), /ctrl/cma_popsize (4..48), /ctrl/cma_sigma0, /hw/ctrl_hi, /hw/extra_pair_arm.\n"
            "Do not invent numeric results. Reply with JSON only: {\"hypothesis\": str, \"patch\": [..]}.\n"
            f"Incumbent config: {json.dumps(inc.config['ctrl'])} hw={json.dumps(inc.config['hw'])} value={inc.value}\n"
            f"Ledger tail: {json.dumps(tail)}"
        )

    def propose(self, ledger: Ledger, incumbent) -> Optional[Proposal]:
        import urllib.request
        prompt = self._prompt(ledger, incumbent)
        if self.anthropic:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps({"model": self.model, "max_tokens": 600, "messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"x-api-key": self.anthropic, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            )
            text = json.load(urllib.request.urlopen(req, timeout=60))["content"][0]["text"]
        else:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"authorization": f"Bearer {self.openai}", "content-type": "application/json"},
            )
            text = json.load(urllib.request.urlopen(req, timeout=60))["choices"][0]["message"]["content"]
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return Proposal(str(obj["hypothesis"]), list(obj["patch"]))


def maybe_llm_proposer() -> Optional[LLMProposer]:
    import os
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return LLMProposer()
    return None


def run_attitude(ledger: Ledger, verbose: bool = True) -> dict:
    """Phase 1: autonomous (no approvals). Phase 2: a human approves the hardware class and the gated hardware
    proposals are re-run from the phase-1 incumbent. Everything goes into the same ledger."""
    ev = AttitudeEvaluator()
    r1 = run_loop("att", BASELINE, ev, RuleProposer(), ledger, max_experiments=40, base_seed=1, approvals={}, verbose=verbose)
    hw_hyps = [(h, p, a) for (h, p, a) in DEFAULT_HYPOTHESES if p[0]["path"].startswith("/hw")]
    # Phase 2 uses a distinct id prefix; the baseline is re-run with the incumbent's seed (same value => chain is self-contained)
    r2 = run_loop("att-hw", r1["incumbent"].config, ev, RuleProposer(hw_hyps), ledger, max_experiments=10, base_seed=2,
                  approvals={"approval:hardware": "human:demo-reviewer"}, verbose=verbose, baseline_seed=r1["incumbent"].seed)
    return {"phase1": r1["incumbent"], "phase2": r2["incumbent"]}


def run_attitude_llm(ledger: Ledger, start, steps: int = 3, verbose: bool = True):
    """Optional (UNTESTED here): continue from `start` with the LLM proposer. Returns None if no API key."""
    p = maybe_llm_proposer()
    if p is None:
        return None
    return run_loop("att-llm", start.config, AttitudeEvaluator(), p, ledger, max_experiments=steps, base_seed=3,
                    verbose=verbose, baseline_seed=start.seed)["incumbent"]
