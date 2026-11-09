# Kinetra

> **Before you build hardware, know if it can work, what breaks first, and what to build.**
>
> 하드웨어를 만들기 전에, 되는지 · 무엇이 먼저 깨지는지 · 무엇을 만들어야 하는지 압니다.

Describe a physical idea in one sentence. Kinetra checks it against physics (MuJoCo), sizes the parts, draws the custom ones, and returns a **design brief**: a verdict with the strength of the evidence, the constraint that breaks first, sized components, custom parts with CAD, a BOM, risks and the first physical test to run.

**Every number comes from a simulation run or a cited catalog entry, never from an LLM.** Anything else is labelled `default`, `unverified` or `estimate`.

## Why this exists

Prototype respins and test campaigns are expensive, and most of a project's cost is locked in at concept stage. Kinetra is for the moment *before* you spend it: hardware founders deciding what the first prototype should be, robotics teams choosing an actuator or battery, makers without a test rig.

The full argument, with sourced figures (and their caveats), personas, what we do **not** claim, and how we would prove it: [`docs/why-kinetra.md`](docs/why-kinetra.md).

## Screenshots

Real captures (1440x900) of the production build on the committed bundles and design files (no fixtures).

| Home | Dashboard |
|---|---|
| ![Home](apps/web/screenshots/home.png) | ![Dashboard](apps/web/screenshots/projects.png) |

| Project overview (roadster, 5000 N) | Simulate: recorded replay (a LIVE mode switch sits beside it) |
|---|---|
| ![Overview](apps/web/screenshots/project-overview.png) | ![Simulate](apps/web/screenshots/project-simulate.png) |

| Design: requirements → parts → CAD → closed loop | Report: design brief + downloads |
|---|---|
| ![Design](apps/web/screenshots/project-design.png) | ![Report](apps/web/screenshots/project-report.png) |

| Design: custom parts with 3D CAD preview and hand-calc checks | Design: closed loop (mass fed back, verdict re-run) |
|---|---|
| ![Parts](apps/web/screenshots/project-design-parts.png) | ![Closed loop](apps/web/screenshots/project-design-loop.png) |

| Evidence | Lab |
|---|---|
| ![Evidence](apps/web/screenshots/project-evidence.png) | ![Lab](apps/web/screenshots/lab.png) |

## What you get: the design brief

| Section | What it contains |
|---|---|
| **Verdict** | `FEASIBLE_FOUND`, `INFEASIBLE_NECESSARY_CONDITION` or `NOT_FOUND_IN_BUDGET`, with `p_success` and a 95 % interval. |
| **What breaks first** | The binding constraint and its margin. |
| **Sized components** | Requirements derived from a real rollout of the witness design, times a margin, matched to cited catalog parts; unmatched lines become *custom* or *needs sourcing*. Never an invented vendor part. |
| **Custom parts + CAD** | Parametric geometry with a simple load check labelled "simplified model, needs FEA"; STL for preview, STEP for engineers. |
| **Closed loop** | The designed hardware's mass is put back into the model and the verdict re-run until it converges. |
| **BOM, risks, next test** | `bom.csv`; only cited prices are summed, unpriced lines are counted, never treated as zero. |

Contract between engine and web: [`docs/design-stage.md`](docs/design-stage.md).

### Verdict asymmetry (the core honesty rule)

| Outcome | Meaning | Strength |
|---|---|---|
| `FEASIBLE_FOUND` | a witness succeeds on the nominal model | strong *existence* evidence; reliability is the separate `p_success` ± CI |
| `INFEASIBLE_NECESSARY_CONDITION` | a necessary condition fails (energy, static torque, impulse) at the favorable end of the assumptions | strong "impossible under these assumptions" |
| `NOT_FOUND_IN_BUDGET` | search found nothing in N evaluations | **weak**, not a proof |

CFD, thermal and FEA are **not** judged; verdicts carry `simplified model, needs precise validation`. Details: [`docs/judgment-spec.md`](docs/judgment-spec.md).

## How it works

```
idea (one sentence)
  → assumptions   editable panel: value, distribution, source, confidence; low-confidence items need review
  → build model   verified template → MuJoCo MJCF
  → necessary-condition screen   cheap analytic/static checks that can PROVE "impossible"
  → search        CMA-ES over a 10–15 parameter control schedule, MuJoCo rollouts
  → Monte-Carlo   success probability + 95 % CI over the uncertain assumptions
  → fix search    the optimizer (not an LLM) sweeps one control to find the smallest verified fix
  → design        requirements → components → custom parts (CAD) → mass-feedback loop → alternatives
  → design brief  design-brief.md + bom.csv + CAD
```

**Judge = MuJoCo (physics), Actor = Three.js (replay).**

## The web app

Hash routes, no backend required (the demo replays committed, seeded bundles):

| Route | What it is |
|---|---|
| `#/` | **Home**: the problem, what you get, how it works, proof with real numbers from the bundles. |
| `#/projects` | **Dashboard**: one card per idea with status, `p_success` ± CI, binding constraint, design status. |
| `#/p/<id>/<tab>` | **Project workspace**: Overview · Assumptions · Simulate · Design · Report · Evidence. |
| `#/lab` | **Lab**: autoresearch (ledger, attitude control, calibration) and the free-form live sandbox. |

Two modes, labelled in the UI:
- **RECORDED** (default, no backend): replays committed, seeded runs ("recorded run, seeded & reproducible").
- **LIVE** (needs the local engine, `scripts/dev.sh`): a *real MuJoCo simulation on your machine* streamed to the 3D view over a WebSocket. If the engine is not reachable the LIVE panel is disabled and shows the start command. Protocol: [`docs/live-mode.md`](docs/live-mode.md).

A narrated presentation build (`present.html`) is documented in [`docs/pitch/README.md`](docs/pitch/README.md).

## Measured results (and their limits)

All numbers were produced by the code in this repo. Spikes are in [`spikes/`](spikes/); production-path numbers are in the committed bundles under `apps/web/public/demo/`.

Verified in this repo: `POST /simulate` on the roadster is deterministic (identical trajectory hash on repeat; asserted in `test_live_api.py`) and reports the failed checks (`pitch_turn`, `roll_turn`, `upright_td`, `impact_vz`, …) when the schedule does not make it. Humanoid live mode is a batch rollout that is then paced (not incremental stepping), and live search is roadster-only.

**Roadster (1,300 kg, 18 cold-gas nozzles, ramp launch, full 360° roll AND full 360° pitch + upright landing)**

*Maneuver, as decided and implemented:* in one ramp jump the car turns a full 360° about its body pitch axis AND a full 360° about its body roll axis (`|∫ω dt| ≥ 340°` of the body-frame rate from launch to first touchdown, i.e. 360° minus the 20° tolerance), then lands upright (roll and pitch each within 20° of a whole number of turns at the end, 30° at touchdown; touchdown vertical speed ≤ 6 m/s; touchdown pitch and roll rates ≤ 3 rad/s; no thrust after contact; propellant within the cap; ride height 0.5–0.8 m). Rotations may be simultaneous or sequential; the optimizer decides. The model gained 8 side roll nozzles (10 pitch/lift + 8 roll, lateral lever arm 0.95 m: our modeling choice, not a sourced layout) and the burn schedule is 21 parameters (7 windows). The propellant cap default moved from 25 kg to 60 kg (a 200 L cylinder at 300 bar holds about 61 kg of N2; unverified), because two rotation axes need more gas than the old pitch-only default.

| Source | Result |
|---|---|
| Spike (`spikes/roadster/REPORT.md`) | **Pitch-only** history (the spike's maneuver, not this one): 5 kN found a flip in 3.4 s / 3,072 rollouts; 300 N proven infeasible. Not comparable with the table below. |
| Engine bundle (current, roll + pitch, n = 500 MC samples, search budget 25,000 evals x up to 3 seeds) | 300 N `INFEASIBLE_NECESSARY_CONDITION` (pitch **and** roll rotation times exceed the flight-time bound); 2 / 4 / 5 / 6 kN `NOT_FOUND_IN_BUDGET` (weak: 75,015 / 75,015 / 75,159 / 57,391 evaluations, no witness); **8 kN `FEASIBLE_FOUND`, `p_success` 15.2 % [12.3, 18.6]** (117,087 evals incl. warm start); **10 kN `FEASIBLE_FOUND`, 12.6 % [10.0, 15.8]** (66,201 evals). |
| Sensitivity: ±3 % / ±10 % independent per-nozzle thrust noise (`scripts/rocket_noise_sensitivity.py`, same witness and MC seed) | 8 kN: 15.2 % → 4.2 % [2.8, 6.3] → 0.8 % [0.3, 2.0]; 10 kN: 12.6 % → 4.0 % [2.6, 6.1] → 1.0 % [0.4, 2.3] (n = 500 each). A 5 kN nozzle was **not** found feasible at all, so there is no 5 kN-equivalent row; the rows above are the nearest measured ones. |
| Design stage (8 kN base) | +175.2 kg of designed hardware (55.5 kg of it flagged placeholder estimates; 1 of 7 requirement lines met by catalog parts). Closed loop: with that mass added the search found no witness (`NOT_FOUND_IN_BUDGET`, weak), so the loop stops at iteration 1. Alternatives 18 x 8 kN and 18 x 10 kN: both `NOT_FOUND_IN_BUDGET` at the designed mass; nothing is recommended. |

Honest reading: a witness that does both full rotations exists at 8 kN and 10 kN per nozzle on the nominal model (strong existence evidence), but it is fragile (12–15 % over the sampled mass/COM spread, ~1 % with 10 % per-nozzle noise) and does not survive the added hardware mass in the search budget. At 2–6 kN the combined maneuver was not found; that is weak evidence, not a proof. The optimizer-fix sweep found no tested value reaching `p_success` ≥ 50 %, so no variant carries a verified fix.

Limits we know about:
- **The bundle does not sample per-nozzle thrust error** (`thrust_spread` = 0); the sensitivity row above is a separate measurement. The spike's original 83–85 % figure for the pitch-only flip had that noise silently not applied.
- The search starts from a small grid of analytic sequential schedules (roll couple, then pitch couple, counted in the eval budget) because uniform-start CMA-ES did not find the combined maneuver in our probes; it is a start point only, not a verdict input. A feedback attitude controller (the autoresearch spike's PD result) was prototyped and **not** adopted: it did not find a witness in the probe budget either, so the template remains open-loop timing windows.
- Per-nozzle thrust of the real hardware is unknown; no catalogued cold-gas thruster comes close (largest read: 8.9 N vs the several-kN class required), so nozzles, valves and regulator are *needs sourcing*.
- Standing-start jump: not found (weak evidence only). Cold-gas Isp (70 s), tank and structure limits are unverified defaults.

**Unitree G1 humanoid jump (Menagerie model, 10 parameters, no RL)**

| Torque scale | Verdict | p_success |
|---|---|---|
| 0.10× / 0.15× | `INFEASIBLE_NECESSARY_CONDITION` (static hold needs 15.7 N·m vs 13 available; takeoff energy 48.3 J vs 27.0 J) | – |
| 0.25× / 0.40× | `NOT_FOUND_IN_BUDGET` (weak) | – |
| 0.60× / 1.00× | `FEASIBLE_FOUND` | 5.0 % / 13.5 % (n = 200) |

Limits: the hero target is **0.15 m**, not 0.3 m (at 0.3 m the controller reached 0–3 % on all 3 probe seeds). Success is low under the sampled mass/friction/torque/COM/landing-force uncertainty; we did not shrink the disturbances. The 9× body-weight landing-force limit is an unverified default. Contact is MuJoCo's default soft contact, uncalibrated; only the sagittal plane was exercised.

Design stage (1.0× base): knee needs 180.7 N·m with margin; the strongest catalogued actuator (CubeMars AKE90-8) peaks at 170 N·m, so the knee is *needs sourcing*; hip and ankle lines are met by verified CubeMars parts. Adding the designed hardware (+12 kg, on top of G1 link masses that already include motors, so this overstates the effect) gives `NOT_FOUND_IN_BUDGET` (weak), and the loop stops there.

**Autoresearch** ([`docs/autoresearch.md`](docs/autoresearch.md)): propose → fixed-budget experiment → one metric → keep/discard → append-only hash-chained ledger; physical-assumption changes are gated behind human approval.
- Attitude control (toy 10 kg single-axis article): open-loop schedule 5.5 % [3.1, 9.6] vs PD/hybrid feedback 100 % [98.1, 100] on 200 held-out samples. PD and hybrid are indistinguishable on this metric.
- Calibration on **synthetic** data: recovers 9/9 hidden parameters on the recommended campaign; a couple-only campaign correctly reports contact parameters as *not identified*.

## What is *not* proven

- **Sim-to-real is not validated.** No real hardware data was used.
- **Willingness to pay is unvalidated.** No customers, revenue or traction. The planned 3-way comparison (by hand / general coding agent / Kinetra) and 5 design-partner interviews are specified in [`docs/why-kinetra.md`](docs/why-kinetra.md) §7 and have **not** been run.
- Rocket and humanoid physics are rigid-body models with default, partly unverified parameters. Real-world cost references ([`docs/judgment-spec.md`](docs/judgment-spec.md) §D, [`docs/why-kinetra.md`](docs/why-kinetra.md) §1) are cited where sourced and marked otherwise; vendor blogs are flagged as such.
- Part checks in the design stage are hand calculations ("simplified model, needs FEA"), not finite-element analysis.

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
packages/engine/.venv/bin/python packages/engine/scripts/build_design_bundle.py         # design.json + cad/*.stl|step + export/{design-brief.md,bom.csv} per scenario
cd packages/engine && .venv/bin/uvicorn kinetra_engine.api:app --port 8000          # live engine API (or: scripts/dev.sh = engine + web together)

# Tests
packages/engine/.venv/bin/python -m pytest packages/engine/tests -q
```

The humanoid build needs the G1 model: `git clone --depth 1 https://github.com/google-deepmind/mujoco_menagerie spikes/humanoid_jump/vendor/mujoco_menagerie` (BSD-3-Clause; or set `KINETRA_MENAGERIE`). Recorded bundles and converted GLB meshes are already committed, so the demo does not need it.

## Repository layout

| Path | Contents |
|---|---|
| `apps/web/` | Vite + React + R3F app (Home, Dashboard, Project workspace, Lab), presentation mode (`present.html`); typed Home copy in `src/content/` |
| `packages/core/` | `physlab_core`: Pydantic contracts (`SpecSheet`, `Trajectory`, `Verdict`, `DesignBrief`) |
| `packages/engine/` | `kinetra_engine`: pipeline, templates (`rocket_car`, `humanoid_jump`), catalog, Monte-Carlo, autoresearch, FastAPI |
| `schemas/` | generated JSON Schemas + `types.ts` (`uv run python packages/core/scripts/export_schemas.py`) |
| `spikes/` | Go/No-Go spikes with `REPORT.md`s: `roadster/`, `humanoid_jump/`, `autoresearch/` |
| `docs/` | `why-kinetra.md` (reason to exist), `design-stage.md`, `judgment-spec.md`, `autoresearch.md`, `live-mode.md`, `demo-bundle.md`, `schemas.md`, `pitch/` |
| `tools/film/` | scripted, TTS-narrated demo film pipeline |

## Roadmap

1. **Validate the reason to exist** before building more: 5 design-partner interviews and the 3-way benchmark ([`docs/why-kinetra.md`](docs/why-kinetra.md) §7).
2. More verified templates (drone, vehicle, robot arm); the template contract is `packages/engine/src/kinetra_engine/base.py`.
3. User-supplied URDF/CAD upload.
4. Calibration on real traces; measure the sim-to-real gap (e.g. a physical SO-101), the long-term moat.
5. Surrogate models trained on accumulated verdicts to speed up sweeps.

Open-source building blocks: [MuJoCo](https://github.com/google-deepmind/mujoco), [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) (Unitree G1), [pycma](https://github.com/CMA-ES/pycma), Three.js / React Three Fiber, Pydantic, FastAPI.
