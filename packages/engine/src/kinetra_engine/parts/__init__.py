"""Part compiler: shape recipe to physical properties (B-01a) and collision proxy (B-01b). glTF (B-01c) comes later."""

from ._shape import ShapeError
from .collision import collision_proxy
from .mass import mass_properties

__all__ = ["ShapeError", "collision_proxy", "mass_properties"]
