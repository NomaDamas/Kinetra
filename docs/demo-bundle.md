# Demo bundle contract (engine -> web)

The web app is static: it reads precomputed bundles from `apps/web/public/demo/`. Engine scripts
(`packages/engine/scripts/build_*_bundle.py`) write them. All JSON validates against `schemas/*.schema.json`
where a schema exists. Quaternions are `[w,x,y,z]` (MuJoCo); Z-up (web converts).

```
public/demo/index.json
  { "scenarios":[{"id","title","idea","template","tagline","tier":1|2,"hero":bool}],
    "autoresearch": {"attitude_ledger":"autoresearch/ledger.json","calibration":"autoresearch/calibration.json",
                     "integration":"autoresearch/integration.json","excitation":"autoresearch/excitation.json"} }
public/demo/<id>/scenario.json
  { "id","idea","template",
    "agent_steps":[{"id","label","tool","status":"done","wall_seconds":float,"summary":str,"detail":any}],
         # real log of the pipeline run: research -> assumptions -> build_model -> necessary_screen -> search -> monte_carlo -> robustify -> bom
    "spec": SpecSheet,
    "control": {"key": assumption key being swept, "label","unit","values":[...],"default_index":int,"hint":str},
    "variants":[{"value":float, "verdict": Verdict, "trajectory": "traj_<k>.json", "headline": str}] # one per control value, ascending
  }
public/demo/<id>/traj_<k>.json   # schema Trajectory (replayable without MuJoCo)
public/assets/<model>/...        # optional GLB meshes referenced by Geom.mesh
```
Rules: every variant has a real Verdict from a real run (seeded). At least one variant is not FEASIBLE_FOUND and at
least one is FEASIBLE_FOUND (the fail -> fix demo moment). `Verdict.suggested_fix` on a failing variant is produced by
the optimizer/sweep (smallest control value whose variant is feasible), with `verified=true` only if that variant's
Monte-Carlo p_success was actually computed. `headline` is generated from Verdict fields by code, not by an LLM.
