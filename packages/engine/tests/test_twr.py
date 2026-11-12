"""X-07: thrust-to-weight on earth, mars and moon and burn time per thruster, before a run (L0).

`uv run pytest packages/engine -q -k twr`. Expected numbers are hand calculations, not read back from the code under test:
the design is X-01c's rocket (`test_thrust.py`: library `tank` at its default size on a library VACCO 48003040, exhaust down),
whose masses that test checks against MuJoCo's `body_mass`. The gravities are written out from `docs/architecture/bodies.md`
(9.80665, 3.73, 1.62 m/s^2), so a changed data file also fails here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from gltf_samples import catalog_material, library_part
from test_thrust import CAPACITY, FLIP_X, FLOW, JET_Z, M_PLATE, M_TANK, M_THRUSTER, TANK_ON_JET_Z, F, instance, on_plate, rocket, weld

from kinetra_core import Badge, PartDef, Project, check_placement
from kinetra_engine.statics import BADGE_STRENGTH, NoValue, thrust_to_weight, weakest
from kinetra_engine.statics.twr import ASSUMPTIONS, GRADE, GRADE_LABEL

ROOT = Path(__file__).resolve().parents[3]
G = {"earth": 9.80665, "mars": 3.73, "moon": 1.62}  # m/s^2, docs/architecture/bodies.md (data/bodies, all `인용`)
M_TOTAL = M_TANK + M_THRUSTER + CAPACITY  # dry tank + thruster + full tank, kg


def badges(value, name):
    return next(r.badges for r in value.inputs if r.input == name)


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_twr_rocket_matches_the_hand_calculation_on_each_planet(planet):
    r = thrust_to_weight(rocket([]).design)
    ratio = next(p for p in r.ratios if p.planet == planet)
    assert ratio.gravity.value == G[planet]
    assert ratio.ratio.value == pytest.approx(F / (M_TOTAL * G[planet]), rel=1e-12)
    assert ratio.ratio.grade == "L0"


def test_twr_rocket_mass_thrust_burn_time_and_the_three_planets_in_order():
    r = thrust_to_weight(rocket([]).design)
    assert r.reason is None
    assert [p.planet for p in r.ratios] == ["earth", "mars", "moon"]
    assert r.mass.value == pytest.approx(M_TOTAL, rel=1e-12)
    assert r.thrust is not None and r.thrust.value == pytest.approx(F, rel=1e-12)
    (burn,) = r.burns
    assert (burn.actuator, burn.instance, burn.tank, burn.shared_with, burn.reason) == ("main", "jet", "tank", (), None)
    assert burn.mass_flow.value == pytest.approx(FLOW, rel=1e-12)
    assert burn.burn_time is not None
    assert burn.burn_time.value == pytest.approx(CAPACITY / FLOW, rel=1e-12)  # 163.50 s
    # the same design weighs the same everywhere: ratio x g is one number on all three planets
    earth, mars, moon = (p.ratio.value * G[p.planet] for p in r.ratios)
    assert mars == pytest.approx(earth, rel=1e-12)
    assert moon == pytest.approx(earth, rel=1e-12)


def test_twr_badges_carry_every_input_and_the_result_follows_the_weakest():
    r = thrust_to_weight(rocket([]).design)
    # dry mass: aluminium density and the VACCO weight `인용`, the tank recipe `기본값`, the VACCO outer shape `추정`
    # (parts-thruster.md); the propellant: the 1000 kg/m^3 placeholder density `기본값` (parts-battery-tank.md)
    assert badges(r.mass, "dry_mass") == (Badge.CITE, Badge.DEFAULT, Badge.ESTIMATE)
    assert badges(r.mass, "propellant") == (Badge.DEFAULT,)
    assert r.mass.badge is Badge.ESTIMATE
    assert r.thrust is not None and r.thrust.badge is Badge.CITE  # rated thrust from the datasheet
    for p in r.ratios:
        assert badges(p.ratio, "gravity") == (p.gravity.badge,) == (Badge.CITE,)
        assert badges(p.ratio, "mass") == (Badge.CITE, Badge.DEFAULT, Badge.ESTIMATE)
        assert badges(p.ratio, "thrust") == (Badge.CITE,)
        assert p.ratio.badge is Badge.ESTIMATE  # the weakest input, not `sim`
    burn = r.burns[0].burn_time
    assert burn is not None
    assert badges(burn, "propellant") == (Badge.DEFAULT,)
    assert badges(burn, "propellant_flow") == (Badge.CITE,)
    assert burn.badge is Badge.DEFAULT


def test_twr_weakest_ranks_cite_default_declared_estimate():
    assert BADGE_STRENGTH == tuple(Badge)
    assert weakest([Badge.CITE, Badge.DEFAULT]) is Badge.DEFAULT
    assert weakest([Badge.DECLARED, Badge.DEFAULT, Badge.CITE]) is Badge.DECLARED
    assert weakest([Badge.DECLARED, Badge.ESTIMATE]) is Badge.ESTIMATE
    with pytest.raises(ValueError):
        weakest([])


def declared_rocket() -> Project:
    """The rocket with the B-03c example part `thruster-declared-8kn` (rated thrust and flow `사용자 선언`) in place of VACCO."""
    part = PartDef.model_validate_json((ROOT / "schemas/examples/PartDef.thruster-declared-8kn.json").read_text(encoding="utf-8"))
    materials = [catalog_material("al6061-t6").model_dump(mode="json"), catalog_material("steel-a36").model_dump(mode="json")]
    instances = [instance("tank", "tank", at=(0.0, 0.0, TANK_ON_JET_Z), material="al6061-t6"),
                 instance("jet", part.id, at=(0.0, 0.0, JET_Z), quat=FLIP_X, material="steel-a36")]
    proj = Project.model_validate({"design": {
        "materials": materials, "parts": [library_part("tank").model_dump(mode="json"), part.model_dump(mode="json")],
        "instances": instances, "joints": [weld("w", ("jet", "mount"), ("tank", "bottom"))],
        "actuators": [{"id": "main", "kind": "thruster", "instance": "jet", "supply": "tank"}], "schedule": {"entries": []}},
        "world": {"planet": "earth"}})
    assert check_placement(proj) == ()
    return proj


def test_twr_declared_thrust_makes_the_ratio_and_burn_time_declared():
    proj = declared_rocket()
    part = next(p for p in proj.design.parts if p.id == "thruster-declared-8kn")
    specs = {s.name: s for s in part.specs}
    rated, flow = specs["rated_thrust"], specs["propellant_flow"]
    assert (rated.badge, flow.badge) == (Badge.DECLARED, Badge.DECLARED)
    r = thrust_to_weight(proj.design)
    assert r.thrust is not None and badges(r.thrust, "thrust") == (Badge.DECLARED,)
    for p in r.ratios:
        assert p.ratio.value == pytest.approx(rated.value / (r.mass.value * G[p.planet]), rel=1e-12)
        assert badges(p.ratio, "thrust") == (Badge.DECLARED,)
        assert p.ratio.badge is Badge.DECLARED  # weakest: thrust and the declared part's shape (mass)
    burn = r.burns[0].burn_time
    assert burn is not None and burn.value == pytest.approx(CAPACITY / flow.value, rel=1e-12)
    assert burn.badge is Badge.DECLARED  # declared flow is weaker than the default propellant density


def test_twr_design_without_a_thruster_gives_no_ratio_and_says_why():
    proj = rocket([])
    design = proj.design.model_copy(update={"actuators": ()})
    r = thrust_to_weight(design)
    assert r.reason is NoValue.NO_THRUSTER
    assert (r.thrust, r.ratios, r.burns) == (None, (), ())
    assert r.mass.value == pytest.approx(M_TOTAL, rel=1e-12)  # the mass is still given; no 0 stands in for a ratio


def test_twr_thruster_without_propellant_has_no_burn_time_but_a_ratio():
    proj = rocket([])
    design = proj.design.model_copy(update={"actuators": tuple(a.model_copy(update={"supply": None}) for a in proj.design.actuators)})
    r = thrust_to_weight(design)
    (burn,) = r.burns
    assert (burn.tank, burn.burn_time, burn.reason) == (None, None, NoValue.NO_PROPELLANT)
    assert burn.max_thrust.value == pytest.approx(F, rel=1e-12)
    assert r.reason is None
    # the tank is still on the design, full, and still weighs (thrust.md rule 2)
    assert [p.ratio.value for p in r.ratios] == pytest.approx([F / (M_TOTAL * G[p]) for p in ("earth", "mars", "moon")], rel=1e-12)


def test_twr_two_thrusters_on_one_tank_add_thrust_and_share_the_burn():
    a = {"id": "a", "kind": "thruster", "instance": "jet-a", "supply": "tank"}
    b = {"id": "b", "kind": "thruster", "instance": "jet-b", "supply": "tank"}
    r = thrust_to_weight(on_plate([("jet-a", "under-a"), ("jet-b", "under-b")], [a, b], []).design)
    mass = M_TANK + M_PLATE + 2 * M_THRUSTER + CAPACITY
    assert r.mass.value == pytest.approx(mass, rel=1e-12)
    assert r.thrust is not None and r.thrust.value == pytest.approx(2 * F, rel=1e-12)
    for p in r.ratios:
        assert p.ratio.value == pytest.approx(2 * F / (mass * G[p.planet]), rel=1e-12)
    assert [(x.actuator, x.shared_with) for x in r.burns] == [("a", ("b",)), ("b", ("a",))]
    for x in r.burns:
        assert x.burn_time is not None and x.burn_time.value == pytest.approx(CAPACITY / (2 * FLOW), rel=1e-12)


def test_twr_curve_peak_above_the_rated_thrust_is_the_maximum_with_the_curve_badge():
    vacco = library_part("thruster-vacco-48003040").model_dump(mode="json")
    curve = vacco["curves"][0]["curve"]
    rise = curve["points"][1]["x"]  # the cited 7 ms opening: unchanged, so the part stays valid
    curve["points"] = [{"x": 0.0, "y": 0.0}, {"x": rise, "y": F}, {"x": 2 * rise, "y": 1.5 * F}, {"x": 3 * rise, "y": F}]
    proj = rocket([])
    parts = tuple(PartDef.model_validate(vacco) if p.id == "thruster-vacco-48003040" else p for p in proj.design.parts)
    r = thrust_to_weight(proj.design.model_copy(update={"parts": parts}))
    (burn,) = r.burns
    assert burn.max_thrust.value == pytest.approx(1.5 * F, rel=1e-12)
    assert badges(burn.max_thrust, "thrust") == (Badge(curve["badge"]),)
    assert burn.mass_flow.value == pytest.approx(1.5 * FLOW, rel=1e-12)  # flow in proportion to thrust (B-03c)
    assert burn.burn_time is not None and burn.burn_time.value == pytest.approx(CAPACITY / (1.5 * FLOW), rel=1e-12)


def test_twr_gravity_comes_from_the_planet_data_files(tmp_path):
    shutil.copytree(ROOT / "data/bodies", tmp_path, dirs_exist_ok=True)
    earth = json.loads((tmp_path / "earth.json").read_text(encoding="utf-8"))
    earth["gravity"]["value"] = 2 * G["earth"]
    (tmp_path / "earth.json").write_text(json.dumps(earth), encoding="utf-8")
    r = thrust_to_weight(rocket([]).design, bodies_directory=tmp_path)
    ratio = next(p for p in r.ratios if p.planet == "earth")
    assert ratio.ratio.value == pytest.approx(F / (M_TOTAL * 2 * G["earth"]), rel=1e-12)


def test_twr_result_states_its_assumptions_and_grade():
    r = thrust_to_weight(rocket([]).design)
    assert (r.grade, r.grade_label) == (GRADE, GRADE_LABEL) == ("L0", "해석 계산")
    text = " ".join(r.assumptions)
    for phrase in ("추진제 가득", "최대 추력", "대기에 따른 추력 변화 없음", "평지의 균일 중력"):
        assert phrase in text
    assert r.assumptions == ASSUMPTIONS
