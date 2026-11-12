"""G-02c: the agent's run and verdict request tools. The agent may ask for a run or a verdict and read the answer; it can never
write one, and a request changes no document.

`uv run pytest packages/engine -q -k run_tools`

The project is one library plate of the catalog's aluminium resting on the ground of the earth, placed by the edit tools
(G-02a); the compiled model has its ground (X-01e). The judge below is a
test stand-in for J-01's (J-01d connects the real one): it returns what it was asked, never a probability, so no number here
reads as a verdict.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from pydantic import ValidationError

from kinetra_core import PLANET_CONSTANT_NAMES, Project, ReasonCode, RunCompleted, RunKind, VerdictState, project_hash
from kinetra_core.validator import VERDICT_FIELD_NAMES
from kinetra_engine.agent import RUN_LABEL, RUN_TOOL_NAMES, EditTools, HubEditTools, QueryTools, RunTools, Verdict, VerdictRequest, run_specs, summarize_rollout
from kinetra_engine.agent import run_tools as rt
from kinetra_engine.protocol import Document, Hub
from kinetra_engine.run import PreviewRun

PLATE = {"part": "plate", "material": "al6061-t6", "place": {"type": "on_ground"}}


def plate_project(**more) -> Project:
    result = EditTools().run(Project.model_validate({"world": {"planet": "earth"}}), "add_part", {**PLATE, **more})
    assert result.ok, result.reasons
    return result.project


class StandInJudge:
    """Records what it is asked and answers with it (no probability, no CI)."""

    def __init__(self):
        self.asked: list[VerdictRequest] = []

    def __call__(self, request: VerdictRequest):
        self.asked.append(request)
        return {"asked": {"revision": request.revision, "definition_hash": request.definition_hash, "seed": request.seed}, "notes": ["stand-in"]}


@pytest.fixture
def hub():
    return Hub({"car": plate_project()})


def state(hub: Hub):
    doc = hub.documents["car"]
    return doc.revision, doc.project, doc.history, doc.verdict


def _property_names(node, out: set[str]) -> set[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                out.update(value)
            _property_names(value, out)
    elif isinstance(node, list):
        for item in node:
            _property_names(item, out)
    return out


def test_run_tools_specs_are_function_tools_with_no_field_for_a_verdict_a_constant_or_the_kind_of_run():
    specs = run_specs()
    assert [s["function"]["name"] for s in specs] == list(RUN_TOOL_NAMES) == ["request_run", "request_verdict"]
    assert all(s["type"] == "function" and s["function"]["parameters"]["additionalProperties"] is False for s in specs)
    names = _property_names([s["function"]["parameters"] for s in specs], set())
    assert names == {"duration_s", "seed"}
    assert not names & (VERDICT_FIELD_NAMES | PLANET_CONSTANT_NAMES | {"kind", "origin", "badge"})


def test_run_tools_a_run_is_one_preview_of_the_document_as_it_is_and_never_a_verdict(hub):
    tools = RunTools(hub, "car")
    result = tools.call("request_run", '{"duration_s": 0.05, "seed": 3}')
    assert result.ok and result.reasons == ()
    doc = hub.documents["car"]
    run, first, last, ended = result.started, result.first_frame, result.last_frame, result.ended
    assert run.kind is RunKind.PREVIEW and run.badge == "sim" and run.seed == 3
    assert (run.project_id, run.revision, run.definition_hash) == ("car", doc.revision, project_hash(doc.project))
    assert first.tick == 0 and last.tick == ended.last_tick and isinstance(ended.end, RunCompleted)
    assert last.sim_time_s >= 0.05 and ended.end.trajectory.platform == run.platform
    # the same run computed directly: the tool adds nothing to the engine's stream
    direct = PreviewRun(doc.project, run_id="direct", project_id="car", revision=doc.revision, duration_s=0.05, seed=3)
    *frames, direct_end = list(direct)
    assert direct_end.end.trajectory.hash == ended.end.trajectory.hash
    assert frames[-1].poses == last.poses and frames[0].poses == first.poses
    assert run.model_labels == direct.started.model_labels
    assert not any("지면 없음" in label for label in run.model_labels)  # the model has its ground (X-01e)
    out = result.to_json()
    assert out["is_verdict"] is False and out["label"] == RUN_LABEL == "1회 실행. 판정이 아닙니다"
    assert out["run"]["started"]["kind"] == "preview" and "verdict" not in out and RUN_LABEL in out["summary"]
    json.dumps(out)


def test_run_tools_a_finished_run_records_its_whole_stream_in_the_shared_query_tools(hub, monkeypatch):
    # A bare UUID hex may start with a digit, which rollout_summary's run_id grammar rejects. Generated ids must remain queryable.
    monkeypatch.setattr(rt.uuid, "uuid4", lambda: uuid.UUID("00000000-0000-4000-8000-000000000001"))
    queries = QueryTools()
    result = RunTools(hub, "car", queries=queries).call("request_run", {"duration_s": 0.05, "seed": 3})
    assert result.ok

    # Recompute the same real engine stream, including frames that RunToolResult does not expose. The summary must be
    # exactly that stream's summary, not a reconstruction from only its first and last frames.
    direct = PreviewRun(
        hub.documents["car"].project,
        run_id=result.started.run_id,
        project_id="car",
        revision=result.revision,
        duration_s=0.05,
        seed=3,
        kind=RunKind.PREVIEW,
    )
    *frames, ended = list(direct)
    expected = summarize_rollout(direct.started, frames, ended)
    actual = queries.run(hub.documents["car"].project, "rollout_summary", {"run_id": result.started.run_id})
    assert actual.ok and actual.data == {**expected, "current_design": True}
    latest = queries.run(hub.documents["car"].project, "rollout_summary", {})
    assert latest.ok and latest.data == actual.data


def test_run_tools_a_request_reads_the_current_revision_and_changes_no_document(hub):
    edit = HubEditTools(hub, "car")
    assert edit.call("set_parameter", {"instance": "plate-1", "name": "thickness", "value": 0.01}).ok
    before = state(hub)
    assert before[0] == 1
    tools = RunTools(hub, "car", judge=StandInJudge())
    run = tools.call("request_run", {"duration_s": 0.01})
    verdict = tools.call("request_verdict", {})
    assert run.started.revision == run.revision == verdict.revision == verdict.verdict.revision == 1
    assert run.started.definition_hash == verdict.verdict.definition_hash == project_hash(hub.documents["car"].project)
    assert state(hub) == before  # no revision, no history entry, same project, same verdict state


def test_run_tools_an_edit_published_during_a_request_does_not_change_what_the_result_says_it_read(monkeypatch):
    """Revision, verdict state, run and verdict all belong to one snapshot taken before the engine or the judge starts. The
    document starts with a `valid` verdict state (as a J-01 verdict will leave it), so the edit during the request moves both
    its revision (0 -> 1) and its verdict state (valid -> invalid, D5)."""
    project = plate_project()
    hub = Hub({"car": project})
    hub.documents["car"] = Document("car", project, VerdictState.VALID)
    thickness = {"instance": "plate-1", "name": "thickness"}

    def edit(value: float) -> None:
        assert HubEditTools(hub, "car").call("set_parameter", {**thickness, "value": value}).ok

    class EditedMidRun(PreviewRun):
        def __iter__(self):
            for n, item in enumerate(super().__iter__()):
                if n == 1:
                    edit(0.01)  # published between two frames of the run
                yield item

    monkeypatch.setattr(rt, "PreviewRun", EditedMidRun)
    run = RunTools(hub, "car").call("request_run", {"duration_s": 0.05})
    doc = hub.documents["car"]
    assert (doc.revision, doc.verdict) == (1, VerdictState.INVALID)  # the edit happened, during the run
    assert (run.revision, run.verdict_state, run.started.revision) == (0, "valid", 0)
    assert run.started.definition_hash == project_hash(project) != project_hash(doc.project)
    assert run.to_json()["revision"] == 0 and run.to_json()["verdict_state"] == "valid"

    hub.documents["car"] = Document("car", project, VerdictState.VALID)

    def judge(request: VerdictRequest):
        edit(0.012)  # published while the judge works
        return {"asked": {"revision": request.revision}}

    verdict = RunTools(hub, "car", judge=judge).call("request_verdict", {})
    doc = hub.documents["car"]
    assert (doc.revision, doc.verdict) == (1, VerdictState.INVALID)
    assert (verdict.revision, verdict.verdict_state, verdict.verdict.revision) == (0, "valid", 0)
    assert verdict.verdict.definition_hash == project_hash(project) != project_hash(doc.project)



def test_run_tools_a_design_that_does_not_compile_or_a_run_too_long_is_refused_with_the_channels_reasons():
    hub = Hub({"bare": Project.model_validate({"world": {"planet": "earth"}}), "car": plate_project()})
    assert HubEditTools(hub, "bare").call("add_part", {"part": "plate", "place": {"type": "on_ground"}}).ok
    before = state(hub)
    refused = RunTools(hub, "bare").call("request_run", {"duration_s": 0.01})  # a plate with no material has no mass
    assert not refused.ok and refused.started is None and refused.ended is None
    (reason,) = refused.reasons
    assert reason.code is ReasonCode.INVALID_PROJECT and reason.message.startswith("part: the design does not compile: ")
    assert {(r.kind.value, r.id) for r in reason.ids} == {("instance", "plate-1"), ("part", "plate")}
    too_long = RunTools(hub, "car").call("request_run", {"duration_s": 1e300})
    assert not too_long.ok and [r.code for r in too_long.reasons] == [ReasonCode.INVALID_COMMAND] and "ticks" in too_long.reasons[0].message
    assert state(hub) == before


@pytest.mark.parametrize(
    ("tool", "arguments", "fragment"),
    [
        ("request_run", {}, "duration_s"),
        ("request_run", {"duration_s": "1"}, "duration_s"),
        ("request_run", {"duration_s": 0}, "duration_s"),
        ("request_run", '{"duration_s": NaN}', "duration_s"),
        ("request_run", {"duration_s": 1, "seed": -1}, "seed"),
        ("request_run", {"duration_s": 1, "seed": True}, "seed"),
        ("request_run", {"duration_s": 1, "kind": "verdict_sample"}, "kind"),
        ("request_verdict", {"samples": 10}, "samples"),
        ("request_verdict", "[1]", "JSON object"),
        ("request_verdict", "{", "not JSON"),
        ("request_verdict", "[" * 40 + "]" * 40, "deeper"),
        ("run_preview", {}, "unknown tool"),
    ],
)
def test_run_tools_a_bad_call_is_invalid_command_and_runs_nothing(hub, monkeypatch, tool, arguments, fragment):
    monkeypatch.setattr(rt, "PreviewRun", lambda *a, **k: pytest.fail("nothing may run"))
    judge = StandInJudge()
    result = RunTools(hub, "car", judge=judge).call(tool, arguments)
    assert not result.ok and result.reasons and judge.asked == []
    assert all(r.code is ReasonCode.INVALID_COMMAND for r in result.reasons)
    assert any(fragment in r.message for r in result.reasons)


WRITE_A_VERDICT = [
    ("set_verdict", {"verdict": "FEASIBLE_FOUND"}),
    ("write_p_success", {"p_success": 1.0}),
    ("update_verdict_state", {"state": "valid"}),
    ("request_verdict", {"verdict": {"kind": "FEASIBLE_FOUND"}}),
    ("request_verdict", {"p_success": 0.97}),
    ("request_verdict", {"seed": 1, "ci": [0.9, 1.0]}),
    ("request_verdict", {"confidenceInterval": [0.9, 1.0]}),
    ("request_verdict", {"result": {"verdict_state": "valid"}}),
    ("request_run", {"duration_s": 1, "verdictState": "valid"}),
    ("request_run", {"duration_s": 1, "kind": "verdict_sample", "P_Success": 1}),
]


@pytest.mark.parametrize(("tool", "arguments"), WRITE_A_VERDICT)
def test_run_tools_a_call_that_tries_to_write_a_verdict_is_refused_as_forbidden_and_changes_nothing(hub, monkeypatch, tool, arguments):
    monkeypatch.setattr(rt, "PreviewRun", lambda *a, **k: pytest.fail("nothing may run"))
    judge = StandInJudge()
    before = state(hub)
    for args in (arguments, json.dumps(arguments)):
        result = RunTools(hub, "car", judge=judge).call(tool, args)
        assert not result.ok and result.verdict is None and result.started is None
        assert ReasonCode.FORBIDDEN in {r.code for r in result.reasons}
        assert any("verdict" in r.message for r in result.reasons if r.code is ReasonCode.FORBIDDEN)
        assert result.to_json()["ok"] is False
    assert judge.asked == [] and state(hub) == before and hub.documents["car"].verdict is VerdictState.NONE


def test_run_tools_the_edit_path_cannot_write_a_verdict_either(hub):
    """The run tools are not edit tools (the edit path names them unknown), and a verdict cannot ride on an edit."""
    before = state(hub)
    thickness = {"instance": "plate-1", "name": "thickness", "value": 0.01}
    for tool, arguments in [*WRITE_A_VERDICT[:3], ("set_parameter", {**thickness, "p_success": 1.0}), ("set_parameter", {**thickness, "verdict": "valid"})]:
        result = HubEditTools(hub, "car").call(tool, arguments)
        assert not result.ok and ReasonCode.FORBIDDEN in {r.code for r in result.reasons}
    for tool in RUN_TOOL_NAMES:  # not an edit tool (`request_verdict` even reads as an attempt there, G-04's word list)
        result = HubEditTools(hub, "car").call(tool, {"duration_s": 1})
        assert not result.ok and result.command is None and result.reasons
    assert state(hub) == before


def test_run_tools_a_result_can_be_read_and_never_changed(hub):
    judge = StandInJudge()
    tools = RunTools(hub, "car", judge=judge)
    run = tools.call("request_run", {"duration_s": 0.01})
    verdict = tools.call("request_verdict", {"seed": 5})
    for result in (run, verdict):
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.ok = False  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.verdict = None  # type: ignore[misc]
    with pytest.raises(ValidationError):
        run.started.kind = RunKind.VERDICT_SAMPLE  # type: ignore[misc]
    with pytest.raises(ValidationError):
        run.ended.last_tick = 0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        run.last_frame.poses[0].position.z = 1.0  # type: ignore[misc]
    v = verdict.verdict
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.revision = 99  # type: ignore[misc]
    with pytest.raises(TypeError):
        v.content["p_success"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        v.content["asked"]["seed"] = 0  # type: ignore[index]
    assert isinstance(v.content["notes"], tuple)
    with pytest.raises(TypeError):
        Verdict("car", 0, "sha256:x", 0, {"p_success": 1.0})  # only a frozen judge's content makes a Verdict
    # the copy the model reads is a copy: changing it changes no verdict
    out = verdict.to_json()
    out["verdict"]["content"]["asked"]["seed"] = 0
    assert v.content["asked"]["seed"] == 5 and verdict.to_json()["verdict"]["content"]["asked"]["seed"] == 5


def test_run_tools_a_verdict_is_the_judges_on_the_document_and_the_judge_keeps_nothing_it_could_change(hub):
    seen = {}

    def judge(request: VerdictRequest):
        seen["answer"] = {"asked": {"seed": request.seed}, "notes": ["stand-in"]}
        seen["request"] = request
        return seen["answer"]

    result = RunTools(hub, "car", judge=judge).call("request_verdict", {"seed": 9})
    doc = hub.documents["car"]
    request = seen["request"]
    assert request.project == doc.project and (request.project_id, request.revision, request.seed) == ("car", doc.revision, 9)
    assert request.definition_hash == project_hash(doc.project) == result.verdict.definition_hash
    seen["answer"]["asked"]["seed"] = 0  # the judge's own dict, changed after the call
    assert result.verdict.content["asked"]["seed"] == 9
    out = result.to_json()
    assert out["ok"] is True and out["verdict"]["by"] == "core" and "is_verdict" not in out and out["verdict_state"] == "none"


def test_run_tools_without_a_judge_there_is_no_verdict_and_no_preview_in_its_place(hub, monkeypatch):
    monkeypatch.setattr(rt, "PreviewRun", lambda *a, **k: pytest.fail("a preview run is never a verdict"))
    before = state(hub)
    result = RunTools(hub, "car").call("request_verdict", {})
    assert not result.ok and result.verdict is None and result.started is None and result.reasons == ()
    assert "no verdict engine" in result.summary and "J-01" in result.summary
    assert result.to_json() == {"ok": False, "tool": "request_verdict", "summary": result.summary, "revision": 0, "verdict_state": "none"}
    assert state(hub) == before


@pytest.mark.parametrize("bad", [{1: "x"}, {"x": {1, 2}}, {"x": object()}])
def test_run_tools_a_judge_answer_that_is_not_json_data_is_not_a_verdict(bad):
    with pytest.raises(TypeError):
        rt.freeze(bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_run_tools_a_judge_answer_with_a_non_finite_number_is_not_a_verdict(hub, bad):
    with pytest.raises(ValueError, match="JSON numbers"):
        rt.freeze({"a": [{"b": bad}]})
    before = state(hub)
    with pytest.raises(ValueError, match="JSON numbers"):  # the core's own judge broke its contract: no verdict comes out
        RunTools(hub, "car", judge=lambda request: {"x": bad}).call("request_verdict", {})
    assert state(hub) == before


def test_run_tools_an_unknown_project_is_a_key_error(hub):
    with pytest.raises(KeyError):
        RunTools(hub, "nope")


def test_run_tools_the_frozen_content_is_json_after_a_round_trip():
    content = rt.freeze({"a": [1, 2.5, {"b": None, "c": True}], "d": "e"})
    assert rt._thaw(content) == {"a": [1, 2.5, {"b": None, "c": True}], "d": "e"}
