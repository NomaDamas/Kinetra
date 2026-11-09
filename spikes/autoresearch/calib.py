"""Calibration: fit simulator parameters to a reference trajectory and say which ones the data constrains.

Pipeline
  trace(s) (synthetic from a hidden model + sensor noise, OR CSV from a real rig)
    -> MAP fit (CMA-ES global [optional] + scipy least_squares) in prior-normalised coordinates
    -> Laplace posterior  C = (J^T J / infl + I)^-1   (J = d(whitened residual)/d(theta), theta in prior-sd units)
    -> identifiability: SVD of J, per-parameter contraction = posterior_sd / prior_sd, parametric bootstrap
    -> Assumption-compatible JSON (normal(mean=fit, std=posterior sd)); NON-identified params keep their PRIOR.

Noise model: pos sigma 2 mm, attitude sigma 3 mrad (synthetic). For real data pass the sensor sigmas explicitly.
"""
from __future__ import annotations

import copy
import csv
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor

import cma
import mujoco
import numpy as np
from scipy.optimize import least_squares

from article import NOMINAL, PARAM_KEYS, PARAM_LABELS, PARAM_UNITS, Article

SIGMA_POS = 0.002
SIGMA_ROT = 0.003
SAMPLE_DT = 0.02  # 50 Hz tracker

# key: (prior mean, prior sd, lower bound, upper bound)
PRIORS = {
    "mass": (10.0, 1.0, 5.0, 20.0),
    "com_x": (0.0, 0.03, -0.2, 0.2),
    "com_z": (0.0, 0.03, -0.1, 0.1),
    "inertia_scale": (1.0, 0.15, 0.5, 2.0),
    "thrust_gain": (1.0, 0.10, 0.5, 1.5),
    "lin_damping": (0.4, 0.4, 0.0, 3.0),
    "rot_damping": (0.1, 0.1, 0.0, 1.5),
    "contact_timeconst": (0.03, 0.01, 0.01, 0.1),
    "contact_dampratio": (0.6, 0.2, 0.2, 2.0),
}
# the hidden "real system" (synthetic ground truth; NEVER visible to the fitter)
HIDDEN_TRUTH = {
    "mass": 11.2, "com_x": 0.020, "com_z": -0.012, "inertia_scale": 1.12, "thrust_gain": 0.93,
    "lin_damping": 0.80, "rot_damping": 0.25, "contact_timeconst": 0.045, "contact_dampratio": 0.85,
}

_ART: Article | None = None


def art() -> Article:
    global _ART
    if _ART is None:
        _ART = Article(extra_pair_arm=None)
    return _ART


# ---------------------------------------------------------------- simulation of a test motion


def simulate(exc: dict, p: dict) -> dict:
    """exc: {T, z0, pitch0, vx0, added_mass, pulses:[{thr:[ids], t_on, dur, level}]}. p: physical params (all keys)."""
    a = art()
    q = dict(NOMINAL)
    q.update(p)
    dm = float(exc.get("added_mass", 0.0))
    if dm:  # known calibration weight at the geometric centre: mass up, COM pulled toward centre
        m0 = q["mass"]
        q["com_x"] *= m0 / (m0 + dm)
        q["com_z"] *= m0 / (m0 + dm)
        q["mass"] = m0 + dm
    a.set_params(q)
    pitch0 = float(exc.get("pitch0", 0.0))
    a.reset(pos=(0.0, 0.0, exc["z0"]), quat=(math.cos(pitch0 / 2), 0.0, math.sin(pitch0 / 2), 0.0))
    a.d.qvel[0] = float(exc.get("vx0", 0.0))
    m, d = a.m, a.d
    n = int(round(exc["T"] / a.dt))
    stride = int(round(SAMPLE_DT / a.dt))
    pulses = exc["pulses"]
    ts, pos, quat = [], [], []
    for k in range(n + 1):
        t = k * a.dt
        if k % stride == 0:
            ts.append(t)
            pos.append(d.qpos[0:3].copy())
            quat.append(d.qpos[3:7].copy())
        if k == n:
            break
        d.ctrl[:] = 0.0
        for pl in pulses:
            if pl["t_on"] <= t < pl["t_on"] + pl["dur"]:
                for i in pl["thr"]:
                    d.ctrl[i] = pl["level"]
        mujoco.mj_step(m, d)
    return {"t": np.array(ts), "pos": np.array(pos), "quat": np.array(quat)}


def add_noise(tr: dict, seed: int, sp: float = SIGMA_POS, sr: float = SIGMA_ROT) -> dict:
    rng = np.random.default_rng(seed)
    out = {"t": tr["t"].copy(), "pos": tr["pos"] + rng.normal(0, sp, tr["pos"].shape)}
    q = tr["quat"].copy()
    for i in range(len(q)):
        mujoco.mju_quatIntegrate(q[i], rng.normal(0, sr, 3), 1.0)  # body-frame rotation-vector noise
        q[i] /= np.linalg.norm(q[i])
    out["quat"] = q
    return out


# ---------------------------------------------------------------- CSV I/O


CSV_COLS = ["t", "x", "y", "z", "qw", "qx", "qy", "qz"]


def save_trace_csv(path: str, tr: dict) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for i in range(len(tr["t"])):
            w.writerow([f"{tr['t'][i]:.5f}"] + [f"{v:.6f}" for v in tr["pos"][i]] + [f"{v:.7f}" for v in tr["quat"][i]])


def load_trace_csv(path: str) -> dict:
    """Load a reference trajectory: header t,x,y,z,qw,qx,qy,qz (SI, MuJoCo quaternion order [w,x,y,z]).

    A real trace (mocap / video-derived) can be dropped in. It must be resampled to SAMPLE_DT (50 Hz) and its
    time axis must start at the first commanded input; the matching `exc` (pulse log + initial state) must be
    supplied to `fit()` by the caller. Rows with NaN are rejected rather than silently interpolated."""
    with open(path) as f:
        r = csv.DictReader(f)
        missing = [c for c in CSV_COLS if c not in (r.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV missing columns {missing}; need {CSV_COLS}")
        rows = [[float(row[c]) for c in CSV_COLS] for row in r]
    arr = np.array(rows)
    if not np.all(np.isfinite(arr)):
        raise ValueError("NaN/inf in trace CSV")
    q = arr[:, 4:8]
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    return {"t": arr[:, 0], "pos": arr[:, 1:4], "quat": q}


# ---------------------------------------------------------------- residuals / fit


def residual(sim: dict, data: dict, sp: float, sr: float) -> np.ndarray:
    n = min(len(sim["t"]), len(data["t"]))
    rp = (sim["pos"][:n] - data["pos"][:n]) / sp
    rr = np.zeros((n, 3))
    tmp = np.zeros(3)
    for i in range(n):
        mujoco.mju_subQuat(tmp, data["quat"][i], sim["quat"][i])
        rr[i] = tmp / sr
    return np.concatenate([rp.ravel(), rr.ravel()])


class Problem:
    """Free parameter set F, prior-normalised coordinates theta = (p - mean) / sd."""

    def __init__(self, designs: list[dict], datas: list[dict], free: list[str], sp=SIGMA_POS, sr=SIGMA_ROT, base: dict | None = None):
        self.designs, self.datas, self.free = designs, datas, list(free)
        self.sp, self.sr = sp, sr
        self.base = {k: PRIORS[k][0] for k in PARAM_KEYS}
        if base:
            self.base.update(base)
        self.nsim = 0

    def p_of(self, theta_free: np.ndarray) -> dict:
        p = dict(self.base)
        for k, th in zip(self.free, theta_free):
            mu, sd, lo, hi = PRIORS[k]
            p[k] = float(np.clip(mu + sd * th, lo, hi))
        return p

    def data_res(self, theta_free: np.ndarray) -> np.ndarray:
        p = self.p_of(theta_free)
        out = []
        for e, dta in zip(self.designs, self.datas):
            out.append(residual(simulate(e, p), dta, self.sp, self.sr))
        self.nsim += len(self.designs)
        return np.concatenate(out)

    def full_res(self, theta_free: np.ndarray) -> np.ndarray:
        return np.concatenate([self.data_res(theta_free), np.asarray(theta_free)])  # MAP: prior rows

    def bounds(self):
        lo = [(PRIORS[k][2] - PRIORS[k][0]) / PRIORS[k][1] for k in self.free]
        hi = [(PRIORS[k][3] - PRIORS[k][0]) / PRIORS[k][1] for k in self.free]
        return np.array(lo), np.array(hi)


def jac_fd(fun, x: np.ndarray, h: float = 0.02) -> np.ndarray:
    f0 = fun(x)
    J = np.zeros((len(f0), len(x)))
    for i in range(len(x)):
        xp, xm = x.copy(), x.copy()
        xp[i] += h
        xm[i] -= h
        J[:, i] = (fun(xp) - fun(xm)) / (2 * h)
    return J


def fit(designs, datas, free, method="lsq", seed=0, sp=SIGMA_POS, sr=SIGMA_ROT, cma_evals=240, base=None) -> dict:
    pr = Problem(designs, datas, free, sp, sr, base)
    x0 = np.zeros(len(free))
    lo, hi = pr.bounds()
    if method == "cma_lsq" and len(free) >= 2:
        es = cma.CMAEvolutionStrategy(x0, 0.7, {"seed": seed + 1, "verbose": -9, "popsize": 12, "maxfevals": cma_evals,
                                                "bounds": [lo.tolist(), hi.tolist()]})
        while not es.stop():
            xs = es.ask()
            es.tell(xs, [float(np.sum(pr.full_res(np.asarray(x)) ** 2)) for x in xs])
        x0 = np.asarray(es.result.xbest)
    sol = least_squares(pr.full_res, x0, jac=lambda x: jac_fd(pr.full_res, x), bounds=(lo, hi), method="trf", max_nfev=30)
    x = sol.x
    return {"theta": x, "p": pr.p_of(x), "problem": pr, "nsim": pr.nsim, "cost": float(sol.cost)}


def data_rms(designs, datas, p, sp=SIGMA_POS, sr=SIGMA_ROT) -> float:
    r = np.concatenate([residual(simulate(e, p), d, sp, sr) for e, d in zip(designs, datas)])
    return float(np.sqrt(np.mean(r ** 2)))


# ---------------------------------------------------------------- identifiability


def identifiability(designs, datas, theta_free, free, sp=SIGMA_POS, sr=SIGMA_ROT, base=None, params=None, infl: float | None = None) -> dict:
    """Laplace posterior over `params` (default: ALL 9) evaluated at the fit point. Parameters outside `free` are held at base."""
    params = list(params or PARAM_KEYS)
    pr = Problem(designs, datas, params, sp, sr, base)
    x = np.zeros(len(params))
    pfit = pr.p_of(np.zeros(len(params)))
    # evaluation point = fitted values for free params, base for the rest, expressed in theta coordinates
    for i, k in enumerate(params):
        mu, sd, _, _ = PRIORS[k]
        v = pr.base[k]
        if k in free:
            v = Problem(designs, datas, free, sp, sr, base).p_of(theta_free)[k]
        x[i] = (v - mu) / sd
    J = jac_fd(pr.data_res, x)
    r0 = pr.data_res(x)
    rms = float(np.sqrt(np.mean(r0 ** 2)))
    inflation = max(1.0, rms ** 2) if infl is None else infl  # inflate when model misfit exceeds assumed sensor noise
    JtJ = J.T @ J / inflation
    C = np.linalg.inv(JtJ + np.eye(len(params)))
    U, S, Vt = np.linalg.svd(J / math.sqrt(inflation), full_matrices=False)
    contraction = np.sqrt(np.diag(C))  # posterior sd / prior sd
    # weakest data direction and which params load on it
    weak = Vt[-1]
    return {
        "params": params, "x": x, "J": J, "C": C, "contraction": contraction, "singular_values": S, "Vt": Vt,
        "weakest_dir": {k: float(w) for k, w in zip(params, weak)}, "weakest_sv": float(S[-1]), "rms": rms, "inflation": inflation,
        "cond": float(S[0] / max(S[-1], 1e-12)),
    }


def classify(contraction: float) -> str:
    if contraction < 0.5:
        return "identified"
    if contraction < 0.9:
        return "weak"
    return "NOT_identified"


def bootstrap(designs, datas, free, fit_res, k=12, seed=0, sp=SIGMA_POS, sr=SIGMA_ROT, base=None, workers: int | None = None) -> dict:
    """Parametric bootstrap: re-simulate the fitted model + fresh sensor noise, refit (warm start)."""
    p_fit = fit_res["p"]
    jobs = [(designs, free, p_fit, seed * 1000 + i, sp, sr, base, fit_res["theta"].tolist()) for i in range(k)]
    import multiprocessing as mp
    with ProcessPoolExecutor(max_workers=workers or max(1, (os.cpu_count() or 4) - 1), mp_context=mp.get_context("spawn")) as ex:
        res = list(ex.map(_boot_one, jobs))
    arr = np.array(res)
    return {"free": free, "mean": dict(zip(free, arr.mean(0).tolist())), "sd": dict(zip(free, arr.std(0, ddof=1).tolist())),
            "q05": dict(zip(free, np.quantile(arr, 0.05, 0).tolist())), "q95": dict(zip(free, np.quantile(arr, 0.95, 0).tolist())), "k": k}


def _boot_one(job):
    designs, free, p_fit, seed, sp, sr, base, th0 = job
    datas = [add_noise(simulate(e, p_fit), seed * 10 + j, sp, sr) for j, e in enumerate(designs)]
    pr = Problem(designs, datas, free, sp, sr, base)
    lo, hi = pr.bounds()
    sol = least_squares(pr.full_res, np.asarray(th0), jac=lambda x: jac_fd(pr.full_res, x), bounds=(lo, hi), method="trf", max_nfev=15)
    return [pr.p_of(sol.x)[k] for k in free]


# ---------------------------------------------------------------- Assumption emission


def to_assumptions(free: list[str], fit_p: dict, idn: dict, source: str, label_prefix: str = "") -> tuple[list[dict], dict]:
    """Return (Assumption dicts compatible with schemas/spec_sheet.schema.json, per-param status).

    identified/weak -> normal(mean=fit, std=posterior sd), clipped to physical bounds.
    NOT identified or not fitted -> PRIOR kept unchanged, confidence 'low'. Never a confident value the data cannot support."""
    out, status = [], {}
    keys = idn["params"]
    for i, k in enumerate(keys):
        mu, sd, lo, hi = PRIORS[k]
        c = float(idn["contraction"][i])
        fitted = k in free
        cls = classify(c) if fitted else "not_fitted"
        status[k] = {"status": cls, "prior_mean": mu, "prior_sd": sd, "contraction": c,
                     "fit": fit_p.get(k) if fitted else None, "post_sd": c * sd if fitted else None}
        if cls in ("identified", "weak"):
            val, std = float(fit_p[k]), float(c * sd)
            conf = "high" if cls == "identified" else "med"
            src = f"{source}; posterior/prior sd = {c:.2f} ({cls})"
        else:
            val, std = mu, sd
            conf = "low"
            src = f"prior kept ({'not fitted' if not fitted else 'NOT identified by calibration data: posterior/prior sd = %.2f' % c}); {source}"
        out.append({
            "key": k, "label": PARAM_LABELS[k], "value": val, "unit": PARAM_UNITS[k],
            "distribution": {"kind": "normal", "mean": val, "std": std, "clip_low": lo, "clip_high": hi},
            "source": src, "confidence": conf, "editable": True,
        })
    return out, status


def validate_assumptions(assumptions: list[dict]) -> str:
    """Validate against physlab_core pydantic Assumption if importable, else against the JSON schema subset."""
    import sys
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(root, "packages", "core", "src"))
    try:
        from physlab_core.schemas import Assumption
        for a in assumptions:
            Assumption.model_validate(a)
        return "pydantic physlab_core.schemas.Assumption"
    except ImportError:
        pass
    sc = json.load(open(os.path.join(root, "schemas", "spec_sheet.schema.json")))
    d = sc["$defs"]["Assumption"]
    for a in assumptions:
        assert set(a) <= set(d["properties"]), set(a) - set(d["properties"])
        assert all(r in a for r in d["required"])
        assert a["distribution"]["kind"] in ("fixed", "uniform", "normal")
    return "manual JSON-schema subset check"
