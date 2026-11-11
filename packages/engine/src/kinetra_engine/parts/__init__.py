"""Part compiler: shape recipe to physical properties (B-01a), collision proxy (B-01b) and visual glTF (B-01c)."""

from ._shape import ShapeError
from .collision import collision_proxy
from .mass import mass_properties
from .visual import part_glb, part_gltf, pbr_for

__all__ = ["ShapeError", "collision_proxy", "mass_properties", "part_glb", "part_gltf", "pbr_for"]
