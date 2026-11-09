"""rocket_car design: requirements -> components -> custom parts for one witness. Pure function of (spec, witness params, seed)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .. import catalog as cat
from . import cad, common, parts, requirements as R, selection as sel

NOZZLE_PLACEHOLDER_KG = 2.0      # per nozzle assembly: flagged placeholder, NOT sourced (no catalog nozzle in the thrust class)
VALVE_PLACEHOLDER_KG = 1.0       # per valve: flagged placeholder (flow class needs a gas valve; Danfoss SV13 is hydraulic-oil rated)
REGULATOR_PLACEHOLDER_KG = 1.5   # flagged placeholder
MAX_TANKS = 12


def design(spec, params: dict[str, float], seed: int, witness_ref: str, cad_dir: Path | None = None) -> dict[str, Any]:
    d = R.rocket_requirements(spec, params, seed, witness_ref)
    ex = d.extras
    catg = cat.components("rocket_car")["categories"]
    req = d.req
    n = R.N_NOZZLES

    nozzle = common.catalog_component(
        "nozzle", "thruster", n, catg["thruster"],
        [sel.Need("nozzle_peak_thrust", "thrust_N", req("nozzle_peak_thrust")["required"], "N")],
        placeholder_mass_each=NOZZLE_PLACEHOLDER_KG,
        unmet_note=f"No cataloged cold-gas thruster reaches {req('nozzle_peak_thrust')['required']:.0f} N (largest read: {max(e['specs']['thrust_N'] for e in catg['thruster']):.1f} N). "
                   "A nozzle in this thrust class has to be custom-designed or sourced from a propulsion supplier.",
        placeholder_note=f"Mass {NOZZLE_PLACEHOLDER_KG:g} kg per nozzle is a flagged placeholder estimate, not a sourced figure.")
    valve = common.catalog_component(
        "valve", "valve", n, catg["valve"],
        [sel.Need("nozzle_peak_flow", "gas_mass_flow_kg_s", req("nozzle_peak_flow")["required"], "kg/s")],
        placeholder_mass_each=VALVE_PLACEHOLDER_KG,
        unmet_note=f"Needs a gas valve passing {req('nozzle_peak_flow')['required']:.2f} kg/s of N2 per nozzle; the one cataloged valve (Danfoss SV13-20-C) is rated in L/min of hydraulic oil only, so it cannot be shown to meet this.",
        placeholder_note=f"Mass {VALVE_PLACEHOLDER_KG:g} kg per valve is a flagged placeholder estimate.")
    tank = common.catalog_component(
        "tank", "propellant_tank", 1, catg["tank"],
        [sel.Need("tank_volume", "volume_L", req("tank_volume")["required"], "L", additive=True),
         sel.Need("tank_working_pressure", "working_pressure_bar", req("tank_working_pressure")["required"], "bar")],
        additive_ok_qty=MAX_TANKS,
        unmet_note="Tank volume is additive: several cylinders are manifolded.")
    regulator = common.catalog_component(
        "regulator", "regulator", 1, catg["regulator"], [], placeholder_mass_each=REGULATOR_PLACEHOLDER_KG,
        unmet_note="No regulator with a read datasheet is in the catalog.", placeholder_note=f"Mass {REGULATOR_PLACEHOLDER_KG:g} kg is a flagged placeholder estimate.")
    n_tanks = tank["quantity"] if tank["choice"] else math.ceil(req("tank_volume")["required"] / 9.0)
    tank_each_kg = tank["mass_kg_each"] or 0.0
    tank_d_mm = float(tank["choice"]["specs"].get("diameter_mm", 186.0)) if tank["choice"] else 186.0

    br = parts.size_bracket(req("bracket_load")["required"], 2.0)
    landing_g = req("landing_load_factor")["required"]
    cr = parts.size_cradle(tank_each_kg, landing_g, tank_d_mm, 2.0)
    custom_parts = []
    comps_custom = []
    for pid, name, sized, qty, kind in (("nozzle_bracket", "Nozzle mount bracket", br, n, "nozzle_bracket"),
                                        ("tank_cradle", "Tank cradle saddle (2 per tank)", cr, 2 * n_tanks, "tank_cradle")):
        cadref = None
        stl = step = None
        note = sized["note"]
        if cad_dir is not None:
            w = cad.write_part(kind, sized["params"], cad_dir, pid)
            stl, step = w["stl"], w["step"]
            cadref = dict(stl=stl, step=step)
            if step is None:
                note += " STEP export unavailable (CAD kernel: trimesh primitives, STL only)."
        custom_parts.append(dict(id=pid, name=name, params=sized["params"], material=sized["material"], mass_kg=sized["mass_kg"], quantity=qty,
                                 cad_stl=stl, cad_step=step, load_case=sized["load_case"], check=sized["check"],
                                 extra_checks=sized["extra_checks"], note=note))
        comps_custom.append(dict(id=pid, role="custom_part", quantity=qty, choice=None, meets=[], ok=False, alternatives=[], custom=True, needs_sourcing=False,
                                 mass_kg_each=sized["mass_kg"], mass_source="cad", note=f"Parametric part: {sized['material']} plate sized by a hand calculation (simplified model, needs FEA).",
                                 cad=cadref))
    propellant_kg = req("propellant_mass")["required"]
    propellant = dict(id="propellant", role="propellant", quantity=1, choice=None, meets=[], ok=False, alternatives=[], custom=False, needs_sourcing=True,
                      mass_kg_each=None, mass_source="none",
                      note=(f"Commodity nitrogen, {propellant_kg:.1f} kg = simulated need {req('propellant_mass')['value']:.1f} kg x margin {req('propellant_mass')['margin_factor']:g}; no cited price. "
                            "Its mass is NOT added by the closed loop: the vehicle_mass assumption already includes the gas."), cad=None)
    comps = [nozzle, valve, tank, regulator, *comps_custom, propellant]
    tot = common.mass_totals(comps)
    return dict(requirements=d.requirements, components=comps, custom_parts=custom_parts, extras=ex, **tot)
