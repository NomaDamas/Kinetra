"""Self-made rigid-body test article: free 6-DoF box with N thruster sites.

MJCF is generated in Python (no dependency on the roadster spike). The same article
serves both autoresearch tasks:

* attitude control  (flip 360 deg about body y and stop upright, ballistic flight)
* calibration       (fit mass / COM / inertia / thrust gain / damping / contact params)

Physical parameters are applied to a compiled model *in place* (no recompile):
body_mass, body_inertia, body_ipos (COM offset), actuator_gear (thrust gain,
per-thruster mismatch), dof_damping, geom_solref (contact). Then ``mj_setConst``.
"""
from __future__ import annotations

import json
import math

import mujoco
import numpy as np

# Calibratable / disturbable physical parameters (shared vocabulary of both tasks).
PARAM_KEYS = [
    "mass", "com_x", "com_z", "inertia_scale", "thrust_gain",
    "lin_damping", "rot_damping", "contact_timeconst", "contact_dampratio",
]
PARAM_UNITS = {
    "mass": "kg", "com_x": "m", "com_z": "m", "inertia_scale": "", "thrust_gain": "",
    "lin_damping": "N*s/m", "rot_damping": "N*m*s/rad", "contact_timeconst": "s",
    "contact_dampratio": "",
}
PARAM_LABELS = {
    "mass": "Article mass", "com_x": "COM offset x (body frame)", "com_z": "COM offset z (body frame)",
    "inertia_scale": "Inertia scale (x nominal box inertia)", "thrust_gain": "Thrust gain (x nominal)",
    "lin_damping": "Linear damping", "rot_damping": "Rotational damping",
    "contact_timeconst": "Contact solref time constant", "contact_dampratio": "Contact solref damping ratio",
}
NOMINAL = {
    "mass": 10.0, "com_x": 0.0, "com_z": 0.0, "inertia_scale": 1.0, "thrust_gain": 1.0,
    "lin_damping": 0.4, "rot_damping": 0.1, "contact_timeconst": 0.03, "contact_dampratio": 0.6,
}
BOX_FULL = (1.0, 0.5, 0.3)  # x, y, z full extents [m]
BASE_MASS = 10.0
BASE_INERTIA = tuple(
    BASE_MASS / 12.0 * v
    for v in (BOX_FULL[1] ** 2 + BOX_FULL[2] ** 2, BOX_FULL[0] ** 2 + BOX_FULL[2] ** 2, BOX_FULL[0] ** 2 + BOX_FULL[1] ** 2)
)


def thruster_layout(extra_pair_arm: float | None = None) -> list[dict]:
    """6 thrusters: 4 pitch-couple thrusters (tags p+/p-) + 2 lateral aux. Optional 4 more at a longer arm."""
    L = [
        dict(name="t0", pos=(-0.5, 0, 0), dir=(0, 0, 1), tag="p+"),
        dict(name="t1", pos=(0.5, 0, 0), dir=(0, 0, -1), tag="p+"),
        dict(name="t2", pos=(0.5, 0, 0), dir=(0, 0, 1), tag="p-"),
        dict(name="t3", pos=(-0.5, 0, 0), dir=(0, 0, -1), tag="p-"),
        dict(name="t4", pos=(0, 0, 0.15), dir=(1, 0, 0), tag="aux"),
        dict(name="t5", pos=(0, 0, -0.15), dir=(1, 0, 0), tag="aux"),
    ]
    if extra_pair_arm:
        a = float(extra_pair_arm)
        L += [
            dict(name="t6", pos=(-a, 0, 0), dir=(0, 0, 1), tag="p+"),
            dict(name="t7", pos=(a, 0, 0), dir=(0, 0, -1), tag="p+"),
            dict(name="t8", pos=(a, 0, 0), dir=(0, 0, 1), tag="p-"),
            dict(name="t9", pos=(-a, 0, 0), dir=(0, 0, -1), tag="p-"),
        ]
    return L


def build_mjcf(layout: list[dict], fmax: float, ctrl_hi: float, dt: float) -> str:
    sites, acts = [], []
    for t in layout:
        p, d = t["pos"], t["dir"]
        sites.append(f'<site name="{t["name"]}" pos="{p[0]} {p[1]} {p[2]}" zaxis="{d[0]} {d[1]} {d[2]}" size="0.02"/>')
        acts.append(
            f'<general name="a_{t["name"]}" site="{t["name"]}" gear="0 0 {fmax} 0 0 0" '
            f'ctrllimited="true" ctrlrange="0 {ctrl_hi}"/>'
        )
    hx, hy, hz = (v / 2 for v in BOX_FULL)
    return f"""
<mujoco model="kinetra_article">
  <option timestep="{dt}" gravity="0 0 -9.81" integrator="implicitfast"/>
  <worldbody>
    <geom name="ground" type="plane" size="20 20 0.1" friction="0.8 0.005 0.0001" solref="0.03 0.6"/>
    <body name="box" pos="0 0 100">
      <freejoint name="free"/>
      <inertial pos="1e-6 1e-6 1e-6" mass="{BASE_MASS}" diaginertia="{BASE_INERTIA[0]} {BASE_INERTIA[1]} {BASE_INERTIA[2]}"/>
      <geom name="boxgeom" type="box" size="{hx} {hy} {hz}" friction="0.8 0.005 0.0001" solref="0.03 0.6" rgba="0.3 0.5 0.9 1"/>
      {' '.join(sites)}
    </body>
  </worldbody>
  <actuator>
    {' '.join(acts)}
  </actuator>
</mujoco>
"""


class Article:
    """Compiled article + in-place parameter application."""

    def __init__(self, extra_pair_arm: float | None = None, fmax: float = 6.0, ctrl_hi: float = 1.0, dt: float = 0.005):
        self.layout = thruster_layout(extra_pair_arm)
        self.fmax, self.ctrl_hi, self.dt = fmax, ctrl_hi, dt
        self.m = mujoco.MjModel.from_xml_string(build_mjcf(self.layout, fmax, ctrl_hi, dt))
        self.d = mujoco.MjData(self.m)
        self.nu = self.m.nu
        self.body = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, "box")
        self.geom = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "boxgeom")
        self.ground = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        self.p_plus = [i for i, t in enumerate(self.layout) if t["tag"] == "p+"]
        self.p_minus = [i for i, t in enumerate(self.layout) if t["tag"] == "p-"]
        self.nominal_torque = sum(self.fmax * self.ctrl_hi * abs(self.layout[i]["pos"][0]) for i in self.p_plus)
        self.inertia_y_nominal = BASE_INERTIA[1]
        self.alpha_nominal = self.nominal_torque / self.inertia_y_nominal  # rad/s^2 at full pitch command

    def set_params(self, p: dict | None = None, mismatch: np.ndarray | None = None) -> None:
        q = dict(NOMINAL)
        if p:
            q.update(p)
        m = self.m
        m.body_mass[self.body] = q["mass"]
        m.body_inertia[self.body] = np.array(BASE_INERTIA) * q["inertia_scale"]
        m.body_ipos[self.body] = [q["com_x"], 0.0, q["com_z"]]
        g = np.full(self.nu, q["thrust_gain"]) * (mismatch if mismatch is not None else 1.0)
        for i in range(self.nu):
            m.actuator_gear[i, 2] = self.fmax * g[i]
        m.dof_damping[0:3] = q["lin_damping"]
        m.dof_damping[3:6] = q["rot_damping"]
        sr = [q["contact_timeconst"], q["contact_dampratio"]]
        m.geom_solref[self.geom] = sr
        m.geom_solref[self.ground] = sr
        mujoco.mj_setConst(m, self.d)

    def reset(self, pos=(0.0, 0.0, 100.0), quat=(1.0, 0.0, 0.0, 0.0)) -> None:
        mujoco.mj_resetData(self.m, self.d)
        self.d.qpos[0:3] = pos
        self.d.qpos[3:7] = quat
        mujoco.mj_forward(self.m, self.d)


def pitch_of(q: np.ndarray) -> float:
    return 2.0 * math.atan2(q[2], q[0])


def versions() -> dict:
    import platform
    import sys
    out = {"python": sys.version.split()[0], "mujoco": mujoco.__version__, "numpy": np.__version__, "platform": platform.platform()}
    try:
        import cma
        out["cma"] = cma.__version__
    except Exception:
        pass
    try:
        import scipy
        out["scipy"] = scipy.__version__
    except Exception:
        pass
    return out


def hw_key(hw: dict) -> str:
    return json.dumps(hw, sort_keys=True)
