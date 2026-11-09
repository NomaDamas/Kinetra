"""Roadster thruster-flip feasibility spike: MJCF template, parameterization, rollout
evaluation, analytic necessary-condition screen.  Physics judge = MuJoCo.

Conventions
-----------
* World: x forward, y left, z up.  Body frame = world frame at identity.
* Pitch theta = rotation about +y.  theta>0 => nose (+x) goes DOWN (front flip).
  theta = atan2(-R20, R00) of the body rotation matrix, unwrapped over time.
* Thruster force direction = force acting ON the body (opposite of exhaust).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import mujoco
import numpy as np
from mujoco import rollout as mj_rollout

G0 = 9.80665
TOL_FIN = np.deg2rad(20.0)   # final pitch / roll tolerance (spec: +-20 deg)
TOL_TD = np.deg2rad(30.0)    # pitch tolerance at first ground contact


# --------------------------------------------------------------------------- config
@dataclass
class Config:
    # vehicle (Tesla-Roadster-like assumptions; all editable "assumptions panel" items)
    mass_total: float = 1300.0
    wheel_mass: float = 20.0
    length: float = 4.2
    width: float = 1.9
    height: float = 1.2
    wheel_r: float = 0.32
    wheel_hw: float = 0.12          # half width of wheel cylinder
    # thrusters (cold-gas style)
    fmax: float = 5000.0            # N per thruster
    isp: float = 70.0               # s, cold gas N2
    fuel_cap: float = 25.0          # kg, usable propellant (mass included in mass_total)
    # scenario (ramp launch)
    scenario: str = "ramp"          # "ramp" | "standing"
    ramp_speed: float = 20.0        # m/s along ramp
    ramp_angle: float = np.deg2rad(20.0)
    ramp_height: float = 1.8        # COM height at ramp end
    # simulation
    dt: float = 0.004
    t_sim: float = 4.5
    # success limits
    vz_max: float = 9.0             # m/s vertical speed at first ground contact
    w_max: float = 3.0              # rad/s pitch rate at first ground contact
    # parameter bounds
    t_start_max: float = 2.5
    dur_max: float = 2.0

    @property
    def nstep(self):
        return int(round(self.t_sim / self.dt))


# thruster layout: (name, group, x, y, z, force dir on body)
UP, DN = (0, 0, 1), (0, 0, -1)
THRUSTERS = [
    ("nose_dn", 0, 2.10, 0.0, 0.3, DN),   # fwd-pitch couple (front flip): torque_y = +
    ("tail_up", 0, -2.10, 0.0, 0.3, UP),
    ("nose_up", 1, 2.10, 0.0, 0.3, UP),   # back-pitch couple (backflip / brake): torque_y = -
    ("tail_dn", 1, -2.10, 0.0, 0.3, DN),
    ("belly_fl", 2, 1.0, 0.6, -0.5, UP),  # lift quad (4 belly thrusters)
    ("belly_fr", 2, 1.0, -0.6, -0.5, UP),
    ("belly_rl", 2, -1.0, 0.6, -0.5, UP),
    ("belly_rr", 2, -1.0, -0.6, -0.5, UP),
    ("mid_dn", 3, 1.00, 0.0, 0.3, DN),    # inner fwd-pitch couple (lever 1 m)
    ("mid_up", 3, -1.00, 0.0, 0.3, UP),
]
GROUP_NAMES = ["pitch_fwd_outer", "pitch_back_outer", "lift_quad", "pitch_fwd_inner"]  # fwd: torque +theta (nose down); back: -theta (nose up)
# burn windows: each window = (t_start, duration, throttle) applied to one thruster group.
# 4 groups, lift pair gets a 2nd window (landing burn) -> 5 windows x 3 = 15 params
WIN_GROUP = [0, 1, 2, 3, 2]
WIN_NAMES = ["pitch_fwd_outer", "pitch_back_outer", "lift_main", "pitch_fwd_inner", "lift_landing"]
NGROUP = len(WIN_GROUP)
GROUP_OF = np.array([t[1] for t in THRUSTERS])
GROUP_MAT = np.zeros((NGROUP, len(THRUSTERS)))
for _w, _g in enumerate(WIN_GROUP):
    GROUP_MAT[_w, GROUP_OF == _g] = 1.0
NPARAM = NGROUP * 3  # (t_start, duration, magnitude) per window = 15


# --------------------------------------------------------------------------- MJCF
def build_mjcf(cfg: Config) -> str:
    m_body = cfg.mass_total - 4 * cfg.wheel_mass
    L, W, H = cfg.length, cfg.width, cfg.height
    ixx = m_body / 12 * (W**2 + H**2)
    iyy = m_body / 12 * (L**2 + H**2)
    izz = m_body / 12 * (L**2 + W**2)
    box_hz = (H - cfg.wheel_r * 0.5 - 0.0) / 2  # box spans z in [-0.3, 0.6]
    wheel_z = -H / 2 + cfg.wheel_r
    wheels = ""
    for nm, wx, wy in [("fl", 1.3, 0.85), ("fr", 1.3, -0.85), ("rl", -1.3, 0.85), ("rr", -1.3, -0.85)]:
        wheels += (
            f'<body name="wheel_{nm}" pos="{wx} {wy} {wheel_z}">'
            f'<joint name="spin_{nm}" type="hinge" axis="0 1 0" damping="0.0"/>'
            f'<geom name="tire_{nm}" type="cylinder" size="{cfg.wheel_r} {cfg.wheel_hw}" '
            f'euler="90 0 0" mass="{cfg.wheel_mass}" friction="0.9 0.005 0.0001"/></body>'
        )
    sites, acts = "", ""
    for name, _g, x, y, z, d in THRUSTERS:
        sites += f'<site name="{name}" pos="{x} {y} {z}" zaxis="{d[0]} {d[1]} {d[2]}" size="0.06" rgba="1 0.4 0 1"/>'
        acts += (
            f'<motor name="{name}" site="{name}" gear="0 0 1 0 0 0" '
            f'ctrllimited="true" ctrlrange="0 {cfg.fmax}"/>'
        )
    return f"""<mujoco model="roadster_flip">
  <compiler angle="degree"/>
  <option timestep="{cfg.dt}" gravity="0 0 -{G0}" integrator="implicitfast"/>
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


class Sim:
    """Compiled model + thread pool + helpers."""

    def __init__(self, cfg: Config, nthread: int | None = None):
        import os

        self.cfg = cfg
        self.model = mujoco.MjModel.from_xml_string(build_mjcf(cfg))
        self.nthread = nthread or max(1, (os.cpu_count() or 2) - 0)
        self.datas = [mujoco.MjData(self.model) for _ in range(self.nthread)]
        self.pool = mj_rollout.Rollout(nthread=self.nthread)
        self.nq, self.nv = self.model.nq, self.model.nv
        self.nth = self.model.nu
        self.dt = cfg.dt
        self.x0 = self._initial_state()
        self.inertia = self._inertia_and_levers()
        self.evals = 0
        self.t_rollout = 0.0
        # lowest-point geometry (local frame)
        L, W = cfg.length, cfg.width
        H = cfg.height
        self.bz0 = -H / 2 + cfg.wheel_r * 0.5   # chassis box bottom (local z)
        self.bz1 = H / 2
        sx, sy = L / 2, W / 2
        self.corners = np.array(
            [[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (self.bz0, self.bz1)]
        )
        self.wheel_c = np.array(
            [[1.3, .85, -H / 2 + cfg.wheel_r], [1.3, -.85, -H / 2 + cfg.wheel_r],
             [-1.3, .85, -H / 2 + cfg.wheel_r], [-1.3, -.85, -H / 2 + cfg.wheel_r]]
        )

    # ---- initial state
    def _initial_state(self):
        cfg, m = self.cfg, self.model
        d = mujoco.MjData(m)
        if cfg.scenario == "ramp":
            th0 = -cfg.ramp_angle  # nose up
            d.qpos[:3] = [0, 0, cfg.ramp_height]
            d.qpos[3:7] = [np.cos(th0 / 2), 0, np.sin(th0 / 2), 0]
            v = cfg.ramp_speed
            d.qvel[:3] = [v * np.cos(cfg.ramp_angle), 0, v * np.sin(cfg.ramp_angle)]
            d.qvel[6:10] = v / cfg.wheel_r  # wheels rolling (relative to body)
        else:  # standing start on the ground, wheels at rest
            d.qpos[:3] = [0, 0, cfg.height / 2 - 0.0]
            d.qpos[3:7] = [1, 0, 0, 0]
        mujoco.mj_forward(m, d)
        s = np.empty(mujoco.mj_stateSize(m, mujoco.mjtState.mjSTATE_FULLPHYSICS))
        mujoco.mj_getState(m, d, s, mujoco.mjtState.mjSTATE_FULLPHYSICS)
        self.theta0 = -cfg.ramp_angle if cfg.scenario == "ramp" else 0.0
        return s

    def _inertia_and_levers(self):
        """Whole-vehicle Iyy about COM (CRB at identity pose) and per-thruster y-torque @ unit force."""
        m = self.model
        d = mujoco.MjData(m)
        d.qpos[:7] = [0, 0, 1, 1, 0, 0, 0]
        mujoco.mj_forward(m, d)
        M = np.zeros((m.nv, m.nv))
        mujoco.mj_fullM(m, d, M)
        com = d.subtree_com[1]
        tau_y, fdir_z = [], []
        for i in range(self.nth):
            sid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, THRUSTERS[i][0])
            r = d.site_xpos[sid] - com
            f = d.site_xmat[sid].reshape(3, 3)[:, 2]
            tau_y.append(r[2] * f[0] - r[0] * f[2])
            fdir_z.append(f[2])
        return dict(mass=float(M[0, 0]), Iyy=float(M[4, 4]), tau_y=np.array(tau_y), fz=np.array(fdir_z))

    # ---- parameter decoding
    def decode(self, X):
        """X (n,12) in [0,1] -> ts, dur, mag each (n,4)."""
        X = np.atleast_2d(X).reshape(-1, NGROUP, 3)
        ts = X[..., 0] * self.cfg.t_start_max
        dur = X[..., 1] * self.cfg.dur_max
        mag = X[..., 2]
        return ts, dur, mag

    def controls(self, X):
        ts, dur, mag = self.decode(X)
        t = (np.arange(self.cfg.nstep)) * self.dt  # time at start of step k
        on = (t[None, None, :] >= ts[..., None]) & (t[None, None, :] < (ts + dur)[..., None])  # (n,G,T)
        grp = on * mag[..., None]  # throttle fraction per group
        thr = np.einsum("ngt,gk->ntk", grp, GROUP_MAT)  # (n,T,K)
        return thr * self.cfg.fmax, thr

    # ---- perturbed models
    def perturbed_models(self, rng: np.random.Generator, n: int, mass_pct=0.05, thrust_pct=0.10,
                         com_xz=(0.15, 0.10)):
        models, info = [], []
        for _ in range(n):
            mdl = copy.copy(self.model)
            sm = 1 + rng.uniform(-mass_pct, mass_pct)
            mdl.body_mass[:] = self.model.body_mass * sm
            mdl.body_inertia[:] = self.model.body_inertia * sm
            dx, dz = rng.uniform(-com_xz[0], com_xz[0]), rng.uniform(-com_xz[1], com_xz[1])
            mdl.body_ipos[1] = self.model.body_ipos[1] + np.array([dx, 0, dz])
            ft = 1 + rng.uniform(-thrust_pct, thrust_pct, self.nth)
            mdl.actuator_gear[:, 0] = self.model.actuator_gear[:, 0] * ft
            mujoco.mj_setConst(mdl, mujoco.MjData(mdl))
            models.append(mdl)
            info.append(dict(mass_scale=sm, com_dx=dx, com_dz=dz, thrust_scale=ft.tolist()))
        return models, info

    # ---- rollout
    def run(self, ctrl, models=None):
        """ctrl (n,T,K) -> state (n,T,nstate)."""
        import time

        t0 = time.perf_counter()
        n = ctrl.shape[0]
        mdl = self.model if models is None else models
        st, _ = self.pool.rollout(mdl, self.datas, self.x0[None, :], np.ascontiguousarray(ctrl))
        self.t_rollout += time.perf_counter() - t0
        self.evals += n
        return st

    # ---- metrics
    def metrics(self, state, thr):
        """Vectorised scoring. state (n,T,ns), thr (n,T,K) throttle fractions."""
        cfg, nq = self.cfg, self.nq
        n, T = state.shape[:2]
        qp = state[..., 1 : 1 + nq]
        qv = state[..., 1 + nq :]
        pos = qp[..., :3]
        qw, qx, qy, qz = (qp[..., 3], qp[..., 4], qp[..., 5], qp[..., 6])
        R00 = 1 - 2 * (qy**2 + qz**2)
        R20 = 2 * (qx * qz - qw * qy)
        R21 = 2 * (qy * qz + qw * qx)
        R22 = 1 - 2 * (qx**2 + qy**2)
        # rotation matrix columns for lowest-point
        R = np.empty(qp.shape[:2] + (3, 3))
        R[..., 0, 0] = R00
        R[..., 0, 1] = 2 * (qx * qy - qw * qz)
        R[..., 0, 2] = 2 * (qx * qz + qw * qy)
        R[..., 1, 0] = 2 * (qx * qy + qw * qz)
        R[..., 1, 1] = 1 - 2 * (qx**2 + qz**2)
        R[..., 1, 2] = 2 * (qy * qz - qw * qx)
        R[..., 2, 0] = R20
        R[..., 2, 1] = R21
        R[..., 2, 2] = R22
        theta = np.unwrap(np.arctan2(-R20, R00), axis=1)
        # lowest point height
        zc = pos[..., 2:3] + np.einsum("ntj,cj->ntc", R[..., 2, :], self.corners)  # (n,T,8)
        wz = pos[..., 2:3] + np.einsum("ntj,cj->ntc", R[..., 2, :], self.wheel_c)
        ay = np.abs(R21)[..., None]
        wlow = wz - (cfg.wheel_r * np.sqrt(np.clip(1 - ay**2, 0, 1)) + cfg.wheel_hw * ay)
        hlow = np.minimum(zc.min(-1), wlow.min(-1))  # (n,T)
        touching = hlow < 0.02
        airborne = hlow > 0.05
        has_air = airborne.any(1)
        ia = airborne.argmax(1)
        after_air = np.arange(T)[None, :] > ia[:, None]
        td_mask = touching & after_air & has_air[:, None]
        landed = td_mask.any(1)
        itd = np.where(landed, td_mask.argmax(1), T - 1)
        idx = np.arange(n)
        th_td = theta[idx, itd]
        vz_td = -qv[idx, itd, 2]
        w_td = np.abs(qv[idx, itd, 4])
        th_end = theta[:, -1]
        two_pi = 2 * np.pi

        def flip_err(th):
            return np.minimum(np.abs(th - two_pi), np.abs(th + two_pi))

        err_td, err_fin = flip_err(th_td), flip_err(th_end)
        roll_end = np.abs(np.arcsin(np.clip(R21[:, -1], -1, 1)))
        z_end = pos[:, -1, 2]
        vz_end = np.abs(qv[:, -1, 2])
        # thrust used after first contact (kN*s, throttle*fmax)
        after = (np.arange(T)[None, :] >= itd[:, None]) & landed[:, None]
        post_imp = (thr.sum(-1) * after).sum(1) * cfg.fmax * self.dt / 1000.0
        # fuel
        impulse = thr.sum((1, 2)) * cfg.fmax * self.dt  # N*s (=sum_k thrust*dt)
        fuel = impulse / (cfg.isp * G0)
        # spec checks
        ok = dict(
            landed=landed,
            flip_final=err_fin <= TOL_FIN,
            flip_td=err_td <= TOL_TD,
            impact_vz=vz_td <= cfg.vz_max,
            impact_w=w_td <= cfg.w_max,
            roll=roll_end <= TOL_FIN,
            ride_height=(z_end > 0.5) & (z_end < 0.8),
            settled=vz_end < 1.0,
            no_post_thrust=post_imp < 0.05,
            fuel=fuel <= cfg.fuel_cap,
        )
        success = np.ones(n, bool)
        for v in ok.values():
            success &= v
        cost = (
            err_td / TOL_TD + err_fin / TOL_FIN
            + 8 * np.maximum(0, vz_td - cfg.vz_max) / cfg.vz_max
            + 4 * np.maximum(0, w_td - cfg.w_max) / cfg.w_max
            + 2 * np.maximum(0, roll_end - TOL_FIN) / TOL_FIN
            + 2 * np.maximum(0, post_imp)
            + 2 * np.maximum(0, fuel / cfg.fuel_cap - 1)
            + 3.0 * (~landed)
            + 1.0 * (~ok["ride_height"])
            + 0.02 * fuel / cfg.fuel_cap
        )
        return dict(
            success=success, cost=cost, ok=ok, th_td=th_td, th_end=th_end, vz_td=vz_td, w_td=w_td,
            roll_end=roll_end, z_end=z_end, fuel=fuel, post_imp=post_imp, itd=itd, theta=theta,
            err_td=err_td, err_fin=err_fin, hlow=hlow,
        )

    def evaluate(self, X, models=None):
        ctrl, thr = self.controls(X)
        st = self.run(ctrl, models)
        return self.metrics(st, thr), st, thr


# --------------------------------------------------------------------------- necessary-condition screen
def necessary_screen(cfg: Config, sim: Sim | None = None) -> dict:
    """Analytic, conservative (relaxed) necessary conditions. A failure => INFEASIBLE (strong)."""
    sim = sim or Sim(cfg, nthread=1)
    I, m = sim.inertia["Iyy"], sim.inertia["mass"]
    tau = sim.inertia["tau_y"] * cfg.fmax          # N*m per thruster at full thrust
    fz = np.maximum(0, sim.inertia["fz"]) * cfg.fmax
    Fup = float(fz.sum())
    th0 = sim.theta0
    # --- available flight time upper bound (all up-capable thrusters on the whole flight, impulse-capped)
    I_tot = cfg.fuel_cap * cfg.isp * G0            # N*s total impulse available from propellant
    h0 = cfg.ramp_height if cfg.scenario == "ramp" else cfg.height / 2
    vz0 = cfg.ramp_speed * np.sin(cfg.ramp_angle) if cfg.scenario == "ramp" else 0.0
    h_land = cfg.height / 2  # COM height at wheel contact
    tt = np.linspace(0, 12, 120001)
    vg = np.minimum(Fup * tt, I_tot) / m
    gain = np.concatenate([[0], np.cumsum(0.5 * (vg[1:] + vg[:-1]) * np.diff(tt))])
    z = h0 + vz0 * tt - 0.5 * G0 * tt**2 + gain
    if cfg.scenario == "standing":
        # must first beat gravity: if Fup <= m*g the vehicle can never leave the ground
        can_lift = Fup > m * G0
        if not can_lift:
            T_ub = 0.0
        else:
            up = np.where(z[1:] > h_land + 0.05)[0]  # airborne after liftoff
            T_ub = float(tt[up[-1] + 1] - 0) if up.size else 0.0
    else:
        can_lift = True
        below = np.where(z < h_land)[0]
        T_ub = float(tt[below[0]]) if below.size else float(tt[-1])
    # --- rotation: time-optimal bang-bang bound (both directions), final-rate cap w_max
    best = None
    for s in (+1, -1):
        dth_min = 2 * np.pi - TOL_FIN - s * th0    # smallest rotation (direction s) consistent with spec
        a_up = float(np.maximum(0, s * tau).sum() / I)
        a_dn = float(np.maximum(0, -s * tau).sum() / I)
        t_min = _bangbang_time(dth_min, a_up, a_dn, cfg.w_max)
        if best is None or t_min < best["t_min"]:
            best = dict(direction=s, alpha_up=a_up, alpha_dn=a_dn, t_min=t_min)
    c_rot = best["t_min"] <= T_ub
    # --- impulse / fuel bound (angular momentum -> thrust impulse via max lever arm)
    r_max = float(np.max(np.abs(sim.inertia["tau_y"])))  # m (torque per N)
    dth_min = 2 * np.pi - TOL_FIN - best["direction"] * th0
    w_req = dth_min / T_ub if T_ub > 0 else np.inf       # min mean rate needed
    L_req = I * (w_req + max(0.0, w_req - cfg.w_max))    # spin-up + brake
    J_min = L_req / r_max if r_max > 0 else np.inf
    fuel_min = J_min / (cfg.isp * G0)
    c_fuel = fuel_min <= cfg.fuel_cap
    checks = dict(
        can_leave_ground=bool(can_lift),
        angular_impulse_time=dict(ok=bool(c_rot), t_min_s=float(best["t_min"]), flight_time_upper_bound_s=T_ub,
                                  alpha_up=best["alpha_up"], alpha_dn=best["alpha_dn"], direction=best["direction"],
                                  delta_theta_rad=float(dth_min)),
        propellant=dict(ok=bool(c_fuel), min_fuel_kg=float(fuel_min) if np.isfinite(fuel_min) else None, fuel_cap_kg=cfg.fuel_cap,
                        min_thrust_impulse_Ns=float(J_min) if np.isfinite(J_min) else None),
    )
    feasible = bool(can_lift and c_rot and c_fuel)
    checks["verdict"] = "PASS_SCREEN" if feasible else "INFEASIBLE"
    checks["failed"] = [k for k, v in [("cannot_leave_ground", can_lift), ("angular_impulse_time", c_rot),
                                       ("propellant", c_fuel)] if not v]
    checks["Iyy"], checks["mass"] = I, m
    checks["label"] = "analytic rigid-body bound; strong evidence when INFEASIBLE"
    return checks


def _bangbang_time(dth, a_up, a_dn, w_f):
    """Min time to rotate dth from rest, ending with |rate|<=w_f, with accel a_up and decel a_dn."""
    if a_up <= 0:
        return np.inf
    # coast-free bang-bang: accelerate to wp then brake to w_f
    if a_dn > 0:
        # dth = wp^2/(2a_up) + (wp^2 - w_f^2)/(2 a_dn)
        wp2 = (dth + w_f**2 / (2 * a_dn)) / (1 / (2 * a_up) + 1 / (2 * a_dn))
        wp = np.sqrt(max(wp2, 0.0))
        if wp >= w_f:
            return wp / a_up + (wp - w_f) / a_dn
    # cannot brake enough (or no brake): reach w_f max, then coast
    d_acc = w_f**2 / (2 * a_up)
    if dth <= d_acc:
        return np.sqrt(2 * dth / a_up)
    return w_f / a_up + (dth - d_acc) / w_f
