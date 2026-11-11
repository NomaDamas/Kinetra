"""B-01d: the second trial part, added by following `docs/process/add-part.md` step by step (its timing is in the guide).

`fixtures/parts/trial-spacer.json` is a test declaration (`사용자 선언`), not a real part: two 0.1 m x 0.1 m blocks of height
`height` side by side, the second turned 45 degrees about z and touching the first. Expected values are hand calculations.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from gltf_samples import catalog_material
from gltf_validate import validate

from kinetra_core import PartDef, Quantity
from kinetra_engine.parts import ShapeError, collision_proxy, mass_properties, part_glb

TRIAL = Path(__file__).parent / "fixtures" / "parts" / "trial-spacer.json"
SRC = {"ref": "B-01d test fixture"}
STEEL = catalog_material("steel-a36")
RHO = 7849.0  # steel-a36 in material_catalog.json (B-07)


@pytest.fixture(scope="module")
def spacer() -> PartDef:
    return PartDef.model_validate_json(TRIAL.read_text(encoding="utf-8"))


def height(v: float, unit: str = "m") -> dict[str, Quantity]:
    return {"height": Quantity(value=v, unit=unit, badge="declared", source=SRC)}


@pytest.mark.parametrize("h", [0.05, 0.1, 0.3])
def test_trial_spacer_mass_and_centre_follow_the_height(spacer, h):
    volume = 2 * 0.1 * 0.1 * h  # two 0.1 x 0.1 x h blocks (the turned one is the same block turned about z)
    r = mass_properties(spacer, STEEL, None if h == 0.1 else height(h))
    assert r.volume.value == pytest.approx(volume, rel=1e-12)
    assert r.mass.value == pytest.approx(RHO * volume, rel=1e-12)
    assert r.center_of_mass.z == pytest.approx(h / 2, abs=1e-12)
    d = 0.05 + 0.05 * math.sqrt(2)  # the turned block touches the first: 0.05 + 0.05 (cos 45 + sin 45)
    assert r.center_of_mass.x == pytest.approx(d / 2, abs=1e-12)
    assert r.center_of_mass.y == pytest.approx(0.0, abs=1e-12)


def test_trial_spacer_inertia_about_z_is_two_square_blocks_and_the_parallel_axis_term(spacer):
    # Each block: Izz = m (0.1^2 + 0.1^2) / 12 about its own centre (a square is the same turned). Two blocks a distance
    # d = 0.05 + 0.05 sqrt 2 apart, each d / 2 from the centre of mass.
    m = RHO * 0.1 * 0.1 * 0.1
    d = 0.05 + 0.05 * math.sqrt(2)
    expected = 2 * (m * 0.02 / 12 + m * (d / 2) ** 2)
    assert mass_properties(spacer, STEEL).inertia.izz == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("bad", [0.04, 0.31])
def test_trial_spacer_rejects_a_height_outside_its_range(spacer, bad):
    with pytest.raises(ShapeError, match="outside the allowed range"):
        mass_properties(spacer, STEEL, height(bad))


def test_trial_spacer_rejects_unknown_and_wrong_unit_parameters(spacer):
    with pytest.raises(ShapeError, match="unknown parameters"):
        mass_properties(spacer, STEEL, {"width": Quantity(value=0.1, unit="m", badge="declared", source=SRC)})
    with pytest.raises(ShapeError, match="need unit"):
        mass_properties(spacer, STEEL, height(0.1, "kg"))


def test_trial_spacer_has_a_proxy_equal_to_its_recipe_and_a_valid_glb(spacer):
    proxy = collision_proxy(spacer)
    assert [g.id for g in proxy.geoms] == ["base", "turned"] and not proxy.filled_voids
    assert proxy.volume_error.value == 0.0
    for h in (0.05, 0.3):
        validate(part_glb(spacer, STEEL, height(h)))


def test_trial_spacer_badges_say_declared(spacer):
    r = mass_properties(spacer, STEEL)
    assert r.derivation.shape.badge.value == "declared"
    assert "declared" in {b.value for b in r.derivation.input_badges}
