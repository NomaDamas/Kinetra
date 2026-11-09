"""Nitrogen storage sizing: ideal gas and van der Waals (real-gas) density.

van der Waals constants for N2 (a = 1.370 L^2*bar/mol^2, b = 0.0387 L/mol) are textbook values NOT checked against a cited page
by the catalog author -> sizing results are labelled 'estimate'. Real-gas density from the EOS differs from the ideal-gas
value by a few percent at 300 bar; the larger required volume of the two is used (conservative).
"""
from __future__ import annotations

import numpy as np

R = 8.314462618          # J/(mol K)
M_N2 = 0.0280134         # kg/mol
VDW_A = 1.370e-1         # Pa m^6 / mol^2   (1.370 L^2 bar / mol^2)
VDW_B = 3.87e-5          # m^3 / mol        (0.0387 L / mol)
VDW_NOTE = ("van der Waals N2 constants a=1.370 L^2*bar/mol^2, b=0.0387 L/mol (textbook, not verified against a cited page); "
            "ideal-gas value also computed, the larger required tank volume is used")


def rho_ideal(p_bar: float, t_k: float) -> float:
    return p_bar * 1e5 * M_N2 / (R * t_k)


def rho_vdw(p_bar: float, t_k: float) -> float:
    """Density [kg/m^3] from the van der Waals EOS (largest real root of the molar-volume cubic = gas branch)."""
    p = p_bar * 1e5
    # p V^3 - (p b + R T) V^2 + a V - a b = 0
    roots = np.roots([p, -(p * VDW_B + R * t_k), VDW_A, -VDW_A * VDW_B])
    v = max(r.real for r in roots if abs(r.imag) < 1e-9 and r.real > VDW_B)
    return M_N2 / v


def usable_density(p_fill_bar: float, p_min_bar: float, t_k: float, real: bool) -> float:
    f = rho_vdw if real else rho_ideal
    return f(p_fill_bar, t_k) - f(p_min_bar, t_k)


def tank_volume_l(mass_kg: float, p_fill_bar: float, p_min_bar: float, t_k: float = 293.15) -> dict[str, float]:
    """Water volume needed to deliver ``mass_kg`` of N2 isothermally between p_fill and p_min (no cooling in blowdown modelled)."""
    out = {}
    for name, real in (("ideal", False), ("vdw", True)):
        out[name] = 1000.0 * mass_kg / usable_density(p_fill_bar, p_min_bar, t_k, real)
    out["used"] = max(out["ideal"], out["vdw"])
    return out
