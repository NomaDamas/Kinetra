"""Template ``rocket_car``: a car-sized rigid body with cold-gas thrusters attempting a ramp-launch full roll + full pitch rotation.

Ported from spikes/roadster (roadster.py + run_spike.py) and refactored to the Template contract.
Judge = MuJoCo (``mujoco.rollout`` thread pool). Search = CMA-ES (IPOP-style restarts) over 21 burn-window
parameters (5 pitch/lift windows + 2 roll windows). Necessary-condition screen = analytic bounds evaluated at the *favorable* end of the assumptions.
Monte-Carlo and robustification draw from the SpecSheet's assumption distributions (``kinetra_engine.mc``).

Differences from the spike worth knowing:
* thrust scale perturbations act on ``actuator_gear[:, 2]`` (the spike perturbed gear[:, 0], which is zero for
  a z-axis motor, so its thrust-error MC was a no-op);
* the throttle (0..1) is the control and ``gear[2] = Fmax * thrust_scale_k``;
* search/robustify budgets are counted in evaluations (wall-clock only as an emergency stop) so results are
  reproducible for a given (spec, seed, budget).
Simplified model, needs precise validation: no aero, no thermal/pressure blowdown, ideal constant-Isp thrust,
constant mass (fuel only accounted), no structural analysis.
"""
from __future__ import annotations

import copy
import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import cma
import mujoco
import numpy as np
from mujoco import rollout as mj_rollout

from physlab_core.schemas import (
    Assumption, BomItem, Comparator, Confidence, ContactEvent, Fixed, Geom, GeomType, NecessaryCheck, Normal,
    ParamBound, Part, SpecSheet, SuccessCriterion, TemplateId, Tier, TimeSeries, TrajBody, Trajectory,
    TrajectoryMeta, Uniform,
)

from .. import mc as mclib
from ..base import Budget, McResult, SearchResult

TEMPLATE_ID = "rocket_car"
G0 = 9.80665
TOL_FIN = np.deg2rad(20.0)   # final pitch / roll tolerance (upright after the maneuver)
TOL_TD = np.deg2rad(30.0)    # pitch / roll tolerance at first ground contact
TURN_MIN = np.deg2rad(340.0)  # a "full" rotation: |integral of the body-frame rate| >= 340 deg (360 deg minus the 20 deg tolerance)
WHEEL_MASS = 20.0

# --------------------------------------------------------------------------- geometry / layout
LENGTH, WIDTH, HEIGHT = 4.2, 1.9, 1.2
WHEEL_R, WHEEL_HW = 0.32, 0.12
UP, DN = (0, 0, 1), (0, 0, -1)
THRUSTERS = [
    ("nose_dn", 0, 2.10, 0.0, 0.3, DN),   # fwd-pitch couple (torque +theta = nose down)
    ("tail_up", 0, -2.10, 0.0, 0.3, UP),
    ("nose_up", 1, 2.10, 0.0, 0.3, UP),   # back-pitch couple (torque -theta)
    ("tail_dn", 1, -2.10, 0.0, 0.3, DN),
    ("belly_fl", 2, 1.0, 0.6, -0.5, UP),  # lift quad
    ("belly_fr", 2, 1.0, -0.6, -0.5, UP),
    ("belly_rl", 2, -1.0, 0.6, -0.5, UP),
    ("belly_rr", 2, -1.0, -0.6, -0.5, UP),
    ("mid_dn", 3, 1.00, 0.0, 0.3, DN),    # inner fwd-pitch couple (1 m lever)
    ("mid_up", 3, -1.00, 0.0, 0.3, UP),
    # side nozzles: roll couples with a 0.95 m lateral lever arm (the car's half width). +roll = torque about +x = left side up.
    # Each couple is two up/down pairs (fore and aft, close to mid-car so they add almost no pitch torque) with equal and opposite
    # vertical forces: no net lift and, fired together, no pitch torque.
    ("side_fl_up", 4, 0.70, 0.95, 0.1, UP),   # roll_pos couple
    ("side_fr_dn", 4, 0.70, -0.95, 0.1, DN),
    ("side_rl_up", 4, -0.70, 0.95, 0.1, UP),
    ("side_rr_dn", 4, -0.70, -0.95, 0.1, DN),
    ("side_fl_dn", 5, 0.40, 0.95, 0.1, DN),   # roll_neg couple (torque about -x)
    ("side_fr_up", 5, 0.40, -0.95, 0.1, UP),
    ("side_rl_dn", 5, -0.40, 0.95, 0.1, DN),
    ("side_rr_up", 5, -0.40, -0.95, 0.1, UP),
]
K = len(THRUSTERS)
GROUP_NAMES = ["pitch_fwd_outer", "pitch_back_outer", "lift_quad", "pitch_fwd_inner", "roll_pos", "roll_neg"]
WIN_GROUP = [0, 1, 2, 3, 2, 4, 5]
WIN_NAMES = ["pitch_fwd_outer", "pitch_back_outer", "lift_main", "pitch_fwd_inner", "lift_landing", "roll_pos", "roll_neg"]
NWIN = len(WIN_GROUP)
NPARAM = NWIN * 3
GROUP_OF = np.array([t[1] for t in THRUSTERS])
GROUP_MAT = np.zeros((NWIN, K))
for _w, _g in enumerate(WIN_GROUP):
    GROUP_MAT[_w, GROUP_OF == _g] = 1.0
T_START_MAX, DUR_MAX = 2.5, 2.0
PNAMES = [f"{w}_{s}" for w in WIN_NAMES for s in ("start", "duration", "throttle")]
DT, T_SIM = 0.004, 4.5
NSTEP = int(round(T_SIM / DT))
WHEELS = [("fl", 1.3, 0.85), ("fr", 1.3, -0.85), ("rl", -1.3, 0.85), ("rr", -1.3, -0.85)]

SIMPLIFIED = "simplified model, needs precise validation"
MODEL_LABELS = [
    SIMPLIFIED,
    "Aerodynamics not simulated (simplified drag/momentum model only) — simplified model, needs precise validation.",
    "Thermal effects not modeled — simplified model, needs precise validation.",
    "Structural strength not analyzed (no FEA) — simplified model, needs precise validation.",
    "Propulsion modeled as ideal constant-Isp thrust — simplified model, needs precise validation.",
    "Perfect state feedback assumed; real sensing/latency not modeled — simplified model, needs precise validation.",
]

# fine-grained failed checks -> docs/judgment-spec.md section A taxonomy
TAXONOMY = {
    "landed": "TIPPING", "pitch_turn": "TIPPING", "roll_turn": "TIPPING", "upright_td": "TIPPING", "upright_final": "TIPPING",
    "ride_height": "TIPPING", "settled": "TIPPING", "no_post_thrust": "TIPPING",
    "impact_vz": "STRUCTURAL_UNMODELED", "impact_w": "STRUCTURAL_UNMODELED", "impact_wr": "STRUCTURAL_UNMODELED", "fuel": "ENERGY_BUDGET",
}
CHECK_UNITS = {"impact_vz": ("impact_speed", "m/s"), "impact_w": ("touchdown_pitch_rate", "rad/s"), "impact_wr": ("touchdown_roll_rate", "rad/s"),
               "fuel": ("propellant", "kg"), "pitch_turn": ("pitch_rotation", "deg"), "roll_turn": ("roll_rotation", "deg"),
               "upright_final": ("final_upright_error", "deg"), "upright_td": ("touchdown_upright_error", "deg")}


# --------------------------------------------------------------------------- MJCF
def build_mjcf() -> str:
    """Base model: Fmax-agnostic (gear z = 1 N per unit control); per-run gear/mass/COM set by ``Rig.model``."""
    m_body = 1300.0 - 4 * WHEEL_MASS
    L, W, H = LENGTH, WIDTH, HEIGHT
    ixx, iyy, izz = m_body / 12 * (W**2 + H**2), m_body / 12 * (L**2 + H**2), m_body / 12 * (L**2 + W**2)
    box_hz = (H - WHEEL_R * 0.5) / 2
    wheel_z = -H / 2 + WHEEL_R
    wheels = ""
    for nm, wx, wy in WHEELS:
        wheels += (f'<body name="wheel_{nm}" pos="{wx} {wy} {wheel_z}"><joint name="spin_{nm}" type="hinge" axis="0 1 0" damping="0.0"/>'
                   f'<geom name="tire_{nm}" type="cylinder" size="{WHEEL_R} {WHEEL_HW}" euler="90 0 0" mass="{WHEEL_MASS}" '
                   f'friction="0.9 0.005 0.0001"/></body>')
    sites, acts = "", ""
    for name, _g, x, y, z, d in THRUSTERS:
        sites += f'<site name="{name}" pos="{x} {y} {z}" zaxis="{d[0]} {d[1]} {d[2]}" size="0.06" rgba="1 0.4 0 1"/>'
        acts += f'<motor name="{name}" site="{name}" gear="0 0 1 0 0 0" ctrllimited="true" ctrlrange="0 1"/>'
    return f"""<mujoco model="rocket_car">
  <compiler angle="degree"/>
  <option timestep="{DT}" gravity="0 0 -{G0}" integrator="implicitfast"/>
  <worldbody>
    <geom name="ground" type="plane" size="0 0 0.1" friction="0.9 0.005 0.0001"/>
    <body name="car" pos="0 0 1">
      <freejoint name="root"/>
      <inertial pos="0 0 0" mass="{m_body}" diaginertia="{ixx} {iyy} {izz}"/>
      <geom name="chassis" type="box" size="{L/2} {W/2} {box_hz}" pos="0 0 {H/2 - box_hz}" mass="0" friction="0.9 0.005 0.0001" rgba="0.8 0.1 0.1 1"/>
      {sites}
      {wheels}
    </body>
  </worldbody>
  <actuator>{acts}</actuator>
</mujoco>"""


_MJCF = build_mjcf()
MODEL_HASH = hashlib.sha256(_MJCF.encode()).hexdigest()
_BASE = mujoco.MjModel.from_xml_string(_MJCF)
_BODY_MASS0 = float(_BASE.body_mass[1])


# --------------------------------------------------------------------------- shared thread pool
_POOL_LOCK = threading.Lock()
_POOLS: dict[int, tuple[Any, list]] = {}


def n_threads() -> int:
    return max(1, int(os.environ.get("KINETRA_THREADS", os.cpu_count() or 2)))


def _pool():
    nt = n_threads()
    with _POOL_LOCK:
        if nt not in _POOLS:
            _POOLS[nt] = (mj_rollout.Rollout(nthread=nt), [mujoco.MjData(_BASE) for _ in range(nt)])
        return _POOLS[nt]


# --------------------------------------------------------------------------- environment (one row per rollout)
@dataclass
class Env:
    mass: np.ndarray        # (n,) total vehicle mass incl. wheels [kg]
    com_dx: np.ndarray
    com_dz: np.ndarray
    fmax: np.ndarray        # (n,) nominal thrust per nozzle [N]
    tscale: np.ndarray      # (n,K) thrust scale per nozzle
    isp: np.ndarray
    fuel_cap: np.ndarray
    ramp_speed: np.ndarray
    ramp_angle: np.ndarray  # rad
    ramp_height: np.ndarray

    @property
    def n(self) -> int:
        return len(self.mass)

    @staticmethod
    def from_values(v: dict[str, float]) -> "Env":
        a = lambda x: np.array([float(x)])
        return Env(a(v["vehicle_mass"]), a(v.get("com_offset_x", 0.0)), a(v.get("com_offset_z", 0.0)), a(v["thruster_force_max"]),
                   np.full((1, K), 1.0 + v.get("thrust_error", 0.0)), a(v["isp"]), a(v["propellant_cap"]),
                   a(v["ramp_speed"]), a(np.deg2rad(v["ramp_angle"])), a(v["ramp_height"]))

    @staticmethod
    def from_samples(s: dict[str, np.ndarray], fixed: dict[str, float]) -> "Env":
        n = len(s["vehicle_mass"])
        g = lambda k: np.asarray(s[k], float) if k in s else np.full(n, fixed.get(k, 0.0))
        jit = (s["_thrust_jitter"] if "_thrust_jitter" in s else np.zeros((n, K))) * g("thrust_spread")[:, None]
        return Env(g("vehicle_mass"), g("com_offset_x"), g("com_offset_z"), g("thruster_force_max"),
                   (1.0 + g("thrust_error"))[:, None] * (1.0 + jit), g("isp"), g("propellant_cap"), g("ramp_speed"),
                   np.deg2rad(g("ramp_angle")), g("ramp_height"))

    def tile(self, m: int) -> "Env":
        t = lambda a: np.tile(a, (m,) + (1,) * (a.ndim - 1))
        return Env(*(t(getattr(self, f)) for f in ("mass", "com_dx", "com_dz", "fmax", "tscale", "isp", "fuel_cap", "ramp_speed", "ramp_angle", "ramp_height")))

    def bcast(self, n: int) -> "Env":
        if self.n == n:
            return self
        b = lambda a: np.broadcast_to(a, (n,) + a.shape[1:])
        return Env(*(b(getattr(self, f)) for f in ("mass", "com_dx", "com_dz", "fmax", "tscale", "isp", "fuel_cap", "ramp_speed", "ramp_angle", "ramp_height")))


def aux_jitter(n: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(mclib.derive_seed(seed, "thrust_jitter"))
    return {"_thrust_jitter": rng.uniform(-1.0, 1.0, (n, K))}


# --------------------------------------------------------------------------- simulator
class Sim:
    def __init__(self, limits: dict[str, float]):
        self.vz_max, self.w_max, self.wr_max = limits["vz_max"], limits["w_max"], limits["wr_max"]
        self.evals = 0
        self.t_rollout = 0.0
        self.nq, self.nv = _BASE.nq, _BASE.nv
        self.ns = int(mujoco.mj_stateSize(_BASE, mujoco.mjtState.mjSTATE_FULLPHYSICS))
        H = HEIGHT
        self.bz0, self.bz1 = -H / 2 + WHEEL_R * 0.5, H / 2
        sx, sy = LENGTH / 2, WIDTH / 2
        self.corners = np.array([[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (self.bz0, self.bz1)])
        self.wheel_c = np.array([[wx, wy, -H / 2 + WHEEL_R] for _, wx, wy in WHEELS])

    # ---- models
    @staticmethod
    def model(mass: float, dx: float, dz: float, fmax: float, tscale: np.ndarray) -> mujoco.MjModel:
        mdl = copy.copy(_BASE)
        mb = mass - 4 * WHEEL_MASS
        r = mb / _BODY_MASS0
        mdl.body_mass[1] = mb
        mdl.body_inertia[1] = _BASE.body_inertia[1] * r
        mdl.body_ipos[1] = _BASE.body_ipos[1] + np.array([dx, 0.0, dz])
        mdl.actuator_gear[:, 2] = fmax * np.asarray(tscale)
        mujoco.mj_setConst(mdl, mujoco.MjData(mdl))
        return mdl

    def models(self, env: Env) -> list:
        return [self.model(env.mass[i], env.com_dx[i], env.com_dz[i], env.fmax[i], env.tscale[i]) for i in range(env.n)]

    def x0(self, env: Env) -> np.ndarray:
        x = np.zeros((env.n, self.ns))
        for i in range(env.n):
            th0 = -env.ramp_angle[i]
            v = env.ramp_speed[i]
            x[i, 1:4] = [0.0, 0.0, env.ramp_height[i]]
            x[i, 4:8] = [np.cos(th0 / 2), 0.0, np.sin(th0 / 2), 0.0]
            vel = 1 + self.nq
            x[i, vel:vel + 3] = [v * np.cos(env.ramp_angle[i]), 0.0, v * np.sin(env.ramp_angle[i])]
            x[i, vel + 6:vel + 10] = v / WHEEL_R
        return x

    # ---- controls
    @staticmethod
    def decode(X):
        X = np.atleast_2d(X).reshape(-1, NWIN, 3)
        return X[..., 0] * T_START_MAX, X[..., 1] * DUR_MAX, X[..., 2]

    def controls(self, X):
        ts, dur, mag = self.decode(X)
        t = np.arange(NSTEP) * DT
        on = (t[None, None, :] >= ts[..., None]) & (t[None, None, :] < (ts + dur)[..., None])
        thr = np.einsum("ngt,gk->ntk", on * mag[..., None], GROUP_MAT)
        return thr

    # ---- rollout
    def run(self, thr: np.ndarray, models, x0: np.ndarray):
        pool, datas = _pool()
        t0 = time.perf_counter()
        st, _ = pool.rollout(models, datas, x0, np.ascontiguousarray(thr))
        self.t_rollout += time.perf_counter() - t0
        self.evals += thr.shape[0]
        return st

    def metrics(self, state, thr, env: Env):
        n, T = state.shape[:2]
        env = env.bcast(n)
        nq = self.nq
        qp, qv = state[..., 1:1 + nq], state[..., 1 + nq:]
        pos = qp[..., :3]
        qw, qx, qy, qz = qp[..., 3], qp[..., 4], qp[..., 5], qp[..., 6]
        R00 = 1 - 2 * (qy**2 + qz**2)
        R20 = 2 * (qx * qz - qw * qy)
        R21 = 2 * (qy * qz + qw * qx)
        R22 = 1 - 2 * (qx**2 + qy**2)
        Rz = np.stack([R20, R21, R22], -1)       # third row of the rotation matrix (n,T,3)
        theta = np.unwrap(np.arctan2(-R20, R00), axis=1)
        zc = pos[..., 2:3] + np.einsum("ntj,cj->ntc", Rz, self.corners)
        wz = pos[..., 2:3] + np.einsum("ntj,cj->ntc", Rz, self.wheel_c)
        ay = np.abs(R21)[..., None]
        wlow = wz - (WHEEL_R * np.sqrt(np.clip(1 - ay**2, 0, 1)) + WHEEL_HW * ay)
        hlow = np.minimum(zc.min(-1), wlow.min(-1))
        touching, airborne = hlow < 0.02, hlow > 0.05
        has_air = airborne.any(1)
        ia = airborne.argmax(1)
        after_air = np.arange(T)[None, :] > ia[:, None]
        td_mask = touching & after_air & has_air[:, None]
        landed = td_mask.any(1)
        itd = np.where(landed, td_mask.argmax(1), T - 1)
        idx = np.arange(n)
        vz_td, w_td, wr_td = -qv[idx, itd, 2], np.abs(qv[idx, itd, 4]), np.abs(qv[idx, itd, 3])
        # full-rotation metrics: integral of the BODY-frame angular velocity (free-joint qvel[3:6] is body-frame) from launch to first touchdown
        cum = np.cumsum(qv[..., 3:5], axis=1) * DT                      # (n,T,2): roll (about body x), pitch (about body y)
        roll_turn, pitch_turn = cum[idx, itd, 0], cum[idx, itd, 1]
        # final / touchdown attitude as wrapped ZYX Euler roll and pitch (a whole number of turns is "upright")
        phi = np.arctan2(R21, R22)
        pit = np.arcsin(np.clip(-R20, -1, 1))
        phi_td, pit_td, phi_end, pit_end = phi[idx, itd], pit[idx, itd], phi[:, -1], pit[:, -1]
        err_td = np.maximum(np.abs(phi_td), np.abs(pit_td))
        err_fin = np.maximum(np.abs(phi_end), np.abs(pit_end))
        z_end, vz_end = pos[:, -1, 2], np.abs(qv[:, -1, 2])
        thrust_N = thr * (env.fmax[:, None] * 1.0)[:, None, :] * env.tscale[:, None, :]    # (n,T,K) actual force
        after = (np.arange(T)[None, :] >= itd[:, None]) & landed[:, None]
        post_imp = (thrust_N.sum(-1) * after).sum(1) * DT / 1000.0
        impulse = thrust_N.sum((1, 2)) * DT
        fuel = impulse / (env.isp * G0)
        ok = dict(
            landed=landed, pitch_turn=np.abs(pitch_turn) >= TURN_MIN, roll_turn=np.abs(roll_turn) >= TURN_MIN,
            upright_td=err_td <= TOL_TD, upright_final=err_fin <= TOL_FIN,
            impact_vz=vz_td <= self.vz_max, impact_w=w_td <= self.w_max, impact_wr=wr_td <= self.wr_max,
            ride_height=(z_end > 0.5) & (z_end < 0.8), settled=vz_end < 1.0, no_post_thrust=post_imp < 0.05,
            fuel=fuel <= env.fuel_cap,
        )
        success = np.ones(n, bool)
        for v in ok.values():
            success &= v
        # search guidance: distance of each rotation integral to one full turn (smooth, monotone while turning); the wrapped upright errors
        # are down-weighted until both turns are complete, otherwise "do not rotate" (wrapped error 0) is a trap for the optimizer
        turn_err = lambda a: np.abs(np.abs(a) - 2 * np.pi) / TOL_TD
        both = ok["pitch_turn"] & ok["roll_turn"]
        w_up = np.where(both, 1.0, 0.25)
        cost = (turn_err(pitch_turn) + turn_err(roll_turn)
                + w_up * ((np.abs(phi_td) + np.abs(pit_td)) / TOL_TD + (np.abs(phi_end) + np.abs(pit_end)) / TOL_FIN)
                + 8 * np.maximum(0, vz_td - self.vz_max) / self.vz_max
                + 4 * np.maximum(0, w_td - self.w_max) / self.w_max
                + 4 * np.maximum(0, wr_td - self.wr_max) / self.wr_max
                + 2 * np.maximum(0, post_imp)
                + 2 * np.maximum(0, fuel / env.fuel_cap - 1)
                + 3.0 * (~landed) + 1.0 * (~ok["ride_height"]) + 0.02 * fuel / env.fuel_cap)
        cost = np.where(np.isfinite(cost), cost, 1e3)      # a diverged rollout (NaN state) is simply the worst candidate
        # signed slack per judged margin (units) and the limits used for normalisation
        turn_deg = np.rad2deg(TURN_MIN)
        margins = dict(
            impact_vz=(self.vz_max - vz_td, np.full(n, self.vz_max)),
            impact_w=(self.w_max - w_td, np.full(n, self.w_max)),
            impact_wr=(self.wr_max - wr_td, np.full(n, self.wr_max)),
            fuel=(env.fuel_cap - fuel, env.fuel_cap),
            pitch_turn=(np.rad2deg(np.abs(pitch_turn) - TURN_MIN), np.full(n, turn_deg)),
            roll_turn=(np.rad2deg(np.abs(roll_turn) - TURN_MIN), np.full(n, turn_deg)),
            upright_final=(np.rad2deg(TOL_FIN - err_fin), np.full(n, np.rad2deg(TOL_FIN))),
            upright_td=(np.rad2deg(TOL_TD - err_td), np.full(n, np.rad2deg(TOL_TD))),
        )
        return dict(success=success, cost=cost, ok=ok, pitch_turn=pitch_turn, roll_turn=roll_turn, phi_td=phi_td, pit_td=pit_td,
                    phi_end=phi_end, pit_end=pit_end, vz_td=vz_td, w_td=w_td, wr_td=wr_td, fuel=fuel,
                    post_imp=post_imp, itd=itd, err_td=err_td, err_fin=err_fin, margins=margins, landed=landed, z_end=z_end)

    def evaluate_nominal(self, X, env: Env):
        """All candidates on ONE (nominal) model."""
        thr = self.controls(X)
        st = self.run(thr, self.models(env)[0], self.x0(env))
        return self.metrics(st, thr, env), st, thr

    def evaluate_models(self, X, env: Env, models, x0):
        """Every candidate on every model of ``env`` (candidate-major; k = env.n)."""
        k, m = env.n, len(X)
        thr = np.repeat(self.controls(X), k, axis=0)
        st = self.run(thr, models * m, np.tile(x0, (m, 1)))
        return self.metrics(st, thr, env.tile(m)), st, thr


# --------------------------------------------------------------------------- necessary-condition screen
def _bangbang_time(dth, a_up, a_dn, w_f):
    if a_up <= 0:
        return np.inf
    if a_dn > 0:
        wp2 = (dth + w_f**2 / (2 * a_dn)) / (1 / (2 * a_up) + 1 / (2 * a_dn))
        wp = np.sqrt(max(wp2, 0.0))
        if wp >= w_f:
            return wp / a_up + (wp - w_f) / a_dn
    d_acc = w_f**2 / (2 * a_up)
    if dth <= d_acc:
        return np.sqrt(2 * dth / a_up)
    return w_f / a_up + (dth - d_acc) / w_f


def _levers(mass: float) -> dict[str, Any]:
    """Pitch / roll inertia about the COM and per-thruster y- / x-torque and z-direction at unit force (CRB at identity pose)."""
    mdl = Sim.model(mass, 0.0, 0.0, 1.0, np.ones(K))
    d = mujoco.MjData(mdl)
    d.qpos[:7] = [0, 0, 1, 1, 0, 0, 0]
    mujoco.mj_forward(mdl, d)
    M = np.zeros((mdl.nv, mdl.nv))
    mujoco.mj_fullM(mdl, d, M)
    com = d.subtree_com[1]
    tau_y, tau_x, fz = [], [], []
    for i in range(K):
        sid = mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_SITE, THRUSTERS[i][0])
        r = d.site_xpos[sid] - com
        f = d.site_xmat[sid].reshape(3, 3)[:, 2]
        tau_y.append(r[2] * f[0] - r[0] * f[2])
        tau_x.append(r[1] * f[2] - r[2] * f[1])
        fz.append(f[2])
    return dict(mass=float(M[0, 0]), Iyy=float(M[4, 4]), Ixx=float(M[3, 3]), tau_y=np.array(tau_y), tau_x=np.array(tau_x), fz=np.array(fz))


def _axis_time(lv: dict[str, Any], axis: str, fmax_eff: float, dths: dict[int, float], w_max: float) -> dict[str, Any]:
    """Fastest bang-bang rotation about one body axis using EVERY nozzle individually (a relaxation of the group windows)."""
    I = lv["Iyy"] if axis == "y" else lv["Ixx"]
    tau = lv["tau_y" if axis == "y" else "tau_x"] * fmax_eff
    best = None
    for s, dth in dths.items():
        a_up = float(np.maximum(0, s * tau).sum() / I)
        a_dn = float(np.maximum(0, -s * tau).sum() / I)
        t_min = _bangbang_time(dth, a_up, a_dn, w_max)
        if best is None or t_min < best["t_min"]:
            best = dict(direction=s, t_min=float(min(t_min, 1e6)), dth=float(dth))
    r_max = float(np.max(np.abs(lv["tau_y" if axis == "y" else "tau_x"])))
    return dict(I=I, r_max=r_max, **best)


def screen_bounds(mass, fmax_eff, isp, cap, ramp_h, speed, angle, w_max, wr_max=None) -> dict[str, float]:
    """Analytic, conservative (relaxed) bounds. Returns pitch- and roll-rotation times, the flight-time upper bound and a propellant bound.

    Pitch must rotate the integral of the pitch rate through >= 340 deg AND land within the touchdown tolerance of upright (start pitch = -ramp angle);
    roll must rotate >= 340 deg (start roll 0). Each axis is bounded alone with all of its nozzles used individually, which only relaxes the bound.
    """
    wr_max = w_max if wr_max is None else wr_max
    lv = _levers(mass)
    m = lv["mass"]
    Fup = float(np.maximum(0, lv["fz"]).sum() * fmax_eff)
    th0 = -angle
    I_tot = cap * isp * G0
    vz0 = speed * np.sin(angle)
    h_land = HEIGHT / 2
    tt = np.linspace(0, 12, 12001)
    vg = np.minimum(Fup * tt, I_tot) / m
    gain = np.concatenate([[0], np.cumsum(0.5 * (vg[1:] + vg[:-1]) * np.diff(tt))])
    z = ramp_h + vz0 * tt - 0.5 * G0 * tt**2 + gain
    below = np.where(z < h_land)[0]
    T_ub = float(tt[below[0]]) if below.size else float(tt[-1])
    turn = float(TURN_MIN)
    pit = _axis_time(lv, "y", fmax_eff, {s: max(turn, 2 * np.pi - TOL_TD - s * th0) for s in (+1, -1)}, w_max)
    rol = _axis_time(lv, "x", fmax_eff, {+1: turn, -1: turn}, wr_max)
    big = 1e6

    def fuel_for(ax: dict[str, Any], wlim: float) -> float:
        w_req = ax["dth"] / T_ub if T_ub > 0 else np.inf
        L_req = ax["I"] * (w_req + max(0.0, w_req - wlim))
        return L_req / ax["r_max"] / (isp * G0)

    fuel_p, fuel_r = fuel_for(pit, w_max), fuel_for(rol, wr_max)
    # one nozzle's impulse can serve both axes, so the total is bounded by the larger single-axis need (not their sum)
    return dict(t_min=min(pit["t_min"], big), T_ub=T_ub, t_min_roll=min(rol["t_min"], big), min_fuel=float(min(max(fuel_p, fuel_r), big)),
                min_fuel_pitch=float(min(fuel_p, big)), min_fuel_roll=float(min(fuel_r, big)), Iyy=pit["I"], Ixx=rol["I"], mass=m, Fup=Fup,
                direction=pit["direction"])


# --------------------------------------------------------------------------- search start points
_LV0: dict[str, Any] = {}


def _sequential_x(fmax: float, u_roll: float, u_pitch: float, gap: float, lm_d: float, lt: float, ld: float, lu: float) -> tuple[np.ndarray, float]:
    """A sequential schedule from constant-acceleration half-turns: roll couple then its reverse, then the outer pitch couple and its reverse
    (durations from the MuJoCo model's roll / pitch inertia and the nozzle lever arms), plus a lift burst at launch and a landing burn."""
    if not _LV0:
        _LV0.update(_levers(1300.0))
    lv = _LV0
    a_r = 4 * 0.95 * fmax * u_roll / lv["Ixx"]
    a_p = 4.2 * fmax * u_pitch / lv["Iyy"]
    t_r = float(np.sqrt(2 * np.pi / a_r))
    t_p = float(np.sqrt(2 * np.pi * 0.95 / a_p))
    t_roll_end = 0.02 + 2 * t_r
    win = {"roll_pos": (0.02, t_r, u_roll), "roll_neg": (0.02 + t_r, t_r, u_roll),
           "pitch_back_outer": (t_roll_end + gap, t_p, u_pitch), "pitch_fwd_outer": (t_roll_end + gap + t_p, t_p, u_pitch), "pitch_fwd_inner": (0.0, 0.0, 0.0),
           "lift_main": (0.0, lm_d, 1.0), "lift_landing": (lt, ld, lu)}
    x = np.zeros(NPARAM)
    for i, w in enumerate(WIN_NAMES):
        a, b, c = win[w]
        x[3 * i:3 * i + 3] = [a / T_START_MAX, b / DUR_MAX, c]
    return np.clip(x, 0.0, 1.0), t_roll_end + gap + 2 * t_p


def seeded_start(sim: "Sim", env: Env) -> tuple[np.ndarray, float, bool]:
    """Best of a small grid of analytic sequential schedules, judged by the SAME cost on the nominal model (evaluations are counted in
    ``sim.evals`` and so in the search budget). It is only a CMA-ES start point: it is not a witness and no verdict reads it directly."""
    fmax = float(env.fmax[0])
    cands = []
    for u_r in (0.3, 0.5, 0.8):
        for u_p in (0.3, 0.5, 0.8):
            for lm in (0.0, 0.3):
                _, t_end = _sequential_x(fmax, u_r, u_p, 0.05, lm, 0.0, 0.0, 0.0)
                for lt in (np.arange(t_end + 0.05, 3.2, 0.1) if t_end + 0.05 < 3.2 else [min(t_end + 0.05, T_SIM - 0.5)]):
                    for ld in (0.3, 0.5, 0.7):
                        for lu in (0.5, 1.0):
                            cands.append(_sequential_x(fmax, u_r, u_p, 0.05, lm, float(lt), ld, lu)[0])
    X = np.array(cands)
    m, _, _ = sim.evaluate_nominal(X, env)
    j = int(np.where(m["success"], m["cost"], np.inf).argmin()) if m["success"].any() else int(m["cost"].argmin())
    return X[j].copy(), float(m["cost"][j]), bool(m["success"][j])


def start_point(restart: int, rng: np.random.Generator, seed_x: np.ndarray) -> tuple[np.ndarray, float, int]:
    """CMA-ES start (mean, sigma, population) of search restart ``restart``. Three of every four restarts start at the seeded schedule
    (sigma .03 / .08 / noisy copy) with a fixed population of 64; every fourth is a uniform draw with a population that doubles (cap 384)
    so the search is not confined to one basin."""
    k = restart % 4
    if k == 0:
        return seed_x.copy(), 0.03, 64
    if k == 1:
        return seed_x.copy(), 0.08, 64
    if k == 2:
        return np.clip(seed_x + rng.normal(0.0, 0.1, NPARAM), 0.0, 1.0), 0.1, 64
    return rng.uniform(0.2, 0.6, NPARAM), 0.3, min(64 * 2 ** (1 + restart // 4), 384)


# --------------------------------------------------------------------------- helpers on the spec
def _vals(spec: SpecSheet) -> dict[str, float]:
    return {a.key: float(a.value) for a in spec.assumptions}


def _assum(spec: SpecSheet) -> dict[str, Assumption]:
    return {a.key: a for a in spec.assumptions}


def _limits(spec: SpecSheet) -> dict[str, float]:
    c = {s.name: s.threshold for s in spec.success_criteria}
    return dict(vz_max=c["touchdown_vertical_speed"], w_max=c["touchdown_pitch_rate"], wr_max=c["touchdown_roll_rate"])


def params_to_x(params: dict[str, float]) -> np.ndarray:
    x = np.empty(NPARAM)
    for i, w in enumerate(WIN_NAMES):
        x[3 * i] = params[f"{w}_start"] / T_START_MAX
        x[3 * i + 1] = params[f"{w}_duration"] / DUR_MAX
        x[3 * i + 2] = params[f"{w}_throttle"]
    return np.clip(x, 0.0, 1.0)


def x_to_params(x: np.ndarray) -> dict[str, float]:
    ts, du, ma = Sim.decode(np.asarray(x)[None])
    out: dict[str, float] = {}
    for i, w in enumerate(WIN_NAMES):
        out[f"{w}_start"] = round(float(ts[0, i]), 5)
        out[f"{w}_duration"] = round(float(du[0, i]), 5)
        out[f"{w}_throttle"] = round(float(ma[0, i]), 5)
    return out


def _clean_x(params: dict[str, float]) -> np.ndarray:
    """Params as stored (rounded) -> unit vector; searching/rolling out always goes through the rounded values."""
    return params_to_x(params)


def _binding(margins, ok_mask: np.ndarray | None) -> dict[str, Any]:
    """Smallest mean normalised slack among the judged margins (over ``ok_mask`` samples if any)."""
    rows = {}
    for name, (slack, lim) in margins.items():
        sl, li = np.asarray(slack, float), np.asarray(lim, float)
        if ok_mask is not None and ok_mask.any():
            sl, li = sl[ok_mask], li[ok_mask]
        rows[name] = (float(np.mean(sl / li)), float(np.mean(sl)))
    name = min(rows, key=lambda k: rows[k][0])
    label, unit = CHECK_UNITS[name]
    return dict(name=label, margin=round(rows[name][1], 4), unit=unit, normalized_margin=round(rows[name][0], 4), check=name)


# --------------------------------------------------------------------------- template
class RocketCar:
    id = TEMPLATE_ID

    # ---- spec
    def default_spec(self, idea: str, overrides: dict[str, float] | None = None) -> SpecSheet:
        A = Assumption
        ass = [
            A(key="thruster_force_max", label="Max thrust per nozzle (10 nozzles)", value=5000.0, unit="N", distribution=Fixed(),
              source="user", confidence=Confidence.med),
            A(key="vehicle_mass", label="Vehicle mass incl. wheels, occupant, gas", value=1300.0, unit="kg",
              distribution=Uniform(low=1235.0, high=1365.0),
              source="default: spikes/roadster model, +-5% as in the spike's disturbance set; production mass unverified (target <1700 kg, https://en.wikipedia.org/wiki/Tesla_Roadster_(second_generation))",
              confidence=Confidence.low),
            A(key="propellant_cap", label="Usable cold-gas propellant", value=60.0, unit="kg", distribution=Fixed(),
              source="default: 60 kg. The earlier pitch-only default (25 kg, roadster spike, no sourced figure) is too small for a second rotation axis; 60 kg is about what a 200 L cylinder holds at 300 bar (catalog: 200 L Nitrogen COPV for the Thrust variant; ideal/vdW N2 at 300 bar ~ 61 kg). Unverified", confidence=Confidence.low),
            A(key="isp", label="Specific impulse (cold-gas N2)", value=70.0, unit="s", distribution=Fixed(),
              source="unverified: 70 s as in the spike; docs/judgment-spec.md R4 gives 60-75 s (widen the distribution in the panel to test)", confidence=Confidence.low),
            A(key="thrust_spread", label="Independent per-nozzle thrust error, half-range (uniform)", value=0.0, unit="", distribution=Fixed(),
              source="default 0 = the spike's EFFECTIVE disturbance set. The spike's report says +-10% per thruster, but its code wrote that to actuator_gear[:,0] (always 0 for these motors), so its Monte-Carlo never varied thrust. Set e.g. 0.10 to apply it; the bundle reports the measured p_success at 3% and 10% separately", confidence=Confidence.low),
            A(key="thrust_error", label="Common thrust scale error", value=0.0, unit="", distribution=Fixed(),
              source="default (0: spike had none)", confidence=Confidence.low),
            A(key="com_offset_x", label="COM offset along car x", value=0.0, unit="m", distribution=Uniform(low=-0.15, high=0.15),
              source="default: spike disturbance set", confidence=Confidence.low),
            A(key="com_offset_z", label="COM offset along car z", value=0.0, unit="m", distribution=Uniform(low=-0.10, high=0.10),
              source="default: spike disturbance set", confidence=Confidence.low),
            A(key="ramp_speed", label="Launch speed at ramp lip", value=22.0, unit="m/s", distribution=Fixed(),
              source="default: roadster spike (fixed there)", confidence=Confidence.med),
            A(key="ramp_angle", label="Ramp angle", value=25.0, unit="deg", distribution=Fixed(),
              source="default: roadster spike (fixed there)", confidence=Confidence.med),
            A(key="ramp_height", label="COM height at ramp lip", value=2.2, unit="m", distribution=Fixed(),
              source="default: roadster spike", confidence=Confidence.med),
        ]
        by = {a.key: a for a in ass}
        for k, v in (overrides or {}).items():
            if k not in by:
                raise ValueError(f"unknown assumption {k!r}; known: {sorted(by)}")
            a = by[k]
            d = a.distribution
            if isinstance(d, Uniform):
                a.distribution = Uniform(low=d.low + v - a.value, high=d.high + v - a.value)
            elif isinstance(d, Normal):
                sh = v - a.value
                a.distribution = Normal(mean=d.mean + sh, std=d.std, clip_low=None if d.clip_low is None else d.clip_low + sh,
                                        clip_high=None if d.clip_high is None else d.clip_high + sh)
            a.value = float(v)
            if a.source != "user":
                a.source = "user"
                a.confidence = Confidence.high
        parts = [
            Part(name="Cold-gas nozzle set (18 nozzles)", role="thruster", mass_kg=0.0, cost_usd=None,
                 source="not itemised: mass inside vehicle_mass; no sourced unit cost"),
            Part(name="Composite overwrapped gas tank", role="propellant_tank", mass_kg=0.0, cost_usd=None,
                 source="not itemised: mass inside vehicle_mass; no sourced unit cost"),
            Part(name="Nitrogen propellant", role="propellant", mass_kg=float(by["propellant_cap"].value), cost_usd=None,
                 source="derived from propellant_cap; no sourced unit cost"),
        ]
        bounds = []
        for w in WIN_NAMES:
            bounds += [
                ParamBound(name=f"{w}_start", low=0.0, high=T_START_MAX, unit="s", init=0.4 * T_START_MAX, description=f"Burn start of window {w}"),
                ParamBound(name=f"{w}_duration", low=0.0, high=DUR_MAX, unit="s", init=0.4 * DUR_MAX, description=f"Burn duration of window {w}"),
                ParamBound(name=f"{w}_throttle", low=0.0, high=1.0, unit="", init=0.4, description=f"Throttle (fraction of thruster_force_max) of window {w}"),
            ]
        crit = [
            SuccessCriterion(name="full_pitch_turn", metric="pitch_turn_deg", comparator=Comparator.ge, threshold=340.0, unit="deg",
                             description="|integral of the body-frame pitch rate| from launch to first touchdown: one full turn about the body y axis (360 deg minus the 20 deg tolerance)"),
            SuccessCriterion(name="full_roll_turn", metric="roll_turn_deg", comparator=Comparator.ge, threshold=340.0, unit="deg",
                             description="|integral of the body-frame roll rate| from launch to first touchdown: one full turn about the body x axis (360 deg minus the 20 deg tolerance)"),
            SuccessCriterion(name="upright_at_touchdown", metric="touchdown_upright_error_deg", comparator=Comparator.le, threshold=30.0, unit="deg",
                             description="Roll and pitch each within 30 deg of a whole number of turns at first ground contact"),
            SuccessCriterion(name="touchdown_vertical_speed", metric="vz_td", comparator=Comparator.le, threshold=6.0, unit="m/s",
                             description="Vertical speed at first ground contact"),
            SuccessCriterion(name="touchdown_pitch_rate", metric="w_td", comparator=Comparator.le, threshold=3.0, unit="rad/s"),
            SuccessCriterion(name="touchdown_roll_rate", metric="wr_td", comparator=Comparator.le, threshold=3.0, unit="rad/s"),
            SuccessCriterion(name="propellant_within_cap", metric="fuel_kg", comparator=Comparator.le, threshold=float(by["propellant_cap"].value), unit="kg"),
            SuccessCriterion(name="no_thrust_after_contact", metric="post_contact_impulse_kNs", comparator=Comparator.lt, threshold=0.05, unit="kN*s"),
            SuccessCriterion(name="upright_settle", metric="final_upright_error_deg", comparator=Comparator.le, threshold=20.0, unit="deg",
                             description="Final roll and pitch each within 20 deg of a whole number of turns, ride height 0.5-0.8 m, vertical speed <1 m/s"),
        ]
        return SpecSheet(idea=idea, template_id=TemplateId.rocket_car, tier=Tier.verified_template, assumptions=ass, parts=parts,
                         param_bounds=bounds, success_criteria=crit)

    necessary_classes = {"flip_time_vs_air_time": "ACTUATOR_SATURATION", "roll_time_vs_air_time": "ACTUATOR_SATURATION", "propellant_mass": "ENERGY_BUDGET"}
    model_labels = MODEL_LABELS
    success_phrase = "a full roll and a full pitch rotation with an upright, speed-limited landing"

    def judge_nominal(self, spec: SpecSheet, params: dict[str, float]) -> bool:
        """Does ``params`` satisfy every success criterion on the nominal model?"""
        m, _, _ = self._sim(spec).evaluate_nominal(params_to_x(params)[None], self._env_nom(spec))
        return bool(m["success"][0])

    def model_info(self, spec: SpecSheet) -> dict[str, Any]:
        lv = _levers(_vals(spec)["vehicle_mass"])
        return dict(model_id="rocket_car_v1", model_hash=MODEL_HASH, mujoco_version=mujoco.__version__, n_bodies=1 + len(WHEELS),
                    n_thrusters=K, n_params=NPARAM, timestep_s=DT, horizon_s=T_SIM, mass_kg=round(lv["mass"], 2),
                    pitch_inertia_kgm2=round(lv["Iyy"], 1), roll_inertia_kgm2=round(lv["Ixx"], 1), integrator="implicitfast")

    # ---- helpers
    def _sim(self, spec: SpecSheet) -> Sim:
        return Sim(_limits(spec))

    def _env_nom(self, spec: SpecSheet) -> Env:
        return Env.from_values(_vals(spec))

    def rescale_params(self, params: dict[str, float], f_from: float, f_to: float) -> dict[str, float]:
        """Warm start across the sweep control: keep the commanded thrust (throttle * Fmax) roughly constant."""
        out = dict(params)
        for w in WIN_NAMES:
            out[f"{w}_throttle"] = float(np.clip(params[f"{w}_throttle"] * f_from / f_to, 0.0, 1.0))
        return out

    def fix_control(self, spec: SpecSheet) -> dict[str, Any]:
        """The user-facing control the fix search sweeps (also the web slider)."""
        return dict(key="thruster_force_max", label="Max thrust per nozzle", unit="N",
                    values=[3000.0, 4000.0, 5000.0, 6000.0, 8000.0, 10000.0],
                    hint="Thrust each of the 18 cold-gas nozzles can deliver (10 pitch/lift + 8 roll); no sourced figure exists for the real hardware.")

    # ---- necessary screen (favorable bounds, judgment-spec R3)
    def necessary_screen(self, spec: SpecSheet) -> list[NecessaryCheck]:
        v, A, lim = _vals(spec), _assum(spec), _limits(spec)
        q = lambda k, p: mclib.quantile(A[k], p)
        fmax_nom = v["thruster_force_max"] * (1.0 + v["thrust_error"])
        fmax_fav = v["thruster_force_max"] * (1.0 + q("thrust_error", 0.95)) * (1.0 + v.get("thrust_spread", 0.0))
        # favourable: lightest vehicle, strongest thrust, best Isp, fastest launch, best ramp angle of the two ends
        def run(mass, fmax, isp, spd, ang):
            return screen_bounds(mass, fmax, isp, v["propellant_cap"], v["ramp_height"], spd, np.deg2rad(ang), lim["w_max"], lim["wr_max"])
        nom = run(v["vehicle_mass"], fmax_nom, v["isp"], v["ramp_speed"], v["ramp_angle"])
        fav = None
        for ang in (q("ramp_angle", 0.05), q("ramp_angle", 0.95)):
            c = run(q("vehicle_mass", 0.05), fmax_fav, q("isp", 0.95), q("ramp_speed", 0.95), ang)
            if fav is None or (c["T_ub"] - max(c["t_min"], c["t_min_roll"])) > (fav["T_ub"] - max(fav["t_min"], fav["t_min_roll"])):
                fav = c
        note_fav = "evaluated at the favorable end of the assumptions (mass 5th pct, thrust +, Isp 95th pct, launch speed 95th pct)"
        return [
            NecessaryCheck(name="flip_time_vs_air_time", passed=bool(fav["t_min"] <= fav["T_ub"]), measured=round(fav["t_min"], 4),
                           limit=round(fav["T_ub"], 4), unit="s",
                           note=f"Min bang-bang PITCH rotation time (every pitch-capable nozzle individually at full thrust, pitch inertia {fav['Iyy']:.0f} kg m^2 from the MuJoCo model) vs flight-time upper bound (all lift thrusters at full thrust, impulse-capped); {note_fav}. Nominal: {nom['t_min']:.2f} s vs {nom['T_ub']:.2f} s."),
            NecessaryCheck(name="roll_time_vs_air_time", passed=bool(fav["t_min_roll"] <= fav["T_ub"]), measured=round(fav["t_min_roll"], 4),
                           limit=round(fav["T_ub"], 4), unit="s",
                           note=f"Min bang-bang ROLL rotation time (every roll-capable nozzle individually at full thrust, roll inertia {fav['Ixx']:.0f} kg m^2 from the MuJoCo model, one full turn) vs the same flight-time upper bound; {note_fav}. Nominal: {nom['t_min_roll']:.2f} s vs {nom['T_ub']:.2f} s."),
            NecessaryCheck(name="propellant_mass", passed=bool(fav["min_fuel"] <= v["propellant_cap"]), measured=round(fav["min_fuel"], 4),
                           limit=round(v["propellant_cap"], 4), unit="kg",
                           note=f"Lower bound on propellant from the required angular impulse of the more demanding axis over the flight time (rocket equation, impulse form; pitch {fav['min_fuel_pitch']:.2f} kg, roll {fav['min_fuel_roll']:.2f} kg at the favorable end); {note_fav}. Nominal: {nom['min_fuel']:.2f} kg."),
        ]

    # ---- search
    def search(self, spec: SpecSheet, seed: int, budget: Budget) -> SearchResult:
        sim = self._sim(spec)
        env = self._env_nom(spec)
        rng = np.random.default_rng(seed)
        t0 = time.perf_counter()
        e0 = sim.evals
        best = dict(cost=np.inf, x=None, success=False)
        pop, restarts, log, stopped = 64, 0, [], "evals"
        seed_x, seed_cost, seed_ok = seeded_start(sim, env)
        best = dict(cost=seed_cost, x=seed_x.copy(), success=seed_ok)
        while not best["success"]:
            if sim.evals - e0 >= budget.max_evals:
                break
            if time.perf_counter() - t0 >= budget.max_seconds:
                stopped = "time"
                break
            x0, sigma0, pop = start_point(restarts, rng, seed_x)
            es = cma.CMAEvolutionStrategy(x0, sigma0, dict(bounds=[0, 1], popsize=pop, seed=int(rng.integers(1 << 30)), verbose=-9,
                                                           tolfun=1e-9, tolx=1e-9))
            g = 0
            while not es.stop() and g < 150 and sim.evals - e0 < budget.max_evals:
                if time.perf_counter() - t0 >= budget.max_seconds:
                    stopped = "time"
                    break
                X = np.array(es.ask())
                m, _, _ = self.eval_x(sim, X, env)
                es.tell(X, m["cost"])
                g += 1
                if m["success"].any():
                    i = int(np.where(m["success"], m["cost"], np.inf).argmin())
                    best = dict(cost=float(m["cost"][i]), x=X[i].copy(), success=True)
                    break
                i = int(m["cost"].argmin())
                if m["cost"][i] < best["cost"]:
                    best = dict(cost=float(m["cost"][i]), x=X[i].copy(), success=False)
            log.append(dict(restart=restarts, popsize=pop, generations=g, best_cost=round(best["cost"], 4)))
            restarts += 1
            if stopped == "time":
                break
        params = x_to_params(best["x"])
        # re-judge the ROUNDED params so the witness we report is exactly what a replay will run
        mb = self.eval_x(sim, params_to_x(params)[None], env)[0]
        found = bool(mb["success"][0])
        failed = [k for k, v in mb["ok"].items() if not bool(v[0])]
        detail: dict[str, Any] = dict(
            restarts=restarts, log=log, stopped_by=stopped, failed_checks=failed,
            best_metrics={k: round(float(mb[k][0]), 4) for k in ("pitch_turn", "roll_turn", "phi_td", "pit_td", "phi_end", "pit_end", "vz_td", "w_td", "wr_td", "fuel", "post_imp")},
            binding=_binding(mb["margins"], None), taxonomy={k: TAXONOMY[k] for k in failed},
            rollout_evals=sim.evals - e0,
        )
        return SearchResult(found=found, best_params=params, n_evals=sim.evals - e0, wall_seconds=time.perf_counter() - t0,
                            best_cost=float(best["cost"]), detail=detail)

    def eval_x(self, sim: Sim, X, env: Env):
        return sim.evaluate_nominal(X, env)

    # ---- robustify (second CMA-ES stage on perturbed models drawn from the assumption distributions)
    def robustify(self, spec: SpecSheet, params: dict[str, float], seed: int, budget: Budget, k: int = 24, popsize: int = 32, rounds: int = 3):
        """Second CMA-ES stage on perturbed models. Each round draws a fresh training set (nominal model + k-1 draws from the
        assumption distributions, seeds disjoint from the held-out MC) and continues from the previous round's best schedule.
        The returned schedule always remains a witness on the NOMINAL model."""
        sim = self._sim(spec)
        fixed = _vals(spec)
        t0 = time.perf_counter()
        e0 = sim.evals
        per_gen = popsize * k
        max_gens = int(min(25, max(4, 3 * budget.max_evals // per_gen // rounds)))   # robustify may use ~3x the search eval budget
        x, best_rate, tot_gens = params_to_x(params), -1.0, 0
        for rd in range(rounds):
            s = mclib.sample_assumptions(spec, k, mclib.derive_seed(seed, "robustify", rd), aux_jitter)
            for key in list(s):
                if key == "_thrust_jitter":
                    s[key][0] = 0.0
                elif key in fixed:
                    s[key][0] = fixed[key]
            env = Env.from_samples(s, fixed)
            models, x0s = sim.models(env), sim.x0(env)
            es = cma.CMAEvolutionStrategy(x, 0.05, dict(bounds=[0, 1], popsize=popsize, seed=(seed + rd) % (1 << 30), verbose=-9))
            best_x, rd_rate, best_c, gens = x.copy(), -1.0, np.inf, 0
            while gens < max_gens and time.perf_counter() - t0 < budget.max_seconds:
                X = np.array(es.ask())
                m, _, _ = sim.evaluate_models(X, env, models, x0s)
                c = m["cost"].reshape(len(X), k)
                sc = m["success"].reshape(len(X), k)
                costs, succ = c.mean(1) + 2.0 * (1 - sc.mean(1)), sc.mean(1)
                es.tell(X, costs)
                nom_ok = sc[:, 0]
                i = int(np.where(nom_ok, costs, np.inf).argmin()) if nom_ok.any() else -1
                if i >= 0 and (succ[i] > rd_rate or (succ[i] == rd_rate and costs[i] < best_c)):
                    best_x, rd_rate, best_c = X[i].copy(), float(succ[i]), float(costs[i])
                gens += 1
                if rd_rate >= 0.99 and gens >= max(3, max_gens // 3):
                    break
            tot_gens += gens
            if rd_rate >= 0:
                x, best_rate = best_x, rd_rate
        return x_to_params(x), dict(train_success=best_rate, train_samples=k, rounds=rounds, generations=tot_gens, evals=sim.evals - e0,
                                    wall_seconds=time.perf_counter() - t0)

    # ---- Monte-Carlo
    def monte_carlo(self, spec: SpecSheet, params: dict[str, float], seed: int, n: int) -> McResult:
        sim = self._sim(spec)
        fixed = _vals(spec)
        thr1 = sim.controls(params_to_x(params)[None])
        store: dict[str, Any] = {}

        def evaluate(samples):
            env = Env.from_samples(samples, fixed)
            m_ = env.n
            thr = np.repeat(thr1, m_, axis=0)
            st = sim.run(thr, sim.models(env), sim.x0(env))
            m = sim.metrics(st, thr, env)
            if "first" not in store:
                store.update(first=True, binding=_binding(m["margins"], m["success"]), vz=m["vz_td"].copy(), fuel=m["fuel"].copy())
            return m["success"], {k: ~v for k, v in m["ok"].items()}

        res = mclib.run_mc(evaluate, spec, n, seed, taxonomy=TAXONOMY, aux=aux_jitter, oat=True, n_oat=48)
        b = dict(store["binding"])
        b["failed_checks"] = (res.binding or {}).get("failed_checks", {})
        b["mean_touchdown_vz"] = round(float(store["vz"].mean()), 3)
        b["mean_fuel_kg"] = round(float(store["fuel"].mean()), 3)
        res.binding = b
        return res

    # ---- rollout / trajectory
    def rollout(self, spec: SpecSheet, params: dict[str, float], seed: int) -> Trajectory:
        sim = self._sim(spec)
        env = self._env_nom(spec)
        x = params_to_x(params)
        thr = sim.controls(x[None])[0]                       # (T,K)
        mdl = sim.models(env)[0]
        d = mujoco.MjData(mdl)
        x0 = sim.x0(env)[0]
        mujoco.mj_setState(mdl, d, x0, mujoco.mjtState.mjSTATE_FULLPHYSICS)
        mujoco.mj_forward(mdl, d)
        bodies = ["car"] + [f"wheel_{n}" for n, *_ in WHEELS]
        bid = [mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_BODY, b) for b in bodies]
        sid = [mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_SITE, t[0]) for t in THRUSTERS]
        stride = 5
        pos, quat = [], []
        series = {n: [] for n in ("pitch_deg", "roll_deg", "height_m", "speed_mps", "fuel_kg")}
        thrust_series = {t[0]: [] for t in THRUSTERS}
        impulse, pit_u, rol_u = 0.0, 0.0, 0.0                # body-frame rate integrals (rotation progress), same definition as the judge
        touchdown, peak_force = None, 0.0
        qs = np.zeros(4)
        for k in range(NSTEP):
            if k % stride == 0:
                p, q = [], []
                for b in bid:
                    p.append([round(float(c), 4) for c in d.xpos[b]])
                    q.append([round(float(c), 5) for c in d.xquat[b]])
                # thruster bodies: pose of the site (local +Z = force direction ON the vehicle)
                for s_ in sid:
                    p.append([round(float(c), 4) for c in d.site_xpos[s_]])
                    mujoco.mju_mat2Quat(qs, d.site_xmat[s_])
                    q.append([round(float(c), 5) for c in qs])
                pos.append(p)
                quat.append(q)
                series["pitch_deg"].append(round(float(np.degrees(pit_u)), 3))
                series["roll_deg"].append(round(float(np.degrees(rol_u)), 3))
                series["height_m"].append(round(float(d.qpos[2]), 4))
                series["speed_mps"].append(round(float(np.linalg.norm(d.qvel[:3])), 4))
                series["fuel_kg"].append(round(impulse / (env.isp[0] * G0), 4))
                for i, t in enumerate(THRUSTERS):
                    thrust_series[t[0]].append(round(float(thr[k, i] * env.fmax[0] * env.tscale[0, i]), 2))
            F = thr[k] * env.fmax[0] * env.tscale[0]
            impulse += float(F.sum()) * DT
            d.ctrl[:] = thr[k]
            mujoco.mj_step(mdl, d)
            rol_u += float(d.qvel[3]) * DT
            pit_u += float(d.qvel[4]) * DT
            # touchdown bookkeeping from the actual contact set (the car starts above the ground, so any contact is the landing)
            if d.ncon > 0:
                fsum = 0.0
                cp = None
                f6 = np.zeros(6)
                for ci in range(d.ncon):
                    c = d.contact[ci]
                    mujoco.mj_contactForce(mdl, d, ci, f6)
                    fsum += abs(f6[0])
                    cp = c.pos if cp is None else cp
                if touchdown is None and fsum > 0:
                    touchdown = dict(t=(k + 1) * DT, pos=[float(c) for c in cp], force=fsum)
                if touchdown is not None and (k + 1) * DT - touchdown["t"] < 0.3:
                    peak_force = max(peak_force, fsum)
        events: list[ContactEvent] = []
        ts, du, ma = Sim.decode(x[None])
        for i in range(NWIN):
            if du[0, i] <= 1e-3 or ma[0, i] <= 1e-3:
                continue
            tname = THRUSTERS[int(np.flatnonzero(GROUP_OF == WIN_GROUP[i])[0])][0]
            fN = float(ma[0, i] * env.fmax[0])
            events.append(ContactEvent(t=round(float(ts[0, i]), 3), kind="thrust", body=f"thr_{tname}", note=f"{WIN_NAMES[i]} ignition ({fN:.0f} N per nozzle)", magnitude=fN))
            events.append(ContactEvent(t=round(float(min(ts[0, i] + du[0, i], T_SIM)), 3), kind="thrust", body=f"thr_{tname}", note=f"{WIN_NAMES[i]} cutoff", magnitude=0.0))
        # final judgement of exactly this rollout
        env1 = self._env_nom(spec)
        m, _, _ = sim.evaluate_nominal(x[None], env1)
        success = bool(m["success"][0])
        if touchdown is not None:
            events.append(ContactEvent(t=round(touchdown["t"], 3), kind="landing", body="car", pos=[round(c, 4) for c in touchdown["pos"]],
                                       magnitude=round(peak_force, 1), note=f"first touchdown; peak contact normal force {peak_force:.0f} N in 0.3 s (pitch turned {np.degrees(m['pitch_turn'][0]):.0f} deg, roll turned {np.degrees(m['roll_turn'][0]):.0f} deg, vz {m['vz_td'][0]:.2f} m/s)"))
        if not success:
            failed = [k_ for k_, v in m["ok"].items() if not bool(v[0])]
            tf = touchdown["t"] if touchdown else T_SIM
            events.append(ContactEvent(t=round(float(tf), 3), kind="failure", body="car",
                                       pos=[round(float(c), 4) for c in d.xpos[bid[0]]], note="best attempt FAILED: " + ", ".join(failed)))
        events.sort(key=lambda e: e.t)
        geoms = [Geom(type=GeomType.box, size=[LENGTH / 2, WIDTH / 2, (HEIGHT - WHEEL_R * 0.5) / 2],
                      pos=[0.0, 0.0, HEIGHT / 2 - (HEIGHT - WHEEL_R * 0.5) / 2], rgba=[0.8, 0.1, 0.1, 1.0])]
        tb = [TrajBody(name="car", parent=None, geoms=geoms)]
        tb[0].name = "chassis"
        for n, *_ in WHEELS:
            tb.append(TrajBody(name=f"wheel_{n}", parent="chassis",
                               geoms=[Geom(type=GeomType.cylinder, size=[WHEEL_R, WHEEL_HW], quat=[0.70710678, 0.70710678, 0.0, 0.0], rgba=[0.12, 0.12, 0.12, 1.0])]))
        for t in THRUSTERS:
            tb.append(TrajBody(name=f"thr_{t[0]}", parent="chassis", geoms=[]))
        for e in events:
            if e.body == "car":
                e.body = "chassis"
        ser = [TimeSeries(name=f"thrust_{t[0]}", unit="N", values=thrust_series[t[0]]) for t in THRUSTERS]
        ser += [TimeSeries(name="pitch_deg", unit="deg", values=series["pitch_deg"]),
                TimeSeries(name="roll_deg", unit="deg", values=series["roll_deg"]),
                TimeSeries(name="height_m", unit="m", values=series["height_m"]),
                TimeSeries(name="speed_mps", unit="m/s", values=series["speed_mps"]),
                TimeSeries(name="fuel_kg", unit="kg", values=series["fuel_kg"])]
        return Trajectory(
            model_id="rocket_car_v1", model_hash=MODEL_HASH, dt=stride * DT, bodies=tb, pos=pos, quat=quat, events=events, series=ser,
            meta=TrajectoryMeta(seed=int(seed), mujoco_version=mujoco.__version__, template_id=TemplateId.rocket_car, params=params,
                                note=("nominal-assumption rollout; success=" + str(success) + "; " + SIMPLIFIED)))

    def bom(self, spec: SpecSheet, params: dict[str, float]) -> list[BomItem]:
        v = _vals(spec)
        peak = max(params[f"{w}_throttle"] for w in WIN_NAMES) * v["thruster_force_max"]
        return [
            BomItem(name=f"Cold-gas nozzle, >= {v['thruster_force_max']:.0f} N each (18 positions: 4 outer pitch, 4 belly lift, 2 inner pitch, 8 side roll)",
                    role="thruster", quantity=18, mass_kg=None, unit_cost_usd=None,
                    source=f"required rating from the sweep control; best schedule peaks at {peak:.0f} N; no sourced unit cost"),
            BomItem(name=f"Composite gas tank for >= {v['propellant_cap']:.0f} kg N2", role="propellant_tank", quantity=1, mass_kg=None,
                    unit_cost_usd=None, source="size from propellant_cap; no sourced unit cost"),
            BomItem(name="Nitrogen propellant (usable)", role="propellant", quantity=1, mass_kg=float(v["propellant_cap"]), unit_cost_usd=None,
                    source="propellant_cap assumption"),
            BomItem(name="Proportional valves + plumbing (one per nozzle)", role="valve", quantity=18, mass_kg=None, unit_cost_usd=None,
                    source="needed for the throttle schedule; no sourced unit cost"),
        ]


TEMPLATE = RocketCar()
