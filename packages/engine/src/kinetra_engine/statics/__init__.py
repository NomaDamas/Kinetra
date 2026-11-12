"""Static checks before a run (X-03): L0 analytic numbers, not a verdict. Support polygon and tip-over angle (X-03a); static
joint load against the break threshold (X-03b); thrust-to-weight on each planet and burn time (X-07)."""

from .static_load import JointLoad, LoadStatus, StaticLoads, static_loads
from .tipover import RIM_SEGMENTS, SupportEdge, SupportPoint, Tipover, TipoverError, tipover
from .twr import (
    BADGE_STRENGTH,
    AnalyticValue,
    InputBadges,
    NoValue,
    PlanetRatio,
    ThrusterBurn,
    ThrustToWeight,
    thrust_to_weight,
    weakest,
)

__all__ = [
    "BADGE_STRENGTH",
    "RIM_SEGMENTS",
    "AnalyticValue",
    "InputBadges",
    "JointLoad",
    "LoadStatus",
    "NoValue",
    "PlanetRatio",
    "StaticLoads",
    "SupportEdge",
    "SupportPoint",
    "ThrustToWeight",
    "ThrusterBurn",
    "Tipover",
    "TipoverError",
    "static_loads",
    "thrust_to_weight",
    "tipover",
    "weakest",
]
