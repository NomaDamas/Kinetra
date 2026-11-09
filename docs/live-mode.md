# Live mode (real MuJoCo on the local engine)

The web demo has two kinds of views and labels them differently:

| | **recorded run** | **LIVE: real MuJoCo on local engine** |
|---|---|---|
| source | `apps/web/public/demo/**` (seeded pipeline runs, built offline) | `packages/engine` FastAPI process steps MuJoCo *while you watch* |
| change a parameter | snaps to a precomputed variant | triggers a genuine fresh simulation |
| needs the engine | no (static site) | yes; if `GET /health` fails the Live tab is disabled with the start command |
| browser physics | none (Three.js only draws) | none (Three.js only draws; MuJoCo runs in Python, **no WASM**) |

Start both: `scripts/dev.sh` (engine on :8000 + `pnpm dev` on :5173), or only the engine:
`cd packages/engine && .venv/bin/uvicorn kinetra_engine.api:app --port 8000`.

## What is real, what is not

* **Real**: every `mj_step`; the model is compiled for exactly the assumption values of the request (thrust, mass, payload,
  friction, ...); metrics (flip error, touchdown speed, fuel, GRF, ...) are computed from that rollout by the template's own judge
  code; the CMA-ES search evaluates real `mujoco.rollout` populations; `perf` numbers are wall-clock measurements.
* **Not re-done live**: the stored schedule (`best_params` of a recorded variant) is *re-simulated under your new parameters*, it is
  not re-optimised (use *Run live search* for that). One nominal rollout is **not** the Monte-Carlo `p_success` of the recorded
  verdict (that needs hundreds of rollouts under sampled assumptions).
* **Pacing**: frames are released against the wall clock (`speed` x real time, `0` = unpaced). Physics for a chunk is executed when its
  simulated time arrives (rocket_car), so a 4.5 s flip takes ~4.5 s at speed 1 although the engine could do it in ~60 ms (see
  `perf.realtime_factor`).
* `rocket_car`: **incremental** (`start.compute == "incremental"`): the stepping loop runs inside the stream.
  `humanoid_jump`: **batch** (`"batch"`): the template's controller loop is monolithic, so the rollout is computed first
  (`compute_ms` reported) and then paced out. Live search: rocket_car only.
* Same `(template, params, overrides, seed)` => bit-identical frames; `result.trajectory_sha256` hashes the streamed frames.
  The `thrust_spread` assumption (per-nozzle random thrust error) is drawn from `seed`.

## REST

`GET /health` -> `{ok, templates, mujoco_version, live:{protocol, templates, search, version_note}}`

`POST /simulate` (always `mode: "sim"`, unpaced)
```json
{"template":"rocket_car","params":{"pitch_fwd_outer_start":0.91,...},   // OR "variant": 5000 (stored best_params of that recorded variant)
 "overrides":{"thruster_force_max":3500,"vehicle_mass":1400},          // assumption key -> value, on top of the recorded scenario's values
 "seed":1,"rescale_throttle":false,"rescale_from":null,"include_trajectory":true}
```
Without `params`/`variant` the recorded hero variant's schedule is used. `bundle_defaults:false` starts from the template defaults
instead of the recorded scenario's assumption values. Response: `{success, failed_checks, display[], perf{steps, sim_time_s, compute_ms,
us_per_step, steps_per_s, realtime_factor, frames}, mujoco_version, seed, params, overrides, events, n_frames, trajectory_sha256, metrics,
wall_ms_total, trajectory (schema `Trajectory`)}`. 400 = bad input, 404 = unknown/unavailable template.

## WebSocket `/ws/sim` (JSON text messages)

Origin must be absent or `localhost` / `127.0.0.1` / `[::1]` (any port); CORS on REST follows the same rule.

Client -> server
* `{"type":"start", template, mode:"sim"|"search", params?, variant?, overrides?, seed?, speed?, rescale_throttle?, rescale_from?, search?:{max_seconds, max_evals, preview_every}}`
  (a new `start` cancels the active run)
* `{"type":"stop"}` -> `{"type":"stopped"}`; `{"type":"restart"}` re-runs the last start request.

Server -> client
* `start`: `run_id, mode, template, model_id, model_hash, mujoco_version, dt, physics_dt, n_frames_max, bodies[], series[{name,unit}], series_max{}, charts[{series,label,unit}], params, overrides, seed, speed, compute, note`
* `frames`: `i0, pos[frame][body][3], quat[frame][body][4 wxyz], series{name: values per frame}, t, steps, compute_ms`
  (Trajectory layout, Z-up, 20 ms per frame for rocket_car)
* search only: `progress{gen, evals, best_cost, success, elapsed_s, evals_per_s, restart, popsize}`, `preview{gen, cost, success, n_frames, pos, quat, series}`
  (full rollout of the best-so-far schedule, sent when it improved every `preview_every` generations), `search_done{found, best_cost, evals, wall_s, evals_per_s, generations, params, stopped_by}`,
  then `replay_start{params}` and the normal `frames`/`result` of the best schedule.
* `result`: `mode, success, failed_checks, display[{key,label,value,unit,ok,threshold}], perf{..., wall_ms, speed}, mujoco_version, seed, params, overrides, events, n_frames, trajectory_sha256`
* `error{message}`. Nothing is ever substituted when a run fails.

Code: `packages/engine/src/kinetra_engine/live.py` (runs, search, stream), `api.py` (routes). Tests: `packages/engine/tests/test_live_api.py`.
