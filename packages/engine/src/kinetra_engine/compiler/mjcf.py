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
back as the same doubles; bodies, joints and geoms are in tree order. No `<option>`: gravity, time step, integrator and contact
parameters are not set here (W-03a, X-02), so MuJoCo's own defaults stand until those leaves set them.

With `drives` (`compile_drives`, X-01b) a slider that carries a spring-damper gets `stiffness` and `damping` (the spring's force is 0
at coordinate 0, `springref` 0) and each motor actuator is a `<motor joint gear="1">` whose `ctrl` is the joint torque in N*m,
`ctrlrange` +- its stall torque; `DriveRuntime` writes `ctrl` every step (`drives.py`).
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

from kinetra_core import JointKind

from .bodytree import Body, BodyGeom, BodyTree
from .drives import Drives

ROOT_JOINT_PREFIX = "__kinetra_root_"
"""The root's free joint is named `__kinetra_root_<body id>`. A project id cannot start with `_` (`ID_PATTERN`), so this name
never collides with a joint of the project."""


def _n(values) -> str:
    return " ".join(repr(float(v) + 0.0) for v in values)  # + 0.0: -0.0 is written 0.0


def _attr(name: str, value: str) -> str:
    return f"{name}={quoteattr(value)}"


def _geom(g: BodyGeom, pad: str) -> str:
    return f"{pad}<geom {_attr('name', g.name)} type={quoteattr(g.type)} size={quoteattr(_n(g.size))} pos={quoteattr(_n(g.pos))} quat={quoteattr(_n(g.quat))}/>"


def _body(tree: BodyTree, b: Body, depth: int, drives: Drives | None) -> list[str]:
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
        spring = None if drives is None else drives.spring(j.id)
        sd = "" if spring is None else f" stiffness={quoteattr(_n([spring.stiffness]))} damping={quoteattr(_n([spring.damping]))}"
        lines.append(f"{pad}  <joint {_attr('name', j.id)} type={quoteattr(kind)} pos={quoteattr(_n(j.pos))} axis={quoteattr(_n(j.axis))}{rng}{sd}/>")
    lines.extend(_geom(g, pad + "  ") for g in b.geoms)
    for child in tree.bodies:
        if child.parent == b.id:
            lines.extend(_body(tree, child, depth + 1, drives))
    lines.append(f"{pad}</body>")
    return lines


def to_mjcf(tree: BodyTree, name: str = "kinetra", drives: Drives | None = None) -> str:
    """The MJCF text of `tree`, with the springs and motors of `drives` when given. The same input gives the same text, byte for byte."""
    lines = [
        f"<mujoco model={quoteattr(name)}>",
        '  <compiler angle="radian" inertiafromgeom="false"/>',
        "  <worldbody>",
    ]
    lines.extend(_body(tree, tree.root, 2, drives))
    lines.append("  </worldbody>")
    if drives is not None and drives.motors:
        lines.append("  <actuator>")
        for m in drives.motors:
            lines.append(
                f"    <motor {_attr('name', m.actuator)} {_attr('joint', m.joint)} gear=\"1\" ctrllimited=\"true\" "
                f"ctrlrange={quoteattr(_n([-m.stall_torque, m.stall_torque]))}/>"
            )
        lines.append("  </actuator>")
    lines.extend(["</mujoco>", ""])
    return "\n".join(lines)
