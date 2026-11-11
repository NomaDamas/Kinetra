"""Cache of compiled parts, keyed by definition hash (B-01d).

Compiling a part (mass, collision proxy, glb) is a pure function of the part definition, the material, the parameter
values and, for the glb, the look. The same part is asked for again and again (every instance of it, every slider step
back to a value already seen), so `PartCache` remembers the result under a key made of the hashes of exactly those inputs.

    cache = PartCache(max_entries=...)
    cache.mass_properties(part, material, parameters=None) -> MassProperties
    cache.collision_proxy(part, parameters=None) -> CollisionProxy
    cache.part_glb(part, material, parameters=None, pbr=None) -> bytes

A hit returns the object the first call returned (all three are immutable), and a cached answer equals the uncached one
(`tests/test_part_cache.py`). What the key contains, why, and what the cache does not do: `docs/architecture/part-cache.md`.

`part_key` is the hash of one `PartDef` as the compiler sees it, and it is not C-03's `kinetra_core.definition_hash`. That one
puts collections in a canonical order (by id) so a reordered file is the same definition; the compiler is not order-free
(component order changes the floating-point sums and the glb node order), so a cache keyed by it would hand back the result
of the other order. Here any change of value, badge, source text or order is a different key: a stale hit cannot happen,
at the price of a miss when a definition is rewritten into an equal one in another order.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from kinetra_core import CollisionProxy, MassProperties, Material, PartDef, PbrSlots, Quantity

from ._shape import _resolve_parameters
from .collision import collision_proxy
from .mass import mass_properties
from .visual import part_glb

_HASH_VERSION = "kinetra-part-definition/1"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def part_key(part: PartDef) -> str:
    """SHA-256 (hex) of `part` as a value: every field, in field order, in the JSON the model serialises to.

    Equal definitions have equal hashes however they were built (from JSON or from the model, any key order in the file).
    Any difference in a number, unit, badge, source, parameter range, snap point, spec or in the order of components or
    parameters gives a different hash, because order changes the floating-point sums and the glb node order."""
    return _sha256(f"{_HASH_VERSION}\n{part.model_dump_json()}")


def material_key(material: Material) -> str:
    """SHA-256 (hex) of `material` as a value (density and its badge and source, the rest of the properties, the id)."""
    return _sha256(f"{_HASH_VERSION}\n{material.model_dump_json()}")


def _parameters_hash(part: PartDef, parameters: Mapping[str, Quantity] | None) -> str:
    """Hash of the parameter values the compiler will use: the override where given, else the default.

    It is the resolved set, so an override equal to the default (same value, unit, badge and source) is the same key as
    no override. Unknown names, wrong units and out-of-range values raise `ShapeError` here, exactly as compiling would."""
    resolved = _resolve_parameters(part, parameters)
    return _sha256(",".join(f'"{name}":{q.model_dump_json()}' for name, q in resolved.items()))


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int
    entries: int
    max_entries: int


class PartCache:
    """Least-recently-used cache of compile results, safe to share between threads.

    `max_entries` counts results of any kind (a glb is far larger than a mass result; the bound is a count, not bytes).
    There is no default: the right size is the caller's, and nothing here has measured one.

    Only successful results are stored. A part the compiler rejects (`ShapeError`) is rejected again on every call, which
    costs the same as before and keeps a bad recipe out of memory. Two threads that miss the same key at once both compute;
    the results are equal, one is stored, and both count as misses."""

    def __init__(self, *, max_entries: int) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError(f"max_entries must be an integer of at least 1, got {max_entries!r}")
        self._max = max_entries
        self._entries: OrderedDict[tuple[str, ...], Any] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = self._misses = self._evictions = 0

    def _get_or_compute(self, key: tuple[str, ...], compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self._hits += 1
                return self._entries[key]
        value = compute()  # outside the lock: compiling must not block other threads' lookups
        with self._lock:
            self._misses += 1
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
                self._evictions += 1
        return value

    def mass_properties(
        self, part: PartDef, material: Material, parameters: Mapping[str, Quantity] | None = None
    ) -> MassProperties:
        key = ("mass", part_key(part), material_key(material), _parameters_hash(part, parameters))
        return self._get_or_compute(key, lambda: mass_properties(part, material, parameters))

    def collision_proxy(self, part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> CollisionProxy:
        """The proxy does not read the material, so one entry serves every material the part is made of."""
        key = ("proxy", part_key(part), _parameters_hash(part, parameters))
        return self._get_or_compute(key, lambda: collision_proxy(part, parameters))

    def part_glb(
        self,
        part: PartDef,
        material: Material,
        parameters: Mapping[str, Quantity] | None = None,
        pbr: PbrSlots | None = None,
    ) -> bytes:
        """The glb bytes. `pbr` is part of the key (an explicit look is a different file); the catalog look of a material is
        looked up by id from the catalog loaded in this process, so it is the same for the life of the cache."""
        look = "catalog" if pbr is None else _sha256(pbr.model_dump_json())
        key = ("glb", part_key(part), material_key(material), _parameters_hash(part, parameters), look)
        return self._get_or_compute(key, lambda: part_glb(part, material, parameters, pbr))

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._hits, self._misses, self._evictions, len(self._entries), self._max)

    def clear(self) -> None:
        """Forget every entry. The hit, miss and eviction counters are kept."""
        with self._lock:
            self._entries.clear()
