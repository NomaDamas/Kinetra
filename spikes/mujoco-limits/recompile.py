# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""A0-01c: runtime recompile time of a part assembly, and whether MjSpec can edit it.

Measurement only (no optimization). Run from the repo root:

    uv run spikes/mujoco-limits/recompile.py --parts 10 50 200 --repeats 5 \
        --json spikes/mujoco-limits/results/a0-01c-main.json
    (dependencies are pinned in the PEP 723 header above)

Assembly: N identical-shape "parts" attached with `MjSpec.attach` onto a grid of frames in the
world. A part is a free-floating box carrying a child link with a hinge joint and a convex-hull
mesh geom (32 seeded random vertices, a different hull per part) plus a site. Parts do not touch
at the start (grid pitch 0.4 m, hung 0.5 m above the plane), so the first frame has no contacts
from the layout itself.

Per repeat, a fresh assembly is built and then edited in place. Timings (all `time.perf_counter`):

  build_s        MjSpec() + one `attach` per part (model editing, no compile yet)
  compile_s      `spec.compile()` of the finished assembly -> MjModel
  first_frame_s  MjData(model) + `mj_forward` + one `mj_step`: first physics frame
  xml_s          `spec.to_xml()` + `MjModel.from_xml_string` (the "re-serialize and reload" path)
  edit_s         change one geom size in the spec, then `spec.recompile(model, data)`
  add_s          attach one more part, then `spec.recompile(model, data)`
  remove_s       delete one attached body (and its frame) from the spec, then `spec.recompile(model, data)`

Each recompile is also checked (`recompile` returns a new (model, data) pair; whether the old model object
is left untouched is recorded as `old_model_unchanged`): the returned model has the expected body count, the size edit
reached `geom_size`, and the old `qpos`/`qvel`/`time` survived (`state_kept`; for add/remove only
the entries that still exist are compared). `api` records which MjSpec operations ran at all.

The numbers are wall clock. On a loaded machine they are pessimistic and noisy; the JSON stores
load average and swap at run time so the reader can label them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time

import mujoco
import numpy as np

PITCH = 0.4  # grid pitch (m), larger than any part's extent
HEIGHT = 0.5
HULL_VERTS = 32
HULL_RADIUS = 0.05


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def machine_spec() -> dict:
    return {
        "cpu": sh("sysctl -n machdep.cpu.brand_string") or platform.processor(),
        "cores_logical": os.cpu_count(),
        "ram_gib": round(int(sh("sysctl -n hw.memsize") or 0) / 2**30, 1),
        "os": platform.platform(),
        "python": platform.python_version(),
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
    }


def load_state() -> dict:
    """Load average and swap at the moment of the call (the labels for every timing)."""
    return {
        "uptime": sh("uptime"),
        "loadavg": [round(x, 1) for x in os.getloadavg()],
        "swap": sh("sysctl -n vm.swapusage"),
        "disk_free": sh("df -h / | tail -1"),
    }


def make_part(seed: int) -> mujoco.MjSpec:
    """One part: free box + hinged child link with a seeded convex-hull mesh."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(HULL_VERTS, 3))
    v = HULL_RADIUS * v / np.linalg.norm(v, axis=1, keepdims=True)
    spec = mujoco.MjSpec()
    spec.add_mesh(name="hull").uservert = v.astype(np.float32).ravel()
    base = spec.worldbody.add_body(name="base")
    base.add_freejoint()
    base.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.05, 0.05, 0.05], name="box", mass=0.5)
    link = base.add_body(name="link", pos=[0.0, 0.0, 0.12])
    link.add_joint(type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0, 1, 0], name="hinge")
    link.add_geom(type=mujoco.mjtGeom.mjGEOM_MESH, meshname="hull", name="hull_geom", mass=0.2)
    link.add_site(name="tip", pos=[0.0, 0.0, 0.06])
    return spec


def grid_pos(i: int, n: int) -> list[float]:
    side = max(1, math.ceil(math.sqrt(n)))
    return [(i % side) * PITCH, (i // side) * PITCH, HEIGHT]


def attach_part(spec: mujoco.MjSpec, part: mujoco.MjSpec, i: int, n: int) -> None:
    frame = spec.worldbody.add_frame(pos=grid_pos(i, n), name=f"f{i}")
    spec.attach(part, prefix=f"p{i}_", frame=frame)


def build(n: int, seed: int) -> mujoco.MjSpec:
    spec = mujoco.MjSpec()
    spec.option.timestep = 0.002
    spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.1])
    for i in range(n):
        attach_part(spec, make_part(seed + i), i, n)
    return spec


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def keep_state(old, new, nq_old: int, nv_old: int) -> bool:
    """Old state survived into the recompiled data (compared over the entries that still exist)."""
    k, kv = min(nq_old, new.qpos.size), min(nv_old, new.qvel.size)
    return bool(
        np.array_equal(old["qpos"][:k], new.qpos[:k])
        and np.array_equal(old["qvel"][:kv], new.qvel[:kv])
        and old["time"] == new.time
    )


def snapshot(d) -> dict:
    return {"qpos": d.qpos.copy(), "qvel": d.qvel.copy(), "time": float(d.time)}


def try_op(api: dict, name: str, fn):
    """Run one MjSpec operation, record whether it worked, never hide an error."""
    try:
        out = fn()
        api.setdefault(name, {"ok": True})
        return out
    except Exception as e:  # noqa: BLE001 - the error text is the finding
        api[name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        return None


def run_once(n: int, seed: int) -> dict:
    api: dict = {}
    r: dict = {"parts": n, "seed": seed}
    r["load_before"] = load_state()

    r["build_s"], spec = timed(lambda: build(n, seed))
    r["compile_s"], model = timed(spec.compile)
    r["first_frame_s"], data = timed(lambda: _first_frame(model))
    r.update(nbody=model.nbody, nq=model.nq, nv=model.nv, nmesh=model.nmesh, ngeom=model.ngeom)
    api["MjSpec"] = {"ok": True}
    api["attach"] = {"ok": True}

    # XML round trip of the same assembly
    def xml_trip():
        return mujoco.MjModel.from_xml_string(spec.to_xml())

    xml_s, m_xml = try_timed(api, "to_xml+from_xml_string", xml_trip)
    r["xml_s"] = xml_s
    r["xml_nbody_matches"] = None if m_xml is None else bool(m_xml.nbody == model.nbody)

    # advance the state so "state kept" is not trivially the default pose
    d = _warm(model)
    snap = snapshot(d)
    nq0, nv0, nbody0 = model.nq, model.nv, model.nbody

    # 1) edit one geom size in place
    geom = spec.geom("p0_box")
    old_size = float(geom.size[0])
    geom.size[0] = old_size * 1.1
    s, out = try_timed(api, "recompile(edit geom size)", lambda: spec.recompile(model, d))
    r["edit_s"] = s
    if out is not None:
        r["recompile_returns_new_objects"] = bool(out[0] is not model and out[1] is not d)
        r["old_model_unchanged"] = bool(abs(model.geom_size[model.geom("p0_box").id][0] - old_size) < 1e-9)
        model, d = out
        r["edit_size_applied"] = bool(abs(model.geom_size[model.geom("p0_box").id][0] - old_size * 1.1) < 1e-9)
        r["edit_state_kept"] = keep_state(snap, d, nq0, nv0)
        r["edit_nbody_ok"] = bool(model.nbody == nbody0)
        r["edit_first_frame_s"], _ = timed(lambda: _forward(model, d))

    # 2) add one part
    snap = snapshot(d)
    nq1, nv1, nbody1 = model.nq, model.nv, model.nbody
    try_op(api, "attach(add part at runtime)", lambda: attach_part(spec, make_part(seed + n), n, n + 1))
    s, out = try_timed(api, "recompile(add part)", lambda: spec.recompile(model, d))
    r["add_s"] = s
    if out is not None:
        model, d = out
        r["add_state_kept"] = keep_state(snap, d, nq1, nv1)
        r["add_nbody_ok"] = bool(model.nbody == nbody1 + 2)

    # 3) remove one part (its frame and attached body)
    snap = snapshot(d)
    nq2, nv2, nbody2 = model.nq, model.nv, model.nbody

    def remove():
        spec.delete(spec.body(f"p{n}_base"))
        spec.delete(spec.frame(f"f{n}"))  # name is not guaranteed to survive attach; error is recorded

    try_op(api, "delete(remove part)", remove)
    s, out = try_timed(api, "recompile(remove part)", lambda: spec.recompile(model, d))
    r["remove_s"] = s
    if out is not None:
        model, d = out
        r["remove_nbody_ok"] = bool(model.nbody == nbody2 - 2)
        r["remove_state_kept"] = keep_state(snap, d, nq2, nv2)

    r["api"] = api
    r["load_after"] = load_state()
    return r


def try_timed(api: dict, name: str, fn):
    t = time.perf_counter()
    out = try_op(api, name, fn)
    return time.perf_counter() - t, out


def _first_frame(model):
    d = mujoco.MjData(model)
    mujoco.mj_forward(model, d)
    mujoco.mj_step(model, d)
    return d


def _forward(model, d):
    mujoco.mj_forward(model, d)


def _warm(model):
    d = mujoco.MjData(model)
    mujoco.mj_step(model, d, nstep=5)
    return d


TIMED = ["build_s", "compile_s", "first_frame_s", "xml_s", "edit_s", "edit_first_frame_s", "add_s", "remove_s"]


def summarize(runs: list[dict]) -> dict:
    out: dict = {}
    for key in TIMED:
        xs = [x[key] for x in runs if x.get(key) is not None]
        if xs:
            out[key] = {
                "n": len(xs),
                "min": round(min(xs), 4),
                "median": round(statistics.median(xs), 4),
                "max": round(max(xs), 4),
            }
    return out


def positive_int(text: str) -> int:
    v = int(text)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", type=positive_int, nargs="+", default=[10, 50, 200])
    ap.add_argument("--repeats", type=positive_int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", help="write full results here")
    args = ap.parse_args()

    result = {"machine": machine_spec(), "start": load_state(), "args": vars(args), "scenes": []}
    print("machine:", json.dumps(result["machine"]))
    print("start  :", result["start"]["uptime"], "|", result["start"]["swap"])
    for n in args.parts:
        runs = [run_once(n, args.seed) for _ in range(args.repeats)]
        summ = summarize(runs)
        result["scenes"].append({"parts": n, "runs": runs, "summary": summ})
        print(f"\nparts={n} nbody={runs[0]['nbody']} nv={runs[0]['nv']} repeats={args.repeats}  (seconds: min / median / max)")
        for key, v in summ.items():
            print(f"  {key:19s} {v['min']:9.4f} {v['median']:9.4f} {v['max']:9.4f}")
        bad = {k: runs[0]["api"][k] for k in runs[0]["api"] if not runs[0]["api"][k]["ok"]}
        print("  api failures:", bad or "none")
        for key in ("edit_state_kept", "add_state_kept", "remove_state_kept", "edit_size_applied", "recompile_returns_new_objects", "old_model_unchanged", "edit_nbody_ok", "add_nbody_ok", "remove_nbody_ok", "xml_nbody_matches"):
            vals = [x.get(key) for x in runs]
            print(f"  {key:19s} {vals}")
        print("  load   :", runs[0]["load_before"]["uptime"], "->", runs[-1]["load_after"]["uptime"])
        print("  swap   :", runs[0]["load_before"]["swap"], "->", runs[-1]["load_after"]["swap"])
    result["end"] = load_state()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
