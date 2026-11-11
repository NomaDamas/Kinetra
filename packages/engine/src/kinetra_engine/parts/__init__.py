"""Part compiler: shape recipe to physical properties (B-01a), collision proxy (B-01b), visual glTF (B-01c), cache (B-01d)."""

from ._shape import ShapeError
from .cache import CacheStats, PartCache, part_key, material_key
from .collision import collision_proxy
from .mass import mass_properties
from .visual import part_glb, part_gltf, pbr_for

__all__ = [
    "CacheStats",
    "PartCache",
    "ShapeError",
    "collision_proxy",
    "part_key",
    "mass_properties",
    "material_key",
    "part_glb",
    "part_gltf",
    "pbr_for",
]
