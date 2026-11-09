"""Controller-independent static torque screen.
Holds a crouch pose at qacc=0 with the COM balanced over the foot contact patch (ideal balance), so any
shortfall is purely actuator-limited. tau = qfrc_bias(gravity, qvel=0) - sum_k J_k^T f_k, where the vertical
support force (= total weight) is spread equally over the 8 foot contact spheres (CoP = their mean = COM x).
mj_inverse is used as an independent cross-check (contacts removed, support wrench supplied as applied force)."""
import json, numpy as np, mujoco
from jump import *


def static_screen(hip, knee, payload=0.0):
    s = Sim(payload=payload); m = s.m; d = s.d
    mujoco.mj_resetData(m, d); d.qpos[:] = s.d_key
    d.qpos[7:19] = s.pose(hip, knee)[:12]
    mujoco.mj_forward(m, d)
    low = min(d.geom_xpos[g][2] - m.geom_size[g][0] for g in s.foot_geoms)
    d.qpos[2] -= low
    mujoco.mj_forward(m, d)
    xs = [d.geom_xpos[g][0] for g in s.foot_geoms]
    cx = d.subtree_com[1][0]
    in_polygon = bool(min(xs) <= cx <= max(xs))
    # support force: half the weight under each foot, centre of pressure placed at COM x (ideal balance)
    W = s.mass * G
    qf_sup = np.zeros(m.nv); jp = np.zeros((3, m.nv))
    for b in (m.body("left_ankle_roll_link").id, m.body("right_ankle_roll_link").id):
        p = np.array([cx, d.xpos[b][1], 0.0])
        mujoco.mj_jac(m, d, jp, None, p, b)
        qf_sup += jp.T @ np.array([0, 0, W / 2])
    # mj_inverse with contacts disabled and support as applied force: qfrc_inverse = actuation needed
    m.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONTACT
    d.qvel[:] = 0; d.qacc[:] = 0; d.qfrc_applied[:] = qf_sup
    mujoco.mj_inverse(m, d)
    tau = d.qfrc_inverse - qf_sup  # qfrc_inverse = applied + actuator + constraint (docs); remove the support wrench
    jt = tau[6:18]; fr = s.fr[:12, 1]; ratio = np.abs(jt) / fr
    names = [m.actuator(i).name.replace("_joint", "") for i in range(12)]
    return dict(hip=hip, knee=knee, payload=payload, total_mass=float(s.mass), torque_Nm=dict(zip(names, map(float, jt))),
                ratio=dict(zip(names, map(float, ratio))), max_ratio=float(ratio.max()),
                com_x_in_foot_extent=in_polygon, com_x_rel_foot_extent=[float(min(xs)-cx), float(max(xs)-cx)], binding=names[int(ratio.argmax())], free_joint_residual_N=float(np.abs(tau[:6]).max()), root_resid_vec=tau[:6].round(2).tolist())


if __name__ == "__main__":
    out = []
    for hk in [(-0.3, 0.6), (-0.8, 1.5), (-1.2, 2.0), (-1.5, 2.5)]:
        for pl in (0.0, 5.0, 20.0, 40.0, 80.0):
            r = static_screen(*hk, payload=pl); out.append(r)
            print(f"hip={hk[0]:+.1f} knee={hk[1]:.1f} payload={pl:4.0f}kg  max_ratio={r['max_ratio']:.2f} ({r['binding']})  knee={r['torque_Nm']['left_knee']:.1f}/139 hip={r['torque_Nm']['left_hip_pitch']:.1f}/88 ankle={r['torque_Nm']['left_ankle_pitch']:.1f}/50 root_resid={r['free_joint_residual_N']:.2f}")
    json.dump(out, open("out/static_screen.json", "w"), indent=1)
