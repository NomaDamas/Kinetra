"""Proposers: rule-based (default, deterministic) and an optional LLM proposer guarded by environment variables.

A proposer supplies a hypothesis and a JSON patch. It never supplies numbers; every patch passes the same gate and
the same fixed-budget evaluator as any other.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Callable, Optional

from .ledger import Ledger, Proposal, Proposer


class RuleProposer(Proposer):
    """Walks a hand-written hypothesis list. Each entry is (hypothesis, patch, guard); `patch` may be a callable
    taking the incumbent config, and `guard(config) -> bool` skips entries that are moot for the incumbent."""
    name = "rules"

    def __init__(self, hypotheses: list):
        self.queue = list(hypotheses)

    def propose(self, ledger: Ledger, incumbent) -> Optional[Proposal]:
        while self.queue:
            hyp, patch, guard = self.queue.pop(0)
            if guard(incumbent.config):
                p = patch(incumbent.config) if callable(patch) else copy.deepcopy(patch)
                return Proposal(hyp, p)
        return None


class LLMProposer(Proposer):
    """OPTIONAL and OFF by default. Only usable when KINETRA_LLM_PROPOSER=1 AND ANTHROPIC_API_KEY or OPENAI_API_KEY
    is set. It shows the model the ledger tail and the allowed patch paths and parses one JSON patch.

    NOT exercised against a live API anywhere in this repo (no key was used): treat as untested code."""
    name = "llm"

    def __init__(self, allowed_paths: str, task_description: str, config_view: Callable[[dict], dict] = lambda c: c,
                 model: Optional[str] = None):
        if os.environ.get("KINETRA_LLM_PROPOSER") != "1":
            raise RuntimeError("LLM proposer disabled (set KINETRA_LLM_PROPOSER=1 to enable)")
        self.anthropic = os.environ.get("ANTHROPIC_API_KEY")
        self.openai = os.environ.get("OPENAI_API_KEY")
        if not (self.anthropic or self.openai):
            raise RuntimeError("no LLM API key in environment")
        self.model = model or ("claude-sonnet-4-5" if self.anthropic else "gpt-4o")
        self.allowed, self.task, self.view = allowed_paths, task_description, config_view

    def _prompt(self, ledger: Ledger, inc) -> str:
        tail = [{"id": e.id, "hypothesis": e.hypothesis, "change": e.change, "value": e.value, "decision": e.decision}
                for e in ledger.tail(8)]
        return (
            f"You are the proposer in an autoresearch loop. Task: {self.task}\n"
            "Propose ONE hypothesis and a JSON patch (RFC6902 'replace' ops only) to the incumbent config.\n"
            f"Allowed paths: {self.allowed}\n"
            "Do not invent numeric results. Reply with JSON only: {\"hypothesis\": str, \"patch\": [..]}.\n"
            f"Incumbent config: {json.dumps(self.view(inc.config))} value={inc.value}\n"
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


def maybe_llm_proposer(allowed_paths: str, task_description: str, config_view: Callable[[dict], dict] = lambda c: c) -> Optional[LLMProposer]:
    """None unless explicitly enabled and a key is present."""
    if os.environ.get("KINETRA_LLM_PROPOSER") == "1" and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        return LLMProposer(allowed_paths, task_description, config_view)
    return None


def rep(path: str, value) -> dict:
    return {"op": "replace", "path": path, "value": value}
