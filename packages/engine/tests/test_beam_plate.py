"""B-02a: the library parts `beam` (I-beam) and `plate` (flat plate with an edge rim), added by `docs/process/add-part.md`.

Definitions: `packages/engine/src/kinetra_engine/parts/library/{beam,plate}.json`. Every expected value below is a hand
calculation from textbook formulas (box volume, parallel axis theorem, quaternion rotation of a vector), not read from the
code under test. Dimensions are `default`-badged choices of this project, not catalogue sections.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest
from gltf_samples import catalog_material
from gltf_validate import validate

from kinetra_core import PartDef, Quantity
from kinetra_engine.parts import PartCache, ShapeError, collision_proxy, mass_properties, part_glb

LIBRARY = Path(__file__).parents[1] / "src" / "kinetra_engine" / "parts" / "library"
SRC = {"ref": "B-02a test: value chosen by the test"}
AL = catalog_material("al6061-t6")
RHO = 2700.0  # al6061-t6 in material_catalog.json (B-07)


def load(part_id: str) -> PartDef:
    return PartDef.model_validate_json((LIBRARY / f"{part_id}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def beam() -> PartDef:
    return load("beam")


@pytest.fixture(scope="module")
def plate() -> PartDef:
    return load("plate")


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


# ---- beam: flanges b x t, web t x (h - 2t), all of length L, hand formulas --------------------------------------------


def beam_volume(L, h, b, t):
    return L * (2 * b * t + t * (h - 2 * t))


def beam_inertia(L, h, b, t):
    """Principal moments about the centre (the section is symmetric, so the centre is the origin and products vanish)."""
    mf, mw = RHO * L * b * t, RHO * L * t * (h - 2 * t)
    d = (h - t) / 2  # flange centre height
    hw = h - 2 * t
    ixx = 2 * (mf * (b**2 + t**2) / 12 + mf * d**2) + mw * (t**2 + hw**2) / 12  # about the long axis x
    iyy = 2 * (mf * (L**2 + t**2) / 12 + mf * d**2) + mw * (L**2 + hw**2) / 12
    izz = 2 * mf * (L**2 + b**2) / 12 + mw * (L**2 + t**2) / 12
    return ixx, iyy, izz


def test_beam_default_mass_centre_and_inertia_match_hand_calculation(beam):
    # L = 0.5, h = 0.06, b = 0.04, t = 0.004 m: flanges 0.216 kg each, web 0.2808 kg, total 0.7128 kg.
    r = mass_properties(beam, AL)
    assert r.volume.value == pytest.approx(0.000264, rel=1e-12)
    assert r.mass.value == pytest.approx(0.7128, rel=1e-12)
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    # By hand: Ixx = 2 (0.216 (0.0016 + 0.000016)/12 + 0.216 0.028^2) + 0.2808 (0.000016 + 0.052^2)/12 = 4.60512e-4.
    assert r.inertia.ixx == pytest.approx(4.60512e-4, rel=1e-9)
    assert (r.inertia.ixx, r.inertia.iyy, r.inertia.izz) == pytest.approx(beam_inertia(0.5, 0.06, 0.04, 0.004), rel=1e-9)
    assert (r.inertia.ixy, r.inertia.ixz, r.inertia.iyz) == pytest.approx((0.0, 0.0, 0.0), abs=1e-15)


@pytest.mark.parametrize("name", ["length", "height", "flange_width", "thickness"])
@pytest.mark.parametrize("end", ["min", "max"])
def test_beam_changing_a_dimension_changes_the_mass_as_the_formula_says(beam, name, end):
    lo, default, hi = ranges(beam)[name]
    v = lo if end == "min" else hi
    base = {"length": 0.5, "height": 0.06, "flange_width": 0.04, "thickness": 0.004}
    changed = {**base, name: v}
    r = mass_properties(beam, AL, params(**{name: v}))
    L, h, b, t = changed["length"], changed["height"], changed["flange_width"], changed["thickness"]
    assert r.volume.value == pytest.approx(beam_volume(L, h, b, t), rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * beam_volume(L, h, b, t), rel=1e-12)
    assert (r.inertia.ixx, r.inertia.iyy, r.inertia.izz) == pytest.approx(beam_inertia(L, h, b, t), rel=1e-9)
    assert r.center_of_mass.z == pytest.approx(0.0, abs=1e-12)
    # The change is visible: the default and the changed value give different masses.
    assert r.mass.value != pytest.approx(mass_properties(beam, AL).mass.value, rel=1e-6)


def test_beam_mass_grows_with_every_dimension_and_is_proportional_to_length(beam):
    base = mass_properties(beam, AL).mass.value
    for name, bigger in (("height", 0.08), ("flange_width", 0.06), ("thickness", 0.006), ("length", 0.6)):
        assert mass_properties(beam, AL, params(**{name: bigger})).mass.value > base, name
    assert mass_properties(beam, AL, params(length=1.0)).mass.value == pytest.approx(2 * base, rel=1e-12)


def test_beam_mass_scales_with_the_material_density(beam):
    cfrp = catalog_material("cfrp-8552-as4-pw")  # 1570 kg/m^3 in the B-07 catalog
    assert mass_properties(beam, cfrp).mass.value == pytest.approx(1570.0 * 0.000264, rel=1e-12)


def test_beam_every_corner_of_the_parameter_range_is_a_valid_disjoint_recipe(beam):
    r = ranges(beam)
    for combo in itertools.product(*[(lo, hi) for lo, _, hi in r.values()]):
        values = dict(zip(r, combo))
        got = mass_properties(beam, AL, params(**values))
        assert got.volume.value == pytest.approx(
            beam_volume(values["length"], values["height"], values["flange_width"], values["thickness"]), rel=1e-12
        )


@pytest.mark.parametrize(
    ("name", "bad"), [("length", 0.09), ("length", 2.01), ("height", 0.019), ("flange_width", 0.16), ("thickness", 0.0019), ("thickness", 0.009)]
)
def test_beam_rejects_a_dimension_outside_its_range(beam, name, bad):
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(beam, AL, params(**{name: bad}))


def test_beam_rejects_unknown_and_wrong_unit_parameters(beam):
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(beam, AL, params(width=0.1))
    with pytest.raises(ShapeError, match="need unit"):
        mass_properties(beam, AL, {"length": Quantity(value=0.5, unit="kg", badge="declared", source=SRC)})


def test_beam_snap_points_follow_the_dimensions_and_face_outwards(beam):
    for L, h in ((0.5, 0.06), (0.1, 0.02), (2.0, 0.2)):
        values = {"length": L, "height": h, "flange_width": 0.04, "thickness": 0.004}
        want = {
            "end-a": ((-L / 2, 0.0, 0.0), (-1.0, 0.0, 0.0)),
            "end-b": ((L / 2, 0.0, 0.0), (1.0, 0.0, 0.0)),
            "top": ((0.0, 0.0, h / 2), (0.0, 0.0, 1.0)),
            "bottom": ((0.0, 0.0, -h / 2), (0.0, 0.0, -1.0)),
        }
        assert {s.id for s in beam.snap_points} == set(want)
        for s in beam.snap_points:
            position, normal = want[s.id]
            assert s.position.evaluate(values) == pytest.approx(position, abs=1e-12), s.id
            # The snap frame's +Z is the outward normal of the surface it sits on.
            assert rotate(s.orientation.model_dump(), (0.0, 0.0, 1.0)) == pytest.approx(normal, abs=1e-12), s.id


def test_beam_snap_points_lie_on_the_extremes_of_the_collision_proxy(beam):
    # The proxy boxes are axis aligned and unrotated: the extreme of their union is the part's outer surface.
    for values in ({"length": 0.5, "height": 0.06}, {"length": 1.7, "height": 0.2}):
        proxy = collision_proxy(beam, params(**values))
        x_max = max(g.center[0] + g.dimensions[0].value / 2 for g in proxy.geoms)
        z_max = max(g.center[2] + g.dimensions[2].value / 2 for g in proxy.geoms)
        end_b = next(s for s in beam.snap_points if s.id == "end-b")
        top = next(s for s in beam.snap_points if s.id == "top")
        full = {"flange_width": 0.04, "thickness": 0.004, **values}
        assert end_b.position.evaluate(full)[0] == pytest.approx(x_max, abs=1e-12)
        assert top.position.evaluate(full)[2] == pytest.approx(z_max, abs=1e-12)


# ---- plate: slab L x W x t and a rim t wide and 2t high on the four edges, sitting on the slab -----------------------


def plate_volume(L, W, t):
    slab = L * W * t
    rim = 2 * (L * t * 2 * t) + 2 * (t * (W - 2 * t) * 2 * t)  # two long rims, two short rims between them
    return slab + rim


def plate_centre_z(L, W, t):
    """Slab centred at z = 0; the rim spans z from t/2 to 5t/2, centre 3t/2."""
    slab = L * W * t
    rim = plate_volume(L, W, t) - slab
    return rim * 1.5 * t / (slab + rim)


def test_plate_default_mass_and_centre_match_hand_calculation(plate):
    # L = 0.3, W = 0.2, t = 0.005 m: slab 3.0e-4 m^3, long rims 2 x 1.5e-5, short rims 2 x 9.5e-6 -> 3.49e-4 m^3.
    r = mass_properties(plate, AL)
    assert r.volume.value == pytest.approx(3.49e-4, rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * 3.49e-4, rel=1e-12)
    # z centre: rim volume 4.9e-5 m^3 at z = 0.0075 m over 3.49e-4 m^3 total.
    assert r.center_of_mass.z == pytest.approx(4.9e-5 * 0.0075 / 3.49e-4, rel=1e-9)
    assert (r.center_of_mass.x, r.center_of_mass.y) == pytest.approx((0.0, 0.0), abs=1e-12)


def test_plate_default_inertia_about_z_matches_hand_calculation(plate):
    # Izz of a box about its own z: m (a^2 + b^2) / 12; the rims are offset from the z axis by their centre distance.
    L, W, t = 0.3, 0.2, 0.005
    slab = RHO * L * W * t * (L**2 + W**2) / 12
    long_rim = RHO * L * t * 2 * t  # centre y = +-(W/2 - t/2)
    short_rim = RHO * t * (W - 2 * t) * 2 * t  # centre x = +-(L/2 - t/2)
    izz = slab + 2 * (long_rim * (L**2 + t**2) / 12 + long_rim * (W / 2 - t / 2) ** 2)
    izz += 2 * (short_rim * (t**2 + (W - 2 * t) ** 2) / 12 + short_rim * (L / 2 - t / 2) ** 2)
    assert mass_properties(plate, AL).inertia.izz == pytest.approx(izz, rel=1e-9)


@pytest.mark.parametrize("name", ["length", "width", "thickness"])
@pytest.mark.parametrize("end", ["min", "max"])
def test_plate_changing_a_dimension_changes_mass_and_centre_as_the_formula_says(plate, name, end):
    lo, _, hi = ranges(plate)[name]
    v = lo if end == "min" else hi
    d = {"length": 0.3, "width": 0.2, "thickness": 0.005, name: v}
    r = mass_properties(plate, AL, params(**{name: v}))
    assert r.volume.value == pytest.approx(plate_volume(d["length"], d["width"], d["thickness"]), rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * plate_volume(d["length"], d["width"], d["thickness"]), rel=1e-12)
    assert r.center_of_mass.z == pytest.approx(plate_centre_z(d["length"], d["width"], d["thickness"]), rel=1e-9)
    assert r.mass.value != pytest.approx(mass_properties(plate, AL).mass.value, rel=1e-6)


def test_plate_mass_grows_with_every_dimension(plate):
    base = mass_properties(plate, AL).mass.value
    for name, bigger in (("length", 0.4), ("width", 0.3), ("thickness", 0.008)):
        assert mass_properties(plate, AL, params(**{name: bigger})).mass.value > base, name


def test_plate_every_corner_of_the_parameter_range_is_a_valid_disjoint_recipe(plate):
    r = ranges(plate)
    for combo in itertools.product(*[(lo, hi) for lo, _, hi in r.values()]):
        v = dict(zip(r, combo))
        got = mass_properties(plate, AL, params(**v))
        assert got.volume.value == pytest.approx(plate_volume(v["length"], v["width"], v["thickness"]), rel=1e-12)


@pytest.mark.parametrize(("name", "bad"), [("length", 0.049), ("length", 1.01), ("width", 0.049), ("width", 1.01), ("thickness", 0.0019), ("thickness", 0.021)])
def test_plate_rejects_a_dimension_outside_its_range(plate, name, bad):
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(plate, AL, params(**{name: bad}))


def test_plate_rejects_unknown_parameters(plate):
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(plate, AL, params(height=0.1))


def test_plate_snap_points_follow_the_dimensions_and_face_outwards(plate):
    for L, W, t in ((0.3, 0.2, 0.005), (0.05, 1.0, 0.02), (1.0, 0.05, 0.002)):
        values = {"length": L, "width": W, "thickness": t}
        want = {
            "top": ((0.0, 0.0, t / 2), (0.0, 0.0, 1.0)),  # the slab's top surface inside the rim
            "bottom": ((0.0, 0.0, -t / 2), (0.0, 0.0, -1.0)),
            "edge-xp": ((L / 2, 0.0, 0.0), (1.0, 0.0, 0.0)),
            "edge-xn": ((-L / 2, 0.0, 0.0), (-1.0, 0.0, 0.0)),
            "edge-yp": ((0.0, W / 2, 0.0), (0.0, 1.0, 0.0)),
            "edge-yn": ((0.0, -W / 2, 0.0), (0.0, -1.0, 0.0)),
        }
        assert {s.id for s in plate.snap_points} == set(want)
        for s in plate.snap_points:
            position, normal = want[s.id]
            assert s.position.evaluate(values) == pytest.approx(position, abs=1e-12), s.id
            assert rotate(s.orientation.model_dump(), (0.0, 0.0, 1.0)) == pytest.approx(normal, abs=1e-12), s.id


def test_beam_ends_and_beam_or_plate_faces_accept_each_other(beam, plate):
    # #541: a post is a beam end butted onto a face, so `end` and `face` accept each other (the validator wants both directions)
    tags = {(p.id, s.id): (s.kind, s.accepts) for p in (beam, plate) for s in p.snap_points}
    assert tags[("beam", "end-a")] == tags[("beam", "end-b")] == ("end", ("end", "edge", "face"))
    for face in (("beam", "top"), ("beam", "bottom"), ("plate", "top"), ("plate", "bottom")):
        assert tags[face] == ("face", ("face", "end")), face
    for edge in ("edge-xp", "edge-xn", "edge-yp", "edge-yn"):
        assert tags[("plate", edge)] == ("edge", ("end", "edge")), edge


def test_plate_edge_snap_points_lie_on_the_extremes_of_the_collision_proxy(plate):
    values = {"length": 0.7, "width": 0.4, "thickness": 0.01}
    proxy = collision_proxy(plate, params(**values))
    ext = lambda i: (  # noqa: E731
        min(g.center[i] - g.dimensions[i].value / 2 for g in proxy.geoms),
        max(g.center[i] + g.dimensions[i].value / 2 for g in proxy.geoms),
    )
    by_id = {s.id: s.position.evaluate(values) for s in plate.snap_points}
    assert by_id["edge-xp"][0] == pytest.approx(ext(0)[1], abs=1e-12)
    assert by_id["edge-xn"][0] == pytest.approx(ext(0)[0], abs=1e-12)
    assert by_id["edge-yp"][1] == pytest.approx(ext(1)[1], abs=1e-12)
    assert by_id["edge-yn"][1] == pytest.approx(ext(1)[0], abs=1e-12)
    assert by_id["bottom"][2] == pytest.approx(ext(2)[0], abs=1e-12)


# ---- both parts ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("part_id", ["beam", "plate"])
def test_beam_and_plate_files_are_named_after_their_ids_and_have_no_voids(part_id):
    part = load(part_id)
    assert part.id == part_id
    proxy = collision_proxy(part)
    assert not proxy.filled_voids and proxy.volume_error.value == 0.0
    assert len(proxy.geoms) == len(part.shape.components)  # one proxy box per added component


@pytest.mark.parametrize("part_id", ["beam", "plate"])
def test_beam_and_plate_glb_is_valid_over_the_parameter_range(part_id):
    part = load(part_id)
    r = ranges(part)
    for combo in (tuple(lo for lo, _, _ in r.values()), tuple(hi for _, _, hi in r.values())):
        validate(part_glb(part, AL, params(**dict(zip(r, combo)))))
    validate(part_glb(part, AL))


@pytest.mark.parametrize("part_id", ["beam", "plate"])
def test_beam_and_plate_say_what_every_number_is(part_id):
    # No number claims a datasheet: ranges, dimensions and snap poses are `default` (Kinetra's choice, reason in the source).
    part = load(part_id)
    badges = {p.default.badge.value for p in part.parameters} | {p.min.badge.value for p in part.parameters}
    badges |= {p.max.badge.value for p in part.parameters} | {part.shape.badge.value} | {s.badge.value for s in part.snap_points}
    assert badges == {"default"}
    assert all("not a datasheet" in p.min.source.ref or "chosen by Kinetra" in p.min.source.ref for p in part.parameters)
    assert not part.specs
    r = mass_properties(part, AL)
    assert r.derivation.shape.badge.value == "default"
    assert {b.value for b in r.derivation.input_badges} == {"cite", "default"}  # the density is cited, the dimensions are not


@pytest.mark.parametrize("part_id", ["beam", "plate"])
def test_beam_and_plate_compile_through_the_cache_like_directly(part_id):
    part = load(part_id)
    cache = PartCache(max_entries=8)
    assert cache.mass_properties(part, AL, None) == mass_properties(part, AL)
    assert cache.mass_properties(part, AL, None) is cache.mass_properties(part, AL, None)
    assert (cache.stats().misses, cache.stats().hits) == (1, 2)  # three calls: one compile, two hits


def test_beam_and_plate_definitions_are_deterministic_text():
    # The committed JSON is what the generator would write: loading and dumping is the identity.
    import json

    for part_id in ("beam", "plate"):
        text = (LIBRARY / f"{part_id}.json").read_text(encoding="utf-8")
        assert json.dumps(load(part_id).model_dump(mode="json", exclude_none=True), indent=2) + "\n" == text


def test_beam_proxy_matches_the_recipe_dimensions():
    proxy = collision_proxy(load("beam"))
    sizes = {g.id: tuple(d.value for d in g.dimensions) for g in proxy.geoms}
    assert sizes["flange_top"] == pytest.approx((0.5, 0.04, 0.004), abs=1e-12)
    assert sizes["web"] == pytest.approx((0.5, 0.004, 0.052), abs=1e-12)
    assert math.isclose(sum(g.volume for g in proxy.geoms), 0.000264, rel_tol=1e-12)
