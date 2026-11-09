"""Template ``humanoid_jump``: Unitree G1 (MuJoCo Menagerie) jump + landing.

Judge = MuJoCo.  10-parameter sagittal keyframe controller searched with CMA-ES; every number in a verdict
comes from a rollout or a MuJoCo static computation, never from an LLM (docs/judgment-spec.md section 2).

Metric choices (documented because they are easy to cheat):
* jump height = ballistic height ``vz_liftoff^2 / 2g`` of the whole-robot COM, NOT COM-rise (leg tucking inflates it);
* landing peak GRF is measured from the *first* foot contact after liftoff (sum of normal contact forces on the foot
  spheres) and is a hard success criterion against ``landing_grf_limit_bw`` (default/unverified assumption);
* torque saturation is real: MuJoCo clips actuator force to ``forcerange`` (scaled by ``torque_scale``).
Search failure is *weak* evidence ("not found in N evaluations"); only the necessary-condition checks can be strong.
"""
from __future__ import annotations

import atexit
import hashlib
import math
import multiprocessing as mp
import os
import time
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from physlab_core.schemas import (
    Assumption, BomItem, Comparator, Confidence, ContactEvent, Fixed, Geom, GeomType, NecessaryCheck, Normal,
    ParamBound, Part, SpecSheet, SuccessCriterion, TemplateId, TimeSeries, Tier, TrajBody, Trajectory,
    TrajectoryMeta, Uniform,
)

from ..base import Budget, McResult, SearchResult

G = 9.81
TEMPLATE_ID = "humanoid_jump"
GLB_PREFIX = "g1"  # Geom.mesh = "g1/<mesh name>.glb", relative to /assets/
MENAGERIE_URL = "https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_g1"

# --------------------------------------------------------------------------------------------- model location
_REPO = Path(__file__).resolve().parents[5]


def g1_dir() -> Path:
    """Directory holding g1.xml / scene.xml / assets (env KINETRA_MENAGERIE = mujoco_menagerie checkout root)."""
    cands = []
    if os.environ.get("KINETRA_MENAGERIE"):
        cands.append(Path(os.environ["KINETRA_MENAGERIE"]))
    cands.append(_REPO / "spikes/humanoid_jump/vendor/mujoco_menagerie")
    for c in cands:
        for sub in (c / "unitree_g1", c):
            if (sub / "scene.xml").exists() and (sub / "g1.xml").exists():
                return sub
    raise FileNotFoundError(
        "Unitree G1 model not found. Set KINETRA_MENAGERIE to a mujoco_menagerie checkout containing unitree_g1/ "
        f"(tried: {[str(c) for c in cands]}).")


def model_hash() -> str:
    d = g1_dir()
    h = hashlib.sha256()
    for f in ("g1.xml", "scene.xml"):
        h.update((d / f).read_bytes())
    return h.hexdigest()


# --------------------------------------------------------------------------------------------- parameters
# p = [crouch_hip, crouch_knee, take_hip, take_knee, air_hip, air_knee, land_hip, land_knee, T_down, T_push]
PNAMES = ["crouch_hip", "crouch_knee", "take_hip", "take_knee", "air_hip", "air_knee",
          "land_hip", "land_knee", "T_down", "T_push"]
PUNITS = ["rad", "rad", "rad", "rad", "rad", "rad", "rad", "rad", "s", "s"]
PDESC = [
    "hip-pitch angle at crouch bottom (neg = thigh forward)", "knee flexion at crouch bottom",
    "hip-pitch angle at take-off pose", "knee flexion at take-off pose",
    "hip-pitch angle in flight", "knee flexion in flight",
    "hip-pitch angle for landing", "knee flexion for landing (leg stroke / compliance)",
    "duration of the crouch-down phase", "duration of the push-off phase",
]
P0 = np.array([-0.8, 1.5, -0.1, 0.1, -0.6, 1.2, -0.8, 1.5, 0.5, 0.25])
LO = np.array([-1.6, 0.0, -1.0, 0.0, -1.6, 0.0, -1.6, 0.0, 0.25, 0.08])
HI = np.array([0.2, 2.5, 0.4, 1.5, 0.2, 2.5, 0.2, 2.5, 1.2, 0.6])
T_SETTLE = 0.3
T_AIR_BLEND = 0.15
FRAME_STRIDE = 9           # 9 * 2 ms = 18 ms -> 55.6 Hz frames in exported trajectories
RESTART_EVALS = 800        # CMA-ES evaluations per restart before restarting from a new random start
FAILURE_CODES = ("MODEL_INVALID", "ACTUATOR_SATURATION", "CONTACT_LOSS", "STRUCTURAL_UNMODELED", "TIPPING",
                 "SEARCH_BUDGET_EXHAUSTED")
ROBUST_K = 10              # assumption scenarios per candidate in the robustification stage
ROBUST_EVALS = 3500        # rollouts (not candidates) spent on robustification
FIX_TORQUE_VALUES = [0.2, 0.35, 0.5, 0.65, 0.8, 1.0]
MAX_DRIFT_M = 0.30          # 'straight up': COM horizontal drift between start and touchdown (default, editable via spec)
DRIFT_SOFT_M = 0.12
MU_DESIGN = 0.5            # design preference: required friction coefficient at takeoff/landing stays below this
DESIGN_MARGIN = 0.10       # search aims for target*(1+margin) so that Monte-Carlo derating still passes (default)
GRF_SOFT_FRAC = 0.80       # soft GRF penalty starts at 80 % of the limit
SAT_FLAG = 0.98            # judgment-spec H4: |tau|/forcerange >= 0.98 counts as saturated

ASSUMPTION_DIRECTION = {   # +1: larger helps feasibility, -1: smaller helps (for favorable bounds, rule R3)
    "torque_scale": +1, "payload_kg": -1, "robot_mass": -1, "ground_friction": +1,
    "landing_grf_limit_bw": +1, "torso_com_offset_x": 0, "target_height": -1,
}
G1_MASS = 33.34            # sum of body masses in the Menagerie g1.xml (measured in code at load)


def smooth(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (10 + x * (-15 + 6 * x))  # min-jerk


# --------------------------------------------------------------------------------------------- simulator
class Sim:
    """G1 model + 10-param controller + judge.  ``configure`` re-applies assumptions from pristine arrays."""

    def __init__(self):
        self.m = m = mujoco.MjModel.from_xml_path(str(g1_dir() / "scene.xml"))
        self.d = mujoco.MjData(m)
        self.d_static = mujoco.MjData(m)
        self._mass0 = m.body_mass.copy()
        self._inertia0 = m.body_inertia.copy()
        self._fr0 = m.actuator_forcerange.copy()
        self._fric0 = m.geom_friction.copy()
        self._ipos0 = m.body_ipos.copy()
        self.d_key = m.key_qpos[0].copy()
        self.q_default = self.d_key[7:].copy()
        self.floor = m.geom("floor").id
        ankle = (m.body("left_ankle_roll_link").id, m.body("right_ankle_roll_link").id)
        self.foot_geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] in ankle and m.geom_contype[g] > 0]
        self.pelvis = m.body("pelvis").id
        self.torso = m.body("torso_link").id
        self.knee_act = [m.actuator("left_knee_joint").id, m.actuator("right_knee_joint").id]
        self.cr = m.actuator_ctrlrange.copy()
        self.gain = m.actuator_gainprm[:, 0].copy()
        self.b1 = m.actuator_biasprm[:, 1].copy()
        self.b2 = m.actuator_biasprm[:, 2].copy()
        self.act_names = [m.actuator(i).name.replace("_joint", "") for i in range(12)]
        self.cfg: tuple | None = None
        self.configure()

    # ---- assumptions -> model
    def configure(self, payload=0.0, torque_scale=1.0, robot_mass=None, mu=None, com_dx=0.0):
        m = self.m
        m.body_mass[:] = self._mass0
        m.body_inertia[:] = self._inertia0
        m.actuator_forcerange[:] = self._fr0 * torque_scale
        m.geom_friction[:] = self._fric0
        m.body_ipos[:] = self._ipos0
        if robot_mass is not None:
            k = robot_mass / self._mass0.sum()
            m.body_mass[:] *= k
            m.body_inertia[:] *= k
        if payload:
            b = self.torso
            k = (m.body_mass[b] + payload) / m.body_mass[b]
            m.body_mass[b] += payload
            m.body_inertia[b] *= k  # inertia scaled proportionally with mass (spec H7)
        if com_dx:
            m.body_ipos[self.torso][0] += com_dx
        if mu is not None:
            for g in (*self.foot_geoms, self.floor):
                m.geom_friction[g, 0] = mu
        mujoco.mj_setConst(m, self.d)  # refresh subtree mass / gravity compensation after mass edits
        self.mass = float(m.body_mass.sum())
        self.fr = m.actuator_forcerange.copy()
        self.cfg = (payload, torque_scale, robot_mass, mu, com_dx)
        self.mu = float(mu if mu is not None else max(self._fric0[self.floor, 0], self._fric0[self.foot_geoms[0], 0]))

    def pose(self, h, k):
        a = -(h + k)
        c = self.q_default.copy()
        for o in (0, 6):
            c[o + 0] = h
            c[o + 3] = k
            c[o + 4] = a
        return np.clip(c, self.cr[:, 0], self.cr[:, 1])

    def _com_vz(self):
        mujoco.mj_subtreeVel(self.m, self.d)
        return self.d.subtree_linvel[1][2]

    # ---- rollout
    def rollout(self, p, record=False, t_end_after_land=1.0, t_max=4.0) -> dict:
        m, d = self.m, self.d
        mujoco.mj_resetData(m, d)
        d.qpos[:] = self.d_key
        mujoco.mj_forward(m, d)
        ch, ck, th, tk, ah, ak, lh, lk, Td, Tp = (float(x) for x in p)
        P_stand = self.pose(0.0, 0.0)
        P_cr, P_tk, P_air, P_land = self.pose(ch, ck), self.pose(th, tk), self.pose(ah, ak), self.pose(lh, lk)
        dt = m.opt.timestep
        n = int(t_max / dt)
        W = self.mass * G
        fr_hi = self.fr[:12, 1]
        fr_knee = self.fr[self.knee_act, 1]
        phase, t_phase = "settle", 0.0
        prev_target = P_stand.copy()
        t_liftoff = t_touch = None
        com_lift = vz_lift = None
        vh_lift = 0.0
        com_xy0 = d.subtree_com[1][:2].copy()
        drift_land = None
        com_apex = -1e9
        max_demand = np.zeros(12)
        max_force = np.zeros(12)
        sat_steps = np.zeros(12)
        push_steps = 0
        push_sat = np.zeros(12)
        n_act = 0
        grf_peak_land = 0.0
        mu_req = 0.0
        bad_contact = False
        land_t0 = None
        blend_from = None
        foot_clear = 0.0
        fall = False
        min_pelvis_land = 9.0
        frames = [] if record else None
        win_grf = win_kt = 0.0
        series = {"knee_torque_ratio": [], "grf_N": [], "com_height_m": []} if record else None
        ev = [] if record else None
        for i in range(n):
            t = d.time
            fz = 0.0
            fw = np.zeros(3)   # net world-frame foot contact force
            foot_c = other_c = False
            for ci in range(d.ncon):
                c = d.contact[ci]
                g1, g2 = c.geom1, c.geom2
                if self.floor in (g1, g2):
                    og = g2 if g1 == self.floor else g1
                    f6 = np.zeros(6)
                    mujoco.mj_contactForce(m, d, ci, f6)
                    if og in self.foot_geoms:
                        foot_c = True
                        fz += f6[0]
                        fw += c.frame.reshape(3, 3).T @ f6[:3]
                    else:
                        other_c = True
            bad_contact |= other_c
            if fz > 0.3 * W:   # H9: net traction demand |F_xy| / F_z while the feet carry real load
                mu_req = max(mu_req, math.hypot(fw[0], fw[1]) / fw[2] if fw[2] > 0 else 0.0)
            com = d.subtree_com[1]
            if t_liftoff is not None and foot_c:   # GRF counted from the FIRST contact after liftoff
                grf_peak_land = max(grf_peak_land, fz)
            if phase == "settle":
                tgt = P_stand
                if t >= T_SETTLE:
                    phase, t_phase = "down", t
            if phase == "down":
                tgt = P_stand + (P_cr - P_stand) * smooth((t - t_phase) / Td)
                if t - t_phase >= Td:
                    phase, t_phase = "push", t
            if phase == "push":
                tgt = P_cr + (P_tk - P_cr) * smooth((t - t_phase) / Tp)
                if (not foot_c) and t - t_phase > 0.02:
                    phase, t_phase = "air", t
                    blend_from = prev_target.copy()
                    t_liftoff, com_lift = t, com[2]
                    vz_lift = self._com_vz()
                    vh_lift = float(np.hypot(*d.subtree_linvel[1][:2]))
                    if record:
                        ev.append(("liftoff", t, d.xpos[self.pelvis].copy(), 0.0))
                elif t - t_phase > Tp + 0.6:
                    phase, t_phase = "noflight", t
            if phase == "noflight":
                tgt = P_tk
                if t - t_phase > 0.5:
                    break
            if phase == "air":
                if not foot_c:
                    com_apex = max(com_apex, com[2])
                    vz = self._com_vz()
                    if vz < 0 and land_t0 is None:
                        land_t0 = t
                        blend_from = prev_target.copy()
                    if land_t0 is None:
                        tgt = blend_from + (P_air - blend_from) * smooth((t - t_phase) / T_AIR_BLEND)
                    else:
                        tgt = blend_from + (P_land - blend_from) * smooth((t - land_t0) / T_AIR_BLEND)
                    foot_clear = max(foot_clear, min(d.geom_xpos[g][2] - m.geom_size[g][0] for g in self.foot_geoms))
                else:
                    if t - t_phase > 0.03:
                        phase, t_touch, t_phase = "land", t, t
                        drift_land = float(np.linalg.norm(d.subtree_com[1][:2] - com_xy0))
                    tgt = prev_target
            if phase == "land":
                tgt = P_land
                if t - t_touch > t_end_after_land:
                    break
            prev_target = tgt
            ctrl = self.q_default.copy()
            ctrl[:12] = tgt[:12]
            d.ctrl[:] = np.clip(ctrl, self.cr[:, 0], self.cr[:, 1])
            mujoco.mj_step(m, d)
            q = d.qpos[7:19]
            qd = d.qvel[6:18]
            dem = self.gain[:12] * d.ctrl[:12] + self.b1[:12] * q + self.b2[:12] * qd
            max_demand = np.maximum(max_demand, np.abs(dem) / fr_hi)
            ratio_applied = np.abs(d.actuator_force[:12]) / fr_hi
            max_force = np.maximum(max_force, ratio_applied)
            sat_steps += ratio_applied >= SAT_FLAG
            n_act += 1
            if phase == "push":
                push_steps += 1
                push_sat += ratio_applied >= SAT_FLAG
            if phase == "land":
                min_pelvis_land = min(min_pelvis_land, d.xpos[self.pelvis][2])
            if record:
                win_grf = max(win_grf, fz)
                win_kt = max(win_kt, float((np.abs(d.actuator_force[self.knee_act]) / fr_knee).max()))
                if t_touch is not None and phase == "land" and t == t_touch:
                    ev.append(("landing", t, d.xpos[self.pelvis].copy(), fz))
                if i % FRAME_STRIDE == 0:
                    frames.append((d.time, d.xpos.copy(), d.xquat.copy()))
                    series["knee_torque_ratio"].append(win_kt)
                    series["grf_N"].append(win_grf)
                    series["com_height_m"].append(float(d.subtree_com[1][2]))
                    win_grf = win_kt = 0.0
            if d.xpos[self.pelvis][2] < 0.3 and t > T_SETTLE + 0.2:
                fall = True
                break
        r: dict[str, Any] = dict(phase=phase, t_end=float(d.time), liftoff=t_liftoff is not None)
        if t_liftoff is not None:
            r["t_liftoff"] = float(t_liftoff)
            r["ballistic_height"] = float(max(vz_lift, 0.0) ** 2 / (2 * G))
            r["com_apex_rise"] = float(max(com_apex, com_lift) - com_lift)
            r["foot_clearance"] = float(foot_clear)
        else:
            r["ballistic_height"] = r["com_apex_rise"] = r["foot_clearance"] = 0.0
        r["landed"] = t_touch is not None
        r["drift_m"] = float(drift_land) if drift_land is not None else 0.0
        r["v_horizontal_liftoff"] = float(vh_lift)
        if t_touch is not None:
            r["t_touch"] = float(t_touch)
        up = float(d.xmat[self.torso].reshape(3, 3)[2, 2])
        r["torso_up"] = up
        r["pelvis_z_end"] = float(d.xpos[self.pelvis][2])
        r["grf_peak_land_N"] = float(grf_peak_land)
        r["grf_peak_land_bw"] = float(grf_peak_land / W)
        r["mu_req"] = float(mu_req)
        r["torque_applied_ratio_max"] = float(max_force.max())
        r["torque_demand_ratio_max"] = float(max_demand.max())
        r["per_joint_applied_ratio"] = max_force.tolist()
        r["push_sat_frac"] = (push_sat / max(push_steps, 1)).tolist()
        j = int(np.argmax(push_sat / max(push_steps, 1))) if push_steps else int(np.argmax(max_force))
        r["binding_joint"] = self.act_names[j]
        r["binding_sat_frac"] = float((push_sat[j] / max(push_steps, 1)))
        r["bad_contact"] = bool(bad_contact)
        stable = bool(r["landed"] and not fall and up > 0.8 and d.xpos[self.pelvis][2] > 0.35 and not bad_contact)
        r["stable_landing"] = stable
        r["fall"] = bool(fall or (r["landed"] and not stable))
        r["finite"] = bool(np.isfinite(d.qpos).all() and np.isfinite(d.qacc).all())
        if record:
            r["frames"] = frames
            r["series"] = series
            r["events"] = ev
            r["fall_t"] = float(d.time) if fall else None
        return r

    # ---- static (controller-independent) torque hold
    def static_hold(self, hip: float, knee: float) -> dict:
        """Torque needed to hold a symmetric crouch at qacc=0, COM balanced over the feet (ideal CoP), via mj_inverse.

        Contacts are disabled and the support wrench (weight split over both feet, CoP at COM x) is applied as
        qfrc_applied; it is subtracted afterwards.  Always run after ``configure`` (which calls mj_setConst)."""
        m, d = self.m, self.d_static
        mujoco.mj_resetData(m, d)
        d.qpos[:] = self.d_key
        d.qpos[7:19] = self.pose(hip, knee)[:12]
        mujoco.mj_forward(m, d)
        low = min(d.geom_xpos[g][2] - m.geom_size[g][0] for g in self.foot_geoms)
        d.qpos[2] -= low
        mujoco.mj_forward(m, d)
        xs = [d.geom_xpos[g][0] for g in self.foot_geoms]
        cx = float(d.subtree_com[1][0])
        W = self.mass * G
        qf = np.zeros(m.nv)
        jp = np.zeros((3, m.nv))
        for b in (m.body("left_ankle_roll_link").id, m.body("right_ankle_roll_link").id):
            pt = np.array([cx, d.xpos[b][1], 0.0])
            mujoco.mj_jac(m, d, jp, None, pt, b)
            qf += jp.T @ np.array([0, 0, W / 2])
        flags = int(m.opt.disableflags)
        m.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONTACT
        d.qvel[:] = 0
        d.qacc[:] = 0
        d.qfrc_applied[:] = qf
        mujoco.mj_inverse(m, d)
        m.opt.disableflags = flags
        tau = d.qfrc_inverse - qf
        jt = tau[6:18]
        fr = self.fr[:12, 1]
        ratio = np.abs(jt) / fr
        j = int(ratio.argmax())
        return dict(
            hip=hip, knee=knee, com_z=float(d.subtree_com[1][2]), total_mass=self.mass,
            torque_Nm=dict(zip(self.act_names, map(float, jt))), ratio=dict(zip(self.act_names, map(float, ratio))),
            max_ratio=float(ratio.max()), binding=self.act_names[j], binding_torque=float(abs(jt[j])),
            binding_limit=float(fr[j]), com_in_foot_extent=bool(min(xs) <= cx <= max(xs)),
            root_residual=float(np.abs(tau[:6]).max()))


# --------------------------------------------------------------------------------------------- assumptions
def _favorable(a: Assumption) -> float:
    """5th/95th percentile in the direction that helps feasibility (judgment-spec rule R3)."""
    sgn = ASSUMPTION_DIRECTION.get(a.key, 0)
    d = a.distribution
    if d.kind == "uniform":
        return float(d.high if sgn > 0 else d.low if sgn < 0 else a.value)
    if d.kind == "normal":
        if sgn == 0:
            return float(d.mean)
        x = d.mean + sgn * 1.645 * d.std
        if d.clip_low is not None:
            x = max(x, d.clip_low)
        if d.clip_high is not None:
            x = min(x, d.clip_high)
        return float(x)
    return float(a.value)


def _values(spec: SpecSheet) -> dict[str, float]:
    return {a.key: float(a.value) for a in spec.assumptions}


def _cfg(v: dict[str, float]) -> tuple:
    return (float(v.get("payload_kg", 0.0)), float(v.get("torque_scale", 1.0)), float(v.get("robot_mass", G1_MASS)),
            float(v.get("ground_friction", 0.8)), float(v.get("torso_com_offset_x", 0.0)))


def _succeeded(r: dict, target: float, grf_limit_bw: float) -> bool:
    return bool(r["liftoff"] and r["stable_landing"] and r["ballistic_height"] >= target
                and r["grf_peak_land_bw"] <= grf_limit_bw and r["drift_m"] <= MAX_DRIFT_M and r["finite"])


def failure_code(r: dict, target: float, grf_limit_bw: float, mu: float) -> str | None:
    """One primary taxonomy code per failed rollout (docs/judgment-spec.md section A, priority order)."""
    if not r["finite"]:
        return "MODEL_INVALID"
    if _succeeded(r, target, grf_limit_bw):
        return None
    if not r["liftoff"] or r["ballistic_height"] < target:
        return "ACTUATOR_SATURATION" if r["binding_sat_frac"] > 0.05 or r["torque_applied_ratio_max"] >= SAT_FLAG \
            else "SEARCH_BUDGET_EXHAUSTED"
    if r["mu_req"] >= 0.98 * mu:   # friction cone saturated (slipping) at takeoff/landing and the jump still failed
        return "CONTACT_LOSS"
    if r["landed"] and r["grf_peak_land_bw"] > grf_limit_bw:
        return "STRUCTURAL_UNMODELED"
    if not r["stable_landing"]:
        return "TIPPING"
    return None


def cost_fn(r: dict, target: float, grf_limit_bw: float, margin: float = DESIGN_MARGIN) -> float:
    h = r["ballistic_height"] if r["liftoff"] else 0.0
    h_req = target * (1.0 + margin)
    c = 100.0 * (h_req - h) ** 2 if h < h_req else 0.0
    if not r["liftoff"]:
        c += 10.0
    elif not r["landed"]:
        c += 5.0
    if r["landed"] and not r["stable_landing"]:
        c += 3.0 + (1.0 - max(min(r["torso_up"], 1.0), -1.0))
    g = r["grf_peak_land_bw"]
    soft = GRF_SOFT_FRAC * grf_limit_bw
    if g > soft:
        c += 20.0 * ((g - soft) / grf_limit_bw) ** 2
    if g > grf_limit_bw:
        c += 1.0 + (g - grf_limit_bw) / grf_limit_bw
    dr = r["drift_m"]
    if dr > DRIFT_SOFT_M:
        c += 30.0 * (dr - DRIFT_SOFT_M) ** 2 + (1.0 if dr > MAX_DRIFT_M else 0.0)
    if r["mu_req"] > MU_DESIGN:     # keep traction demand clear of the low end of the friction range (design preference)
        c += 10.0 * (r["mu_req"] - MU_DESIGN) ** 2
    c += 0.01 * g
    return float(c)


# --------------------------------------------------------------------------------------------- process pool
_SIM: Sim | None = None


def _nominal_ok(cfg, p, target, limit) -> bool:
    return bool(_task((cfg, np.asarray(p).tolist(), target, limit, "search"))[1]["ok"])


def _worker_sim() -> Sim:
    global _SIM
    if _SIM is None:
        _SIM = Sim()
    return _SIM


def _task(args):
    cfg, p, target, limit, kind = args
    s = _worker_sim()
    if s.cfg != cfg:
        s.configure(*cfg)
    r = s.rollout(np.clip(np.asarray(p, float), LO, HI))
    mu = s.mu
    if kind == "search":
        return (cost_fn(r, target, limit), dict(h=r["ballistic_height"], grf=r["grf_peak_land_bw"],
                                                ok=_succeeded(r, target, limit)))
    return (r, failure_code(r, target, limit, mu))


_POOL = None
_POOL_N = 0


def _nproc() -> int:
    return max(1, int(os.environ.get("KINETRA_PROCS", min(8, os.cpu_count() or 1))))


def _pool():
    global _POOL, _POOL_N
    n = _nproc()
    if n <= 1:
        return None
    if _POOL is None or _POOL_N != n:
        if _POOL is not None:
            _POOL.terminate()
        _POOL = mp.get_context("spawn").Pool(n, initializer=_worker_sim)
        _POOL_N = n
    return _POOL


def _close_pool():
    global _POOL
    if _POOL is not None:
        _POOL.terminate()
        _POOL = None


atexit.register(_close_pool)


def _pmap(tasks):
    pool = _pool()
    if pool is None:
        return [_task(t) for t in tasks]
    return pool.map(_task, tasks, chunksize=max(1, len(tasks) // (4 * _POOL_N)))


# --------------------------------------------------------------------------------------------- template
class HumanoidJump:
    id = TEMPLATE_ID
    necessary_classes = {"static_torque_saturation": "ACTUATOR_SATURATION", "takeoff_energy": "ENERGY_BUDGET",
                         "landing_deceleration": "ACTUATOR_SATURATION"}
    model_labels = ["simplified model, needs precise validation",
                    "Structural strength not analyzed (no FEA) - simplified model, needs precise validation",
                    "Perfect state feedback assumed; real sensing/latency not modeled - simplified model, needs precise validation",
                    "Landing GRF limit is an unverified default, not a hardware figure"]
    success_phrase = "a stable jump of the target height with a landing below the assumed peak-GRF limit"

    # ---- spec
    def default_spec(self, idea: str, overrides: dict[str, float] | None = None) -> SpecSheet:
        ov = dict(overrides or {})
        known = {"target_height", "payload_kg", "torque_scale", "robot_mass", "ground_friction",
                 "landing_grf_limit_bw", "torso_com_offset_x"}
        bad = set(ov) - known
        if bad:
            raise KeyError(f"unknown assumption override(s): {sorted(bad)}")
        tgt = ov.get("target_height", 0.30)
        pay = ov.get("payload_kg", 0.0)
        ts = ov.get("torque_scale", 1.0)
        rm = ov.get("robot_mass", G1_MASS)
        mu = ov.get("ground_friction", 0.8)
        lim = ov.get("landing_grf_limit_bw", 9.0)
        cx = ov.get("torso_com_offset_x", 0.0)
        dflt = "default: our choice, editable, not claimed true (docs/judgment-spec.md section 2.2)"
        A = [
            Assumption(key="target_height", label="Target jump height (ballistic, vz^2/2g at liftoff)", value=tgt, unit="m",
                       distribution=Fixed(), source="user", confidence=Confidence.high),
            Assumption(key="payload_kg", label="Payload carried on the torso", value=pay, unit="kg",
                       distribution=Normal(mean=pay, std=0.05 * pay, clip_low=0.0) if pay > 0 else Fixed(),
                       source="user", confidence=Confidence.high),
            Assumption(key="torque_scale", label="Motor torque scale (derating / hot motors); 1.0 = G1 forceranges "
                       "(knee 139, hip 88-139, ankle 50 N*m)", value=ts, unit="",
                       distribution=Uniform(low=0.85 * ts, high=ts),
                       source=f"{MENAGERIE_URL}/g1.xml (forcerange); derating range is a default",
                       confidence=Confidence.med),
            Assumption(key="robot_mass", label="Robot mass (without payload)", value=rm, unit="kg",
                       distribution=Normal(mean=rm, std=0.01 * rm),
                       source=f"{MENAGERIE_URL}/g1.xml (sum of link masses)", confidence=Confidence.med),
            Assumption(key="ground_friction", label="Foot-ground friction coefficient", value=mu, unit="",
                       distribution=Uniform(low=0.6, high=1.0), source=dflt, confidence=Confidence.low),
            Assumption(key="landing_grf_limit_bw", label="Landing peak ground-reaction-force limit (structural, "
                       "UNVERIFIED default - no hardware source)", value=lim, unit="BW",
                       distribution=Uniform(low=6.0, high=12.0) if lim == 9.0 else Uniform(low=lim * 2 / 3, high=lim * 4 / 3),
                       source="default (no source; flagged unverified)", confidence=Confidence.low),
            Assumption(key="torso_com_offset_x", label="Torso COM offset (fore-aft)", value=cx, unit="m",
                       distribution=Normal(mean=cx, std=0.01), source=dflt, confidence=Confidence.low),
        ]
        parts = [Part(name="Unitree G1 humanoid (29 DoF)", role="robot", mass_kg=rm, cost_usd=16000.0,
                      source="unverified: public list price recalled from memory, not checked")]
        if pay > 0:
            parts.append(Part(name="Payload (ballast on torso)", role="payload", mass_kg=pay, cost_usd=None, source="user"))
        bounds = [ParamBound(name=n, low=float(lo), high=float(hi), unit=u, init=float(i), description=dsc)
                  for n, lo, hi, u, i, dsc in zip(PNAMES, LO, HI, PUNITS, P0, PDESC)]
        crit = [
            SuccessCriterion(name="jump_height", metric="ballistic_height_m", comparator=Comparator.ge, threshold=tgt,
                             unit="m", description="Ballistic height vz^2/(2g) of the whole-body COM at liftoff"),
            SuccessCriterion(name="stable_landing", metric="stable_landing", comparator=Comparator.ge, threshold=1.0,
                             description="Lands on both feet, torso upright (z-axis >= 0.8), pelvis >= 0.35 m, no non-foot ground contact"),
            SuccessCriterion(name="horizontal_drift", metric="drift_m", comparator=Comparator.le, threshold=MAX_DRIFT_M, unit="m",
                             description="Horizontal COM travel between start and touchdown ('straight up'); default"),
            SuccessCriterion(name="landing_grf", metric="landing_grf_bw", comparator=Comparator.le, threshold=lim, unit="BW",
                             description="Peak vertical ground-reaction force from first touchdown contact, in body weights"),
        ]
        return SpecSheet(idea=idea, template_id=TemplateId.humanoid_jump, tier=Tier.verified_template,
                         assumptions=A, parts=parts, param_bounds=bounds, success_criteria=crit)

    # ---- necessary conditions
    def _favorable_values(self, spec: SpecSheet) -> dict[str, float]:
        v = _values(spec)
        for a in spec.assumptions:
            v[a.key] = _favorable(a)
        return v

    def _crouch_family(self, s: Sim, n=14):
        """Sagittal crouch family hip = -0.55*knee, standing -> knee 2.5 (the crouch range of the search bounds)."""
        out = []
        for k in np.linspace(0.0, 2.5, n):
            out.append(s.static_hold(-0.55 * k, k))
        return out

    def necessary_screen(self, spec: SpecSheet) -> list[NecessaryCheck]:
        """Tested at the FAVORABLE bound of every assumption (rule R3); passing proves nothing."""
        v = self._favorable_values(spec)
        nominal = _values(spec)
        target = v["target_height"]
        checks = []
        for label, vals in (("favorable", v), ("nominal", nominal)):
            s = Sim()
            s.configure(*_cfg(vals))
            fam = self._crouch_family(s)
            W = s.mass * G
            # --- H1: static torque saturation over the planned crouch range (shallowest planned crouch: knee 0.6)
            rng_poses = [f for f in fam if f["knee"] >= 0.6 - 1e-9]
            shallow = rng_poses[0]
            ref = s.static_hold(-0.8, 1.5)
            deep = s.static_hold(-1.2, 2.0)
            # --- H2/H3: energy: net takeoff work needed vs maximum-effort bound along the push stroke
            F = np.array([W / max(f["max_ratio"], 1e-9) for f in fam])   # max vertical foot force at this pose
            z = np.array([f["com_z"] for f in fam])
            work = 0.0
            stroke = 0.0
            hold_ok = 0
            for i, f in enumerate(fam):
                if f["max_ratio"] >= 1.0:
                    break
                hold_ok = i
            for i in range(hold_ok):
                dz = z[i] - z[i + 1]
                work += max(0.5 * (F[i] + F[i + 1]) - W, 0.0) * dz
                stroke += dz
            SLACK = 1.25   # default allowance for unmodeled arm/waist swing and limb dynamics
            avail = SLACK * work
            req = W * target
            # --- H5 landing pre-check: average deceleration force over the available leg stroke
            s_stop = max(stroke, 1e-3)
            v_td2 = 2 * G * target
            f_avg_bw = v_td2 / (2 * G * s_stop) + 1.0
            grf_lim = v["landing_grf_limit_bw"]
            f_cap_bw = float(np.mean(F[: hold_ok + 1]) / W) if hold_ok else 0.0
            res = dict(
                static=NecessaryCheck(
                    name="static_torque_saturation", passed=bool(shallow["max_ratio"] <= 1.0),
                    measured=round(shallow["binding_torque"], 2), limit=round(shallow["binding_limit"], 2), unit="N*m",
                    note=(f"H1 [{label} bounds]: holding the shallowest planned crouch (knee {shallow['knee']:.1f} rad) needs "
                          f"{shallow['binding']} {shallow['binding_torque']:.1f} of {shallow['binding_limit']:.1f} N*m "
                          f"({shallow['max_ratio']:.2f}x). Reference crouch (hip -0.8, knee 1.5): {ref['max_ratio']:.2f}x; "
                          f"deep crouch (hip -1.2, knee 2.0): {deep['max_ratio']:.2f}x of forcerange "
                          f"[{deep['binding']} {deep['binding_torque']:.1f}/{deep['binding_limit']:.1f} N*m]. "
                          "Passing proves nothing; simplified model, needs precise validation.")),
                energy=NecessaryCheck(
                    name="takeoff_energy", passed=bool(req <= avail), measured=round(req, 2), limit=round(avail, 2), unit="J",
                    note=(f"H2/H3 [{label} bounds]: needs net takeoff work m*g*h = {req:.1f} J; max-effort upper bound "
                          f"{SLACK:.2f} x integral of (F_max(pose) - m*g) over a {stroke:.2f} m crouch stroke = {avail:.1f} J "
                          f"(F_max = weight / static torque ratio, torque scale {vals['torque_scale']:.2f}). "
                          "Neglects limb dynamics and upper-body swing beyond the allowance - simplified model, needs precise validation.")),
                landing=NecessaryCheck(
                    name="landing_deceleration", passed=bool(f_avg_bw <= min(grf_lim, f_cap_bw) if f_cap_bw > 0 else False),
                    measured=round(f_avg_bw, 3), limit=round(min(grf_lim, f_cap_bw), 3), unit="BW",
                    note=(f"H5 pre-check [{label} bounds]: stopping from v_td = {math.sqrt(v_td2):.2f} m/s within the "
                          f"{s_stop:.2f} m leg stroke needs mean {f_avg_bw:.2f} BW; limit = min(assumed structural limit "
                          f"{grf_lim:.1f} BW, mean leg force capability {f_cap_bw:.2f} BW).")),
                stroke=stroke, avail=avail, req=req)
            if label == "favorable":
                fav = res
            else:
                nom = res
        for key in ("static", "energy", "landing"):
            c = fav[key]
            n = nom[key]
            if c.passed and not n.passed:
                c.note += f" (Violated at NOMINAL bounds ({n.measured} vs {n.limit} {n.unit}) but not at favorable bounds: would be UNLIKELY, not impossible.)"
            checks.append(c)
        return checks

    # ---- search
    def search(self, spec: SpecSheet, seed: int, budget: Budget) -> SearchResult:
        """CMA-ES (popsize 20) with restarts; cost includes the landing-GRF penalty (soft from 80 % of the limit, hard
        above it).  The returned witness is the cheapest candidate that meets ALL success criteria on the nominal
        model (not merely the lowest-cost one).  Per-restart budget without a success: RESTART_EVALS."""
        import cma
        v = _values(spec)
        cfg = _cfg(v)
        target, limit = v["target_height"], v["landing_grf_limit_bw"]
        names = [b.name for b in spec.param_bounds]
        assert names == PNAMES, "humanoid_jump param_bounds must keep the template parameterization"
        lo = np.array([b.low for b in spec.param_bounds])
        hi = np.array([b.high for b in spec.param_bounds])
        x_init = np.array([((b.init if b.init is not None else (b.low + b.high) / 2) - b.low) / (b.high - b.low)
                           for b in spec.param_bounds])
        t0 = time.perf_counter()
        n = 0
        best = (1e18, None)
        best_ok = (1e18, None)   # lowest-cost candidate that actually meets every success criterion
        first_success = None
        restarts = 0
        timed_out = False
        while n < budget.max_evals and not timed_out:
            rs = np.random.default_rng(int(seed) % (2 ** 32) + 7919 * restarts)
            x0 = x_init if restarts == 0 else rs.uniform(0.2, 0.8, len(x_init))
            es = cma.CMAEvolutionStrategy(x0, 0.3 if restarts == 0 else 0.35,
                                          dict(seed=(int(seed) + 104729 * restarts) % (2 ** 31 - 1), popsize=20,
                                               bounds=[0, 1], verbose=-9))
            n_run = 0
            stale = 0
            run_best = 1e18
            while n < budget.max_evals and not es.stop():
                xs = es.ask()
                ps = [lo + np.asarray(x) * (hi - lo) for x in xs]
                res = _pmap([(cfg, p.tolist(), target, limit, "search") for p in ps])
                cs = [r[0] for r in res]
                es.tell(xs, cs)
                n += len(xs)
                n_run += len(xs)
                i = int(np.argmin(cs))
                improved = cs[i] < run_best - 1e-6
                run_best = min(run_best, cs[i])
                if cs[i] < best[0]:
                    best = (cs[i], ps[i])
                for j, r in enumerate(res):
                    if r[1]["ok"] and r[0] < best_ok[0]:
                        best_ok = (r[0], ps[j])
                if first_success is None and best_ok[1] is not None:
                    first_success = n
                stale = 0 if improved else stale + 1
                if best_ok[1] is not None and stale >= 12:
                    break
                if best_ok[1] is None and n_run >= RESTART_EVALS:
                    break
                if time.perf_counter() - t0 > budget.max_seconds:
                    timed_out = True
                    break
            if best_ok[1] is not None:
                break
            restarts += 1
        if best_ok[1] is not None:
            best = best_ok
        wall = time.perf_counter() - t0
        p = np.clip(best[1], lo, hi)
        s = Sim()
        s.configure(*cfg)
        r = s.rollout(p)
        found = _succeeded(r, target, limit)
        fails = [] if found else [n_ for n_, bad in (
            ("jump_height", r["ballistic_height"] < target), ("stable_landing", not r["stable_landing"]),
            ("horizontal_drift", r["drift_m"] > MAX_DRIFT_M),
            ("landing_grf", r["grf_peak_land_bw"] > limit)) if bad]
        bm = {k: r[k] for k in ("ballistic_height", "com_apex_rise", "grf_peak_land_bw", "grf_peak_land_N", "stable_landing",
                                "torso_up", "mu_req", "torque_applied_ratio_max", "binding_joint", "binding_sat_frac",
                                "foot_clearance", "drift_m", "v_horizontal_liftoff")}
        detail = dict(metrics=bm, best_metrics=bm, failed_checks=fails, restarts=restarts, stopped_by="time" if timed_out else
                      ("budget" if n >= budget.max_evals else "converged"),
                      evals_to_first_success=first_success, popsize=20, cma_restarts=restarts, design_margin=DESIGN_MARGIN,
                      failure_class=None if found else failure_code(r, target, limit, s.mu) or "SEARCH_BUDGET_EXHAUSTED",
                      truncated_by_time=bool(timed_out))
        if not found:
            detail["binding"] = dict(
                name=f"jump_height (binding joint: {r['binding_joint']}, saturated {100 * r['binding_sat_frac']:.0f}% of push-off)",
                margin=float(r["ballistic_height"] - target), unit="m")
        return SearchResult(found=found, best_params=dict(zip(PNAMES, map(float, p))), n_evals=n, wall_seconds=wall,
                            best_cost=float(best[0]), detail=detail)

    def judge_nominal(self, spec: SpecSheet, params: dict[str, float]) -> bool:
        """Does ``params`` satisfy every success criterion on the nominal model?"""
        v = _values(spec)
        return _nominal_ok(_cfg(v), [params[k] for k in PNAMES], v["target_height"], v["landing_grf_limit_bw"])

    def model_info(self, spec: SpecSheet) -> dict[str, Any]:
        s = Sim()
        m = s.m
        return dict(model_id="unitree_g1_29dof", model_hash=model_hash()[:16], mujoco_version=mujoco.__version__,
                    n_bodies=int(m.nbody - 1), n_actuators=int(m.nu), n_params=len(PNAMES), timestep_s=float(m.opt.timestep),
                    total_mass_kg=round(s.mass, 2), source=MENAGERIE_URL)

    def fix_control(self, spec: SpecSheet) -> dict[str, Any]:
        """The user-facing control the fix search sweeps (also the web slider): payload to remove is NOT swept upward;
        the fix for a too-heavy payload is a LARGER torque scale (actuator upgrade), so that is the swept control."""
        return dict(key="torque_scale", label="Motor torque scale", unit="x G1 forcerange", values=FIX_TORQUE_VALUES,
                    hint="Multiplier on the Menagerie G1 forceranges (knee 139, hip 88-139, ankle 50 N*m).")

    def robustify(self, spec: SpecSheet, params: dict[str, float], seed: int, budget: Budget, ):
        """Second CMA-ES stage on ROBUST_K perturbed models; returns (params, info) for pipeline.run."""
        lo = np.array([b.low for b in spec.param_bounds])
        hi = np.array([b.high for b in spec.param_bounds])
        t0 = time.perf_counter()
        p, n, info = self._robustify(spec, np.array([params[k] for k in PNAMES]), seed, lo, hi, budget, t0)
        p = np.clip(p, lo, hi)
        return dict(zip(PNAMES, map(float, p))), dict(info, evals=int(n), train_samples=ROBUST_K)

    def _robustify(self, spec: SpecSheet, p0, seed: int, lo, hi, budget: Budget, t0: float):
        """Re-optimize the nominal witness against ROBUST_K fixed scenarios drawn from the assumption distributions
        (seed-derived, different from the Monte-Carlo draws).  fitness = mean scenario cost + 2 * failing fraction.
        The nominal witness must keep meeting every criterion on the nominal model, else the original is returned."""
        import cma
        from .. import mc as mclib
        v = _values(spec)
        cfg0, target, limit = _cfg(v), v["target_height"], v["landing_grf_limit_bw"]
        samples = mclib.sample_assumptions(spec, ROBUST_K, mclib.derive_seed(seed, "robustify"))
        scen = []
        for i in range(ROBUST_K):
            vals = {k: float(x[i]) for k, x in samples.items()}
            scen.append((_cfg(vals), vals["target_height"], vals["landing_grf_limit_bw"]))

        def fitness(ps):
            tasks = [(c, p.tolist(), tg, lm, "search") for p in ps for (c, tg, lm) in scen]
            out = _pmap(tasks)
            fits, oks = [], []
            for i in range(len(ps)):
                blk = out[i * ROBUST_K:(i + 1) * ROBUST_K]
                fr = np.mean([0.0 if r[1]["ok"] else 1.0 for r in blk])
                fits.append(float(np.mean([r[0] for r in blk]) + 2.0 * fr))
                oks.append(1.0 - float(fr))
            return fits, oks

        x0 = (np.asarray(p0) - lo) / (hi - lo)
        es = cma.CMAEvolutionStrategy(x0, 0.08, dict(seed=(int(seed) + 15485863) % (2 ** 31 - 1), popsize=16,
                                                     bounds=[0, 1], verbose=-9))
        base_fit, base_ok = fitness([np.asarray(p0)])
        best = (base_fit[0], np.asarray(p0, float), base_ok[0])
        n = ROBUST_K
        while n < ROBUST_EVALS and not es.stop() and time.perf_counter() - t0 < budget.max_seconds:
            xs = es.ask()
            ps = [lo + np.asarray(x) * (hi - lo) for x in xs]
            fits, oks = fitness(ps)
            es.tell(xs, fits)
            n += len(xs) * ROBUST_K
            # accept only candidates that still succeed on the nominal model
            order = np.argsort(fits)
            for j in order[:3]:
                if fits[j] < best[0] and _nominal_ok(cfg0, ps[j], target, limit):
                    best = (fits[j], ps[j], oks[j])
                    break
        return best[1], n, dict(train_scenarios=ROBUST_K, train_success_frac_before=round(base_ok[0], 3),
                                train_success_frac_after=round(best[2], 3))

    # ---- Monte-Carlo
    def monte_carlo(self, spec: SpecSheet, params: dict[str, float], seed: int, n: int) -> McResult:
        """Re-judge the FOUND controller on n joint draws of mass / torque scale / friction / payload / GRF limit /
        COM offset (shared sampler kinetra_engine.mc, deterministic per (spec, seed, n))."""
        from .. import mc as mclib
        p = [params[k] for k in PNAMES]
        nominal = _values(spec)
        store: dict[str, Any] = {}

        def evaluate(samples):
            m_ = len(next(iter(samples.values())))
            tasks = []
            for i in range(m_):
                vals = {k: float(samples[k][i]) for k in samples if not k.startswith("_")}
                tasks.append((_cfg(vals), p, vals["target_height"], vals["landing_grf_limit_bw"], "mc"))
            out = _pmap(tasks)
            ok = np.zeros(m_, bool)
            failed = {c: np.zeros(m_, bool) for c in FAILURE_CODES}
            mh = np.zeros(m_)
            mg = np.zeros(m_)
            for i, (r, code) in enumerate(out):
                if code is None:
                    ok[i] = True
                else:
                    failed[code][i] = True
                tgt, lim = tasks[i][2], tasks[i][3]
                mh[i] = (r["ballistic_height"] - tgt) / tgt
                mg[i] = (lim - r["grf_peak_land_bw"]) / lim if r["landed"] else -1.0
            if "first" not in store:
                store.update(first=True, mh=mh, mg=mg)
            return ok, failed

        res = mclib.run_mc(evaluate, spec, n, seed, taxonomy={}, oat=True, n_oat=48)
        mh, mg = float(store["mh"].mean()), float(store["mg"].mean())
        if mh <= mg:
            binding = dict(name="jump_height", margin=float(mh * nominal["target_height"]), unit="m")
        else:
            binding = dict(name="landing_grf", margin=float(mg * nominal["landing_grf_limit_bw"]), unit="BW")
        binding["failed_checks"] = res.binding.get("failed_checks", {}) if res.binding else {}
        res.binding = binding
        return res

    # ---- rollout / trajectory export
    def rollout(self, spec: SpecSheet, params: dict[str, float], seed: int) -> Trajectory:
        v = _values(spec)
        s = Sim()
        s.configure(*_cfg(v))
        p = np.array([params[k] for k in PNAMES])
        r = s.rollout(p, record=True)
        return export_trajectory(s, r, params, seed, v)

    def bom(self, spec: SpecSheet, params: dict[str, float]) -> list[BomItem]:
        items = []
        for p in spec.parts:
            items.append(BomItem(name=p.name, role=p.role, quantity=1, mass_kg=p.mass_kg, unit_cost_usd=p.cost_usd,
                                 source=p.source))
        return items


# --------------------------------------------------------------------------------------------- trajectory export
_BODY_CACHE: dict[str, Any] = {}


def trajectory_bodies(m: mujoco.MjModel) -> list[TrajBody]:
    """All non-world bodies with their VISUAL geoms (groups 0-2; collision-class group-3 duplicates skipped)."""
    out = []
    for b in range(1, m.nbody):
        geoms = []
        for g in range(m.ngeom):
            if m.geom_bodyid[g] != b or m.geom_group[g] > 2 or m.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE:
                continue
            rgba = m.mat_rgba[m.geom_matid[g]] if m.geom_matid[g] >= 0 else m.geom_rgba[g]
            typ = int(m.geom_type[g])
            kw = dict(pos=[round(float(x), 5) for x in m.geom_pos[g]], quat=[round(float(x), 6) for x in m.geom_quat[g]],
                      rgba=[round(float(x), 3) for x in rgba])
            if typ == mujoco.mjtGeom.mjGEOM_MESH:
                mid = m.geom_dataid[g]
                vs = m.mesh_vert[m.mesh_vertadr[mid]: m.mesh_vertadr[mid] + m.mesh_vertnum[mid]]
                half = ((vs.max(0) - vs.min(0)) / 2).tolist()
                geoms.append(Geom(type=GeomType.mesh, size=[round(x, 5) for x in half],
                                  mesh=f"{GLB_PREFIX}/{m.mesh(mid).name}.glb", **kw))
            else:
                gt = {mujoco.mjtGeom.mjGEOM_BOX: GeomType.box, mujoco.mjtGeom.mjGEOM_SPHERE: GeomType.sphere,
                      mujoco.mjtGeom.mjGEOM_CAPSULE: GeomType.capsule, mujoco.mjtGeom.mjGEOM_CYLINDER: GeomType.cylinder,
                      mujoco.mjtGeom.mjGEOM_ELLIPSOID: GeomType.ellipsoid}[typ]
                nsz = {GeomType.box: 3, GeomType.sphere: 1, GeomType.capsule: 2, GeomType.cylinder: 2, GeomType.ellipsoid: 3}[gt]
                geoms.append(Geom(type=gt, size=[round(float(x), 5) for x in m.geom_size[g][:nsz]], **kw))
        par = int(m.body_parentid[b])
        out.append(TrajBody(name=m.body(b).name, parent=None if par == 0 else m.body(par).name, geoms=geoms))
    return out


def export_trajectory(s: Sim, r: dict, params: dict[str, float], seed: int, values: dict[str, float]) -> Trajectory:
    m = s.m
    bodies = trajectory_bodies(m)
    frames = r["frames"]
    pos = [[[round(float(c), 4) for c in x[b]] for b in range(1, m.nbody)] for _, x, _q in frames]
    quat = [[[round(float(c), 5) for c in q[b]] for b in range(1, m.nbody)] for _, _x, q in frames]
    ts = [f[0] for f in frames]
    dt = FRAME_STRIDE * m.opt.timestep
    kn_lim = float(s.fr[s.knee_act[0], 1])
    series = [
        TimeSeries(name="knee_torque_ratio", unit="", values=[round(x, 4) for x in r["series"]["knee_torque_ratio"]]),
        TimeSeries(name="knee_torque_Nm", unit="N*m", values=[round(x * kn_lim, 2) for x in r["series"]["knee_torque_ratio"]]),
        TimeSeries(name="grf_N", unit="N", values=[round(x, 1) for x in r["series"]["grf_N"]]),
        TimeSeries(name="com_height_m", unit="m", values=[round(x, 4) for x in r["series"]["com_height_m"]]),
    ]
    events = []
    for kind, t, pel, f in r["events"]:
        if kind == "landing":
            events.append(ContactEvent(t=round(t, 4), kind="landing", body="left_ankle_roll_link", other=None,
                                       pos=[round(float(x), 4) for x in pel], force=[0.0, 0.0, round(float(f), 1)],
                                       magnitude=round(float(r["grf_peak_land_N"]), 1),
                                       note=f"touchdown; peak GRF {r['grf_peak_land_bw']:.2f} BW ({r['grf_peak_land_N']:.0f} N)"))
        else:
            events.append(ContactEvent(t=round(t, 4), kind="custom", body="pelvis", pos=[round(float(x), 4) for x in pel],
                                       note=f"liftoff; ballistic height {r['ballistic_height']:.3f} m"))
    if r.get("fall_t") is not None:
        events.append(ContactEvent(t=round(r["fall_t"], 4), kind="failure", body="pelvis", note="pelvis below 0.3 m: fell"))
    return Trajectory(
        model_id="unitree_g1_29dof", model_hash=model_hash(), dt=dt, bodies=bodies, pos=pos, quat=quat, events=events,
        series=series,
        meta=TrajectoryMeta(seed=int(seed), mujoco_version=mujoco.__version__, template_id=TemplateId.humanoid_jump,
                            params={k: round(float(x), 5) for k, x in params.items()},
                            note=(f"payload {values.get('payload_kg', 0):.1f} kg, torque scale {values.get('torque_scale', 1):.2f}; "
                                  f"ballistic {r['ballistic_height']:.3f} m, landing GRF {r['grf_peak_land_bw']:.2f} BW, "
                                  f"stable={r['stable_landing']}; {FRAME_STRIDE * 2} ms frames")))


TEMPLATE = HumanoidJump()
