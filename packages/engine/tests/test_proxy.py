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


def test_proxy_of_a_plate_with_a_hole_fills_the_hole_and_reports_the_volume_error():
    # Plate 0.3 x 0.2 x 0.02 (V = 0.0012 m^3) with a 0.05 m radius through-hole (V = pi 0.0025 0.02 = 5e-5 pi m^3).
    r = collision_proxy(part([box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract")]))
    hole = math.pi * 0.0025 * 0.02  # pi r^2 h
    assert [g.id for g in r.geoms] == ["plate"]  # the hole is not a proxy geom
    assert r.proxy_volume.value == approx(0.0012)  # the plate, solid
    assert r.recipe_volume.value == approx(0.0012 - hole)
    assert r.volume_error.value == approx(hole / (0.0012 - hole))  # about +15.1 %: 1.5708e-4 / (1.2e-3 - 1.5708e-4)
    (f,) = r.filled_voids
    assert (f.id, f.primitive) == ("hole", "cylinder") and f.volume == approx(hole)
    # The recipe volume is the volume B-01a reports for the same part.
    p = part([box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract")])
    assert mass_properties(p, material()).volume.value == approx(r.recipe_volume.value)


def test_proxy_of_a_tube_is_its_outer_cylinder():
    # Tube R = 0.05, r = 0.04, length 0.5: recipe pi (R^2 - r^2) h = 0.00045 pi; proxy pi R^2 h = 0.00125 pi.
    r = collision_proxy(part([cyl("outer", 0.05, 0.5), cyl("bore", 0.04, 0.5, op="subtract")]))
    assert r.proxy_volume.value == approx(0.00125 * math.pi)
    assert r.recipe_volume.value == approx(0.00045 * math.pi)
    assert r.volume_error.value == approx(0.0008 / 0.00045)  # +178 %: a tube's proxy is a bar
    assert r.volume_error.value > 1.0


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
    # A bracket: block with a rotated cylindrical hole through it, plus a post on top and a ball on the side.
    comps = [
        box("base", 0.4, 0.2, 0.1, at=(0.0, 0.0, 0.05)),
        cyl("bore", 0.03, 0.2, at=(0.1, 0.0, 0.05), op="subtract", quat=ROT_X90),
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
    # By hand: base 0.008 + post pi 0.0016 0.3 + ball 4/3 pi 0.000512; bore pi 0.0009 0.2.
    proxy_hand = 0.008 + math.pi * 0.0016 * 0.3 + 4.0 / 3.0 * math.pi * 0.000512
    bore_hand = math.pi * 0.0009 * 0.2
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


def test_proxy_cannot_be_forged():
    r = collision_proxy(part([box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, op="subtract")]))
    CollisionProxy.model_validate(_dump(r))

    def broken(edit, match: str | None):
        d = _dump(r)
        edit(d)
        with pytest.raises(ValueError, match=match):
            CollisionProxy.model_validate(d)

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
