"""Failure explanations of the agent (G-05): the model says why a run ended as it did, quoting only numbers of the run and the checks.

    explainer = Explainer(gateway)                                  # the G-01 gateway: key, budget and cost ledger are its business
    result = explainer.explain("car", project, query_tools, "왜 무너졌어?", run_id="run-1")
    result.status        # "explained" | "discarded" | "no_run" | "budget_exceeded" | "gateway_error"
    result.explanation   # when explained: G-03a's `Explanation` (label, verdict-like sentences removed)
    result.citations     # every number shown, with the datum it was read from

Rules (`docs/architecture/agent-explain.md`):

- **The data is what the core computed.** `evidence_of` reads, through the query tools (G-02b), the summary of one recorded run
  (`rollout_summary`: the run stream and its `run_ended`, X-02d trajectory evidence, the break and condition events) and the checks
  of the design (`statics_check`, X-03a; `mass_properties`). No run recorded: nothing to explain, the model is not asked (`no_run`).
  A check the core cannot compute is left out and named under `unavailable` with its reason code.
- **Every number of the reply must be in the data, or the reply is thrown away whole.** `check_numbers` reads each number of the
  reply text (`NUMBER`; digits inside an id such as `plate-1`, `X-02d` are part of the id) and looks for a datum it is a rounding
  of: a number of the evidence (a JSON number, or a number inside one of its strings, such as a hash), equal to it when rounded to
  as many decimals as the reply wrote, in exact decimal arithmetic. A minus sign written must be the datum's. Thousands grouping
  (`1,234.5`) is one number; digits joined by dots and commas in any other way (`1.234.567`, `2,3`) and an exponent beyond
  `MAX_EXPONENT` (`1e999`, infinity as a float) are not one value and so never cited. One number not found and the reply is
  `discarded`: nothing of it is shown, not even the sentences with only grounded numbers. Numbers of the question are not data.
- **The explanation is never a verdict (V1).** A reply that passes becomes G-03a's `Explanation`: `EXPLANATION_LABEL` and
  `is_verdict: false` always, and the verdict-like sentences taken out by its filter. The run is one preview run; the summary says
  so (`ROLLOUT_NOTICE`).
- **One gateway call per explanation.** `BudgetExceeded` is `budget_exceeded`, any other gateway error `gateway_error`.
- The model does not edit (proposing a fix is out of scope); the prompt says what the check enforces, the check is the guard.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any, Literal

from kinetra_core import Project, Reason

from ..gateway import BudgetExceeded, Gateway, GatewayError, LedgerWriteError
from .proposal import Explanation
from .query_tools import QueryTools

ExplainStatus = Literal["explained", "discarded", "no_run", "budget_exceeded", "gateway_error"]

EVIDENCE_TOOLS = ("rollout_summary", "statics_check", "mass_properties")
"""The query tools (G-02b) whose numbers an explanation may quote: the run, then the checks of the design."""

DISCARDED_NOTICE = "에이전트 설명에 실행·검사 데이터에 없는 수치가 있어 버렸습니다"
"""Shown instead of an explanation that quoted a number the data does not have."""

NUMBER = re.compile(r"(?<![A-Za-z0-9_])(?<![A-Za-z0-9_][.\-])-?(?:\d+|\.\d+)(?:[.,]\d+)*(?:[eE][-+]?\d+)?")
"""A number written in text, with every dot and comma that joins digits to it (`1,234.5`, `1.234.567`, `2,3`) and a decimal point
that starts it (`.5`, `-.25`: 0.5 and -0.25, never 5 and 25). Digits that continue an ASCII id or name (`plate-1`, `run-2`, `X-02d`,
`al6061`, `sha256`, `v.5`) are not a number; digits after Hangul or punctuation are (`틱25`, `높이-0.5`). What it reads is a value
only in one of the forms of `_PLAIN` and `_GROUPED` (`_value`)."""

_PLAIN = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?")
_GROUPED = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:[eE][-+]?\d+)?")
"""Digits grouped by thousands with commas (`1,234`, `12,345.6`; English and Korean writing): one number, read without them."""

MAX_EXPONENT = 400
"""Largest decimal exponent (`Decimal.adjusted`) of a number that is read as a value. A design choice (no source): every datum is a
finite double, between about 4.9e-324 and 1.8e308 in size, so a written number beyond 1e±400 can be no datum's rounding."""

SYSTEM_PROMPT = """You explain to a Kinetra user why a run of their design ended as it did, using only the data you are given:
the summary of one recorded run and the checks the core computed on the design.

Reply with the explanation only, as plain text (no JSON, no Markdown), a few sentences in the language of the user's question.

- Every number you write must be a number of the data, as it is or rounded, in the data's own unit (field names end in their
  unit: _m, _s, _deg, _kg; loads and thresholds carry their unit). Do not convert units, add, subtract, compare by a ratio or
  estimate. A reply with any number that is not in the data is thrown away whole.
- Say what the data shows: how the run ended, a joint that broke (tick, load, threshold), the lowest and highest point, the tilt,
  the static margin and tip-over angle. If the data does not show the cause, say so; do not guess one.
- The run is one preview run, never a verdict: verdicts come only from simulation and Monte Carlo. Do not say whether the design
  will work, give no probability or percentage, and do not use success/pass/fail words (성공, 통과, 실패) next to a number:
  such sentences are removed.
- Do not propose edits; the user decides what to change. Write ids (runs, joints, instances) exactly as they are."""


# --- the data -----------------------------------------------------------------------------------------------------


def evidence_of(tools: QueryTools, project: Project, run_id: str | None = None) -> tuple[dict[str, Any] | None, tuple[Reason, ...]]:
    """The data an explanation may quote: `rollout_summary` of `run_id` (the newest run when `None`) and the checks of `project`,
    as the query tools return them. `(None, reasons)` when there is no such run; a check the core cannot compute is left out and
    listed under `unavailable` with its reason codes."""
    run = tools.run(project, "rollout_summary", {} if run_id is None else {"run_id": run_id})
    if not run.ok:
        return None, run.reasons
    evidence: dict[str, Any] = {"rollout_summary": dict(run.data or {})}
    unavailable: dict[str, list[str]] = {}
    for tool in EVIDENCE_TOOLS[1:]:
        result = tools.run(project, tool, {})
        if result.ok:
            evidence[tool] = dict(result.data or {})
        else:
            unavailable[tool] = [r.code.value for r in result.reasons]
    if unavailable:
        evidence["unavailable"] = unavailable
    return evidence, ()


def _value(written: str) -> Decimal | None:
    """The value of a number read by `NUMBER`, exactly, or `None` when it is not one value: dots and commas that are neither a
    decimal point nor thousands grouping (`1.234.567`, `2,3`, `1,23,456`: a list, a version or another grouping, so possibly one
    number nobody can say), or an exponent beyond `MAX_EXPONENT` (`1e999`, which a float would read as infinity)."""
    if not (_PLAIN.fullmatch(written) or _GROUPED.fullmatch(written)):
        return None
    value = Decimal(written.replace(",", ""))
    return value if abs(value.adjusted()) <= MAX_EXPONENT else None


def _data(value: Any, path: str = "") -> Iterator[tuple[str, Decimal]]:
    """Every number of a JSON value, in document order: `(path, value)`, as the model reads it in the JSON text: a float is its
    shortest round-trip decimal (`repr`, what `json.dumps` writes: 0.145, not the binary 0.14499…), an int is itself, a number in a
    string (a hash, a sentence) is read by `NUMBER` when it is one value and a finite double. Booleans and non-finite numbers are not
    numbers."""
    stack: list[tuple[str, Any]] = [(path, value)]
    while stack:
        here, v = stack.pop()
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int):
            if abs(v) <= sys.float_info.max:
                yield here, Decimal(v)
        elif isinstance(v, float):
            if math.isfinite(v):
                yield here, Decimal(repr(v))
        elif isinstance(v, str):
            for m in NUMBER.finditer(v):
                d = _value(m.group())
                if d is not None and math.isfinite(float(d)):
                    yield here, d
        elif isinstance(v, Mapping):
            stack.extend(reversed([(f"{here}.{k}" if here else str(k), x) for k, x in v.items()]))
        elif isinstance(v, (list, tuple)):
            stack.extend(reversed([(f"{here}[{i}]", x) for i, x in enumerate(v)]))


def _gap(written: str, value: Decimal, datum: Decimal) -> Decimal | None:
    """How far `datum` is from `value` (the number `written`) when `written` is `datum` rounded to the digits written, else
    `None`: at most half a unit of the last digit written (`1.23` cites 1.2349 and 1.225, not 1.2351; the exponent counted, `2e3`
    is rounded to thousands), exactly, with no tolerance; a datum exactly halfway may be rounded either way. A minus sign written
    must be the datum's; an unsigned number may be the size of a negative datum (\"0.08 m 모자라다\" for a margin of -0.08 m)."""
    if written.startswith("-") and datum >= 0:
        return None
    half = Decimal(5).scaleb(value.as_tuple().exponent - 1)  # type: ignore[operator]
    gap = abs(abs(datum) - abs(value))
    return gap if gap <= half else None


@dataclass(frozen=True)
class Citation:
    """A number of the explanation as it was written, and the datum it was read from: its `path` in the evidence
    (`rollout_summary.breaks[0].load.value`) and its value."""

    text: str
    path: str
    value: float

    def to_json(self) -> dict:
        return {"text": self.text, "path": self.path, "value": self.value}


def check_numbers(text: str, evidence: Mapping[str, Any]) -> tuple[tuple[Citation, ...], tuple[str, ...]]:
    """Each number of `text` against the data: `(citations, ungrounded)`. A number is cited from the datum closest to it (the
    first in document order on a tie); a number no datum rounds to, or that is not one value (`_value`), is ungrounded."""
    data = list(_data(evidence))
    span = max((len(d.as_tuple().digits) for _, d in data), default=1)
    cited: list[Citation] = []
    ungrounded: list[str] = []
    for m in NUMBER.finditer(text):
        written = m.group()
        value = _value(written)
        best: tuple[Decimal, str, Decimal] | None = None
        if value is not None:
            with localcontext() as ctx:
                # exact: the digits of the widest datum, the value's (exponent within ±MAX_EXPONENT) and a double's (down to 1e-341)
                ctx.prec = len(written) + span + 2 * MAX_EXPONENT + 400
                for path, datum in data:
                    gap = _gap(written, value, datum)
                    if gap is not None and (best is None or gap < best[0]):
                        best = (gap, path, datum)
        if best is None:
            ungrounded.append(written)
        else:
            cited.append(Citation(written, best[1], float(best[2])))
    return tuple(cited), tuple(ungrounded)


# --- the result ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureExplanation:
    """What an explanation request came to. `message` is this module's sentence (why it stopped or what was dropped); the model's
    words are `explanation` (only when `explained`). `reply` (the model's text) and `ungrounded` (its numbers the data does not
    have) are kept for evaluation, never shown. `evidence` is the data the model was given."""

    status: ExplainStatus
    message: str = ""
    explanation: Explanation | None = None
    citations: tuple[Citation, ...] = ()
    ungrounded: tuple[str, ...] = ()
    reply: str = ""
    evidence: Mapping[str, Any] | None = None
    reasons: tuple[Reason, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "explained"

    def to_json(self) -> dict:
        """What a client shows: the labelled explanation and where each of its numbers came from, or why there is none."""
        out: dict[str, Any] = {"status": self.status}
        if self.message:
            out["message"] = self.message
        if self.evidence is not None:
            run = self.evidence["rollout_summary"]
            out["run_id"] = run["run_id"]
            out["sources"] = [k for k in EVIDENCE_TOOLS if k in self.evidence]
        if self.explanation is not None:
            out["explanation"] = self.explanation.to_json()
            out["citations"] = [c.to_json() for c in self.citations]
        if self.ungrounded:
            out["ungrounded"] = len(self.ungrounded)
        if self.reasons:
            out["reasons"] = [r.model_dump(mode="json") for r in self.reasons]
        return out


# --- the explainer ------------------------------------------------------------------------------------------------


class Explainer:
    """Asks the model, through the gateway, why a recorded run ended as it did, and keeps the answer only if every number of it
    is in the data."""

    def __init__(self, gateway: Gateway, *, model: str | None = None, max_tokens: int | None = None):
        self._gateway = gateway
        self._model = model
        self._max_tokens = max_tokens

    @staticmethod
    def messages(evidence: Mapping[str, Any], question: str) -> list[dict[str, str]]:
        """The conversation: the rules, then the question and the data."""
        data = json.dumps(evidence, ensure_ascii=False, allow_nan=False)
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question:\n{question or 'Why did this run end as it did?'}\n\nData (JSON):\n{data}"},
        ]

    def explain(self, project_id: str, project: Project, tools: QueryTools, question: str = "", *, run_id: str | None = None) -> FailureExplanation:
        """Explain run `run_id` (the newest recorded run when `None`) of `project`. Never raises for a missing run, a gateway
        error or a bad reply; the result says why there is no explanation."""
        evidence, reasons = evidence_of(tools, project, run_id)
        if evidence is None:
            return FailureExplanation("no_run", message="no recorded run to explain; the model was not asked", reasons=reasons)
        try:
            text = self._gateway.chat(project_id, self.messages(evidence, question), model=self._model, max_tokens=self._max_tokens).text
        except LedgerWriteError as e:
            if e.reply is None:
                return FailureExplanation("gateway_error", message=str(e), evidence=evidence)
            text = e.reply.text  # charged and answered: the money is spent, so the answer is checked
        except BudgetExceeded as e:
            return FailureExplanation("budget_exceeded", message=str(e), evidence=evidence)
        except GatewayError as e:
            return FailureExplanation("gateway_error", message=str(e), evidence=evidence)
        return self.check(text, evidence)

    @staticmethod
    def check(text: str, evidence: Mapping[str, Any]) -> FailureExplanation:
        """The model's `text` against `evidence`: thrown away whole if one of its numbers is not in the data, otherwise G-03a's
        labelled `Explanation` of it with the citations of the numbers left on screen."""
        reply = text.strip()
        if not reply:
            return FailureExplanation("discarded", message="the reply was empty", reply=text, evidence=evidence)
        _, ungrounded = check_numbers(reply, evidence)
        if ungrounded:
            return FailureExplanation("discarded", message=DISCARDED_NOTICE, ungrounded=ungrounded, reply=text, evidence=evidence)
        explanation = Explanation.of(reply)
        citations, _ = check_numbers(explanation.text, evidence)
        return FailureExplanation("explained", explanation=explanation, citations=citations, reply=text, evidence=evidence)
