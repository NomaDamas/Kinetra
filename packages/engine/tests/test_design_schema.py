"""DesignBrief validators + generated artefacts (bundle files, if built)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from physlab_core.schemas import DesignBrief

from kinetra_engine.design import brief as B

DEMO = Path(__file__).resolve().parents[3] / "apps/web/public/demo"


def minimal():
    comp = dict(id="nozzle", role="thruster", quantity=2,
                choice=dict(name="n", vendor="v", specs={"thrust_N": 7000.0}, mass_kg=1.2, unit_cost_usd=None, source="https://x", verified=False),
                meets=[dict(requirement_id="r1", required=6250.0, provided=7000.0, unit="N", margin=0.12, ok=True)], ok=True, alternatives=[], custom=False,
                needs_sourcing=False, mass_kg_each=1.2, mass_source="catalog", note="", cad=None)
    return dict(scenario_id="x", template="rocket_car", base_variant=5000.0, headline="h",
                requirements=[dict(id="r1", label="l", value=5000.0, unit="N", derived_from="d", margin_factor=1.25, required=6250.0, source="simulation")],
                components=[comp], custom_parts=[],
                closed_loop=[dict(iteration=0, mass_kg=1300.0, status="FEASIBLE_FOUND", p_success=0.4, ci=[0.3, 0.5], n=500, note="")],
                alternatives=[], risks=[], next_tests=[],
                totals=dict(mass_added_kg=2.4, mass_estimated_kg=0.0, cost_priced_usd=None, unpriced_lines=1), labels=[],
                reproducibility=dict(seed=1, engine="e", mujoco="4", generated_at="t"))


def test_minimal_valid():
    DesignBrief.model_validate(minimal())


def test_required_must_equal_value_times_margin():
    d = minimal(); d["requirements"][0]["required"] = 7000.0
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)


def test_component_ok_iff_all_meets_ok():
    d = minimal(); d["components"][0]["meets"][0].update(provided=6000.0, margin=-0.04, ok=False)
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)               # ok=True but a meets row fails
    d["components"][0]["ok"] = False
    DesignBrief.model_validate(d)                   # honest failure is representable


def test_meets_ok_must_match_numbers():
    d = minimal(); d["components"][0]["meets"][0]["ok"] = False
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)


def test_no_choice_requires_custom_or_sourcing():
    d = minimal(); c = d["components"][0]; c.update(choice=None, meets=[], ok=False)
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)
    c["needs_sourcing"] = True
    DesignBrief.model_validate(d)


def test_unpriced_lines_counted_not_zero():
    d = minimal(); d["totals"]["unpriced_lines"] = 0
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)
    d = minimal(); d["components"][0]["choice"]["unit_cost_usd"] = 10.0; d["totals"].update(unpriced_lines=0, cost_priced_usd=20.0)
    DesignBrief.model_validate(d)
    d["totals"]["cost_priced_usd"] = None
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)


def test_closed_loop_iterations_must_be_sequential_and_checks_labelled():
    d = minimal(); d["closed_loop"][0]["iteration"] = 1
    with pytest.raises(ValidationError):
        DesignBrief.model_validate(d)
    from physlab_core.schemas import DesignCheck
    with pytest.raises(ValidationError):
        DesignCheck(method="m", stress_MPa=1.0, allow_MPa=2.0, ok=True, label="fine")


def test_exports_render():
    b = DesignBrief.model_validate(minimal()).model_dump(mode="json")
    assert "nozzle" in B.bom_csv(b) and "Design brief" in B.brief_md(b)
    assert "needs sourcing" not in B.bom_csv(b).splitlines()[1]


@pytest.mark.parametrize("sid", ["roadster", "humanoid"])
def test_built_bundle_validates_and_has_real_closed_loop(sid):
    p = DEMO / sid / "design.json"
    if not p.exists():
        pytest.skip("design bundle not built")
    b = DesignBrief.model_validate(json.loads(p.read_text()))
    assert len(b.closed_loop) >= 2 and all(i.n_evals > 0 for i in b.closed_loop[1:])      # real re-runs carry real eval counts
    for cp in b.custom_parts:
        assert (DEMO / sid / cp.cad_stl).exists() and cp.check.label == "simplified model, needs FEA"
    assert (DEMO / sid / "export/bom.csv").exists() and (DEMO / sid / "export/design-brief.md").exists()
