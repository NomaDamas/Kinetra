"""B-07: the five S1 materials and their PBR slots. Run with `uv run pytest packages/core -q -k materials`.

Every physical number in the packaged catalog is a cited, defaulted or estimated `Quantity`. These tests check that
the catalog loads, that no property is bare, that each cited number agrees with the number written in its own
source note, and that a property without a source is rejected.
"""

from __future__ import annotations

import copy
import json
from importlib import resources

import pytest
from pydantic import ValidationError

from kinetra_core import Badge, MaterialCatalog, PbrSlots, load_material_catalog

IDS = ["al6061-t6", "steel-a36", "cfrp-8552-as4-pw", "ti-6al-4v", "pom-delrin-150"]
PROPS = ("density", "yield_strength", "elastic_modulus", "friction")
SLOTS = ("metallic", "roughness", "reflectance")

# (material, property) -> (value in SI, text the source note must contain: the number as the source prints it)
CITED = {
    ("al6061-t6", "density"): (2700.0, "2.70 Mg/m3"),
    ("al6061-t6", "yield_strength"): (2.76e8, "276 MPa"),
    ("al6061-t6", "elastic_modulus"): (6.895e10, "68.95 GPa"),
    ("al6061-t6", "friction"): (0.25, "kinetic 0.25"),
    ("steel-a36", "density"): (7849.0, "0.490 kcf"),
    ("steel-a36", "yield_strength"): (2.482e8, "36 ksi"),
    ("steel-a36", "elastic_modulus"): (1.9995e11, "29,000 ksi"),
        ("cfrp-8552-as4-pw", "density"): (1570.0, "1.57 g/cm3"),
    ("cfrp-8552-as4-pw", "yield_strength"): (8.28e8, "828 MPa"),
    ("cfrp-8552-as4-pw", "elastic_modulus"): (6.8e10, "68 GPa"),
    ("ti-6al-4v", "density"): (4420.0, "4.42 g/cm3"),
    ("ti-6al-4v", "yield_strength"): (8.28e8, "120 ksi"),
    ("ti-6al-4v", "elastic_modulus"): (1.151e11, "16.7 x 10^6 psi"),
    ("ti-6al-4v", "friction"): (0.32, "kinetic 0.32"),
    ("pom-delrin-150", "density"): (1420.0, "1.42 g/cc"),
    ("pom-delrin-150", "yield_strength"): (7.65e7, "11,100 psi"),
    ("pom-delrin-150", "elastic_modulus"): (3.103e9, "450,000 psi"),
    ("pom-delrin-150", "friction"): (0.2, "0.20"),
}


def raw() -> dict:
    return json.loads(resources.files("kinetra_core").joinpath("material_catalog.json").read_text(encoding="utf-8"))


def entry(d: dict, material_id: str) -> dict:
    return next(e for e in d["entries"] if e["material"]["id"] == material_id)


def test_materials_catalog_has_the_five_s1_materials():
    cat = load_material_catalog()
    assert [e.material.id for e in cat.entries] == IDS
    names = " ".join(e.material.name for e in cat.entries).lower()
    for family in ("aluminum", "steel", "cfrp", "titanium", "pom"):
        assert family in names
    assert cat.get("ti-6al-4v").material.density.value == 4420.0
    with pytest.raises(KeyError):
        cat.get("unobtainium")


def test_materials_every_property_has_a_badge_and_a_source():
    for e in load_material_catalog().entries:
        for name in PROPS:
            q = getattr(e.material, name)
            assert isinstance(q.badge, Badge)
            assert q.source.ref.strip(), (e.material.id, name)
            assert q.value > 0 or name == "friction"
            if q.badge is Badge.CITE:
                assert q.source.url or q.source.locator, (e.material.id, name)
        for slot in SLOTS:
            q = getattr(e.pbr, slot)
            assert q.source.ref.strip(), (e.material.id, slot)
        assert e.pbr.base_color.source.ref.strip()


def test_materials_cited_numbers_match_their_own_source_note():
    cat = load_material_catalog()
    for (mid, name), (value, printed) in CITED.items():
        q = getattr(cat.get(mid).material, name)
        assert q.value == pytest.approx(value, rel=1e-9), (mid, name)
        assert q.badge is Badge.CITE, (mid, name)
        assert printed in q.source.ref, (mid, name, printed)
        assert q.source.url or q.source.locator


def test_materials_each_metal_and_plastic_cites_a_retrievable_source():
    cat = load_material_catalog()
    for e in cat.entries:
        for name in ("density", "yield_strength", "elastic_modulus"):
            q = getattr(e.material, name)
            assert q.source.url and q.source.url.startswith("https://"), (e.material.id, name)
            assert "accessed 2026-11-11" in q.source.ref, (e.material.id, name)


def test_materials_value_range_is_recorded_beside_the_chosen_value():
    cat = load_material_catalog()
    ti = cat.get("ti-6al-4v").material
    assert "1034 to 1068 MPa" in ti.yield_strength.source.ref and "Chosen 828 MPa" in ti.yield_strength.source.ref
    assert "107 to 122 GPa" in ti.elastic_modulus.source.ref
    pom = cat.get("pom-delrin-150").material.yield_strength.source.ref
    assert "69 to 76.5 MPa" in pom and "Chosen 76.5 MPa" in pom
    assert "68.3 to 68.95 GPa" in cat.get("al6061-t6").material.elastic_modulus.source.ref
    for mid in ("al6061-t6", "steel-a36", "ti-6al-4v", "pom-delrin-150"):
        assert "Range" in getattr(cat.get(mid).material, "friction").source.ref, mid


def test_materials_catalog_contains_no_matweb_urls_or_figures():
    """MatWeb's terms forbid redistributing its content: the shipped data must not name it, link it or quote it."""
    text = resources.files("kinetra_core").joinpath("material_catalog.json").read_text(encoding="utf-8").lower()
    for banned in ("matweb", "archive.org", "web.archive"):
        assert banned not in text, banned
    # figures that only MatWeb printed for these materials (not on the cited sheets) must not reappear
    for figure in ("68.9 gpa", "75.8 mpa", "3.10 gpa", "113.8 gpa", "880 mpa", "7.85 g/cc"):
        assert figure not in text, figure
    for e in load_material_catalog().entries:
        for name in PROPS:
            url = getattr(e.material, name).source.url or ""
            assert url.startswith("https://") and "matweb" not in url


def test_materials_aluminum_modulus_conversion_is_exact():
    q = load_material_catalog().get("al6061-t6").material.elastic_modulus
    assert q.value == pytest.approx(10.0e3 * 6.894757e6, rel=1e-4)  # 10.0 x 10^3 ksi
    assert "10.0 x 10^3 ksi" in q.source.ref and "68.3 GPa" in q.source.ref and "68.95 GPa" in q.source.ref


def test_materials_proxy_friction_is_an_estimate_not_a_citation():
    cat = load_material_catalog()
    a36 = cat.get("steel-a36").material.friction
    assert a36.badge is Badge.ESTIMATE and "proxy" in a36.source.ref and "1032" in a36.source.ref
    assert a36.value == pytest.approx(0.23)


def test_materials_cfrp_has_no_yield_so_the_field_says_it_holds_tensile_strength():
    cfrp = load_material_catalog().get("cfrp-8552-as4-pw").material
    assert cfrp.yield_strength.value > 0
    ref = cfrp.yield_strength.source.ref
    assert "no yield point" in ref and "STRENGTH" in ref and "fracture" in ref
    # a friction value nobody measured for this laminate must not wear the cite badge
    assert cfrp.friction.badge is Badge.ESTIMATE


def test_materials_defaults_and_estimates_say_why():
    for e in load_material_catalog().entries:
        for name in PROPS:
            q = getattr(e.material, name)
            if q.badge in (Badge.DEFAULT, Badge.ESTIMATE):
                assert len(q.source.ref) > 40, (e.material.id, name)


@pytest.mark.parametrize("material_id", IDS)
@pytest.mark.parametrize("prop", PROPS)
def test_materials_property_without_source_is_rejected(material_id, prop):
    d = raw()
    del entry(d, material_id)["material"][prop]["source"]
    with pytest.raises(ValidationError) as e:
        MaterialCatalog.model_validate(d)
    assert any(err["loc"][-1] == "source" for err in e.value.errors())


@pytest.mark.parametrize("prop", PROPS)
def test_materials_property_without_badge_is_rejected(prop):
    d = raw()
    del entry(d, "steel-a36")["material"][prop]["badge"]
    with pytest.raises(ValidationError):
        MaterialCatalog.model_validate(d)


@pytest.mark.parametrize("bad", ["", "   ", "TBD", "n/a", "none", "출처 없음", "-"])
def test_materials_placeholder_source_is_rejected(bad):
    d = raw()
    entry(d, "al6061-t6")["material"]["density"]["source"]["ref"] = bad
    with pytest.raises(ValidationError):
        MaterialCatalog.model_validate(d)


def test_materials_cited_value_without_locator_or_url_is_rejected():
    d = raw()
    s = entry(d, "al6061-t6")["material"]["yield_strength"]["source"]
    s.pop("url")
    s.pop("locator")
    with pytest.raises(ValidationError, match="locator or source.url"):
        MaterialCatalog.model_validate(d)


def test_materials_wrong_unit_and_nonpositive_values_are_rejected():
    d = raw()
    entry(d, "al6061-t6")["material"]["density"]["unit"] = "g/cm^3"
    with pytest.raises(ValidationError):
        MaterialCatalog.model_validate(d)
    d = raw()
    entry(d, "al6061-t6")["material"]["yield_strength"]["value"] = 0
    with pytest.raises(ValidationError):
        MaterialCatalog.model_validate(d)


def test_materials_duplicate_ids_are_rejected():
    d = raw()
    d["entries"][1] = copy.deepcopy(d["entries"][0])
    with pytest.raises(ValidationError, match="unique"):
        MaterialCatalog.model_validate(d)


def test_materials_pbr_slots_are_in_range_and_follow_metal_or_dielectric():
    cat = load_material_catalog()
    for e in cat.entries:
        for slot in SLOTS:
            assert 0.0 <= getattr(e.pbr, slot).value <= 1.0
        assert e.pbr.base_color.srgb.startswith("#") and len(e.pbr.base_color.srgb) == 7
    for mid in ("al6061-t6", "steel-a36", "ti-6al-4v"):
        assert cat.get(mid).pbr.metallic.value == 1.0
    for mid in ("cfrp-8552-as4-pw", "pom-delrin-150"):
        assert cat.get(mid).pbr.metallic.value == 0.0
    # metal base colors are Filament's cited F0 table, not invented
    assert cat.get("al6061-t6").pbr.base_color.srgb == "#e8eaea"
    assert cat.get("ti-6al-4v").pbr.base_color.srgb == "#c1baaf"
    assert cat.get("steel-a36").pbr.base_color.badge is Badge.CITE


def test_materials_pbr_slots_reject_bad_values_and_missing_sources():
    good = raw()["entries"][0]["pbr"]
    PbrSlots.model_validate(good)
    for slot, v in (("metallic", 1.5), ("roughness", -0.1), ("reflectance", 2)):
        d = copy.deepcopy(good)
        d[slot]["value"] = v
        with pytest.raises(ValidationError):
            PbrSlots.model_validate(d)
    for bad in ("e8eaea", "#E8EAEA", "#e8eae", "#gggggg", "red"):
        d = copy.deepcopy(good)
        d["base_color"]["srgb"] = bad
        with pytest.raises(ValidationError):
            PbrSlots.model_validate(d)
    d = copy.deepcopy(good)
    del d["roughness"]["source"]
    with pytest.raises(ValidationError):
        PbrSlots.model_validate(d)
    d = copy.deepcopy(good)
    del d["base_color"]["source"]
    with pytest.raises(ValidationError):
        PbrSlots.model_validate(d)
    d = copy.deepcopy(good)
    d["roughness"]["unit"] = "Pa"
    with pytest.raises(ValidationError):
        PbrSlots.model_validate(d)


def test_materials_pbr_uses_no_texture_files():
    """No CC0 texture in assets/LEDGER.csv shows these materials, so the slots are parametric. No path may sneak in."""
    text = resources.files("kinetra_core").joinpath("material_catalog.json").read_text(encoding="utf-8")
    assert "assets/scene" not in text
    for ext in (".jpg", ".png", ".exr", ".hdr"):
        assert ext not in text
    d = raw()
    entry(d, "al6061-t6")["pbr"]["albedo_map"] = "assets/scene/earth/grass_ground_diff_1k.jpg"
    with pytest.raises(ValidationError):
        MaterialCatalog.model_validate(d)


def test_materials_catalog_roundtrips_through_json():
    cat = load_material_catalog()
    again = MaterialCatalog.model_validate_json(cat.model_dump_json())
    assert again == cat
