"""Part compiler: shape recipe to physical properties (B-01a). Collision proxy (B-01b) and glTF (B-01c) come later."""

from .mass import ShapeError, mass_properties

__all__ = ["ShapeError", "mass_properties"]
