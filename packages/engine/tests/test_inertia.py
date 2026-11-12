"""B-01a: mass, centre of mass and inertia from a part's shape recipe.

Every expected number is written out by hand from the textbook formula, not read back from the code under test. Test
densities and dimensions are fixtures declared by the test (`사용자 선언`), not real material data.
"""

from __future__ import annotations

import math
import random

import pytest

from kinetra_core import Badge, MassProperties, Material, PartDef, Quantity
from kinetra_engine.parts import ShapeError, mass_properties

SRC = {"ref": "unit-test fixture", "locator": "test_inertia.py"}
RHO = 1000.0  # kg/m^3, fixture


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


def material(density=RHO, badge="declared", source=None):
    return Material.model_validate(
        {
            "id": "test-material",
            "name": "Test material",
            "density": q(density, "kg/m^3", badge, source),
            "yield_strength": q(1.0e7, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"),
            "friction": q(0.5, "1"),
        }
    )


def approx(x):
    return pytest.approx(x, rel=1e-9, abs=1e-15)


def inertia(r: MassProperties):
    i = r.inertia
    return (i.ixx, i.iyy, i.izz, i.ixy, i.ixz, i.iyz)


# Quaternion for a rotation of 90 degrees about +x: local z -> -y... (right-handed): z axis maps to -y, y maps to +z.
S2 = math.sqrt(0.5)
ROT_X90 = {"x": S2, "y": 0.0, "z": 0.0, "w": S2}
ROT_Z90 = {"x": 0.0, "y": 0.0, "z": S2, "w": S2}


# --- three primitives with closed forms -----------------------------------------------------------------------------


def test_inertia_box_matches_hand_calculation():
    # 0.2 x 0.1 x 0.3 m at 1000 kg/m^3: V = 0.006 m^3, m = 6 kg.
    r = mass_properties(part([box("b", 0.2, 0.1, 0.3, at=(0.0, 0.0, 0.0))]), material())
    assert r.volume.value == approx(0.006)
    assert r.mass.value == approx(6.0)
    # I = m (b^2 + c^2) / 12 etc.: 6 * 0.10 / 12, 6 * 0.13 / 12, 6 * 0.05 / 12
    ixx, iyy, izz, ixy, ixz, iyz = inertia(r)
    assert (ixx, iyy, izz) == (approx(0.05), approx(0.065), approx(0.025))
    assert (ixy, ixz, iyz) == (0.0, 0.0, 0.0)
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == (0.0, 0.0, 0.0)


def test_inertia_cylinder_matches_hand_calculation():
    # r = 0.05 m, h = 0.4 m, axis along local z: V = pi r^2 h = pi * 0.0025 * 0.4 = pi * 0.001, m = pi kg.
    r = mass_properties(part([cyl("c", 0.05, 0.4, at=(0.0, 0.0, 0.2))]), material())
    m = math.pi
    assert r.mass.value == approx(m)
    # Izz = m r^2 / 2 = pi * 0.00125; Ixx = Iyy = m (3 r^2 + h^2) / 12 = pi * (0.0075 + 0.16) / 12
    ixx, iyy, izz, *off = inertia(r)
    assert izz == approx(m * 0.00125)
    assert ixx == approx(m * (3 * 0.0025 + 0.16) / 12)
    assert iyy == approx(ixx)
    assert off == [0.0, 0.0, 0.0] or all(abs(v) < 1e-18 for v in off)
    assert r.center_of_mass.z == approx(0.2)  # inertia is about the centre of mass, not the part origin


def test_inertia_sphere_matches_hand_calculation():
    # r = 0.1 m: V = 4/3 pi r^3 = 4/3 pi 0.001, m = 4/3 pi kg; I = 2/5 m r^2.
    r = mass_properties(part([sphere("s", 0.1, at=(0.3, -0.2, 0.1))]), material())
    m = 4.0 / 3.0 * math.pi
    assert r.mass.value == approx(m)
    ixx, iyy, izz, *_ = inertia(r)
    assert (ixx, iyy, izz) == (approx(0.4 * m * 0.01),) * 3
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == (approx(0.3), approx(-0.2), approx(0.1))


# --- composition ---------------------------------------------------------------------------------------------------


def test_inertia_parallel_axis_two_boxes_l_bracket():
    # Foot A 0.4 x 0.1 x 0.1 centred (0.2, 0.05, 0.05): m = 4.  Upright B 0.1 x 0.1 x 0.3 centred (0.05, 0.05, 0.25): m = 3.
    # The boxes touch on the face z = 0.1 and do not overlap.
    r = mass_properties(
        part([box("foot", 0.4, 0.1, 0.1, at=(0.2, 0.05, 0.05)), box("upright", 0.1, 0.1, 0.3, at=(0.05, 0.05, 0.25))]),
        material(),
    )
    assert r.mass.value == approx(7.0)
    cx_ = (4 * 0.2 + 3 * 0.05) / 7  # 0.95 / 7
    cy_ = 0.05
    cz_ = (4 * 0.05 + 3 * 0.25) / 7  # 0.95 / 7
    assert (r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z) == (approx(cx_), approx(cy_), approx(cz_))
    # Foot about its own centre: Ixx = 4 (0.01 + 0.01)/12, Iyy = 4 (0.16 + 0.01)/12, Izz = 4 (0.16 + 0.01)/12.
    # Upright: Ixx = 3 (0.01 + 0.09)/12, Iyy = 3 (0.01 + 0.09)/12, Izz = 3 (0.01 + 0.01)/12.
    # Offsets from the centre of mass: foot d = (0.2 - cx_, 0, 0.05 - cz_), upright d = (0.05 - cx_, 0, 0.25 - cz_).
    df = (0.2 - cx_, 0.0, 0.05 - cz_)
    du = (0.05 - cx_, 0.0, 0.25 - cz_)
    ixx = 4 * 0.02 / 12 + 4 * (df[1] ** 2 + df[2] ** 2) + 3 * 0.10 / 12 + 3 * (du[1] ** 2 + du[2] ** 2)
    iyy = 4 * 0.17 / 12 + 4 * (df[0] ** 2 + df[2] ** 2) + 3 * 0.10 / 12 + 3 * (du[0] ** 2 + du[2] ** 2)
    izz = 4 * 0.17 / 12 + 4 * (df[0] ** 2 + df[1] ** 2) + 3 * 0.02 / 12 + 3 * (du[0] ** 2 + du[1] ** 2)
    ixz = -4 * df[0] * df[2] - 3 * du[0] * du[2]
    got = inertia(r)
    assert got[0] == approx(ixx)
    assert got[1] == approx(iyy)
    assert got[2] == approx(izz)
    assert got[3] == approx(0.0) or abs(got[3]) < 1e-15
    assert got[4] == approx(ixz)
    assert got[5] == approx(0.0) or abs(got[5]) < 1e-15
    # Principal moments of any body obey the triangle inequality; a sign slip in a product term would break it.
    assert got[0] + got[1] >= got[2] and got[1] + got[2] >= got[0] and got[0] + got[2] >= got[1]


def test_inertia_void_is_negative_mass_plate_with_hole():
    # Plate 0.3 x 0.2 x 0.02 (m = 1.2) with a 0.05 m radius hole through it (cylinder length 0.02, centred 0.05 off x).
    # Hole mass = 1000 pi 0.0025 0.02 = 0.05 pi.  Net mass = 1.2 - 0.05 pi.
    h = 0.05 * math.pi
    r = mass_properties(
        part([box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract")]),
        material(),
    )
    assert r.mass.value == approx(1.2 - h)
    assert r.center_of_mass.x == approx(-0.05 * h / (1.2 - h))  # first moment: 1.2 * 0 - h * 0.05
    # Izz about the plate centre: plate m (a^2 + b^2)/12 = 1.2 * 0.13 / 12 = 0.013;
    # hole about its own axis h r^2 / 2 plus h d^2: h * (0.00125 + 0.0025).
    izz_origin = 1.2 * 0.13 / 12 - (h * 0.0025 / 2 + h * 0.05**2)
    comx = -0.05 * h / (1.2 - h)
    izz_com = izz_origin - (1.2 - h) * comx**2  # parallel-axis back to the centre of mass
    assert r.inertia.izz == approx(izz_com)
    assert [c.operation for c in r.derivation.components] == ["add", "subtract"]


def test_inertia_tube_from_two_cylinders_matches_thick_wall_formula():
    # Tube R = 0.05, r = 0.04, length 0.5: m = 1000 pi (R^2 - r^2) h = 1000 pi 0.0009 0.5 = 0.45 pi.
    r = mass_properties(
        part([cyl("outer", 0.05, 0.5, at=(0, 0, 0.25)), cyl("bore", 0.04, 0.5, at=(0, 0, 0.25), op="subtract")]),
        material(),
    )
    m = 0.45 * math.pi
    assert r.mass.value == approx(m)
    assert r.inertia.izz == approx(m * (0.05**2 + 0.04**2) / 2)  # m (R^2 + r^2) / 2
    # Ixx = m (3 (R^2 + r^2) + h^2) / 12
    assert r.inertia.ixx == approx(m * (3 * (0.0025 + 0.0016) + 0.25) / 12)


def test_inertia_rotated_cylinder_axis_follows_orientation():
    # Rotating +90 degrees about +x takes the local z axis to -y: the cylinder lies along y, so the axial moment is Iyy.
    r = mass_properties(part([cyl("c", 0.05, 0.4, quat=ROT_X90)]), material())
    m = math.pi
    assert r.inertia.iyy == approx(m * 0.00125)
    assert r.inertia.ixx == approx(m * (3 * 0.0025 + 0.16) / 12)
    assert r.inertia.izz == approx(r.inertia.ixx)


def test_inertia_rotated_box_off_axis_has_product_terms():
    # A 0.4 x 0.1 x 0.1 box rotated 45 degrees about z: Ixx = Iyy = (I_long + I_short) / 2, Ixy = (I_short - I_long) / 2
    # with the sign convention ixy = -integral(xy dm). m = 4, I_long (about its long axis) = 4 * 0.02 / 12,
    # I_across = 4 * 0.17 / 12.
    c = math.cos(math.pi / 8)
    s = math.sin(math.pi / 8)
    r = mass_properties(part([box("b", 0.4, 0.1, 0.1, quat={"x": 0.0, "y": 0.0, "z": s, "w": c})]), material())
    i_axis, i_across = 4 * 0.02 / 12, 4 * 0.17 / 12
    assert r.inertia.izz == approx(i_across)
    assert r.inertia.ixx == approx((i_axis + i_across) / 2)
    assert r.inertia.iyy == approx((i_axis + i_across) / 2)
    # A body stretched along the line y = x has positive integral(xy dm), so Ixy = -integral < 0.
    assert r.inertia.ixy == approx((i_axis - i_across) / 2)
    assert r.inertia.ixy < 0


# --- independent numeric check (1 % DoD) -----------------------------------------------------------------------------


def _column_moments(chords, nx, ny, x0, x1, y0, y1):
    """Raw moments of a solid given by z-chords over a midpoint grid in (x, y): the z integrals are exact per column.

    `chords(x, y)` returns signed (z_lo, z_hi, sign) intervals. This shares no formula with `mass_properties`.
    """
    hx, hy = (x1 - x0) / nx, (y1 - y0) / ny
    s = dict.fromkeys(("1", "x", "y", "z", "xx", "yy", "zz", "xy", "xz", "yz"), 0.0)
    for i in range(nx):
        x = x0 + (i + 0.5) * hx
        for j in range(ny):
            y = y0 + (j + 0.5) * hy
            for lo, hi, sign in chords(x, y):
                dz = hi - lo
                z1 = (hi * hi - lo * lo) / 2
                z2 = (hi**3 - lo**3) / 3
                w = sign * hx * hy
                s["1"] += w * dz
                s["x"] += w * x * dz
                s["y"] += w * y * dz
                s["z"] += w * z1
                s["xx"] += w * x * x * dz
                s["yy"] += w * y * y * dz
                s["zz"] += w * z2
                s["xy"] += w * x * y * dz
                s["xz"] += w * x * z1
                s["yz"] += w * y * z1
    return s


def test_inertia_matches_independent_numeric_integration_within_one_percent():
    """A composite of a block, a bore, a rod lying along x (a rotated cylinder) and a sphere, integrated numerically.

    The numeric integral sweeps z-chords over an (x, y) grid, so it uses none of the closed forms under test.
    """

    def chords(x, y):
        out = []
        if abs(x) <= 0.2 and abs(y) <= 0.1:  # base block, x -0.2..0.2, y -0.1..0.1, z 0..0.1
            out.append((0.0, 0.1, +1))
        if (x + 0.1) ** 2 + y * y <= 0.04**2:  # vertical bore r 0.04 at x = -0.1, through the block
            out.append((0.0, 0.1, -1))
        if 0.0 <= x <= 0.2 and abs(y) <= 0.03:  # rod r 0.03 along x, axis at z = 0.13
            half = math.sqrt(0.03**2 - y * y)
            out.append((0.13 - half, 0.13 + half, +1))
        r2 = 0.05**2 - x * x - y * y  # sphere r 0.05 at z = 0.22
        if r2 >= 0:
            out.append((0.22 - math.sqrt(r2), 0.22 + math.sqrt(r2), +1))
        return out

    comps = [
        box("base", 0.4, 0.2, 0.1, at=(0.0, 0.0, 0.05)),
        cyl("bore", 0.04, 0.1, at=(-0.1, 0.0, 0.05), op="subtract"),
        cyl("rod", 0.03, 0.2, at=(0.1, 0.0, 0.13), quat={"x": 0.0, "y": S2, "z": 0.0, "w": S2}),  # +90 deg about y: z -> +x
        sphere("ball", 0.05, at=(0.0, 0.0, 0.22)),
    ]
    r = mass_properties(part(comps), material())

    s = _column_moments(chords, 400, 200, -0.2, 0.2, -0.1, 0.1)
    v = s["1"]
    cx_, cy_, cz_ = s["x"] / v, s["y"] / v, s["z"] / v
    m = RHO * v
    ixx = RHO * (s["yy"] + s["zz"]) - m * (cy_**2 + cz_**2)
    iyy = RHO * (s["xx"] + s["zz"]) - m * (cx_**2 + cz_**2)
    izz = RHO * (s["xx"] + s["yy"]) - m * (cx_**2 + cy_**2)
    ixz = -(RHO * s["xz"] - m * cx_ * cz_)

    assert r.mass.value == pytest.approx(m, rel=0.01)
    for got, want in zip((r.center_of_mass.x, r.center_of_mass.y, r.center_of_mass.z), (cx_, cy_, cz_)):
        assert got == pytest.approx(want, abs=0.004)  # 1 % of the largest extent, 0.4 m
    assert r.inertia.ixx == pytest.approx(ixx, rel=0.01)
    assert r.inertia.iyy == pytest.approx(iyy, rel=0.01)
    assert r.inertia.izz == pytest.approx(izz, rel=0.01)
    assert r.inertia.ixz == pytest.approx(ixz, rel=0.01)
    assert abs(r.inertia.ixy) < 1e-4 and abs(r.inertia.iyz) < 1e-4


# --- parameters -------------------------------------------------------------------------------------------------------


def length_param(name="w", default=0.2, lo=0.1, hi=0.5, **kw):
    return {"name": name, "unit": "m", "default": q(default, **kw), "min": q(lo), "max": q(hi)}


def param_part():
    comp = {
        "id": "b",
        "primitive": {"kind": "box", "size_x": ax(0.0, [("w", 1.0)]), "size_y": ax(0.1), "size_z": ax(0.3)},
        "position": {"x": ax(0.0, [("w", 0.5)]), "y": ax(), "z": ax()},
    }
    return part([comp], [length_param()])


def test_inertia_follows_the_parameter_default_and_an_override():
    p = param_part()
    default = mass_properties(p, material())
    assert default.mass.value == approx(RHO * 0.2 * 0.1 * 0.3)
    assert default.center_of_mass.x == approx(0.1)  # position follows 0.5 w
    wide = mass_properties(p, material(), {"w": Quantity.model_validate(q(0.4))})
    assert wide.mass.value == approx(RHO * 0.4 * 0.1 * 0.3)
    assert wide.center_of_mass.x == approx(0.2)
    assert wide.inertia.iyy == approx(wide.mass.value * (0.4**2 + 0.3**2) / 12)


def test_inertia_rejects_override_outside_range_unknown_name_and_wrong_unit():
    p = param_part()
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(p, material(), {"w": Quantity.model_validate(q(0.6))})
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(p, material(), {"nope": Quantity.model_validate(q(0.2))})
    with pytest.raises(ShapeError, match="need unit"):
        mass_properties(p, material(), {"w": Quantity.model_validate(q(0.2, "kg"))})


def test_inertia_needs_a_shape():
    bare = PartDef.model_validate({"id": "bare", "name": "Bare"})
    with pytest.raises(ShapeError, match="no shape recipe"):
        mass_properties(bare, material())


# --- the disjoint-sum rule ----------------------------------------------------------------------------------------------


def test_inertia_rejects_overlapping_added_components():
    two = part([box("a", 0.2, 0.2, 0.2), box("b", 0.2, 0.2, 0.2, at=(0.1, 0.0, 0.0))])
    with pytest.raises(ShapeError, match="added components 'a' and 'b' overlap"):
        mass_properties(two, material())
    ball_in_box = part([box("a", 0.2, 0.2, 0.2), sphere("s", 0.05)])
    with pytest.raises(ShapeError, match="overlap"):
        mass_properties(ball_in_box, material())


@pytest.mark.parametrize(
    "other",
    [
        box("b", 0.2, 0.2, 0.2, at=(0.2, 0.0, 0.0)),  # face contact
        cyl("b", 0.1, 0.2, at=(0.2, 0.0, 0.0)),  # cylinder side against a box face
        sphere("b", 0.1, at=(0.2, 0.0, 0.0)),  # sphere touching a box face
        box("b", 0.1, 0.1, 0.1, at=(0.15, 0.15, 0.15)),  # edge contact
    ],
)
def test_inertia_touching_components_are_not_overlap(other):
    r = mass_properties(part([box("a", 0.2, 0.2, 0.2), other]), material())
    assert r.mass.value > RHO * 0.008


def test_inertia_rejects_void_outside_the_material_or_across_two_components():
    outside = part([box("a", 0.2, 0.2, 0.2), cyl("hole", 0.05, 0.1, at=(0.0, 0.0, 0.15), op="subtract")])
    with pytest.raises(ShapeError, match="void 'hole' is not inside"):
        mass_properties(outside, material())
    across = part(
        [
            box("a", 0.2, 0.2, 0.2, at=(-0.1, 0.0, 0.0)),
            box("b", 0.2, 0.2, 0.2, at=(0.1, 0.0, 0.0)),
            cyl("hole", 0.05, 0.1, op="subtract", quat=ROT_X90),
        ]
    )
    with pytest.raises(ShapeError, match="void 'hole' is not inside a single added component"):
        mass_properties(across, material())


@pytest.mark.parametrize("far", [(1.0e3, 0.0, 0.0), (0.0, -5.0e4, 2.0e3), (1.0e6, 1.0e6, 1.0e6)])
def test_inertia_rejects_fully_coincident_elements_far_from_the_origin(far):
    # The overlap tolerance depends on the two elements compared, not on where they are or what else is in the part.
    a = box("a", 0.2, 0.2, 0.2, at=far)
    b = box("b", 0.2, 0.2, 0.2, at=far)
    with pytest.raises(ShapeError, match="added components 'a' and 'b' overlap"):
        mass_properties(part([a, b]), material())
    # A distant unrelated element must not widen the tolerance either: coincident small boxes next to a huge far box.
    huge = box("huge", 2.0, 2.0, 2.0, at=(-1.0e6, 0.0, 0.0))
    small = [box("s1", 1e-3, 1e-3, 1e-3), box("s2", 1e-3, 1e-3, 1e-3)]
    with pytest.raises(ShapeError, match="'s1' and 's2' overlap"):
        mass_properties(part([huge, *small]), material())


def test_inertia_slightly_overlapping_small_elements_next_to_a_huge_one_are_rejected():
    # 1 mm boxes overlapping by 0.5 mm, with a 2 km box elsewhere in the part.
    p = part([box("huge", 2000.0, 2000.0, 2000.0, at=(5000.0, 0, 0)), box("s1", 1e-3, 1e-3, 1e-3), box("s2", 1e-3, 1e-3, 1e-3, at=(5e-4, 0, 0))])
    with pytest.raises(ShapeError, match="'s1' and 's2' overlap"):
        mass_properties(p, material())


def test_inertia_rejects_a_hole_protruding_from_a_cylinder():
    # Cylinder r 0.1: a box void whose corner reaches radius sqrt(0.09^2 + 0.05^2) = 0.103 > 0.1, though its centre,
    # faces and the axis-aligned extent along x (0.09 + 0.01 slack) are inside.
    p = part([cyl("c", 0.1, 0.3), box("v", 0.18, 0.1, 0.1, op="subtract")])
    with pytest.raises(ShapeError, match="void 'v' is not inside"):
        mass_properties(p, material())
    # A cylinder void tilted 60 degrees about x: its rim end sits 0.1 sin 60 = 0.0866 off the axis, plus up to 0.02 more.
    tilt = {"x": math.sin(math.pi / 6), "y": 0.0, "z": 0.0, "w": math.cos(math.pi / 6)}
    p = part([cyl("c", 0.1, 0.3), cyl("v", 0.04, 0.2, op="subtract", quat=tilt)])
    with pytest.raises(ShapeError, match="void 'v' is not inside"):
        mass_properties(p, material())
    # The same void tilted 30 degrees stays inside (rim at most 0.05 + 0.04 = 0.09 off the axis).
    ok = {"x": math.sin(math.pi / 12), "y": 0.0, "z": 0.0, "w": math.cos(math.pi / 12)}
    mass_properties(part([cyl("c", 0.1, 0.3), cyl("v", 0.04, 0.2, op="subtract", quat=ok)]), material())


def test_inertia_void_that_fits_a_cylinder_by_a_hair_is_accepted_and_one_that_misses_by_a_hair_is_not():
    # Coaxial void with the same radius would be flush: accepted. A tilted cylinder void just inside / just outside r = 0.1.
    flush = part([cyl("c", 0.1, 0.3), cyl("v", 0.1, 0.1, op="subtract")])
    assert mass_properties(flush, material()).mass.value == approx(RHO * math.pi * 0.01 * 0.2)
    # Box void centred on the axis: its corner radius is hypot(a, b) / 2.
    inside = part([cyl("c", 0.1, 0.3), box("v", 0.13, 0.13, 0.1, op="subtract")])  # corner at 0.0919
    assert mass_properties(inside, material()).mass.value > 0
    outside = part([cyl("c", 0.1, 0.3), box("v", 0.142, 0.142, 0.1, op="subtract")])  # corner at 0.1004
    with pytest.raises(ShapeError, match="not inside"):
        mass_properties(outside, material())


def test_inertia_rejects_overlapping_voids():
    p = part([box("a", 0.4, 0.4, 0.4), sphere("v1", 0.05, op="subtract"), sphere("v2", 0.05, at=(0.05, 0, 0), op="subtract")])
    with pytest.raises(ShapeError, match="voids 'v1' and 'v2' overlap"):
        mass_properties(p, material())


def test_inertia_void_inside_a_cylinder_and_a_sphere_is_accepted():
    r = mass_properties(
        part([cyl("c", 0.1, 0.3), cyl("bore", 0.03, 0.3, op="subtract"), sphere("s", 0.05, at=(0.3, 0, 0)), sphere("v", 0.02, at=(0.3, 0, 0), op="subtract")]),
        material(),
    )
    want = RHO * (math.pi * 0.01 * 0.3 - math.pi * 0.0009 * 0.3 + 4 / 3 * math.pi * (0.05**3 - 0.02**3))
    assert r.mass.value == approx(want)


def test_inertia_void_poking_out_of_a_rotated_cylinder_is_rejected():
    p = part([cyl("c", 0.1, 0.3), box("v", 0.05, 0.05, 0.05, at=(0.09, 0.0, 0.0), op="subtract")])
    with pytest.raises(ShapeError, match="not inside"):
        mass_properties(p, material())


def test_inertia_rejects_a_void_that_removes_everything():
    p = part([box("a", 0.2, 0.2, 0.2), box("v", 0.2, 0.2, 0.2, op="subtract")])
    with pytest.raises(ShapeError, match="net volume"):
        mass_properties(p, material())


# --- derived-value provenance (C-01a known extension) ---------------------------------------------------------------


def test_inertia_result_is_sim_with_traceable_inputs():
    cited = {"ref": "Test handbook, Table 1", "locator": "row 3", "license": "CC0-1.0"}
    p = part(
        [box("b", 0.2, 0.1, 0.3)],
        badge="cite",
        source={"ref": "Drawing 42", "locator": "sheet 1"},
    )
    r = mass_properties(p, material(7850.0, "cite", cited))
    for v in (r.volume, r.mass, r.center_of_mass, r.inertia):
        assert v.badge is Badge.SIM
        assert "mass_properties" in v.source.ref and "test-part" in v.source.locator
    d = r.derivation
    assert d.density.value == 7850.0 and d.density.badge is Badge.CITE and d.density.source.locator == "row 3"
    assert d.shape.badge is Badge.CITE and d.shape.source.ref == "Drawing 42"
    assert d.material_id == "test-material"
    assert d.input_badges == (Badge.CITE,)
    assert [c.id for c in d.components] == ["b"]
    assert d.components[0].mass == approx(7850.0 * 0.006)
    assert [(x.name, x.value) for x in d.components[0].dimensions] == [("size_x", approx(0.2)), ("size_y", approx(0.1)), ("size_z", approx(0.3))]
    assert any("disjoint" in a for a in d.assumptions)


def test_inertia_derivation_keeps_resolved_dimensions_centre_and_orientation_per_element():
    p = param_part()
    r = mass_properties(p, material(), {"w": Quantity.model_validate(q(0.4))})
    (c,) = r.derivation.components
    assert [(x.name, x.value) for x in c.dimensions] == [("size_x", approx(0.4)), ("size_y", approx(0.1)), ("size_z", approx(0.3))]  # w resolved
    assert c.center == (approx(0.2), 0.0, 0.0)
    assert (c.orientation.x, c.orientation.y, c.orientation.z, c.orientation.w) == (0.0, 0.0, 0.0, 1.0)
    # Redoing the inertia from the derivation alone (box about its own centre) reproduces the result.
    m = c.mass
    assert r.inertia.ixx == approx(m * (c.dimension("size_y") ** 2 + c.dimension("size_z") ** 2) / 12)
    rod = mass_properties(part([cyl("c", 0.05, 0.4, quat=ROT_X90)]), material())
    (rc,) = rod.derivation.components
    assert [(x.name, x.value) for x in rc.dimensions] == [("radius", approx(0.05)), ("length", approx(0.4))]
    assert (rc.orientation.x, rc.orientation.w) == (approx(S2), approx(S2))


def test_inertia_input_badges_name_every_distinct_input_badge_including_parameters():
    p = part(
        [
            {
                "id": "b",
                "primitive": {"kind": "box", "size_x": ax(0.0, [("w", 1.0)]), "size_y": ax(0.1), "size_z": ax(0.3)},
                "position": pos(),
            }
        ],
        [length_param(badge="estimate", source={"ref": "eyeballed from a photo"})],
        badge="declared",
    )
    r = mass_properties(p, material(1000.0, "default", {"ref": "fixture default"}))
    assert set(r.derivation.input_badges) == {Badge.DECLARED, Badge.DEFAULT, Badge.ESTIMATE}
    (use,) = r.derivation.parameters
    assert use.name == "w" and use.value.badge is Badge.ESTIMATE
    # an override carries its own badge into the derivation
    r2 = mass_properties(p, material(), {"w": Quantity.model_validate(q(0.3, badge="default", source={"ref": "fixture default"}))})
    assert r2.derivation.parameters[0].value.badge is Badge.DEFAULT


def test_inertia_result_cannot_claim_a_badge_other_than_sim():
    r = mass_properties(part([box("b", 0.2, 0.1, 0.3)]), material())
    data = r.model_dump(mode="json")
    data["mass"]["badge"] = "cite"
    with pytest.raises(ValueError):
        MassProperties.model_validate(data)


def test_inertia_result_round_trips_through_json_and_is_deterministic():
    p = part([box("b", 0.2, 0.1, 0.3), cyl("c", 0.05, 0.2, at=(0.0, 0.0, 0.25))])
    a = mass_properties(p, material())
    b = mass_properties(p, material())
    assert a == b
    assert MassProperties.model_validate_json(a.model_dump_json()) == a


# --- numerical robustness (second review) ----------------------------------------------------------------------------


def _unit_quaternion(axis, angle, noise=0.0):
    n = math.sqrt(sum(a * a for a in axis))
    s = math.sin(angle / 2) / n
    q = [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(angle / 2) + noise]
    k = math.sqrt(sum(v * v for v in q))
    return {"x": q[0] / k, "y": q[1] / k, "z": q[2] / k, "w": q[3] / k}


@pytest.mark.parametrize("seed", range(40))
def test_inertia_coaxial_tube_with_a_noisy_non_trivial_orientation_is_accepted(seed):
    # A bore whose end faces are flush with the cylinder's, both rotated by the same non-trivial quaternion (some with 1e-16
    # noise before normalising). Testing the bore's end-cap support asks the cylinder for its extent along its own axis,
    # t = axis . axis = 1 - O(1e-16); sqrt(1 - t^2) there is off by ~1e-8 and rejected 10 % of these tubes.
    rng = random.Random(seed)
    quat = _unit_quaternion([rng.gauss(0, 1) for _ in range(3)], rng.uniform(0.0, 6.28), rng.choice([0.0, 1e-16]))
    p = part([cyl("outer", 1.0, 2.0, quat=quat), cyl("bore", 0.9, 2.0, op="subtract", quat=quat)])
    r = mass_properties(p, material())
    assert r.mass.value == approx(RHO * math.pi * (1.0 - 0.81) * 2.0)


def test_inertia_parallel_axis_tiny_perpendicular_offset_along_a_long_one_is_exact():
    # Two 1 mm cubes, 1000 m apart along x and 1e-6 m apart along y. The offsets from the centre of mass are +-500 m in x and
    # +-5e-7 m in y, so Ixx = 2 [m_c (a^2 + a^2) / 12 + m_c (5e-7)^2] and the |d|^2 - d_x^2 form would cancel to noise.
    a = 1e-3
    mc = RHO * a**3
    p = part([box("p", a, a, a, at=(-500.0, -5e-7, 0.0)), box("q", a, a, a, at=(500.0, 5e-7, 0.0))])
    r = mass_properties(p, material())
    want = 2 * (mc * (2 * a * a) / 12 + mc * (5e-7) ** 2)
    assert r.inertia.ixx == pytest.approx(want, rel=1e-9, abs=0)
    assert r.inertia.iyy == pytest.approx(2 * (mc * (2 * a * a) / 12 + mc * 500.0**2), rel=1e-9, abs=0)


def test_inertia_void_protruding_by_the_tolerance_gives_a_rejection_or_a_physical_tensor():
    # The void is 2e-9 m too long in x on both sides of a 1 m block: inside the geometric tolerance, flush in effect.
    for dz in (0.999, 0.5, 1e-3):
        p = part([box("a", 1.0, 1.0, 1.0), box("v", 1.0 + 2e-9, 1.0 + 2e-9, dz, op="subtract")])
        try:
            r = mass_properties(p, material())
        except ShapeError:
            continue
        i = r.inertia
        assert r.mass.value > 0 and i.ixx >= 0 and i.iyy >= 0 and i.izz >= 0
        assert i.ixx + i.iyy >= i.izz * (1 - 1e-9) and i.iyy + i.izz >= i.ixx * (1 - 1e-9) and i.ixx + i.izz >= i.iyy * (1 - 1e-9)


def test_inertia_non_physical_tensors_are_rejected():
    from kinetra_engine.parts.mass import _check_physical

    _check_physical(1.0, (1.0, 1.0, 1.0, 0.0, 0.0, 0.0))
    _check_physical(1.0, (2.0, 3.0, 4.0, 0.5, 0.0, 0.0))
    with pytest.raises(ShapeError, match="not physical"):
        _check_physical(1.0, (-1.0, 1.0, 1.0, 0.0, 0.0, 0.0))  # negative moment
    with pytest.raises(ShapeError, match="not physical"):
        _check_physical(1.0, (1.0, 1.0, 5.0, 0.0, 0.0, 0.0))  # 1 + 1 < 5
    with pytest.raises(ShapeError, match="not physical"):
        _check_physical(1.0, (1.0, 1.0, 1.0, 2.0, 0.0, 0.0))  # product term larger than the moments: eigenvalue -1
    with pytest.raises(ShapeError, match="not finite and positive"):
        _check_physical(0.0, (1.0, 1.0, 1.0, 0.0, 0.0, 0.0))


# --- review 3: parameter overrides, forged derivations, mutation guards -----------------------------------------------


def test_inertia_instance_parameter_values_round_trip_through_json():
    # `Instance.parameters` entries are ParamValue (a Quantity with a `name`); the result must hold a plain Quantity.
    from kinetra_core import ParamValue

    p = param_part()
    pv = ParamValue.model_validate({"name": "w", **q(0.4)})
    r = mass_properties(p, material(), {"w": pv})
    assert type(r.derivation.parameters[0].value) is Quantity
    assert MassProperties.model_validate_json(r.model_dump_json()) == r
    assert r.derivation.parameters[0].value == Quantity.model_validate(q(0.4))


def test_inertia_result_is_hashable_and_has_no_mutable_containers():
    r = mass_properties(part([box("b", 0.2, 0.1, 0.3)]), material())
    assert isinstance(hash(r), int) and {r: 1}[r] == 1
    assert hash(r) == hash(mass_properties(part([box("b", 0.2, 0.1, 0.3)]), material()))


def _dump(r):
    return r.model_dump(mode="json")


def test_derivation_rejects_forged_input_badges():
    p = part([box("b", 0.2, 0.1, 0.3)])
    r = mass_properties(p, material(1000.0, "estimate", {"ref": "a guess"}))
    assert r.derivation.input_badges == (Badge.DECLARED, Badge.ESTIMATE)
    for forged in (["cite"], ["declared"], ["estimate", "declared"], [], ["declared", "estimate", "cite"]):
        d = _dump(r)
        d["derivation"]["input_badges"] = forged
        with pytest.raises(ValueError, match="input_badges must be"):
            MassProperties.model_validate(d)
    d = _dump(r)
    d["derivation"]["density"]["badge"] = "declared"  # the density's own badge changed, the list is now stale
    d["derivation"]["density"]["source"] = SRC
    with pytest.raises(ValueError, match="input_badges must be"):
        MassProperties.model_validate(d)
    MassProperties.model_validate(_dump(r))


@pytest.mark.parametrize(
    "primitive,names",
    [
        ("box", ["radius", "length"]),
        ("box", ["size_x", "size_y"]),
        ("box", ["size_y", "size_x", "size_z"]),
        ("cylinder", ["size_x", "size_y", "size_z"]),
        ("cylinder", ["radius"]),
        ("sphere", ["radius", "length"]),
        ("sphere", ["diameter"]),
    ],
)
def test_derivation_rejects_dimension_keys_that_do_not_fit_the_primitive(primitive, names):
    r = mass_properties(part([box("b", 0.2, 0.1, 0.3)]), material())
    d = _dump(r)
    c = d["derivation"]["components"][0]
    c["primitive"] = primitive
    c["dimensions"] = [{"name": n, "value": 1.0} for n in names]
    with pytest.raises(ValueError, match="has dimensions"):
        MassProperties.model_validate(d)


def test_inertia_ixy_sign_matches_hand_calculation():
    # Unit-mass-ish cubes (0.1 m, 1 kg each) at (0, 0) and (0.2, 0.1): centre of mass (0.1, 0.05), offsets +-(0.1, 0.05).
    # ixy = -sum m dx dy = -(0.1 * 0.05 + 0.1 * 0.05) = -0.01 (the cubes' own products are zero).
    r = mass_properties(part([box("a", 0.1, 0.1, 0.1), box("b", 0.1, 0.1, 0.1, at=(0.2, 0.1, 0.0))]), material())
    assert r.mass.value == approx(2.0)
    assert r.inertia.ixy == approx(-0.01)
    assert abs(r.inertia.ixz) < 1e-15 and abs(r.inertia.iyz) < 1e-15
    # Mirror the second cube in y: the sign flips.
    r2 = mass_properties(part([box("a", 0.1, 0.1, 0.1), box("b", 0.1, 0.1, 0.1, at=(0.2, -0.1, 0.0))]), material())
    assert r2.inertia.ixy == approx(0.01)


def test_inertia_iyz_of_a_box_turned_45_degrees_about_x_matches_hand_calculation():
    # 0.1 x 0.2 x 0.4 box, m = 8 kg. Own diagonal: Iyy' = 8 (0.01 + 0.16) / 12, Izz' = 8 (0.01 + 0.04) / 12. Turned +45 degrees about
    # x, iyz = sin cos (Iyy' - Izz') = 0.5 (0.113333 - 0.033333) = 0.04, positive: the long axis leans toward (-y, +z), and
    # ixx = (Iyy' + Izz') / 2 + ... is not needed here. The other products vanish.
    q45 = {"x": math.sin(math.pi / 8), "y": 0.0, "z": 0.0, "w": math.cos(math.pi / 8)}
    r = mass_properties(part([box("b", 0.1, 0.2, 0.4, quat=q45)]), material())
    assert r.inertia.iyz == approx(0.04)
    assert abs(r.inertia.ixy) < 1e-15 and abs(r.inertia.ixz) < 1e-15
    mirrored = {"x": -q45["x"], "y": 0.0, "z": 0.0, "w": q45["w"]}
    assert mass_properties(part([box("b", 0.1, 0.2, 0.4, quat=mirrored)]), material()).inertia.iyz == approx(-0.04)


def test_overlap_bodies_use_the_forward_rotation_not_its_inverse():
    # A 1.0 x 0.1 x 0.1 bar turned +30 degrees about z leans toward +y at +x. A cube at (0.4, 0.2309, 0) sits on that bar and
    # clear of the bar turned -30 degrees, so +30 must be rejected and -30 accepted. The inverse rotation swaps the two.
    s, c = math.sin(math.pi / 12), math.cos(math.pi / 12)
    cube = box("cube", 0.05, 0.05, 0.05, at=(0.4, 0.4 * math.tan(math.pi / 6), 0.0))
    plus = box("bar", 1.0, 0.1, 0.1, quat={"x": 0.0, "y": 0.0, "z": s, "w": c})
    minus = box("bar", 1.0, 0.1, 0.1, quat={"x": 0.0, "y": 0.0, "z": -s, "w": c})
    with pytest.raises(ShapeError, match="overlap"):
        mass_properties(part([plus, cube]), material())
    assert mass_properties(part([minus, cube]), material()).mass.value == approx(RHO * (0.01 + 0.05**3))
    # The same for voids: a cube void inside the +30 bar is contained, and not contained in the -30 bar.
    hole = box("hole", 0.04, 0.04, 0.04, at=(0.4, 0.4 * math.tan(math.pi / 6), 0.0), op="subtract")
    assert mass_properties(part([plus, hole]), material()).mass.value == approx(RHO * (0.01 - 0.04**3))
    with pytest.raises(ShapeError, match="not inside"):
        mass_properties(part([minus, hole]), material())


def test_inertia_a_void_that_leaves_a_sliver_is_rejected_as_not_physical():
    # The void pokes 5e-10 m out of the top, inside the geometric tolerance, and leaves a 1e-9 m slab of material: the
    # volume is positive but the tensor is not that of any body.
    p = part([box("a", 1.0, 1.0, 1.0), box("v", 1.0, 1.0, 0.999999999, at=(0.0, 0.0, 1e-9), op="subtract")])
    with pytest.raises(ShapeError, match="not physical"):
        mass_properties(p, material())
