"""LLM gateway: the only place in the core that holds the API key, enforces a per-project budget and records cost (G-01).

    gw = Gateway(default_model="openai/gpt-6.1-sol", budgets={"proj-1": Budget(max_calls=50, max_cost_usd=2.0, assumed_call_cost_usd=0.2)},
                 ledger_path=Path("out/llm-cost.jsonl"))
    reply = gw.chat("proj-1", [{"role": "user", "content": "..."}])   # BudgetExceeded when the project has no budget left

Rules:
    - The key is read once from the environment of the core process (`KEY_ENV`, the same variable the review bot uses).
      There is no constructor argument, file or request field that can carry it, and nothing returned to a caller
      (replies, `usage()`, errors, ledger lines, repr) contains it. Error text is masked with the exact key and with
      key-shaped patterns; model replies and ledger lines only with the exact key, so ordinary text is not altered.
    - A request that does not fit the project's budget is rejected before anything is sent.
    - Every request that is sent (and every rejection) adds one JSON line to the cost ledger. Message text is not stored.
      If a ledger line cannot be written the gateway closes: spend that is not on disk would be forgotten after a restart.
    - Redirects are not followed (the Authorization header must not go anywhere else).
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

from .budget import MICRO, Budget, BudgetExceeded, CostLedger, GatewayError, ProjectUsage, to_micro
from .redact import mask_exact, redact
from .transport import HttpRequest, Transport, TransportError, check_base_url, urllib_transport

KEY_ENV = "OPENROUTER_API_KEY"
BASE_URL = "https://openrouter.ai/api/v1"


class UpstreamError(GatewayError):
    """The provider answered with an error status (3xx included) or an unusable body. `status` is the HTTP status (0 = none)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class GatewayClosed(GatewayError):
    """A cost-ledger write failed earlier; the gateway refuses further requests until the process is restarted with a working ledger."""


class LedgerWriteError(GatewayClosed):
    """The request was sent and charged in memory, but its ledger line could not be written. The gateway is now closed.

    `charged_usd` is what was charged. `reply` is the model's answer when the call itself succeeded (use it, the money is spent),
    `upstream` is the provider/transport error when it did not.
    """

    def __init__(self, message: str, charged_usd: float, reply: "Reply | None" = None, upstream: GatewayError | None = None):
        super().__init__(message)
        self.charged_usd = charged_usd
        self.reply = reply
        self.upstream = upstream


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
        base_url: str = BASE_URL,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.time,
        timeout: float = 120.0,
    ):
        key = os.environ.get(KEY_ENV, "").strip()
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
        self._closed = False
        for entry in self._ledger.replay():
            if entry.get("status") == "rejected":
                continue
            u = self._usage.setdefault(str(entry.get("project")), ProjectUsage())
            micro = entry.get("charged_micro_usd")
            if isinstance(micro, bool) or not isinstance(micro, int) or micro < 0:
                raise GatewayError("cost ledger has a line without a valid charged_micro_usd; refusing to start with unknown spend")
            u.calls += 1
            u.charged_micro += micro
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
            max_micro = b.max_cost_micro if b else None
            return {
                "project": project_id,
                "calls": u.calls,
                "charged_usd": u.charged_micro / MICRO,
                "unknown_cost_calls": u.unknown_cost_calls,
                "max_calls": b.max_calls if b else None,
                "max_cost_usd": b.max_cost_usd if b else None,
                "calls_left": None if not b or b.max_calls is None else max(0, b.max_calls - u.calls - u.in_flight),
                "cost_left_usd": None if max_micro is None else max(0, max_micro - u.charged_micro - u.reserved_micro) / MICRO,
                "closed": self._closed,
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
        payload: dict = {"model": model, "messages": [dict(m) for m in messages], "usage": {"include": True}}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # Build the request before reserving budget: a payload that cannot be serialised must not leave a reservation behind.
        req = HttpRequest(
            url=f"{self._base}/chat/completions",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
            timeout=self._timeout,
        )
        self._reserve(project_id, model)
        try:
            resp = self._transport(req)
        except TransportError as e:
            charged, werr = self._settle(project_id, model, "transport_error", 0, None, None, None)
            upstream = UpstreamError(self._mask(str(e)))
            if werr:
                raise self._ledger_failure(werr, charged, upstream=upstream) from None
            raise upstream from None
        except BaseException:
            self._settle(project_id, model, "transport_error", 0, None, None, None)
            raise
        return self._finish(project_id, model, resp.status, resp.body)

    # ------------------------------------------------------------------ internals

    def _mask(self, text: str) -> str:
        return redact(text, (self._key,))

    def _reserve(self, project_id: str, model: str) -> None:
        with self._lock:
            if self._closed:
                raise GatewayClosed("gateway is closed: a cost-ledger write failed earlier")
            b = self._budgets.get(project_id)
            u = self._usage.setdefault(project_id, ProjectUsage())
            reason = None
            if b is None:
                reason = "no budget is configured for this project"
            elif b.max_calls is not None and u.calls + u.in_flight >= b.max_calls:
                reason = f"call budget used up ({u.calls}/{b.max_calls})"
            elif b.max_cost_micro is not None and u.charged_micro + u.reserved_micro + b.assumed_micro > b.max_cost_micro:
                reason = (
                    f"cost budget would be exceeded (charged ${u.charged_micro / MICRO:.4f} of ${b.max_cost_usd:.4f}, "
                    f"next call assumed ${b.assumed_micro / MICRO:.4f})"
                )
            if reason is not None:
                try:
                    self._ledger.append({"ts": self._ts(), "project": project_id, "model": model, "status": "rejected", "reason": reason, "charged_micro_usd": 0, "cost_usd": None})
                except OSError:
                    pass  # a rejection costs nothing; the caller must still learn it was rejected
                raise BudgetExceeded(f"project {project_id!r}: {reason}")
            u.in_flight += 1
            u.reserved_micro += b.assumed_micro

    def _settle(self, project_id: str, model: str, status: str, http_status: int, cost, prompt, completion) -> tuple[float, str | None]:
        """Account for one sent request. Returns (charged USD, ledger error text or None). A ledger error closes the gateway."""
        with self._lock:
            b = self._budgets[project_id]
            u = self._usage[project_id]
            u.in_flight -= 1
            u.reserved_micro -= b.assumed_micro
            charged = to_micro(cost) if cost is not None else b.assumed_micro
            u.calls += 1
            u.charged_micro += charged
            if cost is None:
                u.unknown_cost_calls += 1
            entry = {
                "ts": self._ts(), "project": project_id, "model": model, "status": status, "http_status": http_status,
                "prompt_tokens": prompt, "completion_tokens": completion, "cost_usd": cost,
                "charged_micro_usd": charged, "charged_usd": charged / MICRO,
            }  # fmt: skip
            try:
                self._ledger.append(entry)
            except OSError as e:
                self._closed = True  # the spend is counted in memory only; a restart would forget it
                return charged / MICRO, f"cost ledger write failed ({type(e).__name__}); gateway closed, charged ${charged / MICRO:.6f} is not on disk"
            return charged / MICRO, None

    @staticmethod
    def _ledger_failure(message: str, charged: float, reply: Reply | None = None, upstream: GatewayError | None = None) -> LedgerWriteError:
        return LedgerWriteError(message, charged, reply, upstream)

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
        if not 200 <= status < 300:
            charged, werr = self._settle(project_id, model, "http_error", status, cost, prompt, completion)
            err = d.get("error")
            detail = err.get("message") if isinstance(err, dict) else err
            note = " (redirects are not followed)" if 300 <= status < 400 else ""
            upstream = UpstreamError(self._mask(f"HTTP {status}{note}: {str(detail if detail else body[:200])[:300]}"), status)
            if werr:
                raise self._ledger_failure(werr, charged, upstream=upstream) from None
            raise upstream
        text = None
        choices = d.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str) and msg["content"].strip():
                text = msg["content"]
        if text is None:
            charged, werr = self._settle(project_id, model, "malformed", status, cost, prompt, completion)
            upstream = UpstreamError("response has no message content", status)
            if werr:
                raise self._ledger_failure(werr, charged, upstream=upstream) from None
            raise upstream
        charged, werr = self._settle(project_id, model, "ok", status, cost, prompt, completion)
        reply = Reply(mask_exact(text, (self._key,)), str(mask_exact(str(d.get("model") or model), (self._key,))), prompt, completion, cost, charged)
        if werr:
            raise self._ledger_failure(werr, charged, reply=reply) from None
        return reply
