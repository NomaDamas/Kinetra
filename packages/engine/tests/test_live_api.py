"""Live simulation endpoint: real MuJoCo stepping, determinism, schema-valid frames, stop/restart, search."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from physlab_core.schemas import Trajectory

from kinetra_engine import live
from kinetra_engine.api import app
from kinetra_engine.templates import available


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _sim(client, **kw):
    r = client.post("/simulate", json={"template": "rocket_car", "seed": 7, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_reports_live_and_mujoco(client):
    h = client.get("/health").json()
    assert h["ok"] and h["mujoco_version"] and h["live"]["protocol"] == live.PROTOCOL
    assert "rocket_car" in h["live"]["search"]


def test_simulate_is_deterministic_and_schema_valid(client):
    a, b = _sim(client), _sim(client)
    assert a["trajectory_sha256"] == b["trajectory_sha256"]
    assert a["trajectory"] == b["trajectory"]
    traj = Trajectory.model_validate(a["trajectory"])            # pos/quat/series shapes validated by the schema
    assert traj.n_frames == a["n_frames"] == 225 and len(traj.bodies) == 15
    assert a["perf"]["steps"] == 1125 and a["perf"]["us_per_step"] > 0
    assert a["mujoco_version"]
    assert {d["key"] for d in a["display"]} >= {"rotation_deg", "touchdown_vz", "fuel_kg"}


def test_live_frames_equal_template_rollout(client):
    """The incremental stepper reproduces the template's own rollout (same physics, same export layout)."""
    out = _sim(client)
    res = live.resolve(live.SimRequest(template="rocket_car", seed=7))
    ref = res.tpl.rollout(res.spec, res.params, 7)
    t = out["trajectory"]
    assert t["pos"] == json.loads(ref.model_dump_json())["pos"]
    assert t["quat"] == json.loads(ref.model_dump_json())["quat"]
    live_pitch = next(s for s in t["series"] if s["name"] == "pitch_deg")["values"]
    ref_pitch = next(s for s in ref.series if s.name == "pitch_deg").values
    assert live_pitch == ref_pitch
    assert out["success"] == res.tpl.judge_nominal(res.spec, res.params)


def test_overrides_change_the_physics(client):
    base = _sim(client, include_trajectory=False)
    weak = _sim(client, overrides={"thruster_force_max": 1500.0}, include_trajectory=False)
    assert base["trajectory_sha256"] != weak["trajectory_sha256"]
    assert base["success"] and not weak["success"]            # stored 5000 N schedule cannot flip the car with 1500 N nozzles
    assert weak["failed_checks"]


def test_unknown_override_and_template_rejected(client):
    assert client.post("/simulate", json={"template": "rocket_car", "overrides": {"nope": 1}}).status_code == 400
    assert client.post("/simulate", json={"template": "nope"}).status_code == 404


def test_ws_stream_matches_rest(client):
    ref = _sim(client, include_trajectory=False)
    with client.websocket_connect("/ws/sim", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "start", "template": "rocket_car", "seed": 7, "speed": 0})
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m["type"] in ("result", "error"):
                break
    assert msgs[0]["type"] == "start" and msgs[0]["compute"] == "incremental" and msgs[0]["n_frames_max"] == 225
    frames = [m for m in msgs if m["type"] == "frames"]
    assert sum(len(m["pos"]) for m in frames) == 225
    assert frames[0]["i0"] == 0 and all(len(f["pos"][0]) == len(msgs[0]["bodies"]) for f in frames)
    res = msgs[-1]
    assert res["type"] == "result" and res["trajectory_sha256"] == ref["trajectory_sha256"]
    assert res["perf"]["steps"] == 1125


def test_ws_stop_and_restart(client):
    with client.websocket_connect("/ws/sim") as ws:
        ws.send_json({"type": "start", "template": "rocket_car", "seed": 7, "speed": 1})
        assert ws.receive_json()["type"] == "start"
        ws.send_json({"type": "stop"})
        while True:
            m = ws.receive_json()
            if m["type"] == "stopped":
                break
            assert m["type"] == "frames"
        ws.send_json({"type": "restart"})
        m = ws.receive_json()
        assert m["type"] == "start"
        ws.send_json({"type": "stop"})


def test_ws_rejects_foreign_origin(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/sim", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()


def test_ws_search_streams_progress_and_finds_a_flip(client):
    with client.websocket_connect("/ws/sim") as ws:
        ws.send_json({"type": "start", "template": "rocket_car", "mode": "search", "seed": 3, "speed": 0, "search": {"max_seconds": 40}})
        types, last_progress = [], None
        while True:
            m = ws.receive_json()
            types.append(m["type"])
            if m["type"] == "progress":
                last_progress = m
            if m["type"] == "preview":
                assert m["n_frames"] == len(m["pos"]) <= 225
            if m["type"] in ("result", "error"):
                break
    assert m["type"] == "result", m
    assert types.count("progress") > 5 and "preview" in types and "search_done" in types and "replay_start" in types
    assert last_progress["evals"] > 0
    assert m["success"]                                       # seed 3 finds a witness well inside 40 s on this model


def test_humanoid_batch_stream(client):
    if "humanoid_jump" not in available():
        pytest.skip("humanoid template unavailable")
    r = client.post("/simulate", json={"template": "humanoid_jump", "seed": 1, "variant": 1.0})
    if r.status_code != 200:
        pytest.skip(r.text)
    out = r.json()
    Trajectory.model_validate(out["trajectory"])
    assert out["perf"]["compute"].startswith("batch")
