"""humanoid_jump design: per-joint requirements -> actuator selection -> custom shank link -> battery line."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import catalog as cat
from . import cad, common, parts, requirements as R, selection as sel

BATTERY_PLACEHOLDER_KG = 1.5      # flagged placeholder: no battery entry with a read datasheet
CONTROLLER_NOTE = "Motor drivers / controllers and wiring are not itemised."


def design(spec, params: dict[str, float], seed: int, witness_ref: str, cad_dir: Path | None = None) -> dict[str, Any]:
    d = R.humanoid_requirements(spec, params, seed, witness_ref)
    ex = d.extras
    catg = cat.components("humanoid_jump")["categories"]
    comps = []
    strongest = max((e for e in catg["actuator"] if e["specs"].get("peak_torque_Nm")), key=lambda e: e["specs"]["peak_torque_Nm"])
    for jt in R.JOINT_TYPES:
        tq, sp = d.req(f"{jt}_peak_torque"), d.req(f"{jt}_peak_speed")
        comps.append(common.catalog_component(
            f"act_{jt}", f"actuator_{jt}", 2, catg["actuator"],
            [sel.Need(tq["id"], "peak_torque_Nm", tq["required"], "N*m"), sel.Need(sp["id"], "noload_speed_rad_s", sp["required"], "rad/s")],
            placeholder_mass_each=strongest["mass_kg"],
            placeholder_note=f"Mass {strongest['mass_kg']:g} kg each is a stand-in: the mass of the strongest cataloged actuator ({strongest['name']}), flagged estimate.",
            unmet_note=(f"No cataloged actuator offers both {tq['required']:.0f} N*m peak torque and {sp['required']:.1f} rad/s speed "
                        "(speed compared with the vendor's no-load speed, which is optimistic at peak torque). Needs a custom/sourced actuator.")))
    bat = d.req("battery_energy")
    comps.append(common.catalog_component(
        "battery", "battery", 1, catg["battery"], [], placeholder_mass_each=BATTERY_PLACEHOLDER_KG,
        unmet_note=f"Required energy {bat['required']:.1f} Wh for {R.BATTERY_JUMPS} jumps; no battery with a read datasheet is in the catalog.",
        placeholder_note=f"Mass {BATTERY_PLACEHOLDER_KG:g} kg is a flagged placeholder estimate."))
    knee_tq = d.req("knee_peak_torque")["required"]
    sl = parts.size_shank_link(knee_tq, 300.0, 40.0, 30.0, 2.0)
    cadref = stl = step = None
    note = sl["note"]
    if cad_dir is not None:
        w = cad.write_part("shank_link", sl["params"], cad_dir, "shank_link")
        stl, step = w["stl"], w["step"]
        cadref = dict(stl=stl, step=step)
        if step is None:
            note += " STEP export unavailable (CAD kernel: trimesh primitives, STL only)."
    custom_parts = [dict(id="shank_link", name="Shank link (hollow rectangular tube, knee to ankle)", params=sl["params"], material=sl["material"],
                         mass_kg=sl["mass_kg"], quantity=2, cad_stl=stl, cad_step=step, load_case=sl["load_case"], check=sl["check"],
                         extra_checks=sl["extra_checks"], note=note)]
    comps.append(dict(id="shank_link", role="custom_part", quantity=2, choice=None, meets=[], ok=False, alternatives=[], custom=True, needs_sourcing=False,
                      mass_kg_each=sl["mass_kg"], mass_source="cad", note="Parametric link sized for the knee design torque (simplified model, needs FEA).", cad=cadref))
    tot = common.mass_totals(comps)
    return dict(requirements=d.requirements, components=comps, custom_parts=custom_parts, extras=ex, **tot)
