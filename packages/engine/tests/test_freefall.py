"""W-03a: the compiled model runs with the planet's gravity and atmosphere density, read from `data/bodies` only.

`uv run pytest packages/engine -q -k freefall`. Hand calculation: a body released at rest falls h in t = sqrt(2 h / g). The
expected times below were worked out by hand from the gravities in `docs/architecture/bodies.md` (9.80665, 3.73, 1.62 m/s^2)
and are written out, so a changed data file also fails here, not only the simulation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import pytest

from kinetra_core import Project, load_body
from kinetra_engine.compiler import CompileError, PlanetPhysics, build_body_tree, planet_physics, to_mjcf

SRC = {"ref": "W-03a test fixture: value chosen by the test", "locator": "test_freefall.py"}
DROP = 1.0  # [m]
HAND = {  # sqrt(2 * 1 m / g)
    "earth": 0.45160075575178754,  # g = 9.80665
    "mars": 0.7322520259382125,  # g = 3.73
    "moon": 1.1111111111111112,  # g = 1.62
}


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def block(planet: str) -> Project:
    """One 0.1 m steel-like cube resting on the ground (bottom face at z = 0), free, no joints."""
    shape = {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "box", "size_x": ax(0.1), "size_y": ax(0.1), "size_z": ax(0.1)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    material = {"id": "mat", "name": "Test material", "density": q(7850.0, "kg/m^3"), "yield_strength": q(2.5e8, "Pa"),
                "elastic_modulus": q(2.0e11, "Pa"), "friction": q(0.5, "1")}
    part = {"id": "cube", "name": "cube", "parameters": [], "snap_points": [], "shape": shape}
    inst = {"id": "cube1", "part": "cube", "material": "mat", "pose": {"badge": "declared", "source": SRC,
            "position": {"x": 0.0, "y": 0.0, "z": 0.05}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    return Project.model_validate({"design": {"materials": [material], "parts": [part], "instances": [inst], "joints": []},
                                   "world": {"planet": planet}})


def fall_time(model: mujoco.MjModel, h: float) -> float:
    """Time for the free body to fall `h` from rest, linearly interpolated between the two steps that straddle it. The
    body is first lifted 2 h above its saved pose (an initial condition of the run, not of the project), so it never
    reaches the ground while it falls."""
    data = mujoco.MjData(model)
    data.qpos[2] += 2.0 * h
    z0 = float(data.qpos[2])
    t_prev, z_prev = 0.0, z0
    while True:
        mujoco.mj_step(model, data)
        z = float(data.qpos[2])
        if z0 - z >= h:
            return t_prev + (z_prev - (z0 - h)) / (z_prev - z) * (data.time - t_prev)
        t_prev, z_prev = float(data.time), z


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_freefall_time_matches_the_hand_calculation_on_each_planet(planet):
    g = load_body(planet).gravity.value
    assert math.sqrt(2.0 * DROP / g) == pytest.approx(HAND[planet], rel=1e-12)
    model = mujoco.MjModel.from_xml_string(to_mjcf(build_body_tree(block(planet))))
    t = fall_time(model, DROP)
    # Semi-implicit Euler (MuJoCo's default) puts the body at h_n = g dt^2 n (n + 1) / 2, i.e. g (t + dt/2)^2 / 2 - g dt^2 / 8:
    # it crosses h at sqrt(T^2 + dt^2 / 4) - dt / 2 (T the exact time), about half a step early. Both bounds by hand.
    dt = model.opt.timestep
    assert abs(t - HAND[planet]) <= dt
    assert t == pytest.approx(math.sqrt(HAND[planet] ** 2 + dt * dt / 4.0) - dt / 2.0, abs=1e-2 * dt)


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_freefall_compile_options_come_from_data_bodies(planet):
    body = load_body(planet)
    tree = build_body_tree(block(planet))
    assert tree.planet == PlanetPhysics(planet, body.gravity, body.atmosphere_density)
    # the Quantity travels with its badge and source (V5)
    assert tree.planet.gravity.source == body.gravity.source and tree.planet.atmosphere_density.badge == body.atmosphere_density.badge
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    assert tuple(model.opt.gravity) == (0.0, 0.0, -body.gravity.value)  # bit for bit: written with repr
    assert model.opt.density == 0.0 and model.opt.viscosity == 0.0  # no unlabelled MuJoCo drag (planet.py)


def test_freefall_three_planets_differ_only_in_the_option_line():
    texts = {p: to_mjcf(build_body_tree(block(p))).splitlines() for p in ("earth", "mars", "moon")}
    diff = [i for i, (a, b, c) in enumerate(zip(texts["earth"], texts["mars"], texts["moon"])) if not a == b == c]
    assert len(diff) == 1 and texts["earth"][diff[0]].lstrip().startswith("<option ")


def test_freefall_the_model_runs_what_the_data_file_says(tmp_path: Path):
    """The value reaches the model from the file and from nowhere else: edit the file, the fall changes."""
    raw = json.loads(load_body("earth").model_dump_json())
    raw["gravity"]["value"] = 2.0  # test value: t = sqrt(2 * 1 / 2) = 1 s
    raw["atmosphere_density"]["value"] = 0.5
    (tmp_path / "earth.json").write_text(json.dumps(raw), encoding="utf-8")
    tree = build_body_tree(block("earth"), bodies_directory=tmp_path)
    assert tree.planet == planet_physics("earth", tmp_path)
    assert tree.planet.atmosphere_density.value == 0.5
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    assert tuple(model.opt.gravity) == (0.0, 0.0, -2.0)
    assert abs(fall_time(model, DROP) - 1.0) <= model.opt.timestep


def test_freefall_a_planet_without_data_is_a_compile_error(tmp_path: Path):
    with pytest.raises(CompileError, match="venus"):
        build_body_tree(block("venus"))
    with pytest.raises(CompileError, match="earth"):
        build_body_tree(block("earth"), bodies_directory=tmp_path)  # no earth.json there
