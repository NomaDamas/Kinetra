import copy
import json

import pytest

from kinetra_engine.autoresearch.ledger import (EvalResult, Evaluator, Ledger, Proposal, Proposer, apply_patch, gate_of,
                                                run_loop, verify_rows)
from kinetra_engine.autoresearch.proposers import RuleProposer, maybe_llm_proposer, rep


class Quad(Evaluator):
    """metric = -(x-3)^2, deterministic; budget fixed."""
    metric = "neg_sq"
    budget = {"n": 1}
    calls = 0

    def validate(self, c):
        assert c["budget"]["n"] == 1, "budget is fixed"

    def evaluate(self, c, seed):
        Quad.calls += 1
        return EvalResult(-((c["ctrl"]["x"] - 3.0) ** 2), {}, {"n": 1})


BASE = {"budget": {"n": 1}, "eval": {"seed": 1}, "ctrl": {"x": 0.0}, "assumptions": {"g": 1.0}}


def make_ledger(approvals=None, hyps=None):
    hyps = hyps or [
        ("x to 2", [rep("/ctrl/x", 2.0)], lambda c: True),
        ("x to 1 (worse)", [rep("/ctrl/x", 1.0)], lambda c: True),
        ("cheat: assumptions", [rep("/assumptions/g", 0.1)], lambda c: True),
        ("cheat: budget", [rep("/budget/n", 99)], lambda c: True),
        ("cheat: unknown path", [rep("/zzz", 1)], lambda c: True),
    ]
    led = Ledger()
    run_loop("t", BASE, Quad(), RuleProposer(hyps), led, 10, base_seed=1, approvals=approvals, verbose=False)
    return led


def test_hash_chain_detects_tamper():
    led = make_ledger()
    assert led.verify_chain() and len(led.entries) == 6
    rows = led.rows()
    assert verify_rows(rows)
    bad = copy.deepcopy(rows)
    bad[1]["value"] = 123.0  # edit a recorded result
    assert not verify_rows(bad)
    bad = copy.deepcopy(rows)
    del bad[2]  # drop an entry
    assert not verify_rows(bad)
    bad = copy.deepcopy(rows)
    bad[0], bad[1] = bad[1], bad[0]  # reorder
    assert not verify_rows(bad)
    led.entries[3].decision = "keep"
    assert not led.verify_chain()


def test_ledger_file_roundtrip(tmp_path):
    p = str(tmp_path / "l.jsonl")
    led = Ledger(p)
    run_loop("t", BASE, Quad(), RuleProposer([("a", [rep("/ctrl/x", 2.0)], lambda c: True)]), led, 3, verbose=False)
    again = Ledger(p)
    assert again.verify_chain() and again.head_hash == led.head_hash
    lines = open(p).read().splitlines()
    rec = json.loads(lines[1])
    rec["value"] = 0.0
    lines[1] = json.dumps(rec, sort_keys=True)
    open(p, "w").write("\n".join(lines) + "\n")
    assert not Ledger(p).verify_chain()


def test_gate_blocks_physical_assumption_without_approval():
    Quad.calls = 0
    led = make_ledger()
    by = {e.hypothesis: e for e in led.entries}
    cheat = by["cheat: assumptions"]
    assert cheat.decision == "gated" and cheat.gate == "approval:physical_assumption" and cheat.value is None
    assert by["cheat: budget"].decision == "gated" and by["cheat: budget"].gate == "forbidden"
    assert by["cheat: unknown path"].gate == "forbidden"
    # gated patches never ran the evaluator: baseline + 2 real candidates only
    assert Quad.calls == 3


def test_approval_lets_class_through_but_never_forbidden():
    led = make_ledger(approvals={"approval:physical_assumption": "human:test", "forbidden": "human:test"})
    by = {e.hypothesis: e for e in led.entries}
    ok = by["cheat: assumptions"]
    assert ok.decision in ("keep", "discard") and ok.approved_by == "human:test"
    assert by["cheat: budget"].decision == "gated"  # evaluator contract cannot be approved away


def test_gate_classes_and_prefix_boundaries():
    assert gate_of([rep("/ctrl/family", "pd")]) == "auto"
    assert gate_of([rep("/hw/ctrl_hi", 1.5)]) == "approval:hardware"
    assert gate_of([rep("/ctrl/family", "pd"), rep("/disturbance/x", 1)]) == "approval:physical_assumption"
    assert gate_of([rep("/hw/a", 1), rep("/eval/n_mc", 1)]) == "forbidden"
    assert gate_of([rep("/article", "toy10")]) == "forbidden"
    assert gate_of([rep("/ctrlx/evil", 1)]) == "forbidden"  # must not match the /ctrl prefix


def test_evaluator_contract_catches_gate_bypass_as_crash():
    class Sneaky(Proposer):
        name = "sneaky"
        n = 0

        def propose(self, ledger, inc):
            Sneaky.n += 1
            return Proposal("x", [rep("/ctrl/budget_alias", 1)]) if Sneaky.n == 1 else None

    # a patch under an auto prefix that changes a fixed value is caught by validate() -> logged crash
    base = dict(BASE, ctrl={"budget_alias": 0, "x": 0.0})

    class E2(Quad):
        def validate(self, c):
            assert c["ctrl"]["budget_alias"] == 0, "fixed"

    led = Ledger()
    run_loop("t", base, E2(), Sneaky(), led, 3, verbose=False)
    assert led.entries[1].decision == "crash" and "AssertionError" in led.entries[1].details["error"]


def test_keep_discard_and_determinism():
    a, b = make_ledger(), make_ledger()
    assert [e.decision for e in a.entries] == ["keep", "keep", "discard", "gated", "gated", "gated"]
    strip = lambda L: [(e.id, e.decision, e.value, e.change) for e in L.entries]
    assert strip(a) == strip(b)


def test_apply_patch_add_replace_and_errors():
    out = apply_patch({"a": {"l": [1]}}, [{"op": "add", "path": "/a/l/-", "value": 2}, rep("/a/l/0", 9)])
    assert out == {"a": {"l": [9, 2]}}
    with pytest.raises(KeyError):
        apply_patch({"a": 1}, [rep("/b", 1)])
    with pytest.raises(ValueError):
        apply_patch({"a": 1}, [{"op": "remove", "path": "/a"}])


def test_llm_proposer_is_off_by_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("KINETRA_LLM_PROPOSER", raising=False)
    assert maybe_llm_proposer("/x", "t") is None
