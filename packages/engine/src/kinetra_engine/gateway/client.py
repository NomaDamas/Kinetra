"""LLM gateway: the only place in the core that holds the API key, enforces a per-project budget and records cost (G-01).

    gw = Gateway(default_model="openai/gpt-6.1-sol", budgets={"proj-1": Budget(max_calls=50, max_cost_usd=2.0, assumed_call_cost_usd=0.2)},
                 ledger_path=Path("out/llm-cost.jsonl"))
    reply = gw.chat("proj-1", [{"role": "user", "content": "..."}])   # BudgetExceeded when the project has no budget left

Rules (docs/plan/studio-plan.md 4.4: the agent proposes, the core decides; 5.1: the core owns secrets):
    - The key is read once from an environment variable of the core process (`KEY_ENV`, the same one the review bot
      uses). There is no constructor argument, file or request field that can carry it, and nothing returned to a
      caller (replies, `usage()`, errors, ledger lines, repr) contains it; provider text is masked with `redact`.
    - A request that does not fit the project's budget is rejected before anything is sent.
    - Every request that is sent (and every rejection) adds one JSON line to the cost ledger. Message text is not stored.
    - No retries, no model choice, no prompt logic here; callers decide.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .budget import Budget, BudgetExceeded, CostLedger, GatewayError, ProjectUsage
from .redact import redact
from .transport import HttpRequest, Transport, TransportError, check_base_url, urllib_transport

KEY_ENV = "OPENROUTER_API_KEY"
BASE_URL = "https://openrouter.ai/api/v1"


class UpstreamError(GatewayError):
    """The provider answered with an error status or an unusable body. `status` is the HTTP status (0 = no usable response)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None  # provider-reported; None when the provider did not say
    charged_usd: float  # what the budget was charged (cost_usd, or the assumed cost when unknown)


def _count(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _cost(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and f >= 0 else None


class Gateway:
    def __init__(
        self,
        *,
        default_model: str,
        budgets: Mapping[str, Budget],
        ledger_path: Path | None = None,
        env: Mapping[str, str] | None = None,
        base_url: str = BASE_URL,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.time,
        timeout: float = 120.0,
    ):
        source = os.environ if env is None else env
        key = source.get(KEY_ENV, "").strip()
        if not key:
            raise GatewayError(f"{KEY_ENV} is not set in the core process environment")
        self._key = key
        self._model = default_model
        self._base = check_base_url(base_url)
        self._transport = transport
        self._clock = clock
        self._timeout = timeout
        self._budgets = dict(budgets)
        self._ledger = CostLedger(ledger_path, (key,))
        self._lock = threading.Lock()
        self._usage: dict[str, ProjectUsage] = {}
        for entry in self._ledger.replay():
            if entry.get("status") == "rejected":
                continue
            u = self._usage.setdefault(str(entry.get("project")), ProjectUsage())
            u.calls += 1
            charged = _cost(entry.get("charged_usd"))
            if charged is None:
                raise GatewayError("cost ledger has a line without a valid charged_usd; refusing to start with unknown spend")
            u.charged_usd += charged
            if entry.get("cost_usd") is None:
                u.unknown_cost_calls += 1

    def __repr__(self) -> str:
        return f"Gateway(model={self._model!r}, base={self._base!r}, projects={sorted(self._budgets)})"

    # ------------------------------------------------------------------ public

    def usage(self, project_id: str) -> dict:
        """What a client may see: spend and what is left. Never the key."""
        with self._lock:
            b = self._budgets.get(project_id)
            u = self._usage.get(project_id, ProjectUsage())
            return {
                "project": project_id,
                "calls": u.calls,
                "charged_usd": u.charged_usd,
                "unknown_cost_calls": u.unknown_cost_calls,
                "max_calls": b.max_calls if b else None,
                "max_cost_usd": b.max_cost_usd if b else None,
                "calls_left": None if not b or b.max_calls is None else max(0, b.max_calls - u.calls - u.in_flight),
                "cost_left_usd": None if not b or b.max_cost_usd is None else max(0.0, b.max_cost_usd - u.charged_usd - u.reserved_usd),
            }

    def chat(
        self,
        project_id: str,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> Reply:
        model = model or self._model
        self._reserve(project_id, model)
        payload: dict = {"model": model, "messages": [dict(m) for m in messages], "usage": {"include": True}}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        req = HttpRequest(
            url=f"{self._base}/chat/completions",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
            timeout=self._timeout,
        )
        try:
            resp = self._transport(req)
        except TransportError as e:
            self._settle(project_id, model, "transport_error", 0, None, None, None)
            raise UpstreamError(self._mask(str(e))) from None
        except BaseException:
            self._settle(project_id, model, "transport_error", 0, None, None, None)
            raise
        return self._finish(project_id, model, resp.status, resp.body)

    # ------------------------------------------------------------------ internals

    def _mask(self, text: str) -> str:
        return redact(text, (self._key,))

    def _reserve(self, project_id: str, model: str) -> None:
        with self._lock:
            b = self._budgets.get(project_id)
            u = self._usage.setdefault(project_id, ProjectUsage())
            reason = None
            if b is None:
                reason = "no budget is configured for this project"
            elif b.max_calls is not None and u.calls + u.in_flight >= b.max_calls:
                reason = f"call budget used up ({u.calls}/{b.max_calls})"
            elif b.max_cost_usd is not None and u.charged_usd + u.reserved_usd + b.assumed_call_cost_usd > b.max_cost_usd:
                reason = f"cost budget would be exceeded (charged ${u.charged_usd:.4f} of ${b.max_cost_usd:.4f}, next call assumed ${b.assumed_call_cost_usd:.4f})"
            if reason is not None:
                try:
                    self._write({"ts": self._ts(), "project": project_id, "model": model, "status": "rejected", "reason": reason, "charged_usd": 0.0, "cost_usd": None})
                except GatewayError:
                    pass  # a rejection costs nothing; the caller must still learn it was rejected
                raise BudgetExceeded(f"project {project_id!r}: {reason}")
            u.in_flight += 1
            u.reserved_usd += b.assumed_call_cost_usd or 0.0

    def _settle(self, project_id: str, model: str, status: str, http_status: int, cost, prompt, completion) -> float:
        with self._lock:
            b = self._budgets[project_id]
            u = self._usage[project_id]
            assumed = b.assumed_call_cost_usd or 0.0
            u.in_flight -= 1
            u.reserved_usd -= assumed
            if u.in_flight == 0:
                u.reserved_usd = 0.0  # drop float residue
            charged = cost if cost is not None else assumed
            u.calls += 1
            u.charged_usd += charged
            if cost is None:
                u.unknown_cost_calls += 1
            self._write(
                {
                    "ts": self._ts(), "project": project_id, "model": model, "status": status, "http_status": http_status,
                    "prompt_tokens": prompt, "completion_tokens": completion, "cost_usd": cost, "charged_usd": charged,
                }  # fmt: skip
            )
            return charged

    def _write(self, entry: dict) -> None:
        try:
            self._ledger.append(entry)
        except OSError as e:  # the spend is already counted in memory; do not hide that it is not on disk
            raise GatewayError(f"cost ledger write failed: {type(e).__name__}") from None

    def _ts(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self._clock()))

    def _finish(self, project_id: str, model: str, status: int, body: bytes) -> Reply:
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            data = None
        d = data if isinstance(data, dict) else {}
        usage = d.get("usage") if isinstance(d.get("usage"), dict) else {}
        cost, prompt, completion = _cost(usage.get("cost")), _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
        if status >= 400:
            self._settle(project_id, model, "http_error", status, cost, prompt, completion)
            err = d.get("error")
            detail = err.get("message") if isinstance(err, dict) else err
            raise UpstreamError(self._mask(f"HTTP {status}: {str(detail if detail else body[:200])[:300]}"), status)
        text = None
        choices = d.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str) and msg["content"].strip():
                text = msg["content"]
        if text is None:
            self._settle(project_id, model, "malformed", status, cost, prompt, completion)
            raise UpstreamError("response has no message content", status)
        charged = self._settle(project_id, model, "ok", status, cost, prompt, completion)
        return Reply(self._mask(text), str(d.get("model") or model), prompt, completion, cost, charged)
