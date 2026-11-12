"""W-05: terrain props (ramp and step) compiled into static MJCF geoms, and the slip angle of a block on a real ramp.

`uv run pytest packages/engine -q -k ramp`. MuJoCo 4.0.0 runs the compiled MJCF, no seed (deterministic). Hand calculation: a
block at rest on a ramp of incline theta under vertical gravity g starts to slide when tan(theta) > mu, so the slip angle is
atan(mu); sliding, it accelerates down the slope at g (sin(theta) - mu cos(theta)). mu is the combined coefficient of the block and
the ramp surface, min(mu_block, mu_ramp) (X-01e, `contact.py`). Unlike `test_contact_friction.py`, gravity stays vertical: the ramp
is the compiled prop geom, the block a grounded assembly resting on its slope.

The block is a test material declared at 1.0, above every planet's ground (0.9004 at most) and above catalog steel A36 (0.23), so
the ramp surface decides: a ramp without a material (`material` None: the planet's ground, its nominal from `data/bodies`) or a
steel A36 ramp.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest
from gltf_samples import catalog_material

from pydantic import TypeAdapter

from kinetra_core import Command, CommandRejected, Project, ReasonCode, load_body, validate_command
from kinetra_engine.compiler import PROP_GEOM_PREFIX, build_body_tree, contact_friction, to_mjcf

SRC = {"ref": "W-05 test fixture: value chosen by the test", "locator": "test_terrain_ramp.py"}
PLANETS = ("earth", "mars", "moon")
STEEL = catalog_material("steel-a36").model_dump(mode="json")  # friction 0.23 (catalog)
SIDE, THICK = 0.1, 0.02  # [m] a flat block: it tips only past atan(SIDE / THICK) = 78.7 deg, far above every slip angle here
LENGTH, WIDTH = 3.0, 1.0  # [m] the ramp's run and width: long enough that the block slides 1 s without reaching either end
BLOCK_FRICTION = 1.0


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def grip() -> dict:
    return {"id": "grip", "name": "Test material", "density": q(1000.0, "kg/m^3"), "yield_strength": q(1.0e8, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"), "friction": q(BLOCK_FRICTION, "1")}


def plate() -> dict:
    shape = {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "box", "size_x": ax(SIDE), "size_y": ax(SIDE), "size_z": ax(THICK)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    return {"id": "plate", "name": "plate", "parameters": [], "snap_points": [], "shape": shape}


def ramp(theta, material=None, x=0.0, y=0.0, yaw=0.0, id="ramp1", length=LENGTH, width=WIDTH) -> dict:
    return {"id": id, "kind": "ramp", "material": material, "placement": {"badge": "declared", "source": SRC, "x": x, "y": y, "yaw": yaw},
            "length": q(length, "m"), "width": q(width, "m"), "incline": q(theta, "rad")}


def step(height, material=None, x=0.0, y=0.0, yaw=0.0, id="step1", length=1.0, width=0.5) -> dict:
    return {"id": id, "kind": "step", "material": material, "placement": {"badge": "declared", "source": SRC, "x": x, "y": y, "yaw": yaw},
            "length": q(length, "m"), "width": q(width, "m"), "height": q(height, "m")}


def uphill(theta, yaw) -> np.ndarray:
    """Unit vector up the slope of a ramp turned by `yaw` (it rises along its local +x, `world.py`)."""
    return np.array([math.cos(theta) * math.cos(yaw), math.cos(theta) * math.sin(yaw), math.sin(theta)])


def on_ramp(planet, theta, ramp_material=None, yaw=0.0, x=0.0, y=0.0) -> Project:
    """The block resting on the middle of the ramp's slope: bottom face on the slope, its local x up the slope."""
    surface = np.array([x, y, LENGTH / 2 * math.tan(theta)])  # the slope above the footprint's centre
    normal = np.array([-math.sin(theta) * math.cos(yaw), -math.sin(theta) * math.sin(yaw), math.cos(theta)])
    centre = surface + normal * THICK / 2
    # yaw about z, then -theta about the turned y: local z goes to the slope normal, local x up the slope
    qz = np.array([math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)])
    qy = np.array([math.cos(-theta / 2), 0.0, math.sin(-theta / 2), 0.0])
    w = np.empty(4)
    mujoco.mju_mulQuat(w, qz, qy)
    materials = [grip()] + ([STEEL] if ramp_material == STEEL["id"] else [])
    inst = {"id": "block1", "part": "plate", "material": "grip", "pose": {"badge": "declared", "source": SRC,
            "position": dict(zip("xyz", map(float, centre), strict=True)),
            "orientation": {"w": float(w[0]), "x": float(w[1]), "y": float(w[2]), "z": float(w[3])}}}
    return Project.model_validate({"design": {"materials": materials, "parts": [plate()], "instances": [inst], "joints": []},
                                   "world": {"planet": planet, "terrain_props": [ramp(theta, ramp_material, x, y, yaw)]}})


def slide(planet, theta, ramp_material=None, yaw=0.0, ground_friction=None, seconds=1.0):
    """The block's acceleration down the slope fitted over 0.2 s .. `seconds` (after the contact settles), the friction of every
    contact MuJoCo made, and the geoms it touched."""
    tree = build_body_tree(on_ramp(planet, theta, ramp_material, yaw))
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree, ground_friction=ground_friction))
    data = mujoco.MjData(model)
    up = uphill(theta, yaw)
    t, v, mu_contact, touched = [], [], set(), set()
    for _ in range(round(seconds / model.opt.timestep)):
        mujoco.mj_step(model, data)
        t.append(data.time)
        v.append(-float(np.dot(data.qvel[:3], up)))
        for c in data.contact[: data.ncon]:
            mu_contact.add(float(c.friction[0]))
            touched |= {model.geom(c.geom1).name, model.geom(c.geom2).name}
    t, v = np.array(t), np.array(v)
    window = t >= 0.2
    return float(np.polyfit(t[window], v[window], 1)[0]), load_body(planet).gravity.value, mu_contact, touched


def ramp_mu(planet, ramp_material):
    return 0.23 if ramp_material == STEEL["id"] else load_body(planet).ground_friction.value.value


SURFACES = {"ground": None, "steel": STEEL["id"]}


def with_props(project: Project, *props: dict) -> Project:
    """`project` with steel A36 among its materials and `props` added to its world."""
    data = project.model_dump(mode="json")
    data["design"]["materials"].append(STEEL)
    data["world"]["terrain_props"] += list(props)
    return Project.model_validate(data)


# --- placing: ramp and step with their parameters ----------------------------------------------------------------------------


def world_vertices(model, data, geom) -> np.ndarray:
    g = model.geom(geom)
    m = model.mesh(g.dataid[0])
    local = model.mesh_vert[m.vertadr[0] : m.vertadr[0] + m.vertnum[0]]
    return data.geom_xpos[g.id] + local @ data.geom_xmat[g.id].reshape(3, 3).T


def test_ramp_and_step_are_placed_with_their_incline_length_width_height_and_pose():
    theta, yaw, h = math.radians(20.0), 0.6, 0.15
    project = with_props(on_ramp("earth", theta, yaw=yaw, x=1.0, y=-0.5), step(h, STEEL["id"], x=-2.0, y=1.5, yaw=-0.3, length=1.2, width=0.4))
    tree = build_body_tree(project)
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    # ramp: the six vertices of the prism, footprint LENGTH x WIDTH on z = 0, rise LENGTH tan(theta) at the high end
    rise = LENGTH * math.tan(theta)
    c, s = math.cos(yaw), math.sin(yaw)
    expected = [np.array([1.0 + c * lx - s * ly, -0.5 + s * lx + c * ly, z])
                for ly in (-WIDTH / 2, WIDTH / 2) for lx, z in ((-LENGTH / 2, 0.0), (LENGTH / 2, 0.0), (LENGTH / 2, rise))]
    got = world_vertices(model, data, PROP_GEOM_PREFIX + "ramp1")
    assert len(got) == 6
    for e in expected:
        assert np.min(np.linalg.norm(got - e, axis=1)) < 1e-7  # MuJoCo stores mesh vertices as float32: measured 2.4e-8 m
    assert model.geom(PROP_GEOM_PREFIX + "ramp1").bodyid[0] == 0  # static: a world geom

    # step: a box LENGTH x WIDTH x height standing on z = 0, turned by its yaw
    g = model.geom(PROP_GEOM_PREFIX + "step1")
    assert g.type[0] == mujoco.mjtGeom.mjGEOM_BOX and g.bodyid[0] == 0
    np.testing.assert_allclose(g.size, (0.6, 0.2, h / 2), rtol=0, atol=1e-15)
    np.testing.assert_allclose(data.geom_xpos[g.id], (-2.0, 1.5, h / 2), rtol=0, atol=1e-15)
    rz = np.array([[math.cos(-0.3), -math.sin(-0.3), 0.0], [math.sin(-0.3), math.cos(-0.3), 0.0], [0.0, 0.0, 1.0]])
    np.testing.assert_allclose(data.geom_xmat[g.id].reshape(3, 3), rz, rtol=0, atol=1e-15)


def test_ramp_friction_is_the_material_or_the_planet_ground_and_takes_a_sampled_ground_value():
    planet = "mars"
    d = load_body(planet).ground_friction.distribution
    tree = build_body_tree(with_props(on_ramp(planet, math.radians(10.0)), step(0.1, STEEL["id"], x=5.0)))
    for ground in (None, d.low, d.high):
        friction = contact_friction(tree, ground)
        mu_ground = friction.ground
        assert [(p.prop, p.origin, p.mu) for p in friction.props] == [("ramp1", "ground", mu_ground), ("step1", "material", 0.23)]
        assert friction.props[1].quantity == catalog_material("steel-a36").friction  # badge and source carried
        model = mujoco.MjModel.from_xml_string(to_mjcf(tree, ground_friction=ground))
        assert model.geom(PROP_GEOM_PREFIX + "ramp1").friction[0] == mu_ground == model.geom("__kinetra_ground").friction[0]
        assert model.geom(PROP_GEOM_PREFIX + "step1").friction[0] == 0.23
        # the smaller coefficient has the higher priority (min rule, X-01e), props included
        assert model.geom(PROP_GEOM_PREFIX + "step1").priority[0] > model.geom(PROP_GEOM_PREFIX + "ramp1").priority[0]


def test_ramp_mjcf_is_byte_identical_whatever_the_order_of_the_props():
    project = with_props(on_ramp("earth", math.radians(15.0)), step(0.1, STEEL["id"], x=4.0, id="a-step"), step(0.2, x=-4.0, id="z-step"))
    data = project.model_dump(mode="json")
    flipped = {**data, "world": {**data["world"], "terrain_props": data["world"]["terrain_props"][::-1]}}
    xml = to_mjcf(build_body_tree(project))
    assert xml == to_mjcf(build_body_tree(Project.model_validate(flipped)))
    names = [PROP_GEOM_PREFIX + i for i in ("a-step", "ramp1", "z-step")]
    assert [xml.index(f'name="{n}" type') for n in names] == sorted(xml.index(f'name="{n}" type') for n in names)


def test_ramp_block_on_a_step_rests_on_its_top():
    h = 0.25
    inst = {"id": "block1", "part": "plate", "material": "grip", "pose": {"badge": "declared", "source": SRC,
            "position": {"x": 0.0, "y": 0.0, "z": h + THICK / 2}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    project = Project.model_validate({"design": {"materials": [grip()], "parts": [plate()], "instances": [inst], "joints": []},
                                      "world": {"planet": "moon", "terrain_props": [step(h)]}})
    model = mujoco.MjModel.from_xml_string(to_mjcf(build_body_tree(project)))
    data = mujoco.MjData(model)
    for _ in range(round(1.0 / model.opt.timestep)):
        mujoco.mj_step(model, data)
    assert data.qpos[2] == pytest.approx(h + THICK / 2, abs=1e-4)  # held up by the step; soft contact: measured 0.018 mm lower
    touched = {model.geom(g).name for c in data.contact[: data.ncon] for g in (c.geom1, c.geom2)}
    assert touched == {PROP_GEOM_PREFIX + "step1", "block1/c"}


def test_ramp_and_step_are_placed_moved_and_removed_by_commands_and_reach_the_model():
    """The user places props with `add_terrain_prop`, changes one with `replace_terrain_prop` and removes one with
    `remove_terrain_prop` (C-02a commands, validated like any edit by C-02c); the compiled model follows."""
    command = TypeAdapter(Command).validate_python
    inst = {"id": "block1", "part": "plate", "material": "grip", "pose": {"badge": "declared", "source": SRC,
            "position": {"x": 0.0, "y": 0.0, "z": THICK / 2}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    project = Project.model_validate({"design": {"materials": [grip()], "parts": [plate()], "instances": [inst], "joints": []},
                                      "world": {"planet": "mars"}})

    def top(p: Project) -> float:
        model = mujoco.MjModel.from_xml_string(to_mjcf(build_body_tree(p)))
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        return float(max(world_vertices(model, data, PROP_GEOM_PREFIX + "ramp1")[:, 2]))

    placed = validate_command(project, command({"type": "batch", "commands": [
        {"type": "add_terrain_prop", "prop": ramp(math.radians(10.0), x=3.0)},
        {"type": "add_terrain_prop", "prop": step(0.1, x=-2.0)}]})).project
    assert top(placed) == pytest.approx(LENGTH * math.tan(math.radians(10.0)), abs=1e-6)
    steeper = validate_command(placed, command({"type": "replace_terrain_prop", "prop": ramp(math.radians(25.0), x=3.0)})).project
    assert top(steeper) == pytest.approx(LENGTH * math.tan(math.radians(25.0)), abs=1e-6)
    gone = validate_command(steeper, command({"type": "remove_terrain_prop", "id": "step1"})).project
    assert PROP_GEOM_PREFIX + "step1" in to_mjcf(build_body_tree(steeper))
    assert PROP_GEOM_PREFIX + "step1" not in to_mjcf(build_body_tree(gone))

    with pytest.raises(CommandRejected) as e:  # a step put through the block is refused, like any overlap
        validate_command(project, command({"type": "add_terrain_prop", "prop": step(0.1)}))
    assert e.value.reasons[0].code is ReasonCode.OVERLAP


# --- the slip angle on a ramp against the hand calculation: DoD 2 -----------------------------------------------------------------


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("surface", list(SURFACES))
def test_ramp_slip_starts_at_atan_of_the_combined_coefficient(planet, surface):
    material = SURFACES[surface]
    mu = ramp_mu(planet, material)
    assert mu == min(BLOCK_FRICTION, mu)  # the ramp's surface decides
    hand = math.atan(mu)

    def sliding(theta):
        a, g, _, _ = slide(planet, theta, material, seconds=0.6)
        return a > 1e-3 * g  # creep (slow slip, a ~ 0) is not sliding; sliding accelerates

    lo, hi = hand - math.radians(2.0), hand + math.radians(2.0)
    assert not sliding(lo) and sliding(hi)
    while hi - lo > math.radians(0.02):  # bisection on the ramp's incline
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if sliding(mid) else (mid, hi)
    onset = (lo + hi) / 2
    # measured onset - atan(mu): +0.039 .. +0.055 deg on all six (surface, planet): the 1e-3 g threshold is about 0.05 deg of slope
    assert math.degrees(onset - hand) == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("surface", list(SURFACES))
def test_ramp_sliding_acceleration_is_g_sin_minus_mu_cos_on_a_turned_ramp(planet, surface):
    material = SURFACES[surface]
    mu = ramp_mu(planet, material)
    theta = math.atan(mu) + math.radians(5.0)
    a, g, mu_contact, touched = slide(planet, theta, material, yaw=2.1)
    assert touched == {PROP_GEOM_PREFIX + "ramp1", "block1/c"}  # on the ramp the whole second, never the ground
    assert mu_contact == {mu}  # MuJoCo's contact carries the smaller coefficient, exactly (priority)
    assert (math.sin(theta) - a / g) / math.cos(theta) == pytest.approx(mu, rel=1e-3)  # measured: -3.8e-4 .. +3.3e-4


@pytest.mark.parametrize("planet", PLANETS)
def test_ramp_without_material_takes_the_sampled_ground_value(planet):
    d = load_body(planet).ground_friction.distribution
    for ground in (d.low, d.high):  # the two ends of the planet's distribution (W-03c samples inside it)
        theta = math.atan(ground) + math.radians(5.0)
        a, g, mu_contact, _ = slide(planet, theta, ground_friction=ground)
        assert mu_contact == {ground}
        # measured: within 1.6e-3 (earth's high end, 0.7813, the steepest ramp here: 43 deg)
        assert (math.sin(theta) - a / g) / math.cos(theta) == pytest.approx(ground, rel=3e-3)


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("surface", list(SURFACES))
def test_ramp_below_the_slip_angle_the_block_does_not_slide(planet, surface):
    material = SURFACES[surface]
    theta = math.atan(0.9 * ramp_mu(planet, material))
    a, g, _, _ = slide(planet, theta, material)
    assert abs(a) < 1e-6 * g  # measured |a| / g < 6e-9 (it creeps at a steady speed: MuJoCo's slow slippage, labelled by X-01e)
