# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""A0-01a: native MuJoCo multi-body and joint-release scale measurement.

Measurement only (no optimization). Run:

    uv run spikes/mujoco-limits/scale.py --bodies 200 1000 5000
    (dependencies are pinned in the PEP 723 header above)

Scenes
  pile-N   N free boxes dropped into a walled bin on a plane (contacts included).
  break-100  100 boxes in 10 welded columns; each column's boxes are welded to
           the box below, the lowest box to the world. The 100 weld equality
           constraints are deactivated one by one (data.eq_active = 0) over a
           fixed sim-time window, so the structure falls apart during the run.
  break-100+pile-M  same, with M free boxes piling up in the same world.

rtf = sim seconds / wall seconds spent inside mj_step (the number asked for; on a
loaded machine it is pessimistic). rtf_cpu = sim seconds / process CPU seconds, a
secondary figure that excludes time spent descheduled (still shares caches/memory
bandwidth with the other load, so it is only an indication).

Every run is repeated with a fresh model/data and the same seed; the chained
sha256 of qpos taken every --hash-every steps is compared between repeats.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time

import mujoco
import numpy as np

BOX_HALF = 0.05  # 0.1 m cube
LAYERS = 5
PITCH_XY = 0.18  # > cube diagonal 0.141 m: no initial overlap with yaw/tilt jitter
PITCH_Z = 0.15
WALL_H = 1.0


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def machine_spec() -> dict:
    return {
        "cpu": sh("sysctl -n machdep.cpu.brand_string") or platform.processor(),
        "cores_logical": os.cpu_count(),
        "cores_physical": sh("sysctl -n hw.physicalcpu") or None,
        "ram_gib": round(int(sh("sysctl -n hw.memsize") or 0) / 2**30, 1),
        "os": platform.platform(),
        "python": platform.python_version(),
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
    }


def uptime() -> str:
    return sh("uptime")


def euler_to_quat(rng: np.random.Generator) -> np.ndarray:
    """Random yaw plus small tilt, as a wxyz quaternion."""
    yaw = rng.uniform(0, 2 * math.pi)
    roll, pitch = rng.uniform(-0.15, 0.15, 2)
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return np.array(
        [
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        ]
    )


def pile_bodies(n: int, rng: np.random.Generator, x_offset: float):
    """XML for n free boxes plus the bin (floor plane + 4 walls). Returns (xml, half_extent)."""
    nx = math.ceil(math.sqrt(n / LAYERS))
    ny = math.ceil(n / (LAYERS * nx))
    half_x, half_y = nx * PITCH_XY / 2 + 0.1, ny * PITCH_XY / 2 + 0.1
    parts = []
    for i in range(n):
        layer, rem = divmod(i, nx * ny)
        row, col = divmod(rem, nx)
        x = x_offset + (col - (nx - 1) / 2) * PITCH_XY + rng.uniform(-0.01, 0.01)
        y = (row - (ny - 1) / 2) * PITCH_XY + rng.uniform(-0.01, 0.01)
        z = BOX_HALF + 0.02 + layer * PITCH_Z
        q = euler_to_quat(rng)
        parts.append(
            f'<body name="p{i}" pos="{x:.6f} {y:.6f} {z:.6f}" quat="{q[0]:.8f} {q[1]:.8f} {q[2]:.8f} {q[3]:.8f}">'
            f"<freejoint/>"
            f'<geom type="box" size="{BOX_HALF} {BOX_HALF} {BOX_HALF}" density="1000"/></body>'
        )
    t = 0.05  # wall half-thickness
    # (center x, center y, half size x, half size y): two x-side walls, two y-side walls
    walls = [
        (x_offset + half_x + t, 0.0, t, half_y + 2 * t),
        (x_offset - half_x - t, 0.0, t, half_y + 2 * t),
        (x_offset, half_y + t, half_x + 2 * t, t),
        (x_offset, -half_y - t, half_x + 2 * t, t),
    ]
    for wx, wy, sx, sy in walls:
        parts.append(f'<geom type="box" pos="{wx} {wy} {WALL_H / 2}" size="{sx} {sy} {WALL_H / 2}"/>')
    return "\n".join(parts), half_x


def break_bodies(x_offset: float):
    """10 columns x 10 boxes. Returns (body xml, weld xml); 100 welds total."""
    bodies, welds = [], []
    gap = 0.002
    for c in range(10):
        x = x_offset + c * 0.3
        for r in range(10):
            z = 0.5 + BOX_HALF + r * (2 * BOX_HALF + gap)
            name = f"w{c}_{r}"
            bodies.append(
                f'<body name="{name}" pos="{x:.4f} 0 {z:.4f}"><freejoint/>'
                f'<geom type="box" size="{BOX_HALF} {BOX_HALF} {BOX_HALF}" density="1000"/></body>'
            )
            below = f"w{c}_{r - 1}" if r else None
            if below:
                welds.append(f'<weld name="e{c}_{r}" body1="{name}" body2="{below}"/>')
            else:
                welds.append(f'<weld name="e{c}_{r}" body1="{name}"/>')  # to world
    return "\n".join(bodies), "\n".join(welds)


def build_xml(scene: str, n_pile: int, rng, timestep: float, integrator: str):
    pile_xml, half_x = "", 0.0
    if n_pile:
        pile_xml, half_x = pile_bodies(n_pile, rng, x_offset=0.0)
    brk_bodies, brk_welds = ("", "")
    if scene == "break":
        brk_bodies, brk_welds = break_bodies(x_offset=half_x + 1.0 if n_pile else 0.0)
    return f"""<mujoco>
  <option timestep="{timestep}" integrator="{integrator}"/>
  <size memory="2G"/>
  <worldbody>
    <geom type="plane" size="0 0 0.1"/>
    {pile_xml}
    {brk_bodies}
  </worldbody>
  <equality>{brk_welds}</equality>
</mujoco>"""


def run_once(args, scene: str, n_pile: int) -> dict:
    rng = np.random.default_rng(args.seed)
    xml = build_xml(scene, n_pile, rng, args.timestep, args.integrator)
    t0 = time.perf_counter()
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    compile_s = time.perf_counter() - t0

    # Random initial velocities for pile bodies (seeded): makes the pile chaotic so
    # any nondeterminism would show up in the trajectory hash.
    vrng = np.random.default_rng(args.seed + 1)
    for i in range(model.njnt):
        if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE and n_pile and i < n_pile:
            adr = model.jnt_dofadr[i]
            data.qvel[adr : adr + 2] = vrng.uniform(-0.3, 0.3, 2)

    neq = model.neq
    release_steps = []
    if scene == "break":
        order = np.random.default_rng(args.seed + 2).permutation(neq)
        t_start, t_end = 0.2, 1.2  # sim seconds: all releases happen in this window
        first = round(t_start / args.timestep)
        span = round((t_end - t_start) / args.timestep)
        release_steps = [(first + int(k * span / neq), int(order[k])) for k in range(neq)]
        release_steps.sort()
    target_steps = round(args.sim_seconds / args.timestep)

    h = hashlib.sha256()
    checkpoints: list[str] = []
    wall = 0.0
    cpu = 0.0
    steps = 0
    ncon_max = 0
    capped = False
    released = 0
    ri = 0
    mujoco.mj_forward(model, data)
    load_before = uptime()
    while steps < target_steps:
        chunk = min(args.hash_every - steps % args.hash_every, target_steps - steps)
        # Releases happen at exact steps: split the chunk at the next release step.
        while ri < len(release_steps) and release_steps[ri][0] <= steps:
            data.eq_active[release_steps[ri][1]] = 0
            ri += 1
            released += 1
        if ri < len(release_steps):
            chunk = min(chunk, release_steps[ri][0] - steps)
        t, c = time.perf_counter(), time.process_time()
        mujoco.mj_step(model, data, nstep=chunk)
        wall += time.perf_counter() - t
        cpu += time.process_time() - c
        steps += chunk
        ncon_max = max(ncon_max, data.ncon)
        if steps % args.hash_every == 0 or steps == target_steps:
            h.update(data.qpos.tobytes())
            checkpoints.append(h.hexdigest())
        if wall > args.wall_cap:
            capped = steps < target_steps
            break
    load_after = uptime()
    warnings = int(sum(int(w.number) for w in data.warning))
    finite = bool(np.isfinite(data.qpos).all())
    sim_s = steps * args.timestep
    return {
        "scene": scene if scene == "break" else "pile",
        "n_pile": n_pile,
        "n_bodies": model.nbody - 1,
        "n_welds_total": neq,
        "n_welds_released": released,
        "nv": model.nv,
        "seed": args.seed,
        "timestep": args.timestep,
        "integrator": args.integrator,
        "steps": steps,
        "steps_target": target_steps,
        "capped_by_wall": capped,
        "sim_s": round(sim_s, 6),
        "wall_s": round(wall, 4),
        "rtf": round(sim_s / wall, 4) if wall > 0 else None,
        "cpu_s": round(cpu, 4),
        "rtf_cpu": round(sim_s / cpu, 4) if cpu > 0 else None,
        "compile_s": round(compile_s, 3),
        "ncon_final": int(data.ncon),
        "ncon_max_sampled": int(ncon_max),
        "warnings": warnings,
        "finite": finite,
        "final_hash": checkpoints[-1] if checkpoints else None,
        "checkpoints": checkpoints,
        "uptime_before": load_before,
        "uptime_after": load_after,
        "loadavg_after": [round(x, 1) for x in os.getloadavg()],
    }


def compare(runs: list[dict]) -> dict:
    """Compare chained-hash checkpoints over the common prefix of all repeats.

    identical is True / False, or None ("not comparable") when fewer than two runs
    were given or the runs share no checkpoint. None is never reported as a match.
    """
    k = min((len(r["checkpoints"]) for r in runs), default=0)
    if len(runs) < 2 or k == 0:
        return {"checkpoints_compared": k, "identical": None}
    same = all(r["checkpoints"][:k] == runs[0]["checkpoints"][:k] for r in runs)
    return {"checkpoints_compared": k, "identical": same}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bodies", type=int, nargs="+", default=[200, 1000, 5000])
    ap.add_argument("--break-pile", type=int, nargs="*", default=[0, 1000],
                    help="free boxes piling up alongside the 100-weld break scene (0 = break scene alone)")
    ap.add_argument("--no-break", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timestep", type=float, default=0.002)
    ap.add_argument("--integrator", default="Euler")
    ap.add_argument("--sim-seconds", type=float, default=2.0)
    ap.add_argument("--wall-cap", type=float, default=60.0, help="stop a run after this many stepping seconds")
    ap.add_argument("--hash-every", type=int, default=10)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--json", help="write full results to this file")
    args = ap.parse_args()

    spec = machine_spec()
    print(json.dumps({"machine": spec, "argv": sys.argv, "uptime_start": uptime()}, indent=1), flush=True)

    scenes = [("pile", n) for n in args.bodies]
    if not args.no_break:
        scenes += [("break", n) for n in args.break_pile]

    results = []
    for scene, n in scenes:
        runs = [run_once(args, scene, n) for _ in range(args.repeats)]
        cmp = compare(runs)
        for i, r in enumerate(runs):
            r["repeat"] = i
            print(json.dumps({k: v for k, v in r.items() if k != "checkpoints"}), flush=True)
        label = f"{scene}-{n}"
        verdict = "NOT COMPARABLE" if cmp["identical"] is None else cmp["identical"]
        print(f"HASH {label}: {verdict} over {cmp['checkpoints_compared']} checkpoints "
              f"(final {(runs[0]['final_hash'] or 'none')[:16]})", flush=True)
        results.append({"label": label, "runs": runs, "determinism": cmp})

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"machine": spec, "argv": sys.argv, "results": results}, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
