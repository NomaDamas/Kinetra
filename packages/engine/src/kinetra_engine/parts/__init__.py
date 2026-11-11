"""Part compiler: shape recipe to physical properties (B-01a), collision proxy (B-01b), visual glTF (B-01c), cache (B-01d), battery and tank supply (B-03d)."""

from ._shape import ShapeError
from .cache import CacheStats, PartCache, part_key, material_key
from .collision import collision_proxy
from .curves import CurveError, CurveRangeError, MotorCharacteristics, evaluate, motor_characteristics, motor_torque_limit
from .mass import mass_properties
from .thruster import Burn, CatalogFinding, Thruster, ThrusterError, burn, catalog_finding, thruster_from_part
from .supply import Draw, Supply, SupplyError, battery_supply, electrical_power, tank_supply, tank_total_mass
from .visual import part_glb, part_gltf, pbr_for

__all__ = [
    "Burn",
    "CatalogFinding",
    "Thruster",
    "ThrusterError",
    "burn",
    "catalog_finding",
    "thruster_from_part",
    "CacheStats",
    "CurveError",
    "CurveRangeError",
    "MotorCharacteristics",
    "Draw",
    "PartCache",
    "ShapeError",
    "Supply",
    "SupplyError",
    "battery_supply",
    "collision_proxy",
    "evaluate",
    "motor_characteristics",
    "motor_torque_limit",
    "electrical_power",
    "part_key",
    "mass_properties",
    "material_key",
    "part_glb",
    "part_gltf",
    "pbr_for",
    "tank_supply",
    "tank_total_mass",
]
