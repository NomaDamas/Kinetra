"""Autoresearch library: hash-chained ledger, patch gating, evaluator contract, proposers, attitude / calibration /
excitation tasks and verdict integration. Numbers come only from simulation; proposers supply hypotheses, never results."""
from .ledger import (Experiment, EvalResult, Evaluator, Ledger, Proposal, Proposer, GATE_RULES, apply_patch, gate_of,
                     run_loop)

__all__ = ["Experiment", "EvalResult", "Evaluator", "Ledger", "Proposal", "Proposer", "GATE_RULES", "apply_patch",
           "gate_of", "run_loop"]
