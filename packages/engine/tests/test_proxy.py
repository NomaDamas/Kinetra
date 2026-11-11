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
from kinetra_engine.parts._decompose import MIN_STRIP_FRACTION
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


def test_two_bores_in_one_plate_are_filled_with_the_reason_and_rejected_on_request():
    comps = [
        box("plate", 0.3, 0.2, 0.02),
        cyl("h1", 0.03, 0.02, at=(-0.07, 0.0, 0.0), op="subtract"),
        cyl("h2", 0.03, 0.02, at=(0.07, 0.0, 0.0), op="subtract"),
    ]
    r = collision_proxy(part(comps))
    assert r.derivation.method == "added-primitives" and [v.id for v in r.filled_voids] == ["h1", "h2"]
    assert r.derivation.tolerance is None and r.volume_error.value > 0.1
    for void in ("h1", "h2"):
        assert any(f"Void '{void}' was filled" in a and "2 voids" in a for a in r.derivation.assumptions)
    with pytest.raises(ShapeError, match=r"cannot decompose.*h1.*h2.*on_unsupported='reject'"):
        collision_proxy(part(comps), on_unsupported="reject")
    with pytest.raises(ShapeError, match="on_unsupported must be"):
        collision_proxy(part(comps), on_unsupported="ignore")


def test_unsupported_voids_name_their_reasons():
    skew = [box("blk", 0.3, 0.3, 0.3), cyl("h", 0.03, 0.3, op="subtract", quat={"x": 0.0, "y": math.sin(0.3), "z": 0.0, "w": math.cos(0.3)})]
    tilted = [box("blk", 0.2, 0.2, 1.0), cyl("h", 1e-4, 1.0, op="subtract", quat={"x": 0.0, "y": math.sin(5e-7), "z": 0.0, "w": math.cos(5e-7)})]
    short = [box("blk", 0.3, 0.3, 0.3), cyl("h", 0.03, 0.2, at=(0.0, 0.0, 0.05), op="subtract")]
    for comps, why in ((skew, "not parallel"), (tilted, "not parallel"), (short, "blind pocket")):
        r = collision_proxy(part(comps))
        assert r.derivation.method == "added-primitives" and len(r.filled_voids) == 1
        assert any(why in a for a in r.derivation.assumptions), (why, r.derivation.assumptions)
        with pytest.raises(ShapeError, match=why):
            collision_proxy(part(comps), on_unsupported="reject")


def test_an_eccentric_tube_is_decomposed_around_the_bore_and_stays_inside_the_recipe():
    # Tube R = 0.05, bore r = 0.03 whose axis is 0.004 off the tube's, along x and along a diagonal; inner approximation
    # about the BORE's axis (outer radius R - e = 0.046), so the thick side of the wall is missed, and the tolerance sees it.
    rng = random.Random(4860)
    for off in ((0.004, 0.0), (-0.0024, 0.0032)):
        comps = [cyl("outer", 0.05, 0.4), cyl("bore", 0.03, 0.4, at=(off[0], off[1], 0.0), op="subtract")]
        r = collision_proxy(part(comps), tolerance=0.3)
        d = r.decomposed_voids[0]
        assert d.layout == "ring" and d.ring.wall_closed and -0.3 <= d.error < 0.0
        net = math.pi * (0.05**2 - 0.03**2) * 0.4
        assert d.host_volume - d.volume == pytest.approx(net, rel=1e-12)
        outer, hole = comps[0], comps[1]
        n, outside, in_recipe, missed = 60_000, 0, 0, 0
        for _ in range(n):
            pt = (rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(-0.19, 0.19))
            rec = _geom_contains_component(outer, pt) and not _geom_contains_component(hole, pt)
            prx = _any_geom(r, pt)
            outside += prx and not rec  # zero is the claim
            in_recipe += rec
            missed += rec and not prx
        assert outside == 0
        fraction = missed / in_recipe
        assert fraction == pytest.approx(-d.error, abs=5 * math.sqrt(fraction * (1 - fraction) / in_recipe) + 1e-3)
        assert not _any_geom(r, (off[0], off[1], 0.0))  # the bore's own axis is empty
        # an object of radius 0.0291 around the bore's axis fits
        for k in range(24):
            t = 2 * math.pi * k / 24
            assert not _any_geom(r, (off[0] + 0.0291 * math.cos(t), off[1] + 0.0291 * math.sin(t), 0.0))
    # a bore nearly touching the tube's wall cannot be a ring about its own axis within the tolerance: rejected with the reason
    with pytest.raises(ShapeError, match="cannot be made into a closed ring"):
        collision_proxy(part([cyl("outer", 0.06, 0.4), cyl("bore", 0.02, 0.4, at=(0.02, 0.0, 0.0), op="subtract")]))
    with pytest.raises(ShapeError, match="too close to the tube's outer wall"):
        collision_proxy(part([cyl("outer", 0.06, 0.4), cyl("bore", 0.03, 0.4, at=(0.03, 0.0, 0.0), op="subtract")]))


def test_a_supported_bore_is_decomposed_even_when_another_void_is_filled():
    # plate with a through-bore + a separate block with a ball cavity (not decomposable): per void, not per part
    comps = [*PLATE_HOLE, box("blk", 0.2, 0.2, 0.2, at=(1.0, 0.0, 0.0)), sphere("cavity", 0.05, at=(1.0, 0.0, 0.0), op="subtract")]
    r = collision_proxy(part(comps), tolerance=0.1)
    assert r.derivation.method == "void-decomposition"
    assert [v.id for v in r.decomposed_voids] == ["hole"] and [v.id for v in r.filled_voids] == ["cavity"]
    assert any("Void 'cavity' was filled" in a and "sphere" in a for a in r.derivation.assumptions)
    assert [g.id for g in r.geoms if g.component == "blk"] == ["blk"]  # the block with the cavity is one box
    assert not _any_geom(r, (0.05, 0.0, 0.0)) and _any_geom(r, (1.0, 0.0, 0.0))  # bore empty, cavity filled
    # the part's error is the filled cavity plus the decomposed host's (negative) error, to the volume
    cavity, hole = 4.0 / 3.0 * math.pi * 0.05**3, math.pi * 0.0025 * 0.02
    host_net = 0.0012 - hole
    want = cavity + r.decomposed_voids[0].error * host_net
    assert r.proxy_volume.value - r.recipe_volume.value == pytest.approx(want, rel=1e-9)
    with pytest.raises(ShapeError, match="cavity"):
        collision_proxy(part(comps), on_unsupported="reject")


# --- through-bores are decomposed (B-01f) -------------------------------------------------------------------------------

PLATE_HOLE = [box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract")]
TUBE = [cyl("outer", 0.05, 0.5), cyl("bore", 0.04, 0.5, op="subtract")]


def _any_geom(r, pt):
    return any(_geom_contains(g, pt) for g in r.geoms)


def test_plate_with_a_hole_keeps_the_hole_empty_and_the_error_is_small_and_negative():
    r = collision_proxy(part(PLATE_HOLE), tolerance=0.02)
    hole = math.pi * 0.0025 * 0.02
    assert r.derivation.method == "void-decomposition" and r.derivation.tolerance.value == 0.02
    assert r.derivation.tolerance.badge is Badge.DECLARED and r.filled_voids == ()
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


def test_tube_is_a_closed_ring_of_staves_inside_the_wall_with_reported_deviations():
    r = collision_proxy(part(TUBE))  # default tolerance
    d = r.decomposed_voids[0]
    assert r.derivation.method == "void-decomposition" and r.filled_voids == ()
    assert r.derivation.tolerance.value == DEFAULT_TOLERANCE and r.derivation.tolerance.badge is Badge.DEFAULT
    assert "chosen value" in r.derivation.tolerance.source.ref
    assert d.layout == "ring" and d.ring.wall_closed and d.ring.staves == len(r.geoms) == 16
    assert -DEFAULT_TOLERANCE <= d.error < 0.0
    recipe = math.pi * (0.05**2 - 0.04**2) * 0.5  # pi (R^2 - r^2) h = 0.00045 pi
    assert r.recipe_volume.value == approx(0.00045 * math.pi)
    assert d.union_volume == pytest.approx(recipe * (1.0 + d.error), rel=1e-12)
    assert r.proxy_volume.value == approx(d.union_volume)  # the union, not the sum of the (overlapping) boxes
    assert d.union_volume < sum(g.volume for g in r.geoms)  # the boxes overlap each other: allowed in a collision
    assert all(g.primitive == "box" and g.component == "outer" for g in r.geoms)
    # the bore wall of the proxy is the regular 16-gon of apothem r: at most r (1 / cos(pi/16) - 1) = 0.78 mm into the wall
    assert d.ring.inner_deviation == pytest.approx(0.04 * (1.0 / math.cos(math.pi / 16) - 1.0), rel=1e-12)
    # independent ray scan (no reuse of the engine's formulas): along each of 720 rays at z = 0 the proxy is entered once and
    # left once (no radial slit), the entry is within the reported inner deviation of r and the exit within the outer one of R
    rs = [0.05 * k / 1000 for k in range(1, 1001)]
    entry_dev, exit_dev = 0.0, 0.0
    for m in range(720):
        phi = 2 * math.pi * (m + 0.37) / 720
        inside = [_any_geom(r, (t * math.cos(phi), t * math.sin(phi), 0.0)) for t in rs]
        assert sum(1 for a, b in zip(inside, inside[1:]) if a != b) == 2, f"ray {m} crosses the wall more than once"
        entry_dev = max(entry_dev, next(t for t, f in zip(rs, inside) if f) - 0.04)
        exit_dev = max(exit_dev, 0.05 - max(t for t, f in zip(rs, inside) if f))
    assert entry_dev <= d.ring.inner_deviation + 5e-5 and exit_dev <= d.ring.outer_deviation + 5e-5  # 5e-5 = ray step
    # the deepest notch, found by bisection on the exit radius of 4000 rays across one notch (the ring repeats every 2 pi / 16)
    def exit_radius(phi):
        lo, hi = 0.045, 0.05  # inside at the wall's middle (checked above), outside at R + epsilon
        if _any_geom(r, (hi * math.cos(phi), hi * math.sin(phi), 0.0)):
            return hi
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _any_geom(r, (mid * math.cos(phi), mid * math.sin(phi), 0.0)) else (lo, mid)
        return lo

    deepest = max(0.05 - exit_radius(2 * math.pi / 16 * m / 4000) for m in range(4001))
    assert deepest == pytest.approx(d.ring.outer_deviation, abs=2e-6)  # 1.9 mm of a 50 mm radius: not hidden, not inflated
    # an object of radius 0.039 fits in the bore; the wall's middle (r = 0.045) is solid
    for z in (-0.24, 0.0, 0.24):
        assert not _any_geom(r, (0.0, 0.0, z))
        for k in range(24):
            t = 2 * math.pi * k / 24
            assert not _any_geom(r, (0.0391 * math.cos(t), 0.0391 * math.sin(t), z))
            assert _any_geom(r, (0.045 * math.cos(t), 0.045 * math.sin(t), z))


def test_ring_staves_do_not_leave_the_tube_and_overlap_only_their_neighbours():
    r = collision_proxy(part(TUBE))
    for g in r.geoms:
        o = g.orientation
        for sx in (-1, 1):
            for sy in (-1, 1):
                local = (sx * dims(g)["size_x"] / 2, sy * dims(g)["size_y"] / 2, 0.0)
                # corner in the part frame: rotate by the stave's orientation (about z) and add the centre
                ang = 2 * math.atan2(o.z, o.w)
                cx_ = g.center[0] + local[0] * math.cos(ang) - local[1] * math.sin(ang)
                cy_ = g.center[1] + local[0] * math.sin(ang) + local[1] * math.cos(ang)
                rho = math.hypot(cx_, cy_)
                assert 0.04 * (1 - 1e-9) <= rho <= 0.05 * (1 + 1e-9)


def test_plate_strips_are_disjoint_and_never_thinner_than_the_stated_minimum():
    for tol in (0.1, 0.02):
        r = collision_proxy(part(PLATE_HOLE), tolerance=tol)
        boxes = [
            (tuple(g.center[i] - dims(g)[n] / 2 for i, n in enumerate(("size_x", "size_y", "size_z"))),
             tuple(g.center[i] + dims(g)[n] / 2 for i, n in enumerate(("size_x", "size_y", "size_z"))))
            for g in r.geoms
        ]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (a0, a1), (b0, b1) = boxes[i], boxes[j]
                assert not all(min(a1[k], b1[k]) - max(a0[k], b0[k]) > 1e-12 for k in range(3))
        assert min(dims(g)["size_y"] for g in r.geoms) >= MIN_STRIP_FRACTION * 0.05 * (1 - 1e-9)


def test_strip_boundaries_closer_than_the_minimum_are_merged_and_the_error_still_holds():
    # A hole 0.2 mm off a plate edge: the bore's own grid would put a boundary a hair from the edge.
    comps = [box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.0, 0.0499, 0.0), op="subtract")]
    for tol in (0.05, 0.1):
        r = collision_proxy(part(comps), tolerance=tol)
        thinnest = min(min(dims(g)["size_x"], dims(g)["size_y"]) for g in r.geoms if g.dimensions)
        assert min(dims(g)["size_y"] for g in r.geoms) >= MIN_STRIP_FRACTION * 0.05 * (1 - 1e-9)
        assert -tol <= r.decomposed_voids[0].error < 0.0 and thinnest > 0.0


def test_a_big_base_cannot_hide_a_badly_decomposed_tube():
    # Base 0.5 x 0.5 x 0.1 (V = 0.025) plus a tube whose wall is only 0.00045 pi = 0.0014 m^3. Part-level error is dominated by the
    # base, so a part-wide tolerance would accept a ring with half the wall missing. Each host is held to the tolerance by itself.
    comps = [box("base", 0.5, 0.5, 0.1, at=(0.0, 0.0, -0.3)), cyl("outer", 0.05, 0.5), cyl("bore", 0.04, 0.5, op="subtract")]
    for tol in (0.1, 0.02):
        r = collision_proxy(part(comps), tolerance=tol)
        (d,) = r.decomposed_voids
        assert d.host == "outer" and -tol <= d.error < 0.0
        assert abs(r.volume_error.value) < abs(d.error) / 5  # the part-level number is far smaller than the host's
        ring = [g for g in r.geoms if g.component == "outer"]
        assert d.ring.staves == len(ring) >= 16 and d.ring.wall_closed
        assert [g.id for g in r.geoms if g.component == "base"] == ["base"]
    # and the bound is the host's, not the part's: a ring of 6 boxes at 100 % would have passed a part-level 5 %
    assert collision_proxy(part(comps), tolerance=0.02).decomposed_voids[0].ring.staves > collision_proxy(part(comps), tolerance=0.1).decomposed_voids[0].ring.staves


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
        n, in_recipe, missed = 60_000, 0, 0
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
        assert fraction == pytest.approx(-r.decomposed_voids[0].error, abs=5 * sigma + 1e-4)
        sample_volume = math.prod(b - a for a, b in zip(lo, hi))
        assert in_recipe / n * sample_volume == pytest.approx(r.recipe_volume.value, rel=0.03)


def test_tolerance_is_stated_badged_and_what_cannot_meet_it_is_rejected_with_the_reason():
    assert collision_proxy(part(TUBE)).derivation.tolerance.badge is Badge.DEFAULT
    declared = collision_proxy(part(TUBE), tolerance=0.2).derivation.tolerance
    assert (declared.value, declared.badge, declared.unit.value) == (0.2, Badge.DECLARED, "1")
    cited = Quantity.model_validate({"value": 0.2, "unit": "1", "badge": "cite", "source": {"ref": "Drawing 42", "locator": "note 3"}})
    assert collision_proxy(part(TUBE), tolerance=cited).derivation.tolerance.badge is Badge.CITE
    # a bore of a fifth of the radius cannot be a ring of boxes inside 10 % of the wall (nor of 30 %): rejected, with why
    small = [cyl("outer", 0.05, 0.5), cyl("bore", 0.01, 0.5, op="subtract")]
    with pytest.raises(ShapeError, match=r"void 'bore' in 'outer' cannot be made into a closed ring.*0\.1.*raise the tolerance"):
        collision_proxy(part(small))
    assert collision_proxy(part(small), tolerance=1.0).decomposed_voids[0].error > -1.0  # a looser stated tolerance is accepted
    # a plate whose strips cannot reach 0.5 % within the strip limit
    with pytest.raises(ShapeError, match=r"cannot be cut into boxes within 0\.005"):
        collision_proxy(part(PLATE_HOLE), tolerance=0.005)
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ShapeError, match="tolerance must be"):
            collision_proxy(part(TUBE), tolerance=bad)
    with pytest.raises(ShapeError, match="unit '1'"):
        collision_proxy(part(TUBE), tolerance=Quantity.model_validate(q(0.1, "m")))
    # a tighter tolerance gives more boxes and a smaller error
    loose, tight = collision_proxy(part(TUBE), tolerance=0.1), collision_proxy(part(TUBE), tolerance=0.05)
    assert len(tight.geoms) > len(loose.geoms) and abs(tight.volume_error.value) < abs(loose.volume_error.value)
    # a thin wall (5 % of the radius) is fine for a ring; the report says how far the bore wall moved
    thin = collision_proxy(part([cyl("outer", 0.05, 0.5), cyl("bore", 0.0475, 0.5, op="subtract")]))
    assert thin.decomposed_voids[0].ring.wall_closed and thin.decomposed_voids[0].ring.inner_deviation < 0.0025 * 0.5


def test_piece_ids_avoid_component_ids_and_stay_unique():
    # a separate element named like the first piece of the plate
    comps = [*PLATE_HOLE, box("plate_p0", 0.1, 0.1, 0.1, at=(1.0, 0.0, 0.0))]
    r = collision_proxy(part(comps), tolerance=0.1)
    ids = [g.id for g in r.geoms]
    assert len(set(ids)) == len(ids) and ids.count("plate_p0") == 1
    assert [g.component for g in r.geoms if g.id == "plate_p0"] == ["plate_p0"]
    assert sorted(g.id for g in r.geoms if g.component == "plate")[0] == "plate_p1"  # p0 is taken, so the pieces start at p1
    # two hosts whose names share the first 62 characters: ids are cut to 64, so the pieces need a different suffix
    stem = "h" * 62
    two = [
        box(stem + "aa", 0.3, 0.2, 0.02),
        cyl("hole_a", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract"),
        box(stem + "bb", 0.3, 0.2, 0.02, at=(1.0, 0.0, 0.0)),
        cyl("hole_b", 0.05, 0.02, at=(1.05, 0.0, 0.0), op="subtract"),
    ]
    r2 = collision_proxy(part(two), tolerance=0.1)
    ids2 = [g.id for g in r2.geoms]
    assert len(set(ids2)) == len(ids2) and all(len(i) <= 64 for i in ids2)
    assert {g.component for g in r2.geoms} == {stem + "aa", stem + "bb"}
    assert collision_proxy(part(two), tolerance=0.1) == r2  # deterministic


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
    assert -0.02 <= r.decomposed_voids[0].error < 0.0
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
    assert abs(r.decomposed_voids[0].error) <= 0.02


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
    assert not any("filled" in a for a in r.derivation.assumptions)  # nothing to fill in a solid block
    filled = collision_proxy(part([box("b", 0.2, 0.1, 0.3), sphere("v", 0.02, op="subtract")]))
    assert any("filled" in a for a in filled.derivation.assumptions)


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
    broken(lambda d: d["proxy_volume"].update(value=0.5), "volume_error must be")
    broken(lambda d: (d["proxy_volume"].update(value=0.5), d["volume_error"].update(value=(0.5 - d["recipe_volume"]["value"]) / d["recipe_volume"]["value"])), "proxy_volume must be the sum")
    broken(lambda d: d["filled_voids"].clear(), "filled void")
    broken(lambda d: d["geoms"][0].update(volume=0.01), "does not match")
    broken(lambda d: d["geoms"][0].update(primitive="sphere"), "has dimensions")
    broken(lambda d: d["derivation"].update(input_badges=["cite"]), "input_badges must be")
    broken(lambda d: d["geoms"].append(d["geoms"][0]), "duplicate geom id")
    broken(lambda d: d["geoms"].clear(), None)
    broken(lambda d: d["volume_error"].update(unit="m^3"), "volume_error must be in")
    tol = {"value": 0.1, "unit": "1", "badge": "default", "source": {"ref": "x"}}
    broken(lambda d: d["derivation"].update(tolerance=tol), "tolerance is given exactly")
    broken(lambda d: d["derivation"].update(method="void-decomposition"), "tolerance is given exactly")
    broken(lambda d: d["geoms"][0].update(id="plate_p0"), "copied unchanged")
    broken(lambda d: d.update(decomposed_voids=[{"id": "x", "primitive": "cylinder", "host": "plate", "volume": 1e-5, "host_volume": 0.0012, "union_volume": 0.0011, "error": -0.1, "layout": "strips"}]), None)


def test_decomposed_proxy_cannot_be_forged():
    r = collision_proxy(part(PLATE_HOLE), tolerance=0.1)
    assert r.derivation.method == "void-decomposition"
    broken = _forger(r)
    broken(lambda d: d["derivation"].update(method="added-primitives", tolerance=None), "no decomposed voids")
    broken(lambda d: d["derivation"].update(tolerance=None), "tolerance is given exactly")
    broken(lambda d: d["derivation"]["tolerance"].update(value=0.001), "exceeds the stated tolerance")
    broken(lambda d: d["derivation"]["tolerance"].update(badge="sim"), "badge 'sim'")
    broken(lambda d: d["derivation"]["tolerance"].update(unit="m"), "unit '1'")
    broken(lambda d: d["derivation"]["tolerance"].update(value=2.0), None)
    broken(lambda d: d["decomposed_voids"].clear(), None)
    broken(lambda d: d.update(filled_voids=[{"id": "hole", "primitive": "cylinder", "volume": 1e-5}]), "duplicate void id")
    broken(lambda d: d["decomposed_voids"][0].update(host="nope"), "at least one piece|copied unchanged")
    broken(lambda d: d["decomposed_voids"][0].update(error=-0.5), "error must be")
    broken(lambda d: d["decomposed_voids"][0].update(layout="ring"), "ring layout carries")
    broken(lambda d: d["decomposed_voids"].append(d["decomposed_voids"][0]), "duplicate void id")
    broken(lambda d: d["volume_error"].update(value=-0.2), "volume_error must be")
    broken(lambda d: d["proxy_volume"].update(value=d["proxy_volume"]["value"] * 1.2), "volume_error must be")
    broken(lambda d: (d["proxy_volume"].update(value=d["recipe_volume"]["value"]), d["volume_error"].update(value=0.0)), "must be the sum")
    # the strips of a host are disjoint, so their volumes add up to the union
    broken(lambda d: d["geoms"].pop(), "union_volume must be the sum")
    ring = collision_proxy(part(TUBE))
    broken_ring = _forger(ring)
    broken_ring(lambda d: d["geoms"].pop(), "ring.staves is 16 but host 'outer' has 15 boxes")
    broken_ring(lambda d: d["geoms"].__setitem__(3, {**d["geoms"][3], "orientation": d["geoms"][2]["orientation"], "id": "outer_p3", "center": d["geoms"][2]["center"]}), "one box at every multiple")
    broken_ring(lambda d: d["geoms"][5].update(center=[0.0, 0.0, 0.0]), "sit on one circle")
    broken_ring(lambda d: d["decomposed_voids"][0]["ring"].update(staves=15), "ring.staves is 15 but host 'outer' has 16 boxes")
    broken_ring(lambda d: d["decomposed_voids"][0]["ring"].update(wall_closed=False), "radial slit")
    broken_ring(lambda d: d["decomposed_voids"][0].update(ring=None), "ring layout carries")
    broken_ring(lambda d: d["decomposed_voids"][0].update(union_volume=d["decomposed_voids"][0]["union_volume"] * 1.5, error=0.0), None)


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
