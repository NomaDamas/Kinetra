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
  edit_apply_s       the MjSpec edit itself: change one geom size
  edit_recompile_s   `spec.recompile(model, data)` after that edit
  edit_total_s       apply + recompile
  add_*_s            same three, for `attach` of one more part (the part is built before the clock starts)
  remove_*_s         same three, for `delete` of that part's body and frame

A failed MjSpec call (it raised) gets no time at all: its `*_s` fields are None and it is left out of the
statistics. The per-operation failure counts over all repeats are in `api_summary` of the JSON and are printed.

Each recompile is also checked (`recompile` returns a new (model, data) pair; whether the old model object
is left untouched is recorded as `old_model_unchanged`): the returned model has the expected body count, the size edit
reached `geom_size`, and the old `qpos`/`qvel`/`time` survived (`*_state_kept`; for add/remove only
the entries that still exist are compared). `api` records which MjSpec operations ran.
Before the first edit, 5 `mj_step`s run once so the state is not the default pose; each later recompile
starts from the data the previous recompile returned.

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
    """Run one MjSpec operation and record the outcome in `api[name]`.

    Returns (elapsed_s, ok, out). `elapsed_s` is None when the call raised: the time of a failed
    call is not a measurement and never enters the statistics. The error text is kept.
    """
    t = time.perf_counter()
    try:
        out = fn()
    except Exception as e:  # noqa: BLE001 - the error text is the finding
        api[name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        return None, False, None
    dt = time.perf_counter() - t
    api.setdefault(name, {"ok": True})
    return dt, True, out


def edit_step(api, r, key, apply_name, apply_fn, spec, model, d):
    """Time `apply_fn` (the MjSpec edit), then `spec.recompile(model, d)`, then both together.

    Sets r[key+"_apply_s"], r[key+"_recompile_s"], r[key+"_total_s"] (None for anything that failed)
    and returns (model, d, ok); on failure returns the inputs unchanged.
    """
    apply_s, ok, _ = try_op(api, apply_name, apply_fn)
    r[key + "_apply_s"] = apply_s
    r[key + "_recompile_s"] = r[key + "_total_s"] = None
    if not ok:
        return model, d, False
    rec_s, ok, out = try_op(api, f"recompile({key})", lambda: spec.recompile(model, d))
    if not ok:
        return model, d, False
    r[key + "_recompile_s"] = rec_s
    r[key + "_total_s"] = apply_s + rec_s
    return out[0], out[1], True


def run_once(n: int, seed: int) -> dict:
    api: dict = {}
    r: dict = {"parts": n, "seed": seed}
    r["load_before"] = load_state()

    r["build_s"], spec = timed(lambda: build(n, seed))
    r["compile_s"], model = timed(spec.compile)
    r["first_frame_s"], data = timed(lambda: _first_frame(model))
    r.update(nbody=model.nbody, nq=model.nq, nv=model.nv, nmesh=model.nmesh, ngeom=model.ngeom)

    # XML round trip of the same assembly
    r["xml_s"], ok, m_xml = try_op(api, "to_xml+from_xml_string", lambda: mujoco.MjModel.from_xml_string(spec.to_xml()))
    r["xml_nbody_matches"] = bool(m_xml.nbody == model.nbody) if ok else None

    # run 5 steps once so "state kept" is not trivially the default pose; later recompiles
    # start from the data the previous recompile returned
    d = _warm(model)
    snap = snapshot(d)
    nq0, nv0, nbody0 = model.nq, model.nv, model.nbody

    # 1) edit one geom size in place
    geom = spec.geom("p0_box")
    old_size = float(geom.size[0])

    def edit():
        geom.size[0] = old_size * 1.1

    old_model, old_d = model, d
    model, d, ok = edit_step(api, r, "edit", "edit(geom size)", edit, spec, model, d)
    if ok:
        r["recompile_returns_new_objects"] = bool(model is not old_model and d is not old_d)
        r["old_model_unchanged"] = bool(abs(old_model.geom_size[old_model.geom("p0_box").id][0] - old_size) < 1e-9)
        r["edit_size_applied"] = bool(abs(model.geom_size[model.geom("p0_box").id][0] - old_size * 1.1) < 1e-9)
        r["edit_state_kept"] = keep_state(snap, d, nq0, nv0)
        r["edit_nbody_ok"] = bool(model.nbody == nbody0)
        r["edit_first_frame_s"], _ = timed(lambda: _forward(model, d))

    # 2) add one part
    snap = snapshot(d)
    nq1, nv1, nbody1 = model.nq, model.nv, model.nbody
    part = make_part(seed + n)  # building the part is not part of the timed edit
    model, d, ok = edit_step(api, r, "add", "attach(add part)", lambda: attach_part(spec, part, n, n + 1), spec, model, d)
    if ok:
        r["add_state_kept"] = keep_state(snap, d, nq1, nv1)
        r["add_nbody_ok"] = bool(model.nbody == nbody1 + 2)

    # 3) remove that part (its attached body and its frame)
    snap = snapshot(d)
    nq2, nv2, nbody2 = model.nq, model.nv, model.nbody

    def remove():
        spec.delete(spec.body(f"p{n}_base"))
        spec.delete(spec.frame(f"f{n}"))

    model, d, ok = edit_step(api, r, "remove", "delete(remove part)", remove, spec, model, d)
    if ok:
        r["remove_nbody_ok"] = bool(model.nbody == nbody2 - 2)
        r["remove_state_kept"] = keep_state(snap, d, nq2, nv2)

    r["api"] = api
    r["load_after"] = load_state()
    return r


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


TIMED = [
    "build_s", "compile_s", "first_frame_s", "xml_s",
    "edit_apply_s", "edit_recompile_s", "edit_total_s", "edit_first_frame_s",
    "add_apply_s", "add_recompile_s", "add_total_s",
    "remove_apply_s", "remove_recompile_s", "remove_total_s",
]


def summarize(runs: list[dict]) -> dict:
    out: dict = {}
    for key in TIMED:
        xs = [x[key] for x in runs if x.get(key) is not None]
        if xs:
            out[key] = {
                "n": len(xs),
                "min": round(min(xs), 6),
                "median": round(statistics.median(xs), 6),
                "max": round(max(xs), 6),
            }
    return out


def summarize_api(runs: list[dict]) -> dict:
    """Per MjSpec operation: how many repeats ran it, and how many of those failed (all repeats counted)."""
    out: dict = {}
    for x in runs:
        for name, v in x["api"].items():
            o = out.setdefault(name, {"runs": 0, "failures": 0, "first_error": None})
            o["runs"] += 1
            if not v["ok"]:
                o["failures"] += 1
                o["first_error"] = o["first_error"] or v.get("error")
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
        api_summ = summarize_api(runs)
        result["scenes"].append({"parts": n, "runs": runs, "summary": summ, "api_summary": api_summ})
        print(f"\nparts={n} nbody={runs[0]['nbody']} nv={runs[0]['nv']} repeats={args.repeats}  (seconds: min / median / max)")
        for key, v in summ.items():
            print(f"  {key:19s} {v['min']:9.4f} {v['median']:9.4f} {v['max']:9.4f}")
        bad = {k: v for k, v in api_summ.items() if v["failures"]}
        print(f"  api failures (all {args.repeats} repeats):", bad or "none")
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
