#!/usr/bin/env python
"""Build the autoresearch demo bundle: apps/web/public/demo/autoresearch/{ledger,calibration,integration,excitation}.json

Everything is re-run from the engine code (seeded); nothing is copied from spikes/. Target runtime <= 5 min.

    packages/engine/.venv/bin/python packages/engine/scripts/build_autoresearch_bundle.py [--out DIR] [--quick]

index.json (owned by scripts/build_index.py) is expected to reference:
    "autoresearch": {"attitude_ledger": "autoresearch/ledger.json", "calibration": "autoresearch/calibration.json",
                     "integration": "autoresearch/integration.json", "excitation": "autoresearch/excitation.json"}
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]

from kinetra_engine.autoresearch import attitude as att  # noqa: E402
from kinetra_engine.autoresearch import attitude_loop as attl  # noqa: E402
from kinetra_engine.autoresearch import calib, calibration_loop as calloop, excitation as exc, integration  # noqa: E402
from kinetra_engine.autoresearch.article import PRESETS, PARAM_KEYS  # noqa: E402
from kinetra_engine.autoresearch.ledger import Ledger, run_loop, verify_rows, versions  # noqa: E402

NOTE_SYNTH = ("All results are from MuJoCo simulation of self-built rigid test articles. Calibration uses SYNTHETIC ground "
              "truth (a hidden perturbed model + sensor noise); the fitter's model class equals the generating class, so "
              "coverage is self-consistent and is NOT sim-to-real validation. No real vehicle is modelled or validated.")


def say(s: str = "") -> None:
    print(s, flush=True)


def jsonable(o):
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else float(x)))


def r5(o, nd: int = 5):
    """Round floats (for plotting series / reported numbers; never applied to hashed ledger rows)."""
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: r5(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [r5(v, nd) for v in o]
    return o


def confirm_rows(entries, article: str, n_conf: int) -> list[dict]:
    by = {e.id: e for e in entries}
    picks = [("baseline open-loop schedule", "att-000"), ("robust open-loop (8 disturbed samples)", "att-001")]
    out = []
    ids = [i for _, i in picks]
    inc1 = max((e for e in entries if e.id.startswith("att-") and not e.id.startswith("att-hw") and e.decision == "keep"),
               key=lambda e: int(e.id.split("-")[1]))
    inc2 = max((e for e in entries if e.id.startswith("att-hw") and e.decision == "keep"), key=lambda e: int(e.id.split("-")[2]))
    picks += [("phase-1 incumbent (autonomous)", inc1.id), ("phase-2 incumbent (human-approved hardware)", inc2.id)]
    for label, i in picks:
        e = by[i]
        c = attl.confirm(e.config, e.details["params"], n_conf)
        cc = e.config["ctrl"]
        out.append({"label": label, "id": e.id, "family": cc["family"], "allocation": cc["allocation"],
                    "train_samples": cc["train_samples"], "hw": e.config["hw"], "nominal_ok": e.details["nominal_ok"],
                    "success_rate": c["success_rate"], "k": c["k"], "n": c["n"], "ci": [c["ci_low"], c["ci_high"]],
                    "fuel_Ns": c["fuel_mean"]})
    return out


def family_sweep(article: str, n_conf: int, seeds=(101, 202, 303)) -> dict:
    res = {}
    for fam in ("schedule", "pd", "hybrid"):
        c = attl.baseline_config(article)
        c["ctrl"]["family"] = fam
        rs = []
        for s in seeds:
            tr = att.train(attl.hw_of(c), c["ctrl"], attl.TRAIN_ROLLOUTS, s)
            m = att.mc_eval(attl.hw_of(c), c["ctrl"], tr["params"],
                            att.sample_disturbances(att.CONFIRM_SEED, n_conf, attl._spec(c), article))
            rs.append(m["success_rate"])
        res[fam] = {"seeds": list(seeds), "success_rate": rs, "mean": float(np.mean(rs))}
    return res


def run_article(article: str, n_conf: int, t_budget: dict) -> dict:
    t = time.time()
    led = Ledger()  # in-memory; rows are what gets published
    pre = PRESETS[article]
    res = attl.run_attitude(led, article=article, prefix="att", verbose=True)
    conf = confirm_rows(led.entries, article, n_conf)
    fams = family_sweep(article, n_conf)
    from kinetra_engine.autoresearch.article import Article
    a = Article(article)
    t_budget[article] = time.time() - t
    rows = led.rows()
    return {
        "article": {"id": article, "mass_kg": pre.mass, "box_m": list(pre.box_full), "Iyy_kgm2": a.inertia_y_nominal,
                    "thruster_N": pre.fmax, "pitch_arm_m": pre.arm, "pitch_torque_max_Nm": a.nominal_torque,
                    "alpha_max_rad_s2": a.alpha_nominal},
        "chain_verified": bool(led.verify_chain() and verify_rows(rows)),
        "head_hash": led.head_hash,
        "entries": rows,
        "confirmation": conf,
        "family_seeds": fams,
        "counts": {d: sum(1 for e in led.entries if e.decision == d) for d in ("keep", "discard", "crash", "gated")},
        "wall_s": time.time() - t,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "apps" / "web" / "public" / "demo" / "autoresearch"))
    ap.add_argument("--quick", action="store_true", help="fewer confirmation/bootstrap samples (dev only)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n_conf = 60 if args.quick else 200
    boot_k = 4 if args.quick else 16
    n_int = 60 if args.quick else 200
    t_all = time.time()
    walls: dict = {}

    # ============================================================ attitude: toy 10 kg (primary) + roadster-scale
    say("== attitude autoresearch: toy10")
    toy = run_article("toy10", n_conf, walls)
    say("== attitude autoresearch: roadster-scale article")
    rs = run_article("roadster", n_conf, walls)

    # ============================================================ excitation design
    say("== excitation design")
    t = time.time()
    led_exc = Ledger()
    r = run_loop("exc", exc.BASELINE, exc.ExcitationEvaluator(), exc.ExcitationProposer(), led_exc, max_experiments=12,
                 base_seed=3, verbose=True)
    inc_exc = r["incumbent"]
    campaign = inc_exc.config["excitation"]["trials"]
    first = led_exc.entries[0]
    per_trial = []
    prev = 0.0
    for i, tr in enumerate(campaign):
        cum, _ = exc.eig_of(campaign[: i + 1], seed=7)
        alone, _ = exc.eig_of([tr], seed=7)
        per_trial.append({"name": tr["name"], "T_s": tr["T"], "added_mass_kg": tr.get("added_mass", 0.0),
                          "eig_alone_nats": alone, "eig_cumulative_nats": cum, "marginal_gain_nats": cum - prev,
                          "trial": tr})
        prev = cum
    walls["excitation"] = time.time() - t
    excitation_json = {
        "kind": "excitation_design", "unit": "nats", "note": NOTE_SYNTH + " EIG = 1/2 mean logdet(I + J^T J) over 3 prior-drawn "
        "points, J = Jacobian of noise-whitened residuals (pos 2 mm, attitude 3 mrad @ 50 Hz) w.r.t. prior-sd-normalised parameters. "
        "This is a RECOMMENDATION for a human to run on a rig; nothing was run on hardware.",
        "baseline_eig": first.value, "recommended_eig": inc_exc.value,
        "campaign": [x["name"] for x in campaign], "rig_time_s": sum(x["T"] for x in campaign),
        "budget": {"max_time_s": exc.MAX_TIME, "max_trials": exc.MAX_TRIALS},
        "per_trial": per_trial,
        "n_identified": {"baseline": first.details["n_identified"], "recommended": inc_exc.details["n_identified"], "of": len(PARAM_KEYS)},
        "per_param": {k: {"baseline": first.details["contraction"][k], "recommended": inc_exc.details["contraction"][k]} for k in PARAM_KEYS},
        "entries": led_exc.rows(), "chain_verified": bool(led_exc.verify_chain() and verify_rows(led_exc.rows())),
        "head_hash": led_exc.head_hash,
    }

    # ============================================================ calibration autoresearch
    say("== calibration autoresearch (synthetic truth)")
    t = time.time()
    led_cal = Ledger()
    inc_cal = calloop.run_calibration(led_cal, campaign, verbose=True)
    rep = calloop.calibration_report(inc_cal.config, source="calibration autoresearch on synthetic trace (hidden truth + noise)", boot_k=boot_k)
    cal_doc = calloop.calibration_doc(rep, "recommended campaign: " + ", ".join(x["name"] for x in campaign))
    cal_doc["schema_check"] = calib.validate_assumptions(rep["assumptions"])
    cal_doc["trajectory_compare"] = calloop.trajectory_compare(rep["fit"], calloop.VAL_TRIALS[0])
    cal_doc["trajectory_compare_drop"] = calloop.trajectory_compare(rep["fit"], calloop.VAL_TRIALS[1])
    cfg_bad = copy.deepcopy(calloop.BASELINE)
    cfg_bad["fit"]["free"] = list(PARAM_KEYS)
    rep_bad = calloop.calibration_report(cfg_bad, source="couple-only campaign (failure case)", boot_k=boot_k)
    bad = calloop.calibration_doc(rep_bad, "couple-only campaign (failure case: contact + others not excited)")
    bad["not_identified"] = [k for k, s in rep_bad["status"].items() if s["status"] == "NOT_identified"]
    bad["weak"] = [k for k, s in rep_bad["status"].items() if s["status"] == "weak"]
    bad["trajectory_compare"] = calloop.trajectory_compare(rep_bad["fit"], calloop.VAL_TRIALS[1])
    bad["lesson"] = ("Good train RMS does not mean identified: held-out RMS is far above train RMS and the listed parameters keep "
                     "their prior (std unchanged, confidence=low).")
    cal_doc["failure_case"] = bad
    cal_doc["entries"] = led_cal.rows()
    cal_doc["chain_verified"] = bool(led_cal.verify_chain() and verify_rows(led_cal.rows()))
    cal_doc["head_hash"] = led_cal.head_hash
    cal_doc["bootstrap_k"] = boot_k
    walls["calibration"] = time.time() - t

    # ============================================================ verdict integration
    say("== verdict integration")
    t = time.time()
    _, rows = integration.verdict_table(rep["assumptions"], n_mc=n_int)
    tight = {}
    for te in (2.7, 2.5):
        _, rt = integration.verdict_table(rep["assumptions"], n_mc=max(40, n_int // 2), t_end=te)
        tight[str(te)] = rt

    def pack(rs_, window):
        return [{"family": r["family"], "label": r["label"], "stage": "after" if r["label"].startswith("after") else "before",
                 "p": r["p"], "ci": list(r["ci"]), "ci_width": r["ci"][1] - r["ci"][0], "k": r["k"], "n": r["n"],
                 "fuel": r["fuel"], "truth_ok": bool(r["truth_ok"]), "truth_err_deg": r["truth_err_deg"],
                 "nominal_ok": bool(r["nom_ok"]), "window_s": window} for r in rs_]

    integration_json = {
        "kind": "verdict_integration",
        "note": NOTE_SYNTH + " 'before' = prior assumptions panel (llm_estimate, wide); 'after' = calibrated posterior "
        "(approval gate B assumed granted). Controller is re-searched on each panel's nominal values; p_success = Monte-Carlo "
        "over the panel's distributions + common unmodelled disturbances; CI = Wilson 95%. 'truth_ok' is evaluated at the HIDDEN "
        "synthetic truth and is a sanity check, not a verdict input.",
        "rows": pack(rows, 3.6),
        "tight_windows": {k: pack(v, float(k)) for k, v in tight.items()},
        "n_mc": n_int,
    }
    walls["integration"] = time.time() - t

    # ============================================================ ledger.json (attitude, primary = toy10)
    ledger_json = {
        "kind": "attitude_ledger", "metric_name": "mc_success_rate - 1e-4*fuel_Ns(toy-normalised)",
        "note": NOTE_SYNTH + " Rule proposer walks a hand-written hypothesis list, so 'discovery' = the order evaluated and the "
        "keep/discard evidence. The LLM proposer is code only (off by default, never run). 'Human approval' of the hardware "
        "class is simulated by a dict entry.",
        "article": toy["article"], "chain_verified": toy["chain_verified"], "head_hash": toy["head_hash"],
        "entries": toy["entries"], "confirmation": toy["confirmation"], "family_seeds": toy["family_seeds"], "counts": toy["counts"],
        "excitation_entries": excitation_json["entries"], "excitation_chain_verified": excitation_json["chain_verified"],
        "calibration_entries": cal_doc["entries"], "calibration_chain_verified": cal_doc["chain_verified"],
        "roadster_scale": {k: rs[k] for k in ("article", "chain_verified", "head_hash", "entries", "confirmation", "family_seeds", "counts")},
        "versions": versions(),
    }
    ledger_json["roadster_scale"]["note"] = (
        "Same loop on a rigid 1300 kg box with thrusters at +-2.1 m (Roadster spike pitch-axis numbers; Iyy 2085 kg m^2). "
        "Not the Roadster template and not a real vehicle. Controller gains are in normalised-command units, so no retuning of "
        "the controller structure or bounds was needed; COM-offset disturbance was scaled x4.2 with body length.")

    for name, doc in (("ledger.json", ledger_json), ("calibration.json", cal_doc), ("integration.json", integration_json),
                      ("excitation.json", excitation_json)):
        with open(out / name, "w") as f:
            json.dump(jsonable(doc) if name != "ledger.json" else jsonable(doc), f, separators=(",", ":"))
        say(f"wrote {out / name} ({(out / name).stat().st_size / 1e3:.0f} kB)")

    wall = time.time() - t_all
    say("\n===== SUMMARY")
    for tag, A in (("toy10", toy), ("roadster", rs)):
        say(f"[{tag}] chain {A['chain_verified']} counts {A['counts']} wall {A['wall_s']:.0f}s")
        for c in A["confirmation"]:
            say(f"   {c['id']:<10} {c['family']:<8} {c['success_rate']:.3f} ({c['k']}/{c['n']}) CI [{c['ci'][0]:.3f},{c['ci'][1]:.3f}] fuel {c['fuel_Ns']:.1f}  {c['label']}")
        say("   family seeds: " + "; ".join(f"{f}={[round(x, 3) for x in v['success_rate']]}" for f, v in A["family_seeds"].items()))
    say(f"[excitation] EIG {excitation_json['baseline_eig']:.2f} -> {excitation_json['recommended_eig']:.2f} nats; identified "
        f"{excitation_json['n_identified']}; campaign {excitation_json['campaign']} ({excitation_json['rig_time_s']:.1f}s)")
    say("[calibration] train/val RMS %.3f/%.3f cond %.3g; coverage %d/9; failure case NOT_identified=%s, val RMS %.2f (train %.2f)" % (
        rep["train_rms"], rep["val_rms"], rep["idn"]["cond"], sum(v["within_2sd"] for v in rep["coverage"].values()),
        bad["not_identified"], rep_bad["val_rms"], rep_bad["train_rms"]))
    for r_ in integration_json["rows"]:
        say(f"[integration] {r_['family']:<8} {r_['stage']:<6} p={r_['p']:.3f} CI [{r_['ci'][0]:.3f},{r_['ci'][1]:.3f}] truth_ok={r_['truth_ok']}")
    say(f"phase wall: { {k: round(v) for k, v in walls.items()} }; TOTAL {wall:.0f}s")
    att.shutdown_pool()


if __name__ == "__main__":
    main()
