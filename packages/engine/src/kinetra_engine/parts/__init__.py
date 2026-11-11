"""Part compiler: shape recipe to physical properties (B-01a), collision proxy (B-01b), visual glTF (B-01c), cache (B-01d), battery and tank supply (B-03d), spring-dampers (B-03e), assembly mass (B-02)."""

from ._shape import ShapeError
from .assembly import AssemblyMass, InstanceMass, assembly_mass
from .cache import CacheStats, PartCache, part_key, material_key
from .collision import collision_proxy
from .curves import CurveError, CurveRangeError, MotorCharacteristics, evaluate, motor_characteristics, motor_torque_limit
from .library import library_hashes, library_parts
from .mass import mass_properties
from .separator import ASSUMPTION_LABEL as SEPARATION_ASSUMPTION_LABEL, Separator, SeparatorError, separation_assumption, separator_from_part
from .springs import Oscillation, SpringDamperCharacteristics, oscillation, spring_damper_characteristics, spring_damper_force
from .thruster import Burn, CatalogFinding, Thruster, ThrusterError, burn, catalog_finding, thruster_from_part
from .supply import Draw, Supply, SupplyError, battery_supply, electrical_power, tank_supply, tank_total_mass
from .visual import part_glb, part_gltf, pbr_for

__all__ = [
    "AssemblyMass",
    "Burn",
    "CacheStats",
    "CatalogFinding",
    "CurveError",
    "CurveRangeError",
    "Draw",
    "InstanceMass",
    "MotorCharacteristics",
    "Oscillation",
    "PartCache",
    "SEPARATION_ASSUMPTION_LABEL",
    "Separator",
    "SeparatorError",
    "ShapeError",
    "SpringDamperCharacteristics",
    "Supply",
    "SupplyError",
    "Thruster",
    "ThrusterError",
    "assembly_mass",
    "battery_supply",
    "burn",
    "catalog_finding",
    "collision_proxy",
    "electrical_power",
    "evaluate",
    "library_hashes",
    "library_parts",
    "mass_properties",
    "material_key",
    "motor_characteristics",
    "motor_torque_limit",
    "oscillation",
    "part_glb",
    "part_gltf",
    "part_key",
    "pbr_for",
    "separation_assumption",
    "separator_from_part",
    "spring_damper_characteristics",
    "spring_damper_force",
    "tank_supply",
    "tank_total_mass",
    "thruster_from_part",
]
