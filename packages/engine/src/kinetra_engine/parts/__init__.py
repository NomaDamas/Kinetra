"""Part compiler: shape recipe to physical properties (B-01a), collision proxy (B-01b), visual glTF (B-01c), cache (B-01d), battery and tank supply (B-03d), spring-dampers (B-03e)."""

from ._shape import ShapeError
from .cache import CacheStats, PartCache, part_key, material_key
from .collision import collision_proxy
from .curves import CurveError, CurveRangeError, MotorCharacteristics, evaluate, motor_characteristics, motor_torque_limit
from .mass import mass_properties
from .springs import Oscillation, SpringDamperCharacteristics, oscillation, spring_damper_characteristics, spring_damper_force
from .thruster import Burn, CatalogFinding, Thruster, ThrusterError, burn, catalog_finding, thruster_from_part
from .supply import Draw, Supply, SupplyError, battery_supply, electrical_power, tank_supply, tank_total_mass
from .visual import part_glb, part_gltf, pbr_for

__all__ = [
    "Burn",
    "CacheStats",
    "CatalogFinding",
    "CurveError",
    "CurveRangeError",
    "Draw",
    "MotorCharacteristics",
    "Oscillation",
    "PartCache",
    "ShapeError",
    "SpringDamperCharacteristics",
    "Supply",
    "SupplyError",
    "Thruster",
    "ThrusterError",
    "battery_supply",
    "burn",
    "catalog_finding",
    "collision_proxy",
    "electrical_power",
    "evaluate",
    "mass_properties",
    "material_key",
    "motor_characteristics",
    "motor_torque_limit",
    "oscillation",
    "part_glb",
    "part_gltf",
    "part_key",
    "pbr_for",
    "spring_damper_characteristics",
    "spring_damper_force",
    "tank_supply",
    "tank_total_mass",
    "thruster_from_part",
]
