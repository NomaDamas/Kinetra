# Roadster thruster-flip spike: Go / No-Go

## Verdict: **GO**, with caveats

CMA-ES finds a thruster burn schedule for a 1,300 kg car-like rigid body. The schedule gives a full 360° pitch flip with an upright landing, verified by MuJoCo rollouts.

The search takes **3.4 s and 3,072 rollouts** on a 10-core M-series Mac. Across 16 extra seeds it took 4.5–24 s, and every seed succeeded.

Caveats (details below):
- Only the **ramp-launch** scenario was solved. The standing-start jump was **not found** (weak evidence only).
- The solution is tight on fuel and impact speed.
- The solution was **robustified** against uncertainty in a second search stage. The nominal optimum alone survives Monte-Carlo only 20 % of the time.
- All of this is a simplified rigid-body model, not validated against real hardware.

## Reproduce

```bash
cd spikes/roadster
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt   # mujoco 4.0.0, cma 4.5.0
.venv/bin/python run_spike.py          # full run: about 165 s wall total (40 s search budget per case)
.venv/bin/python run_spike.py --quick  # shorter budgets (flag present, NOT run by me)
```

Outputs:
- `out/trajectory.json`: Three.js replay data.
- `out/report.json`: all numbers below.
- `out/flip.png`: side-view silhouette, pitch curve, throttle plot.

Fixed seed (`SEED=20260001`). A same-seed re-run produced a bit-identical solution and eval count (printed as `determinism ... True`).

## Setup

**Vehicle**
- Mass 1,300 kg, box 4.2 × 1.9 × 1.2 m, four simple wheel cylinders (20 kg each, free hinges).
- I_yy about the COM is 2,085 kg·m².

**Thrusters (8)**
- Each is a MuJoCo `motor` on a `site`, `gear="0 0 1 0 0 0"`, `ctrlrange 0..Fmax`.
- Isp is 70 s (cold-gas N₂). Fuel is accounted as ∑F·dt/(Isp·g), with a **25 kg usable-propellant cap**. Mass is held constant, so there is no mass depletion.
- Groups:
  - Outer pitch couple, forward-pitching: nose-down plus tail-up, lever 2.1 m.
  - Outer pitch couple, back-pitching: the opposite pair.
  - Inner forward-pitch couple, lever 1.0 m.
  - Lift quad: 4 belly thrusters pushing up.

**Ramp launch scenario**
- Initial state at the ramp lip: 22 m/s along a 25° ramp, COM height 2.2 m, nose up 25°, wheels spinning.

**MJCF**
- Built programmatically in `roadster.build_mjcf`. Timestep 4 ms, `implicitfast`, 4.5 s horizon (1,125 steps).

**Success criteria (all must hold)**
1. Final pitch within 360° ± 20°, measured from the unwrapped rotation. Here the flip is a **backflip** (θ → −2π), since the ramp starts nose-up.
2. Pitch within ±30° of the full turn at first touchdown.
3. Vertical speed at touchdown ≤ 6 m/s.
4. Pitch rate at touchdown ≤ 3 rad/s.
5. Final roll within ±20°.
6. Ride height 0.5–0.8 m and vertical speed < 1 m/s at the end.
7. **No thrust after first ground contact.** This is my own strict rule.
8. Fuel ≤ 25 kg.

## Parameterization (15 parameters, all in [0,1], scaled in `Sim.decode`)

There are 5 burn windows, each with 3 parameters: `t_start ∈ [0, 2.5] s`, `duration ∈ [0, 2.0] s`, and `throttle ∈ [0,1]·Fmax`. All thrusters in a group share a window.

| window | group |
|---|---|
| `pitch_fwd_outer` | outer forward-pitch couple |
| `pitch_back_outer` | outer back-pitch couple |
| `lift_main` | lift quad |
| `pitch_fwd_inner` | inner forward-pitch couple |
| `lift_landing` | lift quad (second window) |

The cost function:
- Pitch error at touchdown and at the end.
- Penalties for impact speed, spin rate, residual roll, post-contact thrust and fuel over the cap, plus a small fuel term.
- Hard `success` flag from the checks above.
- Any candidate that satisfies every check ends the search.

The optimizer is CMA-ES with box bounds, popsize 48, σ0 = 0.3, and IPOP-style restarts (population doubles up to 384). Each generation is evaluated in one parallel `mujoco.rollout` call.

## Numbers measured

**Rollout engine**
- `mujoco.rollout.Rollout` is available in 4.0.0 and used with a 10-thread pool.
- Throughput is **≈ 870–920 full 4.5 s rollouts/s** (1,125 steps each).
- Rollouts are deterministic: batch order, batch size and repeat runs give 0.0 difference.
- Re-simulating the chosen schedule with plain `mj_step` matches the rollout state exactly (max deviation 0.0).

**Search cases** (ramp launch, 40 s budget unless noted)

| case | necessary screen | CMA-ES result | evals / wall |
|---|---|---|---|
| ramp, Fmax = 300 N | **INFEASIBLE** (min rotation time 3.34 s > flight-time upper bound 2.43 s) | sanity CMA run (6 s budget): not found, best cost 13.5 | 5,712 / 6 s |
| ramp, 2,000 N | passes | **NOT_FOUND** (weak). Best candidate fails impact speed (10.2 m/s vs 6 limit) and post-contact thrust. | 32,736 / 40 s |
| ramp, 3,000 N (marginal) | passes | **NOT_FOUND** (weak). Near miss: best candidate lands at 6.004 m/s (limit 6.0) and burns 27.8 kg (cap 25). Flip and pitch checks pass. | 33,504 / 40 s |
| ramp, 5,000 N | passes | **FEASIBLE** | 3,072 / **3.4 s** |
| standing, 1,500 N | **INFEASIBLE** (Σ upward thrust < weight, so it cannot leave the ground) | sanity CMA run (6 s budget): not found | ~3,400 / 6 s |
| standing, 15,000 N | passes | **NOT_FOUND** (weak). Best candidate: flip OK, but 6.006 m/s impact and 29.5 kg fuel (cap 25). | 27,168 / 40 s |

- The failed-check lists in this table come from `out/report.json` (`best_candidate_failed_checks`). The console print in the last full run was attached to the wrong case. I fixed the print order in `run_spike.py` afterwards and did not re-run the full script, so only the console print changed.
- At 3,000 N the search never found a candidate that satisfies every check, but it came within 0.004 m/s of the impact limit. The fuel cap (27.8 kg > 25 kg) is the other failure. This is the marginal band: roughly 3–4 kN at these launch conditions.
- Exploratory runs not in `run_spike.py`:
  - Standing start at 15 kN with 40 kg and 60 kg propellant caps: NOT_FOUND in 30 s each.
  - Standing start at 25 kN: NOT_FOUND.
  - Ramp 5 kN with a weaker launch (20 m/s, 20°, 1.8 m): NOT_FOUND within 25–40 s at vz_max 6, 7 and 8. So the launch state matters a lot.
  - So a standing-start jump is **unproven**, not shown impossible.

**Necessary-condition screen** (`necessary_screen`; Fmax sweep on ramp)
- Fmax = 300 N: INFEASIBLE.
- 1,000 N through 5,000 N: pass.
- The screen is cheap (milliseconds).
- It checks:
  - Can the vehicle leave the ground (Σ upward thrust > weight)?
  - Is the minimum bang-bang rotation time within the flight-time upper bound? That bound is computed with all lift thrusters at full thrust, capped by total impulse.
  - Is the propellant lower bound within the cap?
- It is conservative: INFEASIBLE means impossible within the model assumptions, and PASS does not mean feasible. At 2,000–3,000 N it passes while CMA-ES cannot find a landing-compliant schedule, as expected.

**Monte-Carlo** (best solution of the 5 kN case)
- Perturbations: mass ±5 %, per-thruster thrust ±10 % independently, COM offset ±0.15 m (x), ±0.10 m (z).
- Nominal CMA-ES optimum: 20 % success (n = 100, 95 % CI 0.13–0.29).
  - Failures: 80 post-contact-thrust, 27 impact speed, 1 flip.
- Robustified (second CMA-ES stage on 24 fixed perturbed models, 19,968 evals, 26 s):
  - Training success 0.96.
  - **Held-out MC at n = 100: 83 %** (CI 0.74–0.89).
  - **Held-out MC at n = 500: 84.8 %** (CI 0.814–0.877), **0.69 s** wall for 500 rollouts.
  - Failures at n = 500: 76 post-contact-thrust, 31 impact speed.
- Interpretation: the 5 kN solution is a real flip, but a ~15 % tail breaks the strict landing rules. Most failures are the landing burn still firing at touchdown, which is my own strict rule. They are not failures to flip.

**Chosen schedule** (the exported one)

| window | start (s) | duration (s) | thrust (N) |
|---|---|---|---|
| `pitch_fwd_outer` | 1.193 | 0.679 | 2,152 |
| `pitch_back_outer` | 0.008 | 0.592 | 3,508 |
| `lift_main` | 0.065 | 0.784 | 79 |
| `pitch_fwd_inner` | 0.612 | 0.030 | 1,672 |
| `lift_landing` | 1.674 | 0.489 | 4,942 |

- Touchdown at 2.22 s, pitch −365.9°, vertical speed 5.5 m/s.
- Fuel 24.9 kg of the 25 kg cap. The solution is propellant-limited.

**Seed spread** (ad-hoc, not in `run_spike.py`; 8 seeds each, 25 s budget)

| Fmax | success | time to solution |
|---|---|---|
| 5,000 N | 8/8 | 4.5–7.3 s |
| 4,000 N | 8/8 | 4.6–24.1 s |

**Total wall for `run_spike.py`:** about 167 s. The 60 s requirement is for one search: the hero search took 3.4 s, and the 40 s per-case budget was never exceeded.

## Trajectory export

`out/trajectory.json`, schema `roadster-flip-trajectory/v1`:
- 375 frames at dt = 0.012 s (sim dt 0.004, stride 3).
- Per frame: `t`, `p` (xyz), `q` (**wxyz**, MuJoCo order), `wheel_spin[4]`, and `thr[8]` (throttle 0..1 for each thruster).
- Header also contains the body box, wheel and thruster geometry, force directions, event times, the schedule, and `verification` (rollout vs `mj_step` deviation 0.0).
- Coordinates are MuJoCo Z-up. For Three.js use (x, y, z) → (x, z, −y) and reorder the quaternion to xyzw.

## Failure modes met

1. **Landing speed is the binding constraint, not the flip.** CMA-ES finds flips easily. What it struggles with is flip plus lift to cushion plus no-thrust-at-contact plus the fuel cap. The impact-speed penalty weight (2 → 8) changed results a lot in exploratory runs, so the cost shaping is a sensitive choice. A staged or lexicographic cost would be safer.
2. **Fuel cap binds.** The 5 kN solution uses 24.9 of 25 kg, and the 3,000 N and 15 kN-standing best candidates failed on fuel. Isp and the cap are the assumption with the most leverage.
3. **A nominal optimum is brittle.** It sits at the edge of feasibility; MC success of 20 % rose to 85 % only after a robustification stage. The production pipeline should always run it.
4. **Standing jump not found** (15–25 kN, up to 60 kg propellant, 30 s each). It needs a landing burn against a larger vertical drop, so the problem is harder. This is weak evidence only.
5. **Instability warnings.** MuJoCo printed QACC instability warnings in some 15–25 kN standing candidates (thrust ramps with a 4 ms step). These candidates score badly and are discarded. The production template should clamp thrust and use a smaller step when Fmax is large.
6. **Strict post-contact rule.** It fails 76 of 500 MC samples. Relaxing it would raise the success rate but changes the definition.

## Recommendations for the production template

- Expose these parameters:
  - Thruster layout: positions and directions per group.
  - Fmax per group, Isp and propellant cap.
  - Mass, inertia and COM.
  - Launch state (speed, angle, height) or standing start.
  - Landing limits (vertical speed, pitch rate, pitch tolerance, ride height).
- Use burn windows as the search parameters. 5 windows × (start, duration, throttle) = 15 parameters is enough for this case. Bounds: start 0–2.5 s, duration 0–2 s (≈ flight time), throttle 0–1.
- Use CMA-ES with IPOP restarts and a population of at least 48, with a **parallel rollout batch per generation**. This gives ~900 rollouts/s on this laptop.
- Order the verdicts:
  1. Run the cheap analytic screen first. It is a strong INFEASIBLE.
  2. Run CMA-ES. A found solution means FEASIBLE inside the model assumptions.
  3. If the screen passes and nothing is found, report "NOT_FOUND in N evals" as weak evidence only.
- Run the robustification stage plus Monte-Carlo (n ≥ 500, ~0.7 s) on every FEASIBLE result. Report the Wilson CI, not a point estimate.
- Label every result "simplified model, needs precise validation". Real thrusters are not instantaneous, fuel mass depletes, and nozzles, drag and tire contact are not modelled.
- Report the failed-check list for the best candidate. It tells the user the binding constraint (impact speed, fuel, post-contact thrust).
- The "suggested fix" should come from the optimizer, for example the minimum Fmax or propellant for which a solution is found. For a quick sweep, 5 kN solves in seconds and 2–3 kN does not in 40 s.

## Files

- `roadster.py`: MJCF template, parameter decode, rollout, metrics, analytic screen.
- `run_spike.py`: end-to-end driver.
- `requirements.txt`, `.gitignore`.
- `out/`: `trajectory.json`, `report.json`, `flip.png`.
