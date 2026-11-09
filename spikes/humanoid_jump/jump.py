"""Humanoid (Unitree G1, MuJoCo Menagerie) jump spike: 10-param sagittal keyframe controller + rollout judge."""
import os, numpy as np, mujoco

HERE = os.path.dirname(os.path.abspath(__file__))
XML = os.path.join(HERE, "vendor/mujoco_menagerie/unitree_g1/scene.xml")
G = 9.81

# ---- 10-parameter vector --------------------------------------------------------------
# p = [crouch_hip, crouch_knee, take_hip, take_knee, air_hip, air_knee, land_hip, land_knee, T_down, T_push]
# hip = hip_pitch angle (neg = thigh forward), knee = knee flexion (pos). Ankle pitch is derived so the sole
# stays parallel to the floor: ankle = -(hip + knee). Both legs identical (sagittal symmetric).
PNAMES = ["crouch_hip", "crouch_knee", "take_hip", "take_knee", "air_hip", "air_knee",
          "land_hip", "land_knee", "T_down", "T_push"]
P0 = np.array([-0.8, 1.5, -0.1, 0.1, -0.6, 1.2, -0.8, 1.5, 0.5, 0.25])
LO = np.array([-1.6, 0.0, -1.0, 0.0, -1.6, 0.0, -1.6, 0.0, 0.25, 0.08])
HI = np.array([0.2, 2.5, 0.4, 1.5, 0.2, 2.5, 0.2, 2.5, 1.2, 0.6])
T_SETTLE = 0.3   # hold default pose first
T_AIR_BLEND = 0.15


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (10 + x * (-15 + 6 * x))  # min-jerk


class Sim:
    def __init__(self, payload=0.0, torque_scale=1.0):
        self.m = mujoco.MjModel.from_xml_path(XML)
        m = self.m
        if payload:
            m.body_mass[m.body("torso_link").id] += payload
        m.actuator_forcerange[:] *= torque_scale
        self.d = mujoco.MjData(m)
        if payload: mujoco.mj_setConst(m, self.d)  # refresh body_subtreemass
        self.d_key = m.key_qpos[0].copy()
        self.q_default = self.d_key[7:].copy()  # actuator i <-> qpos 7+i (all hinge, in order)
        self.ai = {n: m.actuator(n).id for n in [
            "left_hip_pitch_joint", "left_knee_joint", "left_ankle_pitch_joint",
            "right_hip_pitch_joint", "right_knee_joint", "right_ankle_pitch_joint"]}
        self.leg_act = np.arange(12)  # leg actuators 0..11
        self.floor = m.geom("floor").id
        self.foot_geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] in
                           (m.body("left_ankle_roll_link").id, m.body("right_ankle_roll_link").id)
                           and m.geom_contype[g] > 0]
        self.pelvis = m.body("pelvis").id
        self.torso = m.body("torso_link").id
        self.mass = m.body_mass.sum()
        self.fr = m.actuator_forcerange.copy()
        self.cr = m.actuator_ctrlrange.copy()
        self.gain = m.actuator_gainprm[:, 0].copy()
        self.b1 = m.actuator_biasprm[:, 1].copy()
        self.b2 = m.actuator_biasprm[:, 2].copy()
        self.nsub = 1

    def pose(self, h, k):
        a = -(h + k)
        c = self.q_default.copy()
        for s, o in (("left", 0), ("right", 6)):
            c[o + 0] = h; c[o + 3] = k; c[o + 4] = a
        return np.clip(c, self.cr[:, 0], self.cr[:, 1])

    def rollout(self, p, record=False, t_end_after_land=1.0, t_max=4.0):
        """Return dict of metrics. Event-driven: crouch -> push -> (liftoff) air pose -> (apex) landing pose."""
        m, d = self.m, self.d
        mujoco.mj_resetData(m, d)
        d.qpos[:] = self.d_key
        mujoco.mj_forward(m, d)
        ch, ck, th, tk, ah, ak, lh, lk, Td, Tp = p
        P_stand = self.pose(*self._stand_hk())
        P_cr, P_tk, P_air, P_land = self.pose(ch, ck), self.pose(th, tk), self.pose(ah, ak), self.pose(lh, lk)
        dt = m.opt.timestep
        n = int(t_max / dt)
        frames = [] if record else None
        phase = "settle"; t_phase = 0.0
        prev_target = P_stand.copy()
        t_liftoff = t_touch = None
        com_lift = vz_lift = None
        com_apex = -1e9
        max_demand = np.zeros(12); max_force = np.zeros(12); sat_steps = np.zeros(12)
        n_act_steps = 0
        grf_peak = 0.0; grf_peak_after_land = 0.0
        min_pelvis = 9; bad_contact = False
        air_start = None; land_t0 = None
        blend_from = None
        flight_foot_clear = 0.0
        com0 = d.subtree_com[1][2]
        ok_settle_end = None
        fall = False
        for i in range(n):
            t = d.time
            # --- foot contact
            fz = 0.0; foot_c = False; other_c = False
            for ci in range(d.ncon):
                c = d.contact[ci]
                g1, g2 = c.geom1, c.geom2
                if self.floor in (g1, g2):
                    og = g2 if g1 == self.floor else g1
                    f6 = np.zeros(6); mujoco.mj_contactForce(m, d, ci, f6)
                    if og in self.foot_geoms:
                        foot_c = True; fz += f6[0]
                    else:
                        other_c = True
            if other_c:
                bad_contact = True
            com = d.subtree_com[1]; vcom = d.subtree_linvel[1] if False else None
            # --- phase machine
            if phase == "settle":
                tgt = P_stand
                if t >= T_SETTLE: phase = "down"; t_phase = t
            if phase == "down":
                tgt = P_stand + (P_cr - P_stand) * smooth((t - t_phase) / Td)
                if t - t_phase >= Td: phase = "push"; t_phase = t
            if phase == "push":
                tgt = P_cr + (P_tk - P_cr) * smooth((t - t_phase) / Tp)
                if (not foot_c) and t - t_phase > 0.02:
                    phase = "air"; t_phase = t; blend_from = prev_target.copy()
                    t_liftoff = t; com_lift = com[2]
                    vz_lift = self._com_vz()
                elif t - t_phase > Tp + 0.6:
                    phase = "noflight"
                    t_phase = t
            if phase == "noflight":
                tgt = P_tk
                if t - t_phase > 0.5: break
            if phase == "air":
                if not foot_c:
                    com_apex = max(com_apex, com[2])
                    vz = self._com_vz()
                    if vz < 0 and land_t0 is None:
                        land_t0 = t; blend_from = prev_target.copy()
                    if land_t0 is None:
                        tgt = blend_from + (P_air - blend_from) * smooth((t - t_phase) / T_AIR_BLEND)
                    else:
                        tgt = blend_from + (P_land - blend_from) * smooth((t - land_t0) / T_AIR_BLEND)
                    # foot clearance
                    fh = min(d.geom_xpos[g][2] - m.geom_size[g][0] for g in self.foot_geoms)
                    flight_foot_clear = max(flight_foot_clear, fh)
                else:
                    if t - t_phase > 0.03:
                        phase = "land"; t_touch = t; t_phase = t
                    tgt = prev_target
            if phase == "land":
                tgt = P_land
                grf_peak_after_land = max(grf_peak_after_land, fz)
                if t - t_touch > t_end_after_land: break
            prev_target = tgt
            ctrl = self.q_default.copy(); ctrl[:12] = tgt[:12]
            d.ctrl[:] = np.clip(ctrl, self.cr[:, 0], self.cr[:, 1])
            mujoco.mj_step(m, d)
            # torque metrics (legs): demanded (pre-clip) vs applied
            q = d.qpos[7:19]; qd = d.qvel[6:18]
            dem = self.gain[:12] * d.ctrl[:12] + self.b1[:12] * q + self.b2[:12] * qd
            fr_hi = self.fr[:12, 1]
            max_demand = np.maximum(max_demand, np.abs(dem) / fr_hi)
            fa = np.abs(d.actuator_force[:12])
            max_force = np.maximum(max_force, fa / fr_hi)
            sat_steps += (np.abs(dem) >= fr_hi)
            n_act_steps += 1
            min_pelvis = min(min_pelvis, d.xpos[self.pelvis][2]) if phase in ("land",) else min_pelvis
            if record and i % 5 == 0:  # 100 Hz
                frames.append((d.time, d.xpos.copy(), d.xquat.copy()))
            if d.xpos[self.pelvis][2] < 0.3 and t > T_SETTLE + 0.2:
                fall = True; break
        res = dict(phase=phase, t_end=float(d.time))
        res["liftoff"] = t_liftoff is not None
        if t_liftoff is not None:
            res["t_liftoff"] = t_liftoff; res["ballistic_height"] = float(max(vz_lift,0)**2 / (2*G))
            res["com_apex_rise"] = float(max(com_apex, com_lift) - com_lift)  # apex COM - COM at liftoff
            res["foot_clearance"] = float(flight_foot_clear)
        else:
            res["com_apex_rise"] = 0.0; res["foot_clearance"] = 0.0
        res["landed"] = t_touch is not None
        up = d.xmat[self.torso].reshape(3, 3)[2, 2]
        res["torso_up"] = float(up)
        res["pelvis_z_end"] = float(d.xpos[self.pelvis][2])
        res["min_pelvis_z_land"] = float(min_pelvis) if min_pelvis < 9 else None
        res["grf_peak_land_N"] = float(grf_peak_after_land)
        res["grf_peak_land_bw"] = float(grf_peak_after_land / (self.mass * G))
        res["torque_demand_ratio_max"] = float(max_demand.max())
        res["torque_applied_ratio_max"] = float(max_force.max())
        res["per_joint_demand_ratio"] = max_demand.tolist()
        res["sat_frac"] = (sat_steps / max(n_act_steps, 1)).tolist()
        res["bad_contact"] = bool(bad_contact)
        stable = (res["landed"] and not fall and up > 0.8 and d.xpos[self.pelvis][2] > 0.35 and not bad_contact)
        res["stable_landing"] = bool(stable)
        res["fall"] = bool(fall or (res["landed"] and not stable))
        if record:
            res["frames"] = frames
        return res

    def _stand_hk(self):
        return (0.0, 0.0)

    def _com_vz(self):
        # COM velocity via mj_objectVelocity on pelvis subtree: use momentum / mass
        m, d = self.m, self.d
        # subtree_linvel needs mj_subtreeVel; compute cheaply: sum m_i v_i
        mujoco.mj_subtreeVel(m, d)
        return d.subtree_linvel[1][2]


def objective(p, sim, target_h, w_fall=1.0):
    r = sim.rollout(np.clip(p, LO, HI))
    h = r["com_apex_rise"]
    cost = (h - target_h) ** 2 * 100.0 if h < target_h else 0.0
    if not r["liftoff"]:
        cost += 10.0
    if r["liftoff"] and not r["landed"]:
        cost += 5.0
    if r["landed"] and not r["stable_landing"]:
        cost += 3.0 + (1.0 - max(min(r["torso_up"], 1), -1))
    cost += 0.02 * r["grf_peak_land_bw"]
    return cost, r
