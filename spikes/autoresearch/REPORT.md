# Autoresearch spike: attitude control + calibration (measured numbers)

Everything below was produced by `python run_demo.py` (venv: mujoco 4.0.0, cma 4.5.0, numpy 2.4.6, scipy 1.17.1, pydantic 2.14.3; macOS arm64, 10 cores).
Full verbatim output: `out/demo_summary.md`; raw results: `out/results.json`; ledger: `ledger.jsonl`.
**Wall time of the whole demo: 72 s and 90 s on two runs (the second added section 4b).** All results are deterministic given seeds, except where CPU-count-dependent chunking could change float summation order (not observed).

## Reproduce
```bash
cd spikes/autoresearch
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python run_demo.py            # ~1.5 min -> ledger.jsonl, calibration.json, calibration_failure_case.json, out/
```
Files: `article.py` (self-made 6-DoF box + 6 (opt. 10) thruster sites, MJCF generated in Python, params applied in place), `loop.py` (ledger, gates, loop), `attitude.py` / `attitude_loop.py`, `calib.py` / `calib_loop.py` / `calib_run.py`, `integration.py`.

**Caveat on the test article:** a 10 kg 1.0x0.5x0.3 m box, thrusters 6 N each (4 form the pitch couple, arm 0.5 m, tau_max = 12 N·m, I_y = 0.908 kg·m², alpha_max = 13.2 rad/s²), 5 ms step. It is a toy; no number below says anything about a real vehicle.

## 1. Attitude autoresearch (360-deg pitch flip, stop upright; 3.6 s flight)
Success = |pitch - 2π| < 8° and |ω| < 0.15 rad/s for the last 0.3 s. Disturbances per MC sample: mass ±5% (inertia scales with it), COM offset x ±3 cm / z ±2 cm, global thrust ×U(0.9,1.1), per-thruster ×U(0.98,1.02), sensor delay 0–30 ms, sensor noise (3 mrad, 0.01 rad/s). Metric = MC success rate (**40 samples per decision**) − 1e-4·mean fuel (N·s) (fuel only breaks ties). Per-experiment budget fixed: 3000 CMA-ES rollouts + 40 MC rollouts. Loop MC set seed is fixed; confirmation numbers below use a **different, never-for-decisions 200-sample set**.

Ledger (`att-*`): 
| id | decision | metric | what |
|---|---|---|---|
| att-000 | keep | 0.074 | baseline: open-loop schedule tuned on nominal model |
| att-001 | keep | 0.174 | open-loop tuned on 8 disturbed samples |
| att-002 | gated | – | patch shrinks the thrust disturbance (physical assumption → needs human) |
| att-003 | gated | – | patch cuts n_mc to 5 (forbidden: evaluator contract) |
| att-004 | discard | −0.003 | P-only feedback (no damping) |
| att-005 | **keep** | **0.998** | + derivative gain (PD, saturated allocation) |
| att-006 | keep | 0.999 | schedule+PD hybrid |
| att-007 | discard | 0.924 | bang-bang allocation |
| att-008/009 | discard | 0.9986 / 0.9982 | robust (8-sample) training of incumbent / hybrid |
| att-010/011 | gated | – | hardware changes (ctrl range 1.5, extra thruster pair): need approval |
| att-hw-000..002 | keep | 0.9988 → 0.9989 → 0.9990 | after simulated human approval of the hardware class |

Held-out confirmation (200 fresh disturbed samples):
| config | MC success | Wilson 95% CI | fuel (N·s) |
|---|---|---|---|
| baseline open-loop (att-000) | 0.055 (11/200) | [0.031, 0.096] | 11.9 |
| robust open-loop (att-001) | 0.110 (22/200) | [0.074, 0.161] | 11.1 |
| phase-1 incumbent hybrid (att-006) | 1.000 (200/200) | [0.981, 1.000] | 12.0 |
| + approved hardware (att-hw-002) | 1.000 (200/200) | [0.981, 1.000] | 10.4 |

Family comparison over 3 CMA-ES seeds (nominal-model tuning, 3000 rollouts, fresh 200-sample MC): schedule 0.030 / 0.000 / 0.090; **pd 1.000 / 1.000 / 1.000**; hybrid 1.000 / 1.000 / 0.705.

**Findings (honest):**
- The loop does discover the claim: the open-loop schedule is brittle (nominal rollout succeeds, 5.5% under disturbance; training on disturbed samples only doubles it to 11%), and feedback fixes it (≈100%). Proof is the ledger rows att-000/001/005.
- Rule proposer only walks a hand-written list, so "discovery" = the ordering evaluated and the keep/discard evidence, not creativity. Nothing here shows an LLM would find it.
- att-006 (hybrid) was kept over att-005 (PD) by **+0.0006 metric = fuel tiebreak only** (both 40/40). The 3-seed sweep shows hybrid is *less* seed-robust than plain PD (0.705 on one seed). So the ledger's "keep" at att-006 is not evidence hybrid is better; with only 40 samples and a ceiling effect the metric cannot separate them.
- The hardware phase did not improve success (already ~100%); it only lowered fuel 12.0 → 10.4 N·s. This task is not hardware-limited at 3.6 s.
- att-004 (P-only) was discarded as expected (ringing/undamped).

## 2. Calibration experiment recommendation (excitation-design loop, `exc-*`)
Metric = expected information gain (nats) = ½·mean logdet(I + JᵀJ) at 3 prior-drawn points, J = Jacobian of noise-whitened residuals wrt prior-sd-normalised parameters (pos σ 2 mm, attitude σ 3 mrad @ 50 Hz). Budget fixed: ≤ 5 trials, ≤ 14 s rig time.

| id | decision | EIG | proposal |
|---|---|---|---|
| exc-000 | keep | 33.93 | baseline: pure thruster-couple spin-up/down (3 s) |
| exc-001 | keep | 40.33 | + single-thruster pulse |
| exc-002 | keep | 41.62 | + lateral thruster pulse |
| exc-003 | keep | 54.83 | + 2 m tilted drop (ground contact) |
| exc-004 | discard | 54.91 | + coast with initial velocity (gain 0.08 < 0.25 threshold) |
| exc-005 | keep | 55.95 | + repeat single pulse with known +5 kg mass |
| exc-006 | crash | – | lengthen couple trial to 5 s: violates 14 s budget → validator raises (logged as crash) |
| exc-007 | gated | – | raise time budget (forbidden) |

Recommended campaign (12.5 s): couple_spin, single_t0, lateral_t4, tilted_drop, single_t0_plus5kg. Expected posterior/prior sd (lower = better): baseline mass 0.84, inertia 0.49, thrust_gain 0.74, contact_timeconst 1.00, contact_dampratio 1.00 → recommended all ≤ 0.017. Parameters with expected contraction < 0.5: 5 → 9 of 9.

## 3. Calibration autoresearch (`cal-*`) on SYNTHETIC ground truth
Hidden "real" system: mass 11.2, com_x +2.0 cm, com_z −1.2 cm, inertia ×1.12, thrust ×0.93, lin damping 0.8, rot damping 0.25, contact solref (0.045, 0.85) + Gaussian sensor noise. Prior (the "assumptions panel") is deliberately wrong by 1–2.5 sd. Metric = RMS residual on held-out validation motions in noise-σ units (1.0 = noise floor).

Ledger: baseline (free: mass only, couple-only data) 66.7 → +inertia 49.6 → +thrust gain 9.66 → +damping *discard* (9.96) → +COM 5.64 → +contact params *discard* (5.64, no contact in data, no gain) → forbidden validation-seed swap *gated* → **free all 9 at once 2.27** (greedy one-at-a-time was path-dependent) → **adopt recommended campaign 0.988** → free-all again *discard* / CMA-ES-then-LSQ *discard* (same optimum; ~3–4× more simulations).

Final fit (recommended campaign; 9 free; Laplace posterior with prior, bootstrap k = 16):
| param | fit | post sd | post/prior sd | hidden truth |
|---|---|---|---|---|
| mass | 11.19 | 0.011 | 0.011 | 11.2 |
| com_x | 0.01998 | 3.6e-5 | 0.001 | 0.02 |
| com_z | −0.01193 | 8.0e-5 | 0.003 | −0.012 |
| inertia_scale | 1.120 | 0.0011 | 0.007 | 1.12 |
| thrust_gain | 0.9297 | 0.0008 | 0.008 | 0.93 |
| lin_damping | 0.799 | 0.0008 | 0.002 | 0.8 |
| rot_damping | 0.250 | 0.0004 | 0.004 | 0.25 |
| contact_timeconst | 0.0445 | 0.0004 | 0.043 | 0.045 |
| contact_dampratio | 0.853 | 0.0086 | 0.043 | 0.85 |

Residual RMS (noise units): train 0.983, held-out 0.988; condition number 265; 9/9 truths inside mean ± 2 sd (|z| ≤ 1.1). Bootstrap sd agrees with the Laplace sd (e.g. mass 0.0115 vs 0.0109). CSV round trip (write → `load_trace_csv` → refit) reproduces the same fit.
**Caveat:** this is a *self-consistent* test: the fitter's model class equals the hidden system's model class (same MuJoCo model, only parameters differ). Small posterior sd and 9/9 coverage are therefore expected and are NOT evidence of sim-to-real accuracy. Model-form error (unmodelled aero, thruster lag, real contact) is not represented.

### Failure case (couple-only campaign, all 9 free) → `calibration_failure_case.json`
| param | fit | post/prior sd | verdict |
|---|---|---|---|
| mass | 10.47 | 0.677 | weak |
| thrust_gain | 0.866 | 0.559 | weak |
| inertia_scale | 1.044 | 0.449 | identified (coarsely) |
| contact_timeconst / dampratio | 0.03 / 0.6 | **1.000** | **NOT identified → prior kept, std unchanged, confidence low** |
| com_x, com_z, lin_damping, rot_damping | – | 0.004–0.15 | identified |

Train RMS 0.985 (looks perfect) but held-out 2.274: a good training fit does not mean identified. Whitened Jacobian condition number 3.7e15; weakest direction = contact_timeconst. Mass / thrust_gain / inertia are only coarsely separated by this campaign (posterior/prior sd 0.45–0.68, [INFERENCE] because the pure couple constrains mostly thrust·arm/inertia); they are returned with the wide posterior, not as confident numbers.

## 4. Verdict integration (`integration.py`; 200 MC draws from the assumption distributions; controller re-searched on the assumptions' nominal values each time)
Default 3.6 s window:
| controller | assumptions | p_success | Wilson 95% CI | at hidden truth |
|---|---|---|---|---|
| schedule | before (prior) | 0.010 (2/200) | [0.003, 0.036] | FAIL (122° off) |
| schedule | after (calibrated) | 0.665 (133/200) | [0.597, 0.727] | ok |
| hybrid | before | 0.995 | [0.972, 0.999] | ok |
| hybrid | after | 1.000 | [0.981, 1.000] | ok |
| pd | before | 0.845 (169/200) | [0.788, 0.889] | ok |
| pd | after | 1.000 (200/200) | [0.981, 1.000] | ok |

Tight 2.7 s window (100 draws): pd 0.49 [0.39,0.59] → 0.69 [0.59,0.77]; schedule 0 → 0; hybrid 0 → 0 (hybrid *after* is 283° off at the hidden truth, i.e. failed worse, not better). Tight 2.5 s window: pd 0.27 [0.19,0.36] → 0.46 [0.37,0.56]; schedule 0.00 → 0.05; hybrid 0.00 → 0.00.
Interpretation: calibration moves p_success when the verdict was limited by assumption uncertainty (schedule, pd), and the CI of the post-calibration verdict is dominated by the *unmodelled* disturbances (thruster mismatch, delay, noise) rather than the narrowed parameters. In the tight window the minimum-time hardware limit dominates and calibration cannot create margin; the hybrid controller does worse there, which I did not investigate. Wilson CIs with k=n are conservative/wide for 100 draws.

## What is NOT shown
- No real data; **sim-to-real not validated**. No video-derived trace was tried (CSV loader only tested on synthetic CSV written by this code).
- Fitter model class = truth model class (see caveat). No process/model-form error.
- LLM proposer (`attitude_loop.LLMProposer`) is code only; **never executed** (no API key used). Its patches go through the same gate/evaluator.
- Attitude results are for a 1-DoF pitch task of a single toy article; CMA-ES seeds: 1 per ledger row, 3 in the family sweep.
- "Human approval" is simulated by a dict in code (`approvals={"approval:hardware": ...}`), not a real UI.
- Identifiability = local (Jacobian at the fit, Gaussian); nonlinear/global degeneracies are covered only by the bootstrap (warm-started at the fit, k=16).
