"""Template registry. Modules are imported lazily so a missing/broken template never breaks the others."""
from __future__ import annotations

import importlib
from typing import Any

# template_id -> (module, attribute holding the Template instance)
_REGISTRY: dict[str, tuple[str, str]] = {
    "rocket_car": ("kinetra_engine.templates.rocket_car", "TEMPLATE"),
    "humanoid_jump": ("kinetra_engine.templates.humanoid_jump", "TEMPLATE"),
}


def get(template_id: str) -> Any:
    """Template instance for ``template_id`` (raises KeyError if unknown, ImportError if its module is missing)."""
    if template_id not in _REGISTRY:
        raise KeyError(f"unknown template {template_id!r}; registered: {sorted(_REGISTRY)}")
    mod, attr = _REGISTRY[template_id]
    return getattr(importlib.import_module(mod), attr)


def available() -> list[str]:
    """Template ids whose module imports cleanly right now."""
    out = []
    for tid, (mod, attr) in _REGISTRY.items():
        try:
            getattr(importlib.import_module(mod), attr)
            out.append(tid)
        except Exception:
            continue
    return out
