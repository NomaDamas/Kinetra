"""G-05: a failure explanation quotes only numbers of the run and of the checks; a reply with one number the data does not have is
thrown away whole. Offline: the gateway runs on a fake transport that answers from a script (no network, no real model), as in
`test_proposal`. The run is a real one: the tower of `test_break_runtime` whose weld breaks (X-04b) on the moon.

    uv run pytest packages/engine -q -k explain
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from test_break_runtime import G_MOON, TOP_KG, breakable_tower
from test_proposal import KEY, Script
from test_simulate_stream import run_of, split, tower

from kinetra_core import Project
from kinetra_engine.agent import (
    DISCARDED_NOTICE,
    EXPLANATION_LABEL,
    VERDICT_NOTICE,
    Explainer,
    QueryTools,
    check_numbers,
    evidence_of,
)
from kinetra_engine.gateway import Budget, Gateway, HttpRequest, TransportError
from kinetra_engine.run import PreviewRun


@pytest.fixture(autouse=True)
def core_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)


def explainer(script, max_calls: int = 5) -> Explainer:
    return Explainer(Gateway(default_model="m", budgets={"tower": Budget(max_calls=max_calls)}, transport=script))


@pytest.fixture(scope="module")
def broken():
    """The tower whose weld is set to 0.9 of the weight it holds: it breaks in the first ticks (`test_break_runtime`)."""
    project = breakable_tower(0.9 * TOP_KG * G_MOON)
    run = PreviewRun(project, run_id="run-1", project_id="tower", revision=3, duration_s=1.0)
    items = list(run)
    return project, run.started, items[:-1], items[-1]


def recorded(broken) -> tuple[Project, QueryTools, dict]:
    project, started, frames, ended = broken
    tools = QueryTools()
    tools.record(started, frames, ended)
    evidence, reasons = evidence_of(tools, project)
    assert reasons == () and evidence is not None
    return project, tools, evidence


def grounded_reply(evidence: dict) -> str:
    """Sentences quoting the data, rounded as a model would: the break (tick, load, threshold) and the static check."""
    brk = evidence["rollout_summary"]["breaks"][0]
    statics = evidence["statics_check"]
    return (
        f"틱 {brk['tick']}에서 결합 {brk['joint']}이 끊어졌습니다. "
        f"하중은 {brk['load']['value']:.2f} N이었고 파단 임계는 {brk['threshold']['value']:.3f} N입니다. "
        f"정역학 검사의 전복각은 {statics['tipover_angle_deg']:.1f}°이고 여유는 {statics['margin_m']:.2f} m입니다."
    )


def numbers_of(value) -> list[float]:
    """Every JSON number of `value` (booleans are not numbers), for the test's own check that a made-up number is not data."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [n for v in value.values() for n in numbers_of(v)]
    return [n for v in value for n in numbers_of(v)]


# --- the explanation quotes only the data ---------------------------------------------------------------------------------


def at(evidence: dict, path: str):
    """The value at a citation's `path` (`a.b[0].c`)."""
    value = evidence
    for key in path.replace("[", ".[").split("."):
        value = value[int(key[1:-1])] if key.startswith("[") else value[key]
    return value


def test_explain_quotes_only_numbers_of_the_run_and_the_checks(broken):
    project, tools, evidence = recorded(broken)
    assert evidence["rollout_summary"]["breaks"] and set(evidence) == {"rollout_summary", "statics_check", "mass_properties"}
    reply = grounded_reply(evidence)
    script = Script(reply)
    result = explainer(script).explain("tower", project, tools, "왜 무너졌어?")
    assert result.status == "explained" and result.ok and result.ungrounded == ()
    # the model was given the run summary and the checks the query tools return, and the question
    sent = script.requests[0]["messages"][-1]["content"]
    assert "왜 무너졌어?" in sent and json.loads(sent[sent.index("Data (JSON):\n") + len("Data (JSON):\n") :]) == evidence
    assert result.explanation.text == reply and result.explanation.removed == ()
    brk, statics = evidence["rollout_summary"]["breaks"][0], evidence["statics_check"]
    # every number shown is cited (tick, load, threshold, angle, margin), from a datum it is a rounding of
    assert [c.text for c in result.citations] == [str(brk["tick"]), f"{brk['load']['value']:.2f}", f"{brk['threshold']['value']:.3f}", f"{statics['tipover_angle_deg']:.1f}", f"{statics['margin_m']:.2f}"]
    # The same exact decimal rule as check_numbers: binary subtraction can exceed half a unit at an exact halfway value.
    assert all(
        at(evidence, c.path) == c.value
        and abs(abs(Decimal(repr(c.value))) - abs(Decimal(c.text)))
        <= Decimal("0.5") * Decimal(10) ** -len(c.text.partition(".")[2])
        for c in result.citations
    )
    by_path = {c.path: c for c in result.citations}
    assert by_path["rollout_summary.breaks[0].load.value"].value == brk["load"]["value"]
    assert by_path["rollout_summary.breaks[0].threshold.value"].value == brk["threshold"]["value"]
    assert result.citations[3].value == statics["tipover_angle_deg"]
    shown = result.to_json()
    assert shown["explanation"] == {"by": "agent", "is_verdict": False, "label": EXPLANATION_LABEL, "text": reply}
    assert shown["run_id"] == "run-1" and shown["sources"] == ["rollout_summary", "statics_check", "mass_properties"]
    assert [c["text"] for c in shown["citations"]] == [c.text for c in result.citations]


def test_explain_throws_away_a_reply_with_one_number_not_in_the_data(broken):
    project, tools, evidence = recorded(broken)
    threshold = evidence["rollout_summary"]["breaks"][0]["threshold"]["value"]
    invented = round(3 * threshold + 0.37, 2)  # a load the run never had
    assert all(abs(abs(n) - invented) > 0.005 for n in numbers_of(evidence))
    reply = grounded_reply(evidence) + f" 다음 실행에서는 {invented:.2f} N까지 걸립니다."
    result = explainer(Script(reply)).explain("tower", project, tools)
    assert result.status == "discarded" and result.explanation is None and result.citations == ()
    assert result.ungrounded == (f"{invented:.2f}",) and result.message == DISCARDED_NOTICE and result.reply == reply
    shown = result.to_json()
    assert shown == {"status": "discarded", "message": DISCARDED_NOTICE, "run_id": "run-1", "sources": ["rollout_summary", "statics_check", "mass_properties"], "ungrounded": 1}
    assert "끊어졌습니다" not in json.dumps(shown, ensure_ascii=False)  # not even the grounded sentences are shown


def test_explain_a_number_of_the_question_is_not_data(broken):
    project, tools, evidence = recorded(broken)
    assert all(abs(abs(n) - 3.5) > 0.05 for n in numbers_of(evidence))
    result = explainer(Script("3.5 m 높이에서 떨어진 것이 아닙니다.")).explain("tower", project, tools, "3.5 m 높이에서 떨어졌어?")
    assert result.status == "discarded" and result.ungrounded == ("3.5",)


def test_explain_label_rules_of_g03a_apply_and_a_made_up_number_in_a_removed_sentence_still_discards(broken):
    project, tools, evidence = recorded(broken)
    load = evidence["rollout_summary"]["breaks"][0]["load"]["value"]
    claim = f"하중 {load:.2f} N을 줄이면 통과합니다."  # verdict-like (G-03a filter), with a grounded number
    result = explainer(Script(grounded_reply(evidence) + " " + claim)).explain("tower", project, tools)
    assert result.status == "explained" and result.explanation.removed == (claim,)
    assert result.explanation.text == grounded_reply(evidence) and len(result.citations) == 5
    shown = result.to_json()["explanation"]
    assert shown["is_verdict"] is False and shown["label"] == EXPLANATION_LABEL and shown["notice"] == VERDICT_NOTICE
    # the same claim with a number of its own: the number check reads the whole reply before the filter
    made_up = "보강하면 확률 97%로 통과합니다."
    assert all(abs(abs(n) - 97) > 0.5 for n in numbers_of(evidence))
    result = explainer(Script(grounded_reply(evidence) + " " + made_up)).explain("tower", project, tools)
    assert result.status == "discarded" and result.ungrounded == ("97",)


# --- the number check -----------------------------------------------------------------------------------------------------


DATA = {
    "run": {"load": {"value": 5.832000000000001, "unit": "N"}, "margin_m": -0.08, "stable": True, "hash": "sha256:30c7"},
    "run_id": "plate-1",
}


@pytest.mark.parametrize(
    ("text", "ungrounded"),
    [
        ("5.832 N", ()),  # as it is
        ("5.83 N, 5.8 N, 6 N", ()),  # rounded to the decimals written
        ("5.832e0 N", ()),
        ("5.84 N", ("5.84",)),  # not a rounding of 5.832
        ("5.9 N", ("5.9",)),
        ("여유 -0.08 m, 0.08 m 모자람", ()),  # the size of a negative datum may be written unsigned
        ("-5.83 N", ("-5.83",)),  # a minus sign written must be the datum's
        ("8 cm", ("8",)),  # no unit conversion: 0.08 m is not 8
        ("1", ("1",)),  # a boolean is not a number
        ("hash sha256:30c7, 30", ()),  # a number inside a string of the data (sha256:30c7) is data
        ("plate-1, run-2, X-02d, al6061, sha256", ()),  # digits of an id are part of the id
        ("틱25", ("25",)),  # digits after Hangul are a number
    ],
)
def test_explain_number_check(text, ungrounded):
    cited, missing = check_numbers(text, DATA)
    assert missing == ungrounded
    assert all(c.path in {"run.load.value", "run.margin_m", "run.hash"} for c in cited)


def test_explain_number_check_cites_the_closest_datum_and_its_path():
    cited, missing = check_numbers("0.1 m와 0.12 m", {"a": [0.1234, 0.1], "b": {"c": 0.12}})
    assert missing == () and [(c.text, c.path, c.value) for c in cited] == [("0.1", "a[1]", 0.1), ("0.12", "b.c", 0.12)]


@pytest.mark.parametrize("written", ["1e999", "9e999", "-1e999", "1E+999", "1e-999", "0e999", "1" + "0" * 500])
def test_explain_a_number_too_large_or_small_for_any_datum_is_never_cited(written):
    """`float("1e999")` is infinity: such a number is not one value (`MAX_EXPONENT`), whatever the data holds."""
    data = {"max": 1.7976931348623157e308, "tiny": 5e-324, "zero": 0.0, "one": 1.0}
    assert check_numbers(f"하중 {written} N", data) == ((), (written,))
    result = Explainer.check(f"하중은 {written} N이었습니다.", {"rollout_summary": {"run_id": "run-1", **data}})
    assert result.status == "discarded" and result.ungrounded == (written,) and result.explanation is None


def test_explain_the_largest_and_smallest_doubles_are_still_cited_exactly():
    data = {"max": 1.7976931348623157e308, "tiny": 5e-324, "huge_int": 10**400}  # an int no double can hold is not a datum
    cited, missing = check_numbers("1.8e308, 9e308, 5e-324, 4.9e-324, 1e400", data)
    assert missing == ("9e308", "4.9e-324", "1e400") and [(c.text, c.path) for c in cited] == [("1.8e308", "max"), ("5e-324", "tiny")]
    assert [c.value for c in cited] == [data["max"], data["tiny"]]


@pytest.mark.parametrize(
    ("text", "data", "ungrounded"),
    [
        (".5 m", {"a": 0.5}, ()),  # a leading decimal point is kept: .5 is 0.5
        (".5 m", {"a": 5}, (".5",)),  # and never 5
        ("-.25 m", {"a": -0.25}, ()),
        ("-.25 m", {"a": 25, "b": 0.25}, ("-.25",)),  # neither 25 nor the positive 0.25
        ("높이 .5e1 m", {"a": 5}, ()),
        ("v.5", {"a": 0.5}, ()),  # digits continuing an ASCII name are not a number
    ],
)
def test_explain_a_leading_decimal_point_is_part_of_the_number(text, data, ungrounded):
    assert check_numbers(text, data)[1] == ungrounded


@pytest.mark.parametrize(
    ("written", "datum", "cited"),
    [
        ("1.23", 1.2349, True),  # rounds to 1.23
        ("1.23", 1.2351, False),  # rounds to 1.24: no tolerance past half a unit of the last digit
        ("1.23", 1.225, True),  # halfway (the JSON text 1.225): either way
        ("1.23", 1.235, True),
        ("1.23", 1.2350001, False),
        ("1.23", 1.2249999, False),
        ("0.15", 0.145, True),  # the data as the model reads it (repr 0.145, halfway), not the binary 0.14499…
        ("0.14", 0.145, True),
        ("2e3", 2499.0, True),  # rounded to thousands
        ("2e3", 2500.5, False),
    ],
)
def test_explain_rounding_is_exact_to_half_a_unit_of_the_last_digit_written(written, datum, cited):
    got, missing = check_numbers(written, {"d": datum})
    assert ([(c.path, c.value) for c in got], missing) == (([("d", datum)], ()) if cited else ([], (written,)))


@pytest.mark.parametrize(
    ("text", "data", "cited", "ungrounded"),
    [
        ("하중 1,234 N", {"n": 1234}, [("1,234", 1234.0)], ()),  # thousands grouping: one number
        ("하중 1,234 N", {"a": 1, "b": 234}, [], ("1,234",)),  # not the numbers 1 and 234
        ("틱 1, 234", {"a": 1, "b": 234}, [("1", 1.0), ("234", 234.0)], ()),  # a list written with spaces
        ("1,234.5 N", {"n": 1234.5}, [("1,234.5", 1234.5)], ()),
        ("1,234.5 N", {"a": 1, "b": 234.5}, [], ("1,234.5",)),
        ("12,345,678 N", {"n": 12345678}, [("12,345,678", 12345678.0)], ()),
        ("1,234 N", {"n": 1234.4}, [("1,234", 1234.4)], ()),  # rounded like any number
        ("-1,234 N", {"n": 1234}, [], ("-1,234",)),
        ("틱 2,3", {"a": 2, "b": 3, "c": 23, "d": 2.3}, [], ("2,3",)),  # a list, 23 or 2.3: not one value, never cited
        ("1,23,456 N", {"n": 123456}, [], ("1,23,456",)),  # not thousands grouping
        ("1.234.567 N", {"a": 1.234, "b": 567, "c": 1234567}, [], ("1.234.567",)),  # dots as grouping, or a version: not one value
    ],
)
def test_explain_commas_and_dots_between_digits(text, data, cited, ungrounded):
    got, missing = check_numbers(text, data)
    assert [(c.text, c.value) for c in got] == cited and missing == ungrounded


# --- nothing to explain, and the gateway ------------------------------------------------------------------------------------


def test_explain_without_a_recorded_run_does_not_ask_the_model():
    script = Script()
    result = explainer(script).explain("tower", tower(), QueryTools())
    assert result.status == "no_run" and script.requests == [] and [r.code.value for r in result.reasons] == ["unknown_id"]
    assert "explanation" not in result.to_json()


def test_explain_a_check_the_core_cannot_compute_is_named_not_made_up():
    run = run_of(tower(), duration_s=0.05)
    tools = QueryTools()
    tools.record(run.started, *split(run))
    empty = Project.model_validate({"world": {"planet": "moon"}})  # the design changed to one that does not compile
    evidence, _ = evidence_of(tools, empty)
    assert set(evidence) == {"rollout_summary", "unavailable"} and evidence["rollout_summary"]["current_design"] is False
    assert evidence["unavailable"] == {"statics_check": ["invalid_project"], "mass_properties": ["invalid_project"]}


def test_explain_an_empty_reply_is_discarded(broken):
    _, _, evidence = recorded(broken)
    result = Explainer.check("  \n", evidence)  # the gateway refuses an empty answer itself; a reply of blanks is still no explanation
    assert result.status == "discarded" and result.explanation is None and result.ungrounded == ()


def test_explain_budget_and_gateway_errors_end_it(broken):
    project, tools, evidence = recorded(broken)
    result = explainer(Script(grounded_reply(evidence)), max_calls=0).explain("tower", project, tools)
    assert result.status == "budget_exceeded" and result.explanation is None

    def down(req: HttpRequest):
        raise TransportError("connection refused")

    result = explainer(down).explain("tower", project, tools)
    assert result.status == "gateway_error" and "connection refused" in result.message and result.explanation is None
