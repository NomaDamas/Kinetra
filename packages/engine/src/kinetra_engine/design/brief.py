"""Assemble the DesignBrief dict (risks, next tests, headline, totals) and write exports (design-brief.md, bom.csv)."""
from __future__ import annotations

import csv
import io
from typing import Any

from physlab_core.schemas import DesignBrief

from . import common

ROCKET_RISKS = [
    ("Per-nozzle thrust of the real hardware is unknown; the whole design scales with this swept assumption.", "high",
     "Static thrust-stand test of one candidate nozzle + valve at the working pressure.", "thruster_force_max (no official figure)"),
    ("Blow-down cooling and pressure droop are not modelled: thrust and Isp fall as the tank empties and the gas cools.", "high",
     "Instrumented full-tank blow-down test measuring thrust vs time.", "Thermal/blow-down effects not modelled; constant-Isp thrust"),
    ("Isp (70 s) is an unverified assumption and sets the propellant and tank size.", "med",
     "Measure Isp (thrust / mass flow) on the thrust stand.", "isp (unverified)"),
    ("The landing contact load comes from a rigid-body contact model without suspension compliance (tens of g); bracket and cradle strength were checked only with hand calculations.", "high",
     "FEA of brackets/cradle + drop test of the suspension and mounts at the measured peak contact load.", "Structural strength not analysed (no FEA)"),
    ("Aerodynamic pitching moments in flight are not simulated.", "med", "Wind-tunnel or coast-down test with a scale model / instrumented run.", "Aerodynamics not simulated"),
    ("Real sensing/latency/valve response is not modelled; the controller is open-loop timing windows.", "med",
     "Hardware-in-the-loop test of the valve timing and IMU latency.", "Perfect state feedback assumed"),
    ("Placeholder masses (nozzles, valves, regulator) are not sourced; the closed loop uses them.", "med",
     "Weigh candidate parts and re-run the loop with measured masses.", "placeholder masses flagged estimate"),
]
ROCKET_TESTS = [
    ("Static nozzle thrust-stand test", "Confirm per-nozzle thrust, mass flow and Isp at working pressure", "static_fire_test: no sourced per-test cost"),
    ("Tank blow-down test", "Measure pressure/temperature/thrust decay vs time for the chosen cylinder set", ""),
    ("Bracket and cradle FEA + proof load", "Replace the hand-calc checks with a load test at the measured landing load", ""),
    ("Suspension drop test", "Validate the simulated touchdown contact load", "drop_test_rig_run: no sourced per-test cost"),
]
HUMANOID_RISKS = [
    ("Joint speed is compared with the vendor no-load speed, which overstates speed at peak torque.", "high",
     "Dynamometer test of the chosen actuator at the jump's torque-speed point.", "no torque-speed curves read from vendors"),
    ("Thermal limits: peak torque is a short-duration vendor figure; repeated jumps heat the motors.", "high",
     "Repeated-jump thermal soak test with motor temperature logging.", "Thermal effects not modelled"),
    ("The landing GRF limit is an unverified default (no hardware source).", "high",
     "Drop test of the leg assembly instrumented with a force plate.", "landing_grf_limit_bw (unverified default)"),
    ("Structural strength of links/mounts is a hand calculation only.", "med", "FEA + proof load of the shank link.", "Structural strength not analysed (no FEA)"),
    ("Sensing and actuator latency are not modelled (perfect state feedback).", "med", "Hardware-in-the-loop test with real encoder/command latency.", "Perfect state feedback assumed"),
    ("Mass of the selected actuators is added on top of the G1 model mass (no sourced per-joint G1 actuator mass to subtract); the battery mass is a placeholder.", "med",
     "Weigh the real assembly and re-run the loop.", "placeholder/unsubtracted masses"),
]
HUMANOID_TESTS = [
    ("Actuator dynamometer test", "Measure peak torque at the jump speed and temperature rise per jump", ""),
    ("Single-leg drop test on a force plate", "Validate landing GRF and the leg's structural margin", "drop_test_rig_run: no sourced per-test cost"),
    ("Instrumented repeated-jump test", "Battery energy per jump and motor temperature over N jumps", ""),
]


def headline(template: str, base_value: float, control_label: str, unit: str, iters: list[dict[str, Any]], mass_added: float, n_ok: int, n_comp: int,
             n_custom_parts: int, n_sourcing: int) -> str:
    it0, itl = iters[0], iters[-1]
    drop = f"p_success {100 * it0['p_success']:.0f}% -> {100 * itl['p_success']:.0f}% after adding the designed hardware"
    if itl["status"] == "NOT_FOUND_IN_BUDGET":
        drop = "no witness found in the search budget once the designed hardware mass is added (WEAK evidence: not proof the design fails)"
    elif itl["status"] != "FEASIBLE_FOUND":
        drop = f"verdict after adding the designed hardware: {itl['status']}"
    return (f"{control_label} {base_value:g} {unit}: +{mass_added:.1f} kg of designed hardware ({n_ok}/{n_comp} lines met by catalog parts, "
            f"{n_custom_parts} custom part types, {n_sourcing} needing sourcing); {drop}.")


def build(*, scenario_id, template, base_variant, headline_text, derived, closed_rows, alternatives, risks, tests, labels, repro) -> dict[str, Any]:
    comps = derived["components"]
    unpriced = common.count_unpriced(comps)
    priced = [c for c in comps if c["choice"] is not None and c["choice"].get("unit_cost_usd") is not None]
    cost = sum(c["choice"]["unit_cost_usd"] * c["quantity"] for c in priced) if priced else None
    brief = dict(scenario_id=scenario_id, template=template, base_variant=float(base_variant), headline=headline_text,
                 requirements=derived["requirements"], components=comps, custom_parts=derived["custom_parts"], closed_loop=closed_rows,
                 alternatives=alternatives,
                 risks=[dict(text=t, severity=s, physical_test=p, tied_to=w) for t, s, p, w in risks],
                 next_tests=[dict(name=n, purpose=p, cost=None, source=src) for n, p, src in tests],
                 totals=dict(mass_added_kg=derived["mass_added_kg"], mass_estimated_kg=derived["mass_estimated_kg"], cost_priced_usd=cost, unpriced_lines=unpriced),
                 labels=labels, reproducibility=repro)
    return DesignBrief.model_validate(brief).model_dump(mode="json")


# --------------------------------------------------------------------------- exports
def _g(x: float) -> str:
    return f"{x:.4g}"


def bom_csv(b: dict[str, Any]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["line", "role", "quantity", "item", "vendor", "mass_kg_each", "mass_source", "unit_cost_usd", "status", "verified_specs", "source"])
    cps = {p["id"]: p for p in b["custom_parts"]}
    for c in b["components"]:
        ch = c["choice"]
        if ch:
            item, vendor, cost, ver, src = ch["name"], ch["vendor"], ch["unit_cost_usd"], ch["verified"], ch["source"]
            status = "catalog, meets all requirements" if c["ok"] else "catalog, DOES NOT meet all requirements"
        elif c["custom"]:
            item, vendor, cost, ver, src = cps[c["id"]]["name"] if c["id"] in cps else c["id"], "custom (CAD in export)", None, "", ""
            status = "custom part (6061-T6), simplified model, needs FEA"
        else:
            item, vendor, cost, ver, src = "(needs sourcing)", "", None, "", ""
            status = "needs sourcing"
        m = c.get("mass_kg_each")
        w.writerow([c["id"], c["role"], c["quantity"], item, vendor, "" if m is None else _g(m), c.get("mass_source", ""), "" if cost is None else cost,
                    status, "" if ver == "" else str(ver).lower(), src])
    w.writerow([])
    t = b["totals"]
    w.writerow(["TOTAL", "", "", "", "", _g(t["mass_added_kg"]), f"of which unsourced estimate: {_g(t['mass_estimated_kg'])} kg",
                "" if t["cost_priced_usd"] is None else t["cost_priced_usd"], f"{t['unpriced_lines']} unpriced lines (not counted as zero)", "", ""])
    return out.getvalue()


def brief_md(b: dict[str, Any]) -> str:
    L: list[str] = []
    A = L.append
    A(f"# Design brief — {b['scenario_id']} ({b['template']})")
    A("")
    A(f"> {b['headline']}")
    A("")
    A("Generated by code from `design.json`; every number comes from MuJoCo rollouts, the Monte-Carlo sampler, cited catalog entries or is labelled "
      "`default` / `estimate` / `unverified`.")
    A("")
    A("**Model limits**")
    A("")
    for x in dict.fromkeys(b["labels"]):  # de-duplicate, keep order
        A(f"- {x}")
    A("")
    A(f"## Requirements (derived from the {b['base_variant']:g} variant's witness)")
    A("")
    A("| requirement | measured | margin | required | source |")
    A("|---|---|---|---|---|")
    for r in b["requirements"]:
        A(f"| {r['label']} | {_g(r['value'])} {r['unit']} | x{r['margin_factor']:g} | {_g(r['required'])} {r['unit']} | {r['source']} |")
    A("")
    A("## Components")
    A("")
    A("| line | qty | choice | verified | provided vs required | mass each | status |")
    A("|---|---|---|---|---|---|---|")
    for c in b["components"]:
        ch = c["choice"]
        name = ch["name"] if ch else ("custom part" if c["custom"] else "needs sourcing")
        pv = "; ".join(f"{m['requirement_id']}: {_g(m['provided'])} vs {_g(m['required'])} {m['unit']}" for m in c["meets"]) or "—"
        m = c.get("mass_kg_each")
        mass = "—" if m is None else f"{_g(m)} kg ({c.get('mass_source')})"
        status = "OK" if c["ok"] else ("custom" if c["custom"] else "needs sourcing")
        A(f"| {c['id']} | {c['quantity']} | {name} | {'yes' if ch and ch['verified'] else '—'} | {pv} | {mass} | {status} |")
    A("")
    if b["custom_parts"]:
        A("## Custom parts (simplified model, needs FEA)")
        A("")
        for p in b["custom_parts"]:
            ck = p["check"]
            A(f"- **{p['name']}** x{p['quantity']} — {p['material']}, {_g(p['mass_kg'])} kg each, params {p['params']}; load case {p['load_case']}. "
              f"{ck['method']}: {_g(ck['stress_MPa'])} MPa vs allowable {_g(ck['allow_MPa'])} MPa -> {'OK' if ck['ok'] else 'FAIL'}. CAD: `{p['cad_stl']}`"
              + (f", `{p['cad_step']}`" if p["cad_step"] else " (no STEP: STL only)"))
        A("")
    A("## Closed loop: designed hardware mass fed back into the simulation")
    A("")
    A("| iteration | mass | verdict | p_success (95% CI) | n | note |")
    A("|---|---|---|---|---|---|")
    for i in b["closed_loop"]:
        A(f"| {i['iteration']} | {_g(i['mass_kg'])} kg | {i['status']} | {100 * i['p_success']:.1f}% ({100 * i['ci'][0]:.1f}–{100 * i['ci'][1]:.1f}%) | {i['n']} | {i['note']} |")
    A("")
    if b["alternatives"]:
        A("## Alternatives (same verdict machinery)")
        A("")
        A("| option | verdict | p_success | mass added | note |")
        A("|---|---|---|---|---|")
        for a in b["alternatives"]:
            A(f"| {a['label']}{' **(recommended)**' if a['recommended'] else ''} | {a['status']} | {100 * a['p_success']:.1f}% | +{_g(a['mass_added_kg'])} kg | {a['note']} |")
        A("")
    A("## Risks")
    A("")
    for r in b["risks"]:
        A(f"- **{r['severity']}** — {r['text']} Test: {r['physical_test']} _(tied to: {r['tied_to']})_")
    A("")
    A("## Next physical tests")
    A("")
    for t in b["next_tests"]:
        A(f"- **{t['name']}** — {t['purpose']}" + (f" ({t['source']})" if t["source"] else ""))
    A("")
    t = b["totals"]
    A(f"## Totals\n\nAdded mass {_g(t['mass_added_kg'])} kg (of which {_g(t['mass_estimated_kg'])} kg unsourced estimates); priced cost: "
      + ("none cited" if t["cost_priced_usd"] is None else f"${t['cost_priced_usd']:,.0f}") + f"; {t['unpriced_lines']} lines have no cited unit cost (not counted as zero).")
    r = b["reproducibility"]
    A(f"\n_Seed {r['seed']}, {r['engine']}, MuJoCo {r['mujoco']}, generated {r['generated_at']}._")
    return "\n".join(L) + "\n"
