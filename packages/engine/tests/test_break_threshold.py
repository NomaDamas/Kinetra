"""X-04a: the break threshold of a joint, material strength x section (`kinetra_engine.break_threshold`).

Expected values are hand calculations written out here from the textbook formulas and the catalog's printed strengths
(`material_catalog.json`: A36 248.2 MPa, Ti-6Al-4V 828 MPa, 6061-T6 276 MPa, CFRP 828 MPa, POM 72 MPa), not read from the code
under test:

  1. A36 pin, d = 10 mm, single shear:   A = pi (0.005)^2 = 7.853982e-5 m^2, V = 0.577 * 248.2e6 * A = 11 247.80 N
  2. 6061-T6 bar 20 x 5 mm, tension:     A = 1.0e-4 m^2, P = 276e6 * 1.0e-4 = 27 600 N
  3. Ti-6Al-4V tube D8/d4 mm, double shear: A = pi/4 (0.008^2 - 0.004^2) = 3.769911e-5 m^2,
                                         V = 2 * 0.577 * 828e6 * A = 36 021.95 N
"""

from __future__ import annotations

import math

import pytest

from kinetra_core import Badge, BreakThreshold, Joint, JointKind, Quantity, Unit, load_material_catalog
from kinetra_engine.break_threshold import (
    SIMPLIFIED_MODEL_LABEL,
    Annulus,
    BreakThresholdError,
    DeclaredArea,
    LoadMode,
    Rectangle,
    SolidCircle,
    StrengthBasis,
    critical_load,
    is_fracture_strength,
    strength_basis,
)

SRC = {"ref": "X-04a test: dimension chosen by the test"}


def material(material_id: str):
    return load_material_catalog().get(material_id).material


def length(v: float) -> Quantity:
    return Quantity(value=v, unit=Unit.M, badge=Badge.DECLARED, source=SRC)


def test_break_threshold_hand_calculation_1_a36_pin_single_shear():
    r = critical_load(material("steel-a36"), SolidCircle(length(0.010)), LoadMode.SHEAR)
    assert r.area == pytest.approx(7.853982e-5, rel=1e-6)
    assert r.value == pytest.approx(11247.80, rel=1e-6)
    assert r.quantity.unit is Unit.N
    assert r.strength_basis is StrengthBasis.SPECIFIED_MINIMUM
    assert r.shear_planes == 1


def test_break_threshold_hand_calculation_2_al6061_bar_tension():
    r = critical_load(material("al6061-t6"), Rectangle(length(0.020), length(0.005)), LoadMode.TENSION)
    assert r.area == pytest.approx(1.0e-4, rel=1e-12)
    assert r.value == pytest.approx(27600.0, rel=1e-12)
    assert r.strength_basis is StrengthBasis.TYPICAL


def test_break_threshold_hand_calculation_3_ti_tube_double_shear():
    r = critical_load(material("ti-6al-4v"), Annulus(length(0.008), length(0.004)), LoadMode.SHEAR, shear_planes=2)
    assert r.area == pytest.approx(3.769911e-5, rel=1e-6)
    assert r.value == pytest.approx(36021.95, rel=1e-6)
    assert r.shear_planes == 2


def test_break_threshold_double_shear_is_twice_single_shear():
    one = critical_load(material("steel-a36"), SolidCircle(length(0.006)), LoadMode.SHEAR, shear_planes=1)
    two = critical_load(material("steel-a36"), SolidCircle(length(0.006)), LoadMode.SHEAR, shear_planes=2)
    assert two.value == pytest.approx(2.0 * one.value, rel=1e-12)


def test_break_threshold_declared_area_equals_the_same_rectangle():
    a = DeclaredArea(Quantity(value=1.0e-4, unit=Unit.M2, badge=Badge.DECLARED, source=SRC))
    r = critical_load(material("al6061-t6"), a, LoadMode.TENSION)
    assert r.value == pytest.approx(27600.0, rel=1e-12)


def test_break_threshold_result_is_a_joint_break_threshold_marked_simplified():
    r = critical_load(material("steel-a36"), SolidCircle(length(0.010)), LoadMode.SHEAR)
    assert isinstance(r.quantity, BreakThreshold)
    assert r.model == SIMPLIFIED_MODEL_LABEL == "단순화 모델"
    assert SIMPLIFIED_MODEL_LABEL in r.labels
    assert SIMPLIFIED_MODEL_LABEL in r.quantity.source.ref and "not FEM" in r.quantity.source.ref
    assert r.quantity.badge is Badge.ESTIMATE  # a simplified model's number is an estimate, not cited and not simulated
    # it goes into a Joint as is
    joint = Joint(
        id="j1",
        kind=JointKind.FIXED,
        a={"instance": "a", "snap_point": "p"},
        b={"instance": "b", "snap_point": "q"},
        break_threshold=r.quantity,
    )
    assert joint.break_threshold.value == r.value


def test_break_threshold_carries_citations_with_locators():
    shear = critical_load(material("steel-a36"), SolidCircle(length(0.010)), LoadMode.SHEAR)
    tension = critical_load(material("al6061-t6"), SolidCircle(length(0.010)), LoadMode.TENSION)
    assert any("Eq. (5-21)" in c and "Sec. 5-5" in c and "(1.9)" in c and "(1.10)" in c for c in shear.citations)
    assert any("Eq. (1.5)" in c and "Sec. 1.2A" in c for c in tension.citations)
    assert shear.quantity.source.locator == shear.citations[0] and tension.quantity.source.locator == tension.citations[0]


@pytest.mark.parametrize(
    "material_id, basis",
    [
        ("al6061-t6", StrengthBasis.TYPICAL),
        ("cfrp-8552-as4-pw", StrengthBasis.TYPICAL),
        ("pom-delrin-150", StrengthBasis.TYPICAL),
        ("steel-a36", StrengthBasis.SPECIFIED_MINIMUM),
        ("ti-6al-4v", StrengthBasis.SPECIFIED_MINIMUM),
    ],
)
def test_break_threshold_surfaces_the_mixed_strength_basis(material_id, basis):
    m = material(material_id)
    assert strength_basis(m.yield_strength) is basis
    r = critical_load(m, SolidCircle(length(0.010)), LoadMode.TENSION)
    assert r.strength_basis is basis
    word = "대표값" if basis is StrengthBasis.TYPICAL else "규격 최소값"
    assert any(word in label for label in r.labels)
    assert word in r.quantity.source.ref  # the basis is in the number's own source, so it travels with the joint
    assert any("비교할 수 없다" in label for label in r.labels)  # cross-material comparison is flagged on every result


def test_break_threshold_equal_sections_do_not_rank_materials():
    # Al 6061-T6 (typical 276 MPa) comes out higher than A36 (minimum 248.2 MPa) for the same section. That is the bases, not
    # the materials; both results say so.
    s = SolidCircle(length(0.010))
    al = critical_load(material("al6061-t6"), s, LoadMode.TENSION)
    steel = critical_load(material("steel-a36"), s, LoadMode.TENSION)
    assert al.value > steel.value
    assert al.strength_basis is not steel.strength_basis
    assert all(any("비교할 수 없다" in label for label in r.labels) for r in (al, steel))


def test_break_threshold_cfrp_is_labelled_a_fracture_strength():
    m = material("cfrp-8552-as4-pw")
    assert is_fracture_strength(m.yield_strength)
    assert not is_fracture_strength(material("steel-a36").yield_strength)
    r = critical_load(m, Rectangle(length(0.030), length(0.002)), LoadMode.TENSION)
    assert r.strength_is_fracture
    assert r.value == pytest.approx(828e6 * 0.03 * 0.002, rel=1e-12)  # 49 680 N
    assert any("파단 강도" in label for label in r.labels)
    assert "fracture strength" in r.quantity.source.ref


def test_break_threshold_cfrp_has_no_shear_threshold():
    with pytest.raises(BreakThresholdError, match="fracture strength"):
        critical_load(material("cfrp-8552-as4-pw"), SolidCircle(length(0.010)), LoadMode.SHEAR)


def test_break_threshold_ductile_materials_are_not_labelled_fracture():
    for mid in ("al6061-t6", "steel-a36", "ti-6al-4v", "pom-delrin-150"):
        assert not critical_load(material(mid), SolidCircle(length(0.01)), LoadMode.TENSION).strength_is_fracture


def test_break_threshold_input_badges_cover_strength_and_dimensions():
    r = critical_load(material("steel-a36"), Rectangle(length(0.02), length(0.005)), LoadMode.TENSION)
    assert r.input_badges == (Badge.CITE, Badge.DECLARED, Badge.DECLARED)


def test_break_threshold_unstated_basis_is_said_so():
    m = material("steel-a36")
    stripped = m.model_copy(
        update={"yield_strength": m.yield_strength.model_copy(update={"source": m.yield_strength.source.model_copy(update={"ref": "a datasheet"})})}
    )
    r = critical_load(stripped, SolidCircle(length(0.01)), LoadMode.TENSION)
    assert r.strength_basis is StrengthBasis.UNSTATED
    assert any("적혀 있지 않음" in label for label in r.labels)


def test_break_threshold_assumptions_list_the_limits():
    r = critical_load(material("steel-a36"), SolidCircle(length(0.01)), LoadMode.SHEAR)
    text = " ".join(r.assumptions)
    for word in ("stress concentration", "fatigue", "crack", "anisotropic"):
        assert word in text


@pytest.mark.parametrize(
    "section, message",
    [
        (SolidCircle(length(0.0)), "positive"),
        (SolidCircle(Quantity(value=0.01, unit=Unit.KG, badge=Badge.DECLARED, source=SRC)), "in m"),
        (Rectangle(length(0.02), length(-0.005)), "positive"),
        (Annulus(length(0.004), length(0.008)), "smaller"),
        (Annulus(length(0.008), length(0.008)), "smaller"),
        (DeclaredArea(Quantity(value=1e-4, unit=Unit.M, badge=Badge.DECLARED, source=SRC)), "m\\^2"),
        (DeclaredArea(Quantity(value=0.0, unit=Unit.M2, badge=Badge.DECLARED, source=SRC)), "positive"),
    ],
)
def test_break_threshold_rejects_bad_sections(section, message):
    with pytest.raises(BreakThresholdError, match=message):
        critical_load(material("steel-a36"), section, LoadMode.TENSION)


@pytest.mark.parametrize("planes", [0, 3, -1])
def test_break_threshold_rejects_bad_shear_planes(planes):
    with pytest.raises(BreakThresholdError, match="shear_planes"):
        critical_load(material("steel-a36"), SolidCircle(length(0.01)), LoadMode.SHEAR, shear_planes=planes)


def test_break_threshold_shear_planes_is_for_shear_only():
    with pytest.raises(BreakThresholdError, match="LoadMode.SHEAR only"):
        critical_load(material("steel-a36"), SolidCircle(length(0.01)), LoadMode.TENSION, shear_planes=2)


def test_break_threshold_overflow_is_an_error_not_infinity():
    huge = DeclaredArea(Quantity(value=1e308, unit=Unit.M2, badge=Badge.DECLARED, source=SRC))
    with pytest.raises(BreakThresholdError, match="finite"):
        critical_load(material("steel-a36"), huge, LoadMode.TENSION)


def test_break_threshold_every_catalog_material_gives_a_valid_threshold():
    for entry in load_material_catalog().entries:
        r = critical_load(entry.material, SolidCircle(length(0.01)), LoadMode.TENSION)
        assert math.isfinite(r.value) and r.value > 0.0
        assert r.quantity.unit is Unit.N


@pytest.mark.parametrize("mode", [LoadMode.TENSION, LoadMode.SHEAR])
def test_break_threshold_string_mode_equals_enum_mode(mode):
    m, s = material("steel-a36"), SolidCircle(length(0.010))
    by_enum = critical_load(m, s, mode)
    by_string = critical_load(m, s, mode.value)
    assert by_string == by_enum
    assert by_string.mode is mode


@pytest.mark.parametrize("bad", ["Tension", "bending", "", "shear ", None, 1])
def test_break_threshold_rejects_unknown_mode(bad):
    with pytest.raises(BreakThresholdError, match="mode must be one of"):
        critical_load(material("steel-a36"), SolidCircle(length(0.01)), bad)
