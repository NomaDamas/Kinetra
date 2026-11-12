"""X-01e: the friction of every geom, the combination of two faces (`min`), the contact parameters, and the slip angle on an incline.

`uv run pytest packages/engine -q -k contact_friction`. MuJoCo 4.0.0 runs the compiled MJCF, no seed (deterministic). Hand
calculation: a block at rest on a plane tilted by theta starts to slide when tan(theta) > mu, so the slip angle is atan(mu) and,
sliding, it accelerates at g (sin(theta) - mu cos(theta)) whatever g is. mu is the combined coefficient,
min(mu_part, mu_ground) (`contact.py`). The incline is the planet's gravity turned by theta about y, `g (sin, 0, -cos)`, as in the
rolling test of X-01b: the same problem as a tilted plane under vertical gravity, and the block stays a grounded assembly.

Two material pairs on three planets: catalog steel A36 (0.23, below every planet's ground: the part decides) and a test material
declared at 1.0 (above every planet's ground: the ground decides, its nominal from `data/bodies`).
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest
from gltf_samples import catalog_material, library_part

from kinetra_core import Badge, Project, load_body
from kinetra_engine.compiler import (
    CONTACT_PARAMETERS,
    DEFAULT_FRICTION,
    GROUND_GEOM,
    TREAD_FRICTION_SPEC,
    build_body_tree,
    contact_friction,
    contact_labels,
    proxy_labels,
    to_mjcf,
)

SRC = {"ref": "X-01e test fixture: value chosen by the test", "locator": "test_contact_friction.py"}
PLANETS = ("earth", "mars", "moon")
STEEL = catalog_material("steel-a36")
WHEEL = library_part("wheel")
SIDE, THICK = 0.1, 0.02  # [m] a flat block: it tips only past atan(SIDE / THICK) = 78.7 deg, far above every slip angle here


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def declared(friction: float) -> dict:
    return {"id": "grip", "name": "Test material", "density": q(1000.0, "kg/m^3"), "yield_strength": q(1.0e8, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"), "friction": q(friction, "1")}


def ax(v):
    return {"offset": v, "terms": []}


def plate(id="plate") -> dict:
    shape = {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "box", "size_x": ax(SIDE), "size_y": ax(SIDE), "size_z": ax(THICK)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    return {"id": id, "name": id, "parameters": [], "snap_points": [], "shape": shape}


def instance(id, part, z, material=None, x=0.0):
    inst = {"id": id, "part": part, "pose": {"badge": "declared", "source": SRC, "position": {"x": x, "y": 0.0, "z": z},
                                             "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    if material is not None:
        inst["material"] = material
    return inst


def block(planet: str, material: dict) -> Project:
    """One 0.1 x 0.1 x 0.02 m block of `material` resting on the ground (bottom face at z = 0), free."""
    return Project.model_validate({"design": {"materials": [material], "parts": [plate()], "instances": [instance("block1", "plate", THICK / 2, material["id"])],
                                              "joints": []}, "world": {"planet": planet}})


PAIRS = {
    "steel": STEEL.model_dump(mode="json"),  # 0.23 (catalog, Blau table 1 steel 1032 proxy)
    "declared-1.0": declared(1.0),
}


def tilted(planet, material, theta, ground_friction=None):
    tree = build_body_tree(block(planet, material))
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree, ground_friction=ground_friction))
    g = load_body(planet).gravity.value
    model.opt.gravity[:] = (g * math.sin(theta), 0.0, -g * math.cos(theta))
    return tree, model, g


def slide(planet, material, theta, ground_friction=None, seconds=1.0):
    """Acceleration down the incline fitted over 0.2 s .. `seconds` (after the contact settles), and the friction of every contact
    MuJoCo made on the way (a sliding cube rocks a little: its contact count goes 4, 2, 0 and back)."""
    _, model, g = tilted(planet, material, theta, ground_friction)
    data = mujoco.MjData(model)
    t, v, mu_contact = [], [], set()
    for _ in range(round(seconds / model.opt.timestep)):
        mujoco.mj_step(model, data)
        t.append(data.time)
        v.append(float(data.qvel[0]))
        mu_contact |= {float(data.contact[i].friction[0]) for i in range(data.ncon)}
    t, v = np.array(t), np.array(v)
    window = t >= 0.2
    return float(np.polyfit(t[window], v[window], 1)[0]), g, mu_contact


def combined(planet, material):
    return min(material["friction"]["value"], load_body(planet).ground_friction.value.value)


# --- the slip angle: DoD 3 ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("pair", list(PAIRS))
def test_contact_friction_slip_starts_at_atan_of_the_combined_coefficient(planet, pair):
    material = PAIRS[pair]
    mu = combined(planet, material)
    hand = math.atan(mu)
    # the side of the min that decides: the part for steel, the ground for the declared 1.0
    assert mu == (0.23 if pair == "steel" else load_body(planet).ground_friction.value.value)

    def sliding(theta):
        a, g, _ = slide(planet, material, theta)
        return a > 1e-3 * g  # creep (slow slip, a ~ 0) is not sliding; sliding accelerates

    lo, hi = hand - math.radians(5.0), hand + math.radians(5.0)
    assert not sliding(lo) and sliding(hi)
    while hi - lo > math.radians(0.02):  # bisection on the angle
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if sliding(mid) else (mid, hi)
    onset = (lo + hi) / 2
    # measured onset - atan(mu): +0.049 deg on all six (pair, planet): the 1e-3 g threshold itself is about 0.05 deg of tilt
    assert math.degrees(onset - hand) == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("pair", list(PAIRS))
def test_contact_friction_sliding_acceleration_is_g_sin_minus_mu_cos(planet, pair):
    material = PAIRS[pair]
    mu = combined(planet, material)
    theta = math.atan(mu) + math.radians(5.0)
    a, g, mu_contact = slide(planet, material, theta)
    assert mu_contact == {mu}  # MuJoCo's contact carries the smaller coefficient, exactly (priority)
    mu_measured = (math.sin(theta) - a / g) / math.cos(theta)
    assert mu_measured == pytest.approx(mu, rel=1e-3)  # measured: -1.5e-4 .. +3.3e-4


@pytest.mark.parametrize("planet", PLANETS)
def test_contact_friction_a_sampled_ground_value_reaches_the_contact_and_moves_the_slip_angle(planet):
    d = load_body(planet).ground_friction.distribution
    for ground in (d.low, d.high):  # the two ends of the planet's distribution (W-03c samples inside it)
        theta = math.atan(ground) + math.radians(5.0)
        a, g, mu_contact = slide(planet, PAIRS["declared-1.0"], theta, ground_friction=ground)
        assert mu_contact == {ground}
        # measured: within 1.6e-3 (earth's high end, 0.7813, the steepest incline here: 43 deg)
        assert (math.sin(theta) - a / g) / math.cos(theta) == pytest.approx(ground, rel=3e-3)


@pytest.mark.parametrize("planet", PLANETS)
def test_contact_friction_below_the_slip_angle_only_creeps(planet):
    """Soft contact: under the slip angle the block does not accelerate but creeps at a steady speed (MuJoCo's slow slippage,
    labelled). At tan(theta) = 0.9 mu the steel block creeps at 0.52 (earth), 0.20 (mars), 0.087 (moon) mm/s after 1 s."""
    mu = combined(planet, PAIRS["steel"])
    theta = math.atan(0.9 * mu)
    a, g, _ = slide(planet, PAIRS["steel"], theta)
    assert abs(a) < 1e-6 * g  # measured |a| / g < 1e-8: not sliding
    _, model, _ = tilted(planet, PAIRS["steel"], theta)
    data = mujoco.MjData(model)
    for _ in range(round(1.0 / model.opt.timestep)):
        mujoco.mj_step(model, data)
    assert 0.0 < data.qvel[0] < 1e-3  # creeps, slower than 1 mm/s


# --- the rule: DoD 1 -----------------------------------------------------------------------------------------------------------


def one(part, material=None, z=0.0, planet="earth"):
    """`part` alone at rest on the ground (its lowest point at z = 0 for the pose given)."""
    parts = [part if isinstance(part, dict) else part.model_dump(mode="json")]
    mats = [] if material is None else [material if isinstance(material, dict) else material.model_dump(mode="json")]
    inst = instance("i1", parts[0]["id"], z, None if material is None else mats[0]["id"])
    return build_body_tree(Project.model_validate({"design": {"materials": mats, "parts": parts, "instances": [inst], "joints": []},
                                                   "world": {"planet": planet}}))


WHEEL_TREE = lambda: one(WHEEL, catalog_material("pom-delrin-150"), WHEEL.parameters[0].default.value / 2)  # noqa: E731
BALLAST_TREE = lambda: one(library_part("ballast-weight"))  # noqa: E731  declared mass, no material; disc bottom at z = 0


def test_contact_friction_geom_friction_comes_from_tread_spec_then_material_then_default():
    tread = next(s for s in WHEEL.specs if s.name == TREAD_FRICTION_SPEC)
    wheel = contact_friction(WHEEL_TREE())
    assert {g.origin for g in wheel.geoms} == {"tread"} and len(wheel.geoms) == 7  # every geom of the wheel, not only the tire
    assert all(g.quantity == tread and g.mu == 0.7 for g in wheel.geoms)  # tread 0.7 wins over the POM material's 0.21
    steel = contact_friction(build_body_tree(block("earth", PAIRS["steel"])))
    assert [(g.origin, g.quantity) for g in steel.geoms] == [("material", STEEL.friction)]
    ballast = contact_friction(BALLAST_TREE())
    assert {(g.origin, g.quantity) for g in ballast.geoms} == {("default", DEFAULT_FRICTION)} and DEFAULT_FRICTION.badge is Badge.DEFAULT
    assert DEFAULT_FRICTION.value == 1.0  # MuJoCo's own sliding default, written out


@pytest.mark.parametrize("planet", PLANETS)
def test_contact_friction_priorities_make_every_pair_take_the_smaller_coefficient(planet):
    tree = one(WHEEL, catalog_material("pom-delrin-150"), WHEEL.parameters[0].default.value / 2, planet=planet)
    nominal = load_body(planet).ground_friction.value.value
    friction = contact_friction(tree)
    assert friction.ground == nominal and friction.ground_assumption == load_body(planet).ground_friction
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    mus = [float(model.geom_friction[i][0]) for i in range(model.ngeom)]
    prios = [int(model.geom_priority[i]) for i in range(model.ngeom)]
    assert mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, 0) == GROUND_GEOM and mus[0] == nominal
    for i in range(model.ngeom):
        for j in range(model.ngeom):
            winner = i if prios[i] > prios[j] else j if prios[j] > prios[i] else None
            got = max(mus[i], mus[j]) if winner is None else mus[winner]  # MuJoCo's rule (modeling.html, Contact parameters)
            assert got == min(mus[i], mus[j])


def test_contact_friction_wheel_on_the_ground_uses_the_ground_and_rolls():
    """The tread (0.7) is above every planet's nominal ground: the contact takes the ground's coefficient."""
    tree = one(WHEEL, catalog_material("pom-delrin-150"), WHEEL.parameters[0].default.value / 2, planet="moon")
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    data = mujoco.MjData(model)
    for _ in range(10):
        mujoco.mj_step(model, data)
    assert data.ncon >= 1 and {float(data.contact[i].friction[0]) for i in range(data.ncon)} == {load_body("moon").ground_friction.value.value}


@pytest.mark.parametrize("planet", PLANETS)
def test_contact_friction_rejects_a_ground_value_outside_the_planet_distribution(planet):
    tree = build_body_tree(block(planet, PAIRS["steel"]))
    d = load_body(planet).ground_friction.distribution
    for bad in (d.low - 1e-9, d.high + 1e-9, 0.0, 2.0):
        with pytest.raises(ValueError, match="outside"):
            contact_friction(tree, bad)
        with pytest.raises(ValueError, match="outside"):
            to_mjcf(tree, ground_friction=bad)
    assert contact_friction(tree, d.low).ground == d.low and contact_friction(tree, d.high).ground == d.high


# --- the contact parameters: DoD 2 ------------------------------------------------------------------------------------------------


def test_contact_friction_contact_parameters_are_written_with_a_badge_and_reach_mujoco():
    assert [p.name for p in CONTACT_PARAMETERS] == ["condim", "cone", "solref", "solimp"]
    for p in CONTACT_PARAMETERS:
        assert p.badge in (Badge.DEFAULT, Badge.ESTIMATE) and p.source and p.url.startswith("https://mujoco.readthedocs.io/")
    params = {p.name: p for p in CONTACT_PARAMETERS}
    assert params["cone"].badge is Badge.ESTIMATE  # the one Kinetra choice; the rest are MuJoCo's defaults
    model = mujoco.MjModel.from_xml_string(to_mjcf(build_body_tree(block("earth", PAIRS["steel"]))))
    assert model.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC
    assert model.opt.impratio == 1.0  # not raised: the slow slip it would reduce is labelled instead
    for i in range(model.ngeom):
        assert model.geom_condim[i] == 3
        assert list(model.geom_solref[i]) == [0.02, 1.0]
        assert list(model.geom_solimp[i]) == pytest.approx([0.9, 0.95, 0.001, 0.5, 2.0])
        assert model.geom_margin[i] == 0.0
    # the values written are MuJoCo's own defaults where the badge says `default`
    bare = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom type="sphere" size="1"/></worldbody></mujoco>')
    assert bare.geom_condim[0] == 3 and list(bare.geom_solref[0]) == [0.02, 1.0]
    assert list(bare.geom_solimp[0]) == pytest.approx([0.9, 0.95, 0.001, 0.5, 2.0]) and bare.geom_friction[0][0] == DEFAULT_FRICTION.value
    assert bare.opt.cone == mujoco.mjtCone.mjCONE_PYRAMIDAL  # MuJoCo's default cone, which the compiler changes


def test_contact_friction_mjcf_is_byte_identical_for_the_same_project():
    a, b = build_body_tree(block("mars", PAIRS["steel"])), build_body_tree(block("mars", PAIRS["steel"]))
    assert to_mjcf(a) == to_mjcf(b) and to_mjcf(a, ground_friction=0.4) == to_mjcf(b, ground_friction=0.4)


# --- labels ------------------------------------------------------------------------------------------------------------------------


def test_contact_friction_labels_state_the_rule_the_slow_slip_the_tread_and_the_default():
    rule = ["근사: 접촉 마찰은 두 면 중 작은 계수, 정지·운동 구분 없이 운동 마찰 계수 하나", "근사: 소프트 접촉이라 정지 마찰 범위 안에서도 느리게 미끄러짐",
            "근사: 구름·비틀림 마찰 없음(미끄럼 마찰만)"]
    steel = contact_labels(contact_friction(build_body_tree(block("earth", PAIRS["steel"]))))
    assert [label.text for label in steel] == rule and all(label.kind == "contact" and label.instance is None for label in steel)
    wheel = contact_labels(contact_friction(WHEEL_TREE()))
    assert [label.text for label in wheel] == [*rule, "근사: i1의 모든 접촉 면에 트레드 마찰 0.7"]
    assert (wheel[-1].instance, wheel[-1].part) == ("i1", "wheel")
    ballast = contact_labels(contact_friction(BALLAST_TREE()))
    assert ballast[-1].text == "기본값: i1의 마찰 1(재료도 트레드 사양도 없음, MuJoCo 기본값)" and ballast[-1].part == "ballast-weight"
    assert proxy_labels(WHEEL_TREE()) == ()  # the proxy labels are unchanged: contact labels are their own list
