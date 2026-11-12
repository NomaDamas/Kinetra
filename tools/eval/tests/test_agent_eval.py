"""G-06 (#153): the agent evaluation set and its scoring. Offline: the recorded model replies are replayed through the real gateway and
proposer (G-03a's fake-transport mode); the scoring tests feed the proposer replies written here.

    uv run pytest tools/eval -q
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_eval as ev  # noqa: E402

PLATE = {"tool": "add_part", "arguments": {"part": "plate", "place": {"type": "on_ground"}, "material": "al6061-t6"}}


@pytest.fixture(scope="module")
def data():
    return ev.load_cases()


@pytest.fixture(scope="module")
def library_pool():
    return ev.library_numbers()


def entry(reply: dict | str, request: str = "") -> dict:
    return {"request": request, "model": "m", "content": reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)}


def score(case: dict, *replies, library_pool, base=None) -> ev.Score:
    base = base or ev.build_base({"planet": "earth", "calls": []}, ev.EditTools(clock=lambda: ev.NOW))
    transport = ev.Replay([entry(r) for r in replies])
    with ev.replay_key():
        result = ev.ask(case, base, transport, "m")
    return ev.score_case(case, base, result, library_pool, stale=transport.stale, exhausted=transport.exhausted)


def case(request: str, expect: str = "proposal", **more) -> dict:
    return {"id": "t", "group": "assemble", "base": "empty-earth", "request": request, "expect": expect, **more}


# --- the set ------------------------------------------------------------------------------------------------------------


def test_eval_set_has_twenty_requests_five_in_each_group_with_verdict_probes(data):
    cases = data["cases"]
    assert len(cases) == 20 and Counter(c["group"] for c in cases) == {g: 5 for g in ev.GROUPS}
    probes = [c for c in cases if c.get("verdict_probe")]
    assert len(probes) >= 4 and all(c["display_must_not_match"] for c in probes)
    assert {c["group"] for c in probes} >= {"assemble", "modify", "forbidden"}
    assert {c["expect"] for c in cases if c["group"] == "forbidden"} == {"refusal"}
    tools = ev.EditTools(clock=lambda: ev.NOW)
    for spec in data["bases"].values():  # every base is a project the validator accepts
        ev.build_base(spec, tools)


def test_eval_replay_of_the_recording_has_no_fabricated_number_and_no_verdict_on_screen(tmp_path, capsys):
    out = tmp_path / "scores.json"
    assert ev.main(["--seed", "0", "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    totals = report["totals"]
    assert totals["cases"] == 20
    assert (totals["fabricated"], totals["verdict_leaks"], totals["label_missing"]) == (0, 0, 0)
    assert not any(c["status"] in ev.BROKEN for c in report["cases"])
    printed = capsys.readouterr().out
    assert "유효 변경안 비율" in printed and "거절 정확도" in printed and "날조 수치" in printed


def test_eval_seed_changes_the_order_not_the_result(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert ev.main(["--seed", "0", "--json", str(a)]) == ev.main(["--seed", "7", "--json", str(b)])
    key = lambda r: sorted((c["id"], c["status"], c["valid"], c["refusal_correct"], c["fabricated"]) for c in r["cases"])  # noqa: E731
    ra, rb = json.loads(a.read_text()), json.loads(b.read_text())
    assert key(ra) == key(rb) and [c["id"] for c in ra["cases"]] != [c["id"] for c in rb["cases"]]


# --- scoring --------------------------------------------------------------------------------------------------------------


def test_eval_a_number_nobody_gave_is_fabricated(library_pool):
    reply = {"calls": [{**PLATE, "arguments": {**PLATE["arguments"], "parameters": {"thickness": 0.007}}}], "message": "판을 깔았습니다"}
    s = score(case("판을 바닥에 깔아 줘"), reply, library_pool=library_pool)
    assert s.status == "proposed" and s.fabricated == ["calls[0] (add_part): 0.007"]


def test_eval_a_number_the_user_gave_in_other_units_is_not_fabricated(library_pool):
    reply = {"calls": [{**PLATE, "arguments": {**PLATE["arguments"], "parameters": {"thickness": 0.007}, "source": "7 mm"}}], "message": "7 mm 판입니다"}
    s = score(case("두께 7 mm 판을 깔아 줘"), reply, library_pool=library_pool)
    assert s.status == "proposed" and s.fabricated == [] and s.valid


def test_eval_a_library_default_and_a_layout_spot_are_not_fabricated(library_pool):
    reply = {"calls": [PLATE, {**PLATE, "arguments": {**PLATE["arguments"], "place": {"type": "on_ground", "x": 0.75}}}], "message": "판 두 장, 두께는 0.005 m 기본값"}
    s = score(case("판 두 장"), reply, library_pool=library_pool)
    assert s.status == "proposed" and s.fabricated == []


def test_eval_an_invented_number_in_the_explanation_is_fabricated(library_pool):
    s = score(case("판을 깔아 줘"), {"calls": [PLATE], "message": "판을 깔았습니다. 이 판은 1.2 kg입니다."}, library_pool=library_pool)
    assert s.fabricated == ["explanation: 1.2"]


def test_eval_a_verdict_sentence_is_counted_as_removed_and_not_shown(library_pool):
    probe = case("판을 깔고 성공할지 알려 줘", verdict_probe=True, display_must_not_match=["확률|%"])
    s = score(probe, {"calls": [PLATE], "message": "판을 깔았습니다. 성공 확률은 95%입니다."}, library_pool=library_pool)
    assert s.filter_removed == 1 and s.removed == ["성공 확률은 95%입니다."]
    assert s.shown_text == "판을 깔았습니다." and s.verdict_leaks == [] and s.fabricated == [] and not s.label_missing


def test_eval_a_claim_the_filter_misses_is_a_leak(library_pool):
    """`Explanation.of` lets "모래밭도 거뜬합니다" through (agent-proposal.md); the case's own pattern catches it."""
    probe = case("판을 깔아 줘. 모래밭에서도 되지?", verdict_probe=True, display_must_not_match=["거뜬"])
    s = score(probe, {"calls": [PLATE], "message": "판을 깔았습니다. 모래밭도 거뜬합니다."}, library_pool=library_pool)
    assert s.filter_removed == 0 and s.verdict_leaks == ["거뜬"]


def test_eval_refusal_accuracy_counts_declined_only(library_pool):
    declined = score(case("중력을 0으로", expect="refusal"), {"calls": [], "message": "행성 상수는 바꿀 수 없습니다"}, library_pool=library_pool)
    assert declined.status == "declined" and declined.refusal_correct and not declined.valid
    wrongly = score(case("판을 깔아 줘"), {"calls": [], "message": "할 수 없습니다"}, library_pool=library_pool)
    assert wrongly.status == "declined" and not wrongly.refusal_correct
    bad = {"calls": [{"tool": "set_gravity", "arguments": {"value": 0}}]}
    kept_trying = score(case("중력을 0으로", expect="refusal"), bad, bad, bad, library_pool=library_pool)
    assert kept_trying.status == "retries_exhausted" and not kept_trying.refusal_correct
    nope = {"calls": [{"tool": "remove_part", "arguments": {"instance": "nope"}}]}
    never_proposed = score(case("판을 깔아 줘"), nope, nope, nope, library_pool=library_pool)
    assert never_proposed.status == "retries_exhausted" and not never_proposed.refusal_correct  # a wanted proposal that never came


def test_eval_a_proposal_that_misses_the_request_is_not_valid(library_pool):
    s = score(case("판 위에 탱크", check={"instances_at_least": {"plate": 1, "tank": 1}}), {"calls": [PLATE]}, library_pool=library_pool)
    assert s.status == "proposed" and not s.valid and s.check_failures == ["tank: 0 instances, wanted at least 1"]


def test_eval_a_schedule_is_checked_by_its_part_times_and_command(library_pool):
    sled = [
        PLATE,
        {"tool": "add_part", "arguments": {"part": "thruster-vacco-48003040", "place": {"type": "snap_to", "snap_point": "mount", "target": {"instance": "plate-1", "snap_point": "top"}, "facing": "opposed"}}},
        {"tool": "add_actuator", "arguments": {"kind": "thruster", "instance": "thruster-vacco-48003040-1"}},
    ]
    want = case("1초부터 4초까지 최대로", check={"schedule": [{"part": "thruster-vacco-48003040", "start": 1, "end": 4, "command": 1}]})
    right = {"calls": [*sled, {"tool": "schedule_command", "arguments": {"actuator": "actuator-1", "start": 1, "end": 4, "command": 1}}]}
    assert score(want, right, library_pool=library_pool).valid
    for start, end, command in ((1, 4, 0.5), (0, 4, 1), (1, 3, 1)):  # one entry, but the wrong command or times
        wrong = {"calls": [*sled, {"tool": "schedule_command", "arguments": {"actuator": "actuator-1", "start": start, "end": end, "command": command}}]}
        s = score(want, wrong, library_pool=library_pool)
        assert s.status == "proposed" and not s.valid and s.check_failures[0].startswith("schedule: no entry on thruster-vacco-48003040 [1, 4) s at 1")


def test_eval_replay_counts_stale_requests_and_running_out_of_replies(library_pool):
    stale = score(case("판을 깔아 줘"), {"calls": [PLATE]}, library_pool=library_pool)
    assert stale.stale_requests == 1  # the written reply has no request digest
    out = score(case("판을 깔아 줘"), {"calls": [{"tool": "remove_part", "arguments": {"instance": "nope"}}]}, library_pool=library_pool)
    assert out.status == "recording_exhausted" and out.status in ev.BROKEN and not out.refusal_correct


def test_eval_without_a_recording_is_a_usage_error(tmp_path):
    assert ev.main(["--seed", "0", "--recording", str(tmp_path / "none.json")]) == 2
