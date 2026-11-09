"""End-to-end demo: attitude autoresearch + excitation design + calibration autoresearch + verdict integration.

    .venv/bin/python run_demo.py

Writes: ledger.jsonl (all experiments, hash-chained), calibration.json (Assumption-compatible),
        calibration_failure_case.json, out/traces/*.csv, out/demo_summary.md, out/results.json
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
os.makedirs("out/traces", exist_ok=True)

import calib  # noqa: E402
import calib_loop  # noqa: E402
import calib_run  # noqa: E402
import integration  # noqa: E402
from attitude import mc_eval, sample_disturbances, CONFIRM_SEED  # noqa: E402
from attitude_loop import AttitudeEvaluator, BASELINE as ATT_BASE, confirm, maybe_llm_proposer, run_attitude, _spec  # noqa: E402
from calib import PARAM_KEYS  # noqa: E402
from loop import Ledger, run_loop  # noqa: E402

OUT: list[str] = []


def say(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def ledger_table(entries, only_prefix: str) -> str:
    rows = ["| id | decision | metric | vs incumbent | gate | hypothesis |", "|---|---|---|---|---|---|"]
    for e in entries:
        if not e.id.startswith(only_prefix):
            continue
        v = "-" if e.value is None else f"{e.value:.4f}"
        inc = "-" if e.incumbent_value is None else f"{e.incumbent_value:.4f}"
        rows.append(f"| {e.id} | {e.decision} | {v} | {inc} | {e.gate}{' (' + e.approved_by + ')' if e.approved_by else ''} | {e.hypothesis[:110]} |")
    return "\n".join(rows)


def main() -> None:
    t_all = time.time()
    ledger = Ledger("ledger.jsonl", reset=True)
    results: dict = {}

    # ======================================================= 1. attitude autoresearch
    say("## 1. Attitude-control autoresearch (360-deg pitch flip, stop upright)")
    t = time.time()
    att = run_attitude(ledger, verbose=True)
    ents = ledger.entries
    say(f"\nattitude wall time: {time.time()-t:.1f}s")
    say(ledger_table(ents, "att-"))
    base = next(e for e in ents if e.id == "att-000")
    kept = [e for e in ents if e.id.startswith("att-") and not e.id.startswith("att-hw") and e.decision == "keep"]
    first_robust_ol = next((e for e in ents if e.id == "att-001"), None)
    final = att["phase2"]
    p1 = att["phase1"]

    say("\n### Held-out confirmation (fresh 200 disturbed samples, seed never used for any decision)")
    rows = ["| config | family/alloc | train_samples | hw | nominal rollout | MC success (200) | Wilson 95% CI | fuel Ns |", "|---|---|---|---|---|---|---|---|"]
    conf = {}
    for label, e in [("baseline (att-000)", base), ("robust open-loop (att-001)", first_robust_ol), ("phase-1 incumbent", p1), ("phase-2 incumbent (human-approved hw)", final)]:
        c = confirm(e.config, e.details["params"], 200)
        conf[label] = c
        cc = e.config["ctrl"]
        rows.append(f"| {label} [{e.id}] | {cc['family']}/{cc['allocation']} | {cc['train_samples']} | ctrl_hi={e.config['hw']['ctrl_hi']}, extra_arm={e.config['hw']['extra_pair_arm']} | "
                    f"{'ok' if e.details['nominal_ok'] else 'FAIL'} | {c['success_rate']:.3f} ({c['k']}/{c['n']}) | [{c['ci_low']:.3f}, {c['ci_high']:.3f}] | {c['fuel_mean']:.1f} |")
    say("\n".join(rows))

    say("\n### Seed robustness of the family comparison (3 CMA-ES seeds each, same budget 3000 rollouts, nominal-model tuning, fresh 200-sample MC)")
    from attitude import train
    rows = ["| family | CMA seeds -> MC success | mean |", "|---|---|---|"]
    fam_res = {}
    for fam in ("schedule", "pd", "hybrid"):
        c = copy.deepcopy(ATT_BASE)
        c["ctrl"]["family"] = fam
        c["ctrl"]["train_samples"] = 0
        rs = []
        for s in (101, 202, 303):
            tr = train(c["hw"], c["ctrl"], 3000, s)
            m = mc_eval(c["hw"], c["ctrl"], tr["params"], sample_disturbances(CONFIRM_SEED, 200, _spec(c)))
            rs.append(m["success_rate"])
        fam_res[fam] = rs
        rows.append(f"| {fam} | {', '.join(f'{r:.3f}' for r in rs)} | {np.mean(rs):.3f} |")
    say("\n".join(rows))
    results["attitude"] = {"baseline_value": base.value, "baseline_mc": base.details["mc"], "phase1_value": p1.value, "phase2_value": final.value,
                           "confirm": conf, "family_seeds": fam_res,
                           "gated": [e.id for e in ents if e.decision == "gated"], "crashes": [e.id for e in ents if e.decision == "crash"]}

    llm = maybe_llm_proposer()
    say(f"\nLLM proposer: {'API key present, but NOT exercised in this demo run' if llm else 'skipped (no ANTHROPIC_API_KEY / OPENAI_API_KEY); rule-based proposer only'}")

    # ======================================================= 2. excitation design
    say("\n## 2. Calibration experiment recommendation (excitation-design loop)")
    t = time.time()
    r = run_loop("exc", calib_loop.BASELINE, calib_loop.ExcitationEvaluator(), calib_loop.ExcitationProposer(), ledger, max_experiments=12, base_seed=3, verbose=True)
    inc_exc = r["incumbent"]
    say(f"\nexcitation wall time: {time.time()-t:.1f}s")
    say(ledger_table(ledger.entries, "exc-"))
    campaign = inc_exc.config["excitation"]["trials"]
    first = next(e for e in ledger.entries if e.id == "exc-000")
    say("\nRecommended campaign (" + f"{sum(x['T'] for x in campaign):.1f}s of rig time, {len(campaign)} trials): " + ", ".join(x["name"] for x in campaign))
    say(f"EIG baseline {first.value:.2f} nats -> recommended {inc_exc.value:.2f} nats; parameters with posterior/prior sd < 0.5 (at prior-draw Jacobians): "
        f"{first.details['n_identified']} -> {inc_exc.details['n_identified']} of 9")
    say("Per-parameter expected posterior/prior sd, baseline vs recommended:")
    say("| param | baseline couple-only | recommended |\n|---|---|---|")
    for k in PARAM_KEYS:
        say(f"| {k} | {first.details['contraction'][k]:.3f} | {inc_exc.details['contraction'][k]:.3f} |")
    results["excitation"] = {"baseline_eig": first.value, "recommended_eig": inc_exc.value, "campaign": [x["name"] for x in campaign]}

    # ======================================================= 3. calibration autoresearch
    say("\n## 3. Calibration autoresearch (synthetic hidden-truth system; metric = held-out validation RMS in noise-sigma units)")
    t = time.time()
    inc_cal = calib_run.run_calibration(ledger, campaign, verbose=True)
    say(f"\ncalibration-loop wall time: {time.time()-t:.1f}s")
    say(ledger_table(ledger.entries, "cal-"))

    say("\n### Final calibration with the incumbent config (Laplace posterior + SVD + parametric bootstrap k=16)")
    rep = calib_run.calibration_report(inc_cal.config, source="calibration autoresearch on synthetic trace (hidden truth + noise)", boot_k=16)
    say(calib_run.fmt_table(rep))
    say(f"\nresidual RMS (noise units; 1.0 = noise floor): train {rep['train_rms']:.3f}, held-out validation {rep['val_rms']:.3f}; "
        f"whitened-Jacobian condition number {rep['idn']['cond']:.3g}; singular values {np.array2string(rep['idn']['singular_values'], precision=3)}")
    bs = rep["bootstrap"]
    say("bootstrap (k=16): " + ", ".join(f"{k}: sd={bs['sd'][k]:.3g}" for k in bs["free"]))
    n_cover = sum(v["within_2sd"] for v in rep["coverage"].values())
    say(f"coverage vs hidden truth: {n_cover}/{len(rep['coverage'])} parameters inside mean +- 2 sd of the emitted normal")
    calib_run.emit_json("calibration.json", rep, "recommended campaign: " + ", ".join(x["name"] for x in campaign))
    say(f"schema check of calibration.json assumptions: {calib.validate_assumptions(rep['assumptions'])}")

    say("\n### CSV round trip (loader for a real trace): write campaign traces, reload, refit")
    datas = calib_run.make_data(campaign, inc_cal.config["eval"]["data_seed"])
    for x, d in zip(campaign, datas):
        calib.save_trace_csv(f"out/traces/{x['name']}.csv", d)
    loaded = [calib.load_trace_csv(f"out/traces/{x['name']}.csv") for x in campaign]
    res_csv = calib.fit(campaign, loaded, PARAM_KEYS)
    say("fit from CSV: " + ", ".join(f"{k}={res_csv['p'][k]:.4g}" for k in PARAM_KEYS) + f"  (rms {calib.data_rms(campaign, loaded, res_csv['p']):.3f})")

    say("\n### FAILURE CASE: couple-only campaign (no ground contact, no single-thruster, no added mass), all 9 parameters free")
    cfg_bad = copy.deepcopy(calib_run.BASELINE)
    cfg_bad["fit"]["free"] = list(PARAM_KEYS)
    rep_bad = calib_run.calibration_report(cfg_bad, source="couple-only campaign", boot_k=16)
    say(calib_run.fmt_table(rep_bad))
    say(f"\nresidual RMS train {rep_bad['train_rms']:.3f}, held-out validation {rep_bad['val_rms']:.3f} (a good fit on train that does NOT transfer = unidentified/degenerate directions); "
        f"condition number {rep_bad['idn']['cond']:.3g}; weakest data direction loads on: "
        + ", ".join(f"{k}={v:+.2f}" for k, v in rep_bad["idn"]["weakest_dir"].items() if abs(v) > 0.2))
    ni = [k for k, s in rep_bad["status"].items() if s["status"] == "NOT_identified"]
    wk = [k for k, s in rep_bad["status"].items() if s["status"] == "weak"]
    say(f"-> NOT identified (prior kept, confidence=low, std unchanged): {ni}; weakly identified: {wk}")
    calib_run.emit_json("calibration_failure_case.json", rep_bad, "couple-only campaign (failure case)")
    results["calibration"] = {"val_rms": rep["val_rms"], "train_rms": rep["train_rms"], "cond": rep["idn"]["cond"], "coverage": rep["coverage"],
                              "bad_not_identified": ni, "bad_weak": wk, "bad_val_rms": rep_bad["val_rms"], "bad_train_rms": rep_bad["train_rms"]}

    # ======================================================= 4. verdict integration
    say("\n## 4. Verdict integration: p_success + CI, before vs after calibration narrowing (200 MC samples drawn from the assumption distributions)")
    t = time.time()
    txt, rows = integration.verdict_table(rep["assumptions"], n_mc=200)
    say(txt)
    say(f"\nintegration wall time: {time.time()-t:.1f}s")
    results["verdict_rows"] = [{k: v for k, v in r.items()} for r in rows]

    say("\n### 4b. Same comparison with a TIGHT flight window (hw.t_end = 2.5 s and 2.7 s instead of 3.6 s; 100 MC samples): the regime where hardware margin is thin")
    for te in (2.7, 2.5):
        integration.HW["t_end"] = te
        txt_t, rows_t = integration.verdict_table(rep["assumptions"], n_mc=100)
        say(f"\nt_end = {te} s\n" + txt_t)
        results[f"verdict_rows_t_end_{te}"] = [{k: v for k, v in r.items()} for r in rows_t]
    integration.HW.pop("t_end", None)

    say(f"\nledger: {len(ledger.entries)} experiments, hash chain {'VALID' if ledger.verify_chain() else 'BROKEN'}; "
        f"decisions: " + ", ".join(f"{d}={sum(1 for e in ledger.entries if e.decision == d)}" for d in ("keep", "discard", "crash", "gated")))
    say(f"TOTAL wall time: {time.time()-t_all:.1f}s")
    with open("out/demo_summary.md", "w") as f:
        f.write("\n".join(OUT))
    with open("out/results.json", "w") as f:
        json.dump(results, f, indent=1, default=float)


if __name__ == "__main__":
    main()
