# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""A0-02c: build the example replay bundle (`replay/bundle.json` + `replay/poses.bin`) for the share-link page.

    uv run spikes/web-client/gen_replay.py            # writes replay/ (same bytes every run on the same platform)
    uv run spikes/web-client/gen_replay.py --check    # regenerate in memory, compare with the committed files, exit 1 if different

Source: the NATIVE MuJoCo 4.0.0 trajectory of the legacy rocket car in `spikes/mujoco-wasm/reference/` (scenario `nominal` =
the legacy hero run, 8,000 N, 1,125 steps of 4 ms; made on macOS arm64 by `spikes/mujoco-wasm/gen_reference.py`, see
`spikes/mujoco-wasm/REPORT.md` section 2 for the model and control provenance). This script does not re-simulate. It loads
each recorded `qpos` row into the same MJCF, runs forward kinematics (`mj_kinematics`) and stores the world pose of the 5
rigid bodies (car, 4 wheels). A share page replays recorded poses (client-adapter.md F3), it never runs physics.

Bundle encoding "KPR-spike-1" (NOT the C-05b schema, it only fixes bytes for the measurement):
  poses.bin   little-endian float32, frame-major: frame f, body b (order = bundle.json bodies), 7 floats x y z [m] qx qy qz qw
              (+Z up, unit quaternion). Size = n_frames * n_bodies * 28 bytes. No header: the layout is in bundle.json.
  bundle.json scene (geoms in body-local frames), dt, frame count, provenance (hashes of every input), poses_sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
WASM = HERE.parent / "mujoco-wasm"
OUT = HERE / "replay"
SCENARIO = "nominal"
# (MJCF body name, three.js-side shape). Geom sizes/offsets are read from the compiled model, not typed here.
BODIES = ["car", "wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"]
SHAPES = {mujoco.mjtGeom.mjGEOM_BOX: "box", mujoco.mjtGeom.mjGEOM_CYLINDER: "cylinder"}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build() -> tuple[bytes, dict]:
    man = json.loads((WASM / "reference" / "manifest.json").read_text())
    sc = next(s for s in man["scenarios"] if s["id"] == SCENARIO)
    raw = (WASM / "reference" / "native_qpos.f64").read_bytes()
    rows, nq = man["rows_per_scenario"], man["nq"]
    ids = [s["id"] for s in man["scenarios"]]
    block = rows * nq * 8
    chunk = raw[ids.index(SCENARIO) * block:(ids.index(SCENARIO) + 1) * block]
    if sha256(chunk) != sc["qpos_sha256"]:
        raise SystemExit("reference trajectory does not match manifest qpos_sha256")
    qpos = np.frombuffer(chunk, dtype="<f8").reshape(rows, nq)

    xml = (WASM / "model" / "rocket_car.xml")
    m = mujoco.MjModel.from_xml_path(str(xml))
    d = mujoco.MjData(m)
    bid = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in BODIES]
    poses = np.zeros((rows, len(BODIES), 7), dtype="<f4")
    for f in range(rows):
        d.qpos[:] = qpos[f]
        mujoco.mj_kinematics(m, d)
        for k, b in enumerate(bid):
            w, x, y, z = d.xquat[b]
            poses[f, k] = [*d.xpos[b], x, y, z, w]
    data = poses.tobytes()

    geoms = []
    for g in range(m.ngeom):
        if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE:
            geoms.append({"body": "world", "shape": "plane", "rgba": [0.55, 0.58, 0.62, 1]})
            continue
        w, x, y, z = m.geom_quat[g]
        geoms.append({"body": BODIES[bid.index(int(m.geom_bodyid[g]))], "shape": SHAPES[mujoco.mjtGeom(m.geom_type[g])],
                      "size_m": [float(v) for v in m.geom_size[g]], "pos_m": [float(v) for v in m.geom_pos[g]], "quat_xyzw": [float(x), float(y), float(z), float(w)],
                      "rgba": [round(float(v), 4) for v in m.geom_rgba[g]]})
    bundle = {
        "format": "KPR-spike-1", "kind": "recorded-single-run",  # client-adapter.md F6: one run, not a verdict
        "label": "1회 실행. 판정이 아닙니다", "dt_s": man["dt"], "n_frames": rows, "bodies": BODIES, "floats_per_body": 7,
        "pose_layout": "frame-major float32 LE: x y z qx qy qz qw (+Z up, meters, unit quaternion)", "poses_file": "poses.bin",
        "poses_bytes": len(data), "poses_sha256": sha256(data), "geoms": geoms,
        "provenance": {
            "scenario": SCENARIO, "scenario_kind": sc["kind"], "mujoco": mujoco.mj_versionString(), "numpy": np.__version__,
            "source_trajectory": "spikes/mujoco-wasm/reference/native_qpos.f64", "source_qpos_sha256": sc["qpos_sha256"],
            "source_platform": man["platform"], "source_generator": "spikes/mujoco-wasm/gen_reference.py",
            "model_file": "spikes/mujoco-wasm/model/rocket_car.xml", "model_sha256": sha256(xml.read_bytes()), "legacy_model_hash": man["legacy_model_hash"],
            "legacy_origin": "legacy-v0 packages/engine/src/kinetra_engine/templates/rocket_car.py build_mjcf(); hero controls from legacy-v0 apps/web/public/demo/roadster/traj_8000.json",
            "ctrl_sha256": sc["ctrl_sha256"], "note": "recorded poses only; this bundle was not re-simulated and is not a judgement",
        },
    }
    return data, bundle


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    data, bundle = build()
    text = json.dumps(bundle, indent=1) + "\n"
    if args.check:
        ok = (OUT / "poses.bin").read_bytes() == data and (OUT / "bundle.json").read_text() == text
        print("committed replay/ matches a regeneration" if ok else "committed replay/ DIFFERS from a regeneration")
        return 0 if ok else 1
    OUT.mkdir(exist_ok=True)
    (OUT / "poses.bin").write_bytes(data)
    (OUT / "bundle.json").write_text(text)
    print(f"wrote replay/poses.bin {len(data)} B (sha256 {bundle['poses_sha256'][:16]}), replay/bundle.json {len(text)} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
