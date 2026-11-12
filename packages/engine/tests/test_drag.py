"""W-03b: lumped air drag, `F = -1/2 rho C_dA |v| v` per body, applied as a force of ours (not MuJoCo's medium).

`uv run pytest packages/engine -q -k drag`. Hand calculation: a body falling from rest under gravity and quadratic drag reaches
the terminal speed `v_t = sqrt(2 m g / (rho C_dA))` and has `v(t) = v_t tanh(g t / v_t)`. The terminal speeds below were worked
out by hand from the densities and gravities in `docs/architecture/bodies.md` (Earth 1.217 kg/m^3 and 9.80665 m/s^2, Mars
0.016 and 3.73), the sphere's 0.47 (`drag.py`) and the test sphere, and are written out, so a changed data file or coefficient
also fails here, not only the simulation.
"""

from __future__ import annotations

import math

import mujoco
import pytest

from kinetra_core import Badge, Project, load_body
from kinetra_engine.compiler import (
    DRAG_LABEL,
    BodyGeom,
    DragRuntime,
    build_body_tree,
    compile_drag,
    drag_force,
    drag_labels,
    geom_drag_area,
    model_labels,
    to_mjcf,
)
from kinetra_engine.compiler.drag import BOX_CD, CYLINDER_END_CD, CYLINDER_SIDE_CD, SPHERE_CD

SRC = {"ref": "W-03b test fixture: value chosen by the test", "locator": "test_drag.py"}
RADIUS = 0.05  # [m], test value
DENSITY = {"earth": 50.0, "mars": 5.0}  # [kg/m^3], test values: light spheres, so the terminal speed is reached in seconds
# m = DENSITY * 4/3 pi r^3; C_dA = 0.47 pi r^2; v_t = sqrt(2 m g / (rho C_dA)) = sqrt(8 DENSITY r g / (3 * 0.47 * rho))
HAND_VT = {
    "earth": 10.691053188260371,  # sqrt(8 * 50 * 0.05 * 9.80665 / (1.41 * 1.217))
    "mars": 18.184437271063633,  # sqrt(8 * 5 * 0.05 * 3.73 / (1.41 * 0.016))
}


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def ball(planet: str, density: float = 50.0) -> Project:
    """One sphere of radius `RADIUS` resting on the ground (centre at z = r), free, no joints."""
    shape = {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add", "primitive": {"kind": "sphere", "radius": ax(RADIUS)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    material = {"id": "mat", "name": "Test foam", "density": q(density, "kg/m^3"), "yield_strength": q(1.0e6, "Pa"),
                "elastic_modulus": q(1.0e7, "Pa"), "friction": q(0.5, "1")}
    part = {"id": "ball", "name": "ball", "parameters": [], "snap_points": [], "shape": shape}
    inst = {"id": "ball1", "part": "ball", "material": "mat", "pose": {"badge": "declared", "source": SRC,
            "position": {"x": 0.0, "y": 0.0, "z": RADIUS}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    return Project.model_validate({"design": {"materials": [material], "parts": [part], "instances": [inst], "joints": []},
                                   "world": {"planet": planet}})


def run(planet: str, density: float, seconds: float, timestep: float | None = None):
    """Drop the ball from rest with drag for `seconds` (a whole number of steps); returns (model, data, [(t, vz)] every step).
    There is no ground plane in the model. Counted in steps, not in `data.time`: MuJoCo resets the data (time 0) when the
    state blows up."""
    tree = build_body_tree(ball(planet, density))
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    if timestep is not None:
        model.opt.timestep = timestep
    data = mujoco.MjData(model)
    runtime = DragRuntime(model, compile_drag(tree))
    out = []
    for _ in range(round(seconds / model.opt.timestep)):
        runtime.step(data)
        out.append((float(data.time), float(data.qvel[2])))
    return model, data, out


@pytest.mark.parametrize("planet", ["earth", "mars"])
def test_drag_sphere_terminal_speed_matches_the_hand_calculation(planet):
    body = load_body(planet)
    g, rho = body.gravity.value, body.atmosphere_density.value
    tree = build_body_tree(ball(planet, DENSITY[planet]))
    m = tree.root.mass
    assert m == pytest.approx(DENSITY[planet] * 4.0 / 3.0 * math.pi * RADIUS**3, rel=1e-9)
    area = compile_drag(tree).area(tree.root.id)
    assert area == pytest.approx(0.47 * math.pi * RADIUS**2, rel=1e-12)
    vt = math.sqrt(2.0 * m * g / (rho * area))
    assert vt == pytest.approx(HAND_VT[planet], rel=1e-8)

    tau = vt / g  # the velocity relaxes as tanh(t / tau)
    model, _, trace = run(planet, DENSITY[planet], 8.0 * tau)
    dt = model.opt.timestep
    # terminal speed: after 8 tau the tanh is 1 - 2.3e-7
    assert -trace[-1][1] == pytest.approx(vt, rel=1e-5)
    # the whole fall: v(t) = v_t tanh(g t / v_t); the step is explicit, so the error is of order g dt (measured 0.184 g dt on
    # both planets, MuJoCo 4.0.0)
    worst = max(abs(-vz - vt * math.tanh(t / tau)) for t, vz in trace)
    assert worst <= 0.25 * g * dt


def test_drag_force_is_minus_half_rho_cda_v_v():
    f = drag_force(1.2, 0.5, (3.0, 0.0, -4.0))  # |v| = 5
    assert f == pytest.approx((-0.5 * 1.2 * 0.5 * 5 * 3.0, 0.0, 0.5 * 1.2 * 0.5 * 5 * 4.0), rel=1e-15)
    assert drag_force(0.0, 0.5, (3.0, 0.0, -4.0)) == (-0.0, -0.0, 0.0)


def test_drag_area_of_each_shape_is_the_mean_over_its_three_axes():
    # sphere r: 0.47 pi r^2
    assert geom_drag_area(BodyGeom("s", "i", "g", "sphere", (0.2,), (0, 0, 0), (1, 0, 0, 0))) == pytest.approx(0.47 * math.pi * 0.04)
    # box 0.2 x 0.4 x 0.6 (half extents 0.1, 0.2, 0.3): 1.05 (0.08 + 0.24 + 0.12) / 3
    assert geom_drag_area(BodyGeom("b", "i", "g", "box", (0.1, 0.2, 0.3), (0, 0, 0), (1, 0, 0, 0))) == pytest.approx(1.05 * 0.44 / 3)
    # cylinder r 0.1, length 0.6: (2 * 1.20 * 0.12 + 0.82 * pi * 0.01) / 3
    cyl = BodyGeom("c", "i", "g", "cylinder", (0.1, 0.3), (0, 0, 0), (1, 0, 0, 0))
    assert geom_drag_area(cyl) == pytest.approx((2 * 1.20 * 0.12 + 0.82 * math.pi * 0.01) / 3)
    # a cube's lumped value is the face-on one; edge-on (0.80 x sqrt(2) a^2 = 1.13 a^2) is within 8 %
    cube = geom_drag_area(BodyGeom("b", "i", "g", "box", (0.5, 0.5, 0.5), (0, 0, 0), (1, 0, 0, 0)))
    assert cube == pytest.approx(1.05) and abs(0.80 * math.sqrt(2) - cube) / cube < 0.08
    # every coefficient has a badge and a cited place (V5); only the sphere is the table's own case
    assert SPHERE_CD.badge is Badge.CITE
    assert {BOX_CD.badge, CYLINDER_SIDE_CD.badge, CYLINDER_END_CD.badge} == {Badge.ESTIMATE}
    assert all(c.source.locator and c.source.url for c in (SPHERE_CD, BOX_CD, CYLINDER_SIDE_CD, CYLINDER_END_CD))


def test_drag_moon_is_zero_and_the_trajectory_is_the_one_without_drag():
    tree = build_body_tree(ball("moon"))
    assert load_body("moon").atmosphere_density.value == 0.0
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    with_drag, plain = mujoco.MjData(model), mujoco.MjData(model)
    runtime = DragRuntime(model, compile_drag(tree))
    for _ in range(2000):
        runtime.step(with_drag)
        mujoco.mj_step(model, plain)
    assert with_drag.qpos.tobytes() == plain.qpos.tobytes() and with_drag.qvel.tobytes() == plain.qvel.tobytes()
    assert not with_drag.xfrc_applied.any()
    assert with_drag.qvel[2] == pytest.approx(-load_body("moon").gravity.value * with_drag.time, rel=1e-9)


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_drag_label_is_in_the_model_labels_where_there_is_air(planet):
    tree = build_body_tree(ball(planet))
    labels = model_labels(tree)
    if planet == "moon":
        assert drag_labels(tree) == () and DRAG_LABEL not in [label.text for label in labels]
    else:
        (label,) = drag_labels(tree)
        assert label.text == "근사: 집중 항력" and label.kind == "drag" and label in labels
        assert (label.instance, label.part, label.host, label.percent) == (None, None, None, None)


def test_drag_is_not_mujocos_medium():
    """The decision (`drag.py`): MuJoCo's global medium stays off; the force is ours, so without the runtime there is none."""
    tree = build_body_tree(ball("earth"))
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    assert model.opt.density == 0.0 and model.opt.viscosity == 0.0
    data = mujoco.MjData(model)
    for _ in range(500):
        mujoco.mj_step(model, data)
    assert data.qvel[2] == pytest.approx(-load_body("earth").gravity.value * data.time, rel=1e-9)  # free fall, no drag


def test_drag_keeps_a_force_another_writer_put_in_xfrc_applied():
    """`step` adds drag for this step only: a force someone else keeps in the row is neither cleared nor accumulated."""
    tree = build_body_tree(ball("earth"))
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree))
    data = mujoco.MjData(model)
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, tree.root.id)
    data.xfrc_applied[body, 0] = 0.25
    runtime = DragRuntime(model, compile_drag(tree))
    for _ in range(100):
        runtime.step(data)
    assert tuple(data.xfrc_applied[body]) == (0.25, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_drag_explicit_step_stability_limit_is_v_t_over_g():
    """Explicit drag: near v_t a step multiplies the speed error by 1 - 2 g h / v_t (tau = v_t / g). Measured on Earth with the
    light sphere (tau = 1.09 s): monotone up to h = tau / 2, a decaying overshoot below tau, no convergence above it (a
    two-step cycle at 1.1 tau, a blow-up MuJoCo reports at 1.5 tau). MuJoCo's default 0.002 s is tau / 545 here."""
    vt = HAND_VT["earth"]
    tau = vt / load_body("earth").gravity.value

    def speeds(h: float):
        _, data, trace = run("earth", DENSITY["earth"], 60.0 * tau, timestep=h)
        return data, [-vz for _, vz in trace]

    for f in (0.4, 0.5):
        _, v = speeds(f * tau)
        assert all(b >= a for a, b in zip(v, v[1:])) and v[-1] == pytest.approx(vt, rel=1e-9)
    _, ringing = speeds(0.9 * tau)
    assert max(ringing) > 1.05 * vt and ringing[-1] == pytest.approx(vt, rel=1e-6)  # error x 0.8 a step, 66 steps
    _, cycle = speeds(1.1 * tau)
    assert min(cycle[-10:]) < 0.6 * vt and max(cycle[-10:]) > 1.3 * vt  # 0.49 v_t and 1.33 v_t in turn
    data, _ = speeds(1.5 * tau)
    assert data.warning[mujoco.mjtWarning.mjWARN_BADQACC].number > 0
