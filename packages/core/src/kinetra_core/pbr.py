"""PBR material slots (B-07): how a `Material` is drawn, stated in the metallic-roughness model.

The four slots are the standard parameters of Filament's material model (BaseColor, Metallic, Roughness,
Reflectance; https://google.github.io/filament/Filament.html, "Parameterization"). How a client maps them:

- `base_color`, `metallic`, `roughness`: glTF core `pbrMetallicRoughness` (`baseColorFactor`, `metallicFactor`,
  `roughnessFactor`) and three.js `MeshStandardMaterial` (`color`, `metalness`, `roughness`) take them directly.
- `reflectance`: glTF core and `MeshStandardMaterial` have NO such parameter; their dielectric F0 is fixed at 0.04
  (index of refraction 1.5), which is exactly Filament `reflectance = 0.5`. Every catalog entry uses 0.5, so core
  glTF and `MeshStandardMaterial` render all five correctly. For any other value, the client needs
  `KHR_materials_ior` (glTF) or `MeshPhysicalMaterial.ior` / `.reflectivity` (three.js; reflectivity 0.5 = ior 1.5).
  With Filament's F0 = 0.16 * reflectance^2 = ((ior - 1) / (ior + 1))^2, ior = (1 + 0.4 r) / (1 - 0.4 r).
  Reflectance has no effect when `metallic == 1`.

Slots are parametric, not texture maps: no CC0 texture in `assets/LEDGER.csv` shows metal, composite or plastic (the
ledger holds planet ground textures and skies only), and a new texture would need its own ledger row. A texture slot
can be added the day such an asset is in the ledger.

Conventions (the client converts to its renderer; the core does not):
- `base_color.srgb` is sRGB, lowercase `#rrggbb`, the same notation as the design tokens. Filament's table of metal
  F0 colors is given in sRGB and used as the base color.
- `metallic`, `roughness`, `reflectance` are dimensionless in [0, 1]. For `metallic == 1` the specular color is the
  base color and `reflectance` has no effect; for `metallic == 0` `reflectance` sets F0 (Filament: 0.5 is 4%).
- Every slot carries a badge and a source, like any other number. Appearance choices that no source states are
  `default` badges with the reason in `source.ref`; they are looks, not measurements.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .conventions import Unit
from .provenance import Provenance, Quantity

_Unit01 = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=1)]


class PbrColor(Provenance):
    """Base color as sRGB hex."""

    srgb: str = Field(pattern=r"^#[0-9a-f]{6}$")


class PbrScalar(Quantity):
    """A dimensionless slot value in [0, 1]."""

    value: _Unit01
    unit: Literal[Unit.ONE]


class PbrSlots(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_color: PbrColor
    metallic: PbrScalar
    roughness: PbrScalar
    reflectance: PbrScalar
