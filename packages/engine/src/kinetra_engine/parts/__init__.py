"""Part compiler: shape recipe to physical properties (B-01a), collision proxy (B-01b), visual glTF (B-01c), cache (B-01d), spring-damper (B-03e)."""

from ._shape import ShapeError
from .cache import CacheStats, PartCache, part_key, material_key
from .collision import collision_proxy
from .curves import CurveRangeError, MotorCharacteristics, evaluate, motor_characteristics, motor_torque_limit
from .mass import mass_properties
from .spring import SpringResponse, Trajectory, integrate, joint_spring, spring_response
from .visual import part_glb, part_gltf, pbr_for

__all__ = [
    "CacheStats",
    "CurveRangeError",
    "MotorCharacteristics",
    "PartCache",
    "ShapeError",
    "SpringResponse",
    "Trajectory",
    "collision_proxy",
    "evaluate",
    "integrate",
    "joint_spring",
    "motor_characteristics",
    "motor_torque_limit",
    "part_key",
    "mass_properties",
    "material_key",
    "part_glb",
    "part_gltf",
    "pbr_for",
    "spring_response",
]
