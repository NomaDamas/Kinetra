"""python export.py out/best_X.json -> out/trajectory.json (100 Hz, all bodies pos+quat) + replays params for a metrics check"""
import sys, json, numpy as np, mujoco
from jump import *
j = json.load(open(sys.argv[1]))
p = np.array([j["params"][k] for k in PNAMES])
s = Sim(); r = s.rollout(p, record=True)
fr = r.pop("frames"); m = s.m
names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(m.nbody)]
out = dict(model="unitree_g1 (MuJoCo Menagerie)", dt=0.01, body_names=names, params=j["params"], target_height=j["target"],
           metrics={k: v for k, v in r.items() if k not in ("per_joint_demand_ratio", "sat_frac")},
           frames=[dict(t=round(t, 4), pos=np.round(x, 4).tolist(), quat=np.round(q, 4).tolist()) for t, x, q in fr])
json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else "out/trajectory.json", "w"), separators=(",", ":"))
print(len(fr), "frames", r["com_apex_rise"], r["stable_landing"])
