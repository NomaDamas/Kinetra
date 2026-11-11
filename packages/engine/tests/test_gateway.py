"""G-01 LLM gateway. Offline: every test uses a fake transport, nothing touches the network.

    uv run pytest packages/engine -q -k gateway
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
from kinetra_engine.gateway import (
    Budget,
    BudgetExceeded,
    Gateway,
    GatewayError,
    HttpRequest,
    HttpResponse,
    TransportError,
    UpstreamError,
    redact,
)
from kinetra_engine.gateway.transport import check_base_url

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"
MSG = [{"role": "user", "content": "hello"}]
ROOT = Path(__file__).resolve().parents[3]


def ok_body(content="hi", cost=0.01, prompt=10, completion=5, model="openai/gpt-6.1-sol"):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    if cost is not None:
        usage["cost"] = cost
    return json.dumps({"model": model, "choices": [{"message": {"role": "assistant", "content": content}}], "usage": usage}).encode()


class Fake:
    """Records every request and answers from a queue (or a default 200)."""

    def __init__(self, *responses):
        self.requests: list[HttpRequest] = []
        self.responses = list(responses)

    def __call__(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        r = self.responses.pop(0) if self.responses else HttpResponse(200, ok_body())
        if isinstance(r, Exception):
            raise r
        return r


def make(tmp_path, fake=None, budget=None, ledger=True, env=None, **kw):
    fake = fake or Fake()
    gw = Gateway(
        default_model="openai/gpt-6.1-sol",
        budgets={"p1": budget or Budget(max_calls=3)},
        ledger_path=(tmp_path / "cost.jsonl") if ledger else None,
        env={"OPENROUTER_API_KEY": KEY} if env is None else env,
        transport=fake,
        **kw,
    )
    return gw, fake


def lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "cost.jsonl").read_text().splitlines()]


# ---------------------------------------------------------------- DoD: budget exceeded is rejected


def test_gateway_rejects_when_call_budget_is_used_up(tmp_path):
    gw, fake = make(tmp_path, budget=Budget(max_calls=2))
    gw.chat("p1", MSG)
    gw.chat("p1", MSG)
    with pytest.raises(BudgetExceeded, match="call budget used up"):
        gw.chat("p1", MSG)
    assert len(fake.requests) == 2  # the third was never sent
    assert gw.usage("p1")["calls"] == 2 and gw.usage("p1")["calls_left"] == 0


def test_gateway_rejects_when_cost_budget_would_be_exceeded(tmp_path):
    fake = Fake(HttpResponse(200, ok_body(cost=0.06)), HttpResponse(200, ok_body(cost=0.06)))
    gw, _ = make(tmp_path, fake, Budget(max_cost_usd=0.10, assumed_call_cost_usd=0.05))
    gw.chat("p1", MSG)  # charged 0.06, 0.04 left
    with pytest.raises(BudgetExceeded, match="cost budget"):
        gw.chat("p1", MSG)  # next call is assumed 0.05 > 0.04
    assert len(fake.requests) == 1
    assert gw.usage("p1")["charged_usd"] == pytest.approx(0.06)


def test_gateway_budget_is_per_project(tmp_path):
    gw = Gateway(
        default_model="m", budgets={"a": Budget(max_calls=1), "b": Budget(max_calls=1)}, env={"OPENROUTER_API_KEY": KEY}, transport=Fake()
    )
    gw.chat("a", MSG)
    gw.chat("b", MSG)  # b is untouched by a's spending
    with pytest.raises(BudgetExceeded):
        gw.chat("a", MSG)


def test_gateway_project_without_a_budget_is_rejected_not_unlimited(tmp_path):
    gw, fake = make(tmp_path)
    with pytest.raises(BudgetExceeded, match="no budget is configured"):
        gw.chat("other", MSG)
    assert fake.requests == []


def test_gateway_zero_budget_rejects_everything(tmp_path):
    gw, fake = make(tmp_path, budget=Budget(max_calls=0))
    with pytest.raises(BudgetExceeded):
        gw.chat("p1", MSG)
    assert fake.requests == []


def test_gateway_unknown_cost_is_charged_the_declared_assumption(tmp_path):
    fake = Fake(*[HttpResponse(200, ok_body(cost=None))] * 2)
    gw, _ = make(tmp_path, fake, Budget(max_cost_usd=0.10, assumed_call_cost_usd=0.04))
    r = gw.chat("p1", MSG)
    assert r.cost_usd is None and r.charged_usd == 0.04
    gw.chat("p1", MSG)
    with pytest.raises(BudgetExceeded):  # 0.08 charged, 0.04 more would pass 0.10
        gw.chat("p1", MSG)
    u = gw.usage("p1")
    assert u["unknown_cost_calls"] == 2 and u["charged_usd"] == pytest.approx(0.08)


def test_gateway_in_flight_calls_hold_budget(tmp_path):
    """A second call made while the first is still waiting cannot spend the first call's share."""
    gw, _ = make(tmp_path, budget=Budget(max_calls=1))
    inner = {}

    def reentrant(req):
        try:
            gw.chat("p1", MSG)
        except BudgetExceeded as e:
            inner["err"] = e
        return HttpResponse(200, ok_body())

    gw._transport = reentrant
    gw.chat("p1", MSG)
    assert "err" in inner


def test_gateway_budget_validation():
    for bad in (dict(), dict(max_calls=-1), dict(max_calls=True), dict(max_cost_usd=1.0), dict(max_cost_usd=float("nan"), assumed_call_cost_usd=0.1),
                dict(max_calls=1, assumed_call_cost_usd=0.1), dict(max_cost_usd=-1, assumed_call_cost_usd=0.1)):
        with pytest.raises(ValueError):
            Budget(**bad)


# ---------------------------------------------------------------- DoD: cost is recorded


def test_gateway_records_cost_per_call_and_replays_it_after_restart(tmp_path):
    fake = Fake(HttpResponse(200, ok_body(cost=0.0123, prompt=11, completion=7)), HttpResponse(500, b'{"error":{"message":"boom"}}'))
    gw, _ = make(tmp_path, fake, Budget(max_calls=3))
    r = gw.chat("p1", MSG)
    assert (r.text, r.prompt_tokens, r.completion_tokens, r.cost_usd, r.charged_usd) == ("hi", 11, 7, 0.0123, 0.0123)
    with pytest.raises(UpstreamError) as e:
        gw.chat("p1", MSG)
    assert e.value.status == 500
    rows = lines(tmp_path)
    assert [x["status"] for x in rows] == ["ok", "http_error"]
    assert rows[0]["project"] == "p1" and rows[0]["cost_usd"] == 0.0123 and rows[0]["prompt_tokens"] == 11
    assert rows[1]["http_status"] == 500 and rows[1]["cost_usd"] is None
    # an error response is a request that was sent: it counts against the budget
    assert gw.usage("p1")["calls"] == 2
    # a new process reads the ledger and keeps counting
    gw2, fake2 = make(tmp_path, Fake(), Budget(max_calls=3))
    assert gw2.usage("p1")["calls"] == 2
    gw2.chat("p1", MSG)
    with pytest.raises(BudgetExceeded):
        gw2.chat("p1", MSG)


def test_gateway_ledger_never_stores_message_text(tmp_path):
    gw, _ = make(tmp_path)
    gw.chat("p1", [{"role": "user", "content": "SECRET-DESIGN-TEXT"}])
    assert "SECRET-DESIGN-TEXT" not in (tmp_path / "cost.jsonl").read_text()


def test_gateway_rejections_are_logged_but_not_counted_as_spend(tmp_path):
    gw, _ = make(tmp_path, budget=Budget(max_calls=1))
    gw.chat("p1", MSG)
    with pytest.raises(BudgetExceeded):
        gw.chat("p1", MSG)
    assert [x["status"] for x in lines(tmp_path)] == ["ok", "rejected"]
    gw2, _ = make(tmp_path, budget=Budget(max_calls=1))
    assert gw2.usage("p1")["calls"] == 1  # replay skips the rejection


def test_gateway_transport_failure_is_charged_as_unknown_and_logged(tmp_path):
    gw, _ = make(tmp_path, Fake(TransportError("request failed: TimeoutError")), Budget(max_cost_usd=1.0, assumed_call_cost_usd=0.25))
    with pytest.raises(UpstreamError):
        gw.chat("p1", MSG)
    row = lines(tmp_path)[0]
    assert row["status"] == "transport_error" and row["cost_usd"] is None and row["charged_usd"] == 0.25
    assert gw.usage("p1")["charged_usd"] == 0.25 and gw.usage("p1")["cost_left_usd"] == pytest.approx(0.75)


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"choices":[]}', b'{"choices":[{"message":{"content":"  "}}]}', b'{"choices":[{"message":null}]}'])
def test_gateway_malformed_response_is_an_error_and_still_counts(tmp_path, body):
    gw, _ = make(tmp_path, Fake(HttpResponse(200, body)), Budget(max_calls=1))
    with pytest.raises(UpstreamError, match="no message content"):
        gw.chat("p1", MSG)
    assert gw.usage("p1")["calls"] == 1
    assert lines(tmp_path)[0]["status"] == "malformed"


@pytest.mark.parametrize("cost", ["0.5", True, -1, float("nan"), float("inf"), None, 10**400])
def test_gateway_bad_reported_cost_counts_as_unknown(tmp_path, cost):
    body = json.dumps({"choices": [{"message": {"content": "x"}}], "usage": {"cost": cost}}, allow_nan=True).encode()
    gw, _ = make(tmp_path, Fake(HttpResponse(200, body)), Budget(max_cost_usd=1.0, assumed_call_cost_usd=0.3))
    r = gw.chat("p1", MSG)
    assert r.cost_usd is None and r.charged_usd == 0.3


def test_gateway_corrupt_ledger_stops_startup_instead_of_forgetting_spend(tmp_path):
    (tmp_path / "cost.jsonl").write_text('{"project":"p1","charged_usd":0.1}\n{broken\n')
    with pytest.raises(GatewayError, match="refusing to start"):
        make(tmp_path)
    (tmp_path / "cost.jsonl").write_text('{"project":"p1","cost_usd":null}\n')
    with pytest.raises(GatewayError, match="charged_usd"):
        make(tmp_path)


# ---------------------------------------------------------------- DoD: the key lives only in the core process environment


def test_gateway_key_comes_only_from_the_environment(tmp_path):
    with pytest.raises(GatewayError, match="OPENROUTER_API_KEY is not set"):
        make(tmp_path, env={})
    with pytest.raises(GatewayError):
        make(tmp_path, env={"OPENROUTER_API_KEY": "   "})
    with pytest.raises(TypeError):  # there is no way to pass a key in
        Gateway(default_model="m", budgets={}, api_key=KEY)  # type: ignore[call-arg]


def test_gateway_key_goes_only_in_the_authorization_header(tmp_path):
    gw, fake = make(tmp_path)
    gw.chat("p1", MSG)
    req = fake.requests[0]
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert KEY.encode() not in req.body and KEY not in req.url
    assert req.url == "https://openrouter.ai/api/v1/chat/completions"
    assert json.loads(req.body)["usage"] == {"include": True}
    assert KEY not in repr(req)


def test_gateway_key_never_appears_in_anything_returned_or_written(tmp_path):
    echo = {"error": {"message": f"bad key {KEY} / Authorization: Bearer {KEY}"}}
    fake = Fake(HttpResponse(401, json.dumps(echo).encode()), HttpResponse(200, ok_body(content=f"my key is {KEY}")), TransportError(f"fail {KEY}"))
    gw, _ = make(tmp_path, fake, Budget(max_calls=5))
    seen = []
    with pytest.raises(UpstreamError) as e:
        gw.chat("p1", MSG)
    seen.append(str(e.value))
    seen.append(gw.chat("p1", MSG).text)
    with pytest.raises(UpstreamError) as e:
        gw.chat("p1", MSG)
    seen.append(str(e.value))
    seen += [json.dumps(gw.usage("p1")), repr(gw), (tmp_path / "cost.jsonl").read_text()]
    for s in seen:
        assert KEY not in s
        assert "0123456789abcdef" not in s
    assert "***" in seen[0]


def test_gateway_does_not_leak_the_key_into_the_cause_chain(tmp_path):
    gw, _ = make(tmp_path, Fake(TransportError(f"fail {KEY}")))
    with pytest.raises(UpstreamError) as e:
        gw.chat("p1", MSG)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_gateway_key_is_not_referenced_outside_the_core_packages():
    """The key's variable name appears only in the Python core and dev tooling, never in a client (web app, UI package, design exports)."""
    pat = re.compile(r"OPENROUTER_API_KEY|openrouter\.ai")
    out = subprocess.run(["git", "ls-files", "apps", "packages/ui", "design"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for rel in out:
        p = ROOT / rel
        if p.suffix in {".ts", ".tsx", ".js", ".mjs", ".jsx", ".json", ".html", ".css", ".md"} and p.is_file():
            if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(rel)
    assert hits == []


def test_gateway_redact_masks_key_shaped_strings_and_exact_secrets():
    assert redact(f"a {KEY} b") == "a *** b"
    assert redact("Authorization: Bearer abc.def-123") == "Authorization: ***"
    assert redact("token ghp_" + "a" * 20) == "token ***"
    assert redact("hunter2hunter2", ("hunter2hunter2",)) == "***"
    assert redact("plain text") == "plain text"


def test_gateway_redact_patterns_match_review_bot():
    """The review bot's patterns (tools/review/common.py) are the reference; this fails if the two lists drift."""
    bot = (ROOT / "tools" / "review" / "common.py").read_text(encoding="utf-8")
    ours = (ROOT / "packages" / "engine" / "src" / "kinetra_engine" / "gateway" / "redact.py").read_text(encoding="utf-8")
    pat = re.compile(r're\.compile\((r"(?:[^"\\\n]|\\.)*")')
    assert len(pat.findall(bot)) == 4 and pat.findall(bot) == pat.findall(ours)


@pytest.mark.parametrize("url", ["http://openrouter.ai/api/v1", "ftp://x", "https://", "openrouter.ai", "http://evil.example"])
def test_gateway_refuses_non_https_base_urls_except_loopback(url):
    with pytest.raises(GatewayError):
        check_base_url(url)
    assert check_base_url("http://127.0.0.1:8080/v1/") == "http://127.0.0.1:8080/v1"
    assert check_base_url("https://openrouter.ai/api/v1/") == "https://openrouter.ai/api/v1"


def test_gateway_request_model_and_max_tokens(tmp_path):
    gw, fake = make(tmp_path)
    gw.chat("p1", MSG, max_tokens=64)
    gw.chat("p1", MSG, model="other/model")
    a, b = (json.loads(r.body) for r in fake.requests)
    assert (a["model"], a["max_tokens"], b["model"], "max_tokens" in b) == ("openai/gpt-6.1-sol", 64, "other/model", False)
    assert a["messages"] == MSG


def test_gateway_runs_without_a_ledger_file():
    gw, _ = make(None, ledger=False)
    gw.chat("p1", MSG)
    assert gw.usage("p1")["calls"] == 1
