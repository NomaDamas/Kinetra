"""B-03e: the spring-damper (`spring_damper` part role, `Joint.spring`, `kinetra_engine.parts.spring`).

Definition: `packages/engine/src/kinetra_engine/parts/library/spring-damper-lc075k06m.json` (the rate of Lee Spring's stock
compression spring LC 075K 06 M, 2.77 N/mm; its damping and mass range are ours and say so). Every expected number is a hand
calculation from the textbook second-order system m q'' + c q' + k q = 0, not read from the code under test:

    omega0 = sqrt(k / m)          zeta = c / (2 sqrt(k m))          T = 2 pi / (omega0 sqrt(1 - zeta^2))   (zeta < 1)

The DoD number is the period of a mass on a spring against that formula: `integrate` steps the force law with RK4 and knows no
closed form, so a measured period equal to the formula is a test of both.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from gltf_validate import validate

from kinetra_core import Badge, JointSpring, PartDef, PartRole, Quantity, load_bodies
from kinetra_engine.parts import (
    PartCache,
    ShapeError,
    collision_proxy,
    integrate,
    joint_spring,
    mass_properties,
    part_glb,
    spring_response,
)

LIBRARY = Path(__file__).parents[1] / "src" / "kinetra_engine" / "parts" / "library"
PATH = LIBRARY / "spring-damper-lc075k06m.json"
SRC = {"ref": "B-03e test: value chosen by the test"}


def spring(k: float, c: float, kind: str = "slider") -> JointSpring:
    units = ("N/m", "N*s/m") if kind == "slider" else ("N*m/rad", "N*m*s/rad")
    return JointSpring.model_validate(
        {
            "stiffness": {"value": k, "unit": units[0], "badge": "declared", "source": SRC},
            "damping": {"value": c, "unit": units[1], "badge": "declared", "source": SRC},
        }
    )


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def part() -> PartDef:
    return PartDef.model_validate_json(PATH.read_text(encoding="utf-8"))


def value(v: float, unit: str, badge: str = "declared") -> Quantity:
    return Quantity(value=v, unit=unit, badge=badge, source=SRC)


# ---- the DoD: the period of a mass on a spring against the hand calculation ---------------------------------------------


@pytest.mark.parametrize(
    "k, m, omega0, period",
    [
        (100.0, 1.0, 10.0, 0.6283185307179586),  # sqrt(100/1) = 10 rad/s; 2 pi / 10
        (4000.0, 1.0, 63.245553203367585, 0.09934588265806982),  # sqrt(4000); 2 pi / 63.2456
        (2770.0, 2.77, 31.622776601683793, 0.19869176531613964),  # the library spring's rate: sqrt(2770 / 2.77) = sqrt(1000)
        (250.0, 0.25, 31.622776601683793, 0.19869176531613964),  # same ratio k/m, so the same period
    ],
)
def test_spring_period_of_a_mass_on_a_spring_is_two_pi_root_m_over_k(k, m, omega0, period):
    r = spring_response(spring(k, 0.0), m)
    assert r.natural_frequency == pytest.approx(omega0, rel=1e-12)
    assert r.period == pytest.approx(period, rel=1e-12)
    assert r.undamped_period == pytest.approx(period, rel=1e-12)
    assert r.damping_ratio == 0.0 and r.oscillates


@pytest.mark.parametrize("k, m", [(100.0, 1.0), (4000.0, 1.0), (2770.0, 2.77)])
def test_spring_integrated_period_equals_the_hand_calculated_period(k, m):
    expected = 2.0 * math.pi * math.sqrt(m / k)
    traj = integrate(spring(k, 0.0), m, q0=0.01, duration=20 * expected, dt=expected / 20000)
    assert traj.measured_period() == pytest.approx(expected, rel=1e-7)
    # undamped: the amplitude does not change (energy 1/2 k q^2 + 1/2 m v^2 is kept)
    energy = [0.5 * k * q * q + 0.5 * m * v * v for q, v in zip(traj.q, traj.v)]
    assert max(energy) / min(energy) - 1.0 < 1e-9
    assert max(traj.q) == pytest.approx(0.01, rel=1e-6)


def test_spring_period_does_not_depend_on_the_amplitude():
    # A linear spring: 1 mm and 5 cm swings take the same time.
    k, m = 100.0, 1.0
    expected = 2.0 * math.pi * math.sqrt(m / k)
    for amplitude in (0.001, 0.05):
        traj = integrate(spring(k, 0.0), m, q0=amplitude, duration=10 * expected, dt=expected / 20000)
        assert traj.measured_period() == pytest.approx(expected, rel=1e-7)


def test_spring_torsional_period_is_two_pi_root_inertia_over_stiffness():
    # hinge: k = 0.5 N*m/rad on I = 0.02 kg*m^2: omega0 = sqrt(0.5 / 0.02) = 5 rad/s, T = 2 pi / 5
    s = spring(0.5, 0.0, "hinge")
    r = spring_response(s, 0.02)
    assert r.natural_frequency == pytest.approx(5.0, rel=1e-12)
    assert r.period == pytest.approx(2.0 * math.pi / 5.0, rel=1e-12)
    traj = integrate(s, 0.02, q0=0.1, duration=10 * r.period, dt=r.period / 20000)
    assert traj.measured_period() == pytest.approx(2.0 * math.pi / 5.0, rel=1e-7)


# ---- damping ------------------------------------------------------------------------------------------------------------


def test_spring_damping_ratio_and_damped_period_345_triangle():
    # k = 100, m = 1: omega0 = 10; c = 12 gives zeta = 12 / (2 * 10) = 0.6 and omega_d = 10 sqrt(1 - 0.36) = 8 exactly
    r = spring_response(spring(100.0, 12.0), 1.0)
    assert r.damping_ratio == pytest.approx(0.6, rel=1e-12)
    assert r.damped_frequency == pytest.approx(8.0, rel=1e-12)
    assert r.period == pytest.approx(2.0 * math.pi / 8.0, rel=1e-12)
    assert r.period > r.undamped_period  # damping lengthens the period
    traj = integrate(spring(100.0, 12.0), 1.0, q0=0.01, duration=8.0, dt=1e-4)
    assert traj.measured_period() == pytest.approx(2.0 * math.pi / 8.0, rel=1e-6)


def test_spring_integration_matches_the_closed_form_solution_pointwise():
    # q0 = 1 mm at rest, k = 100, m = 1, c = 2: zeta = 0.1, omega_d = 10 sqrt(0.99), decay a = zeta omega0 = 1:
    #   q(t) = q0 e^{-a t} (cos wd t + (a / wd) sin wd t)
    q0, a = 0.001, 1.0
    wd = 10.0 * math.sqrt(0.99)
    traj = integrate(spring(100.0, 2.0), 1.0, q0=q0, duration=3.0, dt=1e-4)
    for t, q in zip(traj.t[::500], traj.q[::500]):
        exact = q0 * math.exp(-a * t) * (math.cos(wd * t) + (a / wd) * math.sin(wd * t))
        assert q == pytest.approx(exact, abs=1e-12)


def test_spring_amplitude_of_successive_peaks_falls_by_the_log_decrement():
    # zeta = 0.1: successive upward-crossing-to-peak amplitudes fall by exp(zeta omega0 T_d) = exp(2 pi zeta / sqrt(1 - zeta^2))
    traj = integrate(spring(100.0, 2.0), 1.0, q0=0.001, duration=3.0, dt=1e-4)
    peaks = [traj.q[i] for i in range(1, len(traj.q) - 1) if traj.q[i - 1] < traj.q[i] > traj.q[i + 1]]
    assert len(peaks) >= 3
    ratio = math.exp(2.0 * math.pi * 0.1 / math.sqrt(1.0 - 0.01))  # 1.8805...
    assert peaks[0] / peaks[1] == pytest.approx(ratio, rel=1e-4)
    assert peaks[1] / peaks[2] == pytest.approx(ratio, rel=1e-4)


@pytest.mark.parametrize("c", [20.0, 40.0])
def test_spring_critical_and_over_damping_do_not_oscillate(c):
    # k = 100, m = 1: critical damping is 2 sqrt(k m) = 20 N*s/m
    r = spring_response(spring(100.0, c), 1.0)
    assert r.damping_ratio == pytest.approx(c / 20.0, rel=1e-12)
    assert r.period is None and r.damped_frequency is None and not r.oscillates
    traj = integrate(spring(100.0, c), 1.0, q0=0.01, duration=3.0, dt=1e-4)
    assert min(traj.q) >= -1e-12  # never crosses the rest position
    with pytest.raises(ValueError, match="fewer than two"):
        traj.measured_period()


def test_spring_a_pure_damper_has_no_frequency_and_a_pure_spring_is_allowed():
    with pytest.raises(ValueError, match="stiffness 0"):
        spring_response(spring(0.0, 5.0), 1.0)
    assert spring_response(spring(5.0, 0.0), 1.0).damping_ratio == 0.0
    # a pure damper decays exponentially with the rate c / m: q = q0 e^{-c t / m}, v0 = -c q0 / m starts it there
    traj = integrate(spring(0.0, 5.0), 2.0, q0=1.0, v0=-2.5, duration=1.0, dt=1e-4)
    assert traj.q[-1] == pytest.approx(math.exp(-2.5), rel=1e-9)


# ---- gravity and the three planets --------------------------------------------------------------------------------------


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
def test_spring_weight_moves_the_rest_point_by_mg_over_k_and_leaves_the_period_alone(planet):
    g = load_bodies()[planet].gravity.value
    k, m = 100.0, 1.0
    period = 2.0 * math.pi * math.sqrt(m / k)
    traj = integrate(spring(k, 0.0), m, q0=0.0, force=m * g, duration=10 * period, dt=period / 20000)
    # sagging by m g / k: the motion swings between 0 and 2 m g / k about it, with the unchanged period
    assert max(traj.q) == pytest.approx(2.0 * m * g / k, rel=1e-6)
    assert traj.measured_period(about=m * g / k) == pytest.approx(period, rel=1e-7)


def test_spring_the_same_suspension_sags_six_times_less_on_the_moon_than_on_earth():
    bodies = load_bodies()
    k, m = 2770.0, 2.77
    sag = {p: m * bodies[p].gravity.value / k for p in ("earth", "moon")}
    assert sag["earth"] == pytest.approx(9.80665 / 1000.0, rel=1e-12)  # m / k = 1e-3 s^2 exactly
    assert sag["moon"] == pytest.approx(1.62 / 1000.0, rel=1e-12)
    assert sag["earth"] / sag["moon"] == pytest.approx(9.80665 / 1.62, rel=1e-12)


# ---- the part: stiffness and damping parameters, with badges ------------------------------------------------------------


def test_spring_part_is_a_spring_damper_with_stiffness_and_damping_parameters(part):
    assert part.role is PartRole.SPRING_DAMPER
    by = {p.name: p for p in part.parameters}
    assert set(by) == {"stiffness", "damping", "mass"}
    assert (by["stiffness"].unit.value, by["damping"].unit.value) == ("N/m", "N*s/m")
    assert by["stiffness"].default.value == 2770.0  # 2.77 N/mm on the Lee Spring page, in N/m
    assert by["stiffness"].min.value == 100.0 and by["stiffness"].max.value == 100000.0
    assert by["damping"].min.value == 0.0 and by["damping"].default.value == 20.0 and by["damping"].max.value == 2000.0
    assert part.mass_parameter == "mass"


def test_spring_default_joint_spring_is_the_datasheet_rate_with_its_own_badges(part):
    s = joint_spring(part)
    assert (s.stiffness.value, s.stiffness.unit.value) == (2770.0, "N/m")
    assert (s.damping.value, s.damping.unit.value) == (20.0, "N*s/m")
    # the rate is cited, with the place in the source; the damping is our own starting value and says so (not cited)
    assert s.stiffness.badge is Badge.CITE
    assert s.stiffness.source.url == "https://www.leespring.com/product/compression-spring-lc075k06m-music-wire"
    assert "Rate (N/mm) 2.77" in (s.stiffness.source.locator or "")
    assert s.damping.badge is Badge.DEFAULT
    assert "chosen by us" in s.damping.source.ref


def test_spring_instance_values_replace_the_defaults_and_keep_their_own_badge(part):
    s = joint_spring(part, {"stiffness": value(5000.0, "N/m"), "damping": value(0.0, "N*s/m", "estimate")})
    assert (s.stiffness.value, s.stiffness.badge) == (5000.0, Badge.DECLARED)
    assert (s.damping.value, s.damping.badge) == (0.0, Badge.ESTIMATE)
    assert s.stiffness.source.ref == SRC["ref"] and joint_spring(part).stiffness.value == 2770.0  # nothing leaked into the part


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"stiffness": value(99.0, "N/m")}, "outside the allowed range"),
        ({"stiffness": value(100001.0, "N/m")}, "outside the allowed range"),
        ({"damping": value(-1.0, "N*s/m")}, "outside the allowed range"),
        ({"damping": value(2001.0, "N*s/m")}, "outside the allowed range"),
        ({"stiffness": value(2770.0, "N*m/rad")}, "need unit"),
        ({"rate": value(2770.0, "N/m")}, "unknown parameters"),
    ],
)
def test_spring_rejects_values_outside_the_part(part, overrides, message):
    with pytest.raises(ShapeError, match=message):
        joint_spring(part, overrides)


def test_spring_joint_spring_refuses_a_part_that_is_not_a_spring_damper():
    d = load()
    d["role"] = None
    with pytest.raises(ShapeError, match="not 'spring_damper'"):
        joint_spring(PartDef.model_validate(d))


def test_spring_the_library_part_equals_the_schema_example(part):
    example = Path(__file__).parents[3] / "schemas" / "examples" / "PartDef.spring-damper-lc075k06m.json"
    assert PartDef.model_validate_json(example.read_text(encoding="utf-8")) == part


# ---- what the role requires of a definition -----------------------------------------------------------------------------


def with_params(**changes) -> dict:
    d = load()
    for p in d["parameters"]:
        if p["name"] in changes:
            p.update(changes[p["name"]])
    return d


def test_spring_role_needs_both_parameters():
    for name in ("stiffness", "damping"):
        d = load()
        d["parameters"] = [p for p in d["parameters"] if p["name"] != name]
        with pytest.raises(ValueError, match=f"needs the parameter '{name}'"):
            PartDef.model_validate(d)


def test_spring_role_takes_a_matching_unit_pair_either_linear_or_torsional():
    def q(v, unit):
        return {"badge": "default", "source": SRC, "value": v, "unit": unit}

    def param(name, unit, lo, default, hi):
        return {"name": name, "unit": unit, "default": q(default, unit), "min": q(lo, unit), "max": q(hi, unit)}

    base = {"id": "torsion-bar", "name": "Torsion bar", "role": "spring_damper"}
    ok = {**base, "parameters": [param("stiffness", "N*m/rad", 1.0, 5.0, 50.0), param("damping", "N*m*s/rad", 0.0, 0.1, 5.0)]}
    assert PartDef.model_validate(ok).role is PartRole.SPRING_DAMPER
    mixed = {**base, "parameters": [param("stiffness", "N/m", 1.0, 5.0, 50.0), param("damping", "N*m*s/rad", 0.0, 0.1, 5.0)]}
    with pytest.raises(ValueError, match="'N/m' and 'N\\*s/m' or in 'N\\*m/rad'"):
        PartDef.model_validate(mixed)
    wrong = {**base, "parameters": [param("stiffness", "m", 1.0, 5.0, 50.0), param("damping", "N*s/m", 0.0, 0.1, 5.0)]}
    with pytest.raises(ValueError, match="got 'm' and 'N\\*s/m'"):
        PartDef.model_validate(wrong)


def test_spring_role_stiffness_is_above_zero_and_damping_not_negative():
    zero = with_params(stiffness={"min": {**load()["parameters"][0]["min"], "value": 0.0}})
    with pytest.raises(ValueError, match="'stiffness': min must be above zero"):
        PartDef.model_validate(zero)
    negative = with_params(damping={"min": {**load()["parameters"][1]["min"], "value": -1.0}})
    with pytest.raises(ValueError, match="'damping': min must not be negative"):
        PartDef.model_validate(negative)


# ---- mass, centre, drawing (hand calculation) ---------------------------------------------------------------------------


def test_spring_mass_is_the_datasheet_weight_and_the_centre_is_half_way_along_the_axis(part):
    r = mass_properties(part, None)
    assert r.mass.value == 0.0136078  # 0.03 lb x 0.45359237 kg/lb = 0.01360777 kg, the page's Weight, written to 6 significant digits
    assert r.mass.value == pytest.approx(0.03 * 0.45359237, rel=1e-5)
    # symmetric about z = (4 + 50.8 + 4) mm / 2 = 29.4 mm (end caps 4 mm each, the 50.8 mm free length between them)
    assert r.center_of_mass.z == pytest.approx(0.0294, rel=1e-9)
    assert r.center_of_mass.x == pytest.approx(0.0, abs=1e-15) and r.center_of_mass.y == pytest.approx(0.0, abs=1e-15)


def test_spring_volume_of_the_drawn_silhouette():
    # two caps r 12.5 mm x 4 mm + 8 turns r 10.73 mm x 1.91 mm + 7 cores r 4 mm x gap, gap = (50.8 - 8 x 1.91) / 7 mm
    gap = (50.8e-3 - 8 * 1.91e-3) / 7
    expected = math.pi * (2 * 0.0125**2 * 0.004 + 8 * 0.01073**2 * 0.00191 + 7 * 0.004**2 * gap)
    assert expected == pytest.approx(1.1239e-5, rel=1e-4)  # 3.927 + 5.527 + 1.785 (1e-6 m^3)
    part = PartDef.model_validate(load())
    assert mass_properties(part, None).volume.value == pytest.approx(expected, rel=1e-12)


def test_spring_snap_points_sit_on_the_end_faces_and_are_declared(part):
    pts = {s.id: s for s in part.snap_points}
    assert set(pts) == {"end_a", "end_b"}
    assert pts["end_a"].position.z.evaluate({}) == 0.0
    assert pts["end_b"].position.z.evaluate({}) == pytest.approx(0.0588, abs=1e-12)  # caps and free length: 4 + 50.8 + 4 mm
    assert all(s.badge is Badge.DECLARED and s.kind == "spring_mount" for s in pts.values())


def test_spring_every_number_taken_from_the_datasheet_has_a_place_in_the_source(part):
    cited = [p.default for p in part.parameters if p.default.badge is Badge.CITE]
    assert len(cited) == 1 and cited[0].value == 2770.0
    for q in cited:
        assert q.source.locator and q.source.url
    # nothing else claims the datasheet: the ranges, the damping, the mass range are ours
    for p in part.parameters:
        for bound in (p.min, p.max):
            assert bound.badge is not Badge.CITE


def test_spring_collision_proxy_and_glb(part):
    proxy = collision_proxy(part)
    assert not proxy.filled_voids and proxy.volume_error.value == 0.0  # no void in the recipe: the proxy is the recipe
    validate(part_glb(part, None))


def test_spring_cache_keys_follow_stiffness_and_damping(part):
    cache = PartCache(max_entries=8)
    a = cache.mass_properties(part, None, {"stiffness": value(2770.0, "N/m")})
    assert cache.mass_properties(part, None, {"stiffness": value(2770.0, "N/m")}) is a
    b = cache.mass_properties(part, None, {"stiffness": value(5000.0, "N/m")})
    assert b is not a and cache.stats().misses == 2
    assert [u.name for u in b.derivation.parameters] == ["mass"]  # stiffness and damping are not in the recipe; they do not change the mass
    assert b.mass.value == a.mass.value


# ---- the force law on a slider and a hinge (Joint.spring) ---------------------------------------------------------------


def test_spring_unit_pairs_are_checked_by_the_joint_not_by_the_part_alone():
    from kinetra_core import Joint

    base = {
        "id": "strut",
        "kind": "slider",
        "a": {"instance": "x", "snap_point": "p"},
        "b": {"instance": "y", "snap_point": "p"},
    }
    ok = Joint.model_validate({**base, "spring": spring(100.0, 12.0).model_dump(mode="json")})
    assert ok.spring.stiffness.value == 100.0
    with pytest.raises(ValueError, match="spring of a slider joint is in 'N/m' and 'N\\*s/m'"):
        Joint.model_validate({**base, "spring": spring(100.0, 12.0, "hinge").model_dump(mode="json")})
    with pytest.raises(ValueError, match="spring of a hinge joint is in 'N\\*m/rad'"):
        Joint.model_validate({**base, "kind": "hinge", "spring": spring(100.0, 12.0).model_dump(mode="json")})
    with pytest.raises(ValueError, match="a fixed joint has no spring"):
        Joint.model_validate({**base, "kind": "fixed", "spring": spring(100.0, 12.0).model_dump(mode="json")})
