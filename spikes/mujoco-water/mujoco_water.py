# /// script
# requires-python = ">=3.11"
# dependencies = ["mujoco==4.0.0", "numpy==2.5.4"]
# ///
"""FL-01: MuJoCo medium model and water-body-limited forces (spike, measurement only).

    uv run spikes/mujoco-water/mujoco_water.py --seed 0 --json spikes/mujoco-water/results/fl-01.json
    (the issue text says `uv run python spikes/fluids/...`; `uv run python` ignores the PEP 723 header, so this
     spike is run as a script like spikes/mujoco-limits/scale.py)

A  what MuJoCo's own fluid model is: global density/viscosity, no buoyancy, no acceleration-proportional added mass
B  per-body buoyancy force from the submerged volume of the box clipped by the water body (FL-03a definition:
   a horizontal rectangle stood between bottom and surface; outside the sides, below the bottom, above the
   surface is not water) -> equilibrium draft vs Archimedes
C  clipping checks against closed-form volume/centroid
D  added-mass candidates: inertia increase, acceleration-proportional force (lagged / same-step)
E  N-box scene: per-step cost of xfrc_applied vs mjcb_passive, repeat-run hash equality
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

RHO_W = 1000.0  # kg/m^3, a round value chosen for the spike (기본값). Not a cited seawater/freshwater value.
G = 9.81  # MuJoCo's default gravity magnitude (option gravity="0 0 -9.81")
ADDED_MASS_SPHERE = 0.5  # m_a / (rho_fluid V), sphere. MuJoCo docs, ellipsoid model: kappa=2/3 -> kappa/(2-kappa)=1/2

# corner index = 4*ix + 2*iy + iz (0 = -half, 1 = +half); faces as cyclic corner lists
BOX_FACES = [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5]]
BOX_SIGNS = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], dtype=float)


class Water:
    """FL-03a water body: horizontal rectangle [x0,x1]x[y0,y1] between bottom zb and surface zs."""

    def __init__(self, x0, x1, y0, y1, zb, zs):
        self.lo = np.array([x0, y0, zb], dtype=float)
        self.hi = np.array([x1, y1, zs], dtype=float)
        eye = np.eye(3)
        self.planes = [(eye[i], self.hi[i]) for i in range(3)] + [(-eye[i], -self.lo[i]) for i in range(3)]


def clip_halfspace(faces, n, c):
    """Keep n.x <= c of a convex polyhedron given as a list of polygons (N,3); adds the cap face."""
    eps = 1e-12 * (1.0 + abs(c))
    out, cut, capped = [], [], False
    for f in faces:
        d = f @ n - c
        poly = []
        for i in range(len(f)):
            j = (i + 1) % len(f)
            if d[i] <= 0:
                poly.append(f[i])
                if abs(d[i]) <= eps:
                    cut.append(f[i])
            if (d[i] < -eps and d[j] > eps) or (d[i] > eps and d[j] < -eps):
                p = f[i] + (f[j] - f[i]) * (d[i] / (d[i] - d[j]))
                poly.append(p)
                cut.append(p)
        if len(poly) >= 3:
            out.append(np.array(poly))
            capped |= bool(np.all(np.abs(np.array(poly) @ n - c) <= eps))  # an existing face already lies in the plane
    if not capped and cut:
        pts = np.unique(np.round(np.array(cut), 9), axis=0)
        if len(pts) >= 3:
            ctr = pts.mean(axis=0)
            u = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
            u /= np.linalg.norm(u)
            v = np.cross(n, u)
            ang = np.arctan2((pts - ctr) @ v, (pts - ctr) @ u)
            out.append(pts[np.argsort(ang)])
    return out


def poly_volume_centroid(faces):
    """Volume and centroid of a convex polyhedron: tetrahedra fanned from an interior point."""
    if len(faces) < 4:
        return 0.0, None
    ref = np.vstack(faces).mean(axis=0)
    vol, cen = 0.0, np.zeros(3)
    for f in faces:
        for k in range(1, len(f) - 1):
            a, b, c = f[0] - ref, f[k] - ref, f[k + 1] - ref
            v = abs(float(a @ np.cross(b, c))) / 6.0
            vol += v
            cen += v * (ref + (a + b + c) / 4.0)
    return (vol, cen / vol) if vol > 1e-15 else (0.0, None)


def submerged_box(water: Water, center, rot, half):
    """(volume, centroid) of box ∩ water body. Fast paths skip the clip when the box is wholly in or out."""
    corners = center + (BOX_SIGNS * half) @ np.asarray(rot).reshape(3, 3).T
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    if np.any(hi <= water.lo) or np.any(lo >= water.hi):
        return 0.0, None
    if np.all(lo >= water.lo) and np.all(hi <= water.hi):
        return 8.0 * float(np.prod(half)), np.asarray(center, dtype=float)
    faces = [corners[idx] for idx in BOX_FACES]
    for n, c in water.planes:
        faces = clip_halfspace(faces, n, c)
        if len(faces) < 4:
            return 0.0, None
    return poly_volume_centroid(faces)


def machine_spec() -> dict:
    sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {
        "cpu": sh("sysctl -n machdep.cpu.brand_string") or platform.processor(),
        "cores_logical": os.cpu_count(),
        "ram_gib": round(int(sh("sysctl -n hw.memsize") or 0) / 2**30, 1),
        "os": platform.platform(),
        "python": platform.python_version(),
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
        "uptime": sh("uptime"),
    }


# ---------------------------------------------------------------- A: what MuJoCo's own fluid model is
def medium_facts() -> dict:
    """Run MuJoCo's own fluid model with density=1000 and look at what it does (and does not) do."""
    body = '<body name="{n}" pos="{p}"><freejoint/><geom type="{t}" size="{s}" density="500" {x}/></body>'
    xml = ('<mujoco><option density="1000" viscosity="0" integrator="implicitfast"/><worldbody>'
           + body.format(n="box_hi", p="0 0 5", t="box", s=".1 .1 .1", x="")
           + body.format(n="box_lo", p="100 0 -5", t="box", s=".1 .1 .1", x="")
           + body.format(n="ell_hi", p="0 50 5", t="sphere", s=".1", x='fluidshape="ellipsoid"')
           + body.format(n="ell_lo", p="0 -50 -5", t="sphere", s=".1", x='fluidshape="ellipsoid"')
           + "</worldbody></mujoco>")
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)  # all four at rest, body density 500 < medium 1000
    rest = {"qfrc_fluid_absmax": float(np.abs(d.qfrc_fluid).max()),
            "qacc_z": [float(d.qacc[6 * i + 2]) for i in range(4)]}
    d.qvel[[0, 6, 12, 18]] = 1.0  # all four at 1 m/s along +x
    mujoco.mj_forward(m, d)
    f = d.qfrc_fluid.copy()
    box_same = bool(np.array_equal(f[0:6], f[6:12]))  # z=+5 vs z=-5 (x=100): same force
    ell_same = bool(np.array_equal(f[12:18], f[18:24]))
    m.geom_fluid[2, 0] = 0.5  # geom 2 = ell_hi: per-geom interaction coefficient, written at run time
    mujoco.mj_forward(m, d)
    return {
        "density_type": type(m.opt.density).__name__, "density": m.opt.density,
        "viscosity_type": type(m.opt.viscosity).__name__, "viscosity": m.opt.viscosity,
        "mjModel_fields_with_fluid_or_density_or_viscosity": sorted(
            a for a in dir(m) if any(k in a for k in ("fluid", "dens", "visc"))),
        "at_rest": rest, "box_force_equal_at_z+5_and_z-5": box_same, "ellipsoid_force_equal_at_z+5_and_z-5": ell_same,
        "inertia_box_qfrc_x_N": float(f[0]), "ellipsoid_qfrc_x_N": float(f[12]),
        "ellipsoid_x_after_geom_fluid_coef0_set_to_0.5_ratio": float(d.qfrc_fluid[12]) / float(f[12]),
    }


# ---------------------------------------------------------------- B/E: per-body water force
def build_model(boxes, h, floor_z=None):
    parts = [f'<mujoco><option timestep="{h}" integrator="Euler"/><worldbody>']
    if floor_z is not None:
        parts.append(f'<geom type="plane" pos="0 0 {floor_z}" size="0 0 0.1"/>')
    for i, b in enumerate(boxes):
        q = " ".join(f"{x:.9f}" for x in b["quat"])
        p = " ".join(f"{x:.9f}" for x in b["pos"])
        s = " ".join(f"{x:.9f}" for x in b["half"])
        parts.append(f'<body name="b{i}" pos="{p}" quat="{q}"><freejoint/>'
                     f'<geom type="box" size="{s}" density="{b["density"]:.9f}"/></body>')
    parts.append("</worldbody></mujoco>")
    return mujoco.MjModel.from_xml_string("".join(parts))


def body_wrench(m, d, bid, water, zeta):
    """Buoyancy (rho g V_sub at the centroid of the submerged part) plus settling drag. -> (F, point)."""
    half = m.geom_size[m.body_geomadr[bid]]
    vol, cen = submerged_box(water, d.xpos[bid], d.xmat[bid], half)
    if cen is None:
        return None, None
    full = 8.0 * float(np.prod(half))
    k = RHO_W * G * 4.0 * half[0] * half[1]  # heave stiffness rho g A of the upright box
    c = zeta * 2.0 * math.sqrt(k * m.body_mass[bid])
    dof = m.body_dofadr[bid]
    f = np.array([0.0, 0.0, RHO_W * G * vol]) - c * (vol / full) * d.qvel[dof:dof + 3]
    return f, cen


def apply_xfrc(m, d, water, zeta):
    for bid in range(1, m.nbody):
        f, cen = body_wrench(m, d, bid, water, zeta)
        if f is None:
            d.xfrc_applied[bid] = 0.0
        else:
            d.xfrc_applied[bid, :3] = f
            d.xfrc_applied[bid, 3:] = np.cross(cen - d.xipos[bid], f)


def make_passive(water, zeta):
    zero = np.zeros(3)

    def passive(m, d):
        for bid in range(1, m.nbody):
            f, cen = body_wrench(m, d, bid, water, zeta)
            if f is not None:
                mujoco.mj_applyFT(m, d, f, zero, cen, bid, d.qfrc_passive)
    return passive


def run_boxes(boxes, water, path, h, steps, zeta=0.5, floor_z=None, hash_every=10):
    """path: none | xfrc | xfrc_step12 | passive. Returns timing and chained qpos hash.

    xfrc writes d.xfrc_applied before mj_step, from d.xpos/d.xipos as the previous mj_step left them (one step older
    than qpos). xfrc_step12 splits the step (mj_step1: position+velocity stage, write xfrc_applied, mj_step2), the
    split the MuJoCo docs describe for forces that depend on derived quantities, so its poses are current. passive
    runs inside mj_step after the position stage (global mjcb_passive), so its poses are current too."""
    m = build_model(boxes, h, floor_z)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    hs, wall, cpu = hashlib.sha256(), 0.0, 0.0
    if path == "passive":
        mujoco.set_mjcb_passive(make_passive(water, zeta))
    try:
        t0, c0 = time.perf_counter(), time.process_time()
        for n in range(1, steps + 1):
            if path == "xfrc_step12":
                mujoco.mj_step1(m, d)
                apply_xfrc(m, d, water, zeta)
                mujoco.mj_step2(m, d)
            else:
                if path == "xfrc":
                    apply_xfrc(m, d, water, zeta)
                mujoco.mj_step(m, d)
            if n % hash_every == 0:
                hs.update(d.qpos.tobytes())
        wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    finally:
        mujoco.set_mjcb_passive(None)
    return {"model": m, "data": d, "hash": hs.hexdigest(), "qpos": d.qpos.copy(), "us_per_step": wall / steps * 1e6,
            "cpu_us_per_step": cpu / steps * 1e6, "finite": bool(np.isfinite(d.qpos).all())}


def draft_cases(seed):
    rng = np.random.default_rng(seed)
    cases = [(0.4, 0.4, 0.2, 0.25), (0.4, 0.4, 0.2, 0.6), (0.4, 0.4, 0.2, 0.9), (0.6, 0.3, 0.2, 0.5)]
    for _ in range(4):  # seeded: footprint >= 1.5x height keeps the upright float metacentrically stable
        lz = rng.uniform(0.08, 0.3)
        cases.append((round(rng.uniform(1.5, 3) * lz, 4), round(rng.uniform(1.5, 3) * lz, 4), round(lz, 4),
                      round(rng.uniform(0.15, 0.95), 4)))
    return cases


def draft_experiment(seed, h=0.002, settle_s=12.0):
    water = Water(-5, 5, -5, 5, -3.0, 0.0)  # large tank; surface at z=0
    rows = []
    for lx, ly, lz, ratio in draft_cases(seed):
        for path in ("xfrc", "passive"):
            box = {"half": (lx / 2, ly / 2, lz / 2), "density": ratio * RHO_W, "pos": (0.0, 0.0, 0.5 * lz),
                   "quat": (1.0, 0.0, 0.0, 0.0)}  # starts half out of the water, upright
            r = run_boxes([box], water, path, h, round(settle_s / h))
            d = r["data"]
            draft = -(d.qpos[2] - lz / 2)  # surface z=0 minus bottom face z
            exp = ratio * lz
            rows.append({"lx": lx, "ly": ly, "lz": lz, "density_ratio": ratio, "path": path,
                         "draft_expected_m": exp, "draft_measured_m": float(draft),
                         "error_pct": float((draft - exp) / exp * 100.0),
                         "residual_speed_m_s": float(np.abs(d.qvel[:3]).max()),
                         "tilt_deg": float(math.degrees(2 * math.asin(min(1.0, np.linalg.norm(d.qpos[4:6])))))})
    return rows


# ---------------------------------------------------------------- C: clipping against closed forms
def clip_checks():
    w = Water(0, 2, 0, 2, -1.0, 0.0)
    eye = np.eye(3).ravel()
    h = np.array([0.5, 0.5, 0.5])  # 1 m cube, volume 1
    c = lambda x, y, z: np.array([x, y, z], dtype=float)  # noqa: E731
    cases = [  # name, center, rot, expected volume, expected centroid
        ("half out over the +x side wall", c(2.0, 1.0, -0.5), eye, 0.5, c(1.75, 1.0, -0.5)),
        ("corner over two side walls", c(2.0, 2.0, -0.5), eye, 0.25, c(1.75, 1.75, -0.5)),
        ("half through the surface", c(1.0, 1.0, 0.0), eye, 0.5, c(1.0, 1.0, -0.25)),
        ("lower 0.75 m below the bottom", c(1.0, 1.0, -1.25), eye, 0.25, c(1.0, 1.0, -0.875)),
        ("fully below the bottom", c(1.0, 1.0, -2.5), eye, 0.0, None),
        ("fully above the surface", c(1.0, 1.0, 1.0), eye, 0.0, None),
        ("fully outside the side", c(5.0, 1.0, -0.5), eye, 0.0, None),
    ]
    # the 4th case spans z -1.75..-0.75: water holds z -1..-0.75 = 0.25 m of height
    rows = []
    for name, ctr, rot, v_exp, c_exp in cases:
        v, cen = submerged_box(w, ctr, rot, h)
        rows.append({"case": name, "volume_expected": v_exp, "volume": v,
                     "centroid_err_m": None if c_exp is None else float(np.linalg.norm(cen - c_exp)),
                     "volume_abs_err": abs(v - v_exp)})
    # tilted box straddling the surface AND a side wall: no closed form, so compare with a midpoint grid (seed 0 tilt)
    q = np.zeros(4)
    mujoco.mju_euler2Quat(q, np.array([0.4, -0.3, 0.7]), "xyz")
    rot = np.zeros(9)
    mujoco.mju_quat2Mat(rot, q)
    ctr, hh = c(1.9, 1.0, -0.1), np.array([0.3, 0.2, 0.25])
    v, cen = submerged_box(w, ctr, rot, hh)
    k = 160
    g = (np.arange(k) + 0.5) / k * 2 - 1
    pts = np.stack(np.meshgrid(g * hh[0], g * hh[1], g * hh[2], indexing="ij"), -1).reshape(-1, 3)
    wp = ctr + pts @ rot.reshape(3, 3).T
    inside = np.all((wp >= w.lo) & (wp <= w.hi), axis=1)
    v_grid = float(inside.sum()) * 8.0 * float(np.prod(hh)) / k**3
    c_grid = wp[inside].mean(axis=0)
    rows.append({"case": "tilted box over a side wall and the surface vs 160^3 grid", "volume_expected": v_grid,
                 "volume": v, "centroid_err_m": float(np.linalg.norm(cen - c_grid)), "volume_abs_err": abs(v - v_grid)})
    return rows


# ---------------------------------------------------------------- D: added-mass candidates
def sphere_run(method, ratio, h, steps, c_drag=0.0, sample=()):
    r = 0.1
    vol = 4.0 / 3.0 * math.pi * r**3
    ms, ma = ratio * RHO_W * vol, ADDED_MASS_SPHERE * RHO_W * vol
    m = mujoco.MjModel.from_xml_string(
        f'<mujoco><option timestep="{h}" integrator="Euler"/><worldbody><body><freejoint/>'
        f'<geom type="sphere" size="{r}" density="{ratio * RHO_W}"/></body></worldbody></mujoco>')
    d = mujoco.MjData(m)
    if method == "inertia":  # mass up, gravity compensated back to the true weight
        m.body_mass[1], m.body_subtreemass[1] = ms + ma, ms + ma
        m.body_gravcomp[1] = ma / (ms + ma)
        mujoco.mj_setConst(m, d)
    mujoco.mj_forward(m, d)
    fb = np.array([0.0, 0.0, RHO_W * G * vol])
    hs, vs, out = hashlib.sha256(), {}, {}
    t0 = time.perf_counter()
    for n in range(1, steps + 1):
        f = fb - c_drag * d.qvel[:3]
        if method == "lag":
            f = f - ma * d.qacc[:3]  # acceleration of the previous step
        elif method == "twopass":
            d.xfrc_applied[1, :3] = f
            mujoco.mj_forward(m, d)
            f = f - ma * d.qacc[:3] * ms / (ms + ma)  # same-step acceleration a = F/(m+m_a)
        elif method == "inertia":
            m.body_mass[1], m.body_subtreemass[1], m.body_gravcomp[1] = ms + ma, ms + ma, ma / (ms + ma)
        d.xfrc_applied[1, :3] = f
        mujoco.mj_step(m, d)
        if n % 10 == 0:
            hs.update(d.qpos.tobytes())
        if n in sample:
            vs[n] = float(d.qvel[2])
    out["us_per_step"] = (time.perf_counter() - t0) / steps * 1e6
    out.update(hash=hs.hexdigest(), v=vs, v_final=float(d.qvel[2]), finite=bool(np.isfinite(d.qpos).all()),
               m=ms, ma=ma, vol=vol)
    return out


def added_mass_experiment(repeats=3):
    ratios = [5.0, 2.0, 1.5, 0.75, 0.5, 0.4, 0.25, 0.1]
    rows = []
    for h in (0.002, 0.01):
        n1, n2 = round(0.1 / h), round(0.2 / h)
        for ratio in ratios:
            a_exp = G * (1 - ratio) / (ratio + ADDED_MASS_SPHERE)
            for method in ("none", "lag", "twopass", "inertia"):
                r = sphere_run(method, ratio, h, n2, sample=(n1, n2))
                a = (r["v"][n2] - r["v"][n1]) / 0.1
                ms, ma, vol = r["m"], r["ma"], r["vol"]
                c = (ms + ma) / 0.25  # linear drag: time constant 0.25 s
                v_term = (1 - ratio) * RHO_W * vol * G / c
                steps = round(4.0 / h)
                s = sphere_run(method, ratio, h, steps, c_drag=c, sample=range(round(3.0 / h), steps + 1))
                dev = max(abs(v - v_term) for v in s["v"].values()) if s["finite"] else float("inf")
                rows.append({"h": h, "density_ratio": ratio, "method": method, "ma_over_m": ma / ms,
                             "accel_expected": a_exp, "accel_measured": a, "accel_error_pct": (a - a_exp) / a_exp * 100,
                             "stable": bool(s["finite"] and dev <= 1e-3 * abs(v_term)),
                             "max_dev_from_terminal_pct": dev / abs(v_term) * 100})
    cost, hashes = {}, {}
    for method in ("none", "lag", "twopass", "inertia"):
        runs = [sphere_run(method, 0.75, 0.002, 2000) for _ in range(repeats)]
        cost[method] = float(np.median([r["us_per_step"] for r in runs]))
        hashes[method] = len({r["hash"] for r in runs}) == 1
    return {"rows": rows, "us_per_step": cost, "hash_equal": hashes}


# ---------------------------------------------------------------- E: N-box scene, cost + hash
def nbox_scene(n, seed):
    rng = np.random.default_rng(seed)
    side = math.ceil(math.sqrt(n))
    boxes = []
    for i in range(n):
        gx, gy = divmod(i, side)
        yaw, tilt = rng.uniform(0, 2 * math.pi), rng.uniform(-0.3, 0.3, 2)
        q = np.zeros(4)
        mujoco.mju_euler2Quat(q, np.array([tilt[0], tilt[1], yaw]), "xyz")
        boxes.append({"half": tuple(rng.uniform(0.04, 0.08, 3)), "density": float(rng.uniform(0.2, 1.5)) * RHO_W,
                      "pos": ((gx - (side - 1) / 2) * 0.4 + rng.uniform(-0.03, 0.03),
                              (gy - (side - 1) / 2) * 0.4 + rng.uniform(-0.03, 0.03), float(rng.uniform(-0.6, 0.3))),
                      "quat": tuple(q)})
    return boxes


def nbox_experiment(n, seed, repeats=2, h=0.002, steps=500):
    boxes = nbox_scene(n, seed)
    water = Water(-1.0, 1.0, -1.0, 1.0, -1.0, 0.0)  # side walls cut through the grid: some boxes straddle/outside
    out, last = {}, {}
    for path in ("none", "xfrc", "xfrc_step12", "passive"):
        runs = [run_boxes(boxes, water, path, h, steps, floor_z=-1.0) for _ in range(repeats)]
        last[path] = runs[0]["qpos"]
        out[path] = {"us_per_step": float(np.median([r["us_per_step"] for r in runs])),
                     "cpu_us_per_step": float(np.median([r["cpu_us_per_step"] for r in runs])),
                     "hash_equal": len({r["hash"] for r in runs}) == 1, "hash": runs[0]["hash"][:16],
                     "finite": all(r["finite"] for r in runs)}
    out["max_abs_dqpos_vs_passive"] = {k: float(np.abs(last[k] - last["passive"]).max()) for k in ("xfrc", "xfrc_step12")}
    out["hash_equal_across_paths"] = {"xfrc_vs_passive": out["xfrc"]["hash"] == out["passive"]["hash"],
                                      "xfrc_step12_vs_passive": out["xfrc_step12"]["hash"] == out["passive"]["hash"]}
    out["n"], out["steps"], out["timestep"] = n, steps, h
    out["force_eval_us_per_box"] = force_eval_cost(boxes, water)
    return out


def force_eval_cost(boxes, water, reps=200):
    """Cost of the Python reference clip alone (no mj_step), per box, by where the box sits. Not a product number."""
    m = build_model(boxes, 0.002, floor_z=-1.0)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    kinds = {"outside_or_above": [], "fully_inside": [], "straddling": []}
    for bid in range(1, m.nbody):
        half = m.geom_size[m.body_geomadr[bid]]
        v, _ = submerged_box(water, d.xpos[bid], d.xmat[bid], half)
        full = 8.0 * float(np.prod(half))
        kinds["outside_or_above" if v == 0.0 else "fully_inside" if abs(v - full) < 1e-12 else "straddling"].append(bid)
    res = {}
    for k, ids in kinds.items():
        if not ids:
            res[k] = None
            continue
        t0 = time.perf_counter()
        for _ in range(reps):
            for bid in ids:
                body_wrench(m, d, bid, water, 0.5)
        res[k] = {"bodies": len(ids), "us_per_box": (time.perf_counter() - t0) / (reps * len(ids)) * 1e6}
    return res


def mechanism_cost(n, seed, steps=1000, repeats=3):
    """Cost of the force *delivery* alone: a constant per-body force written via xfrc_applied (before mj_step) vs
    via mjcb_passive + mj_applyFT, versus no force. Free boxes with no contacts, so mj_step itself is cheap."""
    boxes = [{"half": (0.05, 0.05, 0.05), "density": 500.0, "pos": (0.3 * (i % 10), 0.3 * (i // 10), 5.0),
              "quat": (1.0, 0.0, 0.0, 0.0)} for i in range(n)]
    f, zero = np.array([0.0, 0.0, 1.0]), np.zeros(3)
    out = {}
    for path in ("none", "xfrc", "xfrc_step12", "passive"):
        samples = []
        for _ in range(repeats):
            m = build_model(boxes, 0.002)
            d = mujoco.MjData(m)
            mujoco.mj_forward(m, d)
            if path == "passive":
                def cb(m_, d_):
                    for b in range(1, m_.nbody):
                        mujoco.mj_applyFT(m_, d_, f, zero, d_.xipos[b], b, d_.qfrc_passive)
                mujoco.set_mjcb_passive(cb)
            try:
                t0 = time.perf_counter()
                for _ in range(steps):
                    if path == "xfrc":
                        for b in range(1, m.nbody):
                            d.xfrc_applied[b, :3] = f
                        mujoco.mj_step(m, d)
                    elif path == "xfrc_step12":
                        mujoco.mj_step1(m, d)
                        for b in range(1, m.nbody):
                            d.xfrc_applied[b, :3] = f
                        mujoco.mj_step2(m, d)
                    else:
                        mujoco.mj_step(m, d)
                samples.append((time.perf_counter() - t0) / steps * 1e6)
            finally:
                mujoco.set_mjcb_passive(None)
        out[path] = float(np.median(samples))
    out["n"], out["steps"] = n, steps
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-boxes", type=int, default=50)
    ap.add_argument("--settle-s", type=float, default=12.0, help="sim seconds each equilibrium-draft run settles")
    ap.add_argument("--only", nargs="*", choices=["A_medium", "C_clip", "B_draft", "D_added_mass", "E0_mechanism", "E_nbox"],
                    help="run only these sections (default: all)")
    ap.add_argument("--json")
    args = ap.parse_args()
    result = {"machine": machine_spec(), "argv": sys.argv, "seed": args.seed}
    print(json.dumps(result, indent=1), flush=True)
    for key, fn in (("A_medium", medium_facts), ("C_clip", clip_checks),
                    ("B_draft", lambda: draft_experiment(args.seed, settle_s=args.settle_s)),
                    ("D_added_mass", added_mass_experiment),
                    ("E0_mechanism", lambda: mechanism_cost(args.n_boxes, args.seed)),
                    ("E_nbox", lambda: nbox_experiment(args.n_boxes, args.seed))):
        if args.only and key not in args.only:
            continue
        result[key] = fn()
        print(f"== {key}\n{json.dumps(result[key], indent=1)}", flush=True)
    result["uptime_end"] = machine_spec()["uptime"]
    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
