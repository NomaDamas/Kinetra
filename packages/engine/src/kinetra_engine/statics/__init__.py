"""Static checks before a run (X-03): L0 analytic numbers, not a verdict. Support polygon and tip-over angle (X-03a)."""

from .tipover import RIM_SEGMENTS, SupportEdge, SupportPoint, Tipover, TipoverError, tipover

__all__ = ["RIM_SEGMENTS", "SupportEdge", "SupportPoint", "Tipover", "TipoverError", "tipover"]
