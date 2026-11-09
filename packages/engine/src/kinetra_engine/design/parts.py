"""Parametric custom parts: closed-form volume/mass and hand-calc load checks (the same numbers drive the CAD in cad.py).

All structural checks are SIMPLIFIED hand calculations (beam bending / bearing) and carry the label
'simplified model, needs FEA'. Sizing picks the smallest 0.5 mm plate thickness that passes the check.
"""
from __future__ import annotations

import math
from typing import Any

from physlab_core.schemas import NEEDS_FEA_LABEL

from .. import catalog as cat

MATERIAL = "6061-T6"
T_STEP = 0.5   # mm sizing grid


def material() -> dict[str, Any]:
    return cat.components("rocket_car")["materials"][MATERIAL]


def _round_up(x: float, step: float = T_STEP) -> float:
    return math.ceil(x / step - 1e-9) * step


def _check(method: str, stress_pa: float, allow_pa: float) -> dict[str, Any]:
    return dict(method=method, stress_MPa=round(stress_pa / 1e6, 3), allow_MPa=round(allow_pa / 1e6, 3),
                ok=bool(round(stress_pa / 1e6, 3) <= round(allow_pa / 1e6, 3)), label=NEEDS_FEA_LABEL)


# --------------------------------------------------------------------------- nozzle mount bracket (L bracket, thrust plate cantilevered from a bolted base flange)
BRACKET_FIXED = dict(width_mm=80.0, height_mm=60.0, depth_mm=70.0, bolt_d_mm=9.0, n_bolts=4)


def bracket_volume_mm3(p: dict[str, float]) -> float:
    W, H, D, t = p["width_mm"], p["height_mm"], p["depth_mm"], p["plate_t_mm"]
    holes = p["n_bolts"] * math.pi * (p["bolt_d_mm"] / 2) ** 2 * t
    return W * D * t + W * t * H - holes      # base flange W x D x t + upright plate W x t x H, holes through the base only


def size_bracket(force_N: float, safety_factor: float = 2.0) -> dict[str, Any]:
    """Thrust plate = cantilever of length H, load F at its tip, section W x t: sigma = 6 F H / (W t^2) <= yield / SF; bearing check on the bolt holes."""
    mat = material()
    y, tau_y = mat["yield_MPa"] * 1e6, mat["shear_MPa"] * 1e6
    allow = y / safety_factor
    W, H = BRACKET_FIXED["width_mm"] / 1e3, BRACKET_FIXED["height_mm"] / 1e3
    t_bend = math.sqrt(6 * force_N * H / (W * allow))
    n, d = BRACKET_FIXED["n_bolts"], BRACKET_FIXED["bolt_d_mm"] / 1e3
    t_brg = force_N / (n * d * (y / safety_factor))
    t = _round_up(max(t_bend, t_brg) * 1e3)
    p = dict(BRACKET_FIXED, plate_t_mm=t)
    sig = 6 * force_N * H / (W * (t / 1e3) ** 2)
    brg = force_N / (n * d * (t / 1e3))
    vol = bracket_volume_mm3(p)
    return dict(params=p, mass_kg=vol * 1e-9 * mat["density_kg_m3"], material=MATERIAL,
                load_case=dict(force_N=round(force_N, 1), safety_factor=safety_factor),
                check=_check("cantilever bending of the thrust plate, hand calc: sigma = 6 F H / (W t^2) vs yield/SF", sig, allow),
                extra_checks=[_check("bolt-hole bearing on the plate, hand calc: F / (n d t) vs yield/SF", brg, allow)],
                note="Gussets, bolt preload, fatigue and the nozzle's own mounting flange are not modelled.")


# --------------------------------------------------------------------------- tank cradle (saddle plate with a circular cut-out; bolted down at both ends)
def cradle_volume_mm3(p: dict[str, float]) -> float:
    W, L, t, r = p["width_mm"], p["length_mm"], p["plate_t_mm"], p["tank_radius_mm"]
    cut = math.pi * r * r * t / 2.0          # half-circle seat cut out of the top edge
    return W * L * t - cut


def size_cradle(tank_mass_kg: float, decel_g: float, tank_diameter_mm: float, safety_factor: float = 2.0) -> dict[str, Any]:
    """Two saddles per tank. Each saddle plate is a beam between its two bolt lines (span = tank diameter + 40 mm) with the inertial
    load of half the tank at mid span: sigma = 6 M / (b t^2), M = F S / 4."""
    mat = material()
    allow = mat["yield_MPa"] * 1e6 / safety_factor
    g = 9.80665
    F = 0.5 * tank_mass_kg * g * decel_g          # per saddle [N]
    S = (tank_diameter_mm + 40.0) / 1e3
    b = 100.0
    t_mm = _round_up(math.sqrt(6 * (F * S / 4) / ((b / 1e3) * allow)) * 1e3)
    p = dict(width_mm=b, length_mm=tank_diameter_mm + 40.0, plate_t_mm=t_mm, tank_radius_mm=tank_diameter_mm / 2.0)
    sig = 6 * (F * S / 4) / ((b / 1e3) * (t_mm / 1e3) ** 2)
    vol = cradle_volume_mm3(p)
    return dict(params=p, mass_kg=vol * 1e-9 * mat["density_kg_m3"], material=MATERIAL,
                load_case=dict(force_N=round(F, 1), safety_factor=safety_factor, decel_g=round(decel_g, 3)),
                check=_check("saddle plate as a simply supported beam, point load at mid span, hand calc", sig, allow),
                extra_checks=[], note="Strap tension, bolt shear and cradle-to-frame load path are not modelled; load = measured peak landing deceleration x tank mass.")


# --------------------------------------------------------------------------- shank link (hollow rectangular tube, humanoid knee)
def tube_volume_mm3(p: dict[str, float]) -> float:
    a, b, w, L = p["outer_w_mm"], p["outer_d_mm"], p["wall_mm"], p["length_mm"]
    return (a * b - (a - 2 * w) * (b - 2 * w)) * L


def size_shank_link(torque_Nm: float, length_mm: float = 300.0, outer_w_mm: float = 40.0, outer_d_mm: float = 30.0,
                    safety_factor: float = 2.0) -> dict[str, Any]:
    """Link loaded by the joint torque as a bending moment at the actuator end: sigma = T c / I for a thin-walled rectangular tube."""
    mat = material()
    allow = mat["yield_MPa"] * 1e6 / safety_factor
    a, b = outer_w_mm / 1e3, outer_d_mm / 1e3

    def stress(w_mm: float) -> float:
        w = w_mm / 1e3
        I = (a * b ** 3 - (a - 2 * w) * (b - 2 * w) ** 3) / 12.0     # bending about the width axis (depth b is the bending direction)
        return torque_Nm * (b / 2) / I
    w_mm = 1.0
    while w_mm < min(outer_w_mm, outer_d_mm) / 2 - 0.5 and stress(w_mm) > allow:
        w_mm += T_STEP
    p = dict(outer_w_mm=outer_w_mm, outer_d_mm=outer_d_mm, wall_mm=w_mm, length_mm=length_mm)
    return dict(params=p, mass_kg=tube_volume_mm3(p) * 1e-9 * mat["density_kg_m3"], material=MATERIAL,
                load_case=dict(torque_Nm=round(torque_Nm, 2), safety_factor=safety_factor),
                check=_check("hollow rectangular tube in bending under the joint torque, hand calc: sigma = T c / I", stress(w_mm), allow),
                extra_checks=[], note="Actuator flange, bearing seats, fatigue and impact loads are not modelled.")
