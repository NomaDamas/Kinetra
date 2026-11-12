"""Static checks before a run (X-03): L0 analytic numbers, not a verdict. Support polygon and tip-over angle (X-03a);
thrust-to-weight on each planet and burn time (X-07)."""

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
    "NoValue",
    "PlanetRatio",
    "SupportEdge",
    "SupportPoint",
    "ThrustToWeight",
    "ThrusterBurn",
    "Tipover",
    "TipoverError",
    "thrust_to_weight",
    "tipover",
    "weakest",
]
