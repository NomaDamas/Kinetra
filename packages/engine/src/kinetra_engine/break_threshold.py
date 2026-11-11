"""Joint break threshold (X-04a): material strength x cross-section = the load [N] at which a connection is taken to fail.

A **simplified model, not FEM** (studio plan 4.6): one nominal stress over one section, no stress concentration, no bending,
no combined loading, no fatigue, no crack. `critical_load` returns a `BreakThreshold` (the `Joint.break_threshold` field type,
`kinetra_core.BreakThreshold`) carrying the simplified-model label, and everything that tells a reader how far to trust it.

Formulas (textbook, with locators; the derivation is in `docs/architecture/break-threshold.md`):

* tension, `LoadMode.TENSION`: the section yields (or, for a brittle material, fractures) when the average normal stress
  sigma = P / A reaches the strength S, so P_crit = S * A.
  Beer, Johnston, DeWolf, Mazurek, *Mechanics of Materials*, 7th ed. (McGraw-Hill, 2015), Sec. 1.2A "Axial Loading: Normal
  Stress", Eq. (1.5).
* shear, `LoadMode.SHEAR`: the average shearing stress tau = P / A (single shear, Eq. 1.9) or tau = F / 2A (double shear,
  Eq. 1.10) reaches the shear yield strength Ssy = 0.577 Sy, so V_crit = planes * 0.577 * Sy * A.
  Beer et al., 7th ed., Sec. 1.2B "Shearing Stress", Eqs. (1.9) and (1.10);
  Budynas, Nisbett, *Shigley's Mechanical Engineering Design*, 9th ed. (McGraw-Hill), Sec. 5-5 "Distortion-Energy Theory for
  Ductile Materials", Eq. (5-21): Ssy = 0.577 Sy.

The strength is `Material.yield_strength` from the B-07 catalog. Its **basis is mixed** and that is not hidden: 6061-T6, CFRP and
POM carry typical values, A36 and Ti-6Al-4V specified minimums (`docs/architecture/materials.md`). The basis is read from the
strength's `source.ref` (the catalog writes "Basis: TYPICAL" or "Basis: specified MINIMUM" there; there is no structured field
yet, issue #481) and put on every result as a label. **Thresholds of different materials must not be compared.**
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from kinetra_core import Badge, BreakThreshold, Material, Quantity, Source, Unit

SIMPLIFIED_MODEL_LABEL = "단순화 모델"
"""Shown with every threshold computed here (X-04a DoD)."""

SHEAR_YIELD_RATIO = 0.577
"""Ssy / Sy of the distortion-energy (von Mises) theory: Shigley's Mechanical Engineering Design, 9th ed., Sec. 5-5, Eq. (5-21).
The book prints 0.577 (1 / sqrt(3) = 0.57735)."""

CITATION_TENSION = "Beer et al., Mechanics of Materials 7th ed., Sec. 1.2A, Eq. (1.5)"
CITATION_SHEAR = (
    "Beer et al., Mechanics of Materials 7th ed., Sec. 1.2B, Eqs. (1.9), (1.10); "
    "Shigley's Mechanical Engineering Design 9th ed., Sec. 5-5, Eq. (5-21)"
)

DOC = "docs/architecture/break-threshold.md"


class BreakThresholdError(ValueError):
    """The inputs cannot give a threshold (bad section, a mode the material's strength does not support)."""


class LoadMode(StrEnum):
    TENSION = "tension"  # load normal to the section
    SHEAR = "shear"  # load in the plane of the section (a pin, a bolt, a weld throat)


class StrengthBasis(StrEnum):
    """What the catalog's strength number is: a typical value or a specified minimum (or not stated)."""

    TYPICAL = "typical"
    SPECIFIED_MINIMUM = "specified_minimum"
    UNSTATED = "unstated"


_BASIS_LABEL = {
    StrengthBasis.TYPICAL: "강도 기준: 대표값(typical), 보증된 최소가 아님",
    StrengthBasis.SPECIFIED_MINIMUM: "강도 기준: 규격 최소값(specified minimum), 대표값이 아님",
    StrengthBasis.UNSTATED: "강도 기준: 출처에 적혀 있지 않음(대표값인지 최소값인지 모름)",
}
_NO_COMPARE_LABEL = "다른 재료의 임계와 비교할 수 없다(재료마다 강도 기준이 다르다)"
_MODE_LABEL = {LoadMode.TENSION: "인장(단면에 수직)", LoadMode.SHEAR: "전단(단면 안쪽)"}

_BASIS_RE = re.compile(r"Basis:\s*(TYPICAL|specified MINIMUM)")
_NO_YIELD_RE = re.compile(r"no yield point", re.IGNORECASE)


def strength_basis(strength: Quantity) -> StrengthBasis:
    """The basis the catalog wrote into the strength's `source.ref` (`Basis: TYPICAL` / `Basis: specified MINIMUM`)."""
    m = _BASIS_RE.search(strength.source.ref)
    if m is None:
        return StrengthBasis.UNSTATED
    return StrengthBasis.TYPICAL if m.group(1) == "TYPICAL" else StrengthBasis.SPECIFIED_MINIMUM


def is_fracture_strength(strength: Quantity) -> bool:
    """True when the source says the material has no yield point and the number is the strength at fracture (the CFRP entry)."""
    return _NO_YIELD_RE.search(strength.source.ref) is not None


def _dimension(q: Quantity, what: str) -> float:
    if q.unit is not Unit.M:
        raise BreakThresholdError(f"{what} must be in m, got {q.unit.value!r}")
    if not (math.isfinite(q.value) and q.value > 0.0):
        raise BreakThresholdError(f"{what} must be a positive finite length, got {q.value}")
    return q.value


@dataclass(frozen=True)
class SolidCircle:
    """A solid round section (a pin or bolt shank, a rod)."""

    diameter: Quantity

    def area(self) -> float:
        d = _dimension(self.diameter, "diameter")
        return math.pi * d * d / 4.0

    def quantities(self) -> tuple[Quantity, ...]:
        return (self.diameter,)

    def describe(self) -> str:
        return f"solid circle d={self.diameter.value:.6g} m"


@dataclass(frozen=True)
class Rectangle:
    """A solid rectangular section (a bar, a plate's cut)."""

    width: Quantity
    height: Quantity

    def area(self) -> float:
        return _dimension(self.width, "width") * _dimension(self.height, "height")

    def quantities(self) -> tuple[Quantity, ...]:
        return (self.width, self.height)

    def describe(self) -> str:
        return f"rectangle {self.width.value:.6g} x {self.height.value:.6g} m"


@dataclass(frozen=True)
class Annulus:
    """A tube or ring section."""

    outer_diameter: Quantity
    inner_diameter: Quantity

    def area(self) -> float:
        do, di = _dimension(self.outer_diameter, "outer_diameter"), _dimension(self.inner_diameter, "inner_diameter")
        if not di < do:
            raise BreakThresholdError(f"inner_diameter {di} must be smaller than outer_diameter {do}")
        return math.pi * (do * do - di * di) / 4.0

    def quantities(self) -> tuple[Quantity, ...]:
        return (self.outer_diameter, self.inner_diameter)

    def describe(self) -> str:
        return f"annulus D={self.outer_diameter.value:.6g} m, d={self.inner_diameter.value:.6g} m"


@dataclass(frozen=True)
class DeclaredArea:
    """A section area given directly [m^2] (a weld throat, a section the three shapes above do not cover)."""

    value: Quantity

    def area(self) -> float:
        q = self.value
        if q.unit is not Unit.M2:
            raise BreakThresholdError(f"area must be in m^2, got {q.unit.value!r}")
        if not (math.isfinite(q.value) and q.value > 0.0):
            raise BreakThresholdError(f"area must be a positive finite number, got {q.value}")
        return q.value

    def quantities(self) -> tuple[Quantity, ...]:
        return (self.value,)

    def describe(self) -> str:
        return f"declared area {self.value.value:.6g} m^2"


Section = SolidCircle | Rectangle | Annulus | DeclaredArea


@dataclass(frozen=True)
class CriticalLoad:
    """The threshold and what stands behind it. `quantity` is a `BreakThreshold`, valid as `Joint.break_threshold`."""

    quantity: BreakThreshold
    material_id: str
    mode: LoadMode
    strength: float  # Pa, the material's Material.yield_strength used (Sy, before the shear ratio)
    strength_basis: StrengthBasis
    strength_is_fracture: bool  # True: the strength is a fracture strength (no yield point), not a yield strength
    area: float  # m^2
    shear_planes: int  # 1 or 2 for LoadMode.SHEAR, 1 for tension (unused)
    model: str  # SIMPLIFIED_MODEL_LABEL
    citations: tuple[str, ...]
    labels: tuple[str, ...]  # what to show beside the number: model, mode, strength basis, no-comparison
    assumptions: tuple[str, ...]
    input_badges: tuple[Badge, ...]  # the badges of strength and of every section dimension

    @property
    def value(self) -> float:
        return self.quantity.value


_ASSUMPTIONS = (
    "One nominal stress, uniform over the section: no stress concentration at holes, threads or fillets, no bending, no "
    "prying, no combined load. The load is one scalar force; its direction is not checked against the joint's free axis.",
    "The threshold is the load at which the section reaches the catalog strength (onset of yield, or fracture for a material "
    "with no yield point), not the load at rupture; for a ductile metal real rupture needs more.",
    "Static strength only: no fatigue, no crack growth, no creep, no temperature or strain-rate effect, no corrosion.",
    "The strength is one scalar from the catalog; an anisotropic material (CFRP) has different strengths along other directions "
    "and in shear, which this does not model.",
    "The caller states which part of the connection governs (a pin, a bolt, a weld, a member) and gives its section; the "
    "two members' materials are not compared here, because strengths of different materials are not comparable.",
)


def critical_load(
    material: Material,
    section: Section,
    mode: LoadMode | str,
    *,
    shear_planes: int = 1,
) -> CriticalLoad:
    """Load [N] at which `section` of `material` fails under `mode`, by the simplified formulas in the module docstring.

    `mode` is a `LoadMode` or its string value (`"tension"`, `"shear"`; anything else raises `BreakThresholdError`).
    `LoadMode.TENSION`: P = Sy * A. `LoadMode.SHEAR`: V = planes * 0.577 * Sy * A, where `shear_planes` is 1 (single shear)
    or 2 (double shear; `section` is the area of *one* shear plane). Sy is `material.yield_strength`.

    A material whose strength is a fracture strength (no yield point) has no shear yield strength: `LoadMode.SHEAR` for it
    raises `BreakThresholdError` instead of applying a ductile-metal ratio to a brittle composite.
    """
    try:
        mode = LoadMode(mode)
    except ValueError:
        raise BreakThresholdError(f"mode must be one of {[m.value for m in LoadMode]}, got {mode!r}") from None
    if shear_planes not in (1, 2):
        raise BreakThresholdError(f"shear_planes must be 1 (single shear) or 2 (double shear), got {shear_planes!r}")
    if mode == LoadMode.TENSION and shear_planes != 1:
        raise BreakThresholdError("shear_planes applies to LoadMode.SHEAR only")
    s = material.yield_strength
    fracture = is_fracture_strength(s)
    if mode == LoadMode.SHEAR and fracture:
        raise BreakThresholdError(
            f"material {material.id!r}: its strength is a fracture strength (no yield point), so there is no shear yield "
            f"strength 0.577 Sy to use; the shear strength of this material is not in the catalog"
        )
    area = section.area()
    basis = strength_basis(s)
    if mode == LoadMode.TENSION:
        load = s.value * area
        citations = (CITATION_TENSION,)
        formula = "P = S*A"
    else:
        load = shear_planes * SHEAR_YIELD_RATIO * s.value * area
        citations = (CITATION_SHEAR,)
        formula = f"V = {shear_planes}*{SHEAR_YIELD_RATIO}*S*A ({'single' if shear_planes == 1 else 'double'} shear)"
    if not (math.isfinite(load) and load > 0.0):
        raise BreakThresholdError(f"the threshold of strength {s.value!r} Pa x area {area!r} m^2 is not a positive finite number")

    kind = "fracture strength" if fracture else "yield strength"
    ref = (
        f"{SIMPLIFIED_MODEL_LABEL} (not FEM): {formula}, S = {s.value:.6g} Pa {kind} of {material.id} "
        f"({_BASIS_LABEL[basis]}), A = {area:.6g} m^2 ({section.describe()}). Strength badge: {s.badge.value}. See {DOC}"
    )
    quantity = BreakThreshold(
        value=load,
        unit=Unit.N,
        badge=Badge.ESTIMATE,
        source=Source(ref=ref, locator=citations[0][:200]),
    )
    labels = (
        SIMPLIFIED_MODEL_LABEL,
        _MODE_LABEL[mode],
        _BASIS_LABEL[basis],
        *(("강도는 항복이 아니라 파단 강도(항복점 없음)",) if fracture else ()),
        _NO_COMPARE_LABEL,
    )
    badges = (s.badge, *(q.badge for q in section.quantities()))
    return CriticalLoad(
        quantity=quantity,
        material_id=material.id,
        mode=mode,
        strength=s.value,
        strength_basis=basis,
        strength_is_fracture=fracture,
        area=area,
        shear_planes=shear_planes if mode == LoadMode.SHEAR else 1,
        model=SIMPLIFIED_MODEL_LABEL,
        citations=citations,
        labels=labels,
        assumptions=_ASSUMPTIONS,
        input_badges=badges,
    )
