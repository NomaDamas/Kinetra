"""Roadster thruster-flip Go/No-Go spike.  Run:  .venv/bin/python run_spike.py [--quick]

Pipeline per case:  necessary-condition screen -> CMA-ES search (MuJoCo rollouts) -> verdict.
Best feasible case additionally: robustification, Monte-Carlo (held-out samples), trajectory export.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cma
import mujoco
import numpy as np

from roadster import (G0, GROUP_NAMES, NGROUP, NPARAM, THRUSTERS, WIN_GROUP, WIN_NAMES, Config, Sim,
                      necessary_screen)

HERE = Path(__file__).parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
QUICK = "--quick" in sys.argv
SEED = 20260001
SEARCH_BUDGET_S = 15.0 if QUICK else 40.0     # wall-clock budget for one CMA-ES search (spec: < 60 s)

# Ramp launch assumptions (editable in the "assumptions panel")
RAMP = dict(scenario="ramp", ramp_speed=22.0, ramp_angle=np.deg2rad(25.0), ramp_height=2.2, vz_max=6.0, w_max=3.0)


def cma_search(sim: Sim, budget_s: float, seed: int, pop0: int = 48, x_init=None, sigma0=0.3):
    """CMA-ES with IPOP-style restarts (pop doubles), stops at first success or wall-clock budget.
    All rollouts of one generation are evaluated in parallel by mujoco.rollout (thread pool)."""
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    e0 = sim.evals
    best = dict(cost=np.inf, x=None, success=False)
    pop, restarts, log = pop0, 0, []
    while time.perf_counter() - t0 < budget_s and not best["success"]:
        x0 = rng.uniform(0.2, 0.6, NPARAM) if (x_init is None or restarts > 0) else x_init
        es = cma.CMAEvolutionStrategy(x0, sigma0, dict(bounds=[0, 1], popsize=pop, seed=int(rng.integers(1 << 30)),
                                                       verbose=-9, tolfun=1e-9, tolx=1e-9))
        g = 0
        while not es.stop() and time.perf_counter() - t0 < budget_s and g < 150:
            X = np.array(es.ask())
            m, _, _ = sim.evaluate(X)
            es.tell(X, m["cost"])
            g += 1
            if m["success"].any():   # any verified-feasible candidate wins (lowest-cost among them)
                i = int(np.where(m["success"], m["cost"], np.inf).argmin())
                best = dict(cost=float(m["cost"][i]), x=X[i].copy(), success=True)
                break
            i = int(m["cost"].argmin())
            if m["cost"][i] < best["cost"]:
                best = dict(cost=float(m["cost"][i]), x=X[i].copy(), success=False)
        log.append(dict(restart=restarts, popsize=pop, generations=g, best_cost=best["cost"],
                        t=round(time.perf_counter() - t0, 2)))
        restarts += 1
        pop = min(pop * 2, 384)
    best.update(wall_s=time.perf_counter() - t0, evals=sim.evals - e0, restarts=restarts, log=log)
    return best


def robustify(sim: Sim, x, seed: int, budget_s: float, k: int = 24):
    """Refine a nominal solution against k fixed perturbed models (sample-average cost).
    Samples used here (seed) are disjoint from the held-out MC samples (different seed)."""
    rng = np.random.default_rng(seed)
    models, _ = sim.perturbed_models(rng, k)
    t0 = time.perf_counter()
    es = cma.CMAEvolutionStrategy(x, 0.05, dict(bounds=[0, 1], popsize=32, seed=seed % (1 << 30), verbose=-9))
    best_x, best_rate, best_c = x.copy(), -1.0, np.inf
    e0 = sim.evals
    while time.perf_counter() - t0 < budget_s:
        X = np.array(es.ask())
        costs = np.empty(len(X))
        succ = np.empty(len(X))
        # evaluate every candidate on all k models: batch = len(X)*k rollouts
        ctrl, thr = sim.controls(X)
        ctrl_b = np.repeat(ctrl, k, axis=0)
        thr_b = np.repeat(thr, k, axis=0)
        st = sim.run(ctrl_b, models * len(X))
        m = sim.metrics(st, thr_b)
        c = m["cost"].reshape(len(X), k)
        s_ = m["success"].reshape(len(X), k)
        costs, succ = c.mean(1) + 2.0 * (1 - s_.mean(1)), s_.mean(1)
        es.tell(X, costs)
        i = int(costs.argmin())
        if succ[i] > best_rate or (succ[i] == best_rate and costs[i] < best_c):
            best_x, best_rate, best_c = X[i].copy(), float(succ[i]), float(costs[i])
        if best_rate >= 1.0 and time.perf_counter() - t0 > budget_s * 0.4:
            break
    return best_x, dict(train_success=best_rate, evals=sim.evals - e0, wall_s=time.perf_counter() - t0)


def monte_carlo(sim: Sim, x, n: int, seed: int):
    """Held-out MC: mass +-5 %, per-thruster thrust +-10 %, COM offset (+-0.15 m x, +-0.10 m z)."""
    rng = np.random.default_rng(seed)
    models, info = sim.perturbed_models(rng, n)
    ctrl, thr = sim.controls(x[None])
    t0 = time.perf_counter()
    st = sim.run(np.repeat(ctrl, n, 0), models)
    m = sim.metrics(st, np.repeat(thr, n, 0))
    wall = time.perf_counter() - t0
    fails = {k: int((~v).sum()) for k, v in m["ok"].items() if (~v).any()}
    p = float(m["success"].mean())
    # Wilson 95 % CI
    z = 1.96
    ph = (p + z * z / (2 * n)) / (1 + z * z / n)
    hw = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return dict(n=n, success_rate=p, ci95=[float(max(0, ph - hw)), float(min(1, ph + hw))], failure_counts=fails, wall_s=wall,
                mean_vz_td=float(m["vz_td"].mean()), max_vz_td=float(m["vz_td"].max()),
                mean_fuel_kg=float(m["fuel"].mean()))


def describe(sim: Sim, x):
    ts, du, ma = sim.decode(x)
    return [dict(window=WIN_NAMES[i], thruster_group=GROUP_NAMES[WIN_GROUP[i]], t_start_s=round(float(ts[0, i]), 3),
                 duration_s=round(float(du[0, i]), 3), throttle=round(float(ma[0, i]), 3),
                 thrust_N=round(float(ma[0, i] * sim.cfg.fmax), 1)) for i in range(NGROUP)]


def run_case(name, cfg_kwargs, budget, seed, run_cma=True):
    cfg = Config(**cfg_kwargs)
    sim = Sim(cfg)
    screen = necessary_screen(cfg, sim)
    res = dict(name=name, fmax_N=cfg.fmax, scenario=cfg.scenario, screen=screen)
    if screen["verdict"] == "INFEASIBLE":
        res["verdict"] = "INFEASIBLE (necessary condition violated: " + ", ".join(screen["failed"]) + ")"
        if run_cma:   # sanity: show the optimizer indeed cannot do it
            b = cma_search(sim, min(budget, 6.0), seed)
            res["sanity_cma"] = dict(found=b["success"], best_cost=b["cost"], evals=b["evals"], wall_s=b["wall_s"])
        return res, sim, None
    b = cma_search(sim, budget, seed)
    mb = sim.evaluate(b["x"][None])[0]
    res["best_candidate_failed_checks"] = [k for k, v in mb["ok"].items() if not v[0]]
    res["best_candidate_metrics"] = {k: round(float(mb[k][0]), 3) for k in
                                     ("th_td", "th_end", "vz_td", "w_td", "fuel", "post_imp", "err_td")}
    res.update(cma=dict(found=b["success"], best_cost=b["cost"], evals=b["evals"], wall_s=round(b["wall_s"], 2),
                        restarts=b["restarts"], log=b["log"]))
    if b["success"]:
        res["verdict"] = "FEASIBLE (solution found within model assumptions; MuJoCo rollout verified)"
        res["schedule"] = describe(sim, b["x"])
    else:
        res["verdict"] = (f"NOT_FOUND (weak evidence: no feasible schedule in {b['evals']} evals / "
                          f"{b['wall_s']:.0f} s; screen passed so NOT proven impossible)")
    return res, sim, b


def export_trajectory(sim: Sim, x, path: Path, stride=3, mc_info=None, meta=None):
    """Re-simulate with mj_step (independent of mujoco.rollout) and dump a Three.js-friendly JSON."""
    cfg = sim.cfg
    m = sim.model
    d = mujoco.MjData(m)
    mujoco.mj_setState(m, d, sim.x0, mujoco.mjtState.mjSTATE_FULLPHYSICS)
    ctrl, thr = sim.controls(x[None])
    ctrl, thr = ctrl[0], thr[0]
    wheels = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"wheel_{n}") for n in ("fl", "fr", "rl", "rr")]
    frames, rec_state = [], []
    for k in range(cfg.nstep):
        if k % stride == 0:
            frames.append(dict(
                t=round(k * cfg.dt, 4),
                p=[round(float(v), 4) for v in d.qpos[:3]],
                q=[round(float(v), 5) for v in d.qpos[3:7]],                # MuJoCo order w,x,y,z
                wheel_spin=[round(float(v), 4) for v in d.qpos[7:11]],
                thr=[round(float(v), 3) for v in thr[k]],                    # 0..1 per thruster
            ))
        rec_state.append(np.concatenate(([d.time], d.qpos, d.qvel)))
        d.ctrl[:] = ctrl[k]
        mujoco.mj_step(m, d)
    # consistency check vs. rollout
    st = sim.run(ctrl[None], None)[0]
    # rollout state[k] is the state AFTER step k; rec_state[k] is BEFORE step k -> shift by one
    dev = float(np.abs(np.array(rec_state)[1:, 1:] - st[:-1, 1:]).max())
    mm = sim.metrics(st[None], thr[None])
    th = mm["theta"][0]
    itd = int(mm["itd"][0])
    doc = dict(
        schema="roadster-flip-trajectory/v1",
        coord="MuJoCo world: x forward, y left, z up (Z-up). Three.js: convert via (x,y,z)->(x,z,-y).",
        quat_order="wxyz (MuJoCo); Three.js Quaternion is xyzw",
        dt=cfg.dt * stride, sim_dt=cfg.dt, n_frames=len(frames),
        body=dict(box_size=[cfg.length, cfg.width, cfg.height], com_local=[0, 0, 0],
                  chassis_z_offset=float(sim.bz0 + (sim.bz1 - sim.bz0) / 2),
                  chassis_half=[cfg.length / 2, cfg.width / 2, (sim.bz1 - sim.bz0) / 2],
                  wheel_radius=cfg.wheel_r, wheel_half_width=cfg.wheel_hw,
                  wheels_local=[[1.3, 0.85, -cfg.height / 2 + cfg.wheel_r], [1.3, -0.85, -cfg.height / 2 + cfg.wheel_r],
                                [-1.3, 0.85, -cfg.height / 2 + cfg.wheel_r], [-1.3, -0.85, -cfg.height / 2 + cfg.wheel_r]],
                  mass_kg=sim.inertia["mass"]),
        thrusters=[dict(name=t[0], group=GROUP_NAMES[t[1]], pos_local=list(t[2:5]), force_dir_local=list(t[5]),
                        fmax_N=cfg.fmax) for t in THRUSTERS],
        events=dict(touchdown_t=round(itd * cfg.dt, 3), total_flip_rad=float(th[-1]),
                    pitch_at_touchdown_deg=float(np.degrees(th[itd])), vz_touchdown=float(mm["vz_td"][0]),
                    fuel_kg=float(mm["fuel"][0])),
        verification=dict(max_abs_state_dev_vs_rollout=dev, success=bool(mm["success"][0])),
        schedule=describe(sim, x), meta=meta or {}, frames=frames,
    )
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return doc, th, mm


def plot(sim: Sim, x, th, path: Path):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        return f"matplotlib unavailable: {e}"
    cfg = sim.cfg
    ctrl, thr = sim.controls(x[None])
    st = sim.run(ctrl, None)[0]
    nq = sim.nq
    pos = st[:, 1:4]
    q = st[:, 4:8]
    t = np.arange(cfg.nstep) * cfg.dt
    fig, ax = plt.subplots(3, 1, figsize=(10, 9))
    ax[0].plot(pos[:, 0], pos[:, 2], "k-", lw=0.8)
    for k in range(0, cfg.nstep, 28):
        qw, qx, qy, qz = q[k]
        R20 = 2 * (qx * qz - qw * qy)
        R00 = 1 - 2 * (qy**2 + qz**2)
        a = np.arctan2(-R20, R00)  # pitch (+ nose down)
        c, s = np.cos(a), np.sin(a)
        # body x axis in (x,z) plane: (cos a, -sin a); body z axis: (sin a, cos a)
        L, H = cfg.length / 2, cfg.height / 2
        pts = np.array([[-L, -H], [L, -H], [L, H], [-L, H], [-L, -H]])
        wx = pos[k, 0] + pts[:, 0] * c + pts[:, 1] * s
        wz = pos[k, 2] - pts[:, 0] * s + pts[:, 1] * c
        ax[0].plot(wx, wz, color=plt.cm.viridis(k / cfg.nstep), lw=1)
        ax[0].plot([wx[0], wx[1]], [wz[0], wz[1]], color="r", lw=1.5) if False else None
    ax[0].axhline(0, color="gray")
    ax[0].set_aspect("equal")
    ax[0].set_title("side view (x fwd), body outline every 0.11 s; flip direction: see pitch curve")
    ax[1].plot(t, np.degrees(th), label="pitch [deg] (unwrapped)")
    ax[1].plot(t, pos[:, 2] * 50, label="z * 50 [m]")
    ax[1].legend()
    ax[1].grid()
    for g, nm in enumerate(GROUP_NAMES):
        idx = [i for i, tt in enumerate(THRUSTERS) if tt[1] == g]
        ax[2].plot(t, thr[0][:, idx[0]] + 1.2 * g, label=nm)
    ax[2].legend(fontsize=7)
    ax[2].set_title("thruster throttle by group (offset)")
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    return "ok"


def main():
    T0 = time.perf_counter()
    report = dict(env=dict(mujoco=mujoco.__version__, cma=cma.__version__, rollout="mujoco.rollout (thread pool)",
                           quick=QUICK, search_budget_s=SEARCH_BUDGET_S), cases=[])
    import os

    report["env"]["cpus"] = os.cpu_count()

    print("== 1. screen sweep (ramp)")
    for f in (300, 1000, 2000, 3000, 4000, 5000):
        cfg = Config(fmax=f, **RAMP)
        sc = necessary_screen(cfg, Sim(cfg, nthread=1))
        a = sc["angular_impulse_time"]
        print(f"  Fmax={f:5d} N  {sc['verdict']:12s} t_rot_min={a['t_min_s']:.2f}s vs t_flight_ub={a['flight_time_upper_bound_s']:.2f}s "
              f"min_fuel={sc['propellant']['min_fuel_kg']:.1f} kg")
    cfg = Config(fmax=8000, scenario="standing")
    sc = necessary_screen(cfg, Sim(cfg, nthread=1))
    print(f"  standing Fmax=8000 -> {sc['verdict']} {sc['failed']}")
    cfg = Config(fmax=1500, scenario="standing")
    sc = necessary_screen(cfg, Sim(cfg, nthread=1))
    print(f"  standing Fmax=1500 -> {sc['verdict']} {sc['failed']}")

    print("== 2. cases")
    cases = [
        ("ramp_300N_underpowered", dict(fmax=300, **RAMP), 6.0),
        ("ramp_2000N", dict(fmax=2000, **RAMP), SEARCH_BUDGET_S),
        ("ramp_3000N_marginal", dict(fmax=3000, **RAMP), SEARCH_BUDGET_S),
        ("ramp_5000N_nominal", dict(fmax=5000, **RAMP), SEARCH_BUDGET_S),
        ("standing_1500N", dict(fmax=1500, scenario="standing"), 6.0),
        ("standing_15000N", dict(fmax=15000, scenario="standing", vz_max=6.0, w_max=3.0), SEARCH_BUDGET_S),
    ]
    bests = {}
    for name, kw, bud in cases:
        res, sim, b = run_case(name, kw, bud, SEED)
        report["cases"].append(res)
        bests[name] = (sim, b)
        c = res.get("cma")
        if "best_candidate_failed_checks" in res:
            print(f"      best candidate fails: {res['best_candidate_failed_checks']} {res['best_candidate_metrics']}")
        print(f"  {name:26s} screen={res['screen']['verdict']:12s} -> {res['verdict'][:60]}"
              + (f" | evals={c['evals']} wall={c['wall_s']}s best_cost={c['best_cost']:.3f}" if c else ""))

    # ---- hero case: first FEASIBLE ramp case with highest fmax
    hero = None
    for name in ("ramp_5000N_nominal", "ramp_3000N_marginal", "ramp_2000N"):
        sim, b = bests[name]
        if b is not None and b["success"]:
            hero = name
            break
    if hero is None:
        print("NO FEASIBLE CASE FOUND -> no MC / export")
        report["verdict"] = "NO-GO"
    else:
        sim, b = bests[hero]
        print(f"== 3. hero = {hero}; search time {b['wall_s']:.1f}s, {b['evals']} evals")
        b2 = cma_search(sim, 30.0, SEED)   # determinism check: same seed, same budget -> same optimum
        det = bool(np.array_equal(b2["x"], b["x"])) and b2["evals"] == b["evals"]
        report["determinism_same_seed_identical_solution"] = det
        print(f"  determinism (re-run same seed): identical solution = {det}")
        mc_nom = monte_carlo(sim, b["x"], 100, SEED + 1)
        print(f"  MC nominal-optimum: {mc_nom['success_rate']*100:.0f}% (CI {mc_nom['ci95'][0]:.2f}-{mc_nom['ci95'][1]:.2f}) "
              f"fails={mc_nom['failure_counts']} wall={mc_nom['wall_s']:.2f}s")
        xr, rinfo = robustify(sim, b["x"], SEED + 2, 10.0 if QUICK else 25.0)
        mc_rob = monte_carlo(sim, xr, 100, SEED + 1)
        nomr = sim.evaluate(xr[None])[0]["success"][0]
        print(f"  robustified (train {rinfo['train_success']:.2f}, {rinfo['evals']} evals, {rinfo['wall_s']:.0f}s): "
              f"held-out MC {mc_rob['success_rate']*100:.0f}% (CI {mc_rob['ci95'][0]:.2f}-{mc_rob['ci95'][1]:.2f}) "
              f"fails={mc_rob['failure_counts']} nominal_ok={bool(nomr)}")
        mc_big = monte_carlo(sim, xr, 500, SEED + 3)
        print(f"  robustified MC n=500: {mc_big['success_rate']*100:.1f}% CI {mc_big['ci95']} wall={mc_big['wall_s']:.2f}s")
        final_x = xr if nomr else b["x"]
        doc, th, mm = export_trajectory(sim, final_x, OUT / "trajectory.json",
                                        meta=dict(case=hero, mc_success_rate=mc_rob["success_rate"],
                                                  note="simplified rigid-body model, needs precise validation"))
        pr = plot(sim, final_x, th, OUT / "flip.png")
        print(f"  trajectory.json frames={doc['n_frames']} dev_vs_rollout={doc['verification']['max_abs_state_dev_vs_rollout']:.2e}"
              f" events={doc['events']} plot={pr}")
        report.update(hero=hero, hero_nominal_solution=describe(sim, b["x"]), mc_nominal_optimum=mc_nom,
                      robustify=rinfo, mc_robustified=mc_rob, mc_robustified_500=mc_big,
                      hero_final_schedule=describe(sim, final_x), hero_params_unit=final_x.tolist(),
                      events=doc["events"], model=dict(mass=sim.inertia["mass"], Iyy=sim.inertia["Iyy"]))
        report["verdict"] = "GO"
    report["total_wall_s"] = time.perf_counter() - T0
    # rollout throughput
    sim = Sim(Config(fmax=5000, **RAMP))
    X = np.random.default_rng(0).random((480, NPARAM))
    t = time.perf_counter()
    sim.evaluate(X)
    dt = time.perf_counter() - t
    report["throughput"] = dict(rollouts_per_s=480 / dt, steps_per_rollout=sim.cfg.nstep, threads=sim.nthread)
    print(f"== throughput: {480/dt:.0f} rollouts/s ({sim.cfg.nstep} steps each, {sim.nthread} threads)")
    (OUT / "report.json").write_text(json.dumps(report, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    print(f"TOTAL wall {report['total_wall_s']:.1f}s")


if __name__ == "__main__":
    main()
