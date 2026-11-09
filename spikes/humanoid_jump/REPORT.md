# Humanoid jump spike — Go/No-Go report

**Verdict: GO for "dynamic jump + landing is feasible with ≤10 params, CMA-ES, no RL".**
Unitree G1 (33.3 kg), 10 parameters, ~6 000 rollouts (~1 min wall on 10 cores) reach **0.2 m, 0.3 m, 0.4 m and 0.5 m** ballistic jump heights with a stable landing, deterministically. The static-torque screen also works and gives a clean controller-independent verdict. Caveats at the bottom (the COM-rise metric can be cheated; the torque-ratio number needs care).

## Setup (what was actually used)
- Model: **Unitree G1 29-DoF, MuJoCo Menagerie** (shallow sparse clone in `vendor/mujoco_menagerie/`, ~81 MB, gitignored). License: **BSD-3-Clause** (Unitree Robotics, `vendor/.../unitree_g1/LICENSE`). H1 not needed.
- Actuators: **position actuators** (`kp=500`, `kv`=dampratio 1), all `ctrllimited` + **`forcelimited`**. Forcerange (N·m): hip pitch/yaw ±88, hip roll ±139, **knee ±139**, **ankle pitch/roll ±50**, waist 88/50/50, arms ±25, wrists ±25/5. So actuator saturation is real in MuJoCo (force is clipped to forcerange), jumps cannot cheat the limits.
- Total mass 33.34 kg. Timestep 0.002 s. One rollout ≈ 0.07 s (single core, 1–3 s sim).

## Parameterization (10 params, `jump.py`)
`[crouch_hip, crouch_knee, take_hip, take_knee, air_hip, air_knee, land_hip, land_knee, T_down, T_push]`
- Left/right legs identical (sagittal symmetric); ankle pitch is *derived* (`ankle = -(hip+knee)`, sole stays parallel to floor); all other joints held at the keyframe default via the same PD.
- Phases: settle 0.3 s → min-jerk down to crouch (`T_down`) → min-jerk push to takeoff pose (`T_push`) → on loss of foot contact blend (0.15 s) to flight pose → when COM vz<0 blend to landing pose → hold landing pose 1 s. Event-driven (liftoff/apex detected from contacts/COM velocity), so only 2 timing params.
- No RL, no learned anything; CMA-ES (`cma` 4.5, popsize 20, bounds [0,1] normalized, fixed seed, sigma0 0.3), cost = 100·(shortfall to target)² + penalties (no liftoff 10, no landing 5, unstable landing 3+tilt) + 0.02·landing GRF/BW.
- Judge outputs per rollout: jump height, per-joint torque ratios, landing peak vertical GRF, fall flag (torso up-axis z ≥ 0.8, pelvis z > 0.35 m at end, no non-foot geom touching floor).

## Results (all seeds fixed; `out/best_*.json`)
Two seeds each, 6 000 evals, 10 procs. "ballistic" = vz_liftoff²/2g (honest height); "COM rise" = apex COM − COM at liftoff (inflated if legs tuck after liftoff).

| target | seed | evals | wall | ballistic h | COM rise | landing peak GRF (N / ×BW) | stable |
|---|---|---|---|---|---|---|---|
| 0.2 | 1 | 6000 | 60 s | 0.189 | 0.198 | 1248 / 3.8 | yes |
| 0.2 | 2 | 6000 | 56 s | 0.238 | 0.235 | 2677 / 8.2 | yes |
| 0.3 | 1 | 6000 | 61 s | 0.290 | 0.288 | 1923 / 5.9 | yes |
| 0.3 | 2 | 6000 | 56 s | 0.351 | 0.347 | 2436 / 7.4 | yes |
| 0.4 | 1 | 6000 | 51 s | 0.402 | 0.392 | 3024 / 9.2 | yes |
| 0.4 | 2 | 6000 | 64 s | 0.549 | 0.543 | 3054 / 9.3 | yes |
| 0.5 | 1 | 6000 | 78 s | 0.527 | 0.517 | 2342 / 7.2 | yes |
| 0.5 | 2 | 6000 | 69 s | 0.439 | 0.541 | 3014 / 9.2 | yes |
| 0.7 | 1 | 4000 | 49 s | **0.399** | 0.682 | 4579 / 14.0 | yes |
| 1.0 | 1 | 4000 | 36 s | **0.484** | 0.958 | 3468 / 10.6 | **no (falls)** |

(Even the 1-seed 1 000-eval run found a 0.17 m stable jump in 11.6 s.) So the honest ceiling with this parameterization is ≈0.5 m ballistic; the 0.7 / 1.0 m targets were "achieved" only by leg-tuck COM inflation → this is the "no solution found" regime (weak evidence, should be reported as such, not as impossible). Re-running `rollout` with the same params gives bit-identical results (checked).

**Max joint torque.** Applied/forcerange max = 1.00 on the knee in every successful jump (the knee saturates for 1.4–3 % of steps at the 0.2/0.4 m solutions) — jumps are genuinely actuator-limited and still feasible. The "demand ratio" (PD-law output before clip ÷ forcerange, `torque_demand_ratio_max`) is 2.4 (0.2 m) … 5–12 (0.4–0.5 m), [INFERENCE: mostly ankle PD target mismatch, not checked]; it is a *saturation indicator*, not a required-torque estimate. Do not report it as "needed torque".

**Feasibility boundary experiments (`sweep.sh`, `out/sweep_log.txt`, 4 000 evals each, seed 1):**
| target | torque scale | payload | result |
|---|---|---|---|
| 0.2 | 1.0 / 0.7 / 0.5 | 0 | stable, ballistic 0.19 / 0.24 / 0.17 |
| 0.2 | **0.35** | 0 | **not reached: 0.094 m ballistic** (cost 0.74) |
| 0.2 | 1.0 | +5 kg torso | stable, 0.26 m (op. found a better one) |
| 0.4 | 1.0 | +5 kg torso | stable, 0.40 m |
| 0.4 | **0.5** | 0 | **not reached: 0.20 m ballistic, falls** |
So scaling forcerange down produces the expected infeasibility — the limit comes from real actuator limits — and it is detectable within ~1 min / 4 000 evals. Note this is *failure to find*, i.e. weak evidence.

## Static screen (`static_screen.py`, `out/static_screen.json`)
Controller-independent. At a given crouch pose, COM placed over the feet (ideal CoP), support force = weight split over both feet, `mj_inverse` with contacts disabled and the support wrench as `qfrc_applied`, then subtract the support wrench → joint torques to hold at qacc=0 (root residual < 0.3 N·m, i.e. valid). Runs in ~0.1 s. Payload = extra mass on torso_link. Worst-joint ratio = |τ|/forcerange (knee binds in all deep crouches):

| crouch (hip, knee) | 0 kg | 5 kg | 20 kg | 40 kg | 80 kg |
|---|---|---|---|---|---|
| (-0.3, 0.6) | 0.08 | 0.10 | 0.15 | 0.22 | 0.37 |
| (-0.8, 1.5) | 0.20 | 0.25 | 0.37 | 0.55 | 0.89 |
| (-1.2, 2.0) | 0.27 | 0.32 | 0.49 | 0.71 | **1.16** |
| (-1.5, 2.5) | 0.29 | 0.35 | 0.52 | 0.76 | **1.24** |
Example: crouch (-0.8, 1.5), 5 kg payload: knee 34.2/139 N·m (margin 4.1×), ankle 0.5/50. Fallback verdict works: "static hold of deep crouch with 80 kg payload violates knee forcerange (172 N·m > 139)" is a strong necessary-condition-style "impossible"; "ratio < 1" is only a necessary condition, not proof of a jump (a jump needs far more than the static hold: the dynamic result above shows the knee saturated at the push-off).

## Time / effort
- Setup (clone, venv, model inspection, kinematic sign probe): ~10 min. Controller + first working jump: ~15 min. Static screen incl. two bug fixes (support wrench; `mj_setConst` after payload mass change, otherwise subtreemass/gravity compensation is wrong): ~10 min. Sweeps: ~20 min wall (machine was heavily loaded, load avg 40–66, so these timings are pessimistic).
- Total hands-on ≈ 1 h; well inside the "2 h-equivalent" budget. One optimization = 4–6 k rollouts ≈ 1 min on 10 cores (≈ 7 min single core).

## What failed / caveats
- First guess params (`P0`) falls over (torso tilt 60°, 6.8×BW landing). CMA-ES fixes it within a few hundred evals.
- **Metric hazard:** apex COM − COM(liftoff) can be inflated by tucking legs in flight; the optimizer exploited it for targets 0.7/1.0 (COM rise 0.68/0.96, ballistic 0.40/0.48). Use ballistic height (vz at liftoff) or pelvis/COM absolute apex minus *standing* COM for the product.
- Seeds differ a lot in *landing GRF* (3.8× to 9.3× BW at the same 0.2 m target) because cost only weakly penalizes impact; if GRF is part of the verdict it must be a constraint, not a weight. GRF is vertical sum of foot-sphere contact forces from `mj_contactForce` at 500 Hz; contact solver is MuJoCo-default soft contact (no calibration of peak GRF against real data → label "simplified, needs validation").
- Foot–floor friction left at model default (not inspected); no ankle-roll/lateral dynamics exercised (sagittal-symmetric only), no upper-body compensation (arms fixed), so these jumps are not "natural" looking.
- Optimization not seeded-robust in the sense that two seeds give different parameter sets; same seed ⇒ identical result.
- Not tried: soccer kick, H1, Monte-Carlo over mass/friction (cheap to add: `Sim(payload=…, torque_scale=…)` already exposes it).

## Recommendation (jump vs kick hero demo)
Jump is the safer hero demo **for this model**: single-contact-sequence, 10 params, ~1 min to a verdict, and the feasibility boundary is visible and controllable (torque scale 0.35→0.2 m infeasible; payload/height sliders change the verdict), the static screen complements it, and the trajectory replays directly. A kick adds balance on one foot, a ball contact model and impact-impulse sensitivity — more fragile. Hero demo suggestion: "humanoid jumps 0.4 m, stable; with torque ×0.5 can't; with 80 kg payload static crouch violates knee limit". Report "found" as strong, "not found in N evals" as weak, and the static-torque violation as strong impossible.

## Reproduce
```bash
cd spikes/humanoid_jump
git clone --depth 1 --filter=blob:none --sparse https://github.com/google-deepmind/mujoco_menagerie vendor/mujoco_menagerie
(cd vendor/mujoco_menagerie && git sparse-checkout set unitree_g1)
uv venv .venv && uv pip install --python .venv/bin/python mujoco cma numpy scipy
.venv/bin/python optimize.py 0.4 6000 1      # target height, evals, seed -> out/best_0.4_seed1.json (~1 min, 10 procs)
.venv/bin/python export.py out/best_0.4_seed1.json out/trajectory_0.4m.json
.venv/bin/python static_screen.py            # -> out/static_screen.json
TSCALE=0.5 PAYLOAD=5 TAG=_x .venv/bin/python optimize.py 0.4 4000 1   # boundary experiments; ./sweep.sh runs the set
```
Python 3.12 venv (uv), mujoco 4.0.0, cma 4.5.0, macOS arm64.

## Outputs
- `out/trajectory.json` — best 0.2 m run (206 frames @100 Hz, 31 bodies, per-frame `pos` xyz + `quat` wxyz for every body in `body_names`; includes params + metrics). `out/trajectory_0.4m.json` — 0.4 m run (250 frames).
- `out/best_*.json`, `out/sweep_log.txt`, `out/static_screen.json`.
- Code: `jump.py` (model+controller+judge), `optimize.py`, `static_screen.py`, `export.py`, `sweep.sh`.
