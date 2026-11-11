"""B-01b: collision proxy from a part's shape recipe, and its volume error against the recipe.

Expected numbers are written out by hand from the textbook volume formulas, not read back from the code under test. Test
dimensions are fixtures declared by the test (`사용자 선언`), not real part data.
"""

from __future__ import annotations

import math
import random

import pytest

from kinetra_core import Badge, CollisionProxy, PartDef, Quantity
from kinetra_engine.parts import ShapeError, collision_proxy, mass_properties
from kinetra_engine.parts.collision import DEFAULT_TOLERANCE

SRC = {"ref": "unit-test fixture", "locator": "test_proxy.py"}
RHO = 1000.0


def q(value, unit="m", badge="declared", source=None):
    return {"value": value, "unit": unit, "badge": badge, "source": source or SRC}


def ax(offset=0.0, terms=()):
    return {"offset": offset, "terms": [{"param": p, "factor": f} for p, f in terms]}


def pos(x=0.0, y=0.0, z=0.0):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def box(id, sx, sy, sz, at=(0, 0, 0), op="add", quat=None):
    return {
        "id": id,
        "operation": op,
        "primitive": {"kind": "box", "size_x": ax(sx), "size_y": ax(sy), "size_z": ax(sz)},
        "position": pos(*at),
        **({"orientation": quat} if quat else {}),
    }


def cyl(id, radius, length, at=(0, 0, 0), op="add", quat=None):
    return {
        "id": id,
        "operation": op,
        "primitive": {"kind": "cylinder", "radius": ax(radius), "length": ax(length)},
        "position": pos(*at),
        **({"orientation": quat} if quat else {}),
    }


def sphere(id, radius, at=(0, 0, 0), op="add"):
    return {"id": id, "operation": op, "primitive": {"kind": "sphere", "radius": ax(radius)}, "position": pos(*at)}


def part(components, parameters=(), badge="declared", source=None):
    return PartDef.model_validate(
        {
            "id": "test-part",
            "name": "Test part",
            "parameters": list(parameters),
            "shape": {"badge": badge, "source": source or SRC, "components": components},
        }
    )


def material():
    from kinetra_core import Material

    return Material.model_validate(
        {
            "id": "test-material",
            "name": "Test material",
            "density": q(RHO, "kg/m^3"),
            "yield_strength": q(1.0e7, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"),
            "friction": q(0.5, "1"),
        }
    )


def approx(x):
    return pytest.approx(x, rel=1e-9, abs=1e-15)


S2 = math.sqrt(0.5)
ROT_X90 = {"x": S2, "y": 0.0, "z": 0.0, "w": S2}


def dims(geom):
    return {d.name: d.value for d in geom.dimensions}


# --- three parts: the DoD's "부품 3종의 프록시 생성" -------------------------------------------------------------------


def test_proxy_of_a_solid_block_is_that_box_with_zero_error():
    # 0.2 x 0.1 x 0.3 m block centred at (0.1, 0, 0.15): V = 0.006 m^3.
    r = collision_proxy(part([box("block", 0.2, 0.1, 0.3, at=(0.1, 0.0, 0.15))]))
    (g,) = r.geoms
    assert (g.id, g.primitive) == ("block", "box")
    assert dims(g) == {"size_x": approx(0.2), "size_y": approx(0.1), "size_z": approx(0.3)}
    assert g.center == (approx(0.1), 0.0, approx(0.15))
    assert (g.orientation.x, g.orientation.y, g.orientation.z, g.orientation.w) == (0.0, 0.0, 0.0, 1.0)
    assert g.volume == approx(0.006)
    assert r.proxy_volume.value == approx(0.006) and r.recipe_volume.value == approx(0.006)
    assert r.volume_error.value == 0.0
    assert r.filled_voids == ()


def test_proxy_of_a_rotated_rod_with_a_ball_keeps_both_primitives_unchanged():
    # Rod r = 0.05, length 0.4 lying along y (axis turned 90 degrees about x), ball r = 0.1 beside it. They do not overlap.
    r = collision_proxy(
        part([cyl("rod", 0.05, 0.4, at=(0.0, 0.0, 0.0), quat=ROT_X90), sphere("ball", 0.1, at=(0.0, 0.4, 0.0))])
    )
    rod, ball = r.geoms
    assert (rod.primitive, ball.primitive) == ("cylinder", "sphere")
    assert dims(rod) == {"radius": approx(0.05), "length": approx(0.4)}
    assert (rod.orientation.x, rod.orientation.w) == (approx(S2), approx(S2))
    assert dims(ball) == {"radius": approx(0.1)}
    assert ball.center == (0.0, approx(0.4), 0.0)
    # V = pi r^2 h + 4/3 pi R^3 = pi * 0.0025 * 0.4 + 4/3 pi * 0.001
    want = math.pi * 0.001 + 4.0 / 3.0 * math.pi * 0.001
    assert r.proxy_volume.value == approx(want) and r.volume_error.value == 0.0


def test_proxy_of_a_blind_pocket_fills_it_and_reports_the_volume_error():
    # Plate 0.3 x 0.2 x 0.02 (V = 0.0012 m^3) with a 0.05 m radius pocket 0.01 deep (V = pi 0.0025 0.01 = 2.5e-5 pi m^3).
    # A blind pocket is not a through-bore: it is not decomposed, so it is filled (B-01b) and the error is the filled volume.
    comps = [box("plate", 0.3, 0.2, 0.02), cyl("pocket", 0.05, 0.01, at=(0.05, 0.0, 0.005), op="subtract")]
    r = collision_proxy(part(comps))
    pocket = math.pi * 0.0025 * 0.01  # pi r^2 h
    assert r.derivation.method == "added-primitives" and r.derivation.tolerance is None
    assert [g.id for g in r.geoms] == ["plate"]  # the pocket is not a proxy geom
    assert r.proxy_volume.value == approx(0.0012)  # the plate, solid
    assert r.recipe_volume.value == approx(0.0012 - pocket)
    assert r.volume_error.value == approx(pocket / (0.0012 - pocket))  # about +7.0 %
    assert r.decomposed_voids == ()
    (f,) = r.filled_voids
    assert (f.id, f.primitive) == ("pocket", "cylinder") and f.volume == approx(pocket)
    # The recipe volume is the volume B-01a reports for the same part.
    assert mass_properties(part(comps), material()).volume.value == approx(r.recipe_volume.value)


def test_proxy_of_a_ball_void_is_filled_too():
    r = collision_proxy(part([box("block", 0.3, 0.3, 0.3), sphere("cavity", 0.1, op="subtract")]))
    assert r.derivation.method == "added-primitives"
    assert r.volume_error.value == approx(4.0 / 3.0 * math.pi * 0.001 / (0.027 - 4.0 / 3.0 * math.pi * 0.001))


def test_two_bores_in_one_plate_take_the_fill_path_for_the_whole_part():
    comps = [
        box("plate", 0.3, 0.2, 0.02),
        cyl("h1", 0.03, 0.02, at=(-0.07, 0.0, 0.0), op="subtract"),
        cyl("h2", 0.03, 0.02, at=(0.07, 0.0, 0.0), op="subtract"),
    ]
    r = collision_proxy(part(comps))
    assert r.derivation.method == "added-primitives" and [v.id for v in r.filled_voids] == ["h1", "h2"]


# --- through-bores are decomposed (B-01f) -------------------------------------------------------------------------------

PLATE_HOLE = [box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract")]
TUBE = [cyl("outer", 0.05, 0.5), cyl("bore", 0.04, 0.5, op="subtract")]


def _in_box(g, pt):
    """Point in an axis-aligned proxy box (all boxes of these parts have the identity orientation)."""
    return all(abs(pt[i] - g.center[i]) <= dims(g)[n] / 2 for i, n in enumerate(("size_x", "size_y", "size_z")))


def _any_geom(r, pt):
    return any(_in_box(g, pt) for g in r.geoms)


def test_plate_with_a_hole_keeps_the_hole_empty_and_the_error_is_small_and_negative():
    r = collision_proxy(part(PLATE_HOLE), tolerance=0.02)
    hole = math.pi * 0.0025 * 0.02
    assert r.derivation.method == "void-decomposition" and r.derivation.tolerance == 0.02
    assert r.filled_voids == ()
    (d,) = r.decomposed_voids
    assert (d.id, d.primitive, d.host) == ("hole", "cylinder", "plate") and d.volume == approx(hole)
    assert all(g.primitive == "box" and g.component == "plate" for g in r.geoms)
    assert r.recipe_volume.value == approx(0.0012 - hole)
    # Points on the hole's centre line (x = 0.05, y = 0) are outside the proxy, so are points inside its wall; material
    # outside the wall is inside.
    for z in (-0.009, 0.0, 0.009):
        assert not _any_geom(r, (0.05, 0.0, z))
        assert not _any_geom(r, (0.05 + 0.04, 0.0, z)) and not _any_geom(r, (0.05, 0.04, z))
        assert _any_geom(r, (0.05 + 0.06, 0.0, z)) and _any_geom(r, (0.05, 0.06, z))
    assert r.proxy_volume.value == pytest.approx(sum(g.volume for g in r.geoms), rel=1e-12)
    assert -0.02 <= r.volume_error.value < 0.0  # inside the recipe: never more than the recipe has


def test_plate_hand_checked_volume_with_four_strips():
    # tolerance 0.10 is met by n = 4: strip boundaries across y at -0.1, -0.05, -0.05 cos 45deg, 0, +0.05 cos 45deg, 0.05, 0.1
    # (c = 0.05 / sqrt 2 = 0.035355). Each box takes the narrower of the plate's width (0.3) and the wider of the bore's chord
    # at the strip's two ends. Outer slabs (|y| in 0.05..0.1) miss the bore: 0.3 x 0.05, twice. The strips |y| in c..0.05
    # have bore half-chord at most sqrt(r^2 - c^2) = c: boxes of width 0.3 - 2c. The strips |y| in 0..c reach the full
    # radius at y = 0: width 0.3 - 2 * 0.05.
    r = collision_proxy(part(PLATE_HOLE), tolerance=0.10)
    assert len(r.geoms) == 10  # 2 whole slabs + 4 slabs each split in two by the bore
    c = 0.05 * math.sqrt(0.5)
    proxy = 0.02 * (2 * 0.05 * 0.3 + 2 * (0.05 - c) * (0.3 - 2 * c) + 2 * c * (0.3 - 2 * 0.05))
    recipe = 0.0012 - math.pi * 0.0025 * 0.02
    assert proxy == pytest.approx(0.001017157287525381, rel=1e-12)
    assert r.proxy_volume.value == approx(proxy)
    assert r.volume_error.value == approx(proxy / recipe - 1.0)
    assert r.volume_error.value == pytest.approx(-0.0247028, abs=1e-6)  # -2.47 %, inside the stated 10 %


def test_tube_is_a_ring_of_boxes_with_the_bore_empty_and_a_small_signed_error():
    r = collision_proxy(part(TUBE))  # default tolerance
    assert r.derivation.method == "void-decomposition" and r.derivation.tolerance == DEFAULT_TOLERANCE and r.filled_voids == ()
    recipe = math.pi * (0.05**2 - 0.04**2) * 0.5  # pi (R^2 - r^2) h = 0.00045 pi
    assert r.recipe_volume.value == approx(0.00045 * math.pi)
    assert -DEFAULT_TOLERANCE <= r.volume_error.value < 0.0
    assert r.proxy_volume.value == pytest.approx(recipe * (1.0 + r.volume_error.value), rel=1e-12)
    assert len(r.geoms) > 8 and all(g.primitive == "box" and g.component == "outer" for g in r.geoms)
    # an object of radius 0.039 fits in the bore: the centre line and the ring of points at r = 0.0399 are free
    for z in (-0.24, 0.0, 0.24):
        assert not _any_geom(r, (0.0, 0.0, z))
        for k in range(24):
            t = 2 * math.pi * k / 24
            assert not _any_geom(r, (0.0399 * math.cos(t), 0.0399 * math.sin(t), z))
            assert _any_geom(r, (0.045 * math.cos(t), 0.045 * math.sin(t), z))  # and the wall's middle (r = 0.045) is solid
    # nothing sticks out of the outer cylinder: every piece corner is within R (up to rounding)
    for g in r.geoms:
        for sx in (-1, 1):
            for sy in (-1, 1):
                assert math.hypot(g.center[0] + sx * dims(g)["size_x"] / 2, g.center[1] + sy * dims(g)["size_y"] / 2) <= 0.05 * (1 + 1e-9)
                assert math.hypot(g.center[0] - sx * dims(g)["size_x"] / 2, g.center[1] - sy * dims(g)["size_y"] / 2) >= 0.0


def test_decomposed_pieces_do_not_overlap_each_other():
    r = collision_proxy(part(TUBE))
    boxes = [(tuple(g.center[i] - dims(g)[n] / 2 for i, n in enumerate(("size_x", "size_y", "size_z"))),
              tuple(g.center[i] + dims(g)[n] / 2 for i, n in enumerate(("size_x", "size_y", "size_z")))) for g in r.geoms]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (a0, a1), (b0, b1) = boxes[i], boxes[j]
            assert not all(min(a1[k], b1[k]) - max(a0[k], b0[k]) > 1e-12 for k in range(3))


def test_monte_carlo_coverage_of_the_decomposed_tube_and_plate():
    # Seeded Monte Carlo against the recipe, independent of the code under test (point-in-primitive by inverse rotation).
    # The decomposition is inside the recipe: no sampled point is in the proxy and not in the recipe, and the fraction of the
    # recipe missed agrees with the reported error within the sampling error.
    rng = random.Random(486)
    for comps, lo, hi, tol in (
        (TUBE, (-0.06, -0.06, -0.26), (0.06, 0.06, 0.26), 0.10),
        (PLATE_HOLE, (-0.16, -0.11, -0.011), (0.16, 0.11, 0.011), 0.02),
    ):
        r = collision_proxy(part(comps), tolerance=tol)
        outer, hole = comps[0], comps[1]
        n, in_recipe, missed = 80_000, 0, 0
        for _ in range(n):
            pt = tuple(rng.uniform(a, b) for a, b in zip(lo, hi))
            rec = _geom_contains_component(outer, pt) and not _geom_contains_component(hole, pt)
            prx = _any_geom(r, pt)
            assert rec or not prx  # the proxy never has material the recipe does not
            in_recipe += rec
            missed += rec and not prx
        fraction = missed / in_recipe
        sigma = math.sqrt(fraction * (1 - fraction) / in_recipe)
        assert fraction <= tol + 5 * sigma
        assert fraction == pytest.approx(-r.volume_error.value, abs=5 * sigma + 1e-4)
        # the recipe volume by sampling (the sample box volume times the hit rate) matches the reported one
        sample_volume = math.prod(b - a for a, b in zip(lo, hi))
        assert in_recipe / n * sample_volume == pytest.approx(r.recipe_volume.value, rel=0.03)


def test_tolerance_is_stated_and_a_wall_too_thin_for_it_is_rejected_with_the_reason():
    thin = [cyl("outer", 0.05, 0.5), cyl("bore", 0.0475, 0.5, op="subtract")]  # wall = 5 % of the radius
    with pytest.raises(ShapeError, match=r"too thin for the tolerance"):
        collision_proxy(part(thin))
    r = collision_proxy(part(thin), tolerance=0.3)  # a looser stated tolerance is accepted, and is the one reported
    assert r.derivation.tolerance == 0.3 and -0.3 <= r.volume_error.value < 0
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ShapeError, match="tolerance must be"):
            collision_proxy(part(TUBE), tolerance=bad)
    # a tighter tolerance gives more pieces and a smaller error
    loose, tight = collision_proxy(part(TUBE), tolerance=0.1), collision_proxy(part(TUBE), tolerance=0.06)
    assert len(tight.geoms) > len(loose.geoms) and abs(tight.volume_error.value) < abs(loose.volume_error.value)


def test_decomposition_follows_the_host_frame_axis_and_parameters():
    # A plate rotated 90 degrees about x (its z axis now along world y), bore along that axis, at an offset centre.
    comps = [
        box("plate", 0.3, 0.2, 0.02, at=(0.1, 0.2, 0.3), quat=ROT_X90),
        cyl("hole", 0.05, 0.02, at=(0.15, 0.2, 0.3), op="subtract", quat=ROT_X90),
    ]
    r = collision_proxy(part(comps), tolerance=0.02)
    assert r.derivation.method == "void-decomposition"
    centre_line = (0.15, 0.2, 0.3)
    assert not any(_geom_contains(g, centre_line) for g in r.geoms)
    assert any(_geom_contains(g, (0.15 + 0.06, 0.2, 0.3 + 0.001)) for g in r.geoms)
    assert not any(_geom_contains(g, (0.15, 0.2 + 0.009, 0.3 + 0.04)) for g in r.geoms)
    assert any(_geom_contains(g, (0.15, 0.2 + 0.009, 0.3 + 0.06)) for g in r.geoms)
    assert -0.02 <= r.volume_error.value < 0.0
    # a bore along the plate's x axis (a box face pair other than z)
    along_x = [box("blk", 0.2, 0.3, 0.3), cyl("b", 0.05, 0.2, op="subtract", quat={"x": 0.0, "y": S2, "z": 0.0, "w": S2})]
    rx = collision_proxy(part(along_x), tolerance=0.05)
    assert rx.derivation.method == "void-decomposition"
    assert not any(_geom_contains(g, (0.09, 0.0, 0.0)) for g in rx.geoms) and any(_geom_contains(g, (0.09, 0.0, 0.08)) for g in rx.geoms)
    # a parameter-driven tube: the proxy follows the length parameter and names it
    tube = {
        "id": "outer",
        "primitive": {"kind": "cylinder", "radius": ax(0.05), "length": ax(0.0, [("w", 1.0)])},
        "position": {"x": ax(), "y": ax(), "z": ax()},
    }
    bore = {**tube, "id": "bore", "operation": "subtract", "primitive": {"kind": "cylinder", "radius": ax(0.04), "length": ax(0.0, [("w", 1.0)])}}
    pp = part([tube, bore], [length_param()])
    long = collision_proxy(pp, {"w": Quantity.model_validate(q(0.4))})
    assert long.derivation.method == "void-decomposition" and long.recipe_volume.value == approx(math.pi * 0.0009 * 0.4)
    assert [u.name for u in long.derivation.parameters] == ["w"]


def test_decomposition_leaves_mass_to_mass_properties():
    p = part(TUBE)
    r = collision_proxy(p, tolerance=0.1)
    m = mass_properties(p, material())
    assert m.volume.value == r.recipe_volume.value  # the recipe volume, bit for bit; the proxy geoms are not summed for mass
    assert m.mass.value == approx(RHO * math.pi * 0.00045)
    assert r.proxy_volume.value != m.volume.value  # the proxy is an approximation and is not what mass uses


def test_a_part_with_a_bore_and_an_unrelated_added_component_keeps_the_latter_whole():
    comps = [*PLATE_HOLE, sphere("ball", 0.05, at=(0.5, 0.0, 0.0))]
    r = collision_proxy(part(comps), tolerance=0.02)
    ball = [g for g in r.geoms if g.component == "ball"]
    assert len(ball) == 1 and ball[0].id == "ball" and ball[0].primitive == "sphere"
    assert abs(r.volume_error.value) <= 0.02


# --- the proxy covers the recipe (independent point test) ---------------------------------------------------------------


def _inside(primitive, d, center, quat, point):
    """Independent point-in-primitive test: express the point in the primitive's frame with the inverse rotation."""
    x, y, z, w = quat
    v = [point[i] - center[i] for i in range(3)]
    # q^-1 v q: rotate by the conjugate
    cx_, cy_, cz_ = -x, -y, -z
    t = (
        2 * (cy_ * v[2] - cz_ * v[1]),
        2 * (cz_ * v[0] - cx_ * v[2]),
        2 * (cx_ * v[1] - cy_ * v[0]),
    )
    lx = v[0] + w * t[0] + (cy_ * t[2] - cz_ * t[1])
    ly = v[1] + w * t[1] + (cz_ * t[0] - cx_ * t[2])
    lz = v[2] + w * t[2] + (cx_ * t[1] - cy_ * t[0])
    if primitive == "box":
        return abs(lx) <= d["size_x"] / 2 and abs(ly) <= d["size_y"] / 2 and abs(lz) <= d["size_z"] / 2
    if primitive == "cylinder":
        return math.hypot(lx, ly) <= d["radius"] and abs(lz) <= d["length"] / 2
    return math.sqrt(lx * lx + ly * ly + lz * lz) <= d["radius"]


def _geom_contains(g, point):
    o = g.orientation
    return _inside(g.primitive, dims(g), g.center, (o.x, o.y, o.z, o.w), point)


def test_proxy_contains_every_sampled_point_of_the_recipe_and_its_volume_matches_integration():
    # A bracket: block with a rotated blind cylindrical pocket in it, plus a post on top and a ball on the side.
    comps = [
        box("base", 0.4, 0.2, 0.1, at=(0.0, 0.0, 0.05)),
        cyl("bore", 0.03, 0.1, at=(0.1, 0.0, 0.05), op="subtract", quat=ROT_X90),  # blind: not a through-bore, so filled
        cyl("post", 0.04, 0.3, at=(-0.1, 0.0, 0.25)),
        sphere("ball", 0.08, at=(0.3, 0.0, 0.05)),
    ]
    p = part(comps)
    r = collision_proxy(p)
    recipe = {c["id"]: c for c in comps}

    def in_recipe(point):
        solids = [
            _geom_contains_component(recipe[i], point) for i in ("base", "post", "ball")
        ]
        return any(solids) and not _geom_contains_component(recipe["bore"], point)

    rng = random.Random(20261111)
    lo, hi = (-0.25, -0.12, -0.04), (0.4, 0.12, 0.42)  # z reaches below the ball (z = -0.03)
    n, inside_recipe, inside_proxy = 120_000, 0, 0
    for _ in range(n):
        pt = tuple(rng.uniform(a, b) for a, b in zip(lo, hi))
        in_p = any(_geom_contains(g, pt) for g in r.geoms)
        in_r = in_recipe(pt)
        inside_proxy += in_p
        inside_recipe += in_r
        assert in_p or not in_r  # the proxy never has less than the recipe
    box_volume = math.prod(b - a for a, b in zip(lo, hi))
    # Monte Carlo (seeded): the estimate of the reported proxy volume is within 2 % of it (the hit fraction is about 0.05, so sigma ~ 0.64 % of the volume at n = 120k).
    assert inside_proxy / n * box_volume == pytest.approx(r.proxy_volume.value, rel=0.02)
    assert inside_recipe / n * box_volume == pytest.approx(r.recipe_volume.value, rel=0.02)
    # By hand: base 0.008 + post pi 0.0016 0.3 + ball 4/3 pi 0.000512; bore pi 0.0009 0.1.
    proxy_hand = 0.008 + math.pi * 0.0016 * 0.3 + 4.0 / 3.0 * math.pi * 0.000512
    bore_hand = math.pi * 0.0009 * 0.1
    assert r.proxy_volume.value == approx(proxy_hand)
    assert r.recipe_volume.value == approx(proxy_hand - bore_hand)
    assert r.volume_error.value == approx(bore_hand / (proxy_hand - bore_hand))


def _geom_contains_component(comp, point):
    prim = comp["primitive"]
    d = {k: v["offset"] for k, v in prim.items() if k != "kind"}
    c = tuple(comp["position"][a]["offset"] for a in "xyz")
    o = comp.get("orientation", {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
    return _inside(prim["kind"], d, c, (o["x"], o["y"], o["z"], o["w"]), point)


# --- parameters, rejection, honesty -------------------------------------------------------------------------------------


def length_param(name="w", default=0.2, lo=0.1, hi=0.5, **kw):
    return {"name": name, "unit": "m", "default": q(default, **kw), "min": q(lo), "max": q(hi)}


def param_part(**kw):
    comp = {
        "id": "b",
        "primitive": {"kind": "box", "size_x": ax(0.0, [("w", 1.0)]), "size_y": ax(0.1), "size_z": ax(0.3)},
        "position": {"x": ax(0.0, [("w", 0.5)]), "y": ax(), "z": ax()},
    }
    return part([comp], [length_param(**kw)])


def test_proxy_recipe_volume_is_the_mass_volume_bit_for_bit_and_survives_cancellation():
    # 1 m^3 added, the same 1 m^3 subtracted, then a ball of radius 1e-6 m clear of the box: material is left (4.19e-18 m^3).
    # Summing adds and voids separately rounds that to zero; the signed sum in recipe order, as mass does, keeps it.
    tiny = [
        box("a", 1.0, 1.0, 1.0),
        box("v", 1.0, 1.0, 1.0, op="subtract"),
        sphere("s", 1e-6, at=(5.0, 0.0, 0.0)),
    ]
    p = part(tiny)
    r = collision_proxy(p)
    assert r.recipe_volume.value == mass_properties(p, material()).volume.value
    assert r.recipe_volume.value == approx(4.0 / 3.0 * math.pi * 1e-18)
    assert r.proxy_volume.value == approx(1.0 + 4.0 / 3.0 * math.pi * 1e-18)
    # and for ordinary recipes with several adds and voids, exactly equal (no relative slack)
    rng = random.Random(7)
    for _ in range(50):
        comps = [box(f"a{i}", rng.uniform(0.1, 0.4), rng.uniform(0.1, 0.4), rng.uniform(0.1, 0.4), at=(i * 1.0, 0.0, 0.0)) for i in range(4)]
        comps += [sphere(f"v{i}", rng.uniform(0.01, 0.05), at=(i * 1.0, 0.0, 0.0), op="subtract") for i in range(4)]
        p = part(comps)
        assert collision_proxy(p).recipe_volume.value == mass_properties(p, material()).volume.value


def test_proxy_follows_the_parameter_default_and_an_override_and_names_the_values_used():
    p = param_part()
    default = collision_proxy(p)
    assert dims(default.geoms[0])["size_x"] == approx(0.2) and default.geoms[0].center[0] == approx(0.1)
    wide = collision_proxy(p, {"w": Quantity.model_validate(q(0.4, badge="estimate", source={"ref": "eyeballed"}))})
    assert dims(wide.geoms[0])["size_x"] == approx(0.4) and wide.geoms[0].center[0] == approx(0.2)
    assert wide.proxy_volume.value == approx(0.4 * 0.1 * 0.3)
    (use,) = wide.derivation.parameters
    assert use.name == "w" and use.value.value == 0.4 and use.value.badge is Badge.ESTIMATE
    assert wide.derivation.input_badges == (Badge.DECLARED, Badge.ESTIMATE)


def test_proxy_rejects_what_mass_rejects():
    p = param_part()
    with pytest.raises(ShapeError, match="outside the allowed range"):
        collision_proxy(p, {"w": Quantity.model_validate(q(0.6))})
    with pytest.raises(ShapeError, match="unknown parameters"):
        collision_proxy(p, {"nope": Quantity.model_validate(q(0.2))})
    with pytest.raises(ShapeError, match="need unit"):
        collision_proxy(p, {"w": Quantity.model_validate(q(0.2, "kg"))})
    with pytest.raises(ShapeError, match="no shape recipe"):
        collision_proxy(PartDef.model_validate({"id": "bare", "name": "Bare"}))
    with pytest.raises(ShapeError, match="overlap"):
        collision_proxy(part([box("a", 0.2, 0.2, 0.2), box("b", 0.2, 0.2, 0.2, at=(0.1, 0.0, 0.0))]))
    with pytest.raises(ShapeError, match="not inside"):
        collision_proxy(part([box("a", 0.2, 0.2, 0.2), box("v", 0.1, 0.1, 0.1, at=(0.3, 0.0, 0.0), op="subtract")]))
    with pytest.raises(ShapeError, match="remove all the material"):
        collision_proxy(part([box("a", 0.2, 0.2, 0.2), box("v", 0.2, 0.2, 0.2, op="subtract")]))


def test_proxy_is_sim_with_the_recipe_and_its_badge_behind_it():
    cited = {"ref": "Drawing 42", "locator": "sheet 1"}
    r = collision_proxy(part([box("b", 0.2, 0.1, 0.3)], badge="cite", source=cited))
    for v in (r, r.proxy_volume, r.recipe_volume, r.volume_error):
        assert v.badge is Badge.SIM
        assert "collision_proxy" in v.source.ref and "test-part" in v.source.locator
    assert r.derivation.shape.badge is Badge.CITE and r.derivation.shape.source.ref == "Drawing 42"
    assert r.derivation.input_badges == (Badge.CITE,)
    assert any("no mesh" in a for a in r.derivation.assumptions)
    assert any("filled" in a for a in r.derivation.assumptions)


def _dump(r):
    return r.model_dump(mode="json")


def _forger(r):
    CollisionProxy.model_validate(_dump(r))

    def broken(edit, match: str | None):
        d = _dump(r)
        edit(d)
        with pytest.raises(ValueError, match=match):
            CollisionProxy.model_validate(d)

    return broken


def test_filled_proxy_cannot_be_forged():
    r = collision_proxy(part([box("plate", 0.3, 0.2, 0.02), cyl("pocket", 0.05, 0.01, at=(0.0, 0.0, 0.005), op="subtract")]))
    assert r.derivation.method == "added-primitives"
    broken = _forger(r)
    broken(lambda d: d.update(badge="cite"), None)
    broken(lambda d: d["volume_error"].update(value=0.0), "volume_error must be")
    broken(lambda d: d["proxy_volume"].update(value=0.5), "proxy_volume must be the sum")
    broken(lambda d: d["filled_voids"].clear(), "filled void")
    broken(lambda d: d["geoms"][0].update(volume=0.01), "does not match")
    broken(lambda d: d["geoms"][0].update(primitive="sphere"), "has dimensions")
    broken(lambda d: d["derivation"].update(input_badges=["cite"]), "input_badges must be")
    broken(lambda d: d["geoms"].append(d["geoms"][0]), "duplicate geom id")
    broken(lambda d: d["geoms"].clear(), None)
    broken(lambda d: d["volume_error"].update(unit="m^3"), "volume_error must be in")
    broken(lambda d: d["derivation"].update(tolerance=0.1), "tolerance is given exactly")
    broken(lambda d: d["derivation"].update(method="void-decomposition"), "tolerance is given exactly")
    broken(lambda d: d["geoms"][0].update(id="plate_p0"), "id must equal component")
    broken(lambda d: d.update(decomposed_voids=[{"id": "x", "primitive": "cylinder", "host": "plate", "volume": 1e-5}]), "no decomposed voids")


def test_decomposed_proxy_cannot_be_forged():
    r = collision_proxy(part(PLATE_HOLE), tolerance=0.1)
    assert r.derivation.method == "void-decomposition"
    broken = _forger(r)
    tol = r.derivation.tolerance
    assert tol == 0.1
    broken(lambda d: d["derivation"].update(method="added-primitives", tolerance=None), "no decomposed voids")
    broken(lambda d: d["derivation"].update(tolerance=None), "tolerance is given exactly")
    broken(lambda d: d["derivation"].update(tolerance=0.001), "exceeds the stated tolerance")
    broken(lambda d: d["decomposed_voids"].clear(), "lists the voids")
    broken(lambda d: d.update(filled_voids=[{"id": "hole", "primitive": "cylinder", "volume": 1e-5}]), "no filled voids")
    broken(lambda d: d["decomposed_voids"][0].update(host="nope"), "host must have at least one piece")
    broken(lambda d: d["decomposed_voids"].append(d["decomposed_voids"][0]), "duplicate decomposed void id")
    broken(lambda d: d["volume_error"].update(value=-tol * 2), "volume_error must be")
    broken(lambda d: (d["volume_error"].update(value=0.5), d["proxy_volume"].update(value=d["recipe_volume"]["value"] * 1.5)), "proxy_volume must be the sum")


def test_proxy_has_no_mesh_kind():
    r = collision_proxy(part([box("b", 0.2, 0.1, 0.3)]))
    for kind in ("mesh", "trimesh"):  # a convex hull is a value L-02b may add; only meshes are excluded here
        d = _dump(r)
        d["geoms"][0]["primitive"] = kind
        with pytest.raises(ValueError):
            CollisionProxy.model_validate(d)
    assert {g.primitive for g in r.geoms} <= {"box", "cylinder", "sphere"}


def test_proxy_round_trips_through_json_is_deterministic_and_hashable():
    p = part([box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract"), sphere("s", 0.05, at=(0.5, 0.0, 0.0))])
    a, b = collision_proxy(p), collision_proxy(p)
    assert a == b and hash(a) == hash(b)
    assert CollisionProxy.model_validate_json(a.model_dump_json()) == a
