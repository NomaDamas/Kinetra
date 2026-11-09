# 모두의 물리 실험실 (Physical Feasibility Harness)

Type one sentence of a wild physical idea ("Tesla Roadster does a rocket-thruster aerial flip").
An agent researches specs; a verified template builds a MuJoCo model; CMA-ES searches a low-dim
control/design parameterization via MuJoCo rollouts; Monte-Carlo over uncertain assumptions gives a
feasibility probability with CI. A human reviews the assumptions panel. Three.js replays trajectories.

Physics = MuJoCo (the judge). Visuals = Three.js (the actor). All numbers come from tools/simulation, never an LLM.

Verdict asymmetry: "solution found" = strong evidence (within model assumptions); "necessary condition
violated" (energy, static torque, impulse) = strong "impossible"; "not found in N evals" = WEAK, worded as such.
Runs are deterministic (fixed seeds). Simplified CFD/thermal/FEA submodels carry "simplified model, needs precise validation".

## Layout
- `schemas/` generated JSON Schemas + `types.ts` (SpecSheet, Trajectory, Verdict)
- `packages/core/` Python package `physlab_core` (Pydantic v2 contracts, export scripts)
- `docs/schemas.md` contracts with illustrative Roadster examples; `docs/judgment-spec.md` judgment rules
- `spikes/` Go/No-Go spikes (`roadster/`, `humanoid_jump/`), each with its own `.venv`

## Run
```
uv run python packages/core/scripts/export_schemas.py     # -> schemas/*.schema.json, schemas/types.ts
uv run python packages/core/scripts/validate_examples.py  # validates docs/schemas.md examples
```
After editing `schemas.py`, re-run the export and commit the regenerated files.
