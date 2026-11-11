"""B-02 epic integration (#96): a skeleton built from beam, plate, shell, payload and mount parts has the mass its parts add up to.

The design is `schemas/examples/Project.structural-skeleton.json` (written by `skeleton_sample.py` from the shipped library parts).
Expected masses are hand calculations from the recipes written down again here (box volumes x 2700 kg/m^3 for al6061-t6, B-07), not
read back from the compiler; the two payloads are declared masses. Dimensions are our own `사용자 선언` choices, not a real vehicle.

    uv run pytest packages/engine -q -k structural
"""

from __future__ import annotations

import json
import math
from fractions import Fraction

import pytest
from gltf_validate import validate
from skeleton_sample import EXAMPLE, FIXTURES, MANIFEST, build_project, glb_name, instance_glb, manifest

from kinetra_core import Badge, Project, SetParameter, apply_command, check_placement
from kinetra_engine.parts import PartCache, assembly_mass, mass_properties

RHO = Fraction(2700)  # al6061-t6 in the B-07 catalog [kg/m^3]
F = Fraction


def box(x, y, z):
    return F(x) * F(y) * F(z)


def beam_mass(length: str, h="0.06", fw="0.04", t="0.004") -> Fraction:
    flange = box(length, fw, t)
    web = box(length, t, F(h) - 2 * F(t))
    return RHO * (2 * flange + web)


def plate_mass(length: str, width: str, t="0.005") -> Fraction:
    slab = box(length, width, t)
    rim_y = box(length, t, 2 * F(t))  # two long rims
    rim_x = box(t, F(width) - 2 * F(t), 2 * F(t))  # two short rims between them
    return RHO * (slab + 2 * rim_y + 2 * rim_x)


def mount_mass(length="0.12", width="0.08", wall="0.04") -> Fraction:
    plate = box(F(length) + F("0.008"), F(width) + F("0.008"), "0.006")
    rails = 2 * box(length, "0.004", wall)
    ends = 2 * box("0.004", F(width) + F("0.008"), F(wall) / 2)
    return RHO * (plate + rails + ends)


# Hand sums, in kg. The shell is the 19-box body of docs/architecture/parts-shell.md: volume 8.8e-4 m^3 (default dimensions).
HAND = {
    "keel-beam": beam_mass("0.4"),
    "deck-plate": plate_mass("0.5", "0.3"),
    "body-shell": RHO * F("8.8e-4"),
    "payload-main": F(3),
    "payload-mount": mount_mass(),
    "payload-sensor": F("0.75"),
    "boom-beam": beam_mass("0.3"),
}


@pytest.fixture(scope="module")
def project() -> Project:
    return build_project()


@pytest.fixture(scope="module")
def result(project):
    return assembly_mass(project.design)


def test_structural_hand_sums_are_the_numbers_written_in_the_docs():
    assert float(HAND["keel-beam"]) == pytest.approx(0.57024, rel=1e-12)
    assert float(HAND["deck-plate"]) == pytest.approx(2.2383, rel=1e-12)
    assert float(HAND["body-shell"]) == pytest.approx(2.376, rel=1e-12)
    assert float(HAND["payload-mount"]) == pytest.approx(0.3241728, rel=1e-12)
    assert float(HAND["boom-beam"]) == pytest.approx(0.42768, rel=1e-12)
    assert sum(HAND.values()) == F("9.6863928")


def test_structural_skeleton_has_the_four_kinds_of_part(project):
    parts = {i.part for i in project.design.instances}
    assert {"beam", "plate", "shell", "payload", "payload-mount"} <= parts
    assert len(project.design.instances) == 7 and len(project.design.joints) == 6


def test_structural_skeleton_is_a_valid_placement(project):
    # Joined snap points meet, no two bodies overlap, the whole thing rests on the ground (the keel beam's bottom is z = 0).
    assert check_placement(project) == ()


def test_structural_each_instance_mass_matches_the_hand_calculation(result):
    got = {r.instance: r.mass for r in result.instances}
    assert set(got) == set(HAND)
    for iid, want in HAND.items():
        assert got[iid] == pytest.approx(float(want), rel=1e-12), iid


def test_structural_each_instance_mass_is_mass_properties_of_its_part(project, result):
    parts = {p.id: p for p in project.design.parts}
    mats = {m.id: m for m in project.design.materials}
    for inst, row in zip(project.design.instances, result.instances):
        direct = mass_properties(parts[inst.part], mats.get(inst.material), {p.name: p for p in inst.parameters})
        assert row.instance == inst.id and row.part == inst.part
        assert row.properties == direct  # the very same computation, with its derivation
        assert row.mass == direct.mass.value


def test_structural_total_is_exactly_the_sum_of_the_parts(result):
    masses = [r.mass for r in result.instances]
    assert result.total.value == math.fsum(masses)  # exact: the correctly rounded sum of these floats
    assert result.total.badge is Badge.SIM and result.total.unit.value == "kg"
    assert abs(result.total.value - sum(masses)) < 1e-14  # and the plain left-to-right sum agrees to rounding


def test_structural_total_matches_the_hand_sum(result):
    assert result.total.value == pytest.approx(9.6863928, rel=1e-12)
    assert result.total.value == pytest.approx(float(sum(HAND.values())), rel=1e-12)


def test_structural_total_does_not_depend_on_the_order_of_the_instances(project):
    design = project.design
    forward = assembly_mass(design).total.value
    backward = assembly_mass(design.model_copy(update={"instances": tuple(reversed(design.instances))})).total.value
    assert forward == backward


def test_structural_joints_and_poses_add_no_mass(project):
    design = project.design
    loose = design.model_copy(update={"joints": ()})
    assert assembly_mass(loose).total.value == assembly_mass(design).total.value


def test_structural_cache_gives_the_same_masses(project, result):
    cached = assembly_mass(project.design, PartCache(max_entries=16))
    assert cached.total.value == result.total.value
    assert [r.mass for r in cached.instances] == [r.mass for r in result.instances]


def test_structural_total_follows_a_parameter_command(project, result):
    # Make the keel beam 0.1 m longer: total rises by the hand-calculated mass of 0.1 m of that section.
    keel = next(i for i in project.design.instances if i.id == "keel-beam")
    value = next(p for p in keel.parameters if p.name == "length").model_copy(update={"value": 0.5})
    edited = apply_command(project, SetParameter(type="set_parameter", instance="keel-beam", parameter=value)).project
    want = float(sum(HAND.values()) - HAND["keel-beam"] + beam_mass("0.5"))
    assert assembly_mass(edited.design).total.value == pytest.approx(want, rel=1e-12)
    assert assembly_mass(edited.design).total.value > result.total.value


def test_structural_declared_masses_are_the_declared_masses_and_the_badges_are_kept(result):
    by = {r.instance: r for r in result.instances}
    assert by["payload-main"].mass == pytest.approx(3.0, rel=1e-12) and by["payload-sensor"].mass == pytest.approx(0.75, rel=1e-12)
    assert by["payload-main"].material is None
    assert Badge.DECLARED in by["payload-main"].properties.derivation.input_badges
    assert set(result.input_badges) == {Badge.CITE, Badge.DEFAULT, Badge.DECLARED}  # density cite, recipe default, mass/length declared


def test_structural_missing_material_names_the_instance(project):
    design = project.design
    bare = design.model_copy(update={"instances": tuple(i.model_copy(update={"material": None}) if i.id == "keel-beam" else i for i in design.instances)})
    with pytest.raises(ValueError, match="instance 'keel-beam'"):
        assembly_mass(bare)


def test_structural_an_empty_design_weighs_nothing():
    empty = Project.model_validate({"world": {"planet": "earth"}})
    r = assembly_mass(empty.design)
    assert r.instances == () and r.total.value == 0.0


# ---- the committed files are what the code writes today ----------------------------------------------------------------


def test_structural_example_project_is_current(project):
    from kinetra_core import export_json

    assert EXAMPLE.read_bytes() == export_json(project), "run: uv run python packages/engine/tests/skeleton_sample.py"


def test_structural_manifest_is_current(project):
    assert json.loads(MANIFEST.read_text(encoding="utf-8")) == manifest(project), "run: uv run python packages/engine/tests/skeleton_sample.py"


def test_structural_glb_per_instance_is_current_and_valid(project):
    for inst in project.design.instances:
        data = (FIXTURES / glb_name(inst.id)).read_bytes()
        assert data == instance_glb(project.design, inst.id), inst.id
        assert validate(data).doc["asset"]["version"] == "2.0"
    assert sorted(p.name for p in FIXTURES.glob("*.glb")) == sorted(glb_name(i.id) for i in project.design.instances)
