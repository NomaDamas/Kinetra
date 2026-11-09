"""Curated, cited spec catalog (offline JSON). NOT live web research.

Each entry carries ``source_url`` and ``verified`` (read in the cited source by the catalog author
on ``checked_on``). ``lookup(template, keys)`` returns entries (or None for unknown keys).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load(template: str) -> dict[str, Any]:
    p = _DIR / f"{template}.json"
    if not p.exists():
        return {"template": template, "catalog_version": None, "kind": "curated_offline_catalog", "entries": {}}
    return json.loads(p.read_text())


def lookup(template: str, keys: list[str] | None = None) -> dict[str, dict[str, Any] | None]:
    """Entries for ``keys`` (all entries when None). Missing key -> None. Each entry gets its ``key``."""
    ents = load(template)["entries"]
    wanted = list(ents) if keys is None else list(keys)
    return {k: ({"key": k, **ents[k]} if k in ents else None) for k in wanted}


def catalog_meta(template: str) -> dict[str, Any]:
    c = load(template)
    return {"catalog_version": c.get("catalog_version"), "kind": c.get("kind"), "note": c.get("note"),
            "n_entries": len(c["entries"])}


@lru_cache(maxsize=None)
def costs() -> dict[str, Any]:
    return json.loads((_DIR / "costs.json").read_text())
