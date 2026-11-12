"""W-03c: the planet's ground friction is a distribution in the verdict's assumption table, and a value drawn from it is the
ground's friction in the compiled model.

`uv run pytest packages/engine -q -k friction`. Hand calculation: a block on a plane tilted by theta, Coulomb friction mu,
starts to slide when tan(theta) > mu, so the critical angle is atan(mu); above it the block accelerates down the plane at
g (sin(theta) - mu cos(theta)), below it stays at rest. The ends of each planet's distribution are written out below (from
`docs/architecture/bodies.md`), so a changed data file fails here, not only the simulation.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest
from pydantic import ValidationError

from kinetra_core import (
    Assumption,
    AssumptionTable,
    Project,
    UniformDistribution,
    VerdictAssumptionTable,
    load_body,
    verdict_assumption_table,
)
from kinetra_engine.compiler import build_body_tree, to_mjcf

SRC = {"ref": "W-03c test fixture: value chosen by the test", "locator": "test_ground_friction.py"}
ENDS = {  # uniform low, high of data/bodies (tan of the weakest and strongest representative angle)
    "earth": (0.3443, 0.7813),  # tan 19 deg, tan 38 deg
    "mars": (0.3249, 0.7002),  # tan 18 deg, tan 35 deg
    "moon": (0.4142, 0.9004),  # tan 22.5 deg, tan 42 deg
}
PART_FRICTION = 1.0
"""The block's declared material friction: above every planet's upper end (0.9004), so under the min rule of X-01e the
ground's value is the pair's friction."""
HALF = (0.1, 0.1, 0.025)
"""A flat block: it tips over at atan(0.1 / 0.025) = 76 deg, far above every critical angle here (42 deg at most)."""


def q(value, unit):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(v):
    return {"offset": v, "terms": []}


def block(planet: str) -> Project:
    """One flat 0.2 x 0.2 x 0.05 m block resting on the ground (bottom face at z = 0), free, no joints."""
    hx, hy, hz = HALF
    shape = {"badge": "declared", "source": SRC, "components": [
        {"id": "c", "operation": "add",
         "primitive": {"kind": "box", "size_x": ax(2 * hx), "size_y": ax(2 * hy), "size_z": ax(2 * hz)},
         "position": {"x": ax(0.0), "y": ax(0.0), "z": ax(0.0)}}]}
    material = {"id": "mat", "name": "Test material", "density": q(7850.0, "kg/m^3"), "yield_strength": q(2.5e8, "Pa"),
                "elastic_modulus": q(2.0e11, "Pa"), "friction": q(PART_FRICTION, "1")}
    part = {"id": "slab", "name": "slab", "parameters": [], "snap_points": [], "shape": shape}
    inst = {"id": "slab1", "part": "slab", "material": "mat", "pose": {"badge": "declared", "source": SRC,
            "position": {"x": 0.0, "y": 0.0, "z": hz}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
    return Project.model_validate({"design": {"materials": [material], "parts": [part], "instances": [inst], "joints": []},
                                   "world": {"planet": planet}})


def slide(project: Project, mu: float, theta: float) -> tuple[np.ndarray, np.ndarray]:
    """Times and down-slope velocities for 1 s from rest. The incline is the planet's gravity turned by `theta` about y,
    `g (sin, 0, -cos)`: in the plane's frame the same problem as the plane tilted under vertical gravity (the rolling test
    of `test_actuator.py` does the same), and the block stays a grounded assembly."""
    tree = build_body_tree(project)
    model = mujoco.MjModel.from_xml_string(to_mjcf(tree, ground_friction=mu))
    assert model.geom("__kinetra_ground").friction[0] == mu  # the drawn value is the ground's sliding coefficient
    g = tree.planet.gravity.value
    model.opt.gravity[:] = (g * math.sin(theta), 0.0, -g * math.cos(theta))
    data = mujoco.MjData(model)
    t, v = [], []
    for _ in range(round(1.0 / model.opt.timestep)):
        mujoco.mj_step(model, data)
        t.append(data.time)
        v.append(float(data.qvel[0]))  # down the slope: +x
    return np.array(t), np.array(v)


# --- the verdict's table ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_ground_friction_is_a_distribution_row_of_the_verdicts_table(planet):
    body = load_body(planet)
    own = Assumption.model_validate({"key": "payload_mass", "label": "Payload mass", "value": q(2.0, "kg"),
                                     "distribution": {"kind": "uniform", "low": 1.5, "high": 2.5, "badge": "declared",
                                                      "source": SRC},
                                     "confidence": "med"})
    table = verdict_assumption_table(AssumptionTable(assumptions=(own,)), body, block(planet).design)  # no breakable joint
    assert table.planet == planet
    assert [a.key for a in table.rows] == ["ground_friction", "payload_mass"]  # planet rows first, then the project's
    row = table.row("ground_friction")
    assert row == body.ground_friction  # value, distribution, badges, sources and confidence as in the data file
    assert not row.editable
    d = row.distribution
    assert isinstance(d, UniformDistribution)
    assert (d.low, d.high) == ENDS[planet]
    assert row.value.value == pytest.approx((d.low + d.high) / 2, abs=5e-5)  # nominal = mean, rounded to 4 places
    assert row.value.badge.value == d.badge.value == "estimate"
    assert row.confidence.value == "low"
    assert table.row("payload_mass") == own
    with pytest.raises(KeyError, match="no assumption"):
        table.row("gravity")


def test_ground_friction_stays_out_of_the_projects_table():
    """The project's stored table still rejects the planet row (rule C4); only the verdict's composed table holds it."""
    mars = load_body("mars")
    with pytest.raises(ValidationError, match="planet constant"):
        AssumptionTable(assumptions=(mars.ground_friction,))
    assert verdict_assumption_table(AssumptionTable(), mars, block("mars").design).rows == (mars.ground_friction,)


def test_ground_friction_planet_rows_are_read_only_planet_constants():
    earth = load_body("earth").ground_friction
    with pytest.raises(ValidationError, match="read-only"):
        VerdictAssumptionTable(planet="earth", planet_rows=(earth.model_copy(update={"editable": True}),), engine_rows=(),
                               project=AssumptionTable())
    with pytest.raises(ValidationError, match="not a planet constant"):
        VerdictAssumptionTable(planet="earth", planet_rows=(earth.model_copy(update={"key": "payload_mass"}),), engine_rows=(),
                               project=AssumptionTable())
    with pytest.raises(ValidationError, match="duplicate planet row"):
        VerdictAssumptionTable(planet="earth", planet_rows=(earth, earth), engine_rows=(), project=AssumptionTable())


# --- the ends of the distribution in the compiled model ---------------------------------------------------------------


@pytest.mark.parametrize("end", [0, 1], ids=["low", "high"])
@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_ground_friction_critical_slide_angle_matches_the_hand_calculation_at_both_ends(planet, end):
    project = block(planet)
    d = verdict_assumption_table(project.assumptions, load_body(planet), project.design).row("ground_friction").distribution
    mu = (d.low, d.high)[end]
    assert mu == ENDS[planet][end]
    g = load_body(planet).gravity.value
    critical = math.atan(mu)

    # half a degree below the critical angle: the block holds. MuJoCo's contact is soft, so the block creeps at a small constant
    # speed instead of standing still (measured 1.7e-4 m/s to 1.8e-3 m/s after 1 s, 8e-5 to 2.1e-4 of g * 1 s); the bound is
    # 1e-3 of g * 1 s, about a tenth of what half a degree above reaches (9e-3 to 1.2e-2 of g * 1 s).
    t, v = slide(project, mu, critical - math.radians(0.5))
    window = t >= 0.2  # after the contact has settled
    assert abs(np.polyfit(t[window], v[window], 1)[0]) < 1e-3 * g
    assert abs(v[-1]) < 1e-3 * g * 1.0

    # above it the block slides at g (sin - mu cos): 0.5 deg is the threshold, 2 deg a clear slide
    for above in (0.5, 2.0):
        theta = critical + math.radians(above)
        hand = g * (math.sin(theta) - mu * math.cos(theta))
        t, v = slide(project, mu, theta)
        slope = np.polyfit(t[window], v[window], 1)[0]
        assert slope == pytest.approx(hand, rel=1e-2)  # measured -0.26 % .. +0.57 % (X-01e contact parameters)
        assert v[-1] > 1e-3 * g * 1.0


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_ground_friction_outside_the_distribution_does_not_enter_the_model(planet):
    """A drawn value comes from the planet's distribution; a value outside it is a planet the data does not describe (rule C4)."""
    tree = build_body_tree(block(planet))
    low, high = ENDS[planet]
    for mu in (low - 1e-4, high + 1e-4):
        with pytest.raises(ValueError):
            to_mjcf(tree, ground_friction=mu)
