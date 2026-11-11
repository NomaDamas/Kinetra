"""Part compiler: shape recipe to physical properties (B-01a) and visual glTF (B-01c). Collision proxy (B-01b) comes later."""

from .mass import ShapeError, mass_properties
from .visual import part_glb, part_gltf, pbr_for

__all__ = ["ShapeError", "mass_properties", "part_glb", "part_gltf", "pbr_for"]
