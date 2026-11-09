"""Requirements derived from REAL rollouts of the base (feasible) variant's witness.

rocket_car   : exact thrust schedule (``Sim.controls``) -> per-nozzle peak thrust, total impulse, propellant, mass flow, tank volume;
               landing load from the MuJoCo contact force of ``RocketCar.rollout`` (peak contact normal force in 0.3 s after touchdown).
humanoid_jump: a traced ``Sim.rollout`` (``mujoco.mj_step`` wrapped to record joint velocity / actuator force every step) -> per-joint
               peak torque and speed, mechanical power and energy to liftoff, landing GRF.
Every returned ``value`` is a maximum / integral over those rollouts; ``required = value * margin_factor``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import gas

G0 = 9.80665
FILL_BAR = 300.0         # default storage pressure = rating of every cataloged tank (design choice, flagged 'default')
MIN_BAR = 10.0           # default minimum usable supply pressure (blow-down end), flagged 'default'
TEMP_K = 293.15
M_NOZZLE = dict(margin=1.25)
N_NOZZLES = 18


@dataclass
class Derived:
    requirements: list[dict[str, Any]]
    extras: dict[str, Any] = field(default_factory=dict)   # raw measurements for sizing / text (not requirements)

    def req(self, rid: str) -> dict[str, Any]:
        return next(r for r in self.requirements if r["id"] == rid)


def _r(id: str, label: str, value: float, unit: str, derived_from: str, margin: float, source: str = "simulation") -> dict[str, Any]:
    value = float(value)
    return dict(id=id, label=label, value=value, unit=unit, derived_from=derived_from, margin_factor=float(margin),
                required=value * float(margin), source=source)


# --------------------------------------------------------------------------- rocket_car
def rocket_requirements(spec, params: dict[str, float], seed: int, witness_ref: str) -> Derived:
    from ..templates import get
    from ..templates import rocket_car as rc
    tpl = get("rocket_car")
    v = {a.key: float(a.value) for a in spec.assumptions}
    sim = tpl._sim(spec)
    env = tpl._env_nom(spec)
    thr = sim.controls(rc.params_to_x(params)[None])[0]                    # (T, K) throttle 0..1, exactly what the judge ran
    force = thr * (env.fmax[0] * env.tscale[0])[None, :]                    # N per nozzle per step
    peak_thrust = float(force.max())
    total_force = force.sum(1)
    impulse = float(total_force.sum() * rc.DT)
    isp = v["isp"]
    propellant = impulse / (isp * G0)
    flow_peak = peak_thrust / (isp * G0)
    burn_s = float(((force.sum(1)) > 1.0).sum() * rc.DT)
    m, _, _ = sim.evaluate_nominal(rc.params_to_x(params)[None], env)
    if not bool(m["success"][0]):
        raise ValueError("witness does not satisfy the success criteria on the nominal model; refusing to derive requirements")
    fuel_judged = float(m["fuel"][0])
    traj = tpl.rollout(spec, params, seed)
    land = next((e for e in traj.events if e.kind == "landing"), None)
    peak_contact = float(land.magnitude) if land and land.magnitude else 0.0
    mass = v["vehicle_mass"]
    decel_g = peak_contact / (mass * G0)
    vol = gas.tank_volume_l(propellant, FILL_BAR, MIN_BAR, TEMP_K)
    wr = f"witness schedule ({witness_ref}), nominal rollout"
    mf_p = 1.2
    reqs = [
        _r("nozzle_peak_thrust", "Peak thrust per nozzle", peak_thrust, "N", f"max over all {N_NOZZLES} nozzles (10 pitch/lift + 8 roll) and time steps of throttle x thrust_force_max, {wr}", 1.25),
        _r("bracket_load", "Nozzle bracket design load (peak thrust, margin applied; part adds safety factor 2.0 on yield)", peak_thrust, "N",
           f"peak per-nozzle thrust of the {wr}", 1.25),
        _r("nozzle_peak_flow", "Peak propellant mass flow per nozzle", flow_peak, "kg/s",
           f"peak thrust / (Isp x g0) with Isp = {isp:g} s (assumption, unverified); {wr}", 1.25, "simulation"),
        _r("total_impulse", "Total impulse of the maneuver", impulse, "N*s", f"sum over nozzles and time of force x dt, {wr}", 1.2),
        _r("propellant_mass", "Propellant mass for the maneuver", propellant, "kg", f"total impulse / (Isp x g0), Isp = {isp:g} s (assumption, unverified); {wr}", mf_p),
        _r("tank_volume", f"Tank water volume at {FILL_BAR:g} bar fill (usable down to {MIN_BAR:g} bar)", vol["used"], "L",
           f"N2 stored isothermally {FILL_BAR:g}->{MIN_BAR:g} bar at {TEMP_K - 273.15:.0f} C: max(ideal gas {vol['ideal']:.2f} L, van der Waals {vol['vdw']:.2f} L) for the propellant above; "
           f"{gas.VDW_NOTE}. Storage pressure and minimum supply pressure are defaults", mf_p, "estimate"),
        _r("tank_working_pressure", "Tank working pressure", FILL_BAR, "bar", "design default (a rated 300 bar Type-4 cylinder class); not derived from the simulation", 1.0, "default"),
        _r("landing_load_factor", "Peak landing contact load (x vehicle weight)", decel_g, "g",
           f"peak contact normal force in the 0.3 s after first touchdown ({peak_contact:.0f} N, MuJoCo contact solver) / (vehicle mass {mass:g} kg x g); {wr}. CAVEAT: the model is a rigid body with no suspension compliance, so this contact load depends on the solver's contact stiffness and is a crude upper-end figure, not a validated landing load", 1.25),
    ]
    extras = dict(peak_thrust_N=peak_thrust, impulse_Ns=impulse, propellant_kg=propellant, fuel_judged_kg=fuel_judged, flow_peak_kg_s=flow_peak,
                  burn_time_s=burn_s, landing_peak_contact_N=peak_contact, landing_load_factor=decel_g, vehicle_mass_kg=mass, tank_volume=vol,
                  fmax_N=float(env.fmax[0]), isp_s=isp, n_nozzles=N_NOZZLES)
    return Derived(reqs, extras)


# --------------------------------------------------------------------------- humanoid_jump
class _TraceMujoco:
    """Proxy for the ``mujoco`` module inside templates.humanoid_jump: ``mj_step`` also records qvel / actuator force of the 12 leg joints."""

    def __init__(self, real):
        self._real = real
        self.t, self.qd, self.tau = [], [], []

    def __getattr__(self, k):
        return getattr(self._real, k)

    def mj_step(self, m, d, *a, **kw):
        self._real.mj_step(m, d, *a, **kw)
        self.t.append(float(d.time))
        self.qd.append(d.qvel[6:18].copy())
        self.tau.append(d.actuator_force[:12].copy())


JOINT_TYPES = ["hip_pitch", "hip_roll", "hip_yaw", "knee", "ankle_pitch", "ankle_roll"]
JOINT_LABEL = {"hip_pitch": "Hip pitch", "hip_roll": "Hip roll", "hip_yaw": "Hip yaw", "knee": "Knee", "ankle_pitch": "Ankle pitch", "ankle_roll": "Ankle roll"}
BATTERY_JUMPS = 100
DRIVE_EFF = 0.5          # default electrical->mechanical chain efficiency (unverified), used only for the battery line


def humanoid_requirements(spec, params: dict[str, float], seed: int, witness_ref: str) -> Derived:
    from ..templates import humanoid_jump as hj
    v = hj._values(spec)
    s = hj.Sim()
    s.configure(*hj._cfg(v))
    p = np.array([params[k] for k in hj.PNAMES])
    real = hj.mujoco
    tr = _TraceMujoco(real)
    hj.mujoco = tr
    try:
        r = s.rollout(p, record=False)
    finally:
        hj.mujoco = real
    if not r.get("stable_landing") or r.get("ballistic_height", 0.0) < v["target_height"]:
        raise ValueError("witness does not reproduce a successful jump on the nominal model; refusing to derive requirements")
    t = np.array(tr.t)
    qd = np.array(tr.qd)
    tau = np.array(tr.tau)
    names = s.act_names
    power = tau * qd                                                       # per joint [W], + = actuator does work on the joint
    t_lift = r["t_liftoff"]
    push = t <= t_lift
    dt = float(s.m.opt.timestep)
    e_pos_to_lift = float((np.clip(power, 0, None).sum(1) * push).sum() * dt)
    p_total = np.clip(power, 0, None).sum(1)
    peak_power = float(p_total.max())
    wr = f"traced nominal rollout of the witness ({witness_ref}); {len(t)} steps of {dt * 1e3:.0f} ms"
    reqs = []
    peaks = {}
    for jt in JOINT_TYPES:
        idx = [i for i, n in enumerate(names) if n.endswith(jt)]
        tq = float(np.abs(tau[:, idx]).max())
        sp = float(np.abs(qd[:, idx]).max())
        peaks[jt] = dict(torque_Nm=tq, speed_rad_s=sp, joints=[names[i] for i in idx], saturated=bool(tq >= 0.98 * max(float(s.fr[i, 1]) for i in idx)))
        fr = max(float(s.fr[i, 1]) for i in idx)
        sat = tq >= 0.98 * fr
        reqs.append(_r(f"{jt}_peak_torque", f"{JOINT_LABEL[jt]} peak torque", tq, "N*m",
                       f"max |actuator force| over both {jt} joints and all steps, {wr}"
                       + (f". SATURATED: equals the model's actuator limit ({fr:g} N*m), so the unconstrained demand is at least this value" if sat else ""), 1.3))
        reqs.append(_r(f"{jt}_peak_speed", f"{JOINT_LABEL[jt]} peak joint speed", sp, "rad/s", f"max |joint velocity| over both {jt} joints and all steps, {wr}", 1.3))
    grf_n = float(r["grf_peak_land_N"])
    mass = float(s.mass)
    e_wh = e_pos_to_lift / 3600.0
    reqs += [
        _r("peak_mech_power", "Peak total mechanical power (12 leg joints)", peak_power, "W", f"max over steps of sum(max(tau*qdot, 0)), {wr}", 1.2),
        _r("jump_energy", "Mechanical energy per jump (to liftoff)", e_pos_to_lift, "J", f"integral of positive joint power from start to liftoff (t = {t_lift:.2f} s), {wr}", 1.2),
        _r("landing_grf", "Peak landing ground-reaction force", grf_n, "N", f"peak vertical foot contact force after first touchdown, {wr}", 1.25),
        _r("battery_energy", f"Battery energy for {BATTERY_JUMPS} jumps", e_wh * BATTERY_JUMPS / DRIVE_EFF, "Wh",
           f"jump energy x {BATTERY_JUMPS} / drive efficiency {DRIVE_EFF:g} (default, unverified); excludes standby and walking", 1.2, "estimate"),
    ]
    extras = dict(peaks=peaks, peak_power_W=peak_power, jump_energy_J=e_pos_to_lift, landing_grf_N=grf_n, landing_grf_bw=float(r["grf_peak_land_bw"]),
                  ballistic_height_m=float(r["ballistic_height"]), t_liftoff_s=float(t_lift), robot_mass_kg=mass,
                  torque_scale=float(v.get("torque_scale", 1.0)), target_height_m=float(v["target_height"]),
                  forcerange_Nm={names[i]: float(s.fr[i, 1]) for i in range(12)})
    return Derived(reqs, extras)
