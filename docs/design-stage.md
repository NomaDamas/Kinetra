# Design stage contract (engine -> web)

The design stage turns a verdict into **something you could build**: requirements derived from the simulation,
components selected from a cited catalog (or flagged as custom), parametric custom parts with CAD, and a
**closed loop** that puts the designed hardware's mass back into the model and re-verifies. Same honesty rules as the
verdict: numbers come from simulation or cited catalog entries; anything else is labelled `default`, `unverified`
or `estimate`; simplified structural checks carry "simplified model, needs FEA".

## Files

```
apps/web/public/demo/<scenario>/design.json        # DesignBrief (below), one per scenario
apps/web/public/demo/<scenario>/cad/<part>.stl     # web preview (binary STL, <= 2 MB each)
apps/web/public/demo/<scenario>/cad/<part>.step    # for engineers (if the CAD kernel is available)
apps/web/public/demo/<scenario>/export/bom.csv
apps/web/public/demo/<scenario>/export/design-brief.md
```

Pydantic models live in `physlab_core.schemas` (`DesignBrief` and children), exported to `schemas/design_brief.schema.json`
and `schemas/types.ts` like the other contracts.

## DesignBrief

```jsonc
{
  "schema_version": "0.1.0",
  "scenario_id": "roadster",
  "template": "rocket_car",
  "base_variant": 5000,                 // control value of the variant the design is derived from (a FEASIBLE_FOUND one)
  "headline": "…",                      // generated from fields by code, never by an LLM
  "requirements": [                     // derived from the witness rollout / MC, with margin
    {"id":"nozzle_peak_thrust","label":"Peak thrust per nozzle","value":5000,"unit":"N",
     "derived_from":"max over witness schedule (traj_5000.json)","margin_factor":1.25,"required":6250,"source":"simulation"}
  ],
  "components": [                       // one line per role; selection = smallest catalog entry meeting all requirements
    {"id":"nozzle","role":"thruster","quantity":10,
     "choice":{"name":"…","vendor":"…","specs":{"thrust_N":7000},"mass_kg":1.2,"unit_cost_usd":null,
               "source":"https://…","verified":false},
     "meets":[{"requirement_id":"nozzle_peak_thrust","required":6250,"provided":7000,"unit":"N","margin":0.12,"ok":true}],
     "alternatives":[{"name":"…","why_rejected":"6 kN < 6.25 kN required"}],
     "custom":false, "cad":null}
  ],
  "custom_parts": [                     // parts no catalog entry provides: parametric geometry + simple load check
    {"id":"nozzle_bracket","name":"Nozzle mount bracket","params":{"plate_t_mm":6,"width_mm":80},
     "material":"6061-T6","mass_kg":0.31,"cad_stl":"cad/nozzle_bracket.stl","cad_step":"cad/nozzle_bracket.step",
     "load_case":{"force_N":6250,"safety_factor":2.0},
     "check":{"method":"cantilever bending, hand calc","stress_MPa":118,"allow_MPa":138,"ok":true,
              "label":"simplified model, needs FEA"}}
  ],
  "closed_loop": [                      // design -> mass -> re-simulate -> verdict; stop when mass converges
    {"iteration":0,"mass_kg":1300,"status":"FEASIBLE_FOUND","p_success":0.13,"ci":[0.11,0.17],"n":500,"note":"before design"},
    {"iteration":1,"mass_kg":1342,"status":"FEASIBLE_FOUND","p_success":0.09,"ci":[0.07,0.12],"n":500,"note":"+ tank, nozzles, brackets"}
  ],
  "alternatives": [                     // design options compared on the same verdict machinery
    {"id":"A","label":"10 × 5 kN nozzles","changes":{"thruster_force_max":5000},"status":"FEASIBLE_FOUND",
     "p_success":0.13,"mass_kg":1342,"cost_usd":null,"recommended":true,"note":"…"}
  ],
  "risks": [{"text":"Landing loads not structurally checked","severity":"high","physical_test":"drop test of the suspension"}],
  "next_tests": [{"name":"Static nozzle thrust stand test","purpose":"confirm per-nozzle thrust","cost":null,"source":""}],
  "totals": {"mass_added_kg":42.0,"cost_priced_usd":null,"unpriced_lines":4},
  "labels": ["simplified model, needs precise validation"],
  "reproducibility": {"seed":1,"engine":"kinetra_engine 0.1.0","mujoco":"4.0.0","generated_at":"…"}
}
```

Rules
- `requirements[].value` must be read from a real rollout/Monte-Carlo of the base variant; `required = value × margin_factor`.
- A component is `ok` only if every `meets[]` row is ok. If no catalog entry meets a requirement, the component is
  `custom: true` and must appear in `custom_parts` or be flagged `"needs sourcing"`; never invent a vendor part.
- `closed_loop` iterations are real re-runs of the pipeline (search + MC) with updated mass assumptions.
- Costs: only cited unit costs are summed; unpriced lines are counted, not treated as zero.
