"""Proposals of the agent (G-03a): a request in words becomes a validated command batch that is *not* applied, retried on refusal.

    proposer = Proposer(gateway)                               # the G-01 gateway: key, budget and cost ledger are its business
    result = proposer.propose("car", project, "put a wheel on the plate")
    result.status        # "proposed" | "declined" | "retries_exhausted" | "budget_exceeded" | "gateway_error"
    result.proposal      # when proposed: the `CommandBatch`, the calls it came from and the project it would make (a preview)
    result.attempts      # every model reply with the reasons it was refused for (empty for the accepted one)

Rules (the issue's DoD; read by G-03b ghost preview, G-03c accept/reject, G-06 evaluation set, G-07 agent bar):

- **The output is a proposal, never an edit.** The model answers with an ordered list of edit-tool calls (G-02a, `edit_tools.py`).
  Each call is built by `EditTools.run` on the project the calls before it left, and the edits of all calls are joined, in order,
  into one flat `CommandBatch` that `validate_command` (C-02c) then checks once against the input project: all or nothing, like a
  batch from any client. `propose` is a function of the project it is given: nothing is published, no document or history changes.
  Accepting (publishing `proposal.command` through `Hub.publish`) is G-03c's and is never done here (no auto-accept).
- **A refusal goes back to the model with its reasons, within a fixed number of attempts.** A reply that is not the JSON object
  asked for, a call a tool refuses (schema, unknown id) or a batch the validator refuses (overlap, floating part, invalid snap, ...)
  is a refused attempt. The reasons are the validator's `Reason`s (code, sentence, typed refs) with `calls[n] (tool): ` in front of
  the sentence, sent back in the conversation, and the model sends the whole proposal again. After `max_attempts` model replies
  (default `DEFAULT_MAX_ATTEMPTS`), the result is `retries_exhausted` with the last reasons and every attempt: a failure report,
  not a partial proposal. Calls before the refused one are not kept: a proposal is whole or nothing.
- **Declining is an answer.** A reply with no calls and a `message` (the request cannot be done with these tools, or must not be)
  is `declined` and is not retried.
- **The model's text is an explanation, never a verdict** (V1: verdicts come only from simulation and Monte Carlo). The `message`
  of a reply becomes an `Explanation`. The guarantee is structural: every explanation a client gets (`to_json`) carries
  `is_verdict: false` and the fixed `label` `EXPLANATION_LABEL`, whatever the text says. On top of that, a best-effort word filter
  takes out sentences that read like a verdict (a percentage or probability, the words verdict/판정 or guarantee/보장, an outcome
  word such as 성공/통과/실패/succeed/pass/fail next to a number, a claim that the design can or will do something or is strong or
  stable enough) before anything is shown, and `VERDICT_NOTICE` is shown in their place. Word lists are never complete, so the label
  does not depend on the filter; and the filter also takes out innocent sentences that use those words, it never adds one back.
- **Money stops the loop.** Every attempt is one `Gateway.chat` call on the project's budget. `BudgetExceeded` ends it as
  `budget_exceeded`, any other gateway error as `gateway_error` (the gateway's own, already redacted, text), with the attempts made.
- The gateway sends chat text only (`Gateway.chat` has no `tools` field and `Reply` has no `tool_calls`), so the tool specs
  (`specs()`, the same OpenAI function-tool objects) go in the system message and the model answers with a JSON object
  `{"calls": [{"tool": ..., "arguments": {...}}], "message": ...}`. A surrounding Markdown code fence is removed; anything else
  that is not exactly that object is refused with `invalid_command`, including JSON nested deeper than `MAX_REPLY_DEPTH` (a scan
  before parsing, so the answer does not depend on the platform's recursion limit).
- The prompt says what the tools already enforce (`edit_tools.py`): positions are snap points, numbers in a call are the user's
  (`declared`, with the user's words as `source`), no verdict, no planet constant, no catalog change. The prompt is not the guard;
  the schemas and the validator are.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kinetra_core import Command, CommandBatch, CommandRejected, PartDef, Project, Reason, ReasonCode, load_material_catalog, validate_command

from ..gateway import BudgetExceeded, Gateway, GatewayError, LedgerWriteError
from .edit_tools import EditTools, load_library, specs
from .guard import OutOfCatalog

DEFAULT_MAX_ATTEMPTS = 3
"""Model replies per proposal: the first and two retries. A design choice of this module (no source), each reply costs one gateway
call; callers pass `max_attempts` to change it."""

Status = Literal["proposed", "declined", "retries_exhausted", "budget_exceeded", "gateway_error"]

EXPLANATION_LABEL = "에이전트 설명이며 판정이 아닙니다. 판정은 실행 뒤 시뮬로만 나옵니다"
"""Shown with every agent explanation, always (not only when the filter removed something)."""

VERDICT_NOTICE = "판정은 실행 뒤 시뮬로만 나옵니다"
"""Shown in place of the sentences of the model's explanation that read like a verdict."""

_CLAIM_WORDS = re.compile(
    r"\d\s*%|퍼센트|percent|likel(?:y|ihood)"
    r"|(?:성공|통과|작동)(?:합니다|할 것|한다|해요|할 겁니다|됩니다)|버팁니다|견딥니다|버틸 것|견딜 것|보장합니다"
    # a probability given a value or a size, even beside a refusal ("확률은 높지만", "probability is 0.9")
    r"|(?:확률|probability|chances?|odds)\s*(?:[이은는도가]|is|are|of)?\s*(?:높|낮|크|큽|커|클|작|적|희박|거의|\d|high|low|good|slim|about|around)"
    r"|(?:high|low|good|slim)\s+(?:probability|chances?|odds)"
    # capability and success claims about the design, without numbers
    r"|(?:오를|올라갈|견딜|버틸|날|뛸|착지할|달릴|넘을|건널|지탱할|해낼|성공할|통과할|작동할|움직일|굴러갈|들어 올릴|이길|살아남을)\s*수\s*있"
    r"|충분|튼튼|견고|안정적|문제\s?없|잘 됩니다|될 것|될 겁니다|견뎌|버텨|(?<!불)가능합니다|(?<!불)가능할 것"
    r"|\b(?:can|could|will|would|should|is able to|are able to|able to)\s+(?:definitely |surely |certainly |easily )?"
    r"(?:climb|hold|survive|carry|lift|fly|jump|land|work|succeed|pass|withstand|support|handle|reach|drive|roll|stay|stand|balance|make it|win)\b"
    r"|\b(?:strong|sturdy|stable|light|fast|powerful|safe|stiff|rigid)\s+enough\b|\benough to\b|\bsufficient(?:ly)?\b"
    r"|\bwithout (?:any )?problems?\b|\bno problem\b",
    re.IGNORECASE,
)
"""Verdict claims: a sentence with one of these is removed, whatever else it says."""
_TOPIC_WORDS = re.compile(r"확률|probab|\bchances?\b|\bodds\b|판정|verdict|보장|guarantee", re.IGNORECASE)
"""Words of a verdict: removed unless their clause refuses to give one (`_REFUSAL`) or defers it to simulation (`_DEFERRAL`)."""
_REFUSAL = re.compile(
    r"(?:판정|보장|산출|계산|추정|예측|기록|표시|약속|단정|확인|제공|선언|평가|부여|결정|답변|말씀)(?:을|를|은|는|이|가|도)?\s*"
    r"(?:(?:할|해\s?드릴|하여 드릴|내릴|드릴)\s*수\s*(?:는|가|도)?\s*없|(?:하|내리)지\s*(?:않|못)|(?:(?:하|내리|드리)는 것은\s*)?불가능)"
    r"|(?:말할|말씀드릴|알|내릴|매길|정할)\s*수\s*(?:는|가|도)?\s*없"
    r"|\b(?:cannot|can't|can not|could not|couldn't|won't|will not|do not|don't|am not able to|unable to|not able to|not allowed to)\s+"
    r"(?:\w+\s+){0,2}?(?:guarantee|give|provide|state|say|promise|predict|estimate|compute|calculate|record|mark|issue|declare|decide|determine|judge|assign|tell|claim)\b",
    re.IGNORECASE,
)
_DEFERRAL = re.compile(r"(?=.*(?:시뮬|몬테\s?카를로|simulation|monte carlo))(?=.*(?:로만|으로만|만으로|통해서만|에서만|뒤에만|후에만|\bonly\b))", re.IGNORECASE)
_CLAUSE_END = re.compile(r"[,;:]|지만|그러나|하지만|다만|는데|고\s|\b(?:but|however|although|though|while|yet)\b", re.IGNORECASE)
_OUTCOME_WORDS = re.compile(r"성공|통과|실패|succe|\bpass|\bfail", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n+")


def _verdict_like(sentence: str) -> bool:
    """A claim anywhere, an outcome word with a number, or a verdict word in a clause that neither refuses nor defers the verdict.
    Splitting into more clauses only removes more: each clause with a verdict word must refuse or defer on its own."""
    if _CLAIM_WORDS.search(sentence) or (_OUTCOME_WORDS.search(sentence) and re.search(r"\d", sentence)):
        return True
    return any(
        _TOPIC_WORDS.search(clause) and not (_REFUSAL.search(clause) or _DEFERRAL.match(clause)) for clause in _CLAUSE_END.split(sentence)
    )



MAX_REPLY_DEPTH = 64
"""Deepest `[`/`{` nesting a reply may have. A design choice (no source): the deepest valid reply is 6 levels
(reply → calls → call → arguments → place → target), so 64 refuses only junk, and it is checked by a scan before `json.loads` so the
answer does not depend on the platform's recursion or stack limits."""
_TOO_DEEP = 'the reply is nested too deeply to read; send one flat JSON object {"calls": [...], "message": "..."}'

SYSTEM_PROMPT = """You turn a user's request about a Kinetra project into a proposal: an ordered list of edit-tool calls.
Nothing you send is applied. The user previews the proposal and accepts or rejects it.

Reply with exactly one JSON object and nothing else:
{"calls": [{"tool": "<tool name>", "arguments": {...}}, ...], "message": "<short explanation of the edit for the user>"}

- The calls run in order, each on the project as the calls before it left it. Together they are validated as one batch:
  all of them or none.
- Place a part only by snap points (add_part with place snap_to, connect) or on the ground (on_ground). No tool takes a pose.
- Numbers in the arguments are recorded as declared by the user. Use the numbers the user gave, or leave a parameter out so the
  part keeps its default. Put the user's words that justify a number in the call's "source".
- You do not say whether the design will work: verdicts come only from simulation and Monte Carlo. "message" explains the edit;
  it never gives a probability, a percentage or a verdict (such sentences are removed). You cannot change planet constants or
  the material catalog.
- If the request cannot or must not be done with these tools, reply {"calls": [], "message": "<why>"}.
- If your proposal is refused you get the validator's reasons. Fix the proposal and send it again whole.

Tools (OpenAI function-tool objects; "arguments" must match "parameters"):
{tools}

Parts of the library (ids for add_part, with their snap points and parameters in SI units):
{library}

Materials of the catalog (ids for add_part and set_material):
{materials}"""


# --- what the model must send ------------------------------------------------------------------------------------


class _Call(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: str
    arguments: dict[str, Any]


class _Reply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    calls: list[_Call]
    message: str = Field(default="", max_length=2000)


# --- results -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedCall:
    """One call of a proposal and what the edit tool made of it. `out_of_catalog` (G-04) is what the call brings in beyond the
    catalogs; accepting (G-03c) must show those labels and get the user's confirmation, as `HubEditTools.call` does."""

    tool: str
    arguments: Mapping[str, Any]
    summary: str
    command: Command
    effects: Mapping[str, Any] = field(default_factory=dict)
    out_of_catalog: tuple[OutOfCatalog, ...] = ()


@dataclass(frozen=True)
class Explanation:
    """The model's note to the user: an explanation of the proposal (or of declining), never a verdict. `text` is what may be shown,
    always with `EXPLANATION_LABEL`; `removed` are the sentences the best-effort filter found verdict-like, taken out (kept for
    evaluation, G-06, not for display)."""

    text: str
    removed: tuple[str, ...] = ()

    @classmethod
    def of(cls, message: str) -> Explanation:
        kept: list[str] = []
        removed: list[str] = []
        for sentence in (s.strip() for s in _SENTENCE_END.split(message)):
            if not sentence:
                continue
            verdict_like = _verdict_like(sentence)
            (removed if verdict_like else kept).append(sentence)
        return cls(" ".join(kept), tuple(removed))

    @property
    def notice(self) -> str:
        return VERDICT_NOTICE if self.removed else ""

    def to_json(self) -> dict:
        out: dict[str, Any] = {"by": "agent", "is_verdict": False, "label": EXPLANATION_LABEL, "text": self.text}
        if self.removed:
            out["notice"] = self.notice
            out["verdict_like_removed"] = len(self.removed)
        return out


@dataclass(frozen=True)
class Proposal:
    """A validated, unapplied change. `command` is one flat `CommandBatch` (the edits of `calls` in order); `project` is what
    `validate_command(base, command)` returned: the preview of the change, not the document."""

    request: str
    calls: tuple[ProposedCall, ...]
    command: CommandBatch
    project: Project
    explanation: Explanation = Explanation("")


@dataclass(frozen=True)
class Attempt:
    """One model reply. `reasons` is empty for the accepted (or declining) reply; `refused_call` is the index of the call that was
    refused, `None` when the reply itself or the batch as a whole was."""

    number: int
    reply: str
    reasons: tuple[Reason, ...] = ()
    refused_call: int | None = None


@dataclass(frozen=True)
class ProposalResult:
    """`message` is this module's own sentence (why it stopped); what the model said is `explanation`."""

    status: Status
    attempts: tuple[Attempt, ...]
    proposal: Proposal | None = None
    message: str = ""
    reasons: tuple[Reason, ...] = ()
    explanation: Explanation | None = None

    @property
    def ok(self) -> bool:
        return self.status == "proposed"

    def to_json(self) -> dict:
        """What a client shows: the outcome, the calls in words, and on failure the last reasons and every attempt's."""
        out: dict[str, Any] = {"status": self.status, "attempts": len(self.attempts)}
        if self.message:
            out["message"] = self.message
        if self.explanation is not None:
            out["explanation"] = self.explanation.to_json()
        if self.proposal is not None:
            out["calls"] = [
                {
                    "tool": c.tool,
                    "summary": c.summary,
                    **({"effects": dict(c.effects)} if c.effects else {}),
                    **({"out_of_catalog": [f.to_json() for f in c.out_of_catalog]} if c.out_of_catalog else {}),
                }
                for c in self.proposal.calls
            ]
        if self.reasons:
            out["reasons"] = [r.model_dump(mode="json") for r in self.reasons]
        if not self.ok and any(a.reasons for a in self.attempts):
            out["refusals"] = [
                {"attempt": a.number, "refused_call": a.refused_call, "reasons": [r.model_dump(mode="json") for r in a.reasons]}
                for a in self.attempts
                if a.reasons
            ]
        return out


class _Refused(Exception):
    def __init__(self, reasons: tuple[Reason, ...], call: int | None = None):
        super().__init__(reasons)
        self.reasons, self.call = reasons, call


def _invalid(message: str) -> _Refused:
    return _Refused((Reason(code=ReasonCode.INVALID_COMMAND, message=message),))


def _prefixed(prefix: str, reasons: Sequence[Reason]) -> tuple[Reason, ...]:
    return tuple(r.model_copy(update={"message": f"{prefix}: {r.message}"}) for r in reasons)


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```") and t.endswith("```") and len(t) >= 6:
        t = t[3:-3]
        first, _, rest = t.partition("\n")
        t = rest if first.strip() in ("", "json") else t
    return t.strip()


def _too_deep(text: str, limit: int = MAX_REPLY_DEPTH) -> bool:
    """Whether the JSON-ish `text` nests `[`/`{` deeper than `limit`, brackets inside strings not counted. Iterative, no recursion."""
    depth, in_string, escaped = 0, False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def _library_summary(library: Mapping[str, PartDef]) -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            **({"role": str(p.role)} if p.role is not None else {}),
            "snap_points": [{"id": s.id, "kind": s.kind, **({"accepts": list(s.accepts)} if s.accepts else {})} for s in p.snap_points],
            "parameters": [{"name": d.name, "unit": str(d.unit), "default": d.default.value, "min": d.min.value, "max": d.max.value} for d in p.parameters],
        }
        for p in sorted(library.values(), key=lambda p: p.id)
    ]


# --- the proposer ------------------------------------------------------------------------------------------------


class Proposer:
    """Asks the model for a proposal through the gateway and checks it with the edit tools and the validator."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        library: Mapping[str, PartDef] | None = None,
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        model: str | None = None,
        max_tokens: int | None = None,
    ):
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be an int >= 1")
        library = dict(load_library() if library is None else library)
        self._gateway = gateway
        self._tools = EditTools(library=library, clock=clock)
        self._max_attempts = max_attempts
        self._model = model
        self._max_tokens = max_tokens
        materials = sorted(e.material.id for e in load_material_catalog().entries)
        self._system = (
            SYSTEM_PROMPT.replace("{tools}", json.dumps(specs(), ensure_ascii=False))
            .replace("{library}", json.dumps(_library_summary(library), ensure_ascii=False))
            .replace("{materials}", json.dumps(materials))
        )

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def messages(self, project: Project, request: str) -> list[dict[str, str]]:
        """The opening conversation: the rules with the tools, then the project and the request."""
        return [
            {"role": "system", "content": self._system},
            {"role": "user", "content": f"Project (JSON):\n{project.model_dump_json(exclude_defaults=True)}\n\nRequest:\n{request}"},
        ]

    def propose(self, project_id: str, project: Project, request: str) -> ProposalResult:
        """Ask, check, and on refusal send the reasons back, up to `max_attempts` replies. Never applies anything."""
        conversation = self.messages(project, request)
        attempts: list[Attempt] = []
        for number in range(1, self._max_attempts + 1):
            try:
                text = self._gateway.chat(project_id, conversation, model=self._model, max_tokens=self._max_tokens).text
            except LedgerWriteError as e:
                if e.reply is None:
                    return ProposalResult("gateway_error", tuple(attempts), message=str(e))
                text = e.reply.text  # charged and answered; the gateway is closed for the next call
            except BudgetExceeded as e:
                return ProposalResult("budget_exceeded", tuple(attempts), message=str(e))
            except GatewayError as e:
                return ProposalResult("gateway_error", tuple(attempts), message=str(e))
            try:
                reply = self._parse(text)
                if not reply.calls:
                    attempts.append(Attempt(number, text))
                    return ProposalResult("declined", tuple(attempts), message="the agent declined; nothing was changed", explanation=Explanation.of(reply.message))
                proposal = self._check(project, request, reply)
            except _Refused as refused:
                attempts.append(Attempt(number, text, refused.reasons, refused.call))
                left = self._max_attempts - number
                conversation = [*conversation, {"role": "assistant", "content": text}, {"role": "user", "content": self._feedback(refused, left)}]
                continue
            attempts.append(Attempt(number, text))
            return ProposalResult("proposed", tuple(attempts), proposal=proposal, explanation=proposal.explanation)
        last = attempts[-1]
        return ProposalResult(
            "retries_exhausted",
            tuple(attempts),
            message=f"no valid proposal after {len(attempts)} attempts; nothing was changed",
            reasons=last.reasons,
        )

    # --- internals

    @staticmethod
    def _parse(text: str) -> _Reply:
        body = _strip_fence(text)
        if _too_deep(body):
            raise _invalid(_TOO_DEEP)
        try:
            raw = json.loads(body)
        except ValueError as e:
            raise _invalid(f"the reply is not JSON ({e}); send one JSON object {{\"calls\": [...], \"message\": \"...\"}}") from None
        except RecursionError:  # fallback; the scan above refuses what could get here
            raise _invalid(_TOO_DEEP) from None
        try:
            reply = _Reply.model_validate(raw)
        except RecursionError:
            raise _invalid(_TOO_DEEP) from None
        except ValidationError as e:
            raise _Refused(
                tuple(
                    Reason(code=ReasonCode.INVALID_COMMAND, message=f"the reply is not the object asked for: {'.'.join(str(p) for p in err['loc']) or 'reply'}: {err['msg']}")
                    for err in e.errors()
                )
            ) from None
        if not reply.calls and not reply.message.strip():
            raise _invalid("the reply has no calls and no message; propose calls, or say in \"message\" why the request cannot be done")
        return reply

    def _check(self, base: Project, request: str, reply: _Reply) -> Proposal:
        current = base
        calls: list[ProposedCall] = []
        edits: list = []
        for index, call in enumerate(reply.calls):
            result = self._tools.run(current, call.tool, call.arguments)
            if not result.ok:
                raise _Refused(_prefixed(f"calls[{index}] ({call.tool})", result.reasons), index)
            assert result.command is not None and result.project is not None
            calls.append(ProposedCall(call.tool, call.arguments, result.summary, result.command, result.effects, result.out_of_catalog))
            edits.extend(result.command.commands if isinstance(result.command, CommandBatch) else (result.command,))
            current = result.project
        batch = CommandBatch(type="batch", commands=tuple(edits))
        try:
            applied = validate_command(base, batch)
        except CommandRejected as e:
            raise _Refused(_prefixed("batch", e.reasons)) from None
        return Proposal(request=request, calls=tuple(calls), command=batch, project=applied.project, explanation=Explanation.of(reply.message))

    @staticmethod
    def _feedback(refused: _Refused, left: int) -> str:
        where = f"calls[{refused.call}] was refused" if refused.call is not None else "the reply was refused"
        body = {
            "refused": True,
            "refused_call": refused.call,
            "reasons": [r.model_dump(mode="json") for r in refused.reasons],
            "attempts_left": left,
        }
        return (
            f"Your proposal was refused ({where}); nothing was applied. Fix it and send the whole proposal again as one JSON object.\n"
            f"{json.dumps(body, ensure_ascii=False)}"
        )
