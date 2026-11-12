"""X-01a: body tree, fixed joints, MJCF through the real MuJoCo loader, proxy approximation labels, canonical order (#511).

Expected numbers are written out by hand from textbook formulas, not read back from the code under test; MuJoCo is the
independent reader of the MJCF. Dimensions, densities and poses are fixtures declared by the test (`사용자 선언`), not part data.
"""

from __future__ import annotations

import itertools
import math
import random
from pathlib import Path

import mujoco
import numpy as np
import pytest

from kinetra_core import Material, PartDef, Project, canonical_order, project_hash
from kinetra_engine.compiler import CompileError, build_body_tree, proxy_labels, to_mjcf
from kinetra_engine.parts import PartCache, assembly_mass, collision_proxy, mass_properties

SRC = {"ref": "X-01a test fixture: value chosen by the test", "locator": "test_body_tree.py"}
RHO = 1000.0
S2 = math.sqrt(0.5)
ROT_X90 = {"x": S2, "y": 0.0, "z": 0.0, "w": S2}
ROT_Z90 = {"x": 0.0, "y": 0.0, "z": S2, "w": S2}
IDENT = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
EXAMPLES = Path(__file__).parents[3] / "schemas" / "examples"


def q(value, unit="m"):
    return {"value": value, "unit": unit, "badge": "declared", "source": SRC}


def ax(offset=0.0):
    return {"offset": offset, "terms": []}


def pos(x=0.0, y=0.0, z=0.0):
    return {"x": ax(x), "y": ax(y), "z": ax(z)}


def box(id, sx, sy, sz, at=(0, 0, 0), op="add", quat=None):
    return {"id": id, "operation": op, "primitive": {"kind": "box", "size_x": ax(sx), "size_y": ax(sy), "size_z": ax(sz)},
            "position": pos(*at), **({"orientation": quat} if quat else {})}


def cyl(id, radius, length, at=(0, 0, 0), op="add", quat=None):
    return {"id": id, "operation": op, "primitive": {"kind": "cylinder", "radius": ax(radius), "length": ax(length)},
            "position": pos(*at), **({"orientation": quat} if quat else {})}


def sphere(id, radius, at=(0, 0, 0), op="add"):
    return {"id": id, "operation": op, "primitive": {"kind": "sphere", "radius": ax(radius)}, "position": pos(*at)}


def snap(id, at=(0, 0, 0), quat=None):
    return {"id": id, "kind": "plug", "accepts": ["plug"], "badge": "declared", "source": SRC, "position": pos(*at), "orientation": quat or IDENT}


def part(id, components, snaps=None):
    return {"id": id, "name": id, "parameters": [], "snap_points": snaps if snaps is not None else [snap("s1"), snap("s2"), snap("s3")],
            "shape": {"badge": "declared", "source": SRC, "components": components}}


def instance(id, part, at=(0, 0, 0), quat=None, material="mat"):
    return {"id": id, "part": part, "material": material,
            "pose": {"badge": "declared", "source": SRC, "position": {"x": at[0], "y": at[1], "z": at[2]}, "orientation": quat or IDENT}}


def joint(id, kind, a, b, axis=None, limits=None):
    j = {"id": id, "kind": kind, "a": {"instance": a[0], "snap_point": a[1]}, "b": {"instance": b[0], "snap_point": b[1]}}
    if axis is not None:
        j["axis"] = {"x": axis[0], "y": axis[1], "z": axis[2], "badge": "declared", "source": SRC}
    if limits is not None:
        unit = "rad" if kind == "hinge" else "m"
        j["limits"] = {"lower": q(limits[0], unit), "upper": q(limits[1], unit)}
    return j


MATERIAL = {"id": "mat", "name": "Test material", "density": q(RHO, "kg/m^3"), "yield_strength": q(1.0e7, "Pa"),
            "elastic_modulus": q(1.0e9, "Pa"), "friction": q(0.5, "1")}


def project(parts, instances, joints=()):
    return Project.model_validate({"design": {"materials": [MATERIAL], "parts": list(parts), "instances": list(instances), "joints": list(joints)},
                                   "world": {"planet": "earth"}})


def mj(tree):
    return mujoco.MjModel.from_xml_string(to_mjcf(tree))


def body_row(model, name):
    return mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)


def rotation_matrix(quat):
    return np.array(
        [[1 - 2 * (quat["y"] ** 2 + quat["z"] ** 2), 2 * (quat["x"] * quat["y"] - quat["z"] * quat["w"]), 2 * (quat["x"] * quat["z"] + quat["y"] * quat["w"])],
         [2 * (quat["x"] * quat["y"] + quat["z"] * quat["w"]), 1 - 2 * (quat["x"] ** 2 + quat["z"] ** 2), 2 * (quat["y"] * quat["z"] - quat["x"] * quat["w"])],
         [2 * (quat["x"] * quat["z"] - quat["y"] * quat["w"]), 2 * (quat["y"] * quat["z"] + quat["x"] * quat["w"]), 1 - 2 * (quat["x"] ** 2 + quat["y"] ** 2)]]
    )


# --- three parts, welded and hinged: mass and centre of mass are the sums ------------------------------------------------

BLOCK = part("block", [box("b", 0.2, 0.1, 0.3, at=(0.1, 0.0, 0.15))])  # 6 kg, centre (0.1, 0, 0.15)
BALL = part("ball", [sphere("s", 0.1, at=(0.1, 0.0, 0.0))])  # 4/3 pi 1e-3 * 1000 kg, centre (0.1, 0, 0)
ROD = part("rod", [cyl("c", 0.05, 0.4)])  # pi 0.0025 0.4 * 1000 kg, centre at the origin
M_BLOCK, M_BALL, M_ROD = 6.0, 4.0 / 3.0 * math.pi * 1e-3 * RHO, math.pi * 0.0025 * 0.4 * RHO


def chain(order=1):
    """block (1, 0, 0) welded to ball (0, 2, 0) turned 90 deg about z, a rod (3, 1, 1) on a hinge about +y of the ball's snap s2."""
    instances = [instance("blk", "block", (1, 0, 0)), instance("ball", "ball", (0, 2, 0), ROT_Z90), instance("rod", "rod", (3, 1, 1))]
    joints = [joint("weld", "fixed", ("blk", "s1"), ("ball", "s1")),
              joint("hinge", "hinge", ("ball", "s2"), ("rod", "s1"), axis=(0, 1, 0), limits=(-1.0, 2.0))]
    return project([BLOCK, BALL, ROD], instances[::order], joints[::order])


def test_body_tree_welded_instances_are_one_body_with_the_summed_mass_and_centre():
    tree = build_body_tree(chain())
    assert [b.id for b in tree.bodies] == ["ball", "rod"]  # blk and ball welded; the group is named by its smallest id
    assert tree.body("ball").instances == ("ball", "blk")
    assert tree.root.joint is None and tree.body("rod").parent == "ball" and tree.body("rod").joint.id == "hinge"
    welded = tree.body("ball")
    assert welded.mass == pytest.approx(M_BLOCK + M_BALL, rel=1e-12)
    # world centre of the welded body by hand: block (1, 0, 0) + (0.1, 0, 0.15); ball (0, 2, 0) + Rz90 (0.1, 0, 0) = (0, 2.1, 0)
    hand_world = (M_BLOCK * np.array([1.1, 0.0, 0.15]) + M_BALL * np.array([0.0, 2.1, 0.0])) / (M_BLOCK + M_BALL)
    # the body frame is the ball's: position (0, 2, 0), turned 90 deg about z
    r = rotation_matrix(ROT_Z90)
    assert np.array(welded.pos) == pytest.approx([0.0, 2.0, 0.0], abs=1e-15)
    assert np.array(welded.pos) + r @ np.array(welded.com) == pytest.approx(hand_world, rel=1e-12)


def test_body_tree_total_mass_and_centre_of_mass_match_the_sum_in_mujoco():
    tree = build_body_tree(chain())
    model = mj(tree)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    total = M_BLOCK + M_BALL + M_ROD
    assert model.body_subtreemass[0] == pytest.approx(total, rel=1e-12)  # MuJoCo's own sum over the loaded bodies
    assert float(model.body_mass.sum()) == pytest.approx(total, rel=1e-12)
    hand = (M_BLOCK * np.array([1.1, 0.0, 0.15]) + M_BALL * np.array([0.0, 2.1, 0.0]) + M_ROD * np.array([3.0, 1.0, 1.0])) / total
    assert data.subtree_com[0] == pytest.approx(hand, rel=1e-12)
    # and the core's own sum over MassProperties, instance by instance
    assert sum(i.properties.mass.value for i in tree.instances) == pytest.approx(total, rel=1e-12)


def test_body_tree_inertia_of_the_welded_body_is_the_parallel_axis_sum():
    tree = build_body_tree(chain())
    model = mj(tree)
    welded = body_row(model, "ball")
    # about the welded body's own centre of mass, in world axes, by hand (diagonal textbook tensors + parallel axis)
    block = np.diag([M_BLOCK / 12 * (0.1**2 + 0.3**2), M_BLOCK / 12 * (0.2**2 + 0.3**2), M_BLOCK / 12 * (0.2**2 + 0.1**2)])
    ball = np.eye(3) * 0.4 * M_BALL * 0.1**2
    c = (M_BLOCK * np.array([1.1, 0.0, 0.15]) + M_BALL * np.array([0.0, 2.1, 0.0])) / (M_BLOCK + M_BALL)
    total = np.zeros((3, 3))
    for m, i_c, p in ((M_BLOCK, block, np.array([1.1, 0.0, 0.15])), (M_BALL, ball, np.array([0.0, 2.1, 0.0]))):
        d = p - c
        total += i_c + m * (d @ d * np.eye(3) - np.outer(d, d))
    assert sorted(model.body_inertia[welded]) == pytest.approx(sorted(np.linalg.eigvalsh(total)), rel=1e-9)
    assert model.body_mass[welded] == pytest.approx(M_BLOCK + M_BALL, rel=1e-12)


def test_body_tree_parallel_axis_keeps_a_small_perpendicular_offset_along_a_long_one():
    # two equal small balls welded 1e4 m apart along x and 1e-3 m apart along y. About their common centre each is
    # (+-5e3, +-5e-4, 0) away: Ixx gets 2 m (5e-4)^2, which |d|^2 - dx^2 (|d|^2 ~ 2.5e7) would round away entirely.
    L, h, r = 1.0e4, 1.0e-3, 0.01
    parts = [part("ball", [sphere("s", r)])]
    instances = [instance("p", "ball", (0, 0, 0)), instance("q", "ball", (L, h, 0))]
    tree = build_body_tree(project(parts, instances, [joint("w", "fixed", ("p", "s1"), ("q", "s1"))]))
    (body,) = tree.bodies
    m = tree.instances[0].properties.mass.value
    own = 0.4 * m * r * r
    hand = (2 * own + 2 * m * (h / 2) ** 2, 2 * own + 2 * m * (L / 2) ** 2, 2 * own + 2 * m * ((L / 2) ** 2 + (h / 2) ** 2))
    assert body.inertia[:3] == pytest.approx(hand, rel=1e-9)
    assert body.inertia[0] - 2 * own == pytest.approx(2 * m * (h / 2) ** 2, rel=1e-6)  # the small term itself survives
    assert body.inertia[3] == pytest.approx(-2 * m * (L / 2) * (h / 2), rel=1e-9)  # ixy = -sum m dx dy


def test_body_tree_hinge_axis_pos_and_limits_in_the_world():
    tree = build_body_tree(chain())
    model = mj(tree)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "hinge")
    # axis +y of the snap point s2 of `ball` (turned 90 deg about z): +y maps to -x in the world
    assert data.xaxis[j] == pytest.approx([-1.0, 0.0, 0.0], abs=1e-12)
    assert data.xanchor[j] == pytest.approx([0.0, 2.0, 0.0], abs=1e-12)  # the snap point sits at the ball's origin
    assert model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE and bool(model.jnt_limited[j])
    assert list(model.jnt_range[j]) == [-1.0, 2.0]
    assert model.nq == 7 + 1 and model.nv == 6 + 1  # a free root and one hinge


def test_body_tree_a_joint_met_from_its_b_side_is_reversed_with_its_limits():
    # B is the b side of both joints; the root is the smaller of the a sides (A), and C hangs from B through j2 backwards.
    parts = [part("blk", [box("b", 0.1, 0.1, 0.1)])]
    instances = [instance("a", "blk", (0, 0, 0)), instance("b", "blk", (1, 0, 0)), instance("c", "blk", (2, 0, 0))]
    joints = [joint("j1", "hinge", ("a", "s1"), ("b", "s1"), axis=(0, 0, 1), limits=(-0.5, 1.0)),
              joint("j2", "slider", ("c", "s1"), ("b", "s2"), axis=(1, 0, 0), limits=(-0.25, 0.75))]
    tree = build_body_tree(project(parts, instances, joints))
    assert [b.id for b in tree.bodies] == ["a", "b", "c"] and tree.body("c").parent == "b"
    assert tree.body("c").joint.reversed and not tree.body("b").joint.reversed
    model = mj(tree)
    data = mujoco.MjData(model)
    j2 = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "j2")
    assert model.jnt_type[j2] == mujoco.mjtJoint.mjJNT_SLIDE
    assert list(model.jnt_range[j2]) == [-0.25, 0.75]  # the joint's own coordinate and limits: only the axis flips
    mujoco.mj_forward(model, data)
    assert data.xaxis[j2] == pytest.approx([-1.0, 0.0, 0.0], abs=1e-12)
    # world motion: the project's coordinate q moves b by q along +x relative to c, so c moves by -q relative to b (fixed here)
    for q_ in (-0.25, 0.0, 0.5, 0.75):
        data.qpos[:] = model.qpos0
        data.qpos[model.jnt_qposadr[j2]] = q_
        mujoco.mj_forward(model, data)
        b, c = body_row(model, "b"), body_row(model, "c")
        assert data.xpos[b][0] - data.xpos[c][0] == pytest.approx(-1.0 + q_, abs=1e-12)  # b - c along the axis: rest + q


def hinge_pair(reverse):
    """c and b, a hinge with `a` = c, `b` = b, axis +z of c's snap, limits [-0.5, 1.0]. `reverse`: b is also the `b` side of a
    hinge `h0` from `a0` (the smallest id), so the root is `a0`, the tree reaches b through `h0` and meets `h` from its `b` side."""
    parts = [part("blk", [box("b", 0.1, 0.1, 0.1)])]
    instances = [instance("c", "blk", (0, 0, 0)), instance("b", "blk", (1, 0, 0))]
    joints = [joint("h", "hinge", ("c", "s1"), ("b", "s1"), axis=(0, 0, 1), limits=(-0.5, 1.0))]
    if reverse:
        instances.append(instance("a0", "blk", (1, 1, 0)))
        joints.append(joint("h0", "hinge", ("a0", "s1"), ("b", "s2"), axis=(1, 0, 0)))
    return build_body_tree(project(parts, instances, joints))


def test_body_tree_a_hinge_met_from_either_side_gives_the_same_relative_motion_over_the_same_range():
    forward, backward = hinge_pair(False), hinge_pair(True)
    assert not forward.body("b").joint.reversed
    assert backward.root.id == "a0" and backward.body("c").joint.reversed
    for tree in (forward, backward):
        model = mj(tree)
        data = mujoco.MjData(model)
        h = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "h")
        assert list(model.jnt_range[h]) == [-0.5, 1.0]
        for q_ in (-0.5, 0.0, 0.3, 1.0):
            data.qpos[:] = model.qpos0
            data.qpos[model.jnt_qposadr[h]] = q_
            mujoco.mj_forward(model, data)
            rc = data.xmat[body_row(model, "c")].reshape(3, 3)
            rb = data.xmat[body_row(model, "b")].reshape(3, 3)
            rel = rc.T @ rb  # b relative to c: Joint.displacement(q), a right-handed turn by q about +z
            hand = np.array([[math.cos(q_), -math.sin(q_), 0], [math.sin(q_), math.cos(q_), 0], [0, 0, 1]])
            assert rel == pytest.approx(hand, abs=1e-12)
            # b's origin turns about the hinge point (c's snap s1, c's origin) by q
            p = rc.T @ (data.xpos[body_row(model, "b")] - data.xpos[body_row(model, "c")])
            assert p == pytest.approx([math.cos(q_), math.sin(q_), 0.0], abs=1e-12)


def test_body_tree_root_free_joint_name_cannot_collide_with_a_project_joint():
    parts = [part("blk", [box("b", 0.1, 0.1, 0.1)])]
    instances = [instance("a", "blk", (0, 0, 0)), instance("b", "blk", (1, 0, 0))]
    joints = [joint("free-a", "hinge", ("a", "s1"), ("b", "s1"))]  # a legal joint id, the name the root once had
    model = mj(build_body_tree(project(parts, instances, joints)))
    names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, k) for k in range(model.njnt)]
    assert names == ["__kinetra_root_a", "free-a"]
    assert model.jnt_type[0] == mujoco.mjtJoint.mjJNT_FREE


# --- MuJoCo geom mapping: half extents, radius and half length, w x y z ----------------------------------------------------


def one(components, at=(0, 0, 0), quat=None):
    return build_body_tree(project([part("p", components)], [instance("i", "p", at, quat)]))


def test_body_tree_box_proxy_maps_to_half_extents_mass_and_volume():
    tree = one([box("b", 0.2, 0.1, 0.3, at=(0.1, 0.0, 0.15))])
    model = mj(tree)
    assert model.ngeom == 1 and model.geom_type[0] == mujoco.mjtGeom.mjGEOM_BOX
    assert list(model.geom_size[0]) == pytest.approx([0.1, 0.05, 0.15], rel=1e-15)  # half of the full extents 0.2 0.1 0.3
    assert list(model.geom_pos[0]) == pytest.approx([0.1, 0.0, 0.15], rel=1e-15)
    volume = 8 * model.geom_size[0].prod()  # the box volume read back from MuJoCo's size
    assert volume == pytest.approx(0.2 * 0.1 * 0.3, rel=1e-12)
    assert model.body_mass[1] == pytest.approx(RHO * 0.006, rel=1e-12)
    assert tree.instances[0].properties.volume.value == pytest.approx(0.006, rel=1e-12)
    # inertia about the centre, textbook m (b^2 + c^2) / 12; MuJoCo sorts principal moments
    m = 6.0
    hand = sorted([m / 12 * (0.1**2 + 0.3**2), m / 12 * (0.2**2 + 0.3**2), m / 12 * (0.2**2 + 0.1**2)])
    assert sorted(model.body_inertia[1]) == pytest.approx(hand, rel=1e-9)


def test_body_tree_cylinder_proxy_maps_to_radius_half_length_and_wxyz_quaternion():
    tree = one([cyl("c", 0.05, 0.4, at=(0.0, 0.0, 0.2), quat=ROT_X90)])  # the axis (part z) turned onto -y
    model = mj(tree)
    assert model.geom_type[0] == mujoco.mjtGeom.mjGEOM_CYLINDER
    assert list(model.geom_size[0][:2]) == pytest.approx([0.05, 0.2], rel=1e-15)  # radius, half of the length 0.4
    assert list(model.geom_quat[0]) == pytest.approx([S2, S2, 0.0, 0.0], rel=1e-15)  # w x y z, the scalar first
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    axis = data.geom_xmat[0].reshape(3, 3)[:, 2]  # the geom's local z in the world: the cylinder's axis
    assert axis == pytest.approx([0.0, -1.0, 0.0], abs=1e-12)  # Rx(90): z -> -y
    assert math.pi * model.geom_size[0][0] ** 2 * 2 * model.geom_size[0][1] == pytest.approx(math.pi * 0.0025 * 0.4, rel=1e-12)
    m = RHO * math.pi * 0.0025 * 0.4
    assert model.body_mass[1] == pytest.approx(m, rel=1e-12)
    hand = sorted([m * (3 * 0.05**2 + 0.4**2) / 12, m * (3 * 0.05**2 + 0.4**2) / 12, m * 0.05**2 / 2])
    assert sorted(model.body_inertia[1]) == pytest.approx(hand, rel=1e-9)


def test_body_tree_sphere_proxy_maps_to_its_radius_and_the_instance_pose_composes():
    tree = one([sphere("s", 0.1, at=(0.1, 0.0, 0.0))], at=(1.0, 2.0, 3.0), quat=ROT_Z90)
    model = mj(tree)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert model.geom_type[0] == mujoco.mjtGeom.mjGEOM_SPHERE and model.geom_size[0][0] == pytest.approx(0.1, rel=1e-15)
    assert 4 / 3 * math.pi * model.geom_size[0][0] ** 3 == pytest.approx(4 / 3 * math.pi * 1e-3, rel=1e-12)
    assert model.body_mass[1] == pytest.approx(RHO * 4 / 3 * math.pi * 1e-3, rel=1e-12)
    assert list(data.geom_xpos[0]) == pytest.approx([1.0, 2.1, 3.0], abs=1e-12)  # (0.1, 0, 0) turned onto +y, then moved
    assert list(data.xipos[1]) == pytest.approx([1.0, 2.1, 3.0], abs=1e-12)  # the inertial frame is MassProperties' centre
    assert model.body_mass[1] == pytest.approx(RHO * (4 / 3) * math.pi * 0.1**3, rel=1e-12)


def test_body_tree_mass_and_inertia_come_from_mass_properties_not_from_the_proxy():
    # a blind pocket is filled in the proxy (the proxy has MORE volume), the body mass is the recipe's (less)
    pocket = [box("plate", 0.3, 0.2, 0.02), cyl("pocket", 0.05, 0.01, at=(0.05, 0.0, 0.005), op="subtract")]
    tree = one(pocket)
    model = mj(tree)
    recipe = 0.3 * 0.2 * 0.02 - math.pi * 0.05**2 * 0.01
    assert model.body_mass[1] == pytest.approx(RHO * recipe, rel=1e-12)
    assert model.body_mass[1] < RHO * 0.3 * 0.2 * 0.02  # not the filled proxy's mass
    assert list(model.geom_size[0]) == pytest.approx([0.15, 0.1, 0.01], rel=1e-15)  # one box: the pocket is not a geom
    c = tree.instances[0].properties.center_of_mass
    assert list(model.body_ipos[1]) == pytest.approx([c.x, c.y, c.z], rel=1e-12)
    assert c.x < 0.0  # the pocket on +x moves the centre of mass towards -x: the inertial frame is not the box's centre


# --- approximation labels --------------------------------------------------------------------------------------------------

TUBE = [cyl("outer", 0.05, 0.5), cyl("bore", 0.04, 0.5, op="subtract")]
PLATE_HOLE = [box("plate", 0.3, 0.2, 0.02), cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract")]
POCKET = [box("plate", 0.3, 0.2, 0.02), cyl("pocket", 0.05, 0.01, at=(0.05, 0.0, 0.005), op="subtract")]


def labelled(components, tolerance=None):
    return proxy_labels(build_body_tree(project([part("p", components)], [instance("i", "p")]), tolerance=tolerance))


def test_body_tree_label_tube_and_holed_plate_are_decomposed_with_the_hosts_signed_error():
    for components, host in ((TUBE, "outer"), (PLATE_HOLE, "plate")):
        (label,) = labelled(components)
        proxy = collision_proxy(part_def(components))
        (void,) = proxy.decomposed_voids
        assert void.error < 0.0 and abs(void.error) <= 0.10
        n = f"{100 * void.error:.3g}"
        assert label.text == f"근사: 충돌 프록시가 빈 곳을 상자 조각으로 근사함(오차 {n}%, 허용 오차 10%, 기본값)"
        assert (label.kind, label.host, label.instance, label.part) == ("decomposed", host, "i", "p")
        assert label.percent == pytest.approx(100 * void.error, rel=1e-12)


def part_def(components):
    return PartDef.model_validate(part("p", components))


def test_body_tree_label_decomposed_tolerance_badge_default_suffix_only_when_default():
    (default,) = labelled(TUBE)
    (declared,) = labelled(TUBE, tolerance=0.05)
    assert default.text.endswith("허용 오차 10%, 기본값)")
    assert declared.text.endswith("허용 오차 5%)") and "기본값" not in declared.text
    assert declared.percent != default.percent  # a tighter tolerance needs more boxes and a smaller error


def test_body_tree_label_blind_pocket_is_filled_with_the_plus_percent_of_the_recipe_volume():
    (label,) = labelled(POCKET)
    pocket = math.pi * 0.05**2 * 0.01
    recipe = 0.3 * 0.2 * 0.02 - pocket
    hand = 100 * pocket / recipe  # about 7.0 %
    assert label.kind == "filled" and label.host is None
    assert label.percent == pytest.approx(hand, rel=1e-9)
    assert label.text == f"근사: 충돌 프록시가 빈 곳을 메움(+{hand:.3g}%)"
    assert "+7%" in label.text


MIXED = [
    box("slab", 0.3, 0.2, 0.02, at=(0.0, 0.0, 0.0)),
    cyl("hole", 0.05, 0.02, at=(0.05, 0.0, 0.0), op="subtract"),  # through the slab: decomposed (about -2.5 %)
    box("block", 0.1, 0.1, 0.1, at=(1.0, 0.0, 0.0)),
    sphere("dent", 0.01, at=(1.0, 0.0, 0.03), op="subtract"),  # a sphere cannot be decomposed: filled
]


def test_body_tree_label_mixed_part_keeps_both_labels_while_the_total_volume_error_is_negative():
    proxy = collision_proxy(part_def(MIXED))
    assert proxy.volume_error.value < 0.0 and proxy.filled_voids and proxy.decomposed_voids  # the filled volume is netted out
    labels = labelled(MIXED)
    assert [l.kind for l in labels] == ["filled", "decomposed"]
    dent = 4 / 3 * math.pi * 0.01**3
    recipe = 0.3 * 0.2 * 0.02 - math.pi * 0.05**2 * 0.02 + 0.1**3 - dent
    n = 100 * dent / recipe
    assert n > 0 and labels[0].text == f"근사: 충돌 프록시가 빈 곳을 메움(+{n:.3g}%)"  # (a) is the filled volume over recipe_volume, positive
    assert labels[0].percent == pytest.approx(n, rel=1e-9)
    assert labels[1].host == "slab" and labels[1].percent == pytest.approx(100 * proxy.decomposed_voids[0].error, rel=1e-12)
    assert labels[1].percent < 0.0 and labels[1].text.startswith("근사: 충돌 프록시가 빈 곳을 상자 조각으로 근사함(오차 -")
    assert labels[0].percent != pytest.approx(100 * proxy.volume_error.value)  # not the netted-out total


def test_body_tree_label_a_design_without_voids_has_none_and_two_instances_label_separately():
    assert labelled([box("b", 0.1, 0.1, 0.1), sphere("s", 0.05, at=(0.5, 0.0, 0.0))]) == ()
    parts = [part("tube", TUBE), part("pocket", POCKET), part("solid", [box("b", 0.1, 0.1, 0.1)])]
    instances = [instance("i-tube", "tube", (0, 0, 0)), instance("i-pocket", "pocket", (1, 0, 0)), instance("i-solid", "solid", (2, 0, 0))]
    joints = [joint("w1", "fixed", ("i-tube", "s1"), ("i-pocket", "s1")), joint("w2", "fixed", ("i-pocket", "s2"), ("i-solid", "s1"))]
    labels = proxy_labels(build_body_tree(project(parts, instances, joints)))
    assert [(l.instance, l.kind) for l in labels] == [("i-pocket", "filled"), ("i-tube", "decomposed")]  # instance id order


# --- compile errors name the instances and joints --------------------------------------------------------------------------


def blocks(*names):
    return [part("blk", [box("b", 0.1, 0.1, 0.1)])], [instance(n, "blk", (float(k), 0, 0)) for k, n in enumerate(names)]


def test_body_tree_rejects_a_loop_of_fixed_joints_a_hinge_inside_a_weld_and_a_loop_of_bodies():
    parts, inst = blocks("a", "b", "c")
    loop = [joint("j1", "fixed", ("a", "s1"), ("b", "s1")), joint("j2", "fixed", ("b", "s2"), ("c", "s1")), joint("j3", "fixed", ("c", "s2"), ("a", "s2"))]
    with pytest.raises(CompileError, match="loop of fixed joints") as e:
        build_body_tree(project(parts, inst, loop))
    assert e.value.joints == ("j3",)
    inside = [joint("j1", "fixed", ("a", "s1"), ("b", "s1")), joint("j2", "hinge", ("a", "s2"), ("b", "s2")), joint("j3", "fixed", ("b", "s3"), ("c", "s1"))]
    with pytest.raises(CompileError, match="could not move") as e:
        build_body_tree(project(parts, inst, inside))
    assert e.value.joints == ("j2",) and set(e.value.instances) == {"a", "b"}
    ring = [joint("j1", "hinge", ("a", "s1"), ("b", "s1")), joint("j2", "hinge", ("b", "s2"), ("c", "s1")), joint("j3", "hinge", ("c", "s2"), ("a", "s2"))]
    with pytest.raises(CompileError, match="loop between bodies") as e:
        build_body_tree(project(parts, inst, ring))
    assert e.value.joints == ("j3",)


def test_body_tree_rejects_two_pieces_and_a_part_that_cannot_be_compiled():
    parts, inst = blocks("a", "b", "c")
    with pytest.raises(CompileError, match="not one piece") as e:
        build_body_tree(project(parts, inst, [joint("j1", "fixed", ("a", "s1"), ("b", "s1"))]))
    assert e.value.instances == ("a", "c")
    bad = [instance("a", "blk", material=None)]  # no material and no declared mass
    with pytest.raises(CompileError, match=r"instance 'a' \(part 'blk'\)") as e:
        build_body_tree(project(parts, bad))
    assert e.value.instances == ("a",) and e.value.parts == ("blk",)


# --- canonical order (#511) ------------------------------------------------------------------------------------------------

FIVE = [box("c0", 0.123456789, 0.1, 0.1), box("c1", 0.1, 0.0731, 0.1, at=(1, 0, 0)), cyl("c2", 0.0333333, 0.17, at=(2, 0, 0)),
        sphere("c3", 0.0777777, at=(3, 0, 0)), box("c4", 1e-3, 1e-3, 0.9, at=(4, 0, 0))]


def shuffled_chain(seed):
    """The same project as `chain_of_five`, every collection in the order of a seeded shuffle."""
    rng = random.Random(seed)
    comps = list(FIVE)
    rng.shuffle(comps)
    parts = [part("five", comps), BLOCK, BALL]
    rng.shuffle(parts)
    instances = [instance("i-five", "five", (0, 0, 0), ROT_Z90), instance("i-blk", "block", (1, 2, 3)), instance("i-ball", "ball", (0.5, 0.25, 0.125))]
    rng.shuffle(instances)
    joints = [joint("w1", "fixed", ("i-five", "s1"), ("i-blk", "s1")), joint("h1", "hinge", ("i-blk", "s2"), ("i-ball", "s1"), axis=(0, 0, 1), limits=(-1, 1))]
    rng.shuffle(joints)
    return project(parts, instances, joints)


def test_canonical_order_two_projects_with_one_project_hash_give_bit_identical_mjcf_and_mass_properties():
    base = shuffled_chain(0)
    others = [shuffled_chain(s) for s in range(1, 12)]
    assert any(o != base for o in others)  # the documents differ in order ...
    assert {project_hash(o) for o in others} == {project_hash(base)}  # ... and have one hash
    trees = [build_body_tree(p) for p in [base, *others]]
    assert len({to_mjcf(t) for t in trees}) == 1  # one MJCF text, byte for byte
    assert len({tuple(i.properties.model_dump_json() for i in t.instances) for t in trees}) == 1  # one MassProperties, bit for bit
    assert len({(b.id, b.mass, b.com, b.inertia, b.pos, b.quat) for t in trees for b in t.bodies}) == len(trees[0].bodies)


def test_canonical_order_the_recipe_order_is_what_changes_the_float_sum_without_it():
    # why the rule exists: read in file order, the five-component part has several bit patterns; read in canonical order, one
    orders = list(itertools.islice(itertools.permutations(FIVE), 0, 120, 7))
    direct = {mass_properties(PartDef.model_validate(part("five", list(o))), Material.model_validate(MATERIAL)).model_dump_json() for o in orders}
    ordered = {
        mass_properties(canonical_order(PartDef.model_validate(part("five", list(o)))), Material.model_validate(MATERIAL)).model_dump_json() for o in orders
    }
    assert len(direct) > 1 and len(ordered) == 1


def test_canonical_order_the_compiler_reads_instances_joints_and_geoms_in_id_order():
    tree = build_body_tree(shuffled_chain(3))
    assert [i.instance for i in tree.instances] == ["i-ball", "i-blk", "i-five"]
    assert [j.id for j in tree.joints] == ["h1", "w1"]
    assert [b.id for b in tree.bodies] == ["i-blk", "i-ball"]  # i-five and i-blk are welded: the body is named by the smaller id
    assert tree.body("i-blk").instances == ("i-blk", "i-five")
    owners = [g.instance for g in tree.body("i-blk").geoms]
    assert owners == sorted(owners)  # geoms: instance id order, then the proxy geoms
    five = [g.proxy_geom for g in tree.body("i-blk").geoms if g.instance == "i-five"]
    assert five == sorted(five) == ["c0", "c1", "c2", "c3", "c4"]  # the recipe components in id order, not the shuffled file order


def test_canonical_order_cache_serves_the_same_tree_as_no_cache():
    cache = PartCache(max_entries=16)
    a = to_mjcf(build_body_tree(shuffled_chain(5), cache=cache))
    b = to_mjcf(build_body_tree(shuffled_chain(6), cache=cache))
    assert a == b == to_mjcf(build_body_tree(shuffled_chain(7)))
    assert cache.stats().hits > 0


# --- the committed example --------------------------------------------------------------------------------------------------


def test_body_tree_structural_skeleton_total_mass_equals_assembly_mass():
    project_ = Project.model_validate_json((EXAMPLES / "Project.structural-skeleton.json").read_text(encoding="utf-8"))
    tree = build_body_tree(project_)
    model = mj(tree)
    total = assembly_mass(project_.design).total.value
    assert float(model.body_mass.sum()) == pytest.approx(total, rel=1e-12)
    assert sum(b.mass for b in tree.bodies) == pytest.approx(total, rel=1e-12)
    assert model.body_subtreemass[0] == pytest.approx(total, rel=1e-12)
