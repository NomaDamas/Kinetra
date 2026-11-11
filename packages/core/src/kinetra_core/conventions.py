"""Units and coordinate conventions of the Project model (A0-04 carry-over, issue #60 comment).

Every number that crosses the adapter boundary (`docs/architecture/client-adapter.md` rule G4) is written in
these conventions. Clients convert to their own renderer's frame; the core never does.

- Units: SI. Length m, mass kg, time s, angle rad. The `Unit` vocabulary below is closed: a quantity whose unit
  is not in it is rejected, so a client never has to guess what `"mm"` or `"deg"` means.
- Frame: right-handed, +Z is up. In Project JSON a quaternion is an object with named components `x, y, z, w`
  (unit norm, `w` is the scalar part), never a bare array. Streamed frames (C-05b) use the same component order and
  meaning; their encoding is C-05b's.
"""

from __future__ import annotations

from enum import StrEnum

COORDINATE_FRAME = "right-handed, +Z up"
QUATERNION_COMPONENTS = ("x", "y", "z", "w")
QUATERNION_NORM_TOLERANCE = 1e-6

ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"  # stable ids of materials, parts, snap points, instances, joints, actuators (G3)
NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"  # parameter, spec and tag names


class Unit(StrEnum):
    """Closed unit vocabulary (SI, written the way the JSON carries it)."""

    ONE = "1"  # dimensionless (friction coefficient, ratio, count)
    M = "m"
    M2 = "m^2"
    M3 = "m^3"
    KG = "kg"
    S = "s"
    RAD = "rad"
    M_PER_S = "m/s"
    M_PER_S2 = "m/s^2"
    RAD_PER_S = "rad/s"
    N = "N"
    N_M = "N*m"
    N_PER_M = "N/m"
    N_S_PER_M = "N*s/m"  # linear damping (B-03e)
    N_M_PER_RAD = "N*m/rad"  # torsional spring rate
    N_M_S_PER_RAD = "N*m*s/rad"  # torsional damping (B-03e)
    PA = "Pa"
    KG_PER_M3 = "kg/m^3"
    KG_M2 = "kg*m^2"
    J = "J"
    W = "W"
    W_PER_M2 = "W/m^2"  # irradiance (planet insolation, W-01)
    V = "V"  # electrical: motor rated voltage (B-03b)
    A = "A"  # electrical: motor current (B-03b)
