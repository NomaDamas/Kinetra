"""C-05b: the run stream frame format (`kinetra_core.frames`; `client-adapter.md` 3.3 and 3.3.1).

    uv run pytest packages/engine -q -k frame
"""

from __future__ import annotations

import copy
import json
import re
import struct
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

import kinetra_core
from kinetra_core import (
    BINARY_BODY_BYTES,
    BINARY_HEADER_BYTES,
    Frame,
    FrameDecodeError,
    PlatformTag,
    RunEnded,
    RunStarted,
    ServerMessage,
    binary_frame_size,
    check_frame,
    check_run,
    decode_frame,
    encode_frame,
)

import frame_fixture

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "frames"
SERVER = TypeAdapter(ServerMessage)

PLATFORM_COMPONENTS = ["os", "cpu", "image_digest", "engine", "runtime", "core_build", "compute", "threads"]


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def recorded() -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / "run.jsonl").read_text(encoding="utf-8").splitlines()]


def started() -> dict:
    return copy.deepcopy(recorded()[0])


def without(data: dict, *path: str) -> dict:
    data = copy.deepcopy(data)
    cur = data
    for k in path[:-1]:
        cur = cur[k]
    del cur[path[-1]]
    return data


def schema_ok(name: str, data) -> bool:
    return not list(validator(name).iter_errors(data))


# --- the recorded fixture -----------------------------------------------------------------------------------


def test_the_committed_fixture_is_what_the_generator_writes():
    for name, data in frame_fixture.build().items():
        assert (FIXTURES / name).read_bytes() == data, f"{name} is stale: run packages/engine/tests/frame_fixture.py"


def test_every_recorded_message_validates_against_the_schema_and_the_model():
    messages = recorded()
    assert [m["type"] for m in messages][:1] == ["run_started"] and messages[-1]["type"] == "run_ended"
    assert {m["type"] for m in messages[1:-1]} == {"frame"} and len(messages) > 10
    for m in messages:
        name = {"run_started": "RunStarted", "frame": "Frame", "run_ended": "RunEnded"}[m["type"]]
        assert list(validator(name).iter_errors(m)) == [], m["type"]
        assert list(validator("ServerMessage").iter_errors(m)) == [], m["type"]
        assert SERVER.validate_python(m).type == m["type"]


def stream():
    messages = recorded()
    return (
        RunStarted.model_validate(messages[0]),
        [Frame.model_validate(m) for m in messages[1:-1]],
        RunEnded.model_validate(messages[-1]),
    )


def test_the_recorded_run_is_internally_consistent():
    run, frames, ended = stream()
    check_run(run, frames, ended)
    grid = [f.tick for f in frames[:-1]]
    assert grid == list(range(0, grid[-1] + 1, run.frame_every_ticks))
    kinds = {e.kind for f in frames for e in f.events}
    assert kinds == {"contact", "condition_met", "break"}  # the three event kinds of the DoD
    assert ended.last_tick == frames[-1].tick and ended.end.trajectory.platform == run.platform


def test_a_run_that_ends_between_intervals_sends_a_last_frame_with_the_rest_of_its_events():
    """The fixture ends at tick 130, between the frames of 128 and 136: the core sends a frame at 130, off the grid,
    and the break of tick 129 is in it. Without that frame the client would never see the break or the end pose."""
    run, frames, ended = stream()
    last = frames[-1]
    assert last.tick % run.frame_every_ticks and last.tick == ended.last_tick
    assert [e.kind for e in last.events] == ["break"] and frames[-2].tick < last.events[0].tick <= last.tick
    with pytest.raises(ValueError, match="multiple"):
        check_frame(run, last)  # off the grid: only the final frame may be
    check_frame(run, last, final=True)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda f, e: (f[:-1], e), "last_tick"),  # the final frame was not sent
        (lambda f, e: (f, e.model_copy(update={"last_tick": e.last_tick + 1})), "last_tick"),
        (lambda f, e: ([], e), "at least one frame"),
        (lambda f, e: (f[:3] + [f[5]] + f[3:5] + f[6:], e), "increase"),
        (lambda f, e: (f, e.model_copy(update={"run_id": "other"})), "run_ended of run"),
    ],
)
def test_check_run_refuses_a_stream_without_its_end_frame_or_out_of_order(change, message):
    run, frames, ended = stream()
    frames, ended = change(frames, ended)
    with pytest.raises(ValueError, match=message):
        check_run(run, frames, ended)


def test_check_run_accepts_a_skipped_frame_whose_events_move_to_the_next():
    """A sender may skip a frame under load (frames are full states); the skipped frame's events go in the next one."""
    run, frames, ended = stream()
    contact = next(i for i, f in enumerate(frames) if any(e.kind == "contact" for e in f.events))
    moved = frames[contact + 1].model_copy(update={"events": frames[contact].events + frames[contact + 1].events})
    check_run(run, frames[:contact] + [moved] + frames[contact + 2 :], ended)


def test_check_run_refuses_an_event_sent_twice_or_a_middle_frame_off_the_grid():
    run, frames, ended = stream()
    contact = next(i for i, f in enumerate(frames) if any(e.kind == "contact" for e in f.events))
    again = frames[contact + 1].model_copy(update={"events": frames[contact].events})
    with pytest.raises(ValueError, match="earlier frame"):
        check_run(run, frames[: contact + 1] + [again] + frames[contact + 2 :], ended)
    off = frames[2].model_copy(update={"tick": frames[2].tick + 1, "sim_time_s": (frames[2].tick + 1) * run.timestep_s})
    with pytest.raises(ValueError, match="multiple"):
        check_run(run, frames[:2] + [off] + frames[3:], ended)


def test_an_event_is_in_the_frame_that_follows_it_and_never_in_two():
    frames = [Frame.model_validate(m) for m in recorded()[1:-1]]
    events = [(f.tick, e) for f in frames for e in f.events]
    assert all(e.tick <= t for t, e in events)
    assert len({e.model_dump_json() + str(e.tick) for _, e in events}) == len(events)  # no event repeated in a later frame
    contacts = [e for _, e in events if e.kind == "contact"]
    assert len(contacts) == 4 and {e.tick for e in contacts} == {frame_fixture.CONTACT_TICK}


def test_the_examples_are_the_recorded_messages():
    run = json.loads((SCHEMAS / "examples" / "RunStarted.four-wheel-car.json").read_text(encoding="utf-8"))
    assert RunStarted.model_validate(run) == RunStarted.model_validate(recorded()[0])
    ended = json.loads((SCHEMAS / "examples" / "RunEnded.completed.json").read_text(encoding="utf-8"))
    assert RunEnded.model_validate(ended) == RunEnded.model_validate(recorded()[-1])


# --- no engine words (F1, G2) -------------------------------------------------------------------------------

ENGINE_WORDS = re.compile(r"\b(qpos|qvel|geom|mjcf|mjmodel|mjdata|xpos|xquat|ncon|eq_|site|body_id)\b|mujoco", re.I)


def test_no_engine_term_in_the_frame_schemas_or_the_recorded_messages():
    """The engine is a *value* of the platform tag (`engine.name`), nowhere a field name or a type name."""
    for name in ("RunStarted", "Frame", "RunEnded", "ContactEvent", "BreakEvent", "ConditionMetEvent", "PlatformTag"):
        text = (SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8")
        assert ENGINE_WORDS.search(text) is None, (name, ENGINE_WORDS.search(text))
    for m in recorded():
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                keys.update(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(m)
        assert not [k for k in keys if ENGINE_WORDS.search(k)], keys
    # the field names of the models, too
    for cls in (RunStarted, Frame, RunEnded, PlatformTag, kinetra_core.WheelEngine, kinetra_core.WasmEngine, kinetra_core.CustomBuildEngine):
        assert not [n for n in cls.model_fields if ENGINE_WORDS.search(n)], cls


# --- the platform tag (A0-05) -------------------------------------------------------------------------------


def test_the_platform_tag_has_the_eight_components_of_the_decision_table():
    assert list(PlatformTag.model_fields) == PLATFORM_COMPONENTS
    schema = json.loads((SCHEMAS / "PlatformTag.schema.json").read_text(encoding="utf-8"))
    assert schema["required"] == PLATFORM_COMPONENTS  # all required, including a null image digest
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("component", PLATFORM_COMPONENTS)
def test_a_run_started_without_a_platform_tag_component_fails_schema_validation(component):
    data = without(started(), "platform", component)
    assert not schema_ok("RunStarted", data)
    assert not schema_ok("ServerMessage", data)
    with pytest.raises(ValidationError):
        RunStarted.model_validate(data)


def test_a_run_started_without_a_platform_tag_fails_schema_validation():
    """The DoD test: the whole tag missing."""
    data = without(started(), "platform")
    assert not schema_ok("RunStarted", data)
    with pytest.raises(ValidationError):
        RunStarted.model_validate(data)
    with pytest.raises(ValidationError):
        SERVER.validate_python(data)


def test_a_null_platform_tag_fails_too():
    data = started()
    data["platform"] = None
    assert not schema_ok("RunStarted", data)
    with pytest.raises(ValidationError):
        RunStarted.model_validate(data)


def test_no_image_is_an_explicit_null_not_an_omission():
    data = started()
    assert data["platform"]["image_digest"] is None and schema_ok("RunStarted", data)
    data["platform"]["image_digest"] = "sha256:" + "a" * 64
    assert schema_ok("RunStarted", data) and RunStarted.model_validate(data).platform.image_digest is not None
    data["platform"]["image_digest"] = "latest"
    assert not schema_ok("RunStarted", data)


def test_the_tag_refuses_a_component_it_does_not_know_and_a_false_tag_equality():
    data = started()
    data["platform"]["gpu"] = {"model": "x"}
    assert not schema_ok("RunStarted", data)
    with pytest.raises(ValidationError):
        RunStarted.model_validate(data)
    a, b = RunStarted.model_validate(started()), RunStarted.model_validate(started())
    assert a.platform == b.platform
    other = started()
    other["platform"]["threads"]["physics"] = 2
    assert RunStarted.model_validate(other).platform != a.platform  # one component differs: another tag (H1)


ENGINES = {
    "wheel": {"name": "any-engine", "version": "1.2.3", "distribution": "wheel", "artifact_hash": "sha256:" + "b" * 64},
    "wasm_package": {"name": "any-engine", "version": "1.2.3", "distribution": "wasm_package", "artifact_hash": "sha256:" + "b" * 64},
    "custom_build": {"name": "any-engine", "version": "1.2.3", "distribution": "custom_build", "compiler": "cc 1", "build_flags": ""},
}


def with_engine(engine: dict) -> dict:
    data = started()
    data["platform"]["engine"] = engine
    return data


def test_the_engine_is_named_by_value():
    engine = started()["platform"]["engine"]
    assert set(engine) >= {"name", "version", "distribution"}
    for distribution, engine in ENGINES.items():
        assert schema_ok("RunStarted", with_engine(engine)), distribution
        assert RunStarted.model_validate(with_engine(engine)).platform.engine.distribution == distribution


@pytest.mark.parametrize(
    ("distribution", "change"),
    [
        ("wheel", {"artifact_hash": KeyError}),
        ("wheel", {"artifact_hash": None}),
        ("wasm_package", {"artifact_hash": KeyError}),
        ("wasm_package", {"artifact_hash": None}),
        ("custom_build", {"compiler": KeyError}),
        ("custom_build", {"compiler": None}),
        ("custom_build", {"build_flags": KeyError}),
        ("custom_build", {"build_flags": None}),
        ("wheel", {"distribution": "docker"}),
        ("wheel", {"artifact_hash": "latest"}),
    ],
)
def test_the_engine_tag_conditional_rule_is_in_the_schema_and_the_model_alike(distribution, change):
    """What the model refuses the JSON Schema refuses too (a schema-only client checks the same rule)."""
    engine = dict(ENGINES[distribution])
    for key, value in change.items():
        if value is KeyError:
            del engine[key]
        else:
            engine[key] = value
    data = with_engine(engine)
    assert not schema_ok("RunStarted", data)
    assert not schema_ok("PlatformTag", data["platform"])
    with pytest.raises(ValidationError):
        RunStarted.model_validate(data)


def test_the_fields_of_another_distribution_do_not_substitute():
    """A wheel with a compiler and flags but no file hash is not identified; a custom build with a hash but no
    compiler is not either."""
    wheel = {k: v for k, v in ENGINES["custom_build"].items() if k != "distribution"} | {"distribution": "wheel"}
    custom = {k: v for k, v in ENGINES["wheel"].items() if k != "distribution"} | {"distribution": "custom_build"}
    for engine in (wheel, custom):
        assert not schema_ok("RunStarted", with_engine(engine))
        with pytest.raises(ValidationError):
            RunStarted.model_validate(with_engine(engine))


def test_the_time_step_is_said_once_in_effect():
    data = started()
    data["timestep_s"] = 0.004
    with pytest.raises(ValidationError, match="timestep_s"):
        RunStarted.model_validate(data)


@pytest.mark.parametrize(
    ("name", "ok"),
    [("iterations", True), ("cone_type", True), ("Bad-Key", False), ("1st", False), ("", False), ("a" * 65, False)],
)
def test_a_solver_setting_name_follows_one_rule_in_schema_and_model(name, ok):
    data = started()
    data["platform"]["compute"]["solver"] = {name: 1}
    assert schema_ok("RunStarted", data) is ok
    assert schema_ok("ComputeTag", data["platform"]["compute"]) is ok
    if ok:
        RunStarted.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            RunStarted.model_validate(data)


def test_the_solver_name_pattern_is_the_conventions_name_pattern():
    schema = json.loads((SCHEMAS / "ComputeTag.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["solver"]["propertyNames"] == {"pattern": kinetra_core.conventions.NAME_PATTERN}
    assert "patternProperties" not in schema["properties"]["solver"]


@pytest.mark.parametrize(("seed", "ok"), [(0, True), (2**53 - 1, True), (2**53, False), (-1, False)])
def test_the_seed_fits_a_javascript_safe_integer(seed, ok):
    assert kinetra_core.MAX_SEED == 2**53 - 1  # Number.MAX_SAFE_INTEGER
    data = started()
    data["seed"] = seed
    assert schema_ok("RunStarted", data) is ok
    if ok:
        assert RunStarted.model_validate(data).seed == seed
    else:
        with pytest.raises(ValidationError):
            RunStarted.model_validate(data)


def ended_with(**end) -> dict:
    data = copy.deepcopy(recorded()[-1])
    data["end"] = end
    return data


def test_a_trajectory_hash_is_only_evidence_with_its_platform_tag():
    ended = recorded()[-1]
    assert schema_ok("RunEnded", ended)
    assert not schema_ok("RunEnded", without(ended, "end", "trajectory", "platform"))
    assert not schema_ok("RunEnded", without(ended, "end", "trajectory", "hash"))
    with pytest.raises(ValidationError):
        RunEnded.model_validate(without(ended, "end", "trajectory", "platform"))
    bare = ended_with(reason="completed", trajectory={"hash": ended["end"]["trajectory"]["hash"]})  # a hash with no tag
    assert not schema_ok("RunEnded", bare)
    with pytest.raises(ValidationError):
        RunEnded.model_validate(bare)


@pytest.mark.parametrize("reason", ["completed", "stopped"])
def test_a_run_that_ended_with_a_trajectory_requires_it_in_schema_and_model(reason):
    trajectory = recorded()[-1]["end"]["trajectory"]
    good = ended_with(reason=reason, trajectory=trajectory)
    assert schema_ok("RunEnded", good) and schema_ok("ServerMessage", good)
    assert RunEnded.model_validate(good).end.reason == reason
    for bad in (ended_with(reason=reason), ended_with(reason=reason, trajectory=None)):
        assert not schema_ok("RunEnded", bad) and not schema_ok("ServerMessage", bad)
        with pytest.raises(ValidationError):
            RunEnded.model_validate(bad)


def test_a_failed_run_has_no_trajectory_and_may_not_claim_one():
    trajectory = recorded()[-1]["end"]["trajectory"]
    failed = ended_with(reason="failed")
    assert schema_ok("RunEnded", failed) and RunEnded.model_validate(failed).end.reason == "failed"
    claimed = ended_with(reason="failed", trajectory=trajectory)
    assert not schema_ok("RunEnded", claimed)
    with pytest.raises(ValidationError):
        RunEnded.model_validate(claimed)
    assert not schema_ok("RunEnded", ended_with(reason="exploded"))
    with pytest.raises(ValidationError):
        RunEnded.model_validate(ended_with(reason="exploded"))


# --- frames: poses, quaternion order, events ----------------------------------------------------------------


def frame_with_event(event: dict) -> dict:
    f = copy.deepcopy(recorded()[-2])  # the last frame: every event tick in these tests is before it
    f["events"] = [event]
    return f


def test_a_pose_is_a_named_position_and_a_named_quaternion_in_project_order():
    pose = recorded()[1]["poses"][1]
    assert set(pose["position"]) == {"x", "y", "z"}
    assert tuple(pose["orientation"]) == kinetra_core.QUATERNION_COMPONENTS  # x, y, z, w
    bad = copy.deepcopy(recorded()[1])
    bad["poses"][0]["orientation"] = [0.0, 0.0, 0.0, 1.0]  # an array is not a quaternion (G4)
    assert not schema_ok("Frame", bad)
    with pytest.raises(ValidationError):
        Frame.model_validate(bad)
    bad["poses"][0]["orientation"] = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 2.0}
    with pytest.raises(ValidationError, match="unit norm"):
        Frame.model_validate(bad)


def test_events_validate_by_kind_and_carry_si_units():
    contact = {"kind": "contact", "tick": 3, "phase": "begin", "body": "wheel-fl", "other": {"kind": "prop", "id": "prop-a"},
               "force": {"value": 12.5, "unit": "N"}}
    brk = {"kind": "break", "tick": 3, "joint": "axle-fl", "load": {"value": 150.0, "unit": "N"}, "threshold": {"value": 120.0, "unit": "N"}}
    met = {"kind": "condition_met", "tick": 3, "condition": "landed"}
    for event in (contact, brk, met):
        assert schema_ok("Frame", frame_with_event(event))
        assert Frame.model_validate(frame_with_event(event)).events[0].kind == event["kind"]
    wrong_unit = {**brk, "load": {"value": 150.0, "unit": "kg"}}
    assert not schema_ok("Frame", frame_with_event(wrong_unit))
    with pytest.raises(ValidationError):
        Frame.model_validate(frame_with_event(wrong_unit))
    unknown_kind = {"kind": "explosion", "tick": 3}
    assert not schema_ok("Frame", frame_with_event(unknown_kind))


def contact_with(other) -> dict:
    event = {"kind": "contact", "tick": 3, "phase": "begin", "body": "wheel-fl"}
    if other is not KeyError:
        event["other"] = other
    return frame_with_event(event)


@pytest.mark.parametrize(
    ("other", "ok"),
    [
        ({"kind": "ground"}, True),
        ({"kind": "body", "id": "wheel-fr"}, True),
        ({"kind": "prop", "id": "prop-a"}, True),
        ({"kind": "ground", "id": "ground-1"}, False),  # the ground has no id
        ({"kind": "body"}, False),
        ({"kind": "prop"}, False),
        ({"kind": "body", "id": None}, False),
        ({"kind": "prop", "id": "Not An Id"}, False),
        ({"kind": "wall", "id": "x"}, False),
        (KeyError, False),
        (None, False),
    ],
)
def test_a_contact_names_its_other_side_by_kind_in_schema_and_model_alike(other, ok):
    data = contact_with(other)
    assert schema_ok("Frame", data) is ok
    if ok:
        Frame.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            Frame.model_validate(data)


def test_an_event_after_its_frame_or_a_body_twice_is_refused():
    late = {"kind": "condition_met", "tick": 10**6, "condition": "landed"}
    with pytest.raises(ValidationError, match="after its frame"):
        Frame.model_validate(frame_with_event(late))
    twice = copy.deepcopy(recorded()[1])
    twice["poses"].append(twice["poses"][0])
    with pytest.raises(ValidationError, match="one pose"):
        Frame.model_validate(twice)


def test_check_frame_catches_what_one_message_cannot():
    run = RunStarted.model_validate(recorded()[0])
    good = Frame.model_validate(recorded()[3])
    check_frame(run, good)
    for change, text in (
        ({"run_id": "other"}, "run"),
        ({"tick": good.tick + 1}, "multiple"),
        ({"sim_time_s": good.sim_time_s + 0.5}, "sim_time_s"),
        ({"poses": good.poses[:-1]}, "exactly the bodies"),
    ):
        with pytest.raises(ValueError, match=text):
            check_frame(run, good.model_copy(update=change))
    stranger = good.model_copy(update={"events": (kinetra_core.ContactEvent(kind="contact", tick=1, phase="end", body="ghost", other=kinetra_core.GroundTarget(kind="ground")),)})
    with pytest.raises(ValueError, match="not in the run"):
        check_frame(run, stranger)


def test_a_message_ignores_fields_it_does_not_know_and_a_union_picks_by_type():
    data = recorded()[1]
    assert Frame.model_validate({**data, "later_field": 1}).tick == data["tick"]
    assert isinstance(SERVER.validate_python(data), Frame)
    assert isinstance(SERVER.validate_python(recorded()[0]), RunStarted)
    assert isinstance(SERVER.validate_python(recorded()[-1]), RunEnded)


def test_a_run_started_that_lies_about_its_bodies_is_refused():
    data = started()
    data["bodies"].append({"id": "chassis-1", "instances": ["x1"]})
    with pytest.raises(ValidationError, match="unique"):
        RunStarted.model_validate(data)
    data = started()
    data["bodies"][1]["instances"] = ["chassis-1"]
    with pytest.raises(ValidationError, match="one body"):
        RunStarted.model_validate(data)
    data = started()
    data["badge"] = "declared"  # the stream is the engine's output
    with pytest.raises(ValidationError):
        RunStarted.model_validate(data)


# --- the binary form ----------------------------------------------------------------------------------------


def binary_context():
    run = RunStarted.model_validate(recorded()[0])
    return run, [b.id for b in run.bodies]


def test_the_binary_frame_round_trips_to_float32_and_has_the_stated_size():
    run, ids = binary_context()
    messages = recorded()[1:-1]
    for i, message in enumerate(messages):
        frame = Frame.model_validate(message)
        data = encode_frame(frame, ids)
        assert len(data) == BINARY_HEADER_BYTES + BINARY_BODY_BYTES * len(ids) + len(_events_json(frame))
        back = decode_frame(data, run.run_id, ids)
        assert back.tick == frame.tick and back.sim_time_s == frame.sim_time_s  # exact: u32 and f64
        assert back.events == frame.events
        for a, b in zip(back.poses, frame.poses, strict=True):
            assert a.body == b.body
            assert a.position.z == pytest.approx(b.position.z, abs=1e-6)
            assert a.orientation.w == pytest.approx(b.orientation.w, abs=1e-6)
        check_frame(run, back, final=i == len(messages) - 1)


def _events_json(frame: Frame) -> bytes:
    return TypeAdapter(tuple[kinetra_core.FrameEvent, ...]).dump_json(frame.events)


def test_the_committed_binary_frame_has_the_documented_layout():
    """The layout of `client-adapter.md` 3.3.1, read byte by byte, without the codec."""
    data = (FIXTURES / "frame-0000.bin").read_bytes()
    n = 5
    assert len(data) == 24 + 28 * n + 2 == binary_frame_size(n)
    assert data[0] == 1 and data[1:4] == b"\0\0\0"
    tick, count, event_bytes = struct.unpack_from("<III", data, 4)
    assert (tick, count, event_bytes) == (0, n, 2)
    assert struct.unpack_from("<d", data, 16) == (0.0,)
    first = struct.unpack_from("<7f", data, 24)  # chassis-1: x y z qx qy qz qw
    assert first == pytest.approx((0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 1.0))
    wheel = struct.unpack_from("<7f", data, 24 + 28)  # wheel-rl: a quarter turn about x
    assert wheel[3:] == pytest.approx((0.70710678, 0.0, 0.0, 0.70710678))
    assert data[24 + 28 * n :] == b"[]"


def test_the_quaternion_component_order_is_x_y_z_w_in_both_encodings():
    """A quarter turn about +x has x = sin(pi/4) and w = cos(pi/4); a swapped order would put the large value
    in `w` of the wheels' first bytes and `x` of the chassis."""
    run, ids = binary_context()
    json_frame = Frame.model_validate(recorded()[1])
    wheel = next(p for p in json_frame.poses if p.body == "wheel-fl")
    asymmetric = json_frame.model_copy(
        update={"poses": tuple(
            p.model_copy(update={"orientation": kinetra_core.Quaternion(x=0.6, y=0.0, z=0.0, w=0.8)}) if p.body == "wheel-fl" else p
            for p in json_frame.poses
        )}
    )
    data = encode_frame(asymmetric, ids)
    at = BINARY_HEADER_BYTES + BINARY_BODY_BYTES * ids.index("wheel-fl")
    qx, qy, qz, qw = struct.unpack_from("<4f", data, at + 12)
    assert (qx, qy, qz, qw) == pytest.approx((0.6, 0.0, 0.0, 0.8))
    assert decode_frame(data, run.run_id, ids).poses[ids.index("wheel-fl")].orientation.x == pytest.approx(0.6)
    assert wheel.orientation.w == pytest.approx(0.70710678)


def test_the_binary_frame_is_written_in_the_bodies_order_whatever_the_frame_order():
    run, ids = binary_context()
    frame = Frame.model_validate(recorded()[2])
    shuffled = frame.model_copy(update={"poses": tuple(reversed(frame.poses))})
    assert encode_frame(shuffled, ids) == encode_frame(frame, ids)


def test_a_binary_frame_that_is_not_a_frame_of_the_run_is_refused():
    run, ids = binary_context()
    good = encode_frame(Frame.model_validate(recorded()[1]), ids)
    for data, text in (
        (good[:10], "shorter"),
        (good + b"x", "bytes, the header says"),
        (good[:-1], "bytes, the header says"),
        (bytes([2]) + good[1:], "version"),
        (good[:1] + b"\1" + good[2:], "reserved"),
        (good[:8] + struct.pack("<I", 4) + good[12:], "has 4 bodies"),
        (good[:BINARY_HEADER_BYTES] + struct.pack("<f", float("nan")) + good[BINARY_HEADER_BYTES + 4 :], "non-finite"),
        (good[:-2] + b"{}", "events"),
    ):
        with pytest.raises(FrameDecodeError, match=text):
            decode_frame(data, run.run_id, ids)
    with pytest.raises(FrameDecodeError):  # a quaternion of length 2
        bad = bytearray(good)
        struct.pack_into("<f", bad, BINARY_HEADER_BYTES + 24, 2.0)
        decode_frame(bytes(bad), run.run_id, ids)
    with pytest.raises(ValueError, match="exactly the bodies"):
        encode_frame(Frame.model_validate(recorded()[1]).model_copy(update={"poses": ()}), ids)


def test_the_frame_size_matches_the_measured_arithmetic_of_the_spike():
    """A0-02a measured 24 + 28 n bytes with no events; this header is the same 24 bytes and the event text is 2
    more (`[]`), so 200 / 1,000 / 5,000 bodies at 60 Hz stay within 0.1 % of 2.70 / 13.45 / 67.21 Mbit/s."""
    for n, mbit in ((200, 2.70), (1000, 13.45), (5000, 67.21)):
        assert binary_frame_size(n, 0) == 24 + 28 * n
        assert binary_frame_size(n) * 60 * 8 / 1e6 == pytest.approx(mbit, rel=1e-3)
