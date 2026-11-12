"""The recorded run of the C-05b tests, and the writer of the committed fixtures in `tests/fixtures/frames/`.

    uv run python packages/engine/tests/frame_fixture.py     # rewrites the fixtures (test_frames.py fails when they are stale)

This is NOT an engine run. The core has no engine yet (X-01, X-02), so the recording is an analytic one: the four-wheel
car example (`schemas/examples/Project.four-wheel-car.json`) dropped 0.2 m onto the ground in free fall under the
Earth's surface gravity of `data/bodies/earth.json` (9.80665 m/s^2, `인용`), stopped at contact (no bounce, no solver).
It has the shape of what X-02 will record, so the schemas, the codec and the clients can be tested before the engine
exists. The numbers are fixture values, not simulation results: the platform tag names the generator, the contact has no
force (an engine reports it), the `break` event is an example of the form (its load and threshold are made up and the
example car's joints have no threshold), and the trajectory hash is the fixture's own: `sha256` over the binary
frames in order (X-02d defines the real one). The run ends at tick 130, between two frame intervals (every 8 ticks): the last
frame is at 130 and alone carries the `break` of tick 129, as `client-adapter.md` 3.3 requires of the core.

Files:
    run.jsonl   one JSON message per line (keys in model order, so a quaternion reads x, y, z, w): `run_started`, every `frame`, `run_ended`
    frame-0000.bin   the first frame in the binary form (`kinetra_core.encode_frame`)
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from kinetra_core import Frame, RunEnded, RunStarted, encode_frame

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "frames"

G = 9.80665  # m/s^2, data/bodies/earth.json
TIMESTEP = 0.002
FRAME_EVERY = 8
LAST_TICK = 130  # not a multiple of FRAME_EVERY: the run ends between two intervals and still sends a frame there
DROP = 0.2
REST_Z = 0.05  # the example car's instance z

BODIES = {
    "chassis-1": ["chassis-1", "motor-l", "motor-r"],
    "wheel-rl": ["wheel-rl"],
    "wheel-rr": ["wheel-rr"],
    "wheel-fl": ["wheel-fl"],
    "wheel-fr": ["wheel-fr"],
}
XY = {
    "chassis-1": (0.0, 0.0),
    "wheel-rl": (-0.1, 0.13),
    "wheel-rr": (-0.1, -0.13),
    "wheel-fl": (0.1, 0.1),
    "wheel-fr": (0.1, -0.1),
}
S = math.sqrt(0.5)  # wheels: a quarter turn about x puts the axle on y
WHEEL_Q = {"x": S, "y": 0.0, "z": 0.0, "w": S}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
WHEELS = [b for b in BODIES if b.startswith("wheel")]
CONTACT_TICK = next(t for t in range(LAST_TICK + 1) if REST_Z + DROP - G * (t * TIMESTEP) ** 2 / 2 <= REST_Z)
BREAK_TICK = 129  # after the last regular frame (128): only the final frame at LAST_TICK carries it
TICKS = [*range(0, LAST_TICK + 1, FRAME_EVERY), *([LAST_TICK] if LAST_TICK % FRAME_EVERY else [])]


def run_started() -> dict:
    return {
        "type": "run_started",
        "run_id": "fixture-run-1",
        "kind": "preview",
        "badge": "sim",
        "project_id": "four-wheel-car",
        "revision": 0,
        "definition_hash": "sha256:" + "0" * 64,
        "planet": "earth",
        "seed": 0,
        "timestep_s": TIMESTEP,
        "frame_every_ticks": FRAME_EVERY,
        "bodies": [{"id": b, "instances": i} for b, i in BODIES.items()],
        "platform": {
            "os": {"kind": "macos", "kernel_release": "24.6.0"},
            "cpu": {"architecture": "arm64", "model": "Apple M2 Pro"},
            "image_digest": None,
            "engine": {
                "name": "analytic-fixture",
                "version": "0",
                "distribution": "custom_build",
                "compiler": "none (pure Python)",
                "build_flags": "",
            },
            "runtime": {"python": "3.12.11", "numpy": "2.5.4"},
            "core_build": {"commit": "8371a65c9bae8f9ba6831ae1eb88473feb2aa4cc"},
            "compute": {"integrator": "closed-form free fall", "timestep_s": TIMESTEP, "substeps_per_tick": 1, "solver": {}},
            "threads": {"physics": 1, "solver": 1},
        },
    }


def frame(tick: int) -> dict:
    previous = TICKS[TICKS.index(tick) - 1] if tick else -1
    z = max(REST_Z, REST_Z + DROP - G * (tick * TIMESTEP) ** 2 / 2)
    events = []
    if previous < CONTACT_TICK <= tick:
        events += [{"kind": "contact", "tick": CONTACT_TICK, "phase": "begin", "body": w, "other": {"kind": "ground"}} for w in WHEELS]
        events.append({"kind": "condition_met", "tick": CONTACT_TICK, "condition": "landed"})
    if previous < BREAK_TICK <= tick:
        events.append(
            {
                "kind": "break",
                "tick": BREAK_TICK,
                "reason": "over_threshold",
                "joint": "axle-fl",
                "load": {"value": 150.0, "unit": "N"},
                "threshold": {"value": 120.0, "unit": "N"},
            }
        )
    return {
        "type": "frame",
        "run_id": "fixture-run-1",
        "tick": tick,
        "sim_time_s": tick * TIMESTEP,
        "poses": [
            {
                "body": b,
                "position": {"x": XY[b][0], "y": XY[b][1], "z": z},
                "orientation": WHEEL_Q if b in WHEELS else IDENTITY,
            }
            for b in BODIES
        ],
        "events": events,
    }


def build() -> dict[str, bytes]:
    started = RunStarted.model_validate(run_started())
    ids = [b.id for b in started.bodies]
    frames = [Frame.model_validate(frame(t)) for t in TICKS]
    digest = hashlib.sha256(b"".join(encode_frame(f, ids) for f in frames)).hexdigest()
    ended = RunEnded.model_validate(
        {
            "type": "run_ended",
            "run_id": "fixture-run-1",
            "last_tick": frames[-1].tick,
            "end": {
                "reason": "completed",
                "trajectory": {"hash": "sha256:" + digest, "platform": run_started()["platform"]},
            },
        }
    )
    lines = [m.model_dump(mode="json") for m in (started, *frames, ended)]
    text = "".join(json.dumps(m) + "\n" for m in lines)
    return {"run.jsonl": text.encode("utf-8"), "frame-0000.bin": encode_frame(frames[0], ids)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in build().items():
        (OUT / name).write_bytes(data)
        print(f"wrote {OUT / name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
