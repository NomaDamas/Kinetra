"""Generic autoresearch loop (Karpathy-style): propose change -> fixed-budget experiment ->
compare ONE scalar metric against the incumbent -> keep/discard -> append to ledger.

Roles
-----
Proposer   : (LLM or rules) proposes a hypothesis + JSON patch to the incumbent config. Never produces numbers.
Evaluator  : fixed contract. Runs a deterministic, fixed-budget experiment, returns ONE scalar + details.
Ledger     : append-only JSONL, hash-chained. Every experiment is logged, including discards/crashes/gated.
Gate       : patch paths are classified; physical-assumption/hardware patches need human approval,
             evaluator-contract paths (/budget, /eval, /metric) can never be patched by the loop.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from article import versions

# ---------------------------------------------------------------- JSON patch (RFC6902 subset: add/replace)


def _walk(doc: Any, parts: list[str]):
    for p in parts:
        doc = doc[int(p)] if isinstance(doc, list) else doc[p]
    return doc


def apply_patch(config: dict, patch: list[dict]) -> dict:
    out = copy.deepcopy(config)
    for op in patch:
        if op["op"] not in ("add", "replace"):
            raise ValueError(f"unsupported op {op['op']}")
        parts = [p for p in op["path"].split("/") if p]
        parent = _walk(out, parts[:-1])
        key = parts[-1]
        if isinstance(parent, list):
            if key == "-":
                parent.append(copy.deepcopy(op["value"]))
            else:
                parent[int(key)] = copy.deepcopy(op["value"])
        else:
            if op["op"] == "replace" and key not in parent:
                raise KeyError(f"replace on missing path {op['path']}")
            parent[key] = copy.deepcopy(op["value"])
    return out


# ---------------------------------------------------------------- gates

# first matching prefix wins
GATE_RULES: list[tuple[str, str]] = [
    ("/budget", "forbidden"),        # evaluator contract: budget is fixed by the harness, not by the proposer
    ("/eval", "forbidden"),          # evaluator contract: success definition, MC seed, n samples
    ("/metric", "forbidden"),
    ("/disturbance", "approval:physical_assumption"),
    ("/assumptions", "approval:physical_assumption"),
    ("/hw", "approval:hardware"),
    ("/ctrl", "auto"),
    ("/fit", "auto"),
    ("/excitation", "auto"),
]


def gate_of(patch: list[dict]) -> str:
    """Strictest gate over all ops: forbidden > approval:* > auto."""
    gates = []
    for op in patch:
        for prefix, g in GATE_RULES:
            if op["path"].startswith(prefix):
                gates.append(g)
                break
        else:
            gates.append("forbidden")  # unknown path: refuse
    if "forbidden" in gates:
        return "forbidden"
    appr = sorted({g for g in gates if g.startswith("approval:")})
    return appr[0] if appr else "auto"


# ---------------------------------------------------------------- data


@dataclass
class Experiment:
    id: str
    parent_id: Optional[str]
    hypothesis: str
    change: list
    budget: dict
    metric: str
    value: Optional[float]
    incumbent_value: Optional[float]
    decision: str  # keep | discard | crash | gated
    seed: int
    versions: dict
    config: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    gate: str = "auto"
    approved_by: Optional[str] = None
    proposer: str = ""
    wall_s: float = 0.0
    ts: float = 0.0
    prev_hash: str = ""
    entry_hash: str = ""


@dataclass
class Proposal:
    hypothesis: str
    patch: list


class Proposer:
    name = "base"

    def propose(self, ledger: "Ledger", incumbent: Experiment) -> Optional[Proposal]:  # None => stop
        raise NotImplementedError


@dataclass
class EvalResult:
    value: float
    details: dict
    budget_used: dict


class Evaluator:
    metric = "metric"
    direction = "max"  # or "min"
    min_delta = 0.0
    budget: dict = {}

    def validate(self, config: dict) -> None:
        pass

    def evaluate(self, config: dict, seed: int) -> EvalResult:
        raise NotImplementedError


class Ledger:
    def __init__(self, path: str, reset: bool = False):
        self.path = path
        if reset and os.path.exists(path):
            os.remove(path)
        self.entries: list[Experiment] = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    if line.strip():
                        self.entries.append(Experiment(**json.loads(line)))

    def append(self, e: Experiment) -> None:
        e.prev_hash = self.entries[-1].entry_hash if self.entries else ""
        body = json.dumps({k: v for k, v in asdict(e).items() if k != "entry_hash"}, sort_keys=True, default=_jd)
        e.entry_hash = hashlib.sha256(body.encode()).hexdigest()[:16]
        with open(self.path, "a") as f:  # append-only
            f.write(json.dumps(asdict(e), sort_keys=True, default=_jd) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.entries.append(e)

    def tail(self, n: int = 8) -> list[Experiment]:
        return self.entries[-n:]

    def verify_chain(self) -> bool:
        prev = ""
        for e in self.entries:
            body = json.dumps({k: v for k, v in asdict(e).items() if k != "entry_hash"}, sort_keys=True, default=_jd)
            if e.prev_hash != prev or hashlib.sha256(body.encode()).hexdigest()[:16] != e.entry_hash:
                return False
            prev = e.entry_hash
        return True


def _jd(o):
    import numpy as np
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(type(o))


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=_jd).encode()).hexdigest()[:10]


def _better(evaluator: Evaluator, new: float, old: float) -> bool:
    if evaluator.direction == "max":
        return new > old + evaluator.min_delta
    return new < old - evaluator.min_delta


def run_loop(
    name: str,
    baseline: dict,
    evaluator: Evaluator,
    proposer: Proposer,
    ledger: Ledger,
    max_experiments: int,
    base_seed: int = 0,
    approvals: Optional[dict] = None,
    verbose: bool = True,
    baseline_seed: Optional[int] = None,
) -> dict:
    """approvals: {gate_class: approver_id}. A gated patch whose class is absent is logged as 'gated' and NOT run."""
    approvals = approvals or {}
    ver = versions()
    prefix = name
    idx = 0

    def new_id() -> str:
        nonlocal idx
        eid = f"{prefix}-{idx:03d}"
        idx += 1
        return eid

    def run_one(parent: Optional[Experiment], hypothesis: str, patch: list, cfg: dict, gate: str, approver: Optional[str], seed: int, proposer_name: str) -> Experiment:
        t0 = time.time()
        e = Experiment(
            id=new_id(), parent_id=parent.id if parent else None, hypothesis=hypothesis, change=patch,
            budget=dict(evaluator.budget), metric=evaluator.metric, value=None,
            incumbent_value=parent.value if parent is not None else None, decision="crash", seed=seed,
            versions=ver, config=cfg, gate=gate, approved_by=approver, proposer=proposer_name, ts=time.time(),
        )
        try:
            evaluator.validate(cfg)
            r = evaluator.evaluate(cfg, seed)
            e.value, e.details = float(r.value), r.details
            e.details["budget_used"] = r.budget_used
        except Exception as ex:  # crash is a legitimate, logged outcome
            e.decision = "crash"
            e.details = {"error": repr(ex), "trace": traceback.format_exc()[-600:]}
        e.wall_s = time.time() - t0
        return e

    incumbent = run_one(None, "baseline", [], baseline, "auto", None, base_seed * 1000 if baseline_seed is None else baseline_seed, "baseline")
    incumbent.decision = "keep" if incumbent.value is not None else "crash"
    ledger.append(incumbent)
    if incumbent.value is None:
        raise RuntimeError("baseline crashed: " + incumbent.details.get("error", ""))
    if verbose:
        print(f"[{name}] {incumbent.id} baseline {evaluator.metric}={incumbent.value:.4f}  ({incumbent.wall_s:.1f}s)", flush=True)

    for _ in range(max_experiments):
        prop = proposer.propose(ledger, incumbent)
        if prop is None:
            break
        gate = gate_of(prop.patch)
        seed = base_seed * 1000 + idx
        if gate == "forbidden" or (gate.startswith("approval:") and gate not in approvals):
            e = Experiment(
                id=new_id(), parent_id=incumbent.id, hypothesis=prop.hypothesis, change=prop.patch,
                budget=dict(evaluator.budget), metric=evaluator.metric, value=None, incumbent_value=incumbent.value,
                decision="gated", seed=seed, versions=ver, config=incumbent.config,
                details={"reason": "forbidden path (evaluator contract)" if gate == "forbidden" else f"awaiting human approval for {gate}"},
                gate=gate, proposer=proposer.name, ts=time.time(),
            )
            ledger.append(e)
            if verbose:
                print(f"[{name}] {e.id} GATED({gate}) {prop.hypothesis}", flush=True)
            continue
        try:
            cand_cfg = apply_patch(incumbent.config, prop.patch)
        except Exception as ex:
            e = Experiment(
                id=new_id(), parent_id=incumbent.id, hypothesis=prop.hypothesis, change=prop.patch,
                budget=dict(evaluator.budget), metric=evaluator.metric, value=None, incumbent_value=incumbent.value,
                decision="crash", seed=seed, versions=ver, config=incumbent.config, details={"error": f"bad patch: {ex!r}"},
                gate=gate, proposer=proposer.name, ts=time.time(),
            )
            ledger.append(e)
            continue
        e = run_one(incumbent, prop.hypothesis, prop.patch, cand_cfg, gate, approvals.get(gate), seed, proposer.name)
        if e.value is not None and _better(evaluator, e.value, incumbent.value):
            e.decision = "keep"
        elif e.value is not None:
            e.decision = "discard"
        ledger.append(e)
        if verbose:
            v = "None" if e.value is None else f"{e.value:.4f}"
            print(f"[{name}] {e.id} {e.decision.upper():7s} {evaluator.metric}={v} vs inc {incumbent.value:.4f}  ({e.wall_s:.1f}s)  {prop.hypothesis}", flush=True)
        if e.decision == "keep":
            incumbent = e
    return {"incumbent": incumbent, "n": len(ledger.entries)}
