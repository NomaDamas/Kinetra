"""B-03e: the spring-damper part `spring-damper-lee-lc032b08` (stiffness and damping parameters) and the period of a mass on it.

Definition: `packages/engine/src/kinetra_engine/parts/library/spring-damper-lee-lc032b08.json`. The spring rate and outline are
the Lee Spring product page's numbers (LC 032B 08 S316: 5.99 N/mm, 19.05 mm free length, 4.57 mm outside diameter). Expected values are
hand calculations from the textbook mass-spring formulas, T = 2 pi sqrt(m / k), zeta = c / (2 sqrt(k m)), T_d = T / sqrt(1 - zeta^2),
the logarithmic decrement 2 pi zeta / sqrt(1 - zeta^2), not read from the code under test. The period is also *measured*: the
equation of motion is integrated here by a fourth-order Runge-Kutta step written in this file (it shares no code with
`kinetra_engine.parts.springs`) and the time between zero crossings is compared with the hand value.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from gltf_validate import validate

from kinetra_core import Badge, PartDef, PartRole, Quantity
from kinetra_engine.parts import (
    PartCache,
    ShapeError,
    collision_proxy,
    mass_properties,
    oscillation,
    part_glb,
    spring_damper_characteristics,
    spring_damper_force,
)

LIBRARY = Path(__file__).parents[1] / "src" / "kinetra_engine" / "parts" / "library"
PATH = LIBRARY / "spring-damper-lee-lc032b08.json"
SRC = {"ref": "B-03e test: value chosen by the test"}

K = 5990.0  # N/m, the page's 5.99 N/mm
FREE_LENGTH = 0.01905
OUTSIDE_DIAMETER = 0.00457


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spring() -> PartDef:
    return PartDef.model_validate_json(PATH.read_text(encoding="utf-8"))


def declared(value: float, unit: str) -> Quantity:
    return Quantity(value=value, unit=unit, badge=Badge.DECLARED, source=SRC)


def spring_with(**changes) -> PartDef:
    d = load()
    d.update(changes)
    return PartDef.model_validate(d)


def set_range(d: dict, name: str, **fields) -> dict:
    p = next(p for p in d["parameters"] if p["name"] == name)
    for key, value in fields.items():
        p[key] = {**p[key], "value": value}
    return d


# ---- the DoD: a mass on the spring oscillates with the period of the hand calculation ----------------------------------


def simulate(k: float, c: float, m: float, x0: float, steps_per_period: int = 4000, periods: int = 10):
    """Integrate m x'' = -k x - c x' by RK4 from rest at x0 and return (times, positions). Independent of the code under test."""
    w0 = math.sqrt(k / m)
    dt = 2 * math.pi / w0 / steps_per_period
    x, v, t = x0, 0.0, 0.0
    ts, xs = [t], [x]

    def acc(x, v):
        return (-k * x - c * v) / m

    for _ in range(steps_per_period * periods):
        k1x, k1v = v, acc(x, v)
        k2x, k2v = v + dt / 2 * k1v, acc(x + dt / 2 * k1x, v + dt / 2 * k1v)
        k3x, k3v = v + dt / 2 * k2v, acc(x + dt / 2 * k2x, v + dt / 2 * k2v)
        k4x, k4v = v + dt * k3v, acc(x + dt * k3x, v + dt * k3v)
        x += dt / 6 * (k1x + 2 * k2x + 2 * k3x + k4x)
        v += dt / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)
        t += dt
        ts.append(t)
        xs.append(x)
    return ts, xs


def downward_zero_crossings(ts, xs):
    """Times (linearly interpolated) at which x goes from positive to negative."""
    out = []
    for i in range(len(xs) - 1):
        if xs[i] > 0.0 >= xs[i + 1]:
            out.append(ts[i] + (ts[i + 1] - ts[i]) * xs[i] / (xs[i] - xs[i + 1]))
    return out


def test_spring_period_of_half_a_kilogram_on_the_cited_spring_is_57_4_ms(spring):
    # by hand: w0 = sqrt(5990 / 0.5) = sqrt(11980) = 109.4532 rad/s, T = 2 pi / 109.4532 = 0.0574052 s
    k = spring_damper_characteristics(spring).stiffness
    assert k == 5990.0
    o = oscillation(k, 0.0, 0.5)
    assert o.natural_angular_frequency == pytest.approx(109.4532, rel=1e-6)
    assert o.period == pytest.approx(0.0574052, rel=1e-6)
    assert o.damped_period == pytest.approx(o.period, rel=1e-15)  # no damping: the same
    assert o.damping_ratio == 0.0


@pytest.mark.parametrize(
    "k, m, period",
    [
        (1.0, 1.0, 2 * math.pi),  # w0 = 1 rad/s
        (100.0, 1.0, 0.6283185307179586),  # w0 = 10 rad/s, T = pi / 5
        (400.0, 1.0, math.pi / 10),  # w0 = 20
        (100.0, 4.0, 2 * math.pi / 5),  # w0 = sqrt(25) = 5: four times the mass, twice the period of m = 1
        (5990.0, 0.5, 0.05740522973590041),
    ],
)
def test_spring_undamped_period_is_two_pi_sqrt_m_over_k(k, m, period):
    assert oscillation(k, 0.0, m).period == pytest.approx(period, rel=1e-12)


@pytest.mark.parametrize("mass", [0.05, 0.5, 5.0])
def test_spring_measured_period_of_a_mass_on_the_part_matches_the_hand_calculation(spring, mass):
    """The period measured from an integrated trajectory (time between zero crossings, ten periods) equals 2 pi sqrt(m / k)."""
    k = spring_damper_characteristics(spring, {"damping": declared(0.0, "N*s/m")}).stiffness
    ts, xs = simulate(k, 0.0, mass, x0=0.002)
    crossings = downward_zero_crossings(ts, xs)
    assert len(crossings) == 10
    measured = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
    assert measured == pytest.approx(2 * math.pi * math.sqrt(mass / K), rel=1e-6)


def test_spring_stiffer_spring_shortens_the_period_by_the_square_root_of_the_ratio(spring):
    soft = spring_damper_characteristics(spring, {"stiffness": declared(1000.0, "N/m")}).stiffness
    stiff = spring_damper_characteristics(spring, {"stiffness": declared(4000.0, "N/m")}).stiffness
    assert (soft, stiff) == (1000.0, 4000.0)
    assert oscillation(stiff, 0.0, 1.0).period == pytest.approx(oscillation(soft, 0.0, 1.0).period / 2, rel=1e-12)  # sqrt(4000/1000) = 2
    assert oscillation(soft, 0.0, 1.0).period == pytest.approx(0.19869176531592203, rel=1e-12)  # 2 pi / sqrt(1000)


def test_spring_damped_period_damping_ratio_and_decay_match_the_hand_calculation(spring):
    """m = 0.5 kg on the part's own k = 5990 and c = 20: zeta = 20 / (2 sqrt(5990 * 0.5)) = 20 / 109.4532 = 0.182727;
    T_d = 0.0574052 / sqrt(1 - 0.182727^2) = 0.0583883 s; each period the peak falls by exp(-2 pi zeta / sqrt(1 - zeta^2))."""
    c = spring_damper_characteristics(spring)
    assert c.damping == 20.0
    o = oscillation(c.stiffness, c.damping, 0.5)
    assert o.critical_damping == pytest.approx(109.4532, rel=1e-6)  # 2 sqrt(k m) = 2 sqrt(2995)
    assert o.damping_ratio == pytest.approx(0.182727, rel=1e-5)
    assert o.damped_period == pytest.approx(0.0583883, rel=1e-5)
    ts, xs = simulate(c.stiffness, c.damping, 0.5, x0=0.002)
    crossings = downward_zero_crossings(ts, xs)
    assert (crossings[-1] - crossings[0]) / (len(crossings) - 1) == pytest.approx(0.0583883, rel=1e-4)
    # peaks one damped period apart fall by the factor exp(-zeta w0 T_d) = exp(-2 pi zeta / sqrt(1 - zeta^2))
    zeta = 20 / (2 * math.sqrt(5990 * 0.5))
    ratio = math.exp(-2 * math.pi * zeta / math.sqrt(1 - zeta**2))
    assert ratio == pytest.approx(0.31106, abs=1e-5)  # by hand: 2 pi x 0.182727 / sqrt(1 - 0.03339) = 1.16783; exp(-1.16783) = 0.31106
    peaks = [xs[i] for i in range(1, len(xs) - 1) if xs[i - 1] < xs[i] >= xs[i + 1] and xs[i] > 0]
    assert peaks[1] / peaks[0] == pytest.approx(ratio, rel=1e-3)


def test_spring_critical_damping_does_not_oscillate():
    o = oscillation(100.0, 20.0, 1.0)  # 2 sqrt(100 * 1) = 20 N*s/m
    assert o.critical_damping == pytest.approx(20.0, rel=1e-15)
    assert o.damping_ratio == pytest.approx(1.0, rel=1e-15)
    assert o.damped_period is None
    assert oscillation(100.0, 50.0, 1.0).damped_period is None  # overdamped
    ts, xs = simulate(100.0, 20.0, 1.0, x0=0.01, steps_per_period=400, periods=5)
    assert downward_zero_crossings(ts, xs) == []  # it creeps back to 0 and never crosses


def test_spring_force_pulls_towards_the_saved_pose_and_against_the_motion():
    assert spring_damper_force(5990.0, 20.0, 0.001, 0.0) == pytest.approx(-5.99, rel=1e-12)  # 5990 N/m x 1 mm
    assert spring_damper_force(5990.0, 20.0, -0.001, 0.0) == pytest.approx(5.99, rel=1e-12)
    assert spring_damper_force(5990.0, 20.0, 0.0, 0.1) == pytest.approx(-2.0, rel=1e-12)  # 20 N*s/m x 0.1 m/s
    assert spring_damper_force(5990.0, 20.0, 0.0, 0.0) == 0.0
    # at the maximum of the cited spring's travel (free length - solid height = 7.62 mm) the load is 45.64 N: the page's own figure
    travel = 0.01905 - 0.01143
    assert abs(spring_damper_force(5990.0, 0.0, travel, 0.0)) == pytest.approx(45.64, rel=2e-3)  # 5990 * 0.00762 = 45.64


@pytest.mark.parametrize(
    "k, c, m, message",
    [
        (0.0, 0.0, 1.0, "stiffness"),
        (-1.0, 0.0, 1.0, "stiffness"),
        (math.inf, 0.0, 1.0, "stiffness"),
        (1.0, -0.1, 1.0, "damping"),
        (1.0, math.nan, 1.0, "damping"),
        (1.0, 0.0, 0.0, "mass"),
        (1.0, 0.0, math.nan, "mass"),
    ],
)
def test_spring_oscillation_refuses_numbers_that_are_not_a_spring_a_damper_and_a_mass(k, c, m, message):
    with pytest.raises(ValueError, match=message):
        oscillation(k, c, m)


@pytest.mark.parametrize(
    "k, c, m, w0, zeta, c_crit",
    [
        (1e200, 1e200, 1e200, 1.0, 0.5, 2e200),  # k * m = inf in the naive form: zeta came out 0
        (1e-200, 1e-200, 1e-200, 1.0, 0.5, 2e-200),  # k * m = 0: ZeroDivisionError in the naive form
        (1e300, 1e150, 1e-10, 1e155, 5e4, None),  # w0 = 1e150 / 1e-5; zeta = 1e150 / (2 x 1e150 x 1e-5) = 5e4: overdamped
    ],
)
def test_spring_oscillation_is_exact_where_k_times_m_overflows_or_underflows(k, c, m, w0, zeta, c_crit):
    # by hand: w0 = sqrt(k / m), zeta = c / (2 sqrt(k) sqrt(m)); with k = c = m = x both are 1 and 1/2
    o = oscillation(k, c, m)
    assert o.natural_angular_frequency == pytest.approx(w0, rel=1e-12)
    assert o.damping_ratio == pytest.approx(zeta, rel=1e-12)
    assert o.period == pytest.approx(2 * math.pi / w0, rel=1e-12)
    if c_crit is not None:
        assert o.critical_damping == pytest.approx(c_crit, rel=1e-12)
        assert o.damped_period == pytest.approx(2 * math.pi / math.sqrt(0.75), rel=1e-12)  # T / sqrt(1 - 1/4)
    else:
        assert o.damped_period is None


@pytest.mark.parametrize(
    "k, c, m, what",
    [
        (1.7e308, 0.0, 5e-324, "natural angular frequency"),  # sqrt(k) / sqrt(m) = 6e315
        (1e308, 0.0, 1e308, "critical damping"),  # 2 sqrt(k) sqrt(m) = 2e308
        (5e-324, 0.0, 1.7e308, "period"),  # w0 is subnormal, 2 pi / w0 overflows
    ],
)
def test_spring_oscillation_refuses_a_result_that_is_not_a_finite_float(k, c, m, what):
    with pytest.raises(ValueError, match=f"{what}.*not a finite float"):
        oscillation(k, c, m)


# ---- stiffness and damping are parameters ------------------------------------------------------------------------------


def test_spring_stiffness_and_damping_are_parameters_with_ranges_and_units(spring):
    p = {p.name: p for p in spring.parameters}
    assert p["stiffness"].unit.value == "N/m"
    assert (p["stiffness"].min.value, p["stiffness"].default.value, p["stiffness"].max.value) == (100.0, 5990.0, 100000.0)
    assert p["damping"].unit.value == "N*s/m"
    assert (p["damping"].min.value, p["damping"].default.value, p["damping"].max.value) == (0.0, 20.0, 500.0)
    assert spring.role is PartRole.SPRING_DAMPER


def test_spring_instance_values_override_the_defaults_within_the_range(spring):
    c = spring_damper_characteristics(spring, {"stiffness": declared(2500.0, "N/m"), "damping": declared(7.5, "N*s/m")})
    assert (c.stiffness, c.damping) == (2500.0, 7.5)
    ends = spring_damper_characteristics(spring, {"stiffness": declared(100.0, "N/m"), "damping": declared(500.0, "N*s/m")})
    assert (ends.stiffness, ends.damping) == (100.0, 500.0)
    top = spring_damper_characteristics(spring, {"stiffness": declared(100000.0, "N/m"), "damping": declared(0.0, "N*s/m")})
    assert (top.stiffness, top.damping) == (100000.0, 0.0)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"stiffness": declared(99.0, "N/m")}, "outside the allowed range"),
        ({"stiffness": declared(100001.0, "N/m")}, "outside the allowed range"),
        ({"damping": declared(-1.0, "N*s/m")}, "outside the allowed range"),
        ({"damping": declared(501.0, "N*s/m")}, "outside the allowed range"),
        ({"stiffness": declared(1000.0, "N")}, "need unit 'N/m'"),
        ({"damping": declared(1.0, "N/m")}, "need unit 'N\\*s/m'"),
        ({"rate": declared(1000.0, "N/m")}, "unknown parameters"),
    ],
)
def test_spring_parameters_out_of_range_wrong_unit_or_unknown_are_rejected(spring, overrides, message):
    with pytest.raises(ShapeError, match=message):
        spring_damper_characteristics(spring, overrides)


def test_spring_characteristics_refuse_a_part_that_is_not_a_spring_damper(spring):
    d = load()
    d["role"] = None
    with pytest.raises(ValueError, match="not 'spring_damper'"):
        spring_damper_characteristics(PartDef.model_validate(d))
    d["role"] = "wheel"
    with pytest.raises(ValueError, match="role 'wheel', not 'spring_damper'"):
        spring_damper_characteristics(PartDef.model_validate(d))


# ---- a part that says "spring_damper" has to have the two parameters ---------------------------------------------------


def drop(d: dict, name: str) -> dict:
    d["parameters"] = [p for p in d["parameters"] if p["name"] != name]
    return d


def test_spring_role_needs_the_stiffness_parameter():
    with pytest.raises(ValueError, match="needs the parameter 'stiffness'"):
        PartDef.model_validate(drop(load(), "stiffness"))


def test_spring_role_needs_the_damping_parameter():
    with pytest.raises(ValueError, match="needs the parameter 'damping'"):
        PartDef.model_validate(drop(load(), "damping"))


def test_spring_stiffness_must_be_a_spring_rate_and_damping_a_damping_coefficient():
    d = load()
    for p in d["parameters"]:
        if p["name"] == "stiffness":
            p["unit"] = "N"
            for key in ("default", "min", "max"):
                p[key]["unit"] = "N"
    with pytest.raises(ValueError, match="spring rate in 'N/m'"):
        PartDef.model_validate(d)
    d = load()
    for p in d["parameters"]:
        if p["name"] == "damping":
            p["unit"] = "N/m"
            for key in ("default", "min", "max"):
                p[key]["unit"] = "N/m"
    with pytest.raises(ValueError, match="damping coefficient in 'N\\*s/m'"):
        PartDef.model_validate(d)


def test_spring_stiffness_must_stay_above_zero_over_the_whole_range():
    with pytest.raises(ValueError, match="min must be above zero"):
        PartDef.model_validate(set_range(load(), "stiffness", min=0.0))


def test_spring_damping_must_never_be_negative_but_may_be_zero():
    with pytest.raises(ValueError, match="min must not be negative"):
        PartDef.model_validate(set_range(load(), "damping", min=-1.0))
    assert PartDef.model_validate(set_range(load(), "damping", min=0.0, default=0.0)).role is PartRole.SPRING_DAMPER


def test_spring_other_roles_and_plain_parts_need_no_spring_parameters():
    for role in ("wheel", "battery", "tank", None):
        assert PartDef.model_validate(drop(drop({**load(), "role": role}, "stiffness"), "damping")).role == (None if role is None else PartRole(role))


# ---- the definition: cited numbers, drawn envelope, mass ---------------------------------------------------------------


def test_spring_rate_and_catalogue_numbers_are_cited_with_a_place_in_the_source(spring):
    p = {p.name: p for p in spring.parameters}
    assert p["stiffness"].default.badge is Badge.CITE
    assert p["stiffness"].default.source.url == "https://www.leespring.com/compression-specific/331081"
    assert "5.99" in p["stiffness"].default.source.locator
    specs = {s.name: s for s in spring.specs}
    assert specs["free_length"].value == 0.01905 and specs["free_length"].unit.value == "m"
    assert specs["solid_height"].value == 0.01143
    assert specs["outside_diameter"].value == 0.00457
    assert specs["wire_diameter"].value == 0.00081
    assert specs["active_coils"].value == 11.82 and specs["total_coils"].value == 13.82
    assert specs["load_at_solid_height"].value == 45.64 and specs["load_at_solid_height"].unit.value == "N"
    for s in specs.values():
        assert s.badge is Badge.CITE and s.source.locator and s.source.url


def test_spring_rate_agrees_with_the_coil_formula_within_the_catalogue_tolerance(spring):
    """Cross-check of the cited rate by the textbook coil spring formula k = G d^4 / (8 D^3 n) with the page's own geometry:
    d = 0.81 mm, mean coil diameter D = OD - d = 3.76 mm, n = 11.82 active coils, G = 69 GPa (type 316 stainless, generic).
    by hand: d^4 = 4.305e-13 m^4, D^3 = 5.3157e-8 m^3, k = 69e9 x 4.305e-13 / (8 x 5.3157e-8 x 11.82) = 5909 N/m: 1.4 % below the
    page's 5990 N/m, inside the page's own rate tolerance of 10 % (3.42 lb/in on 34.2)."""
    d, od, n, g = 0.00081, 0.00457, 11.82, 69e9
    big_d = od - d
    k = g * d**4 / (8 * big_d**3 * n)
    assert k == pytest.approx(5909, rel=2e-3)
    assert abs(k / 5990.0 - 1) < 0.10


def test_spring_the_estimated_and_default_values_say_how_they_were_made(spring):
    p = {p.name: p for p in spring.parameters}
    assert p["damping"].default.badge is Badge.DEFAULT and "zeta" in p["damping"].default.source.ref
    for key in ("min", "max"):
        assert getattr(p["stiffness"], key).badge is Badge.DEFAULT
        assert getattr(p["damping"], key).badge is Badge.DEFAULT
    for key in ("default", "min", "max"):
        assert getattr(p["mass"], key).badge is Badge.ESTIMATE
        assert "8000" in getattr(p["mass"], key).source.ref
    assert spring.shape.badge is Badge.DECLARED
    for s in spring.snap_points:
        assert s.badge is Badge.DECLARED and s.kind == "spring_end" and s.accepts == ("spring_end",)


def test_spring_the_estimated_mass_is_wire_volume_times_steel_density(spring):
    # by hand: wire length = pi (4.57 - 0.81) mm x 13.82 coils = 163.25 mm, volume = pi/4 (0.81 mm)^2 x 163.25 mm = 84.1 mm^3,
    # x 8000 kg/m^3 = 0.673 g
    length = math.pi * (0.00457 - 0.00081) * 13.82
    mass = math.pi / 4 * 0.00081**2 * length * 8000.0
    assert mass == pytest.approx(0.000673, rel=2e-3)
    r = mass_properties(spring, None)
    assert r.mass.value == pytest.approx(0.000673, rel=1e-12)


def test_spring_mass_centre_and_inertia_of_the_seven_turns(spring):
    r = mass_properties(spring, None)
    # seven discs of radius 2.285 mm and thickness t = 19.05 mm / 13 = 1.465 mm at z = -L/2 + t/2 + 2 i t, i = 0..6: symmetric
    # about the middle, so the centre of mass is the origin
    t = FREE_LENGTH / 13
    r0 = OUTSIDE_DIAMETER / 2
    assert r.volume.value == pytest.approx(7 * math.pi * r0**2 * t, rel=1e-12)  # 168.26 mm^3
    assert r.center_of_mass.x == pytest.approx(0.0, abs=1e-15)
    assert r.center_of_mass.y == pytest.approx(0.0, abs=1e-15)
    assert r.center_of_mass.z == pytest.approx(0.0, abs=1e-12)
    m = 0.000673
    zs = [-FREE_LENGTH / 2 + t / 2 + 2 * i * t for i in range(7)]
    assert sum(zs) == pytest.approx(0.0, abs=1e-15)
    izz = m * r0**2 / 2  # about the axis: a solid cylinder's m r^2 / 2 whatever the thickness
    ixx = sum(m / 7 * ((3 * r0**2 + t**2) / 12 + z**2) for z in zs)  # parallel axes, equal mass per disc
    assert r.inertia.izz == pytest.approx(izz, rel=1e-9)
    assert r.inertia.ixx == pytest.approx(ixx, rel=1e-9)
    assert r.inertia.iyy == pytest.approx(ixx, rel=1e-9)


def test_spring_snap_points_are_the_two_ends_of_the_axis(spring):
    ends = {s.id: s.position.z.offset for s in spring.snap_points}
    assert ends == {"end_a": pytest.approx(-FREE_LENGTH / 2), "end_b": pytest.approx(FREE_LENGTH / 2)}
    assert all(s.position.x.offset == 0.0 and s.position.y.offset == 0.0 for s in spring.snap_points)


def test_spring_collision_proxy_has_no_voids_and_the_glb_validates(spring):
    proxy = collision_proxy(spring)
    assert proxy.volume_error.value == pytest.approx(0.0, abs=1e-12)  # discs: nothing is filled
    validate(part_glb(spring, None))


def test_spring_definition_round_trips_and_the_schema_example_is_the_library_part(spring):
    assert PartDef.model_validate(spring.model_dump(mode="json", exclude_none=True)) == spring
    again = PartDef.model_validate_json(spring.model_dump_json())
    assert again == spring and hash(again) == hash(spring)
    example = Path(__file__).parents[3] / "schemas" / "examples" / "PartDef.spring-damper-lee-lc032b08.json"
    assert example.read_bytes() == PATH.read_bytes()


def test_spring_cache_keys_follow_the_stiffness(spring):
    cache = PartCache(max_entries=8)
    cache.mass_properties(spring, None)
    cache.mass_properties(spring, None)
    assert cache.stats().hits == 1
    other = PartDef.model_validate(set_range(load(), "stiffness", default=6000.0))
    cache.mass_properties(other, None)
    assert cache.stats().misses == 2
