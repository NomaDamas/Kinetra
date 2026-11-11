"""Canonical form and definition hashes (C-03).

A hash says "this is the same thing" without a diff. Two values that differ only in how they are shown (the order
of a list, the key order or whitespace of the JSON text they were read from, `1` against `1.0`, the UTC offset a
timestamp was written in) must therefore hash the same, and two values that differ in anything else must not.
`project-model.md` keeps the order of every collection as part of the value (a `Project` compares unequal to its
reordered twin and a saved file keeps its order); this module is where that order stops mattering.

The canonical form of a value (`canonical_json`):

- Every field of every model, in a JSON object whose keys are sorted (by UTF-16 code unit, as RFC 8785 does).
  A field that is not required and holds its default is left out, so a leaf that later adds an optional field
  does not change the hash of a value that leaves it alone (`client-adapter.md` G5: fields can be added).
- Every collection is sorted by the key that names its items. The key is registered per FIELD (`_ORDER`, keyed by
  the owning model and the field name), not per item type: `DesignSpec.materials`, `.parts`, `.instances`,
  `.joints`, `.actuators`, `ControlSchedule.entries` and `World.terrain_props` by `id`; `PartDef.parameters`,
  `.specs` and `Instance.parameters` by `name`; `PartDef.snap_points` and `Shape.components` by `id`;
  `AssumptionTable.assumptions` by `key`; `SnapPoint.accepts` tags by value; `AxisExpr.terms` by
  `(param, factor)`. Every item of a collection has such a key, so the order is total. Names and ids match
  ASCII patterns, so code point order is UTF-16 code unit order and a client compares with `<`, not a locale
  collation. A tuple field with no entry in `_ORDER` raises `CanonicalError` instead of being hashed in file order, and
  `test_hash_every_collection_of_the_project_model_has_a_canonical_order` walks the model and fails when a leaf
  adds a tuple field that is not registered (a list whose order MEANS something, like a route of ids, must never
  be sorted: such a field is a new rule, not a new entry).
- Whatever is not a collection keeps its meaning: a joint's `a` (parent) and `b` (child), a quaternion's four
  components, a snap point's position, ids and names. They are values, not display.
- Numbers are written the way ECMAScript's `Number.prototype.toString` writes them (RFC 8785 section 3.2.2.3):
  shortest digits that read back to the same double, `1` for `1.0`, `0` for `-0.0`, `1e+21` and `1e-7` outside
  [1e-6, 1e21). A non-finite number is an error (the model rejects it already).
- Timestamps (`declared_at`) are converted to UTC and written `YYYY-MM-DDTHH:MM:SS[.f]Z`, the fraction with its
  trailing zeros trimmed. The same instant hashes the same whatever offset it was declared in.
- Not stored in the text: a field that is not required and holds its default (above). Which fields these are,
  with their defaults, is pinned in `test_hash_omitted_defaults_are_pinned`: **changing a model default is a change
  of these rules** (it changes what an omitted field means and what is hashed), so it needs a file `version` bump
  and a migration of older files, never a silent edit.
- Strings are JSON-escaped as RFC 8785 says (only `"` `\\` and control characters; everything else is the UTF-8
  character itself) and are not normalised or trimmed: a different string is a different value. No whitespace
  between tokens.

The hash is `sha256:` and the hex digest of the UTF-8 bytes of that text. It carries the algorithm, not the rules:
a change to these rules is a new file `version` (`projectfile.py`).

`definition_hash` is the hash of one definition (a `PartDef` or a `Material`), `project_hash` of a whole `Project`
(design, world and assumptions). Not here: what a client does with a hash that differs from the catalog's (C-06),
the trajectory hash of a run (X-02d), asset content hashes (A2).

What this does not promise: two projects with equal hashes are equal as documents, not bit for bit as inputs. The
float sum of an engine that walks `instances` in list order can differ in its last digits from the sum in another
order, and MuJoCo orders its solver by body order. A consumer that needs one hash to mean one trajectory has to read
the project in this module's order (by id): the compiler's rule, issue #511. Until then there are two definition
hashes in the repository on purpose: this one (order-free, "is it the same definition?", C-06) and
`kinetra_engine.parts.cache.part_key` (strict, a cache key: never reuse a result computed from another order).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from .assumption import AssumptionTable
from .designspec import ControlSchedule, DesignSpec, Instance
from .geometry import AxisExpr
from .material import Material
from .partdef import PartDef, SnapPoint
from .project import Project
from .shape import Shape
from .world import World

HASH_PREFIX = "sha256:"


class CanonicalError(ValueError):
    """A value has no canonical form (an unknown collection, a number that is not finite, text that is not UTF-8)."""


# The key of each item of an ordered-by-name collection, by (owning model, field). A key is unique inside its
# collection (the models check it), so sorting by it is total. `str` items are the tags of `SnapPoint.accepts`.
def _id(m: Any) -> Any:
    return m.id


def _name(m: Any) -> Any:
    return m.name


_ORDER: dict[tuple[type, str], Callable[[Any], Any]] = {
    (DesignSpec, "materials"): _id,
    (DesignSpec, "parts"): _id,
    (DesignSpec, "instances"): _id,
    (DesignSpec, "joints"): _id,
    (DesignSpec, "actuators"): _id,
    (ControlSchedule, "entries"): _id,
    (World, "terrain_props"): _id,
    (PartDef, "parameters"): _name,
    (PartDef, "specs"): _name,
    (PartDef, "snap_points"): _id,
    (Shape, "components"): _id,
    (Instance, "parameters"): _name,
    (AssumptionTable, "assumptions"): lambda m: m.key,
    (SnapPoint, "accepts"): lambda tag: tag,
    (AxisExpr, "terms"): lambda t: (t.param, t.factor),
}


def _sorted(owner: BaseModel, field: str, items: tuple[Any, ...]) -> list[Any]:
    key = _ORDER.get((type(owner), field))
    if key is None:
        raise CanonicalError(
            f"no canonical order for {type(owner).__name__}.{field}: register the key that names its items in "
            "canonical._ORDER (or, if its order is part of its meaning, make it a new rule with a file version)"
        )
    return sorted(items, key=key)


def _utc(value: datetime) -> str:
    try:
        u = value.astimezone(timezone.utc)
    except OverflowError:
        raise CanonicalError(f"timestamp {value.isoformat()} is outside the years 1 to 9999 once written in UTC") from None
    fraction = f".{u.microsecond:06d}".rstrip("0") if u.microsecond else ""
    return f"{u.year:04d}-{u.month:02d}-{u.day:02d}T{u.hour:02d}:{u.minute:02d}:{u.second:02d}{fraction}Z"


def _plain(value: Any) -> Any:
    """The value as JSON-ready Python: dicts, lists, strings, finite floats, booleans, None, small ints."""
    if isinstance(value, BaseModel):
        out: dict[str, Any] = {}
        for name, field in type(value).model_fields.items():
            item = getattr(value, name)
            if not field.is_required() and item == field.get_default(call_default_factory=True):
                continue
            out[name] = [_plain(i) for i in _sorted(value, name, item)] if isinstance(item, tuple) else _plain(item)
        return out
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise CanonicalError(f"timestamp without a time zone: {value!r}")
        return _utc(value)
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        if abs(value) > 2**53:
            raise CanonicalError(f"integer {value} is not exactly a double")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalError(f"number is not finite: {value}")
        return value
    raise CanonicalError(f"no canonical form for a {type(value).__name__}")


def _number(x: float | int) -> str:
    """ECMAScript `Number::toString(x)` for a finite number (RFC 8785 3.2.2.3)."""
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    # `repr` of a float is the shortest string that reads back to the same double; so is ECMAScript's. Only the
    # layout differs, which is decided below from the digits `s` and the position `n` of the decimal point.
    d = Decimal(repr(abs(float(x)))).as_tuple()
    s = "".join(map(str, d.digits))
    exp = int(d.exponent)
    stripped = s.rstrip("0")
    exp += len(s) - len(stripped)
    s = stripped
    k = len(s)
    n = k + exp  # the value is 0.s * 10**n
    if k <= n <= 21:
        body = s + "0" * (n - k)
    elif 0 < n <= 21:
        body = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + s
    else:
        e = n - 1
        mantissa = s if k == 1 else s[0] + "." + s[1:]
        body = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body


def _string(s: str) -> str:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise CanonicalError(f"text is not valid Unicode (a lone surrogate): {s!r}") from None
    return json.dumps(s, ensure_ascii=False)


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(i) for i in value) + "]"
    keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
    return "{" + ",".join(f"{_string(k)}:{_serialize(value[k])}" for k in keys) + "}"


def canonical_json(model: BaseModel) -> str:
    """The canonical text of `model` (see the module docstring). Raises `CanonicalError` when it has none."""
    return _serialize(_plain(model))


def _hash(model: BaseModel) -> str:
    return HASH_PREFIX + hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()


def definition_hash(definition: PartDef | Material) -> str:
    """Hash of one part or material definition: its fields in canonical form, nothing about where it sits in a project."""
    if not isinstance(definition, (PartDef, Material)):
        raise TypeError(f"a definition is a PartDef or a Material, not {type(definition).__name__}")
    return _hash(definition)


def project_hash(project: Project) -> str:
    """Hash of a whole `Project`: design (with its definitions), world and assumptions."""
    if not isinstance(project, Project):
        raise TypeError(f"expected a Project, not {type(project).__name__}")
    return _hash(project)
