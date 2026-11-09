# Autoresearch — attitude control and calibration (spike design, v0)

Code and measured numbers: `spikes/autoresearch/` (`REPORT.md`, `run_demo.py`). This document is the design contract; everything labeled *shown* was measured in the spike, everything labeled *not shown* was not.

"Autoresearch" is meant in the Karpathy sense: an agent proposes a change, a **fixed-budget** experiment runs, **one scalar metric** is compared with the incumbent, the change is kept or discarded, and **every** experiment is appended to a ledger. Numbers come only from simulation; the proposer (rules or an LLM) supplies hypotheses and patches, never results.

## 1. Architecture

```
config (JSON) ──► Proposer.propose(ledger tail, incumbent) ──► {hypothesis, patch}
                                                                   │
                                      Gate (path classes) ◄────────┘
                       forbidden ─► logged "gated", NOT run
                       approval:* ─► logged "gated" unless a human approval is present
                       auto ─► apply patch ─► Evaluator.evaluate(config, seed)  (fixed budget, deterministic)
                                                   │ one scalar + details
                       keep if better than incumbent by min_delta, else discard; exception ⇒ crash
                                                   ▼
                                      Ledger.append  (ledger.jsonl, append-only, SHA-256 hash chain)
```

* **Experiment record** (`loop.Experiment`): `id, parent_id, hypothesis, change` (RFC-6902 `add`/`replace` patch), `budget`, `metric`, `value`, `incumbent_value`, `decision` ∈ keep | discard | crash | gated, `seed`, `versions` (python/mujoco/numpy/cma/scipy), full `config`, `details`, `gate`, `approved_by`, `proposer`, `wall_s`, `prev_hash/entry_hash`. `Ledger.verify_chain()` detects edits.
* **Evaluator contract** (fixed by the harness, not patchable): per-experiment budget (CMA-ES rollouts / test seconds), success definition, MC sample count (≥ 30; spike uses 40 per decision, 200 for confirmation), MC/data seeds, the metric. `Evaluator.validate()` asserts these on every config, so even a patch that sneaks through is a logged `crash`. Same seed ⇒ same value (determinism).
* **Proposer interface** (`loop.Proposer.propose(ledger, incumbent) -> Proposal | None`): `RuleProposer` / `CalProposer` / `ExcitationProposer` walk hand-written hypothesis lists with applicability guards. `LLMProposer` (optional; only built if `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set) shows the LLM the ledger tail and the allowed patch paths and parses a JSON patch. **The LLM proposer is untested against a live API.** Its output goes through the same gate and evaluator.
* **Metrics**: attitude = MC success rate − 1e-4·fuel (fuel breaks ties only); calibration = held-out validation RMS in sensor-noise units; excitation design = expected information gain (½ logdet(I + JᵀJ), nats).

### Evaluator contracts per task
| task | config the loop may patch (`auto`) | fixed (forbidden) | needs human |
|---|---|---|---|
| attitude | `/ctrl/*` (family schedule\|pd\|hybrid, allocation saturated\|bangbang, kd on/off, train_samples, CMA popsize/σ) | `/budget`, `/eval`, `/metric` | `/disturbance/*` (physical assumptions), `/hw/*` (ctrl range, extra thruster pair) |
| calibration | `/fit/*` (free set, method), `/excitation/*` (recommended campaign) | `/budget`, `/eval` (validation seed, data seed) | – (but see §3: running the campaign on hardware) |

## 2. Attitude control (shown)
Task: 360° pitch flip and stop upright (|θ−2π| < 8°, |ω| < 0.15 rad/s for 0.3 s) on a self-built 10 kg box with thrusters; MC over mass ±5%, COM offset, thrust ±10% (+ per-thruster ±2%), 0–30 ms sensor delay, sensor noise. Controller families: open-loop CMA-ES schedule, PD + saturated/bang-bang allocation, schedule+PD hybrid.
Measured (held-out 200 samples): open-loop 5.5% [3.1, 9.6]; open-loop tuned on disturbed samples 11%; PD/hybrid 100% [98.1, 100]. The ledger records the path: open-loop brittle → derivative-gain feedback fixes it. Qualifications: plain PD was as good as hybrid; hybrid was less seed-stable (one of three CMA seeds gave 70.5%); the 40-sample metric saturates and cannot rank them. See REPORT §1.

## 3. Calibration (shown on synthetic data only)
Pipeline: trace(s) → MAP fit in prior-normalised coordinates (`scipy.least_squares`, optional CMA-ES warm start) → Laplace posterior `C = (JᵀJ/inflation + I)⁻¹` → identifiability from the whitened-Jacobian SVD, per-parameter posterior/prior sd (< 0.5 identified, < 0.9 weak, else NOT identified), and a parametric bootstrap → emit `Assumption` objects.

* **Output** `calibration.json`: `assumptions[]` validated against `physlab_core.schemas.Assumption` (`key, label, value, unit, distribution{kind:"normal", mean, std, clip_low, clip_high}, source, confidence, editable`) so it can be spliced into `SpecSheet.assumptions` (it is **not** yet merged into any pipeline code), plus residual RMS, singular values, condition number, weakest direction, bootstrap.
* **Non-identified parameters are not given a confident value**: the prior is kept unchanged (`std` = prior sd), `confidence: "low"`, and `source` says "NOT identified by calibration data". Failure case measured: a couple-only campaign leaves contact stiffness/damping at posterior/prior sd 1.00 and returns held-out RMS 2.27 vs 0.98 train (a good train fit is not identification).
* **Excitation design / "calibration experiment recommendation"**: the same loop, with the information gain as metric, proposes which motions to add (single-thruster pulses, lateral pulse, tilted drop, known added mass). Recommended 12.5 s campaign: EIG 33.9 → 55.9 nats; parameters with expected contraction < 0.5: 5 → 9 of 9. Output is a *recommendation* for a human to run on the rig.
* **CSV loader** (`calib.load_trace_csv`): columns `t,x,y,z,qw,qx,qy,qz`, SI units, MuJoCo quaternion order, 50 Hz; the matching excitation description (initial state, thruster pulse log) must be supplied. Only a synthetic CSV was tried. Video-derived traces need pose extraction + time alignment + a noise model that this spike does not provide.
* **Verdict impact** (`integration.py`): replacing the prior panel by the calibrated posterior moved p_success for the open-loop schedule 0.010 → 0.665 and for PD 0.845 → 1.000 (CI width 0.100 → 0.019) at 3.6 s; in tight-window cases the gain is smaller or absent (REPORT §4).

## 4. How it plugs into the main pipeline
```
idea → research (LLM fills assumptions panel, source=llm_estimate, confidence=low)
     → [HUMAN GATE A: assumptions panel review]
     → build model from template  ─┐
     → search (CMA-ES)             │  attitude autoresearch lives here:
     → MC verdict                  │  it proposes controller-structure patches, evaluator = the verdict MC
     → Verdict                     ┘
optional, when the user has rig/video data:
     calibration autoresearch → calibration.json → [HUMAN GATE B] → replaces/narrows Assumption.distribution → re-run search + verdict
```
Human-review gates (implemented as path classes in `loop.GATE_RULES`):
| patch class | example | rule |
|---|---|---|
| controller structure / optimizer settings | family, kd on/off, allocation, train_samples | auto-apply; each logged |
| hardware (thrusters, ctrl range, extra pair) | `/hw/*` | **human approval**: changes the bill of materials and the idea itself |
| physical assumptions / disturbance model | `/disturbance/*`, `/assumptions/*`, any narrowing of `Assumption.distribution` | **human approval**: this is exactly what lets a loop "win" by redefining the problem |
| evaluator contract | budget, n_mc, seeds, success definition, metric | **never** patchable by the loop |
| running a calibration campaign on hardware | the recommended trials | human performs it |
A calibrated `Assumption` replaces the prior only after approval (gate B); a parameter flagged NOT identified must stay at its prior and cannot be shrunk.

## 5. Proven vs not proven
**Shown in the spike** (REPORT has numbers): ledger/gate/hash-chain mechanics (34 experiments: 18 keep, 9 discard, 1 crash, 6 gated: 4 cheat attempts on assumptions/evaluator contract, 2 hardware proposals awaiting approval); loop finds open-loop brittleness and feedback robustness on a toy article; calibration recovers a hidden perturbed model within its posterior (9/9 within 2 sd) on a campaign recommended by the excitation loop; unidentifiable parameters are flagged and left at the prior; the posterior is expressible as a schema-valid `Assumption`; verdict p_success/CI change with narrowed assumptions.
**Not shown**: sim-to-real (no real data; the fit model class equals the generating model class, so coverage is self-consistent, not validated); that an LLM proposer helps (never run); statistical significance of keep decisions at MC=40 (ceiling effect; att-006 over att-005 was a fuel tiebreak); thruster lag, plume, aero, structure; multi-axis attitude (only pitch); any integration code in `packages/` (none written); that rule order does not bias the result (one ordering).

## 6. Limits
* Local (Gaussian) identifiability; nonlinear degeneracies only partly covered by a warm-started bootstrap (k=16).
* A loop that optimises a metric can overfit it: mitigations in the spike are a held-out MC seed for confirmation, fixed evaluator contract, parsimony threshold (`min_delta`), and gates. Not a guarantee.
* Greedy one-at-a-time structure edits are path-dependent (the calibration ledger shows freeing parameters sequentially gave worse validation than freeing all at once on the same data).
* Compute: whole demo ≈ 1.5 min on 10 cores; per-experiment ≈ 1–5 s for the toy. A real template with contact-rich 30-DoF models will be orders of magnitude slower; budgets must be set per template.

## 7. Next steps
1. Run the LLM proposer on a live key and compare against the rule list on the same ledger (needs several runs for variance).
2. Obtain one real trace (e.g. bench drop + thruster pulse tracked by video/mocap), test the CSV path, and add a model-discrepancy term (GP or inflated noise) so the posterior reflects model-form error.
3. Wire `calibration.json` into `SpecSheet.assumptions` behind review gate B; add a Verdict field recording which assumptions were calibrated and by which ledger id.
4. Raise MC and add sequential stopping so keep/discard uses CI separation, not point estimates; add multi-axis attitude and a drone template.
5. Persist the ledger (and its hash head) with the Verdict's `Reproducibility` block.
