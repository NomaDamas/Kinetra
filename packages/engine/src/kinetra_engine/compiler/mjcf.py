"""MJCF of a body tree (X-01a): the engine's model, an artifact. The Project JSON stays the original.

    to_mjcf(tree, name="kinetra") -> str

Mapping (`docs/architecture/collision-proxy.md`, "MuJoCo 매핑"; the values do not pass through unchanged):

| body tree | MJCF |
|---|---|
| box proxy geom, full extents | `type="box" size="hx hy hz"`, half extents |
| cylinder, radius and full length, axis the local z | `type="cylinder" size="r half_length"` |
| sphere | `type="sphere" size="r"` |
| centre | `pos="x y z"` |
| orientation `{x, y, z, w}` | `quat="w x y z"` |

The body's mass, centre of mass and inertia come from `MassProperties` as an explicit `<inertial pos mass fullinertia>`; the
geoms carry no density and `inertiafromgeom="false"` makes MuJoCo refuse a body without that element, so no body takes its mass
from a collision proxy (which has filled voids in it). `fullinertia` is `Ixx Iyy Izz Ixy Ixz Iyz`, the matrix entries about the
centre of mass in the body frame, the same signs as `MassProperties`. Angles are radians. The root has a `freejoint` named
`ROOT_JOINT_PREFIX + <body id>`; every
other body has the one `hinge` or `slider` joint of its tree joint, `pos`/`axis` in the body frame, `range` the limits (the
coordinate is 0 at the saved pose, which is also the model's reference pose). Numbers are written with `repr`, so they read
back as the same doubles; bodies, joints and geoms are in tree order. `<option>` carries the planet (W-03a, `planet.py`):
`gravity="0 0 -g"` with g from `data/bodies`, and MuJoCo's medium off (`density="0" viscosity="0"`; the planet's air density
is on `tree.planet` for the drag of W-03b, `planet.py` says why it is not MuJoCo's medium). Time step, integrator and
contact parameters are not set here (X-01b, X-02), so MuJoCo's own defaults stand until those leaves set them.
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

from kinetra_core import JointKind

from .bodytree import Body, BodyGeom, BodyTree

ROOT_JOINT_PREFIX = "__kinetra_root_"
"""The root's free joint is named `__kinetra_root_<body id>`. A project id cannot start with `_` (`ID_PATTERN`), so this name
never collides with a joint of the project."""


def _n(values) -> str:
    return " ".join(repr(float(v) + 0.0) for v in values)  # + 0.0: -0.0 is written 0.0


def _attr(name: str, value: str) -> str:
    return f"{name}={quoteattr(value)}"


def _geom(g: BodyGeom, pad: str) -> str:
    return f"{pad}<geom {_attr('name', g.name)} type={quoteattr(g.type)} size={quoteattr(_n(g.size))} pos={quoteattr(_n(g.pos))} quat={quoteattr(_n(g.quat))}/>"


def _body(tree: BodyTree, b: Body, depth: int) -> list[str]:
    pad = "  " * depth
    lines = [f"{pad}<body {_attr('name', b.id)} pos={quoteattr(_n(b.pos))} quat={quoteattr(_n(b.quat))}>"]
    ixx, iyy, izz, ixy, ixz, iyz = b.inertia
    lines.append(f"{pad}  <inertial pos={quoteattr(_n(b.com))} mass={quoteattr(_n([b.mass]))} fullinertia={quoteattr(_n([ixx, iyy, izz, ixy, ixz, iyz]))}/>")
    if b.joint is None:
        lines.append(f"{pad}  <freejoint {_attr('name', ROOT_JOINT_PREFIX + b.id)}/>")
    else:
        j = b.joint
        kind = "hinge" if j.kind is JointKind.HINGE else "slide"
        rng = "" if j.range is None else f" limited=\"true\" range={quoteattr(_n(j.range))}"
        lines.append(f"{pad}  <joint {_attr('name', j.id)} type={quoteattr(kind)} pos={quoteattr(_n(j.pos))} axis={quoteattr(_n(j.axis))}{rng}/>")
    lines.extend(_geom(g, pad + "  ") for g in b.geoms)
    for child in tree.bodies:
        if child.parent == b.id:
            lines.extend(_body(tree, child, depth + 1))
    lines.append(f"{pad}</body>")
    return lines


def to_mjcf(tree: BodyTree, name: str = "kinetra") -> str:
    """The MJCF text of `tree`. The same tree gives the same text, byte for byte."""
    lines = [
        f"<mujoco model={quoteattr(name)}>",
        '  <compiler angle="radian" inertiafromgeom="false"/>',
        f"  <option gravity={quoteattr(_n(tree.planet.gravity_vector))} density=\"0\" viscosity=\"0\"/>",
        "  <worldbody>",
    ]
    lines.extend(_body(tree, tree.root, 2))
    lines.extend(["  </worldbody>", "</mujoco>", ""])
    return "\n".join(lines)
