"""G-01 LLM gateway. Offline: every test uses a fake transport, nothing touches the network.

    uv run pytest packages/engine -q -k gateway
"""

import http.server
import json
import re
import subprocess
import threading
from pathlib import Path

import pytest
from kinetra_engine.gateway import (
    Budget,
    BudgetExceeded,
    Gateway,
    GatewayClosed,
    GatewayError,
    HttpRequest,
    HttpResponse,
    LedgerWriteError,
    TransportError,
    UpstreamError,
    redact,
)
from kinetra_engine.gateway.budget import to_micro
from kinetra_engine.gateway.redact import mask_exact
from kinetra_engine.gateway.transport import check_base_url, urllib_transport

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
        if isinstance(r, BaseException):
            raise r
        return r


@pytest.fixture(autouse=True)
def core_env(monkeypatch):
    """The core process environment: the only place the key can come from."""
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)


def make(tmp_path, fake=None, budget=None, ledger=True, project="p1", **kw):
    fake = fake or Fake()
    gw = Gateway(
        default_model="openai/gpt-6.1-sol",
        budgets={project: budget or Budget(max_calls=3)},
        ledger_path=(tmp_path / "cost.jsonl") if ledger else None,
        transport=fake,
        **kw,
    )
    return gw, fake


def all_lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "cost.jsonl").read_text().splitlines()]


def lines(tmp_path):
    """The ledger without the `reserved` lines: one settled or rejected record per request."""
    return [x for x in all_lines(tmp_path) if x["status"] != "reserved"]


def fail_settlements(gw):
    """Make every ledger write after the `reserved` line fail, as a disk that fills up during the call would."""
    real = gw._ledger.append

    def append(entry):
        if entry["status"] == "reserved":
            return real(entry)
        raise OSError("disk full")

    gw._ledger.append = append


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
    gw = Gateway(default_model="m", budgets={"a": Budget(max_calls=1), "b": Budget(max_calls=1)}, transport=Fake())
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
                dict(max_calls=1, assumed_call_cost_usd=0.1), dict(max_cost_usd=-1, assumed_call_cost_usd=0.1),
                dict(max_cost_usd=1.0, assumed_call_cost_usd=0), dict(max_cost_usd=1.0, assumed_call_cost_usd=0.0)):
        with pytest.raises(ValueError):
            Budget(**bad)


# ---------------------------------------------------------------- DoD: cost is recorded


def test_gateway_records_cost_per_call_and_replays_it_after_restart(tmp_path):
    fake = Fake(HttpResponse(200, ok_body(cost=0.0123, prompt=11, completion=7)), HttpResponse(500, b'{"error":{"message":"boom"}}'))
    slug = "desk-lamp-rocket"  # contains `sk-lamp-rocket`, which a key-shaped pattern would mask and so lose the project's spend
    gw, _ = make(tmp_path, fake, Budget(max_calls=3), project=slug)
    r = gw.chat(slug, MSG)
    assert (r.text, r.prompt_tokens, r.completion_tokens, r.cost_usd, r.charged_usd) == ("hi", 11, 7, 0.0123, 0.0123)
    with pytest.raises(UpstreamError) as e:
        gw.chat(slug, MSG)
    assert e.value.status == 500
    rows = lines(tmp_path)
    assert [x["status"] for x in rows] == ["ok", "http_error"]
    assert rows[0]["project"] == slug and rows[0]["cost_usd"] == 0.0123 and rows[0]["prompt_tokens"] == 11
    assert rows[0]["charged_micro_usd"] == 12300
    assert rows[1]["http_status"] == 500 and rows[1]["cost_usd"] is None
    # an error response is a request that was sent: it counts against the budget
    assert gw.usage(slug)["calls"] == 2
    # a new process reads the ledger and keeps counting, under the same project id
    gw2, _ = make(tmp_path, Fake(), Budget(max_calls=3), project=slug)
    assert gw2.usage(slug)["calls"] == 2
    gw2.chat(slug, MSG)
    with pytest.raises(BudgetExceeded):
        gw2.chat(slug, MSG)


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
    assert row["status"] == "transport_error" and row["cost_usd"] is None and row["charged_micro_usd"] == 250000
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
    (tmp_path / "cost.jsonl").write_text('{"project":"p1","charged_micro_usd":100000}\n{broken\n')
    with pytest.raises(GatewayError, match="refusing to start"):
        make(tmp_path)
    (tmp_path / "cost.jsonl").write_text('{"project":"p1","cost_usd":null}\n')
    with pytest.raises(GatewayError, match="charged_micro_usd"):
        make(tmp_path)


# ---------------------------------------------------------------- DoD: the key lives only in the core process environment


def test_gateway_key_comes_only_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(GatewayError, match="OPENROUTER_API_KEY is not set"):
        make(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    with pytest.raises(GatewayError):
        make(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    for kwarg in ("api_key", "key", "env"):  # there is no way to pass a key (or a substitute environment) in
        with pytest.raises(TypeError):
            Gateway(default_model="m", budgets={}, **{kwarg: KEY})  # type: ignore[arg-type]


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


# ---------------------------------------------------------------- review fixes


def test_gateway_reply_text_is_not_pattern_masked(tmp_path):
    """Only the exact key is removed from a model reply; hyphenated words and prose that merely look like a key stay intact."""
    text = f"Use the disk-brake-rotor and task-0123456789; the bearer bracket holds. key={KEY}"
    gw, _ = make(tmp_path, Fake(HttpResponse(200, ok_body(content=text))))
    out = gw.chat("p1", MSG).text
    assert out == "Use the disk-brake-rotor and task-0123456789; the bearer bracket holds. key=***"


def test_gateway_error_text_is_pattern_masked(tmp_path):
    echo = {"error": {"message": "rejected sk-someotherkey1234 and Bearer abc.def"}}
    gw, _ = make(tmp_path, Fake(HttpResponse(401, json.dumps(echo).encode())))
    with pytest.raises(UpstreamError) as e:
        gw.chat("p1", MSG)
    assert "sk-someotherkey1234" not in str(e.value) and "abc.def" not in str(e.value)


def test_gateway_ledger_masks_exact_key_before_serialising(tmp_path):
    """A key with a quote or backslash is escaped by json.dumps and would no longer match afterwards."""
    tricky = 'ab"cd\\ef-secret'
    assert mask_exact({"x": f"p{tricky}q", f"k{tricky}": [tricky]}, (tricky,)) == {"x": "p***q", "k***": ["***"]}
    gw, _ = make(tmp_path, project=f"proj-{KEY}")
    gw.chat(f"proj-{KEY}", MSG)
    text = (tmp_path / "cost.jsonl").read_text()
    assert KEY not in text and "proj-***" in text


def test_gateway_unserialisable_request_leaves_no_reservation(tmp_path):
    gw, fake = make(tmp_path, budget=Budget(max_calls=1))
    with pytest.raises(TypeError):
        gw.chat("p1", [{"role": "user", "content": b"bytes are not JSON"}])
    assert fake.requests == []
    assert gw.usage("p1")["calls_left"] == 1
    assert gw.chat("p1", MSG).text == "hi"  # the one call was not eaten by the failed one


def test_gateway_unexpected_transport_exception_becomes_a_masked_upstream_error_and_settles(tmp_path):
    gw, _ = make(tmp_path, Fake(RuntimeError(f"boom {KEY} sk-otherkey123456")), Budget(max_cost_usd=1.0, assumed_call_cost_usd=0.25))
    with pytest.raises(UpstreamError) as e:
        gw.chat("p1", MSG)
    assert "RuntimeError" in str(e.value) and KEY not in str(e.value) and "sk-otherkey123456" not in str(e.value)
    assert e.value.__cause__ is None
    u = gw.usage("p1")
    assert u["calls"] == 1 and u["charged_usd"] == 0.25 and u["cost_left_usd"] == 0.75  # the request may have left: charged the assumed cost, reservation released
    row = lines(tmp_path)[0]
    assert row["status"] == "transport_error" and row["charged_micro_usd"] == 250000
    assert KEY not in (tmp_path / "cost.jsonl").read_text()


def test_gateway_keyboard_interrupt_still_settles_the_books(tmp_path):
    gw, _ = make(tmp_path, Fake(KeyboardInterrupt()), Budget(max_calls=2))
    with pytest.raises(KeyboardInterrupt):
        gw.chat("p1", MSG)
    assert gw.usage("p1")["calls"] == 1 and gw.usage("p1")["calls_left"] == 1


class _Server:
    def __init__(self, handler):
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_gateway_urllib_transport_does_not_follow_redirects(tmp_path):
    seen = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(ok_body())

        def log_message(self, *a):
            pass

    with _Server(Target) as target:

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(307)
                self.send_header("Location", target.url + "/steal")
                self.end_headers()

            def log_message(self, *a):
                pass

        with _Server(Redirector) as redirector:
            gw = Gateway(default_model="m", budgets={"p1": Budget(max_calls=2)}, ledger_path=tmp_path / "cost.jsonl", base_url=redirector.url + "/v1")
            with pytest.raises(UpstreamError, match="redirects are not followed") as e:
                gw.chat("p1", MSG)
    assert e.value.status == 307
    assert seen == []  # the key never reached the redirect target
    assert gw.usage("p1")["calls"] == 1  # the request was sent, so it is spent
    assert lines(tmp_path)[0]["status"] == "http_error"


def test_gateway_urllib_transport_reads_error_bodies_and_round_trips():
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            code = 429 if b"fail" in body else 200
            self.send_response(code)
            self.end_headers()
            self.wfile.write(ok_body() if code == 200 else b'{"error":{"message":"slow down"}}')

        def log_message(self, *a):
            pass

    with _Server(H) as s:
        ok = urllib_transport(HttpRequest(s.url, b"{}", {"Content-Type": "application/json"}, 5))
        bad = urllib_transport(HttpRequest(s.url, b"fail", {"Content-Type": "application/json"}, 5))
    assert ok.status == 200 and bad.status == 429 and b"slow down" in bad.body
    with pytest.raises(TransportError):
        urllib_transport(HttpRequest("http://127.0.0.1:9/", b"{}", {}, 1))


def test_gateway_ledger_write_failure_closes_the_gateway_and_returns_the_reply(tmp_path):
    gw, fake = make(tmp_path, Fake(HttpResponse(200, ok_body(content="the answer", cost=0.02))), Budget(max_calls=5))

    fail_settlements(gw)
    with pytest.raises(LedgerWriteError) as e:
        gw.chat("p1", MSG)
    err = e.value
    assert err.reply is not None and err.reply.text == "the answer" and err.charged_usd == pytest.approx(0.02)
    assert "may not be on disk" in str(err) and KEY not in str(err)
    assert gw.usage("p1")["closed"] is True and gw.usage("p1")["charged_usd"] == pytest.approx(0.02)
    with pytest.raises(GatewayClosed):  # nothing more is sent: spend that cannot be recorded would be forgotten
        gw.chat("p1", MSG)
    assert len(fake.requests) == 1


def test_gateway_ledger_write_failure_after_an_upstream_error_keeps_the_error(tmp_path):
    gw, _ = make(tmp_path, Fake(HttpResponse(500, b'{"error":{"message":"boom"}}')), Budget(max_calls=5))
    fail_settlements(gw)
    with pytest.raises(LedgerWriteError) as e:
        gw.chat("p1", MSG)
    assert e.value.reply is None and isinstance(e.value.upstream, UpstreamError) and e.value.upstream.status == 500


def test_gateway_budget_arithmetic_is_exact_in_micro_dollars(tmp_path):
    """Three calls of $0.10 fit in $0.30 exactly (0.1 + 0.1 + 0.1 > 0.3 in floats), the fourth does not."""
    assert 0.1 + 0.1 + 0.1 > 0.3
    fake = Fake(*[HttpResponse(200, ok_body(cost=0.10))] * 3)
    gw, _ = make(tmp_path, fake, Budget(max_cost_usd=0.30, assumed_call_cost_usd=0.10))
    for _ in range(3):
        gw.chat("p1", MSG)
    with pytest.raises(BudgetExceeded):
        gw.chat("p1", MSG)
    assert gw.usage("p1")["charged_usd"] == 0.3 and gw.usage("p1")["cost_left_usd"] == 0.0
    assert len(fake.requests) == 3


def test_gateway_to_micro_rounds_a_real_cost_up_never_to_zero():
    assert to_micro(0.1) == 100000 and to_micro(0.3) == 300000 and to_micro(0) == 0
    assert to_micro(1e-9) == 1  # a non-zero cost is never free
    assert to_micro(0.0000015) == 2


def test_gateway_tiny_reported_costs_still_consume_the_budget(tmp_path):
    """A reported $1e-9 is charged one micro-dollar, so a long run of tiny calls still hits the cap."""
    fake = Fake(*[HttpResponse(200, ok_body(cost=1e-9))] * 2)
    gw, _ = make(tmp_path, fake, Budget(max_cost_usd=0.000002, assumed_call_cost_usd=0.000001))
    gw.chat("p1", MSG)
    gw.chat("p1", MSG)
    assert gw.usage("p1")["charged_usd"] == 0.000002
    with pytest.raises(BudgetExceeded):
        gw.chat("p1", MSG)


# ---------------------------------------------------------------- review round 2: cost semantics, persisted reservation, cap rounding


def test_gateway_charge_is_the_larger_of_reported_and_assumed_and_overshoot_is_recorded(tmp_path):
    """cap $1.00, assumed $0.30: a call reported at $0.90 is charged $0.90 (> assumed), a call reported at $0.01 is charged the assumed $0.30."""
    fake = Fake(HttpResponse(200, ok_body(cost=0.01)), HttpResponse(200, ok_body(cost=0.90)), HttpResponse(200, ok_body(cost=0.90)))
    gw, _ = make(tmp_path, fake, Budget(max_cost_usd=1.0, assumed_call_cost_usd=0.30))
    a = gw.chat("p1", MSG)
    assert (a.cost_usd, a.charged_usd) == (0.01, 0.30)  # reported is below the least a call can cost: charge the assumption
    b = gw.chat("p1", MSG)  # remaining 0.70 >= 0.30 so it is sent; reported 0.90 -> charged 0.90, total 1.20
    assert b.charged_usd == 0.90
    rows = lines(tmp_path)
    assert rows[0]["overshoot_micro_usd"] == 0 and rows[1]["overshoot_micro_usd"] == 200000  # 1.20 - 1.00
    assert gw.usage("p1")["overshoot_usd"] == 0.2
    with pytest.raises(BudgetExceeded, match="cost cap reached"):  # spent >= cap: nothing more is sent
        gw.chat("p1", MSG)
    assert len(gw._transport.requests) == 2


def test_gateway_overshoot_is_at_most_reported_minus_assumed(tmp_path):
    """A call is only sent with remaining >= assumed, so total <= cap - assumed + reported, i.e. overshoot <= reported - assumed."""
    cap, assumed, reported = 1.0, 0.15, 0.80
    gw, _ = make(tmp_path, Fake(*[HttpResponse(200, ok_body(cost=reported))] * 5), Budget(max_cost_usd=cap, assumed_call_cost_usd=assumed))
    sent = 0
    while True:
        try:
            gw.chat("p1", MSG)
        except BudgetExceeded:
            break
        sent += 1
    spent = gw.usage("p1")["charged_usd"]
    assert sent == 2 and spent == pytest.approx(1.6)  # 0.80; remaining 0.20 >= 0.15 so a second call goes out (1.60); spent >= cap so no third
    assert spent - cap <= reported - assumed + 1e-9


def test_gateway_max_cost_is_rounded_down_to_micro_dollars_never_above_the_declared_cap(tmp_path):
    b = Budget(max_cost_usd=0.0000019, assumed_call_cost_usd=0.000001)
    assert b.max_cost_micro == 1  # 1.9 micro-dollars -> 1, not 2
    gw, _ = make(tmp_path, Fake(HttpResponse(200, ok_body(cost=None)), HttpResponse(200, ok_body(cost=None))), b)
    gw.chat("p1", MSG)  # remaining 1 >= assumed 1
    with pytest.raises(BudgetExceeded):  # rounding the cap up to 2 would have allowed this second call
        gw.chat("p1", MSG)
    assert Budget(max_cost_usd=0.30, assumed_call_cost_usd=0.10).max_cost_micro == 300000
    assert Budget(max_cost_usd=0.1 + 0.2, assumed_call_cost_usd=0.1).max_cost_micro == 300000  # 0.30000000000000004 -> 300000


def test_gateway_a_crash_between_send_and_settle_counts_the_reservation_as_spent(tmp_path):
    """Simulated crash: the transport kills the process before the settlement line is written."""
    b = Budget(max_cost_usd=0.50, assumed_call_cost_usd=0.20)

    class Crash(BaseException):
        pass

    gw, _ = make(tmp_path, Fake(HttpResponse(200, ok_body(cost=0.01))), b)
    gw._settle = lambda *a, **k: (_ for _ in ()).throw(Crash())  # the reply arrived, the process dies before recording it
    with pytest.raises(Crash):
        gw.chat("p1", MSG)
    on_disk = all_lines(tmp_path)
    assert [x["status"] for x in on_disk] == ["reserved"] and on_disk[0]["reserved_micro_usd"] == 200000
    gw2, _ = make(tmp_path, Fake(), b)  # restart
    u = gw2.usage("p1")
    assert u["calls"] == 1 and u["charged_usd"] == 0.20 and u["unknown_cost_calls"] == 1 and u["cost_left_usd"] == pytest.approx(0.30)
    gw2.chat("p1", MSG)  # 0.30 left >= 0.20
    with pytest.raises(BudgetExceeded):  # 0.20 + 0.20 charged, 0.10 left < 0.20
        gw2.chat("p1", MSG)


def test_gateway_reservation_line_is_written_before_the_request_is_sent(tmp_path):
    seen = {}

    def transport(req):
        seen["ledger"] = all_lines(tmp_path)
        return HttpResponse(200, ok_body())

    gw, _ = make(tmp_path, Fake(), Budget(max_cost_usd=1.0, assumed_call_cost_usd=0.1))
    gw._transport = transport
    gw.chat("p1", MSG)
    assert [x["status"] for x in seen["ledger"]] == ["reserved"]
    final = all_lines(tmp_path)
    assert [x["status"] for x in final] == ["reserved", "ok"] and final[0]["rid"] == final[1]["rid"]


def test_gateway_settled_reservation_is_not_counted_twice_on_restart(tmp_path):
    b = Budget(max_cost_usd=1.0, assumed_call_cost_usd=0.1)
    gw, _ = make(tmp_path, Fake(HttpResponse(200, ok_body(cost=0.25))), b)
    gw.chat("p1", MSG)
    gw2, _ = make(tmp_path, Fake(), b)
    assert gw2.usage("p1")["calls"] == 1 and gw2.usage("p1")["charged_usd"] == 0.25


def test_gateway_reservation_write_failure_sends_nothing_and_closes(tmp_path):
    gw, fake = make(tmp_path)
    gw._ledger.append = lambda entry: (_ for _ in ()).throw(OSError("read-only"))
    with pytest.raises(LedgerWriteError, match="nothing was sent"):
        gw.chat("p1", MSG)
    assert fake.requests == [] and gw.usage("p1")["calls"] == 0 and gw.usage("p1")["closed"] is True
