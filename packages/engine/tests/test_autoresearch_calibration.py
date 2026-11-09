import copy
import os

os.environ.setdefault("KINETRA_AR_WORKERS", "0")

import numpy as np
import pytest

from kinetra_engine.autoresearch import calib, calibration_loop as cl
from kinetra_engine.autoresearch.article import PARAM_KEYS


def _report(cfg, boot_k=0):
    return cl.calibration_report(cfg, source="test", boot_k=boot_k)


@pytest.fixture(scope="module")
def couple_only():
    cfg = copy.deepcopy(cl.BASELINE)
    cfg["fit"]["free"] = list(PARAM_KEYS)
    return _report(cfg)


def test_non_excited_parameters_not_identified(couple_only):
    st = couple_only["status"]
    # a pure thruster couple in free flight never touches the ground
    assert st["contact_timeconst"]["status"] == "NOT_identified"
    assert st["contact_dampratio"]["status"] == "NOT_identified"
    assert st["contact_timeconst"]["contraction"] > 0.9
    # the prior is kept for them: std unchanged, confidence low, source says so
    by = {a["key"]: a for a in couple_only["assumptions"]}
    for k in ("contact_timeconst", "contact_dampratio"):
        a = by[k]
        mu, sd, _, _ = calib.PRIORS[k]
        assert a["confidence"] == "low" and a["value"] == mu and a["distribution"]["std"] == sd
        assert "NOT identified" in a["source"]
    # a good train fit does not transfer
    assert couple_only["val_rms"] > 1.5 * couple_only["train_rms"]


def test_assumptions_validate_against_core_schema(couple_only):
    assert "Assumption" in calib.validate_assumptions(couple_only["assumptions"])
    doc = cl.calibration_doc(couple_only, "test")
    assert set(doc["identifiability"]) == set(PARAM_KEYS) and "truth" in doc


def test_excited_campaign_identifies_contact():
    from kinetra_engine.autoresearch.excitation import BASELINE_TRIAL, P_, T_
    trials = [BASELINE_TRIAL, T_("single_t0", 2.5, pulses=[P_([0], 0.3, 0.8)]), T_("tilted_drop", 2.0, z0=2.0, pitch0=0.5)]
    datas = cl.make_data(trials, cl.DATA_SEED)
    res = calib.fit(trials, datas, list(PARAM_KEYS))
    idn = calib.identifiability(trials, datas, res["theta"], list(PARAM_KEYS))
    c = dict(zip(idn["params"], idn["contraction"]))
    assert c["contact_timeconst"] < 0.9 and c["contact_dampratio"] < 0.9


def test_calibration_deterministic():
    cfg = copy.deepcopy(cl.BASELINE)
    cfg["fit"]["free"] = ["mass", "inertia_scale", "thrust_gain"]
    a, b = _report(cfg), _report(cfg)
    assert a["fit"] == b["fit"] and a["val_rms"] == b["val_rms"]
    np.testing.assert_array_equal(a["idn"]["contraction"], b["idn"]["contraction"])


def test_trajectory_compare_shape(couple_only):
    tc = cl.trajectory_compare(couple_only["fit"], cl.VAL_TRIALS[0], max_pts=50)
    n = len(tc["t"])
    assert n <= 50 and all(len(tc[k]["pitch_deg"]) == n and len(tc[k]["z"]) == n for k in ("reference", "fitted", "prior"))
