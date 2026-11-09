# Contracts: SpecSheet / Trajectory / Verdict

Source of truth: `packages/core/src/physlab_core/schemas.py` (Pydantic v2).
Generated: `schemas/*.schema.json`, `schemas/types.ts` (`uv run python packages/core/scripts/export_schemas.py`).
Examples below are validated by `packages/core/scripts/validate_examples.py`.

**All numbers in the examples are ILLUSTRATIVE** (Roadster rocket-thruster aerial maneuver; the shipped template now asks for a full roll AND pitch rotation). They are not simulation output.

Conventions: SI units; MuJoCo world frame (+Z up); quaternions `[w, x, y, z]` (Three.js wants `[x, y, z, w]` — reorder in the viewer);
`pos[frame][body]` / `quat[frame][body]` index bodies in the order of `bodies`.

TypeScript note: `types.ts` describes the fully-populated form Python *emits* (defaulted fields are required).
JSON Schema files describe what the validator *accepts* (defaulted fields optional). A TS producer should fill every field.

Verdict asymmetry is enforced by the model: `INFEASIBLE_NECESSARY_CONDITION` requires a failed `necessary_check`;
`FEASIBLE_FOUND` requires `best_params` and forbids failed checks; `NOT_FOUND_IN_BUDGET` is weak evidence only.

## SpecSheet

<!-- example: spec_sheet -->
```json
{
  "schema_version": "0.1.0",
  "idea": "Tesla Roadster does a rocket-thruster aerial flip",
  "template_id": "rocket_car",
  "tier": 1,
  "assumptions": [
    {"key": "vehicle_mass", "label": "Vehicle mass", "value": 1800.0, "unit": "kg",
     "distribution": {"kind": "normal", "mean": 1800.0, "std": 40.0, "clip_low": null, "clip_high": null},
     "source": "llm_estimate", "confidence": "med", "editable": true},
    {"key": "pitch_inertia", "label": "Pitch moment of inertia (about CoM)", "value": 2900.0, "unit": "kg*m^2",
     "distribution": {"kind": "uniform", "low": 2400.0, "high": 3400.0},
     "source": "llm_estimate", "confidence": "low", "editable": true},
    {"key": "thruster_force_max", "label": "Max thrust per nozzle", "value": 12000.0, "unit": "N",
     "distribution": {"kind": "fixed"},
     "source": "user", "confidence": "high", "editable": true},
    {"key": "thruster_burn_time", "label": "Available burn time", "value": 3.0, "unit": "s",
     "distribution": {"kind": "fixed"},
     "source": "llm_estimate", "confidence": "low", "editable": true},
    {"key": "ramp_speed", "label": "Launch speed at ramp", "value": 25.0, "unit": "m/s",
     "distribution": {"kind": "uniform", "low": 20.0, "high": 30.0},
     "source": "user", "confidence": "med", "editable": true}
  ],
  "parts": [
    {"name": "Cold-gas thruster module", "role": "thruster", "mass_kg": 45.0, "cost_usd": 18000.0, "source": "llm_estimate"},
    {"name": "Composite gas tank 300 bar", "role": "propellant_tank", "mass_kg": 30.0, "cost_usd": 6000.0, "source": "llm_estimate"}
  ],
  "param_bounds": [
    {"name": "thruster_offset_x", "low": -2.0, "high": 2.0, "unit": "m", "init": 0.0, "description": "Nozzle position along car x-axis from CoM"},
    {"name": "ignition_time", "low": 0.0, "high": 1.5, "unit": "s", "init": 0.3, "description": "Time after ramp exit"},
    {"name": "thrust_fraction", "low": 0.0, "high": 1.0, "unit": "", "init": 0.5, "description": "Fraction of thruster_force_max"}
  ],
  "success_criteria": [
    {"name": "full_flip", "metric": "rotation_deg", "comparator": ">=", "threshold": 360.0, "unit": "deg", "description": "Pitch rotation completed"},
    {"name": "safe_landing", "metric": "landing_tilt_deg", "comparator": "<=", "threshold": 15.0, "unit": "deg", "description": "Wheels-down within 15 deg"}
  ]
}
```

## Trajectory

Truncated to 4 frames for the doc; real ones have hundreds.

<!-- example: trajectory -->
```json
{
  "schema_version": "0.1.0",
  "model_id": "rocket_car_v1",
  "model_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "dt": 0.5,
  "bodies": [
    {"name": "chassis", "parent": null,
     "geoms": [{"type": "box", "size": [2.1, 0.9, 0.6], "pos": [0, 0, 0], "quat": [1, 0, 0, 0], "rgba": [0.8, 0.1, 0.1, 1.0], "mesh": null}]},
    {"name": "thruster", "parent": "chassis",
     "geoms": [{"type": "cylinder", "size": [0.12, 0.25], "pos": [-2.0, 0, 0], "quat": [0.7071068, 0, 0.7071068, 0], "rgba": [0.3, 0.3, 0.3, 1.0], "mesh": null}]}
  ],
  "pos": [
    [[0.0, 0.0, 1.0], [-2.0, 0.0, 1.0]],
    [[12.5, 0.0, 4.2], [10.5, 0.0, 4.2]],
    [[25.0, 0.0, 5.8], [23.0, 0.0, 5.8]],
    [[37.5, 0.0, 1.0], [35.5, 0.0, 1.0]]
  ],
  "quat": [
    [[1, 0, 0, 0], [1, 0, 0, 0]],
    [[0.7071068, 0, 0.7071068, 0], [0.7071068, 0, 0.7071068, 0]],
    [[0, 0, 1, 0], [0, 0, 1, 0]],
    [[0.7071068, 0, -0.7071068, 0], [0.7071068, 0, -0.7071068, 0]]
  ],
  "events": [
    {"t": 0.3, "kind": "thrust", "body": "thruster", "other": null, "pos": [-2.0, 0.0, 2.0], "force": [0.0, 0.0, 9000.0], "magnitude": 9000.0, "note": "ignition"},
    {"t": 1.5, "kind": "landing", "body": "chassis", "other": null, "pos": [37.5, 0.0, 0.6], "force": [0.0, 0.0, 41000.0], "magnitude": 41000.0, "note": "touchdown (illustrative)"}
  ],
  "series": [
    {"name": "thrust_N", "unit": "N", "values": [0.0, 9000.0, 9000.0, 0.0]},
    {"name": "pitch_deg", "unit": "deg", "values": [0.0, 90.0, 180.0, 270.0]}
  ],
  "meta": {"seed": 42, "mujoco_version": "3.2.0", "template_id": "rocket_car",
           "params": {"thruster_offset_x": -2.0, "ignition_time": 0.3, "thrust_fraction": 0.75}, "note": "illustrative"}
}
```

## Verdict

<!-- example: verdict -->
```json
{
  "schema_version": "0.1.0",
  "status": "FEASIBLE_FOUND",
  "summary": "A parameter set achieving a full flip and safe landing was found; it succeeds in 62% of sampled assumption sets (illustrative).",
  "feasibility": {"p_success": 0.62, "ci_low": 0.58, "ci_high": 0.66, "n_samples": 800, "ci_method": "wilson_95"},
  "necessary_checks": [
    {"name": "energy_budget", "passed": true, "measured": 190000.0, "limit": 520000.0, "unit": "J", "note": "rotational KE needed vs thruster work available"},
    {"name": "static_torque_saturation", "passed": true, "measured": 24000.0, "limit": 46000.0, "unit": "N*m", "note": "mj_inverse torque at max pitch rate"},
    {"name": "impulse", "passed": true, "measured": 31000.0, "limit": 36000.0, "unit": "N*s", "note": "angular impulse required vs available"}
  ],
  "binding_constraint": {
    "name": "burn_time", "margin": 0.4, "unit": "s",
    "sensitivities": [
      {"assumption_key": "pitch_inertia", "effect": -0.21, "rank": 1, "method": "one_at_a_time"},
      {"assumption_key": "ramp_speed", "effect": 0.12, "rank": 2, "method": "one_at_a_time"},
      {"assumption_key": "vehicle_mass", "effect": -0.05, "rank": 3, "method": "one_at_a_time"}
    ]
  },
  "best_params": {"thruster_offset_x": -1.8, "ignition_time": 0.35, "thrust_fraction": 0.78},
  "suggested_fix": {
    "changes": [{"param": "thruster_burn_time", "from_value": 3.0, "to_value": 3.6, "unit": "s"}],
    "rationale": "Optimizer raised p_success from 0.62 to 0.91 by extending burn time 3.0 -> 3.6 s (illustrative).",
    "verified": true,
    "verified_p_success": 0.91
  },
  "bom": [
    {"name": "Cold-gas thruster module", "role": "thruster", "quantity": 2, "mass_kg": 45.0, "unit_cost_usd": 18000.0, "source": "llm_estimate"},
    {"name": "Composite gas tank 300 bar", "role": "propellant_tank", "quantity": 1, "mass_kg": 30.0, "unit_cost_usd": 6000.0, "source": "llm_estimate"}
  ],
  "cost_estimate": {
    "sim_cost": {"n_evals": 2800, "wall_seconds": 95.0},
    "physical_equivalent_estimate": {"is_estimate": true, "low_usd": 150000.0, "high_usd": 600000.0,
                                     "basis": "Order-of-magnitude: stunt-vehicle rig + thruster hardware + test days (ESTIMATE)",
                                     "sources": ["llm_estimate"]}
  },
  "model_labels": ["simplified model, needs precise validation"],
  "human_review": {"required": true, "items": [
    {"assumption_key": "pitch_inertia", "reason": "Low-confidence LLM estimate; dominant sensitivity.", "severity": "warn"}
  ]},
  "reproducibility": {"seed": 42, "versions": {"mujoco": "3.2.0", "cma": "3.3.0", "physlab_core": "0.1.0"},
                      "search_budget": {"cma_evals": 2000, "mc_samples": 800}, "spec_hash": null},
  "trajectory_ref": "out/roadster_flip/best.trajectory.json"
}
```
