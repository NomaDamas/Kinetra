"""B-02b: the library part `shell` (an original open-cab body shell), added by `docs/process/add-part.md`.

Definition: `packages/engine/src/kinetra_engine/parts/library/shell.json`. Every expected value below is a hand calculation:
the body is written down again as boxes given by their x/y/z extents (the recipe gives centre and size, so this is a different
route to the same volume), then volume, centroid and inertia come from textbook formulas (box volume, weighted mean of
centroids, box inertia m (b^2 + c^2) / 12, parallel axis theorem). Dimensions are `default`-badged choices of this project,
not a real vehicle's and not a datasheet's.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest
from gltf_samples import catalog_material
from gltf_validate import validate

from kinetra_core import PartDef, Quantity
from kinetra_engine.parts import PartCache, ShapeError, collision_proxy, mass_properties, part_glb

LIBRARY = Path(__file__).parents[1] / "src" / "kinetra_engine" / "parts" / "library"
SRC = {"ref": "B-02b test: value chosen by the test"}
AL = catalog_material("al6061-t6")
RHO = 2700.0  # al6061-t6 in material_catalog.json (B-07)
S2 = math.sqrt(0.5)


def load() -> PartDef:
    return PartDef.model_validate_json((LIBRARY / "shell.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def shell() -> PartDef:
    return load()


def params(**values: float) -> dict[str, Quantity]:
    return {k: Quantity(value=v, unit="m", badge="declared", source=SRC) for k, v in values.items()}


def ranges(part: PartDef) -> dict[str, tuple[float, float, float]]:
    return {p.name: (p.min.value, p.default.value, p.max.value) for p in part.parameters}


DEFAULT = {"length": 0.4, "width": 0.2, "height": 0.12, "thickness": 0.004}


def rotate(q: dict[str, float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    """v' = v + 2 w (u x v) + 2 u x (u x v), u = (x, y, z)."""
    ux, uy, uz, w = q["x"], q["y"], q["z"], q["w"]
    cx = (uy * v[2] - uz * v[1], uz * v[0] - ux * v[2], ux * v[1] - uy * v[0])
    ccx = (uy * cx[2] - uz * cx[1], uz * cx[0] - ux * cx[2], ux * cx[1] - uy * cx[0])
    return tuple(v[i] + 2 * w * cx[i] + 2 * ccx[i] for i in range(3))  # type: ignore[return-value]


# ---- the body as boxes of extents, the same drawing as docs/architecture/parts-shell.md ----------------------------------
# x runs tail to nose, as fractions of the length L: cabin from -0.15 L to 0.1 L, the arch walls over the wheel openings at
# -0.42 L .. -0.22 L and 0.22 L .. 0.42 L, nose at +L/2, tail at -L/2. z = 0 is the belt line (the top of the lower walls and the
# hood); the floor is the bottom t of the body at z = -H/2, the roof the top t at z = +H/2.


def boxes(L, W, H, t):
    """(x0, x1, y0, y1, z0, z1) of every solid box: the sum is the part (no overlap, contact only)."""
    z_floor = -H / 2
    out = [(-L / 2, L / 2, -W / 2, W / 2, z_floor, z_floor + t)]  # floor
    for s in (1, -1):
        y0, y1 = sorted((s * W / 2, s * (W / 2 - t)))
        for x0, x1 in ((-0.5 * L, -0.42 * L), (-0.22 * L, 0.22 * L), (0.42 * L, 0.5 * L)):
            out.append((x0, x1, y0, y1, z_floor + t, 0.0))  # lower wall: from the floor up to the belt line
        for x0, x1 in ((-0.42 * L, -0.22 * L), (0.22 * L, 0.42 * L)):
            out.append((x0, x1, y0, y1, -H / 4 + t / 2, 0.0))  # the wall over a wheel opening: from the opening's top up
        out.append((-0.15 * L, 0.1 * L, y0, y1, 0.0, H / 2 - t))  # cabin wall
    inner = (-(W / 2 - t), W / 2 - t)
    out.append((L / 2 - t, L / 2, *inner, z_floor + t, 0.0))  # nose
    out.append((-L / 2, -L / 2 + t, *inner, z_floor + t, 0.0))  # tail
    out.append((0.1 * L, L / 2 - t, *inner, -t, 0.0))  # hood
    out.append((0.1 * L - t, 0.1 * L, *inner, 0.0, H / 2 - t))  # windscreen
    out.append((-0.15 * L, -0.15 * L + t, *inner, 0.0, H / 2 - t))  # cabin back
    out.append((-0.15 * L, 0.1 * L, -W / 2, W / 2, H / 2 - t, H / 2))  # roof
    return out


def vol(b):
    return (b[1] - b[0]) * (b[3] - b[2]) * (b[5] - b[4])


def centre(b):
    return ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)


def hand_volume(L, W, H, t):
    return sum(vol(b) for b in boxes(L, W, H, t))


def hand_centroid(L, W, H, t):
    bs = boxes(L, W, H, t)
    v = sum(vol(b) for b in bs)
    return tuple(sum(vol(b) * centre(b)[i] for b in bs) / v for i in range(3))


def hand_inertia(L, W, H, t):
    """(Ixx, Iyy, Izz, Ixz) about the centroid, density RHO; Ixz = -sum m x z (the sign convention of `MassProperties`)."""
    bs = boxes(L, W, H, t)
    c = hand_centroid(L, W, H, t)
    ixx = iyy = izz = ixz = 0.0
    for b in bs:
        m = RHO * vol(b)
        a, bb, cc = b[1] - b[0], b[3] - b[2], b[5] - b[4]
        dx, dy, dz = (centre(b)[i] - c[i] for i in range(3))
        ixx += m * (bb**2 + cc**2) / 12 + m * (dy**2 + dz**2)
        iyy += m * (a**2 + cc**2) / 12 + m * (dx**2 + dz**2)
        izz += m * (a**2 + bb**2) / 12 + m * (dx**2 + dy**2)
        ixz -= m * dx * dz
    return ixx, iyy, izz, ixz


# ---- mass, centre and inertia --------------------------------------------------------------------------------------------


def test_shell_default_volume_and_mass_match_hand_calculation():
    # L = 0.4, W = 0.2, H = 0.12, t = 0.004 m, in m^3: floor 3.2e-4, lower walls 2 x 5.376e-5, wheel-opening walls 2 x 1.792e-5,
    # cabin walls 2 x 2.24e-5, nose and tail 2 x 4.3008e-5, hood 1.19808e-4, windscreen and cabin back 2 x 4.3008e-5, roof 8e-5.
    expected = 3.2e-4 + 2 * 5.376e-5 + 2 * 1.792e-5 + 2 * 2.24e-5 + 2 * 4.3008e-5 + 1.19808e-4 + 2 * 4.3008e-5 + 8e-5
    assert expected == pytest.approx(8.8e-4, rel=1e-12)
    r = mass_properties(load(), AL)
    assert r.volume.value == pytest.approx(8.8e-4, rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * 8.8e-4, rel=1e-12)  # 2.376 kg of aluminium
    assert r.volume.value == pytest.approx(hand_volume(**dict(zip("LWHt", DEFAULT.values()))), rel=1e-12)


def test_shell_default_centre_of_mass_matches_hand_calculation(shell):
    r = mass_properties(shell, AL)
    want = hand_centroid(0.4, 0.2, 0.12, 0.004)
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == pytest.approx(want, abs=1e-12)
    assert r.center_of_mass.y == pytest.approx(0.0, abs=1e-12)  # mirror symmetric about y = 0
    # Hand check of the x component: the floor (centre 0, 3.2e-4) and the roof (centre -0.025 L, 8e-5) alone would give
    # a negative x; the hood and nose pull it forward, so the whole body ends up 13.67 mm forward of the middle.
    assert r.center_of_mass.x == pytest.approx(0.013669527272727274, rel=1e-9)
    assert r.center_of_mass.z < 0.0  # the heavy floor is below the belt line


def test_shell_default_inertia_matches_hand_calculation(shell):
    r = mass_properties(shell, AL)
    ixx, iyy, izz, ixz = hand_inertia(0.4, 0.2, 0.12, 0.004)
    assert (r.inertia.ixx, r.inertia.iyy, r.inertia.izz) == pytest.approx((ixx, iyy, izz), rel=1e-9)
    assert r.inertia.ixz == pytest.approx(ixz, rel=1e-9)
    assert (r.inertia.ixy, r.inertia.iyz) == pytest.approx((0.0, 0.0), abs=1e-15)  # mirror symmetric about y = 0
    assert r.inertia.ixz != 0.0  # the body is not symmetric about x or z: the product term is real
    assert izz > ixx and izz > iyy  # a long, thin-walled tub: the yaw moment is the largest


@pytest.mark.parametrize("name", ["length", "width", "height", "thickness"])
@pytest.mark.parametrize("end", ["min", "max"])
def test_shell_changing_a_dimension_changes_mass_centre_and_inertia_as_the_formulas_say(shell, name, end):
    lo, _, hi = ranges(shell)[name]
    v = lo if end == "min" else hi
    d = {**DEFAULT, name: v}
    args = (d["length"], d["width"], d["height"], d["thickness"])
    r = mass_properties(shell, AL, params(**{name: v}))
    assert r.volume.value == pytest.approx(hand_volume(*args), rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * hand_volume(*args), rel=1e-12)
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == pytest.approx(hand_centroid(*args), abs=1e-12)
    assert (r.inertia.ixx, r.inertia.iyy, r.inertia.izz) == pytest.approx(hand_inertia(*args)[:3], rel=1e-9)
    # The change is visible: the default and the changed value give different masses.
    assert r.mass.value != pytest.approx(mass_properties(shell, AL).mass.value, rel=1e-6)


def test_shell_mass_grows_with_every_dimension(shell):
    base = mass_properties(shell, AL).mass.value
    for name, bigger in (("length", 0.5), ("width", 0.3), ("height", 0.15), ("thickness", 0.006)):
        assert mass_properties(shell, AL, params(**{name: bigger})).mass.value > base, name


def test_shell_mass_scales_with_the_material_density(shell):
    cfrp = catalog_material("cfrp-8552-as4-pw")  # 1570 kg/m^3 in the B-07 catalog
    assert mass_properties(shell, cfrp).mass.value == pytest.approx(1570.0 * 8.8e-4, rel=1e-12)


def test_shell_every_corner_of_the_parameter_range_is_a_valid_disjoint_recipe(shell):
    r = ranges(shell)
    for combo in itertools.product(*[(lo, hi) for lo, _, hi in r.values()]):
        v = dict(zip(r, combo))
        got = mass_properties(shell, AL, params(**v))
        assert got.volume.value == pytest.approx(hand_volume(v["length"], v["width"], v["height"], v["thickness"]), rel=1e-12)


@pytest.mark.parametrize(
    ("name", "bad"),
    [("length", 0.19), ("length", 0.81), ("width", 0.09), ("width", 0.41), ("height", 0.059), ("height", 0.31), ("thickness", 0.0019), ("thickness", 0.011)],
)
def test_shell_rejects_a_dimension_outside_its_range(shell, name, bad):
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(shell, AL, params(**{name: bad}))


def test_shell_rejects_unknown_and_wrong_unit_parameters(shell):
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(shell, AL, params(radius=0.1))
    with pytest.raises(ShapeError, match="need unit"):
        mass_properties(shell, AL, {"length": Quantity(value=0.4, unit="kg", badge="declared", source=SRC)})


# ---- snap points ---------------------------------------------------------------------------------------------------------


def snap_expectations(L, W, H, t):
    """Position and outward normal of every snap point, by hand. Frame: x forward, y left, z up."""
    zw = -H / 4 + t / 2  # centre of the lower wall (the nose and tail middle)
    z_axle = (-H / 2 + t + (-H / 4 + t / 2)) / 2  # middle of the wheel opening: floor top .. the arch wall's lower edge
    want = {
        "bed": ((-0.325 * L + t / 2, 0.0, -H / 2 + t), (0.0, 0.0, 1.0)),  # floor top, middle of the open bed
        "underside": ((0.0, 0.0, -H / 2), (0.0, 0.0, -1.0)),
        "roof": ((-0.025 * L, 0.0, H / 2), (0.0, 0.0, 1.0)),
        "nose": ((L / 2, 0.0, zw), (1.0, 0.0, 0.0)),
        "tail": ((-L / 2, 0.0, zw), (-1.0, 0.0, 0.0)),
    }
    for name, sx, sy in (("fl", 1, 1), ("fr", 1, -1), ("rl", -1, 1), ("rr", -1, -1)):
        want[f"axle-{name}"] = ((sx * 0.32 * L, sy * W / 2, z_axle), (0.0, float(sy), 0.0))
    return want


@pytest.mark.parametrize("values", [DEFAULT, {"length": 0.2, "width": 0.1, "height": 0.06, "thickness": 0.01}, {"length": 0.8, "width": 0.4, "height": 0.3, "thickness": 0.002}])
def test_shell_snap_points_follow_the_dimensions_and_face_outwards(shell, values):
    want = snap_expectations(values["length"], values["width"], values["height"], values["thickness"])
    assert {s.id for s in shell.snap_points} == set(want)
    assert len(shell.snap_points) >= 4  # DoD: four or more snap points
    for s in shell.snap_points:
        position, normal = want[s.id]
        assert s.position.evaluate(values) == pytest.approx(position, abs=1e-12), s.id
        # The snap frame's +Z is the outward normal of the surface it sits on.
        assert rotate(s.orientation.model_dump(), (0.0, 0.0, 1.0)) == pytest.approx(normal, abs=1e-12), s.id


def test_shell_snap_points_lie_on_the_collision_proxy(shell):
    # The proxy boxes are axis aligned and unrotated: the extremes of their union are the body's outer surface.
    for values in (DEFAULT, {"length": 0.7, "width": 0.3, "height": 0.2, "thickness": 0.006}):
        proxy = collision_proxy(shell, params(**values))
        lo = [min(g.center[i] - g.dimensions[i].value / 2 for g in proxy.geoms) for i in range(3)]
        hi = [max(g.center[i] + g.dimensions[i].value / 2 for g in proxy.geoms) for i in range(3)]
        at = {s.id: s.position.evaluate(values) for s in shell.snap_points}
        assert at["underside"][2] == pytest.approx(lo[2], abs=1e-12)
        assert at["roof"][2] == pytest.approx(hi[2], abs=1e-12)
        assert at["nose"][0] == pytest.approx(hi[0], abs=1e-12)
        assert at["tail"][0] == pytest.approx(lo[0], abs=1e-12)
        for n in ("fl", "rl"):
            assert at[f"axle-{n}"][1] == pytest.approx(hi[1], abs=1e-12)
        for n in ("fr", "rr"):
            assert at[f"axle-{n}"][1] == pytest.approx(lo[1], abs=1e-12)
        # The bed seat is on top of the floor box and not inside any other box.
        floor = next(g for g in proxy.geoms if g.id == "floor")
        assert at["bed"][2] == pytest.approx(floor.center[2] + floor.dimensions[2].value / 2, abs=1e-12)
        assert not any(
            all(abs(at["bed"][i] - g.center[i]) < g.dimensions[i].value / 2 - 1e-9 for i in range(3)) for g in proxy.geoms
        )  # the seat is a surface point, in no box's interior


def test_shell_axle_snap_points_are_a_mirrored_front_and_rear_pair_in_the_wheel_openings(shell):
    at = {s.id: s.position.evaluate(DEFAULT) for s in shell.snap_points}
    assert at["axle-fl"][0] == pytest.approx(-at["axle-rl"][0], abs=1e-12) and at["axle-fl"][0] > 0
    for a, b in (("fl", "fr"), ("rl", "rr")):
        assert at[f"axle-{a}"][0] == at[f"axle-{b}"][0] and at[f"axle-{a}"][1] == -at[f"axle-{b}"][1]
        assert at[f"axle-{a}"][2] == at[f"axle-{b}"][2]
    # Each axle point sits in the opening: it is in the x range of an arch wall and below the arch wall's lower edge.
    proxy = collision_proxy(shell)
    arch = {g.id: g for g in proxy.geoms}["arch_l_front"]
    assert abs(at["axle-fl"][0] - arch.center[0]) < arch.dimensions[0].value / 2
    assert at["axle-fl"][2] < arch.center[2] - arch.dimensions[2].value / 2
    floor_top = -0.06 + 0.004
    assert at["axle-fl"][2] > floor_top  # and above the floor: the opening is between the two


def test_shell_snap_kinds_and_tags_agree_with_the_four_wheel_car_example(shell):
    # schemas/examples/DesignSpec.four-wheel-car.json: the chassis' wheel sites are `axle_mount` and accept `shaft`.
    by = {s.id: s for s in shell.snap_points}
    for n in ("fl", "fr", "rl", "rr"):
        assert (by[f"axle-{n}"].kind, by[f"axle-{n}"].accepts) == ("axle_mount", ("shaft",))
    assert (by["bed"].kind, by["bed"].accepts) == ("payload_seat", ("payload_base",))  # B-02c's payload `base`
    assert by["nose"].accepts == ("end", "edge") and by["tail"].accepts == ("end", "edge")  # B-02a's `end` / `edge` tags
    assert by["roof"].accepts == by["underside"].accepts == ("face",)


# ---- the outline: not a box or a cylinder --------------------------------------------------------------------------------


def test_shell_is_a_hollow_body_with_a_silhouette_not_a_box(shell):
    proxy = collision_proxy(shell)
    assert len(proxy.geoms) >= 15  # many pieces: a floor, walls, wheel openings, cabin, hood, roof
    L, W, H = 0.4, 0.2, 0.12
    # It fills a small part of its bounding box (a solid block would fill all of it).
    assert mass_properties(shell, AL).volume.value / (L * W * H) == pytest.approx(8.8e-4 / 9.6e-3, rel=1e-12)
    assert 8.8e-4 / 9.6e-3 < 0.1
    # Silhouette from the side: the height of the highest part over each station along x. A box would show one level.
    def top_at(x):
        return max((g.center[2] + g.dimensions[2].value / 2 for g in proxy.geoms if abs(x - g.center[0]) < g.dimensions[0].value / 2), default=None)

    levels = {round(top_at(x), 9) for x in (-0.19, -0.1, 0.0, 0.1, 0.18)}
    assert levels == {0.0, 0.06}  # belt line at the walls, roof line over the cabin, nothing else
    assert top_at(0.0) == pytest.approx(0.06, abs=1e-12) and top_at(0.18) == pytest.approx(0.0, abs=1e-12)
    # The cab is a closed room whose centre is empty, and the bed is open to the sky.
    def inside(p):
        return any(all(abs(p[i] - g.center[i]) < g.dimensions[i].value / 2 for i in range(3)) for g in proxy.geoms)

    assert not inside((-0.01, 0.0, 0.03)) and not inside((-0.13, 0.0, -0.03))
    assert inside((-0.01, 0.0, 0.058)) and inside((0.0, 0.0, -0.058))  # roof and floor are solid


def test_shell_wheel_openings_are_free_of_material(shell):
    proxy = collision_proxy(shell)
    for s in shell.snap_points:
        if s.kind != "axle_mount":
            continue
        p = s.position.evaluate(DEFAULT)
        inner = (p[0], p[1] - math.copysign(0.004, p[1]), p[2])  # a hair inside the side wall
        assert not any(all(abs(inner[i] - g.center[i]) < g.dimensions[i].value / 2 for i in range(3)) for g in proxy.geoms), s.id


# ---- the file, the proxy, the glb, the cache ------------------------------------------------------------------------------


def test_shell_file_is_named_after_its_id_and_has_no_voids(shell):
    assert shell.id == "shell"
    proxy = collision_proxy(shell)
    assert not proxy.filled_voids and proxy.volume_error.value == 0.0
    assert len(proxy.geoms) == len(shell.shape.components)  # one proxy box per added component
    assert sum(g.volume for g in proxy.geoms) == pytest.approx(8.8e-4, rel=1e-12)
    assert all(c.primitive.kind == "box" for c in shell.shape.components)


def test_shell_glb_is_valid_over_the_parameter_range(shell):
    r = ranges(shell)
    for combo in (tuple(lo for lo, _, _ in r.values()), tuple(hi for _, _, hi in r.values())):
        validate(part_glb(shell, AL, params(**dict(zip(r, combo)))))
    glb = validate(part_glb(shell, AL))
    assert len(glb.doc["nodes"]) == 1 + len(shell.shape.components)


def test_shell_says_what_every_number_is(shell):
    # No number claims a datasheet or a real vehicle: ranges, dimensions and snap poses are `default` (Kinetra's choice).
    badges = {q.badge.value for p in shell.parameters for q in (p.default, p.min, p.max)}
    badges |= {shell.shape.badge.value} | {s.badge.value for s in shell.snap_points}
    assert badges == {"default"}
    assert all("not a datasheet" in p.min.source.ref and "original body" in p.min.source.ref for p in shell.parameters)
    assert "not a real vehicle" in shell.shape.source.ref
    assert not shell.specs
    r = mass_properties(shell, AL)
    assert r.derivation.shape.badge.value == "default"
    assert {b.value for b in r.derivation.input_badges} == {"cite", "default"}  # the density is cited, the dimensions are not


def test_shell_compiles_through_the_cache_like_directly(shell):
    cache = PartCache(max_entries=8)
    assert cache.mass_properties(shell, AL, None) == mass_properties(shell, AL)
    assert cache.mass_properties(shell, AL, None) is cache.mass_properties(shell, AL, None)
    assert (cache.stats().misses, cache.stats().hits) == (1, 2)  # three calls: one compile, two hits


def test_shell_definition_is_deterministic_text():
    text = (LIBRARY / "shell.json").read_text(encoding="utf-8")
    assert json.dumps(load().model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False) + "\n" == text
