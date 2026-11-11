"""W-01: planet data files and loader (`-k bodies`). The numbers are the data files' own; tests check structure,
badges, sources, cross-checks between a value and what its source text says, and that no code carries a gravity."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinetra_core import (
    BODIES_DIR,
    BODY_IDS,
    PLANET_CONSTANT_NAMES,
    Badge,
    Body,
    Unit,
    World,
    check_world_references,
    load_bodies,
    load_body,
)

REPO = Path(__file__).resolve().parents[3]


def raw(body_id):
    return json.loads((BODIES_DIR / f"{body_id}.json").read_text(encoding="utf-8"))


def quantities(body):
    d = body.ground_friction.distribution
    return {
        "gravity": body.gravity,
        "atmosphere_density": body.atmosphere_density,
        "insolation": body.insolation,
        "ground_friction.value": body.ground_friction.value,
        "ground_friction.distribution": d,
    }


def test_bodies_three_planets_load_with_expected_ids():
    bodies = load_bodies()
    assert tuple(bodies) == BODY_IDS == ("earth", "mars", "moon")
    for i, b in bodies.items():
        assert b.id == i
    assert sorted(p.name for p in BODIES_DIR.glob("*.json")) == ["earth.json", "mars.json", "moon.json"]


def test_bodies_every_item_has_badge_source_and_access_date():
    for b in load_bodies().values():
        for name, q in quantities(b).items():
            assert q.badge in set(Badge), (b.id, name)
            assert re.search(r"accessed 2026-11-11", q.source.ref), (b.id, name, "no access date")
            assert q.source.ref and (q.source.url or q.source.locator), (b.id, name)
            if q.source.url:
                assert q.source.url.startswith("https://"), (b.id, name)


def test_bodies_cited_values_say_where_in_the_source():
    for b in load_bodies().values():
        for name, q in quantities(b).items():
            if q.badge is Badge.CITE:
                assert q.source.locator and q.source.url, (b.id, name)


def test_bodies_units_are_si_and_closed_vocabulary():
    for b in load_bodies().values():
        assert b.gravity.unit is Unit.M_PER_S2
        assert b.atmosphere_density.unit is Unit.KG_PER_M3
        assert b.insolation.unit is Unit.W_PER_M2
        assert b.ground_friction.value.unit is Unit.ONE


@pytest.mark.parametrize(
    "body_id, g, rho, s",
    [("earth", 9.80665, 1.217, 1361.0), ("mars", 3.73, 0.016, 586.2), ("moon", 1.62, 0.0, 1361.0)],
)
def test_bodies_values_match_what_their_sources_print(body_id, g, rho, s):
    """Values as printed on the NASA NSSDCA fact sheets read 2026-11-11 (see each `source.ref`)."""
    b = load_body(body_id)
    assert (b.gravity.value, b.atmosphere_density.value, b.insolation.value) == (g, rho, s)


def test_bodies_gravity_ordering_and_cross_checks():
    e, m, moon = (load_body(i) for i in BODY_IDS)
    assert e.gravity.value > m.gravity.value > moon.gravity.value
    # GM/R^2 from the sheets' own GM and mean radius (km^3/s^2, km), within 1% of the printed surface gravity.
    for body, gm, radius in [(e, 398600.0, 6371.0), (m, 42828.0, 3389.5), (moon, 4902.8, 1737.4)]:
        assert body.gravity.value == pytest.approx(gm / radius**2 * 1e3, rel=0.01)
    assert e.atmosphere_density.value > m.atmosphere_density.value > moon.atmosphere_density.value == 0.0
    assert moon.insolation.value == e.insolation.value > m.insolation.value


def test_bodies_ground_friction_is_a_c01c_assumption_with_an_honest_distribution():
    for b in load_bodies().values():
        a = b.ground_friction
        d = a.distribution
        assert a.key == "ground_friction" and a.editable is False
        assert d.kind == "uniform" and 0 < d.low <= a.value.value <= d.high
        assert d.badge is Badge.ESTIMATE and a.value.badge in (Badge.ESTIMATE, Badge.CITE)
        assert a.confidence.value in ("low", "med")  # never "high": no source gives a distribution


def test_bodies_friction_values_are_tangents_of_the_angles_in_their_sources():
    """Each nominal is tan(angle in degrees) where the angle is written in `source.ref`."""
    for b in load_bodies().values():
        for q in (b.ground_friction.value, b.ground_friction.distribution):
            for ang, val in re.findall(r"tan\((\d+(?:\.\d+)?) deg\) = (\d+\.\d+)", q.source.ref):
                assert math.tan(math.radians(float(ang))) == pytest.approx(float(val), abs=5e-5), (b.id, ang)
    moon = load_body("moon")
    assert moon.ground_friction.value.badge is Badge.CITE and moon.ground_friction.confidence.value == "med"
    assert load_body("earth").ground_friction.confidence.value == "low"
    assert load_body("mars").ground_friction.confidence.value == "low"


def test_bodies_weak_items_are_marked_unverified_and_cited_ones_are_not():
    expected = {
        "earth": {"ground_friction"},
        "mars": {"ground_friction"},
        "moon": {"atmosphere_density", "ground_friction"},
    }
    for i, b in load_bodies().items():
        assert {u.item for u in b.unverified} == expected[i]
        assert all(len(u.reason) > 40 for u in b.unverified)
    assert load_body("moon").atmosphere_density.badge is Badge.DEFAULT
    assert load_body("moon").atmosphere_density.value == 0.0


@pytest.mark.parametrize("drop", ["earth", "moon"])
def test_bodies_unverified_must_match_badges(drop):
    d = raw(drop)
    d["unverified"] = []
    with pytest.raises(ValidationError, match="must be listed in unverified"):
        Body.model_validate(d)
    d = raw(drop)
    d["unverified"] = d["unverified"] + [{"item": "gravity", "reason": "claimed unverified though cited"}]
    with pytest.raises(ValidationError, match="listed in unverified"):
        Body.model_validate(d)


def test_bodies_a_value_without_badge_or_source_fails():
    for key in ("badge", "source"):
        d = raw("mars")
        del d["gravity"][key]
        with pytest.raises(ValidationError):
            Body.model_validate(d)
    d = raw("mars")
    d["gravity"]["source"]["ref"] = "TBD"
    with pytest.raises(ValidationError, match="placeholder"):
        Body.model_validate(d)
    d = raw("mars")
    d["gravity"]["badge"] = "cite"
    del d["gravity"]["source"]["locator"], d["gravity"]["source"]["url"]
    with pytest.raises(ValidationError, match="locator or source.url"):
        Body.model_validate(d)


def test_bodies_rejects_wrong_units_negative_values_and_unknown_fields():
    d = raw("earth")
    d["gravity"]["unit"] = "m/s"
    with pytest.raises(ValidationError):
        Body.model_validate(d)
    d = raw("earth")
    d["gravity"]["value"] = -9.8
    with pytest.raises(ValidationError):
        Body.model_validate(d)
    d = raw("earth")
    d["ground_friction"]["value"]["unit"] = "m"
    with pytest.raises(ValidationError, match="dimensionless"):
        Body.model_validate(d)
    d = raw("earth")
    d["ground_friction"]["distribution"]["low"] = -0.1
    with pytest.raises(ValidationError, match="below 0"):
        Body.model_validate(d)
    d = raw("earth")
    d["wind"] = 1
    with pytest.raises(ValidationError):
        Body.model_validate(d)


def test_bodies_loader_errors(tmp_path):
    with pytest.raises(KeyError, match="unknown planet"):
        load_body("venus")
    with pytest.raises(FileNotFoundError, match="not found"):
        load_body("earth", directory=tmp_path)
    d = raw("earth")
    (tmp_path / "earth.json").write_text(json.dumps({**d, "id": "mars"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must equal the file name"):
        load_body("earth", directory=tmp_path)
    (tmp_path / "earth.json").write_text(json.dumps(d), encoding="utf-8")
    assert load_body("earth", directory=tmp_path) == load_body("earth")


def test_bodies_world_names_planet_that_exists_and_materials_of_the_project():
    src = {"ref": "unit-test fixture", "locator": "test_bodies.py"}
    size = {"value": 1.0, "unit": "m", "badge": "declared", "source": src}
    prop = {
        "kind": "step",
        "id": "prop-a",
        "material": "oak",
        "placement": {"x": 0.0, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": src},
        "length": size,
        "width": size,
        "height": size,
    }
    world = World.model_validate({"planet": "mars", "terrain_props": [prop]})
    check_world_references(world, planets=BODY_IDS, materials=["oak"])
    with pytest.raises(ValueError, match="unknown material 'oak'"):
        check_world_references(world, planets=BODY_IDS, materials=[])
    ghost = World.model_validate({"planet": "venus", "terrain_props": [{**prop, "material": None}]})
    with pytest.raises(ValueError, match="unknown planet 'venus'"):
        check_world_references(ghost, planets=BODY_IDS, materials=[])
    with pytest.raises(ValueError) as e:
        check_world_references(
            World.model_validate({"planet": "venus", "terrain_props": [prop]}), planets=BODY_IDS, materials=[]
        )
    assert "venus" in str(e.value) and "oak" in str(e.value)  # every problem is listed


def test_bodies_world_rejects_planet_constants_so_the_data_files_are_their_only_home():
    assert {"gravity", "air_density", "ground_friction", "insolation"} <= PLANET_CONSTANT_NAMES
    with pytest.raises(ValidationError, match="data/bodies"):
        World.model_validate({"planet": "earth", "gravity": 9.8})


# --- no gravity literal in engine or client code ---------------------------------------------------------------

CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".html", ".wgsl", ".glsl"}
CODE_ROOTS = ["packages/core/src", "packages/engine/src", "packages/judge/src", "packages/ui", "apps", "scripts"]
SKIP_DIRS = {"node_modules", ".venv", "dist", "build", "__pycache__", ".next", ".svelte-kit", "coverage", "tests", "test"}
NUMBER = re.compile(r"(?<![\w.])(\d+\.\d+|\d+)(?:[eE][+-]?\d+)?(?![\w.])")
GRAVITY_ROUNDINGS = (9.80665, 9.8067, 9.807, 9.81, 9.8, 9.82, 9.78, 9.832, 3.73, 3.72, 3.71, 3.69, 3.7, 1.62, 1.622, 1.625, 1.63)


def gravity_literals():
    """Numbers a gravity could be written as: the three data-file values and their usual roundings."""
    vals = {b.gravity.value for b in load_bodies().values()} | set(GRAVITY_ROUNDINGS)
    return {f"{v:g}" for v in vals} | {repr(v) for v in vals}


def scan_for_gravity_literals(root: Path, roots=CODE_ROOTS):
    bad = gravity_literals()
    hits = []
    for r in roots:
        base = root / r
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in CODE_SUFFIXES or SKIP_DIRS & set(p.relative_to(base).parts):
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                code = re.sub(r"(#|//).*$", "", line)  # numbers in comments are prose
                for m in NUMBER.finditer(code):
                    if m.group(0) in bad:
                        hits.append(f"{p.relative_to(root)}:{n}: {m.group(0)}")
    return hits


def test_bodies_no_gravity_literal_in_engine_or_client_code():
    assert scan_for_gravity_literals(REPO) == []


@pytest.mark.parametrize("literal", ["9.81", "9.80665", "3.73", "3.71", "1.62", "9.8"])
def test_bodies_gravity_literal_scan_detects_a_planted_literal(tmp_path, literal):
    (tmp_path / "packages" / "engine" / "src").mkdir(parents=True)
    (tmp_path / "apps" / "studio" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "engine" / "src" / "sim.py").write_text(f"G = {literal}\n", encoding="utf-8")
    (tmp_path / "apps" / "studio" / "src" / "scene.ts").write_text(f"const gravity = [0, 0, -{literal}];\n", encoding="utf-8")
    hits = scan_for_gravity_literals(tmp_path)
    assert any("sim.py:1" in h for h in hits) and any("scene.ts:1" in h for h in hits)


def test_bodies_gravity_literal_scan_ignores_comments_identifiers_and_longer_numbers(tmp_path):
    (tmp_path / "packages" / "engine" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "engine" / "src" / "ok.py").write_text(
        "x = 1  # g = 9.81 on Earth\nv1_62 = 19.81 + 3.7301 + 21.62\n", encoding="utf-8"
    )
    assert scan_for_gravity_literals(tmp_path) == []
