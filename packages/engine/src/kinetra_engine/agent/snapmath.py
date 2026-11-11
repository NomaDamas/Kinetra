"""Pose arithmetic for placing a part by its snap points (G-02a). Pure functions on the core's own frames (`conventions.py`).

A snap point has a frame in its part (`SnapPoint.position` evaluated at the instance's parameters, `SnapPoint.orientation`). Placing an
instance so that its snap point `s` meets a target snap frame `T` (world) is a closed-form rigid transform:

    R_snap_world = R_T . Q . Rz(roll)           Q = I (coincident) or Rx(pi) (opposed: the two +Z point against each other)
    R_inst       = R_snap_world . R_s^T         R_s: orientation of `s` in the part
    t_inst       = p_T - R_inst . p_s           p_s: position of `s` in the part

`Q . Rz(roll)` turns about the new snap point's own +Z, so the roll is a turn about the axis the two parts are joined along.
Nothing here is numeric judgement: the same inputs give the same pose, and the validator (C-02c) decides whether the result is allowed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from kinetra_core import PartDef, Quaternion, convex as cx
from kinetra_core.designspec import Instance

Vec = cx.Vec
Mat = cx.Mat

IDENTITY: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
RX_PI: Mat = ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
_QUARTER = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))  # (cos, sin) of 0, 90, 180, 270 degrees: exact, no float trig

DECIMALS = 12
"""Stored poses are rounded to 1e-12 (m, and quaternion components). That is a thousandth of a millionth of the validator's tolerance
(`PLACEMENT_TOLERANCE`, 1 micrometre), so rounding never turns a meeting snap pair into a separated one; it only keeps the stored
numbers readable (0.005 instead of 0.005000000000000001)."""


def matmul(a: Mat, b: Mat) -> Mat:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]


def transpose(a: Mat) -> Mat:
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def apply(r: Mat, v: Vec) -> Vec:
    return (cx.dot(r[0], v), cx.dot(r[1], v), cx.dot(r[2], v))


def rz_quarter(turns: int) -> Mat:
    c, s = _QUARTER[turns % 4]
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def rz(angle: float) -> Mat:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def to_quaternion(r: Mat) -> Quaternion:
    """The unit quaternion {x, y, z, w} of rotation matrix `r`, with w >= 0 (q and -q are one rotation)."""
    t = r[0][0] + r[1][1] + r[2][2]
    if t > 0.0:
        s = math.sqrt(t + 1.0) * 2.0
        w, x, y, z = s / 4.0, (r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2.0
        w, x, y, z = (r[2][1] - r[1][2]) / s, s / 4.0, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2.0
        w, x, y, z = (r[0][2] - r[2][0]) / s, (r[0][1] + r[1][0]) / s, s / 4.0, (r[1][2] + r[2][1]) / s
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2.0
        w, x, y, z = (r[1][0] - r[0][1]) / s, (r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, s / 4.0
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    if w < 0.0 or (w == 0.0 and (x, y, z) < (0.0, 0.0, 0.0)):
        x, y, z, w = -x, -y, -z, -w
    return Quaternion(x=clean(x), y=clean(y), z=clean(z), w=clean(w))


def clean(v: float) -> float:
    """`v` rounded to `DECIMALS`, with no negative zero."""
    return round(v, DECIMALS) + 0.0


def parameter_values(part: PartDef, instance: Instance | None) -> dict[str, float]:
    """Parameter values of an instance: its own where set, else the part's default (the same rule as the validator's)."""
    values = {p.name: p.default.value for p in part.parameters}
    if instance is not None:
        values |= {p.name: p.value for p in instance.parameters}
    return values


def snap_local(part: PartDef, snap_id: str, values: Mapping[str, float]) -> tuple[Vec, Mat]:
    """Position and orientation matrix of snap point `snap_id` in the part's frame at parameter `values`."""
    snap = next(s for s in part.snap_points if s.id == snap_id)
    return snap.position.evaluate(values), cx.rotation(snap.orientation)


def world_bodies(part: PartDef, values: Mapping[str, float], r: Mat, t: Vec) -> list[cx.Body]:
    """Collision geometry of the part at world rotation `r` and position `t`: the added components of its shape recipe, as the
    validator reads them (`validator._instance_bodies`). Empty for a part without a shape recipe."""
    if part.shape is None:
        return []
    out = []
    for comp in part.shape.components:
        if comp.operation != "add":
            continue
        dims = {name: expr.evaluate(values) for name, expr in comp.primitive.dimensions()}
        local = cx.make_body(comp.primitive, dims, comp.position.evaluate(values), cx.rotation(comp.orientation))
        out.append(cx.Body(local.kind, cx.add(apply(r, local.center), t), tuple(apply(r, a) for a in local.axes), local.half))  # type: ignore[arg-type]
    return out


def lowest_z(bodies: list[cx.Body]) -> float | None:
    """Lowest world z over `bodies`, or None when there is no geometry."""
    if not bodies:
        return None
    return min(-b.support((0.0, 0.0, -1.0)) for b in bodies)
