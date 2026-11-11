"""B-01d: the add-part procedure (`docs/process/add-part.md`) works as written.

The trial part `fixtures/parts/trial-bracket.json` is a test declaration (`사용자 선언`), not a real part. Expected numbers are
the textbook volume and centroid formulas written out below, not read back from the compiler.
"""

from __future__ import annotations

import json
import math
import re
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

import pytest
from gltf_samples import ROT_X90, box, catalog_material, part
from gltf_validate import validate

from kinetra_core import PartDef
from kinetra_engine.parts import PartCache, ShapeError, mass_properties
from kinetra_engine.parts.__main__ import main

ROOT = Path(__file__).resolve().parents[3]
TRIAL = Path(__file__).parent / "fixtures" / "parts" / "trial-bracket.json"
DOC = ROOT / "docs" / "process" / "add-part.md"
RHO_AL = 2700.0  # al6061-t6 in data/material_catalog.json (B-07)


def run(capsys, *argv) -> tuple[int, dict | None, str]:
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, (json.loads(out.out) if out.out.strip() else None), out.err


def test_add_part_trial_part_is_a_valid_part_definition():
    part_def = PartDef.model_validate_json(TRIAL.read_text(encoding="utf-8"))
    assert part_def.id == "trial-bracket"
    badges = {p.default.badge.value for p in part_def.parameters} | {part_def.shape.badge.value}
    assert badges == {"declared"}  # a trial part cites nothing


def test_add_part_check_command_reports_the_hand_calculated_mass_and_centre(capsys, tmp_path):
    code, report, err = run(capsys, TRIAL, "--material", "al6061-t6", "--out", tmp_path)
    assert code == 0 and err == ""
    # plate 0.1 x 0.06 x 0.01 at the origin; upright 0.02 x 0.06 x 0.05 at (-0.04, 0, 0.03); pin r 0.005, length 0.06 at
    # (-0.04, 0, 0.06); void r 0.008, length 0.01 at (0.02, 0, 0).
    v_plate, v_up = 0.1 * 0.06 * 0.01, 0.02 * 0.06 * 0.05
    v_pin, v_hole = math.pi * 0.005**2 * 0.06, math.pi * 0.008**2 * 0.01
    volume = v_plate + v_up + v_pin - v_hole
    assert report["volume_m3"] == pytest.approx(volume, rel=1e-12)
    assert report["mass_kg"] == pytest.approx(RHO_AL * volume, rel=1e-12)
    x = (v_up * -0.04 + v_pin * -0.04 - v_hole * 0.02) / volume
    z = (v_up * 0.03 + v_pin * 0.06) / volume
    assert report["center_of_mass_m"] == pytest.approx([x, 0.0, z], abs=1e-12)
    # The void is filled in the proxy and not cut out of the drawing: both are named in the report.
    assert report["filled_voids"] == ["hole"] == report["undrawn_voids"]
    assert report["proxy_volume_error"] == pytest.approx(v_hole / volume, rel=1e-12)
    assert report["proxy_geoms"] == 3
    assert set(report["milliseconds"]) == {"mass", "proxy", "glb"}
    glb = (tmp_path / "trial-bracket.glb").read_bytes()
    assert len(glb) == report["glb_bytes"]
    validate(glb)  # the structural check of B-01c


def test_add_part_check_command_names_what_it_rejects(capsys, tmp_path):
    code, report, err = run(capsys, TRIAL, "--material", "unobtainium")
    assert (code, report) == (1, None) and "unknown material 'unobtainium'" in err and "al6061-t6" in err

    code, _, err = run(capsys, tmp_path / "missing.json", "--material", "al6061-t6")
    assert code == 1 and "missing.json" in err

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"id": "x"}), encoding="utf-8")
    code, _, err = run(capsys, bad, "--material", "al6061-t6")
    assert code == 1 and "not a valid PartDef" in err

    overlap = part("overlap", [box("a", 0.2, 0.2, 0.2), box("b", 0.2, 0.2, 0.2, at=(0.1, 0, 0))])
    f = tmp_path / "overlap.json"
    f.write_text(overlap.model_dump_json(), encoding="utf-8")
    code, _, err = run(capsys, f, "--material", "al6061-t6")
    assert code == 1 and "rejected by the part compiler" in err and "overlap" in err


def test_add_part_trial_part_goes_through_the_cache_like_the_studio_will_use_it():
    part_def = PartDef.model_validate_json(TRIAL.read_text(encoding="utf-8"))
    al = catalog_material("al6061-t6")
    cache = PartCache(max_entries=4)
    first = cache.mass_properties(part_def, al)
    assert first == mass_properties(part_def, al)
    assert cache.mass_properties(part_def, al) is first


# ---- the rule the guide gives for touching, rotated elements ----------------------------------------------------------


def _touching_pair(centre_x: float, degrees: float) -> PartDef:
    a = math.radians(degrees)
    q = {"x": 0.0, "y": 0.0, "z": math.sin(a / 2), "w": math.cos(a / 2)}
    return part("pair", [box("a", 0.2, 0.2, 0.2), box("b", 0.2, 0.2, 0.2, at=(centre_x, 0, 0), quat=q)])


def _accepted(centre_x: float, degrees: float) -> bool:
    try:
        mass_properties(_touching_pair(centre_x, degrees), catalog_material("al6061-t6"))
        return True
    except ShapeError:
        return False


@pytest.mark.parametrize("degrees", [20.5, 30.0, 45.0, 60.0])
def test_add_part_rounding_away_from_a_rotated_neighbour_is_always_accepted(degrees):
    """Two 0.2 m cubes, the second turned about z; the exact touching distance is 0.1 + 0.1 (|cos| + |sin|). Rounding it
    up (away from the first cube: a gap of under 10^-d m) is accepted at every digit count, rounding it down (a
    penetration under 10^-d m) is rejected until the error is below the tolerance of 1e-9 x 0.2 m = 2e-10 m."""
    a = math.radians(degrees)
    exact = Decimal(repr(0.1 + 0.1 * (abs(math.cos(a)) + abs(math.sin(a)))))
    for digits in range(3, 13):
        step = Decimal(1).scaleb(-digits)
        assert _accepted(float(exact.quantize(step, rounding=ROUND_CEILING)), degrees), digits
    floored = {d: _accepted(float(exact.quantize(Decimal(1).scaleb(-d), rounding=ROUND_FLOOR)), degrees) for d in range(3, 13)}
    assert not floored[7] and not floored[8]  # the seven-digit trap of part-mass.md
    assert floored[11] and floored[12]  # error well below 2e-10 m


def test_add_part_the_seven_digit_example_of_part_mass_md():
    assert _accepted(0.2414214, 45.0) and not _accepted(0.2414213, 45.0)


def test_add_part_axis_aligned_contact_needs_no_care():
    for gap_free in (0.2, 0.2000000000, 0.2 + 1e-12):
        cubes = part("pair", [box("a", 0.2, 0.2, 0.2), box("b", 0.2, 0.2, 0.2, at=(gap_free, 0, 0))])
        assert mass_properties(cubes, catalog_material("al6061-t6")).mass.value == pytest.approx(RHO_AL * 0.016, rel=1e-12)
    rotated_cylinder = part("rod", [box("a", 0.2, 0.2, 0.2), {**box("r", 0.1, 0.1, 0.1, at=(0.2, 0, 0)), "orientation": ROT_X90}])
    assert mass_properties(rotated_cylinder, catalog_material("al6061-t6")).mass.value > 0


# ---- the guide names things that exist ---------------------------------------------------------------------------------


def test_add_part_guide_names_files_and_commands_that_exist():
    text = DOC.read_text(encoding="utf-8")
    for path in re.findall(r"`((?:packages|docs|schemas|tools)/[\w./-]+)`", text):
        if "<" in path or "*" in path:
            continue
        assert (ROOT / path.split(":")[0]).exists(), f"add-part.md names {path}, which does not exist"
    assert "uv run python -m kinetra_engine.parts" in text
    assert "uv run pytest packages/engine -q -k cache" in text
