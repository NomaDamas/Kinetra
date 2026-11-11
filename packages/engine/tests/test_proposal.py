"""G-03a: a request becomes a validated, unapplied command batch; a refusal goes back to the model with the validator's reasons and is
retried a fixed number of times. Offline: the gateway runs on a fake transport that answers from a script (no network, no real model).

    uv run pytest packages/engine -q -k proposal
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from kinetra_core import CommandBatch, Origin, Project, Publish, ReasonCode, validate_command
from kinetra_engine.agent import DEFAULT_MAX_ATTEMPTS, EXPLANATION_LABEL, TOOL_NAMES, VERDICT_NOTICE, Explanation, Proposer
from kinetra_engine.agent.proposal import MAX_REPLY_DEPTH, _too_deep
from kinetra_engine.gateway import Budget, Gateway, HttpRequest, HttpResponse
from kinetra_engine.protocol import Hub

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
GROUND = {"type": "on_ground"}


def empty() -> Project:
    return Project.model_validate({"world": {"planet": "earth"}})


def body(content: str) -> bytes:
    return json.dumps(
        {"model": "m", "choices": [{"message": {"role": "assistant", "content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}}
    ).encode()


class Script:
    """The model: answers each request with the next scripted reply and keeps the requests it got."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(json.loads(req.body))
        reply = self.replies.pop(0)
        return HttpResponse(200, body(reply if isinstance(reply, str) else json.dumps(reply)))


@pytest.fixture(autouse=True)
def core_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)


def proposer(script: Script, max_calls: int = 10, **kw) -> Proposer:
    gw = Gateway(default_model="m", budgets={"car": Budget(max_calls=max_calls)}, transport=script)
    return Proposer(gw, clock=lambda: NOW, **kw)


def plate(x=0.0, **more):
    return {"tool": "add_part", "arguments": {"part": "plate", "place": {**GROUND, "x": x}, "material": "al6061-t6", **more}}


def beam_on(instance="plate-1"):
    snap = {"type": "snap_to", "snap_point": "bottom", "target": {"instance": instance, "snap_point": "top"}, "facing": "opposed"}
    return {"tool": "add_part", "arguments": {"part": "beam", "parameters": {"length": 0.1}, "place": snap, "material": "steel-a36", "source": "a 10 cm post"}}


def last_feedback(script: Script) -> dict:
    """The JSON the proposer sent back after a refusal (the last user message of the latest request)."""
    text = script.requests[-1]["messages"][-1]["content"]
    return json.loads(text[text.index("{") :])


# --- the output is an unapplied command batch -------------------------------------------------------------------------


def test_proposal_is_one_unapplied_command_batch_that_the_validator_accepts():
    script = Script({"calls": [plate(), beam_on()], "message": "a plate with a post"})
    base = empty()
    result = proposer(script).propose("car", base, "a plate with a 10 cm post on it")
    assert result.ok and result.status == "proposed" and len(result.attempts) == 1
    assert result.explanation == result.proposal.explanation == Explanation("a plate with a post")
    assert result.to_json()["explanation"] == {"by": "agent", "is_verdict": False, "label": EXPLANATION_LABEL, "text": "a plate with a post"}
    proposal = result.proposal
    assert isinstance(proposal.command, CommandBatch)
    assert all(c.type != "batch" for c in proposal.command.commands)  # flat: batches do not nest
    assert [c.tool for c in proposal.calls] == ["add_part", "add_part"]
    assert {i.id for i in proposal.project.design.instances} == {"plate-1", "beam-1"}
    assert validate_command(base, proposal.command).project == proposal.project  # the preview is exactly what the batch makes
    assert base == empty() and len(script.requests) == 1


def test_proposal_is_not_applied_until_someone_publishes_it():
    hub = Hub({"desk": empty()})
    doc = hub.documents["desk"]
    result = proposer(Script({"calls": [plate(), beam_on()]})).propose("car", doc.project, "a plate with a post")
    assert result.ok and doc.revision == 0 and doc.project == empty() and not doc.history.entries  # nothing reached the document
    # accepting is G-03c's: publishing the batch as one edit gives the previewed project and one undo step
    msg = Publish(type="publish", id=uuid.uuid4().hex, base_revision=doc.revision, command=result.proposal.command, origin=Origin.AGENT)
    assert hub.publish("desk", msg).reply.type == "accepted"
    assert doc.project == result.proposal.project and len(doc.history.entries) == 1


def test_proposal_prompt_carries_the_tools_the_library_and_the_request():
    script = Script({"calls": [plate()]})
    proposer(script).propose("car", empty(), "put a plate down")
    system, user = script.requests[0]["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert all(f'"name": "{name}"' in system["content"] for name in TOOL_NAMES)
    assert '"id": "plate"' in system["content"] and '"al6061-t6"' in system["content"]
    assert user["content"].endswith("put a plate down") and '"planet":"earth"' in user["content"]
    assert KEY not in json.dumps(script.requests)


# --- refused -> reasons back -> retried -> passes ----------------------------------------------------------------------


def test_proposal_refused_by_the_validator_is_retried_with_the_reasons_and_then_passes():
    script = Script(
        {"calls": [plate(), plate()]},  # the second plate on the same spot: overlap
        {"calls": [plate(), plate(x=1.0)], "message": "two plates, 1 m apart"},
    )
    result = proposer(script).propose("car", empty(), "two plates")
    assert result.ok and len(result.attempts) == 2 and len(script.requests) == 2
    first = result.attempts[0]
    assert first.refused_call == 1 and [r.code for r in first.reasons] == [ReasonCode.OVERLAP]
    assert first.reasons[0].message.startswith("calls[1] (add_part): ")
    assert {ref.id for ref in first.reasons[0].ids} == {"plate-1", "plate-2"}
    assert result.attempts[1].reasons == ()
    # what went back to the model: its own reply, then the validator's reasons as written (code, sentence, typed refs)
    retry = script.requests[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": first.reply}
    feedback = last_feedback(script)
    assert feedback["refused_call"] == 1 and feedback["attempts_left"] == DEFAULT_MAX_ATTEMPTS - 1
    assert feedback["reasons"] == [r.model_dump(mode="json") for r in first.reasons] and feedback["reasons"][0]["code"] == "overlap"
    assert {i.id for i in result.proposal.project.design.instances} == {"plate-1", "plate-2"}


@pytest.mark.parametrize(
    "bad, code",
    [
        ("I would add a plate.", ReasonCode.INVALID_COMMAND),  # not JSON
        ({"calls": [{"tool": "add_part"}]}, ReasonCode.INVALID_COMMAND),  # no arguments
        ({"calls": [plate()], "verdict": "it works"}, ReasonCode.INVALID_COMMAND),  # a field the reply does not have
        ({"calls": []}, ReasonCode.INVALID_COMMAND),  # neither calls nor a reason not to
        ({"calls": [{"tool": "set_gravity", "arguments": {"value": 3.7}}]}, ReasonCode.INVALID_COMMAND),  # no such tool
        ({"calls": [{"tool": "add_part", "arguments": {"part": "plate", "place": GROUND, "pose": [0, 0, 1]}}]}, ReasonCode.INVALID_COMMAND),
        ({"calls": [{"tool": "remove_part", "arguments": {"instance": "ghost-1"}}]}, ReasonCode.UNKNOWN_ID),
    ],
)
def test_proposal_any_refusal_is_retried_with_its_reason(bad, code):
    script = Script(bad, {"calls": [plate()]})
    result = proposer(script).propose("car", empty(), "a plate")
    assert result.ok and len(result.attempts) == 2
    assert code in [r.code for r in result.attempts[0].reasons]
    assert code.value in [r["code"] for r in last_feedback(script)["reasons"]]


def test_proposal_reply_in_a_code_fence_is_read():
    result = proposer(Script("```json\n" + json.dumps({"calls": [plate()]}) + "\n```")).propose("car", empty(), "a plate")
    assert result.ok and len(result.attempts) == 1


# --- retries exhausted: a failure report, nothing proposed ---------------------------------------------------------------


def test_proposal_gives_up_after_the_fixed_number_of_attempts_and_reports_why():
    script = Script(*[{"calls": [plate(), plate()]}] * 5)
    result = proposer(script, max_attempts=3).propose("car", empty(), "two plates")
    assert result.status == "retries_exhausted" and not result.ok and result.proposal is None
    assert len(result.attempts) == 3 and len(script.requests) == 3 and len(script.replies) == 2  # no fourth call
    assert all([r.code for r in a.reasons] == [ReasonCode.OVERLAP] for a in result.attempts)
    assert result.reasons == result.attempts[-1].reasons
    assert [m["role"] for m in script.requests[-1]["messages"]] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert last_feedback(script)["attempts_left"] == 1
    report = result.to_json()
    assert report["status"] == "retries_exhausted" and report["attempts"] == 3 and "nothing was changed" in report["message"]
    assert [x["attempt"] for x in report["refusals"]] == [1, 2, 3] and report["reasons"][0]["code"] == "overlap"
    assert "calls" not in report


def test_proposal_one_attempt_means_no_retry():
    script = Script("not json", {"calls": [plate()]})
    result = proposer(script, max_attempts=1).propose("car", empty(), "a plate")
    assert result.status == "retries_exhausted" and len(script.requests) == 1


@pytest.mark.parametrize("n", [0, -1, 1.5, True, "3"])
def test_proposal_max_attempts_must_be_a_positive_int(n):
    with pytest.raises(ValueError):
        proposer(Script(), max_attempts=n)


# --- other ends: declined, budget ----------------------------------------------------------------------------------------


def test_proposal_declined_by_the_model_is_not_retried():
    script = Script({"calls": [], "message": "The tools cannot change gravity."}, {"calls": [plate()]})
    result = proposer(script).propose("car", empty(), "make gravity 3.7")
    assert result.status == "declined" and result.proposal is None and result.explanation.text == "The tools cannot change gravity."
    assert len(script.requests) == 1


def test_proposal_stops_when_the_budget_is_used_up():
    script = Script({"calls": [plate(), plate()]}, {"calls": [plate()]})
    result = proposer(script, max_calls=1).propose("car", empty(), "two plates")
    assert result.status == "budget_exceeded" and "call budget used up" in result.message
    assert len(result.attempts) == 1 and result.attempts[0].reasons and len(script.requests) == 1


def test_proposal_reports_a_gateway_error():
    def broken(req):
        return HttpResponse(500, b'{"error": {"message": "upstream down"}}')

    gw = Gateway(default_model="m", budgets={"car": Budget(max_calls=5)}, transport=broken)
    result = Proposer(gw, clock=lambda: NOW).propose("car", empty(), "a plate")
    assert result.status == "gateway_error" and "upstream down" in result.message and result.attempts == ()


# --- the model's text is an explanation, never a verdict (V1) -------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "성공 확률 90%입니다.",
        "판정: 통과.",
        "이 차는 화성에서 점프에 성공합니다.",
        "착지 성공률은 0.9 정도입니다.",
        "The jump will work.",
        "It has a 90 % chance of landing.",
        "Probability of success is high.",
        "Verdict: pass.",
        "It should pass 3 of 4 trials.",
        "이 설계는 안전을 보장합니다.",
        # capability and success claims without numbers (review of #528)
        "이 설계는 화성 언덕을 오를 수 있습니다.",
        "충분히 튼튼합니다.",
        "this will hold.",
        "The car can climb the ramp.",
        "It is strong enough for the landing.",
        "구조가 안정적이라 문제없습니다.",
        "이 기둥은 하중을 견딜 수 있습니다.",
    ],
)
def test_proposal_verdict_like_sentences_of_the_explanation_are_removed_and_flagged(claim):
    message = f"판 위에 10 cm 기둥을 세웠습니다. {claim} 기둥 재료는 강철입니다."
    result = proposer(Script({"calls": [plate(), beam_on()], "message": message})).propose("car", empty(), "a plate with a post")
    assert result.ok
    explanation = result.proposal.explanation
    assert explanation.text == "판 위에 10 cm 기둥을 세웠습니다. 기둥 재료는 강철입니다." and explanation.removed == (claim,)
    assert explanation.notice == VERDICT_NOTICE == "판정은 실행 뒤 시뮬로만 나옵니다"
    shown = result.to_json()["explanation"]
    assert shown == {
        "by": "agent", "is_verdict": False, "label": EXPLANATION_LABEL, "text": explanation.text, "notice": VERDICT_NOTICE, "verdict_like_removed": 1
    }  # fmt: skip
    assert claim not in json.dumps(result.to_json(), ensure_ascii=False)


def test_proposal_an_explanation_without_verdict_claims_is_kept_whole_and_has_no_notice():
    message = "판 위에 기둥을 세웠습니다.\n길이는 요청대로 0.1 m입니다. 결과는 실행해 봐야 압니다."
    explanation = Explanation.of(message)
    assert explanation.removed == () and explanation.notice == ""
    assert explanation.text == "판 위에 기둥을 세웠습니다. 길이는 요청대로 0.1 m입니다. 결과는 실행해 봐야 압니다."


def test_proposal_a_declining_explanation_is_filtered_too():
    script = Script({"calls": [], "message": "이 요청은 도구로 할 수 없습니다. 어차피 성공 확률은 0%입니다."})
    result = proposer(script).propose("car", empty(), "make gravity 3.7")
    assert result.status == "declined" and result.explanation.text == "이 요청은 도구로 할 수 없습니다."
    assert result.to_json()["explanation"]["notice"] == VERDICT_NOTICE


@pytest.mark.parametrize(
    "message",
    [
        "판 위에 기둥을 세웠습니다.",  # nothing to remove
        "이 바퀴면 모래밭도 거뜬합니다.",  # a claim the word filter does not know: the label is still there
        "",
    ],
)
def test_proposal_every_explanation_carries_the_label_whatever_the_filter_does(message):
    assert EXPLANATION_LABEL == "에이전트 설명이며 판정이 아닙니다. 판정은 실행 뒤 시뮬로만 나옵니다"
    proposed = proposer(Script({"calls": [plate()], "message": message})).propose("car", empty(), "a plate").to_json()["explanation"]
    assert proposed["label"] == EXPLANATION_LABEL and proposed["is_verdict"] is False and proposed["by"] == "agent"
    if message:
        declined = proposer(Script({"calls": [], "message": message})).propose("car", empty(), "x").to_json()["explanation"]
        assert declined["label"] == EXPLANATION_LABEL and declined["is_verdict"] is False


# --- a reply too deep to read is a malformed reply, not a crash -------------------------------------------------------------


@pytest.mark.parametrize(
    "deep",
    [
        "[" * 100_000 + "]" * 100_000,
        '{"calls": [{"tool": "add_part", "arguments": {"part": ' + "[" * 100_000 + "]" * 100_000 + "}}]}",
        "[" * 65 + "]" * 65,  # one past the limit: refused by the scan, whatever the platform's recursion limit
    ],
)
def test_proposal_a_deeply_nested_reply_is_refused_and_retried(deep):
    script = Script(deep, {"calls": [plate()]})
    result = proposer(script).propose("car", empty(), "a plate")
    assert result.ok and len(result.attempts) == 2
    assert [r.code for r in result.attempts[0].reasons] == [ReasonCode.INVALID_COMMAND] and "nested too deeply" in result.attempts[0].reasons[0].message


def test_proposal_the_depth_scan_counts_brackets_outside_strings_only():
    assert MAX_REPLY_DEPTH == 64
    assert not _too_deep("[" * 64 + "]" * 64) and _too_deep("[" * 65 + "]" * 65) and _too_deep("{" * 65)
    assert not _too_deep(json.dumps({"message": "[" * 1000 + '\\" {{{' * 100}))  # inside a string, escaped quotes included
    # a valid reply whose explanation is full of brackets is read, not refused as too deep
    result = proposer(Script({"calls": [plate()], "message": "[" * 200})).propose("car", empty(), "a plate")
    assert result.ok and len(result.attempts) == 1
