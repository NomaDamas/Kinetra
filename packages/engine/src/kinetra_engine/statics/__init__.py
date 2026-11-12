"""Static checks before a run (X-03): L0 analytic numbers, not a verdict. Support polygon and tip-over angle (X-03a), static
joint load against the break threshold (X-03b)."""

from .static_load import JointLoad, LoadStatus, StaticLoads, static_loads
from .tipover import RIM_SEGMENTS, SupportEdge, SupportPoint, Tipover, TipoverError, tipover

__all__ = [
    "RIM_SEGMENTS",
    "JointLoad",
    "LoadStatus",
    "StaticLoads",
    "SupportEdge",
    "SupportPoint",
    "Tipover",
    "TipoverError",
    "static_loads",
    "tipover",
]
