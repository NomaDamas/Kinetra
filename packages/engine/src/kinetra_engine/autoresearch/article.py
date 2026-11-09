"""Self-made rigid-body evaluation articles: a free 6-DoF box with N thruster sites (MJCF generated in Python).

Two presets, same code path:

* ``toy10``    : 10 kg, 1.0 x 0.5 x 0.3 m box, 6 N thrusters, pitch lever arm 0.5 m. Serves both autoresearch tasks
                 (attitude control, calibration). I_y = 0.908 kg m^2.
* ``roadster`` : 1300 kg, 4.2 x 1.9 x 1.2 m box, 5000 N thrusters at +-2.1 m (the Roadster spike's pitch-axis
                 numbers; I_y = 2085.4 kg m^2 is the whole-vehicle value that spike measured). Only the attitude task
                 is run on it. It is a rigid box, NOT the Roadster template (no wheels, ramp, aero, structure).

Physical parameters are applied to a compiled model *in place* (no recompile): body_mass, body_inertia,
body_ipos (COM offset), actuator_gear (thrust gain, per-thruster mismatch), dof_damping, geom_solref (contact),
then ``mj_setConst``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Preset:
    name: str
    mass: float
    box_full: tuple          # x, y, z full extents [m]
    inertia: tuple           # diagonal about COM [kg m^2]
    fmax: float              # N per thruster at ctrl=1
    arm: float               # pitch-couple lever arm [m]
    aux_z: float             # lateral aux thrusters at (0, 0, +-aux_z) pushing +x
    com_scale: float         # COM-offset disturbance scale relative to the toy (x +-3 cm, z +-2 cm)
    extra_arm_hyp: float     # lever arm used by the "second thruster pair" hardware hypothesis
    nominal: tuple           # (lin_damping, rot_damping) nominal


def _box_inertia(m, b):
    return tuple(m / 12.0 * v for v in (b[1] ** 2 + b[2] ** 2, b[0] ** 2 + b[2] ** 2, b[0] ** 2 + b[1] ** 2))


_TOY_BOX = (1.0, 0.5, 0.3)
_RS_BOX = (4.2, 1.9, 1.2)
_RS_I = _box_inertia(1300.0, _RS_BOX)
PRESETS: dict[str, Preset] = {
    "toy10": Preset("toy10", 10.0, _TOY_BOX, _box_inertia(10.0, _TOY_BOX), 6.0, 0.5, 0.15, 1.0, 0.7, (0.4, 0.1)),
    "roadster": Preset("roadster", 1300.0, _RS_BOX, (_RS_I[0], 2085.368, _RS_I[2]), 5000.0, 2.1, 0.3, 4.2, 1.5,
                       (0.4, 0.1)),
}

# Back-compat names for the toy (calibration task is toy-only).
NOMINAL = {
    "mass": 10.0, "com_x": 0.0, "com_z": 0.0, "inertia_scale": 1.0, "thrust_gain": 1.0,
    "lin_damping": 0.4, "rot_damping": 0.1, "contact_timeconst": 0.03, "contact_dampratio": 0.6,
}


def nominal_params(preset: str = "toy10") -> dict:
    p = PRESETS[preset]
    q = dict(NOMINAL)
    q["mass"] = p.mass
    return q


def thruster_layout(preset: Preset, extra_pair_arm: float | None = None) -> list[dict]:
    """6 thrusters: 4 pitch-couple thrusters (tags p+/p-) + 2 lateral aux. Optional 4 more at another arm."""
    a0, z = preset.arm, preset.aux_z
    L = [
        dict(name="t0", pos=(-a0, 0, 0), dir=(0, 0, 1), tag="p+"),
        dict(name="t1", pos=(a0, 0, 0), dir=(0, 0, -1), tag="p+"),
        dict(name="t2", pos=(a0, 0, 0), dir=(0, 0, 1), tag="p-"),
        dict(name="t3", pos=(-a0, 0, 0), dir=(0, 0, -1), tag="p-"),
        dict(name="t4", pos=(0, 0, z), dir=(1, 0, 0), tag="aux"),
        dict(name="t5", pos=(0, 0, -z), dir=(1, 0, 0), tag="aux"),
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


def build_mjcf(preset: Preset, layout: list[dict], ctrl_hi: float, dt: float) -> str:
    sites, acts = [], []
    for t in layout:
        p, d = t["pos"], t["dir"]
        sites.append(f'<site name="{t["name"]}" pos="{p[0]} {p[1]} {p[2]}" zaxis="{d[0]} {d[1]} {d[2]}" size="0.02"/>')
        acts.append(
            f'<general name="a_{t["name"]}" site="{t["name"]}" gear="0 0 {preset.fmax} 0 0 0" '
            f'ctrllimited="true" ctrlrange="0 {ctrl_hi}"/>'
        )
    hx, hy, hz = (v / 2 for v in preset.box_full)
    I = preset.inertia
    return f"""
<mujoco model="kinetra_article_{preset.name}">
  <option timestep="{dt}" gravity="0 0 -9.81" integrator="implicitfast"/>
  <worldbody>
    <geom name="ground" type="plane" size="20 20 0.1" friction="0.8 0.005 0.0001" solref="0.03 0.6"/>
    <body name="box" pos="0 0 100">
      <freejoint name="free"/>
      <inertial pos="1e-6 1e-6 1e-6" mass="{preset.mass}" diaginertia="{I[0]} {I[1]} {I[2]}"/>
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

    def __init__(self, preset: str = "toy10", extra_pair_arm: float | None = None, ctrl_hi: float = 1.0, dt: float = 0.005):
        self.preset = PRESETS[preset]
        self.layout = thruster_layout(self.preset, extra_pair_arm)
        self.fmax, self.ctrl_hi, self.dt = self.preset.fmax, ctrl_hi, dt
        self.nominal = nominal_params(preset)
        self.m = mujoco.MjModel.from_xml_string(build_mjcf(self.preset, self.layout, ctrl_hi, dt))
        self.d = mujoco.MjData(self.m)
        self.nu = self.m.nu
        self.body = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, "box")
        self.geom = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "boxgeom")
        self.ground = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        self.p_plus = [i for i, t in enumerate(self.layout) if t["tag"] == "p+"]
        self.p_minus = [i for i, t in enumerate(self.layout) if t["tag"] == "p-"]
        self.nominal_torque = sum(self.fmax * self.ctrl_hi * abs(self.layout[i]["pos"][0]) for i in self.p_plus)
        self.inertia_y_nominal = self.preset.inertia[1]
        self.alpha_nominal = self.nominal_torque / self.inertia_y_nominal  # rad/s^2 at full pitch command
        # fuel is reported in units that make the 1e-4 tie-break weight article-independent (toy fmax = 6 N)
        self.fuel_scale = 6.0 / self.fmax

    def set_params(self, p: dict | None = None, mismatch: np.ndarray | None = None) -> None:
        q = dict(self.nominal)
        if p:
            q.update(p)
        m = self.m
        m.body_mass[self.body] = q["mass"]
        m.body_inertia[self.body] = np.array(self.preset.inertia) * q["inertia_scale"]
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
