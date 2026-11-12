"""P0-06b: uv run pytest tools/review -q -k call   (네트워크 없음: 가짜 curl)"""

import json
from pathlib import Path

import pytest

from review import call, collect, common
from review.conftest import FAKE_KEY, FIXTURES

RESP = FIXTURES / "responses"
ITEMS = {str(i): n for i, n in enumerate(["계획 부합", "정확성", "테스트", "정직성 라벨", "라이선스", "보안", "디자인 부합"], 1)}


def response_review(name):
    d = json.loads((RESP / name).read_text(encoding="utf-8"))
    return json.loads(d["body"]["choices"][0]["message"]["content"])


def run(fake_env, tmp_path, **kw):
    bundle = collect.collect(101, "o/r")
    return call.review_bundle(bundle, cost_log=tmp_path / "cost.jsonl", sleep=lambda s: None, **kw)


# ---------------------------------------------------------------- 스키마 검증(응답 픽스처)

def test_call_schema_accepts_fixture_and_sorts_by_severity():
    out = call.validate(response_review("ok.json"), ITEMS)
    assert [f["severity"] for f in out["findings"]] == ["concern", "nit"]
    assert list(out["rubric"]) == list(ITEMS)


@pytest.mark.parametrize(
    "name,needle",
    [
        ("bad_verdict.json", "verdict"),
        ("bad_rubric_missing.json", "rubric 키"),
        ("bad_item.json", "item"),
        ("bad_severity.json", "severity"),
        ("bad_missing_where.json", "키는 severity,item,where,what,why,fix"),
        ("bad_approve_with_block.json", "approve"),
    ],
)
def test_call_schema_rejects_bad_fixture(name, needle):
    with pytest.raises(call.SchemaError) as e:
        call.validate(response_review(name), ITEMS)
    assert needle in str(e.value)


def test_call_schema_collects_all_violations():
    with pytest.raises(call.SchemaError) as e:
        call.validate({"verdict": "x", "rubric": [], "findings": "no", "summary": "", "extra": 1}, ITEMS)
    assert len(e.value.errors) >= 5


def test_call_schema_rejects_more_than_ten_findings_and_bool_item():
    r = response_review("ok.json")
    r["findings"] = [dict(r["findings"][0]) for _ in range(11)]
    with pytest.raises(call.SchemaError, match="최대 10건"):
        call.validate(r, ITEMS)
    r = response_review("ok.json")
    r["findings"][0]["item"] = True
    with pytest.raises(call.SchemaError, match="item"):
        call.validate(r, ITEMS)


def test_call_parse_json_variants():
    assert call.parse_json('{"a":1}') == {"a": 1}
    assert call.parse_json('```json\n{"a":1}\n```') == {"a": 1}
    assert call.parse_json('앞말 {"a":1} 뒷말') == {"a": 1}
    for bad in ("", "no json", "[1]", "{broken"):
        with pytest.raises(call.SchemaError):
            call.parse_json(bad)


# ---------------------------------------------------------------- 루브릭은 문서에서

def test_call_rubric_items_come_from_the_rubric_document():
    items, doc = call.load_rubric()
    assert items == ITEMS
    assert doc == (common.ROOT / "docs/process/review-rubric.md").read_text(encoding="utf-8")
    sys_msg = call.system_prompt(items, doc)
    assert doc in sys_msg  # 루브릭 문서 전체를 싣는다
    assert '"7":"pass|concern|block"' in sys_msg and "1-7" in sys_msg


def test_call_rubric_with_more_items_changes_schema(tmp_path):
    p = tmp_path / "rubric.md"
    p.write_text("# R\n\n## 루브릭\n\n1. **가**\n2. **나**\n8. **다**\n", encoding="utf-8")
    with pytest.raises(common.ReviewError, match="1부터 이어지는"):
        call.load_rubric(p)
    p.write_text("# R\n\n## 루브릭\n\n1. **가**\n2. **나**\n\n## 다음\n\n3. **무시**\n", encoding="utf-8")
    assert call.load_rubric(p)[0] == {"1": "가", "2": "나"}


# ---------------------------------------------------------------- 호출·재시도·비용

def test_call_success_records_tokens_and_cost(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json")
    res = run(fake_env, tmp_path)
    u = res.usage
    assert (u.calls, u.prompt_tokens, u.completion_tokens, u.reasoning_tokens) == (1, 1200, 800, 500)
    assert u.cost_usd == pytest.approx(0.0123)
    assert res.review["verdict"] == "changes" and res.attempts == 1 and res.errors == []
    rows = [json.loads(ln) for ln in (tmp_path / "cost.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["ok"] is True and rows[0]["cost_usd"] == pytest.approx(0.0123)
    assert rows[0]["pr"] == 101 and rows[0]["model"] == "openai/gpt-6.1-sol" and rows[0]["reasoning_tokens"] == 500


def test_call_request_uses_model_reasoning_high_and_key_only_in_stdin(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json")
    run(fake_env, tmp_path)
    (c,) = curl_queue.log()
    req = c["request"]
    assert req["model"] == "openai/gpt-6.1-sol" and req["reasoning"] == {"effort": "high"}
    assert req["response_format"] == {"type": "json_object"} and req["usage"] == {"include": True}
    assert req["messages"][0]["role"] == "system" and "리뷰 루브릭 문서" in req["messages"][0]["content"]
    assert "PR #101" in req["messages"][1]["content"]
    assert FAKE_KEY not in json.dumps(c["argv"]) and FAKE_KEY not in json.dumps(req)  # argv·요청 본문에 키가 없다
    assert FAKE_KEY in c["stdin"] and "https://openrouter.ai/api/v1/chat/completions" in c["argv"]


def test_call_endpoint_model_and_effort_follow_the_environment(fake_env, curl_queue, tmp_path, monkeypatch):
    monkeypatch.setenv(call.ENDPOINT_ENV, "https://proxy.example.org/v1/chat/completions")
    monkeypatch.setenv(call.MODEL_ENV, "gpt-6.1-sol")
    monkeypatch.setenv(call.EFFORT_ENV, "medium")
    curl_queue("ok.json")
    res = run(fake_env, tmp_path)
    (c,) = curl_queue.log()
    assert c["request"]["model"] == "gpt-6.1-sol" and c["request"]["reasoning"] == {"effort": "medium"}
    assert "https://proxy.example.org/v1/chat/completions" in c["argv"] and "https://openrouter.ai/api/v1/chat/completions" not in c["argv"]
    assert FAKE_KEY in c["stdin"] and FAKE_KEY not in json.dumps(c["argv"])  # 키는 여전히 표준입력으로만
    assert (res.model, res.effort) == ("gpt-6.1-sol", "medium")
    rows = [json.loads(ln) for ln in (tmp_path / "cost.jsonl").read_text().splitlines()]
    assert rows[0]["model"] == "gpt-6.1-sol" and rows[0]["effort"] == "medium"


@pytest.mark.parametrize(
    "env,value",
    [
        ("KINETRA_REVIEW_ENDPOINT", "http://proxy.example.org/v1/chat/completions"),
        ("KINETRA_REVIEW_ENDPOINT", "https://evil.example.org/x -o /tmp/y"),
        ("KINETRA_REVIEW_MODEL", "gpt 6"),
        ("KINETRA_REVIEW_EFFORT", "max"),
    ],
)
def test_call_rejects_bad_environment_settings_before_any_request(fake_env, curl_queue, tmp_path, monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    curl_queue("ok.json")
    with pytest.raises(common.ReviewError, match=env):
        run(fake_env, tmp_path)
    assert curl_queue.count == 0


@pytest.mark.parametrize("first", ["http_429.json", "http_500.json", "no_choices.json", "not_json.json", "bad_verdict.json"])
def test_call_retries_once_then_succeeds(fake_env, curl_queue, tmp_path, first):
    curl_queue(first, "ok.json")
    res = run(fake_env, tmp_path)
    assert curl_queue.count == 2 and res.attempts == 2 and len(res.errors) == 1
    assert res.review["verdict"] == "changes"
    rows = [json.loads(ln) for ln in (tmp_path / "cost.jsonl").read_text().splitlines()]
    assert [r["ok"] for r in rows] == [False, True]


def test_call_schema_retry_tells_the_model_what_was_wrong(fake_env, curl_queue, tmp_path):
    curl_queue("bad_item.json", "ok.json")
    run(fake_env, tmp_path)
    first, second = (c["request"]["messages"] for c in curl_queue.log())
    assert len(first) == 2 and len(second) == 3
    assert "스키마를 어겼다" in second[2]["content"] and "item" in second[2]["content"]


def test_call_failed_attempt_cost_is_still_counted(fake_env, curl_queue, tmp_path):
    curl_queue("bad_verdict.json", "ok.json")
    u = run(fake_env, tmp_path).usage
    assert u.calls == 2 and u.prompt_tokens == 2400 and u.cost_usd == pytest.approx(0.0246)


def test_call_gives_up_after_one_retry(fake_env, curl_queue, tmp_path):
    curl_queue("http_429.json", "http_500.json", "ok.json")
    with pytest.raises(common.ReviewError, match="2번 모두 실패"):
        run(fake_env, tmp_path)
    assert curl_queue.count == 2  # 세 번째는 부르지 않는다


def test_call_auth_error_is_not_retried(fake_env, curl_queue, tmp_path):
    curl_queue("http_401.json", "ok.json")
    with pytest.raises(common.ReviewError, match="HTTP 401"):
        run(fake_env, tmp_path)
    assert curl_queue.count == 1


def test_call_transport_failure_retries(fake_env, curl_queue, tmp_path):
    (Path(__import__("os").environ["FAKE_CURL_QUEUE"]) / "1.json").write_text(json.dumps({"exit": 28, "stderr": f"timeout with {FAKE_KEY}"}))
    (Path(__import__("os").environ["FAKE_CURL_QUEUE"]) / "2.json").write_text((RESP / "ok.json").read_text())
    res = run(fake_env, tmp_path)
    assert res.attempts == 2
    assert FAKE_KEY not in " ".join(res.errors) and "***" in res.errors[0]


def test_call_missing_key_is_an_error_and_makes_no_request(fake_env, curl_queue, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    curl_queue("ok.json")
    with pytest.raises(common.ReviewError, match="OPENROUTER_API_KEY"):
        run(fake_env, tmp_path)
    assert curl_queue.count == 0


def test_call_error_text_and_cost_log_never_contain_the_key(fake_env, curl_queue, tmp_path):
    echo = {"status": 500, "body": f"upstream echoed Authorization: Bearer {FAKE_KEY} and {FAKE_KEY}"}
    q = Path(__import__("os").environ["FAKE_CURL_QUEUE"])
    (q / "1.json").write_text(json.dumps(echo))
    (q / "2.json").write_text(json.dumps(echo))
    with pytest.raises(common.ReviewError) as e:
        run(fake_env, tmp_path)
    assert FAKE_KEY not in str(e.value) and "***" in str(e.value)
    assert FAKE_KEY not in (tmp_path / "cost.jsonl").read_text()


def test_call_cost_unknown_when_response_has_no_cost(fake_env, curl_queue, tmp_path):
    d = json.loads((RESP / "ok.json").read_text())
    d["body"]["usage"] = {"prompt_tokens": 5, "completion_tokens": 6}
    (Path(__import__("os").environ["FAKE_CURL_QUEUE"]) / "1.json").write_text(json.dumps(d))
    u = run(fake_env, tmp_path).usage
    assert u.cost_usd is None and u.prompt_tokens == 5


# ---------------------------------------------------------------- 여러 부분

def test_call_multi_part_calls_per_part_and_merges(fake_env, curl_queue, tmp_path):
    bundle = collect.collect(101, "o/r", chunk_max=420)
    n = len(bundle.diff_parts)
    assert n >= 2
    curl_queue(*(["ok.json"] * n))
    res = call.review_bundle(bundle, cost_log=None, sleep=lambda s: None)
    assert curl_queue.count == n and res.parts == n and res.usage.calls == n
    users = [c["request"]["messages"][1]["content"] for c in curl_queue.log()]
    assert all(f"부분 {i + 1}/{n}" in u for i, u in enumerate(users))
    assert len(res.review["findings"]) == 2 * n  # 각 부분의 지적이 합쳐진다


def test_call_merge_takes_worst_and_caps_findings():
    a = call.validate(response_review("ok.json"), ITEMS)
    b = json.loads(json.dumps(a))
    b["verdict"] = "block"
    b["rubric"]["2"] = "block"
    b["findings"] = [dict(a["findings"][0], where=f"f{i}:1") for i in range(10)]
    m = call.merge([a, b])
    assert m["verdict"] == "block" and m["rubric"]["2"] == "block" and m["rubric"]["1"] == "concern"
    assert len(m["findings"]) == 10 and "생략" in m["summary"]
    assert call.merge([a]) is a


def test_call_result_json_roundtrip(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json")
    res = run(fake_env, tmp_path)
    assert call.Result.from_json(res.to_json()) == res


def test_call_cli_prints_json_and_cost_summary(fake_env, curl_queue, tmp_path, capsys):
    curl_queue("ok.json")
    assert call.main(["101", "--repo", "o/r", "--cost-log", str(tmp_path / "c.jsonl")]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["review"]["verdict"] == "changes"
    assert "토큰 1200+800(reasoning 500)" in cap.err and "$0.0123" in cap.err
    assert FAKE_KEY not in cap.out + cap.err


def test_call_cli_failure_exit_code_and_masked_message(fake_env, curl_queue, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(call.time, "sleep", lambda s: None)
    curl_queue("http_401.json")
    assert call.main(["101", "--repo", "o/r", "--cost-log", str(tmp_path / "c.jsonl")]) == 1
    assert "HTTP 401" in capsys.readouterr().err


# ---------------------------------------------------------------- 1차 리뷰 반영

def good():
    return response_review("ok.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(findings=[1, "x", None]),  # 배열 원소가 객체가 아님 + approve
        lambda r: r.update(verdict="approve", findings=[None]),
        lambda r: r.update(verdict="approve", findings=[[]]),
        lambda r: r.update(verdict="approve", rubric={"1": ["block"], "2": {}, "3": None, "4": 1, "5": "pass", "6": "pass", "7": "pass"}),
        lambda r: r.update(verdict=["approve"]),
        lambda r: r.update(verdict={"a": 1}),
        lambda r: r["findings"][0].update(severity=["block"]),
        lambda r: r["findings"][0].update(severity={"x": 1}),
        lambda r: r["findings"][0].update(item=[1]),
        lambda r: r["findings"][0].update(item=1.0),
        lambda r: r["findings"][0].update(where=5),
        lambda r: r["findings"][0].update(what=None),
        lambda r: r.update(rubric={1: "pass"}),
        lambda r: r.update(summary=5),
        lambda r: r.update(findings=None),
        lambda r: r.update(verdict="approve", findings={"a": "b"}),
    ],
)
def test_call_schema_never_raises_typeerror(mutate):
    r = good()
    mutate(r)
    with pytest.raises(call.SchemaError):
        call.validate(r, ITEMS)


def test_call_validate_non_dict_top_level():
    for bad in ([], "x", 1, None):
        with pytest.raises(call.SchemaError):
            call.validate(bad, ITEMS)


def test_call_approve_with_block_is_checked_only_on_valid_arrays():
    r = good()
    r["verdict"] = "approve"
    r["findings"][0]["severity"] = "block"
    with pytest.raises(call.SchemaError, match="approve"):
        call.validate(r, ITEMS)
    r["findings"][0]["severity"] = "concern"
    r["rubric"]["2"] = "pass"
    r["rubric"]["1"] = "pass"
    assert call.validate(r, ITEMS)["verdict"] == "approve"


@pytest.mark.parametrize("where", ["tools/x.py:9", "a/b c/d.py:1", "한글/파일.md:12-30", "x.py:7-7", "C:/x.py:3"])
def test_call_where_accepts_path_line(where):
    r = good()
    r["findings"][0]["where"] = where
    call.validate(r, ITEMS)


@pytest.mark.parametrize("where", ["x.py", "x.py:0", "x.py:-3", "x.py:abc", "x.py:9-3", "x.py:1-", ":5", " x.py:5", "x.py:5\n", "x.py:1,2", "a|b.py:3", "a`b.py:3", "x.py:1.5", "여러 곳", "x.py:99999999999"])
def test_call_where_rejects_bad_syntax(where):
    r = good()
    r["findings"][0]["where"] = where
    with pytest.raises(call.SchemaError, match="where"):
        call.validate(r, ITEMS)


def _queue(*specs):
    q = Path(os.environ["FAKE_CURL_QUEUE"])
    for i, spec in enumerate(specs, 1):
        (q / f"{i}.json").write_text(json.dumps(spec, ensure_ascii=False))


def _resp(content, **usage):
    return {"status": 200, "body": {"choices": [{"message": {"content": content}}], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}}}


import os  # noqa: E402

MALFORMED = {
    "choices_not_list": {"status": 200, "body": {"choices": "x", "usage": {"prompt_tokens": 7, "cost": 0.02}}},
    "choices_dict": {"status": 200, "body": {"choices": {"message": {}}}},
    "choice_not_dict": {"status": 200, "body": {"choices": ["x"]}},
    "message_not_dict": {"status": 200, "body": {"choices": [{"message": "x"}]}},
    "message_null": {"status": 200, "body": {"choices": [{"message": None}]}},
    "content_list": {"status": 200, "body": {"choices": [{"message": {"content": ["a"]}}]}},
    "content_null": {"status": 200, "body": {"choices": [{"message": {"content": None}}]}},
    "body_list": {"status": 200, "body": [1, 2]},
    "body_string_json": {"status": 200, "body": "\"just a string\""},
    "usage_garbage": {"status": 200, "body": {"choices": [{"message": {"content": "no json here"}}], "usage": "oops"}},
    "usage_nested_garbage": {"status": 200, "body": {"choices": [{"message": {"content": "{}"}}], "usage": {"completion_tokens_details": "x", "cost": "free", "prompt_tokens": -4}}},
}


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_call_malformed_response_retries_then_gives_up_with_two_attempts(fake_env, curl_queue, tmp_path, name):
    _queue(MALFORMED[name], MALFORMED[name], MALFORMED[name])
    with pytest.raises(common.ReviewError, match="2번 모두 실패"):
        run(fake_env, tmp_path)
    assert curl_queue.count == 2  # 상한 2번
    rows = [json.loads(ln) for ln in (tmp_path / "cost.jsonl").read_text().splitlines()]
    assert [r["ok"] for r in rows] == [False, False]  # 시도마다 기록


def test_call_malformed_then_valid_recovers(fake_env, curl_queue, tmp_path):
    _queue(MALFORMED["message_not_dict"], json.loads((RESP / "ok.json").read_text()))
    res = run(fake_env, tmp_path)
    assert res.attempts == 2 and res.review["verdict"] == "changes"


def test_call_malformed_attempt_cost_is_counted_per_attempt(fake_env, curl_queue, tmp_path):
    _queue(MALFORMED["choices_not_list"], json.loads((RESP / "ok.json").read_text()))
    res = run(fake_env, tmp_path)
    rows = [json.loads(ln) for ln in (tmp_path / "cost.jsonl").read_text().splitlines()]
    assert rows[0]["ok"] is False and rows[0]["prompt_tokens"] == 7 and rows[0]["cost_usd"] == pytest.approx(0.02)
    assert res.usage.cost_usd == pytest.approx(0.0323) and res.usage.prompt_tokens == 1207


def test_call_schema_violation_retry_keeps_cost_for_every_attempt(fake_env, curl_queue, tmp_path):
    bad = good()
    bad["findings"] = [None]
    bad["verdict"] = "approve"  # 예전에는 TypeError 로 재시도 없이 죽었다
    _queue(_resp(json.dumps(bad), prompt_tokens=100, completion_tokens=10, cost=0.5), json.loads((RESP / "ok.json").read_text()))
    res = run(fake_env, tmp_path)
    assert res.attempts == 2 and res.usage.calls == 2 and res.usage.cost_usd == pytest.approx(0.5123)


def test_call_unknown_cost_is_reported_as_partial_sum(fake_env, curl_queue, tmp_path):
    _queue(_resp("not json", prompt_tokens=100, completion_tokens=10), json.loads((RESP / "ok.json").read_text()))
    u = run(fake_env, tmp_path).usage
    assert u.cost_usd == pytest.approx(0.0123) and u.cost_unknown_calls == 1
    assert u.cost_text() == "$0.0123(확인된 비용 합계, 호출 1회는 비용 미상)"


def test_call_transport_failure_counts_as_unknown_cost(fake_env, curl_queue, tmp_path):
    q = Path(os.environ["FAKE_CURL_QUEUE"])
    (q / "1.json").write_text(json.dumps({"exit": 28, "stderr": "timeout"}))
    (q / "2.json").write_text((RESP / "ok.json").read_text())
    u = run(fake_env, tmp_path).usage
    assert u.cost_unknown_calls == 1 and "미상" in u.cost_text() and u.cost_usd == pytest.approx(0.0123)


def test_call_cost_text_variants():
    assert call.Usage().cost_text() == "미상"
    assert call.Usage(cost_usd=0.5).cost_text() == "$0.5000"
    assert call.Usage(cost_usd=0.5, cost_unknown_calls=2).cost_text() == "$0.5000(확인된 비용 합계, 호출 2회는 비용 미상)"


def test_call_usage_add_survives_garbage():
    u = call.Usage()
    for raw in ("x", 5, None, [], {"cost": float("nan")}, {"cost": -1}, {"cost": True}, {"completion_tokens_details": 3}):
        u.add(raw)
    assert u.calls == 8 and u.cost_usd is None and u.cost_unknown_calls == 8


def test_call_cli_prints_partial_cost_text(fake_env, curl_queue, tmp_path, capsys):
    _queue(_resp("no", prompt_tokens=1), json.loads((RESP / "ok.json").read_text()))
    assert call.main(["101", "--repo", "o/r", "--cost-log", str(tmp_path / "c.jsonl")]) == 0
    assert "확인된 비용 합계" in capsys.readouterr().err


# ---------------------------------------------------------------- 2차 리뷰 반영

def test_call_schema_retry_message_masks_echoed_secret(fake_env, curl_queue, tmp_path):
    bad = good()
    bad["verdict"] = FAKE_KEY  # 모델이 비밀을 되돌려 쓴 잘못된 필드
    bad["findings"][0]["severity"] = f"Bearer {FAKE_KEY}"
    _queue(_resp(json.dumps(bad)), json.loads((RESP / "ok.json").read_text()))
    res = run(fake_env, tmp_path)
    assert res.attempts == 2
    first, second = (c["request"] for c in curl_queue.log())
    retry_text = json.dumps(second, ensure_ascii=False)
    assert FAKE_KEY not in retry_text and "스키마를 어겼다" in retry_text and "***" in retry_text
    assert FAKE_KEY not in " ".join(res.errors) and FAKE_KEY not in (tmp_path / "cost.jsonl").read_text()


@pytest.mark.parametrize("cost", [10**400, -(10**400), 1e999, float("inf"), float("nan"), -1, True, "1", None, [1]])
def test_call_usage_add_odd_cost_is_unknown_not_a_crash(cost):
    u = call.Usage()
    one = u.add({"prompt_tokens": 3, "cost": cost})
    assert one["cost_usd"] is None and u.cost_usd is None and u.cost_unknown_calls == 1 and u.prompt_tokens == 3


def test_call_huge_int_cost_through_the_call_path(fake_env, curl_queue, tmp_path):
    d = json.loads((RESP / "ok.json").read_text())
    q = Path(os.environ["FAKE_CURL_QUEUE"])
    (q / "1.json").write_text(json.dumps(d).replace('"cost": 0.0123', '"cost": ' + "9" * 400))  # JSON 의 아주 큰 정수
    assert "9" * 400 in (q / "1.json").read_text()
    res = run(fake_env, tmp_path)
    assert res.usage.cost_usd is None and res.usage.cost_unknown_calls == 1 and res.usage.prompt_tokens == 1200
    assert "미상" in res.usage.cost_text()
    row = json.loads((tmp_path / "cost.jsonl").read_text().splitlines()[0])
    assert row["ok"] is True and row["cost_usd"] is None


def test_call_cli_failure_after_two_validation_failures_prints_summary(fake_env, curl_queue, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(call.time, "sleep", lambda s: None)
    curl_queue("bad_verdict.json", "bad_item.json", "ok.json")
    assert call.main(["101", "--repo", "o/r", "--cost-log", str(tmp_path / "c.jsonl")]) == 1
    err = capsys.readouterr().err
    assert "2번 모두 실패" in err
    assert "call: 호출 2회, 토큰 2400+1600(reasoning 1000), 비용 $0.0246" in err
    assert curl_queue.count == 2


def test_call_review_bundle_fills_the_callers_usage_on_failure(fake_env, curl_queue, tmp_path):
    curl_queue("bad_verdict.json", "bad_verdict.json")
    u = call.Usage()
    with pytest.raises(common.ReviewError):
        call.review_bundle(collect.collect(101, "o/r"), cost_log=None, sleep=lambda s: None, usage=u)
    assert u.calls == 2 and u.cost_usd == pytest.approx(0.0246)


def test_call_cli_auth_failure_prints_summary_with_unknown_cost(fake_env, curl_queue, tmp_path, capsys):
    curl_queue("http_401.json")
    assert call.main(["101", "--repo", "o/r", "--cost-log", str(tmp_path / "c.jsonl")]) == 1
    err = capsys.readouterr().err
    assert "HTTP 401" in err and "call: 호출 1회, 토큰 0+0(reasoning 0), 비용 미상" in err
