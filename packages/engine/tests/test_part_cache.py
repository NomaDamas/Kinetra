"""B-01d: the compile cache keyed by definition hash.

A cached answer must equal the uncached one, and a changed input must never be served a stale answer. The second is
tested by changing every leaf of a part's JSON in turn (not a hand-picked list of fields) and by changing each of the
other inputs (material, parameter values, look) one at a time. Test dimensions are fixtures declared by the test.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

import pytest
from gltf_samples import (
    ROT_X90,
    ax,
    box,
    catalog_material,
    cyl,
    glossy_dielectric,
    mounting_plate,
    q,
    sphere,
    user_material,
    width_param,
)

from kinetra_core import PartDef, Quantity
from kinetra_engine.parts import (
    PartCache,
    ShapeError,
    collision_proxy,
    part_key,
    mass_properties,
    material_key,
    part_glb,
)

AL = "al6061-t6"


def plate() -> PartDef:
    return mounting_plate()


def width(value: float, badge: str = "declared", unit: str = "m") -> dict[str, Quantity]:
    """A `width` override: declared by the test, or any other badge (the source says it is a fixture either way)."""
    return {"width": Quantity(value=value, unit=unit, badge=badge, source={"ref": "B-01d test fixture"})}


def with_snap_point_and_spec() -> PartDef:
    """The plate plus a snap point and a spec, so the hash is tested over every section of a `PartDef`."""
    d = plate().model_dump(mode="json")
    declared = {"badge": "declared", "source": {"ref": "B-01d test fixture"}}
    d["snap_points"] = [
        {
            "id": "mount",
            "kind": "bolt",
            "accepts": ["bolt"],
            "position": {"x": ax(0.0, [("width", 0.5)]), "y": ax(0.0), "z": ax(0.01)},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            **declared,
        }
    ]
    d["specs"] = [{"name": "rated_load", "value": 100.0, "unit": "N", **declared}]
    return PartDef.model_validate(d)


# ---- the cache returns what the compiler returns ---------------------------------------------------------------------


def test_cache_returns_the_same_results_as_compiling_directly():
    cache, part, al = PartCache(max_entries=8), plate(), catalog_material(AL)
    assert cache.mass_properties(part, al) == mass_properties(part, al)
    assert cache.collision_proxy(part) == collision_proxy(part)
    assert cache.part_glb(part, al) == part_glb(part, al)
    # ... also with parameter overrides and an explicit look.
    over = width(0.15)
    assert cache.mass_properties(part, al, over) == mass_properties(part, al, over)
    assert cache.collision_proxy(part, over) == collision_proxy(part, over)
    assert cache.part_glb(part, al, over, glossy_dielectric()) == part_glb(part, al, over, glossy_dielectric())


def test_cache_second_call_is_a_hit_and_returns_the_stored_object():
    cache, part, al = PartCache(max_entries=8), plate(), catalog_material(AL)
    first = cache.mass_properties(part, al)
    assert cache.mass_properties(part, al) is first
    proxy = cache.collision_proxy(part)
    assert cache.collision_proxy(part) is proxy
    glb = cache.part_glb(part, al)
    assert cache.part_glb(part, al) is glb
    s = cache.stats()
    assert (s.hits, s.misses, s.entries, s.evictions) == (3, 3, 3, 0)


def test_cache_hits_for_an_equal_definition_built_separately():
    """The key is the value, not the object: the same JSON read twice, in any key order, is one entry."""
    cache, al = PartCache(max_entries=8), catalog_material(AL)
    d = plate().model_dump(mode="json")
    reordered = json.loads(json.dumps(d, sort_keys=True))  # same data, object keys in another order
    a, b = PartDef.model_validate(d), PartDef.model_validate(reordered)
    assert a is not b and a == b
    assert part_key(a) == part_key(b)
    assert cache.mass_properties(a, al) is cache.mass_properties(b, al)
    assert cache.stats().misses == 1


def test_cache_is_identical_across_processes_and_hash_seeds():
    """`part_key` must not use Python's `hash()` (salted per process): the same part gives the same hex digest."""
    code = (
        "import sys; sys.path.insert(0, 'packages/engine/tests')\n"
        "from gltf_samples import mounting_plate, catalog_material\n"
        "from kinetra_engine.parts import part_key, material_key\n"
        f"print(part_key(mounting_plate()), material_key(catalog_material('{AL}')))\n"
    )
    root = Path(__file__).resolve().parents[3]
    outs = set()
    for seed in ("1", "2", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
        outs.add(subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True).stdout)
    assert len(outs) == 1
    assert outs.pop().split() == [part_key(plate()), material_key(catalog_material(AL))]


# ---- a changed input is never served a stale answer ------------------------------------------------------------------


def _leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, path + (i,))
    else:
        yield path, node


_ALTERNATIVE = {"declared": "estimate", "add": "subtract", "subtract": "add"}  # badge and operation: another valid value


def _changed(value):
    if isinstance(value, str) and value in _ALTERNATIVE:
        return _ALTERNATIVE[value]
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1.0e-3 if abs(value) < 100 else value * 1.001
    if isinstance(value, str):
        return value + "x"
    return None  # null: not changed to anything (an absent optional)


def test_cache_part_key_changes_with_every_leaf_of_the_definition():
    """Change each field of the part's JSON, one at a time. Every change that still validates is a different hash, and
    nothing is skipped silently: the count of leaves changed is asserted, so a new section of `PartDef` that the hash
    ignored would show up as a failing assertion rather than as a stale hit."""
    base = with_snap_point_and_spec()
    d = base.model_dump(mode="json")
    seen = skipped = optional = 0
    for path, value in _leaves(d):
        new = _changed(value)
        if new is None:
            optional += 1
            continue
        mutated = copy.deepcopy(d)
        node = mutated
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = new
        try:
            part = PartDef.model_validate(mutated)
        except ValueError:
            skipped += 1  # the change breaks a rule of the model (a unit, a pattern, a quaternion norm): not a part
            continue
        assert part_key(part) != part_key(base), f"hash ignores {path}"
        seen += 1
    # Everything that is not an absent optional was either a valid different part (a different hash) or broke a rule of the
    # model (a unit, a pattern, a quaternion norm, a primitive kind), which no cache is asked about.
    assert seen + skipped + optional == sum(1 for _ in _leaves(d))
    assert seen >= 50 and seen > 2 * skipped, (seen, skipped)


def test_cache_part_key_sees_order():
    """Order is part of the value: swapping two components changes the glb node order and the floating-point sums."""
    base = plate().model_dump(mode="json")
    swapped = copy.deepcopy(base)
    comps = swapped["shape"]["components"]
    comps[0], comps[1] = comps[1], comps[0]
    assert part_key(PartDef.model_validate(swapped)) != part_key(PartDef.model_validate(base))


def test_cache_changed_dimension_is_a_miss_with_the_new_result():
    cache, al = PartCache(max_entries=8), catalog_material(AL)
    a = plate()
    d = a.model_dump(mode="json")
    d["shape"]["components"][0]["primitive"]["size_y"]["offset"] = 0.3
    b = PartDef.model_validate(d)
    ma, mb = cache.mass_properties(a, al), cache.mass_properties(b, al)
    assert ma.mass.value != mb.mass.value
    assert mb == mass_properties(b, al)
    assert cache.stats().misses == 2


def test_cache_changed_badge_or_source_is_a_miss_because_the_result_carries_them():
    cache, al = PartCache(max_entries=8), catalog_material(AL)
    a = plate()
    d = a.model_dump(mode="json")
    d["shape"]["badge"] = "estimate"
    b = PartDef.model_validate(d)
    assert cache.mass_properties(a, al).derivation.shape.badge.value == "declared"
    assert cache.mass_properties(b, al).derivation.shape.badge.value == "estimate"
    d2 = a.model_dump(mode="json")
    d2["shape"]["source"]["ref"] = "another source"
    assert cache.mass_properties(PartDef.model_validate(d2), al).derivation.shape.source.ref == "another source"


def test_cache_material_matters_for_mass_and_glb_but_not_for_the_proxy():
    cache, part = PartCache(max_entries=16), plate()
    al, steel = catalog_material(AL), catalog_material("steel-a36")
    assert cache.mass_properties(part, al).mass.value != cache.mass_properties(part, steel).mass.value
    assert cache.part_glb(part, al) != cache.part_glb(part, steel)  # density is not in a glb, the look is
    assert material_key(al) != material_key(steel)
    before = cache.stats()
    p1, p2 = cache.collision_proxy(part), cache.collision_proxy(part)
    assert p1 is p2
    assert cache.stats().misses == before.misses + 1  # the proxy was computed once for any material


def test_cache_material_with_the_same_id_but_another_density_is_a_miss():
    cache, part = PartCache(max_entries=8), plate()
    d = catalog_material(AL).model_dump(mode="json")
    d["density"]["value"] *= 1.5
    heavy = type(catalog_material(AL)).model_validate(d)
    assert heavy.id == catalog_material(AL).id
    assert cache.mass_properties(part, heavy).mass.value == pytest.approx(
        1.5 * cache.mass_properties(part, catalog_material(AL)).mass.value, rel=1e-12
    )


def test_cache_parameter_values_are_part_of_the_key():
    cache, part, al = PartCache(max_entries=16), plate(), catalog_material(AL)
    default = cache.mass_properties(part, al)
    wide = cache.mass_properties(part, al, width(0.2))
    assert wide.mass.value > default.mass.value
    assert cache.mass_properties(part, al, width(0.2)) is wide  # the same override again is a hit
    # An override equal to the part's default (same value, unit, badge, source) is the default.
    explicit_default = {"width": part.parameters[0].default}
    assert cache.mass_properties(part, al, explicit_default) is default
    # The same number with another badge is another input: the result carries the badge.
    other_badge = cache.mass_properties(part, al, width(0.2, "estimate"))
    assert other_badge is not wide
    assert other_badge.derivation.parameters[0].value.badge.value == "estimate"
    assert wide.derivation.parameters[0].value.badge.value == "declared"


def test_cache_explicit_look_is_part_of_the_glb_key():
    cache, part, pom = PartCache(max_entries=8), plate(), catalog_material("pom-delrin-150")
    catalog = cache.part_glb(part, pom)
    glossy = cache.part_glb(part, pom, pbr=glossy_dielectric())
    assert catalog != glossy
    assert cache.part_glb(part, pom, pbr=glossy_dielectric()) is glossy
    assert cache.part_glb(part, pom) is catalog


def test_cache_user_material_outside_the_catalog_has_its_own_entries():
    cache, part = PartCache(max_entries=8), plate()
    user = user_material()
    assert cache.part_glb(part, user) == part_glb(part, user)
    assert cache.mass_properties(part, user) == mass_properties(part, user)


# ---- bad input, bounds, concurrency ----------------------------------------------------------------------------------


def test_cache_rejects_what_the_compiler_rejects_and_stores_nothing():
    cache, al = PartCache(max_entries=8), catalog_material(AL)
    part = plate()
    for call in (
        lambda: cache.mass_properties(part, al, width(0.5)),  # outside [0.1, 0.2]
        lambda: cache.collision_proxy(part, {"nope": width(0.1)["width"]}),  # unknown parameter
        lambda: cache.part_glb(part, al, width(0.15, unit="kg")),  # wrong unit
    ):
        with pytest.raises(ShapeError):
            call()
        with pytest.raises(ShapeError):
            call()
    no_shape = PartDef.model_validate({"id": "bare", "name": "bare"})
    with pytest.raises(ShapeError, match="no shape recipe"):
        cache.mass_properties(no_shape, al)
    overlap = PartDef.model_validate(
        {
            "id": "overlap",
            "name": "overlap",
            "shape": {
                "badge": "declared",
                "source": {"ref": "B-01d test fixture"},
                "components": [box("a", 0.2, 0.2, 0.2), box("b", 0.2, 0.2, 0.2, at=(0.1, 0, 0))],
            },
        }
    )
    with pytest.raises(ShapeError, match="overlap"):
        cache.mass_properties(overlap, al)
    with pytest.raises(ShapeError, match="overlap"):
        cache.mass_properties(overlap, al)
    s = cache.stats()
    assert (s.entries, s.hits, s.misses) == (0, 0, 0)


def test_cache_evicts_the_least_recently_used_entry():
    cache, al = PartCache(max_entries=2), catalog_material(AL)
    part = plate()
    a = cache.mass_properties(part, al, width(0.12))
    b = cache.mass_properties(part, al, width(0.14))
    assert cache.mass_properties(part, al, width(0.12)) is a  # a is now the most recent
    cache.mass_properties(part, al, width(0.16))  # evicts b, the least recently used
    s = cache.stats()
    assert (s.entries, s.evictions, s.max_entries) == (2, 1, 2)
    assert cache.mass_properties(part, al, width(0.12)) is a  # still there
    again = cache.mass_properties(part, al, width(0.14))
    assert again == b and again is not b  # was evicted: recomputed, equal but a new object


def test_cache_clear_empties_entries_and_keeps_counters():
    cache, al = PartCache(max_entries=4), catalog_material(AL)
    first = cache.mass_properties(plate(), al)
    cache.mass_properties(plate(), al)
    cache.clear()
    s = cache.stats()
    assert (s.entries, s.hits, s.misses) == (0, 1, 1)
    again = cache.mass_properties(plate(), al)
    assert again == first and again is not first


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, None, "3"])
def test_cache_requires_a_positive_integer_size(bad):
    with pytest.raises(ValueError, match="max_entries"):
        PartCache(max_entries=bad)


def test_cache_is_safe_to_share_between_threads():
    cache, part, al = PartCache(max_entries=64), plate(), catalog_material(AL)
    widths = [0.12 + 0.002 * i for i in range(20)]
    expected = {w: mass_properties(part, al, width(w)) for w in widths}
    errors: list[BaseException] = []

    def work():
        try:
            for _ in range(5):
                for w in widths:
                    assert cache.mass_properties(part, al, width(w)) == expected[w]
        except BaseException as e:  # noqa: BLE001 - report any failure from the worker thread
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    s = cache.stats()
    assert s.entries == len(widths)
    assert s.hits + s.misses == 8 * 5 * len(widths)


def test_cache_every_primitive_kind_round_trips():
    """Box, cylinder and sphere parts with a rotated element: cached equals compiled."""
    part = PartDef.model_validate(
        {
            "id": "mixed",
            "name": "mixed",
            "parameters": [width_param(0.1)],
            "shape": {
                "badge": "declared",
                "source": {"ref": "B-01d test fixture"},
                "components": [
                    box("b", ax(0.0, [("width", 1.0)]), 0.1, 0.1),
                    cyl("c", 0.02, 0.2, at=(0.0, 0.0, 0.2), quat=ROT_X90),
                    sphere("s", 0.03, at=(0.0, 0.0, -0.2)),
                ],
            },
        }
    )
    cache, al = PartCache(max_entries=4), catalog_material(AL)
    assert cache.mass_properties(part, al) == mass_properties(part, al)
    assert cache.collision_proxy(part) == collision_proxy(part)
    assert cache.part_glb(part, al) == part_glb(part, al)


class _ShiftingMapping(Mapping):
    """A caller's mapping that answers with `first` the first time it is read and with `later` every time after: a
    mapping that another thread changes between the cache computing its key and compiling."""

    def __init__(self, first, later):
        self._values = [first, later]
        self.reads = 0

    def _current(self):
        return self._values[min(self.reads, 1)]

    def __iter__(self):
        value = self._current()
        self.reads += 1
        return iter(value)

    def __len__(self):
        return len(self._values[0])

    def __getitem__(self, name):
        return self._values[min(self.reads - 1, 1) if self.reads else 0][name]


@pytest.mark.parametrize("kind", ["mass", "proxy", "glb"])
def test_cache_key_and_compile_use_one_snapshot_of_the_parameters(kind):
    """The parameter values are read once. A mapping that changes after that read cannot make the cache store the result
    of other values under the key of the first, which a later call with the first values would be served."""
    al, part = catalog_material(AL), plate()

    def call(cache, params):
        if kind == "mass":
            return cache.mass_properties(part, al, params)
        if kind == "proxy":
            return cache.collision_proxy(part, params)
        return cache.part_glb(part, al, params)

    def direct(params):
        if kind == "mass":
            return mass_properties(part, al, params)
        if kind == "proxy":
            return collision_proxy(part, params)
        return part_glb(part, al, params)

    cache = PartCache(max_entries=8)
    shifting = _ShiftingMapping(width(0.12), width(0.19))
    stored = call(cache, shifting)
    assert shifting.reads >= 1
    assert stored == direct(width(0.12))  # the values the key was made from
    assert call(cache, width(0.12)) is stored  # a later call with those values gets the right entry
    assert call(cache, width(0.19)) != stored  # and the other values are not served from it


def test_cache_a_dict_changed_after_the_call_does_not_change_what_was_stored():
    cache, part, al = PartCache(max_entries=8), plate(), catalog_material(AL)
    params = width(0.12)
    stored = cache.mass_properties(part, al, params)
    params["width"] = width(0.19)["width"]
    assert cache.mass_properties(part, al, width(0.12)) is stored
    assert cache.mass_properties(part, al, params).mass.value > stored.mass.value
