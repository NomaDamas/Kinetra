"""B-03b: the library part `motor-37d-12v-50-1` (Pololu 37D gearmotor, 12 V, 50:1) and the motor torque-speed curve.

Definition: `packages/engine/src/kinetra_engine/parts/library/motor-37d-12v-50-1.json`. Every expected value is a hand
calculation from the datasheet's own numbers (200 rpm, 210 kg*mm, 205 g, the drawing's diameters and lengths) and textbook
formulas (cylinder volume and inertia, parallel axes, a straight line), not read from the code under test. The torque-speed
curve in the definition is the datasheet's no-load and stall points joined by the line a DC motor follows.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from gltf_validate import validate

from kinetra_core import Badge, PartDef, PartRole
from kinetra_engine.parts import (
    CurveRangeError,
    PartCache,
    collision_proxy,
    evaluate,
    mass_properties,
    motor_characteristics,
    motor_torque_limit,
    part_glb,
)

LIBRARY = Path(__file__).parents[1] / "src" / "kinetra_engine" / "parts" / "library"
PATH = LIBRARY / "motor-37d-12v-50-1.json"

KGF = 9.80665  # m/s^2: 1 kgf = 9.80665 N (standard gravity), so 1 kg*mm = 9.80665e-3 N*m
STALL = 210 * KGF * 1e-3  # N*m, the datasheet's stall extrapolation, 210 kg*mm = 2.0593965
NO_LOAD = 200 * 2 * math.pi / 60  # rad/s, 200 rpm = 20.943951...


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def motor() -> PartDef:
    return PartDef.model_validate_json(PATH.read_text(encoding="utf-8"))


def motor_with(**changes) -> PartDef:
    d = load()
    d.update(changes)
    return PartDef.model_validate(d)


# ---- the two numbers of the DoD: no-load speed and stall torque ---------------------------------------------------------


def test_motor_no_load_speed_is_200_rpm_and_stall_torque_is_210_kg_mm(motor):
    c = motor_characteristics(motor)
    assert c.no_load_speed == pytest.approx(20.943951023931955, rel=1e-12)  # 200 rpm
    assert c.no_load_speed == pytest.approx(NO_LOAD, rel=1e-12)
    assert c.stall_torque == pytest.approx(2.0593965, rel=1e-12)  # 210 kg*mm
    assert c.stall_torque == pytest.approx(STALL, rel=1e-12)
    assert c.rated_voltage == 12.0


def test_motor_curve_gives_stall_torque_at_zero_speed_and_zero_torque_at_no_load_speed(motor):
    assert motor_torque_limit(motor, 0.0) == pytest.approx(STALL, rel=1e-12)
    assert motor_torque_limit(motor, NO_LOAD) == 0.0
    # direction does not matter: the same torque limit turning the other way
    assert motor_torque_limit(motor, -NO_LOAD / 4) == pytest.approx(motor_torque_limit(motor, NO_LOAD / 4), rel=1e-12)


@pytest.mark.parametrize("fraction", [0.0, 0.1, 0.25, 0.5, 0.9, 1.0])
def test_motor_curve_is_the_line_from_stall_to_no_load(motor, fraction):
    # a straight line: torque = stall * (1 - speed / no_load)
    assert motor_torque_limit(motor, fraction * NO_LOAD) == pytest.approx(STALL * (1 - fraction), rel=1e-12, abs=1e-15)


def test_motor_beyond_no_load_speed_delivers_nothing_not_a_negative_torque(motor):
    assert motor_torque_limit(motor, 1.5 * NO_LOAD) == 0.0
    assert motor_torque_limit(motor, -10 * NO_LOAD) == 0.0


def test_motor_curve_evaluation_never_extrapolates(motor):
    curve = motor.curves[0].curve
    assert evaluate(curve, 0.0) == pytest.approx(STALL, rel=1e-12)
    for x in (-1e-9, NO_LOAD * (1 + 1e-12), 100.0):
        with pytest.raises(CurveRangeError, match="outside the curve's range"):
            evaluate(curve, x)


def test_motor_model_against_the_datasheets_max_power_point_differs_by_the_documented_amount(motor):
    """Datasheet p.13: 98 rpm at 100 kg*mm (max power, 10 W). The line from the summary table's stall and no-load points
    gives 200 * (1 - 100/210) = 104.76 rpm there: the model runs 6.9 % faster at that load. This is a known approximation
    (the datasheet's own fit is 200 - 1.0 * torque, i.e. its graph's extrapolated stall is not exactly 210), not a check
    that the model is right to better than that."""
    torque = 100 * KGF * 1e-3
    speed = NO_LOAD * (1 - torque / STALL)  # inverse of the curve
    assert motor_torque_limit(motor, speed) == pytest.approx(torque, rel=1e-12)
    rpm = speed * 60 / (2 * math.pi)
    assert rpm == pytest.approx(200 * (1 - 100 / 210), rel=1e-12)
    assert rpm / 98 - 1 == pytest.approx(0.069, abs=0.001)


def test_motor_peak_power_of_the_line_model_is_stall_times_no_load_over_four(motor):
    # P(w) = T0 (1 - w/w0) w is largest at w0/2 with P = T0 w0 / 4 = 2.0593965 * 20.94395 / 4 = 10.78 W
    best = max(motor_torque_limit(motor, NO_LOAD * k / 1000) * NO_LOAD * k / 1000 for k in range(1001))
    assert best == pytest.approx(STALL * NO_LOAD / 4, rel=1e-6)
    assert best == pytest.approx(10.78, abs=0.01)


# ---- the definition ----------------------------------------------------------------------------------------------------


def test_motor_is_a_motor_part_with_its_specs(motor):
    assert motor.role is PartRole.MOTOR
    specs = {s.name: s for s in motor.specs}
    assert specs["rated_voltage"].unit.value == "V" and specs["rated_voltage"].value == 12.0
    assert specs["no_load_current"].value == 0.2 and specs["no_load_current"].unit.value == "A"
    assert specs["stall_current"].value == 5.5
    assert specs["gear_ratio"].value == 50.0
    assert specs["no_load_speed"].value == pytest.approx(NO_LOAD, rel=1e-12)
    assert specs["stall_torque"].value == pytest.approx(STALL, rel=1e-12)
    assert specs["continuous_torque_limit"].value == pytest.approx(100 * KGF * 1e-3, rel=1e-12)  # 100 kg*mm


def test_motor_every_number_is_cited_with_a_place_in_the_source(motor):
    """Spec values, the curve, the mass and the outline come from the Pololu datasheet and drawing: each says where."""
    d = load()
    cited = [*d["specs"], d["curves"][0]["curve"], d["shape"]]
    cited += [d["parameters"][0][k] for k in ("default", "min", "max")]
    for item in cited:
        assert item["badge"] == "cite"
        src = item["source"]
        assert src["url"].startswith("https://www.pololu.com/") and src["locator"]
    assert motor.curves[0].curve.badge is Badge.CITE


def test_motor_snap_points_are_declared_poses_of_this_project(motor):
    for s in motor.snap_points:
        assert s.badge is Badge.DECLARED
    assert {s.id: s.kind for s in motor.snap_points} == {"mount": "motor_mount", "shaft": "shaft"}


def test_motor_has_no_dimension_parameter_and_a_fixed_mass(motor):
    (p,) = motor.parameters
    assert p.name == "mass" and p.unit.value == "kg"
    assert p.min.value == p.default.value == p.max.value == 0.205  # 205 g, the product page's weight


def test_motor_definition_round_trips_as_json(motor):
    again = PartDef.model_validate_json(motor.model_dump_json())
    assert again == motor and hash(again) == hash(motor)
    assert PartDef.model_validate(motor.model_dump(mode="json", exclude_none=True)) == motor


# ---- mass, centre of mass, inertia from the drawing (hand calculation) ------------------------------------------------


# (radius, length, z centre) in m from the drawing: face plate at z = 0, output shaft towards +z
PIECES = [
    (0.003, 0.016, 0.014),  # D shaft: 6 mm dia, 16 mm long, starting 6 mm from the face plate
    (0.006, 0.006, 0.003),  # boss: 12 mm dia, 6 mm
    (0.0184, 0.024, -0.012),  # gearbox: 36.8 mm dia, L = 24.0 mm
    (0.0174, 0.0307, -(0.024 + 0.0307 / 2)),  # motor can: 34.8 mm dia, 30.7 mm
    (0.017, 0.0154, -(0.024 + 0.0307 + 0.0154 / 2)),  # encoder: 34.0 mm dia, 15.4 mm
]


def test_motor_mass_is_the_datasheet_weight_and_the_centre_lies_on_the_axis(motor):
    r = mass_properties(motor, None)
    assert r.mass.value == pytest.approx(0.205, rel=1e-12)
    vols = [math.pi * rad**2 * length for rad, length, _ in PIECES]
    total = sum(vols)
    assert r.volume.value == pytest.approx(total, rel=1e-12)
    z = sum(v * zc for v, (_, _, zc) in zip(vols, PIECES)) / total
    assert r.center_of_mass.x == pytest.approx(0.0, abs=1e-15)
    assert r.center_of_mass.y == pytest.approx(0.0, abs=1e-15)
    assert r.center_of_mass.z == pytest.approx(z, rel=1e-9)
    # by hand, volumes in 1e-6 m^3 (0.452, 0.679, 25.53, 29.20, 13.98; total 69.82) times their z: sum -2318.7e-9 m^4 / 69.82e-6 = -33.2 mm
    assert z == pytest.approx(-0.03321, abs=2e-5)


def test_motor_inertia_about_the_shaft_axis_and_across_it(motor):
    r = mass_properties(motor, None)
    vols = [math.pi * rad**2 * length for rad, length, _ in PIECES]
    total = sum(vols)
    rho = 0.205 / total
    zc = sum(v * z for v, (_, _, z) in zip(vols, PIECES)) / total
    izz = sum(rho * v * rad**2 / 2 for v, (rad, _, _) in zip(vols, PIECES))
    # across the axis through the centre of mass: I = m/12 (3 r^2 + L^2) + m d^2 per piece (parallel axes)
    ixx = sum(rho * v * (3 * rad**2 + length**2) / 12 + rho * v * (z - zc) ** 2 for v, (rad, length, z) in zip(vols, PIECES))
    assert r.inertia.izz == pytest.approx(izz, rel=1e-9)
    assert r.inertia.ixx == pytest.approx(ixx, rel=1e-9)
    assert r.inertia.iyy == pytest.approx(ixx, rel=1e-9)
    assert r.inertia.ixy == pytest.approx(0.0, abs=1e-15)
    assert 0.5 * 0.205 * 0.0184**2 > r.inertia.izz * 0.9  # a solid 36.8 mm cylinder's m r^2 / 2 bounds it from above


def test_motor_collision_proxy_and_glb(motor):
    proxy = collision_proxy(motor)
    assert proxy.volume_error.value == pytest.approx(0.0, abs=1e-12)  # solid cylinders: nothing is filled
    validate(part_glb(motor, None))


def test_motor_cache_keys_follow_the_curve(motor):
    cache = PartCache(max_entries=8)
    cache.mass_properties(motor, None)
    cache.mass_properties(motor, None)
    assert cache.stats().hits == 1
    d = load()
    d["curves"][0]["curve"]["points"][0]["y"] = STALL * 1.01
    other = PartDef.model_validate(d)
    cache.mass_properties(other, None)
    assert cache.stats().misses == 2


# ---- a part that says "motor" has to have a motor's numbers -----------------------------------------------------------


def test_motor_role_needs_the_torque_speed_curve():
    d = load()
    d["curves"] = []
    with pytest.raises(ValueError, match="needs the curve 'torque_speed'"):
        PartDef.model_validate(d)


def test_motor_role_needs_the_rated_voltage():
    d = load()
    d["specs"] = [s for s in d["specs"] if s["name"] != "rated_voltage"]
    with pytest.raises(ValueError, match="needs the spec 'rated_voltage'"):
        PartDef.model_validate(d)


def test_motor_rated_voltage_must_be_volts():
    d = load()
    for s in d["specs"]:
        if s["name"] == "rated_voltage":
            s["unit"], s["value"] = "A", 12.0
    with pytest.raises(ValueError, match="positive voltage"):
        PartDef.model_validate(d)


@pytest.mark.parametrize(
    "points, message",
    [
        ([(1.0, 2.0), (20.0, 0.0)], "starts at speed 0"),
        ([(0.0, 0.0), (20.0, 0.0)], "stall torque must be positive"),
        ([(0.0, 2.0), (20.0, 0.5)], "ends at no load"),
        ([(0.0, 2.0), (10.0, 0.5), (20.0, 1.0), (30.0, 0.0)], "must not rise with speed"),
    ],
)
def test_motor_curve_must_look_like_a_motor(points, message):
    d = load()
    d["curves"][0]["curve"]["points"] = [{"x": x, "y": y} for x, y in points]
    with pytest.raises(ValueError, match=message):
        PartDef.model_validate(d)


def test_motor_curve_units_must_be_speed_and_torque():
    d = load()
    d["curves"][0]["curve"]["x_unit"] = "m/s"
    with pytest.raises(ValueError, match=r"speed \[rad/s\] -> torque"):
        PartDef.model_validate(d)


@pytest.mark.parametrize(
    "points, message",
    [
        ([{"x": 0.0, "y": 1.0}], "at least 2 items"),
        ([{"x": 0.0, "y": 1.0}, {"x": 0.0, "y": 0.0}], "strictly increasing"),
        ([{"x": 0.0, "y": 1.0}, {"x": 2.0, "y": 0.5}, {"x": 1.0, "y": 0.0}], "strictly increasing"),
        ([{"x": 0.0, "y": 1.0}, {"x": float("nan"), "y": 0.0}], "finite"),
    ],
)
def test_curve_rejects_bad_points(points, message):
    d = load()
    d["curves"][0]["curve"]["points"] = points
    with pytest.raises(ValueError, match=message):
        PartDef.model_validate(d)


def test_motor_curve_without_badge_or_source_is_rejected():
    for key in ("badge", "source"):
        d = load()
        del d["curves"][0]["curve"][key]
        with pytest.raises(ValueError):
            PartDef.model_validate(d)


def test_cited_curve_needs_a_place_in_its_source():
    d = load()
    src = d["curves"][0]["curve"]["source"]
    del src["locator"], src["url"]
    with pytest.raises(ValueError, match="cited"):
        PartDef.model_validate(d)


def test_part_curve_names_must_be_unique():
    d = load()
    d["curves"].append(d["curves"][0])
    with pytest.raises(ValueError, match="duplicate curve name"):
        PartDef.model_validate(d)


def test_motor_torque_limit_refuses_a_part_that_is_not_a_motor(motor):
    d = load()
    d["role"] = "wheel"
    wheel = PartDef.model_validate(d)
    with pytest.raises(ValueError, match="not 'motor'"):
        motor_torque_limit(wheel, 1.0)
    assert motor_with(role=None).role is None


def test_motor_schema_example_is_the_library_part():
    """`schemas/examples/PartDef.motor-37d-12v-50-1.json` (checked against the JSON Schema by validate_examples.py) is a copy."""
    example = Path(__file__).parents[3] / "schemas" / "examples" / "PartDef.motor-37d-12v-50-1.json"
    assert example.read_bytes() == PATH.read_bytes()


# ---- evaluation stays finite for every curve the model accepts ---------------------------------------------------------

BIG = 1.7e308  # near the largest float (1.797e308): spans and slopes of such curves overflow in the naive formula


def big_curve(points):
    from kinetra_core import Curve

    return Curve.model_validate(
        {"badge": "declared", "source": {"ref": "B-03b test"}, "x_unit": "rad/s", "y_unit": "N*m", "points": [{"x": x, "y": y} for x, y in points]}
    )


@pytest.mark.parametrize(
    "points",
    [
        [(-BIG, -BIG), (BIG, BIG)],  # span 2*BIG and rise 2*BIG overflow
        [(-BIG, BIG), (BIG, -BIG)],
        [(0.0, BIG), (1e-300, -BIG)],  # slope = -2*BIG / 1e-300
        [(0.0, 5e-324), (5e-324 * 2, 0.0)],  # subnormal x steps
        [(0.0, 1.0), (1e308, 2.0), (1.7e308, -1.0)],
    ],
)
def test_curve_evaluation_is_finite_and_between_the_neighbours_for_extreme_finite_curves(points):
    curve = big_curve(points)
    xs = [p[0] for p in points]
    probes = [xs[0], xs[-1], (xs[0] / 2 + xs[-1] / 2), xs[0] + (xs[-1] / 4 - xs[0] / 4), xs[-1] - (xs[-1] / 8 - xs[0] / 8)]
    for x in probes:
        y = evaluate(curve, x)
        assert math.isfinite(y), (points, x)
        assert min(p[1] for p in points) <= y <= max(p[1] for p in points)


def test_curve_evaluation_is_exact_at_the_points_and_midway_for_a_huge_span():
    curve = big_curve([(-BIG, -BIG), (BIG, BIG)])
    assert evaluate(curve, -BIG) == -BIG and evaluate(curve, BIG) == BIG
    assert evaluate(curve, 0.0) == pytest.approx(0.0, abs=1e292)  # the line y = x: 0 at 0 within rounding of 1.7e308 * 1e-16
    assert evaluate(curve, BIG / 2) == pytest.approx(BIG / 2, rel=1e-12)


def test_curve_evaluation_refuses_nan_and_inf():
    curve = big_curve([(0.0, 1.0), (1.0, 0.0)])
    for x in (math.nan, math.inf, -math.inf):
        with pytest.raises(CurveRangeError):
            evaluate(curve, x)
