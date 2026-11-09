# Kinetra — a physical feasibility lab

> **Don't build it to discover it won't work.** Kinetra kills bad physical ideas in simulation before you spend a dollar on hardware.
>
> 한 문장의 물리 아이디어를 넣으면, MuJoCo가 "된다 / 안 된다 / 못 찾았다"를 판정하고, 무엇이 먼저 깨지는지와 고칠 값을 알려줍니다. 소프트웨어로 된 MythBusters.

**Judge = MuJoCo (physics), Actor = Three.js (replay).** Every number on screen comes from a simulation run, never from an LLM.

## What it does

```
idea (one sentence)
  → research      curated, cited spec catalog (offline; each value flagged verified / unverified)
  → assumptions   editable panel with source + confidence; low-confidence items need human review
  → build model   verified template → MuJoCo MJCF
  → necessary-condition screen   cheap analytic/static checks that can PROVE "impossible"
  → search        CMA-ES over a 10–15 parameter control schedule, MuJoCo rollouts
  → Monte-Carlo   success probability + 95% CI over the uncertain assumptions
  → fix search    optimizer (not an LLM) sweeps a control to find a smallest verified fix
  → verdict + BOM + 3D replay
```

### Verdict asymmetry (the core honesty rule)

| Outcome | Meaning | Strength |
|---|---|---|
| `FEASIBLE_FOUND` | a witness succeeds on the nominal model | strong *existence* evidence; reliability is the separate `p_success` ± CI |
| `INFEASIBLE_NECESSARY_CONDITION` | a necessary condition fails (energy, static torque, impulse) | strong "impossible under these assumptions" |
| `NOT_FOUND_IN_BUDGET` | search found nothing in N evaluations | **weak** — not a proof |

CFD, thermal and FEA are **not** judged; verdicts carry a `simplified model, needs precise validation` label. Details: [`docs/judgment-spec.md`](docs/judgment-spec.md).

## What is in the demo

Open the web app ([Run it](#run-it)). Three things to try:

1. **Roadster rocket flip** — slide the thruster force. Low values are `INFEASIBLE` (the screen proves the car cannot rotate in the available flight time) or `NOT_FOUND` (weak); higher values find a flip. Replay the best run in 3D.
2. **Unitree G1 humanoid jump** — slide the motor-torque scale. 0.10× and 0.15× are *proven impossible* (static hold needs 15.7 N·m vs 13 available; takeoff energy needs 48.3 J vs 27.0 J available). Real G1 meshes replay.
3. **Autoresearch tab** — an experiment ledger (hash-chained, keep/discard/gated), attitude-control search, and simulator calibration with identifiability.

**Two modes, clearly labelled in the UI.**
- **RECORDED** (default, no backend): replays committed, seeded runs (*recorded run, seeded & reproducible*). The slider snaps to precomputed variants.
- **LIVE** (needs the local engine, `scripts/dev.sh`): the **Live tab** runs a *real MuJoCo simulation on your machine* and streams frames to the 3D view over a WebSocket. Change thruster force or mass and a fresh rollout runs; "Run live search" shows CMA-ES finding a flip in real time (roadster). If the engine is not reachable the Live tab is disabled and shows the start command. Protocol: [`docs/live-mode.md`](docs/live-mode.md).

Verified in this repo: `POST /simulate` on the roadster at 5 kN is deterministic (identical trajectory hash on repeat) and runs ~29,000 steps/s (4.5 s of sim in ~39 ms); at 1 kN the same endpoint reports the failed checks (`flip_final`, `flip_td`, `impact_vz`, …). 10 live-API tests pass. Humanoid live mode is a batch rollout that is then paced (not incremental stepping), and live search is roadster-only.

## Measured results (and their limits)

All numbers were produced by the code in this repo. Spikes are in [`spikes/`](spikes/); the production-path numbers are in the committed bundles under `apps/web/public/demo/`.

**Roadster (1,300 kg, 8 cold-gas thrusters, ramp launch, 360° flip + upright landing)**

| Source | Result |
|---|---|
| Spike (`spikes/roadster/REPORT.md`) | 5 kN: flip found in 3.4 s / 3,072 rollouts; 16 extra seeds all succeeded. 300 N proven infeasible (needs 3.34 s to rotate, ≤ 2.43 s flight). 2–3 kN: `NOT_FOUND` (weak). |
| Engine bundle | 300 N `INFEASIBLE`; 1–2 kN `NOT_FOUND`; 3 / 4 / 5 / 6 kN `FEASIBLE_FOUND` with `p_success` 3.6 / 46.6 / 13.4 / 58.4 % (n = 500). |

Limits we know about:
- `p_success` is **not monotone** in thrust (5 kN < 4 kN) — search noise with a small budget; we did not tune it away.
- The spike's 83–85 % robustness figure was measured with the ±10 % thrust perturbation silently not applied (it wrote to `actuator_gear[:,0]`, which is 0 for these motors). The engine applies it. With thrust noise off the engine reproduces ~91 % at 5 kN; with it on, it is ~13 %. The shipped bundle uses the thrust-noise-on setting.
- The shipped "fix" (3 kN) has only 3.6 % verified success — it is a verified *witness*, not a robust design. The UI marks such results *fragile under uncertainty*.
- Standing-start jump: not found (weak evidence only). Cold-gas Isp, tank and structure limits are unverified defaults.

**Unitree G1 humanoid jump (Menagerie model, 10 parameters, no RL)**

| Torque scale | Verdict | p_success |
|---|---|---|
| 0.10× / 0.15× | `INFEASIBLE_NECESSARY_CONDITION` | – |
| 0.25× / 0.40× | `NOT_FOUND_IN_BUDGET` (weak) | – |
| 0.60× / 1.00× | `FEASIBLE_FOUND` | 5.0 % / 13.5 % (n = 200) |

Limits: the hero target is **0.15 m**, not 0.3 m (at 0.3 m the controller reached 0–3 % on all 3 probe seeds). Success is low under the sampled mass/friction/torque/COM/landing-force uncertainty; we did not shrink the disturbances. The 9× body-weight landing-force limit is an unverified default. Contact is MuJoCo's default soft contact, uncalibrated; only the sagittal plane was exercised.

**Autoresearch** ([`docs/autoresearch.md`](docs/autoresearch.md)) — Karpathy-style loop: propose → fixed-budget experiment → one metric → keep/discard → append-only hash-chained ledger. Physical-assumption changes are gated behind human approval.
- Attitude control (toy 10 kg single-axis article): open-loop schedule 5.5 % [3.1, 9.6] vs PD/hybrid feedback 100 % [98.1, 100] on 200 held-out samples. PD and hybrid are indistinguishable on this metric.
- Calibration on **synthetic** data: recovers 9/9 hidden parameters on the recommended campaign; a couple-only campaign correctly reports contact parameters as *not identified* rather than returning a confident value.
- **Sim-to-real is not validated.** No real data was used.

## What is *not* proven

- Willingness to pay is **unvalidated**. The business hypothesis (viral "cheapest physics lab" → teams with money on the line pay for verdicts) is untested.
- No customer, traction or accuracy-vs-reality claims. The planned 3-way comparison (by hand / general coding agent / Kinetra) was **not run**.
- Rocket and humanoid physics are rigid-body models with default, partly unverified parameters; real-world cost references in [`docs/judgment-spec.md`](docs/judgment-spec.md) §D are cited where sourced and marked otherwise.

## Positioning

- *Drift builds the sim. We kill ideas not worth simulating.*
- *Luminary speeds up experts' simulations. We give everyone their first physical experiment.*

## Run it

Requirements: Python ≥ 3.10 with [`uv`](https://docs.astral.sh/uv/), Node ≥ 20 with `pnpm`.

```bash
# Web demo (uses the committed recorded bundles)
cd apps/web && pnpm install && pnpm dev          # http://localhost:5173
pnpm build                                        # strict TS + production build

# Engine (rebuild bundles / live API)
uv venv packages/engine/.venv && uv pip install --python packages/engine/.venv/bin/python -e . -e packages/engine
packages/engine/.venv/bin/python packages/engine/scripts/build_rocket_bundle.py     # ~10–25 min cold, seconds cached
packages/engine/.venv/bin/python packages/engine/scripts/build_humanoid_bundle.py   # needs MuJoCo Menagerie, see below
packages/engine/.venv/bin/python packages/engine/scripts/build_autoresearch_bundle.py   # ~3 min
cd packages/engine && .venv/bin/uvicorn kinetra_engine.api:app --port 8000          # live engine API (or: scripts/dev.sh = engine + web together)

# Tests
packages/engine/.venv/bin/python -m pytest packages/engine/tests -q
```

The humanoid build needs the G1 model: `git clone --depth 1 https://github.com/google-deepmind/mujoco_menagerie spikes/humanoid_jump/vendor/mujoco_menagerie` (BSD-3-Clause; or set `KINETRA_MENAGERIE`). Recorded bundles and converted GLB meshes are already committed, so the demo does not need it.

## Repository layout

| Path | Contents |
|---|---|
| `apps/web/` | Vite + React + R3F demo, presentation mode (`present.html`) |
| `packages/core/` | `physlab_core` — Pydantic contracts (`SpecSheet`, `Trajectory`, `Verdict`) |
| `packages/engine/` | `kinetra_engine` — pipeline, templates (`rocket_car`, `humanoid_jump`), Monte-Carlo, autoresearch, FastAPI |
| `schemas/` | generated JSON Schemas + `types.ts` (`uv run python packages/core/scripts/export_schemas.py`) |
| `spikes/` | Go/No-Go spikes with `REPORT.md`s: `roadster/`, `humanoid_jump/`, `autoresearch/` |
| `docs/` | `judgment-spec.md` (judgment items, failure taxonomy, wording rules, cost sources), `autoresearch.md`, `demo-bundle.md`, `schemas.md`, `pitch/` |
| `tools/film/` | scripted, TTS-narrated demo film pipeline |

## Roadmap

1. More verified templates (drone, vehicle, robot arm); the template contract is `packages/engine/src/kinetra_engine/base.py`.
2. User-supplied URDF/CAD upload.
3. Calibration on real traces; measure sim-to-real gap (e.g. a physical SO-101) — the long-term moat.
4. Surrogate models trained on accumulated verdicts to speed up sweeps.
5. Validate who pays, and the planned 3-way benchmark.

Open-source building blocks: [MuJoCo](https://github.com/google-deepmind/mujoco), [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) (Unitree G1), [pycma](https://github.com/CMA-ES/pycma), Three.js / React Three Fiber, Pydantic, FastAPI.
