"""Attitude-control task: 360-degree pitch flip under thrust limits and disturbance.

Evaluator contract (fixed, NOT patchable by the loop):
  * success: |theta - 2pi| < 8 deg and |omega| < 0.15 rad/s for the whole last 0.3 s of a 3.6 s flight
  * MC disturbance model DISTURBANCE_SPEC and the held-out eval seeds
  * metric = success_rate - FUEL_TIEBREAK * mean_fuel_Ns   (success first, fuel breaks ties)
"""
from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor

import cma
import mujoco
import numpy as np

from article import Article, pitch_of

TARGET = 2.0 * math.pi
T_END = 3.6
TOL_THETA = math.radians(8.0)
TOL_OMEGA = 0.15
HOLD_S = 0.3
FUEL_TIEBREAK = 1e-4  # metric = success_rate - FUEL_TIEBREAK * fuel[N*s]
FUEL_COST_W = 0.01

# Disturbance model (the "assumptions panel" for this task). Changing it needs human approval.
DISTURBANCE_SPEC = {
    "mass_ratio": ("uniform", 0.95, 1.05),          # inertia scales with mass
    "com_x": ("uniform", -0.03, 0.03),              # m
    "com_z": ("uniform", -0.02, 0.02),              # m
    "thrust_gain": ("uniform", 0.90, 1.10),         # global thrust gain
    "thruster_mismatch": ("uniform", 0.98, 1.02),   # per thruster
    "delay_steps": ("int", 0, 6),                   # sensor delay in steps of 5 ms (0..30 ms)
    "sigma_theta": 0.003,                           # rad
    "sigma_omega": 0.01,                            # rad/s
}
EVAL_SEED = 777_001      # held-out MC set used for every keep/discard decision
CONFIRM_SEED = 888_002   # fresh set, used only once at the end


def sample_disturbances(seed: int, n: int, spec: dict | None = None) -> list[dict]:
    spec = spec or DISTURBANCE_SPEC
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        def u(key):
            _, lo, hi = spec[key]
            return float(rng.uniform(lo, hi))
        mr = u("mass_ratio")
        s = {
            "params": {"mass": 10.0 * mr, "inertia_scale": mr, "com_x": u("com_x"), "com_z": u("com_z"), "thrust_gain": u("thrust_gain")},
            "mismatch": rng.uniform(*spec["thruster_mismatch"][1:], size=10).tolist(),
            "delay": int(rng.integers(spec["delay_steps"][1], spec["delay_steps"][2] + 1)),
            "noise_seed": int(rng.integers(0, 2**31 - 1)),
            "sigma_theta": spec["sigma_theta"], "sigma_omega": spec["sigma_omega"],
        }
        out.append(s)
    return out


NOMINAL_SAMPLE = {"params": {}, "mismatch": [1.0] * 10, "delay": 2, "noise_seed": 1, "sigma_theta": 0.0, "sigma_omega": 0.0}

# ---------------------------------------------------------------- controllers

SCHEDULE_BOUNDS = [(0.2, 2.0), (0.0, 1.5), (0.2, 2.0), (0.3, 1.0)]       # t_acc, t_coast, t_dec, amp
SCHEDULE_NAMES = ["t_acc", "t_coast", "t_dec", "amp"]
PD_BOUNDS_KD = [(0.2, 25.0), (0.0, 12.0)]                                # kp, kd
PD_BOUNDS_KP_ONLY = [(0.2, 25.0)]
PD_NAMES = ["kp", "kd"]


def param_space(ctrl: dict) -> tuple[list[tuple[float, float]], list[str]]:
    fam = ctrl["family"]
    pd_b = PD_BOUNDS_KD if ctrl["pd"]["kd_enabled"] else PD_BOUNDS_KP_ONLY
    pd_n = PD_NAMES if ctrl["pd"]["kd_enabled"] else PD_NAMES[:1]
    b, n = [], []
    if fam in ("schedule", "hybrid"):
        b += SCHEDULE_BOUNDS
        n += SCHEDULE_NAMES
    if fam in ("pd", "hybrid"):
        b += pd_b
        n += pd_n
    if fam == "pd" and ctrl["allocation"] == "bangbang":
        b += [(0.0, 0.8)]
        n += ["deadband"]
    return b, n


def decode(ctrl: dict, x01: np.ndarray) -> dict:
    b, n = param_space(ctrl)
    return {name: lo + float(v) * (hi - lo) for (lo, hi), name, v in zip(b, n, np.clip(x01, 0, 1))}


class Controller:
    """u in [-1, 1] = normalised pitch command. Positive u fires the p+ thruster group."""

    def __init__(self, ctrl: dict, p: dict, alpha_nom: float, dt: float, t_end: float = T_END):
        self.fam = ctrl["family"]
        self.alloc = ctrl["allocation"]
        self.p = p
        self.dt = dt
        self.kd_enabled = ctrl["pd"]["kd_enabled"]
        if self.fam in ("schedule", "hybrid"):
            self.t1 = p["t_acc"]
            self.t2 = p["t_acc"] + p["t_coast"]
            self.t3 = self.t2 + p["t_dec"]
            self.amp = p["amp"]
        if self.fam == "hybrid":
            n = int(t_end / dt) + 2
            th, om = np.zeros(n), np.zeros(n)
            for k in range(1, n):
                u = self.ff((k - 1) * dt)
                om[k] = om[k - 1] + alpha_nom * u * dt
                th[k] = th[k - 1] + om[k - 1] * dt + 0.5 * alpha_nom * u * dt * dt
            self.th_ref, self.om_ref = th, om

    def ff(self, t: float) -> float:
        if t < self.t1:
            return self.amp
        if t < self.t2:
            return 0.0
        if t < self.t3:
            return -self.amp
        return 0.0

    def __call__(self, k: int, t: float, th: float, om: float) -> float:
        fam = self.fam
        if fam == "schedule":
            return self.ff(t)
        kp = self.p["kp"]
        kd = self.p["kd"] if self.kd_enabled else 0.0
        if fam == "pd":
            v = kp * (TARGET - th) - kd * om
        else:  # hybrid: track the nominal schedule's reference, then hold the target
            if t < self.t3:
                kk = min(k, len(self.th_ref) - 1)
                v = self.ff(t) + kp * (self.th_ref[kk] - th) + kd * (self.om_ref[kk] - om)
            else:
                v = kp * (TARGET - th) - kd * om
        if self.alloc == "bangbang":
            db = self.p.get("deadband", 0.2)
            return 0.0 if abs(v) < db else math.copysign(1.0, v)
        return max(-1.0, min(1.0, v))


# ---------------------------------------------------------------- rollout

_ART: dict[str, Article] = {}


def get_article(hw: dict) -> Article:
    key = f"{hw['ctrl_hi']}|{hw['extra_pair_arm']}"  # t_end is not part of the model
    a = _ART.get(key)
    if a is None:
        a = Article(extra_pair_arm=hw["extra_pair_arm"], ctrl_hi=hw["ctrl_hi"])
        _ART[key] = a
    return a


def rollout(hw: dict, ctrl: dict, p: dict, sample: dict, record: bool = False) -> dict:
    art = get_article(hw)
    m, d = art.m, art.d
    art.set_params(sample["params"], np.array(sample["mismatch"][: art.nu]))
    art.reset()
    mp = ctrl.get("model_params", {})  # the controller's own model of the plant (e.g. calibrated values)
    alpha_nom = art.alpha_nominal * mp.get("thrust_gain", 1.0) / mp.get("inertia_scale", 1.0)
    t_end = hw.get("t_end", T_END)
    controller = Controller(ctrl, p, alpha_nom, art.dt, t_end)
    rng = np.random.default_rng(sample["noise_seed"])
    n = int(round(t_end / art.dt))
    delay = sample["delay"]
    th_hist = np.zeros(n + 1)
    om_hist = np.zeros(n + 1)
    th_true = np.zeros(n + 1)
    om_true = np.zeros(n + 1)
    nth = rng.normal(0, sample["sigma_theta"], n + 1) if sample["sigma_theta"] else np.zeros(n + 1)
    nom = rng.normal(0, sample["sigma_omega"], n + 1) if sample["sigma_omega"] else np.zeros(n + 1)
    theta = 0.0
    fuel = 0.0
    gear = m.actuator_gear[:, 2]
    pp, pm = art.p_plus, art.p_minus
    hi = art.ctrl_hi
    thr_axis = np.zeros(art.nu)
    ctrl_arr = d.ctrl
    for k in range(n):
        # truth at step k
        w = pitch_of(d.qpos[3:7])
        theta += (w - theta + math.pi) % (2 * math.pi) - math.pi
        om = d.qvel[4]
        th_true[k], om_true[k] = theta, om
        th_hist[k] = theta + nth[k]
        om_hist[k] = om + nom[k]
        kk = max(0, k - delay)
        u = controller(k, k * art.dt, th_hist[kk], om_hist[kk])
        ctrl_arr[:] = 0.0
        if u > 0:
            for i in pp:
                ctrl_arr[i] = hi * u
        elif u < 0:
            for i in pm:
                ctrl_arr[i] = -hi * u
        fuel += float(np.dot(ctrl_arr, gear)) * art.dt
        mujoco.mj_step(m, d)
    w = pitch_of(d.qpos[3:7])
    theta += (w - theta + math.pi) % (2 * math.pi) - math.pi
    th_true[n], om_true[n] = theta, d.qvel[4]
    nh = int(HOLD_S / art.dt)
    e_th = float(np.max(np.abs(th_true[n - nh:] - TARGET)))
    e_om = float(np.max(np.abs(om_true[n - nh:])))
    ok = bool(e_th < TOL_THETA and e_om < TOL_OMEGA and np.all(np.isfinite(th_true)))
    cost = min(50.0, (e_th / TOL_THETA) ** 2 + (e_om / TOL_OMEGA) ** 2) + FUEL_COST_W * fuel
    out = {"ok": ok, "e_theta_deg": math.degrees(e_th), "e_omega": e_om, "fuel": fuel, "cost": cost}
    if record:
        out["theta"] = th_true
        out["omega"] = om_true
    return out


def _eval_task(args):
    hw, ctrl, p, samples = args
    rs = [rollout(hw, ctrl, p, s) for s in samples]
    return rs


_POOL: ProcessPoolExecutor | None = None


def pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        import multiprocessing as mp
        _POOL = ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) - 1), mp_context=mp.get_context("spawn"))
    return _POOL


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def mc_eval(hw: dict, ctrl: dict, p: dict, samples: list[dict]) -> dict:
    chunks = [samples[i::max(1, (os.cpu_count() or 4) - 1)] for i in range(max(1, (os.cpu_count() or 4) - 1))]
    chunks = [c for c in chunks if c]
    res = []
    for r in pool().map(_eval_task, [(hw, ctrl, p, c) for c in chunks]):
        res.extend(r)
    k = sum(r["ok"] for r in res)
    n = len(res)
    lo, hi = wilson(k, n)
    fuel = float(np.mean([r["fuel"] for r in res]))
    return {
        "n": n, "k": k, "success_rate": k / n, "ci_low": lo, "ci_high": hi, "fuel_mean": fuel,
        "metric": k / n - FUEL_TIEBREAK * fuel,
        "median_err_theta_deg": float(np.median([r["e_theta_deg"] for r in res])),
    }


def train(hw: dict, ctrl: dict, budget_rollouts: int, seed: int) -> dict:
    """CMA-ES over the controller's parameters; fixed rollout budget, common random numbers."""
    bounds, names = param_space(ctrl)
    dim = len(bounds)
    n_train = ctrl["train_samples"]
    nom = dict(NOMINAL_SAMPLE, params=ctrl.get("model_params", {}))
    samples = [nom] if n_train <= 0 else sample_disturbances(seed + 17, n_train)
    popsize = ctrl["cma_popsize"]
    gens = max(1, budget_rollouts // (popsize * len(samples)))
    dim_cma = max(2, dim)  # cma needs dim >= 2; extra coordinates are ignored by decode()
    es = cma.CMAEvolutionStrategy(
        [0.5] * dim_cma, ctrl["cma_sigma0"],
        {"bounds": [0, 1], "popsize": popsize, "seed": seed, "verbose": -9, "maxiter": gens},
    )
    best_x, best_c, used, g = None, 1e18, 0, 0
    ex = pool()
    while g < gens and not es.stop():
        xs = es.ask()
        tasks = [(hw, ctrl, decode(ctrl, np.asarray(x)), samples) for x in xs]
        costs = []
        for rs in ex.map(_eval_task, tasks):
            costs.append(float(np.mean([r["cost"] for r in rs])))
        used += len(xs) * len(samples)
        es.tell(xs, costs)
        i = int(np.argmin(costs))
        if costs[i] < best_c:
            best_c, best_x = costs[i], np.asarray(xs[i])
        g += 1
    return {"x": best_x.tolist(), "params": decode(ctrl, best_x), "train_cost": best_c, "rollouts_used": used, "generations": g}
