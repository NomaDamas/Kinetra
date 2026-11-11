"""B-03c: thruster part (`parts/library/thruster-vacco-48003040.json`) and `kinetra_engine.parts.thruster`.

Expected values are hand calculations from the datasheet numbers (VACCO 48003040: 2.0 lbf, 0.0267 lbm/s, 0.83 lbm, opening
response 7 ms), not read from the code. 1 lbf = 4.4482216152605 N, 1 lbm = 0.45359237 kg (exact definitions), g0 = 9.80665 m/s^2.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from gltf_samples import catalog_material
from gltf_validate import validate

from kinetra_core import Badge, PartDef, PartRole
from kinetra_engine.parts import (
    ThrusterError,
    burn,
    catalog_finding,
    mass_properties,
    part_glb,
    thruster_from_part,
)
from kinetra_engine.parts import collision_proxy
from kinetra_engine.parts.thruster import catalog_thrusts

ROOT = Path(__file__).resolve().parents[3]
LIBRARY = ROOT / "packages/engine/src/kinetra_engine/parts/library/thruster-vacco-48003040.json"
EXAMPLE_8KN = ROOT / "schemas/examples/PartDef.thruster-declared-8kn.json"

LBF, LBM, G0 = 4.4482216152605, 0.45359237, 9.80665
F = 2.0 * LBF  # 8.896443230521 N
FLOW = 0.0267 * LBM  # 0.012110916279 kg/s
T_OPEN = 0.007  # s, the cited opening response
STEEL = catalog_material("steel-a36")


@pytest.fixture(scope="module")
def vacco() -> PartDef:
    return PartDef.model_validate_json(LIBRARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def th(vacco):
    return thruster_from_part(vacco)


def raw(path: Path = LIBRARY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def reject(d: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        PartDef.model_validate(d)


# --- numbers and badges ---------------------------------------------------------------------------------------------


def test_thruster_part_numbers_are_the_datasheet_numbers(vacco, th):
    assert vacco.role is PartRole.THRUSTER
    assert th.rated_thrust == pytest.approx(8.896443230521, rel=1e-12)
    assert th.propellant_flow == pytest.approx(0.012110916279, rel=1e-12)
    # I_sp = F / (mdot g0) = 2.0 lbf / (0.0267 lbm/s) with lbf = lbm g0: 74.9064 s
    assert th.specific_impulse == pytest.approx(2.0 / 0.0267, rel=1e-12)
    assert th.exhaust_velocity == pytest.approx(2.0 / 0.0267 * G0, rel=1e-12)


def test_thruster_part_every_spec_is_cited_with_a_locator_in_the_datasheet(vacco):
    by = {s.name: s for s in vacco.specs}
    assert set(by) == {"rated_thrust", "propellant_flow", "mass", "opening_response", "closing_response"}
    for s in by.values():
        assert s.badge is Badge.CITE
        assert s.source.url == "https://www.vacco.com/images/uploads/pdfs/cold_gas_thrusters.pdf"
        assert s.source.locator
    assert by["mass"].value == pytest.approx(0.83 * LBM, rel=1e-12)


def test_thruster_part_curve_shape_is_an_estimate_and_says_so(vacco):
    curve = vacco.curves[0].curve
    assert vacco.curves[0].name == "thrust"
    assert curve.badge is Badge.ESTIMATE  # the datasheet gives the 7 ms opening time, not the shape of the rise
    assert [(p.x, p.y) for p in curve.points] == [(0.0, 0.0), (T_OPEN, pytest.approx(F, rel=1e-12))]
    assert "7 ms" in curve.source.ref
    assert vacco.shape.badge is Badge.ESTIMATE  # the datasheet gives no dimensions


def test_thruster_part_mass_is_the_datasheet_weight(vacco):
    r = mass_properties(vacco, STEEL)
    assert r.mass.value == pytest.approx(0.83 * LBM, rel=1e-9)  # 0.376481667 kg
    # the cylinders are coaxial on z: no off-axis centre of mass or product of inertia
    assert r.center_of_mass.x == pytest.approx(0.0, abs=1e-15)
    assert r.center_of_mass.y == pytest.approx(0.0, abs=1e-15)
    assert r.inertia.ixy == r.inertia.ixz == r.inertia.iyz == 0.0


def test_thruster_part_has_a_proxy_and_a_valid_glb(vacco):
    proxy = collision_proxy(vacco)
    assert len(proxy.geoms) == 3 and proxy.volume_error.value == pytest.approx(0.0, abs=1e-12)
    validate(part_glb(vacco, STEEL))


# --- direction ------------------------------------------------------------------------------------------------------


def test_thruster_force_is_opposite_the_exhaust_which_is_the_nozzle_z(th):
    assert th.direction == pytest.approx((0.0, 0.0, -1.0), abs=1e-15)
    fx, fy, fz = th.force(1.0, 0.5)
    assert (fx, fy) == (0.0, 0.0) and fz == pytest.approx(-0.5 * F, rel=1e-12)


def test_thruster_nozzle_position_is_half_the_part_length_from_the_centre(vacco, th):
    # total length = body + neck + bell; the shape is centred on the origin by the generator, so the exit is at +L/2
    lengths = []
    for c in vacco.shape.components:
        lengths.append(c.primitive.length.offset)
    assert th.position == (0.0, 0.0, pytest.approx(sum(lengths) / 2, rel=1e-12))


def test_thruster_direction_follows_a_turned_nozzle_frame(vacco):
    # nozzle frame turned 90 degrees about y: its +z becomes the part's +x, so the force on the part is along -x
    d = raw()
    s2 = math.sqrt(0.5)
    for sp in d["snap_points"]:
        if sp["id"] == "nozzle":
            sp["orientation"] = {"x": 0.0, "y": s2, "z": 0.0, "w": s2}
    t = thruster_from_part(PartDef.model_validate(d))
    assert t.direction == pytest.approx((-1.0, 0.0, 0.0), abs=1e-12)


# --- impulse = thrust x time ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("duration", [0.007, 0.5, 2.0, 10.0])
def test_thruster_impulse_is_thrust_times_time_with_the_ramp_taken_out(th, duration):
    # F t minus the area the 7 ms linear rise misses: F * T_open / 2
    expected = F * (duration - T_OPEN / 2)
    b = burn(th, duration)
    assert b.impulse == pytest.approx(expected, rel=1e-12)
    assert b.propellant_used == pytest.approx(FLOW * (duration - T_OPEN / 2), rel=1e-12)
    assert b.duration == duration and not b.depleted and b.badge is Badge.SIM


def test_thruster_impulse_inside_the_ramp_is_the_triangle(th):
    t = 0.003
    assert burn(th, t).impulse == pytest.approx(0.5 * (F * t / T_OPEN) * t, rel=1e-12)


def test_thruster_impulse_scales_with_the_command(th):
    # command c scales the whole curve: impulse = c F (T - T_open/2)
    assert burn(th, 2.0, command=0.25).impulse == pytest.approx(0.25 * F * (2.0 - T_OPEN / 2), rel=1e-12)
    assert burn(th, 2.0, command=0.0).impulse == 0.0
    assert burn(th, 0.0).impulse == 0.0


def test_thruster_impulse_is_the_numerical_integral_of_the_thrust(th):
    n, T = 200_000, 0.02  # midpoint rule over the ramp and past it
    h = T / n
    assert sum(th.thrust((i + 0.5) * h) for i in range(n)) * h == pytest.approx(burn(th, T).impulse, rel=1e-9)


def test_thruster_impulse_equals_exhaust_velocity_times_propellant_used(th):
    # Delta v of the thrust is v_e x ln(m0/m1); here the impulse itself: J = v_e * m_used
    b = burn(th, 3.0)
    assert b.impulse == pytest.approx(th.exhaust_velocity * b.propellant_used, rel=1e-12)


def test_thruster_thrust_and_flow_at_points(th):
    assert th.thrust(-1.0) == 0.0 and th.thrust(0.0) == 0.0
    assert th.thrust(T_OPEN / 2) == pytest.approx(F / 2, rel=1e-12)
    assert th.thrust(T_OPEN) == pytest.approx(F, rel=1e-12)
    assert th.thrust(100.0) == pytest.approx(F, rel=1e-12)  # steady after the table
    assert th.mass_flow(100.0) == pytest.approx(FLOW, rel=1e-12)
    assert th.mass_flow(100.0, 0.5) == pytest.approx(FLOW / 2, rel=1e-12)


# --- propellant draw ------------------------------------------------------------------------------------------------


def test_thruster_stops_when_the_propellant_is_gone_and_never_overdraws(th):
    m = 0.01  # kg
    b = burn(th, 2.0, propellant=m)
    assert b.depleted and b.propellant_used == pytest.approx(m, rel=1e-12)
    # J = m v_e; steady after the ramp: t = T_open/2 + J / F
    j = m * 2.0 / 0.0267 * G0
    assert b.impulse == pytest.approx(j, rel=1e-12)
    assert b.duration == pytest.approx(T_OPEN / 2 + j / F, rel=1e-12)
    assert b.duration < 2.0


def test_thruster_runs_dry_inside_the_ramp(th):
    # propellant for 1e-3 N*s of impulse: 0.5 * (F/T_open) t^2 = 1e-3
    m = 1e-3 * FLOW / F
    b = burn(th, 1.0, propellant=m)
    assert b.depleted
    assert b.duration == pytest.approx(math.sqrt(2e-3 * T_OPEN / F), rel=1e-12)
    assert b.duration < T_OPEN


def test_thruster_with_enough_propellant_is_not_depleted(th):
    b = burn(th, 2.0, propellant=1.0)
    assert not b.depleted and b.duration == 2.0
    assert burn(th, 2.0, propellant=0.0).duration == 0.0 and burn(th, 2.0, propellant=0.0).depleted


def test_thruster_rejects_bad_command_duration_propellant(th):
    for kw in ({"command": 1.5}, {"command": -0.1}):
        with pytest.raises(ThrusterError, match="fraction"):
            burn(th, 1.0, **kw)
    with pytest.raises(ThrusterError):
        th.thrust(1.0, 2.0)
    for bad in (-1.0, math.inf, math.nan):
        with pytest.raises(ThrusterError, match="duration"):
            burn(th, bad)
    with pytest.raises(ThrusterError, match="propellant"):
        burn(th, 1.0, propellant=-1.0)


# --- the catalog range: 카탈로그 밖 · 사용자 선언 ---------------------------------------------------------------------


def test_thruster_catalog_range_is_the_cited_thrusts():
    values = sorted(q.value for q in catalog_thrusts())
    assert values[0] == pytest.approx(0.010) and values[-1] == pytest.approx(F, rel=1e-12)
    assert all(q.badge is Badge.CITE and q.source.url and q.source.locator for q in catalog_thrusts())


def test_thruster_cited_part_is_in_the_catalog_with_its_own_badge(vacco):
    f = catalog_finding(vacco)
    assert f.in_catalog and f.badge is Badge.CITE and f.label == "인용"
    assert (f.catalog_min, f.catalog_max) == (pytest.approx(0.010), pytest.approx(F, rel=1e-12))


def test_thruster_declared_8_kn_is_out_of_the_catalog():
    part = PartDef.model_validate_json(EXAMPLE_8KN.read_text(encoding="utf-8"))
    f = catalog_finding(part)
    assert f.value == 8000.0 and not f.in_catalog
    assert f.badge is Badge.DECLARED and f.label == "카탈로그 밖 · 사용자 선언"
    # the same impulse = thrust x time holds for the declared part: 8000 N for 2 s, 50 ms rise
    t = thruster_from_part(part)
    assert burn(t, 2.0).impulse == pytest.approx(8000.0 * (2.0 - 0.05 / 2), rel=1e-12)


def test_thruster_declared_value_inside_the_range_stays_declared():
    d = raw()
    for s in d["specs"]:
        if s["name"] == "rated_thrust":
            s.update(value=3.0, badge="declared", source={"ref": "test"})
            s.pop("locator", None)
    d["curves"][0]["curve"]["points"][-1]["y"] = 3.0
    f = catalog_finding(PartDef.model_validate(d))
    assert f.in_catalog and f.label == "사용자 선언"  # in the range does not make it cited


def test_thruster_catalog_finding_needs_a_thruster():
    block = PartDef.model_validate_json((ROOT / "schemas/examples/PartDef.block-with-hole.json").read_text(encoding="utf-8"))
    with pytest.raises(ThrusterError, match="not a thruster"):
        catalog_finding(block)
    with pytest.raises(ThrusterError, match="not 'thruster'"):
        thruster_from_part(block)


# --- what a thruster part must have ---------------------------------------------------------------------------------


def mutated(fn) -> dict:
    d = copy.deepcopy(raw())
    fn(d)
    return d


def test_thruster_part_without_its_curve_is_rejected():
    reject(mutated(lambda d: d.update(curves=[])), "needs the curve 'thrust'")


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (lambda c: c.update(x_unit="rad/s"), "time \\[s\\] -> thrust \\[N\\]"),
        (lambda c: c.update(y_unit="N*m"), "time \\[s\\] -> thrust \\[N\\]"),
        (lambda c: c["points"].__setitem__(0, {"x": 0.001, "y": 0.0}), "starts at time 0"),
        (lambda c: c["points"].insert(1, {"x": 0.003, "y": -1.0}), "must not be negative"),
        (lambda c: c["points"].__setitem__(-1, {"x": 0.007, "y": 0.0}), "must be positive"),
    ],
)
def test_thruster_part_with_a_bad_curve_is_rejected(edit, match):
    reject(mutated(lambda d: edit(d["curves"][0]["curve"])), match)


def test_thruster_part_without_rated_thrust_or_flow_is_rejected():
    reject(mutated(lambda d: d.update(specs=[s for s in d["specs"] if s["name"] != "rated_thrust"])), "needs the spec 'rated_thrust'")
    reject(mutated(lambda d: d.update(specs=[s for s in d["specs"] if s["name"] != "propellant_flow"])), "needs the spec 'propellant_flow'")


def test_thruster_part_with_a_flow_in_the_wrong_unit_or_not_positive_is_rejected():
    def unit(d):
        for s in d["specs"]:
            if s["name"] == "propellant_flow":
                s["unit"] = "kg"

    def zero(d):
        for s in d["specs"]:
            if s["name"] == "propellant_flow":
                s["value"] = 0.0

    reject(mutated(unit), "positive in 'kg/s'")
    reject(mutated(zero), "positive in 'kg/s'")


def test_thruster_rated_thrust_must_equal_the_steady_end_of_the_curve():
    def edit(d):
        d["curves"][0]["curve"]["points"][-1]["y"] = 9.0

    reject(mutated(edit), "must equal the last point")


def test_thruster_part_without_a_nozzle_is_rejected():
    reject(mutated(lambda d: d.update(snap_points=[s for s in d["snap_points"] if s["id"] != "nozzle"])), "needs the snap point 'nozzle'")


def test_thruster_part_has_no_propellant_chemistry_field():
    # safety line (docs/process/review-rubric.md 1): the definition names no propellant composition, combustion or nozzle-flow value
    names = {s["name"] for s in raw()["specs"]} | {c["name"] for c in raw()["curves"]}
    assert not any(w in n for n in names for w in ("chamber", "combust", "mixture", "composition", "nozzle_flow", "oxidizer"))


# --- in a design ----------------------------------------------------------------------------------------------------


def rocket_car(part: dict) -> dict:
    """The rocket-car skeleton example with its `rocket` part replaced by `part` (under the id the instance uses)."""
    d = json.loads((ROOT / "schemas/examples/Project.rocket-car-skeleton.json").read_text(encoding="utf-8"))["design"]
    old = next(p for p in d["parts"] if p["id"] == "rocket")
    snaps = [s for s in old["snap_points"] if s["id"] not in {x["id"] for x in part["snap_points"]}]
    d["parts"] = [p for p in d["parts"] if p["id"] != "rocket"] + [{**part, "id": "rocket", "snap_points": part["snap_points"] + snaps}]
    return d


def test_thruster_part_carries_the_thruster_actuator_of_a_design():
    from kinetra_core import DesignSpec

    spec = DesignSpec.model_validate(rocket_car(raw()))
    assert [a.kind.value for a in spec.actuators] == ["thruster"]
    # the joint to the chassis snap points of the example still resolves: the thruster part keeps the old snap points it lacks
    assert {s.id for s in next(p for p in spec.parts if p.id == "rocket").snap_points} >= {"mount", "nozzle"}


def test_thruster_actuator_on_a_part_of_another_role_is_rejected():
    from kinetra_core import DesignSpec

    d = rocket_car(raw())
    d["parts"][-1]["role"] = "wheel"
    d["parts"][-1].pop("curves")
    with pytest.raises(ValueError, match="a thruster drives a part with role 'thruster'"):
        DesignSpec.model_validate(d)


# --- review findings (#512) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("t", [math.nan, math.inf, -math.inf])
def test_thruster_thrust_rejects_a_time_that_is_not_finite(th, t):
    for call in (th.thrust, th.force, th.mass_flow):
        with pytest.raises(ThrusterError, match="finite"):
            call(t)


def test_thruster_opening_response_spec_equals_the_curve_rise_in_both_parts(vacco):
    declared = PartDef.model_validate_json(EXAMPLE_8KN.read_text(encoding="utf-8"))
    for part in (vacco, declared):
        opening = next(s.value for s in part.specs if s.name == "opening_response")
        points = part.curves[0].curve.points
        rated = next(s.value for s in part.specs if s.name == "rated_thrust")
        assert opening == next(p.x for p in points if p.y == rated)
    assert next(s.value for s in declared.specs if s.name == "opening_response") == 0.05


def test_thruster_opening_response_that_disagrees_with_the_curve_is_rejected():
    def edit(d):
        for s in d["specs"]:
            if s["name"] == "opening_response":
                s["value"] = 0.05  # the curve rises in 7 ms

    reject(mutated(edit), "must equal the time the curve 'thrust' first reaches the rated thrust")


def test_thruster_opening_response_is_checked_against_the_first_time_at_rated_thrust():
    def edit(d):
        d["curves"][0]["curve"]["points"] = [{"x": 0.0, "y": 0.0}, {"x": 0.007, "y": F}, {"x": 1.0, "y": F}]

    PartDef.model_validate(mutated(edit))  # a flat tail after the rise is fine: the spec still names the first time
