"""B-03a: the library part `wheel`, added by following `docs/process/add-part.md`.

Definition: `packages/engine/src/kinetra_engine/parts/library/wheel.json`. Every expected value is a hand calculation from
textbook formulas (cylinder volume and inertia, parallel axis theorem, rolling without slipping on an incline), not read
from the code under test. Dimensions are `default`-badged choices of this project; the two friction numbers are the only
cited values. Test inputs (override values, planets' gravity read through `load_body`) are declared by the test.

The recipe, at diameter D and tread width W (all lengths follow the two parameters), axle along part y:

    tire      radius 0.50 D, length 1.00 W, centre y = 0
    sidewall  radius 0.42 D, length 0.06 W, centre y = +-0.53 W   (one per side)
    rim       radius 0.32 D, length 0.10 W, centre y = +-0.61 W
    hub       radius 0.10 D, length 0.20 W, centre y = +-0.76 W
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from gltf_samples import catalog_material
from gltf_validate import validate

from kinetra_core import PartDef, Quantity, load_body
from kinetra_engine.parts import PartCache, ShapeError, collision_proxy, mass_properties, part_glb

LIBRARY = Path(__file__).parents[1] / "src" / "kinetra_engine" / "parts" / "library"
SRC = {"ref": "B-03a test: value chosen by the test"}
POM = catalog_material("pom-delrin-150")
RHO = 1420.0  # pom-delrin-150 in material_catalog.json (B-07)

# (id prefix, radius / D, length / W, centre |y| / W), the sidewall, rim and hub exist once on each side of the tire.
SIDES = (("sidewall", 0.42, 0.06, 0.53), ("rim", 0.32, 0.10, 0.61), ("hub", 0.10, 0.20, 0.76))


def load() -> PartDef:
    return PartDef.model_validate_json((LIBRARY / "wheel.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def wheel() -> PartDef:
    return load()


def params(**values: float) -> dict[str, Quantity]:
    return {k: Quantity(value=v, unit="m", badge="declared", source=SRC) for k, v in values.items()}


def ranges(part: PartDef) -> dict[str, tuple[float, float, float]]:
    return {p.name: (p.min.value, p.default.value, p.max.value) for p in part.parameters}


def rotate(q: dict[str, float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    """v' = v + 2 w (u x v) + 2 u x (u x v), u = (x, y, z)."""
    ux, uy, uz, w = q["x"], q["y"], q["z"], q["w"]
    cx = (uy * v[2] - uz * v[1], uz * v[0] - ux * v[2], ux * v[1] - uy * v[0])
    ccx = (uy * cx[2] - uz * cx[1], uz * cx[0] - ux * cx[2], ux * cx[1] - uy * cx[0])
    return tuple(v[i] + 2 * w * cx[i] + 2 * ccx[i] for i in range(3))  # type: ignore[return-value]


def quat(q) -> dict[str, float]:
    return {"x": q.x, "y": q.y, "z": q.z, "w": q.w}


def discs(D: float, W: float):
    """(mass, radius, length, centre y) of the seven discs by hand: the tire, and a sidewall, rim and hub on each side."""
    out = [(RHO * math.pi * (0.5 * D) ** 2 * W, 0.5 * D, W, 0.0)]
    for _, rf, lf, cf in SIDES:
        for s in (1.0, -1.0):
            r, length = rf * D, lf * W
            out.append((RHO * math.pi * r * r * length, r, length, s * cf * W))
    return out


def wheel_volume(D: float, W: float) -> float:
    return sum(m for m, *_ in discs(D, W)) / RHO


def wheel_inertia(D: float, W: float):
    """About the centre of mass, which is the origin (the wheel is symmetric about y = 0): axle y, and the two diameters."""
    iyy = sum(m * r * r / 2 for m, r, _, _ in discs(D, W))  # a solid cylinder about its own axis
    ixx = sum(m * (3 * r * r + h * h) / 12 + m * y * y for m, r, h, y in discs(D, W))  # about a diameter, parallel axis
    return ixx, iyy, ixx


# ---- mass, centre of mass, inertia ---------------------------------------------------------------------------------------


def test_wheel_default_mass_centre_and_inertia_match_hand_calculation(wheel):
    # D = 0.1, W = 0.04 m. V = pi W D^2 (0.25 + 2 (0.06 0.42^2 + 0.10 0.32^2 + 0.20 0.10^2)) = pi 0.04 0.01 0.295648 m^3.
    r = mass_properties(wheel, POM)
    volume = math.pi * 0.04 * 0.01 * (0.25 + 2 * (0.06 * 0.1764 + 0.10 * 0.1024 + 0.20 * 0.01))
    assert volume == pytest.approx(3.715222e-4, rel=1e-6)  # the hand value is the number the formula gives
    assert r.volume.value == pytest.approx(volume, rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * volume, rel=1e-12)  # 0.52756 kg
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    # About the axle (y): Iyy = (rho pi / 2) W D^4 (0.0625 + 2 (0.06 0.42^4 + 0.10 0.32^4 + 0.20 0.10^4)).
    iyy = 0.5 * RHO * math.pi * 0.04 * 1e-4 * (0.0625 + 2 * (0.06 * 0.42**4 + 0.10 * 0.32**4 + 0.20 * 0.1**4))
    assert iyy == pytest.approx(6.1002e-4, rel=1e-4)
    assert r.inertia.iyy == pytest.approx(iyy, rel=1e-9)
    assert (r.inertia.ixx, r.inertia.iyy, r.inertia.izz) == pytest.approx(wheel_inertia(0.1, 0.04), rel=1e-9)
    assert (r.inertia.ixy, r.inertia.ixz, r.inertia.iyz) == pytest.approx((0.0, 0.0, 0.0), abs=1e-15)
    assert r.inertia.iyy > r.inertia.ixx  # a wheel is a disc: the axle is the principal axis of the largest moment


@pytest.mark.parametrize("name", ["diameter", "width"])
@pytest.mark.parametrize("end", ["min", "max"])
def test_wheel_changing_a_dimension_changes_mass_and_inertia_as_the_formula_says(wheel, name, end):
    lo, default, hi = ranges(wheel)[name]
    value = lo if end == "min" else hi
    D, W = (value, 0.04) if name == "diameter" else (0.1, value)
    r = mass_properties(wheel, POM, params(**{name: value}))
    assert r.volume.value == pytest.approx(wheel_volume(D, W), rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * wheel_volume(D, W), rel=1e-12)
    assert (r.inertia.ixx, r.inertia.iyy, r.inertia.izz) == pytest.approx(wheel_inertia(D, W), rel=1e-9)
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)


def test_wheel_mass_scales_with_the_diameter_squared_and_the_width_linearly(wheel):
    base = mass_properties(wheel, POM).mass.value
    assert mass_properties(wheel, POM, params(diameter=0.2)).mass.value == pytest.approx(4 * base, rel=1e-12)
    assert mass_properties(wheel, POM, params(width=0.08)).mass.value == pytest.approx(2 * base, rel=1e-12)  # all lengths scale with W
    # Axle inertia scales as D^4 W (mass x radius squared).
    i0 = mass_properties(wheel, POM).inertia.iyy
    assert mass_properties(wheel, POM, params(diameter=0.2, width=0.08)).inertia.iyy == pytest.approx(32 * i0, rel=1e-9)


def test_wheel_mass_scales_with_the_material_density(wheel):
    al = catalog_material("al6061-t6")
    assert mass_properties(wheel, al).mass.value == pytest.approx(2700.0 * wheel_volume(0.1, 0.04), rel=1e-12)


def test_wheel_every_corner_of_the_parameter_range_is_a_valid_disjoint_recipe(wheel):
    import itertools

    r = ranges(wheel)
    for combo in itertools.product(*[(lo, hi) for lo, _, hi in r.values()]):
        values = dict(zip(r, combo))
        assert mass_properties(wheel, POM, params(**values)).mass.value == pytest.approx(RHO * wheel_volume(values["diameter"], values["width"]), rel=1e-12)


@pytest.mark.parametrize(("name", "bad"), [("diameter", 0.039), ("diameter", 0.31), ("width", 0.009), ("width", 0.121)])
def test_wheel_rejects_a_dimension_outside_its_range(wheel, name, bad):
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(wheel, POM, params(**{name: bad}))


def test_wheel_rejects_unknown_and_wrong_unit_parameters(wheel):
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(wheel, POM, params(radius=0.05))
    with pytest.raises(ShapeError, match="need unit"):
        mass_properties(wheel, POM, {"diameter": Quantity(value=0.1, unit="kg", badge="declared", source=SRC)})


# ---- contact geometry ----------------------------------------------------------------------------------------------------


def test_wheel_tire_is_the_one_contact_cylinder_and_its_axle_is_part_y(wheel):
    proxy = collision_proxy(wheel)
    assert not proxy.filled_voids and proxy.volume_error.value == 0.0 and len(proxy.geoms) == 7
    assert [g.id for g in proxy.geoms][0] == "tire"
    for g in proxy.geoms:
        assert g.primitive == "cylinder"  # an exact round contact surface, not a polygon
        axis = rotate(quat(g.orientation), (0.0, 0.0, 1.0))  # the cylinder's own axis, in part coordinates
        assert axis == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)  # every disc is coaxial: the axle is part y
        assert g.center[0] == pytest.approx(0.0, abs=1e-15) and g.center[2] == pytest.approx(0.0, abs=1e-15)
    tire = proxy.geoms[0]
    dims = {d.name: d.value for d in tire.dimensions}
    assert dims == pytest.approx({"radius": 0.05, "length": 0.04}, abs=1e-15)  # D / 2 and W
    assert tire.center == pytest.approx((0.0, 0.0, 0.0), abs=1e-15)


@pytest.mark.parametrize(("D", "W"), [(0.04, 0.01), (0.1, 0.04), (0.3, 0.12), (0.1, 0.12), (0.3, 0.01)])
def test_wheel_only_the_tire_touches_flat_ground_and_the_contact_is_a_line_along_the_axle(wheel, D, W):
    proxy = collision_proxy(wheel, params(diameter=D, width=W))
    radius = {g.id: next(d.value for d in g.dimensions if d.name == "radius") for g in proxy.geoms}
    length = {g.id: next(d.value for d in g.dimensions if d.name == "length") for g in proxy.geoms}
    # Axle at height D / 2 over the ground: the lowest point of each coaxial cylinder is its own radius below the axle.
    assert radius["tire"] == pytest.approx(D / 2, rel=1e-12)
    for gid, r in radius.items():
        if gid != "tire":
            assert r < radius["tire"], gid  # clear of the ground ...
            assert radius["tire"] - r >= 0.08 * D - 1e-12, gid  # ... by at least 0.08 D (the sidewall: 0.5 D - 0.42 D)
    # Flat ground meets a cylinder along a line parallel to its axis (y), as long as the tread is wide.
    assert length["tire"] == pytest.approx(W, rel=1e-12)


def test_wheel_side_discs_are_inside_the_tread_radius_and_beside_the_tread(wheel):
    proxy = collision_proxy(wheel)
    tire_half = 0.04 / 2
    for g in proxy.geoms[1:]:
        # Beside the tread (outside |y| <= W / 2): they cannot touch ground the tread rolls on.
        half = next(d.value for d in g.dimensions if d.name == "length") / 2
        assert abs(g.center[1]) - half >= tire_half - 1e-12, g.id
    ys = sorted(round(g.center[1], 12) for g in proxy.geoms)
    assert ys == pytest.approx([-0.0304, -0.0244, -0.0212, 0.0, 0.0212, 0.0244, 0.0304], abs=1e-12)  # 0.04 x (0.76, 0.61, 0.53)
    # Left-right symmetric about the wheel's mid-plane, so the centre of mass is on the axle at the middle of the tread.
    assert sum(g.center[1] * g.volume for g in proxy.geoms) == pytest.approx(0.0, abs=1e-18)


def test_wheel_hub_snap_point_is_on_the_axle_at_the_centre_of_mass_and_points_along_it(wheel):
    (hub,) = wheel.snap_points
    values = {"diameter": 0.2, "width": 0.1}
    assert hub.id == "hub" and hub.kind == "shaft" and {"shaft", "axle_mount"} <= set(hub.accepts)
    assert hub.position.evaluate(values) == (0.0, 0.0, 0.0)  # independent of the dimensions
    assert rotate(quat(hub.orientation), (0.0, 0.0, 1.0)) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)  # snap +Z = the axle = part +y
    assert mass_properties(wheel, POM, params(**values)).center_of_mass.y == pytest.approx(0.0, abs=1e-12)


# ---- friction material ---------------------------------------------------------------------------------------------------


def test_wheel_tread_friction_is_cited_with_a_place_and_kinetic_is_not_above_static(wheel):
    specs = {s.name: s for s in wheel.specs}
    assert set(specs) == {"tread_friction_static", "tread_friction_kinetic"}
    for s in specs.values():
        assert s.unit.value == "1" and s.badge.value == "cite"
        assert s.source.locator and "Table 5.1" in s.source.locator and s.source.url.startswith("https://openstax.org/")
        assert "reference pair" in s.source.ref or "reference-pair" in s.source.ref  # rubber on concrete, said to be a reference pair
    assert "not this wheel on any Kinetra planet" in specs["tread_friction_static"].source.ref
    assert specs["tread_friction_static"].value == 1.0 and specs["tread_friction_kinetic"].value == 0.7
    assert 0.0 < specs["tread_friction_kinetic"].value <= specs["tread_friction_static"].value
    # The planets' ground friction is planet data and is not read from the part (rule C4).
    assert load_body("earth").ground_friction.value.value != specs["tread_friction_static"].value


# ---- the compiled mass and inertia satisfy the rolling-without-slip relations ---------------------------------------------
# These tests do NOT simulate a rolling wheel. They take the compiled mass m and axle inertia I and check them against the
# relations of rolling without slipping (a = g sin(theta) / (1 + I / (m R^2)), friction needed), written out by hand here.
# The simulated rolling on the three planets (MuJoCo against the same formula) is carried by X-01b.


def rolling_ratio(wheel: PartDef, D: float = 0.1, W: float = 0.04) -> float:
    """k = I_axle / (m R^2) of the compiled wheel."""
    r = mass_properties(wheel, POM, params(diameter=D, width=W))
    return r.inertia.iyy / (r.mass.value * (D / 2) ** 2)


def test_wheel_rolling_ratio_is_the_hand_value_and_between_a_ring_and_a_solid_disc(wheel):
    # k = I / (m R^2) with the hand sums: I = 6.1002e-4 kg m^2, m = 0.52756 kg, R = 0.05 m  ->  0.4625.
    k = rolling_ratio(wheel)
    assert k == pytest.approx(6.1002e-4 / (0.52756 * 0.05**2), rel=1e-3)
    assert 0.25 < k < 0.5 + 1e-9  # a solid disc is 0.5 (all mass at the rim would be 1). Our wheel keeps its mass nearer the axle
    # The proportions fix k: it does not depend on the size or on the material.
    assert rolling_ratio(wheel, 0.3, 0.12) == pytest.approx(k, rel=1e-9)
    assert rolling_ratio(wheel, 0.04, 0.01) == pytest.approx(k, rel=1e-9)


@pytest.mark.parametrize("planet", ["earth", "mars", "moon"])
@pytest.mark.parametrize("theta_deg", [5.0, 20.0, 45.0])
def test_wheel_compiled_mass_and_inertia_satisfy_the_rolling_relations_on_every_planet(wheel, planet, theta_deg):
    g = load_body(planet).gravity.value
    theta = math.radians(theta_deg)
    r = mass_properties(wheel, POM)
    R, m, I = 0.05, r.mass.value, r.inertia.iyy
    L = 2.0  # slope length travelled, m
    # (1) Energy: m g L sin = 1/2 m v^2 + 1/2 I w^2 with v = w R (the contact point is at rest).
    v_energy = math.sqrt(2 * m * g * L * math.sin(theta) / (m + I / R**2))
    # (2) Forces: m a = m g sin - F, I a / R = F R (torque of the friction force F about the axle), no slipping.
    a = m * g * math.sin(theta) / (m + I / R**2)
    v_force = math.sqrt(2 * a * L)
    assert v_energy == pytest.approx(v_force, rel=1e-12)
    # (3) Step the closed-form motion (not a physics engine): the wheel turns w and travels x with x' = w R, w' = a / R, from rest. Semi-implicit Euler, dt = 1 ms.
    x = w = 0.0
    dt, t = 1e-3, 0.0
    while x < L:
        w += (a / R) * dt
        x += w * R * dt
        t += dt
    assert w * R == pytest.approx(v_energy, rel=2e-3)  # the stepped speed at x = L agrees with the closed form
    assert t == pytest.approx(math.sqrt(2 * L / a), rel=2e-3)
    # The acceleration is g sin(theta) / (1 + k): slower than a sliding block (1) and than a hoop (1/2).
    k = I / (m * R**2)
    assert a == pytest.approx(g * math.sin(theta) / (1 + k), rel=1e-12)
    assert 0.5 * g * math.sin(theta) < a < g * math.sin(theta)


def test_wheel_rolling_relation_scales_with_the_planets_gravity_and_not_with_the_wheel(wheel):
    g = {p: load_body(p).gravity.value for p in ("earth", "mars", "moon")}
    k = rolling_ratio(wheel)
    a = {p: g[p] * math.sin(math.radians(20.0)) / (1 + k) for p in g}
    assert a["moon"] / a["earth"] == pytest.approx(g["moon"] / g["earth"], rel=1e-12)
    assert a["mars"] / a["earth"] == pytest.approx(g["mars"] / g["earth"], rel=1e-12)
    for D, W in ((0.04, 0.01), (0.3, 0.12)):  # k, so the acceleration, is the same for every size
        assert g["earth"] * math.sin(math.radians(20.0)) / (1 + rolling_ratio(wheel, D, W)) == pytest.approx(a["earth"], rel=1e-9)


def test_wheel_no_slip_slope_limit_from_the_cited_static_friction(wheel):
    # The friction force is F = m g sin(theta) k / (1 + k) and may not exceed mu_s m g cos(theta): tan(theta) <= mu_s (1 + k) / k.
    k = rolling_ratio(wheel)
    mu_s = {s.name: s.value for s in wheel.specs}["tread_friction_static"]
    limit = math.atan(mu_s * (1 + k) / k)
    assert math.degrees(limit) == pytest.approx(math.degrees(math.atan(1.0 * (1 + 0.4625) / 0.4625)), abs=0.1)  # 72.4 degrees
    # The same bound with the kinetic coefficient (what a slipping wheel gets) is lower.
    mu_k = {s.name: s.value for s in wheel.specs}["tread_friction_kinetic"]
    assert math.atan(mu_k * (1 + k) / k) < limit
    needed = lambda theta: math.sin(theta) * k / (1 + k) / math.cos(theta)  # mu the slope needs  # noqa: E731
    assert needed(math.radians(30.0)) < mu_s  # a 30 degree slope: rolls
    assert needed(math.radians(80.0)) > mu_s  # an 80 degree slope: slips
    # The bound does not involve gravity: the same on every planet.
    for planet in ("earth", "mars", "moon"):
        g = load_body(planet).gravity.value
        N, F = g * math.cos(limit), g * math.sin(limit) * k / (1 + k)  # per unit mass
        assert F / N == pytest.approx(mu_s, rel=1e-12)


# ---- the file ------------------------------------------------------------------------------------------------------------


def test_wheel_file_is_named_after_its_id_and_has_no_voids(wheel):
    assert wheel.role is not None and wheel.role.value == "wheel"  # B-03b PartRole: a wheel actuator or joint check can find it
    assert wheel.id == "wheel" and (LIBRARY / "wheel.json").exists()
    assert all(c.operation == "add" for c in wheel.shape.components)  # no hole: nothing is filled or left undrawn


def test_wheel_glb_is_valid_over_the_parameter_range(wheel):
    r = ranges(wheel)
    for combo in (tuple(lo for lo, _, _ in r.values()), tuple(hi for _, _, hi in r.values())):
        validate(part_glb(wheel, POM, params(**dict(zip(r, combo)))))
    glb = validate(part_glb(wheel, POM))
    assert [m["name"] for m in glb.doc["meshes"]][0] == "tire"
    assert len(glb.doc["meshes"]) == 7


def test_wheel_says_what_every_number_is(wheel):
    # Dimensions, ranges and the snap pose are `default` (Kinetra's choice, not a datasheet); the friction pair is `cite`.
    badges = {p.default.badge.value for p in wheel.parameters} | {p.min.badge.value for p in wheel.parameters}
    badges |= {p.max.badge.value for p in wheel.parameters} | {wheel.shape.badge.value} | {s.badge.value for s in wheel.snap_points}
    assert badges == {"default"}
    assert all("not a datasheet" in p.min.source.ref for p in wheel.parameters)
    assert "not a datasheet" in wheel.shape.source.ref
    r = mass_properties(wheel, POM)
    assert r.derivation.shape.badge.value == "default"
    assert {b.value for b in r.derivation.input_badges} == {"cite", "default"}  # the density is cited, the dimensions are not


def test_wheel_compiles_through_the_cache_like_directly(wheel):
    cache = PartCache(max_entries=8)
    assert cache.mass_properties(wheel, POM, None) == mass_properties(wheel, POM)
    assert cache.mass_properties(wheel, POM, None) is cache.mass_properties(wheel, POM, None)
    assert (cache.stats().misses, cache.stats().hits) == (1, 2)


def test_wheel_definition_is_deterministic_text():
    text = (LIBRARY / "wheel.json").read_text(encoding="utf-8")
    assert json.dumps(load().model_dump(mode="json", exclude_none=True), indent=2) + "\n" == text
