"""Catalog selection: lightest entry meeting every requirement; otherwise nothing (-> custom / needs sourcing).

An entry is compared on the spec figures it PUBLISHES; a missing (null) figure counts as 'cannot show it meets' and rejects the
entry. ``additive`` requirements (e.g. tank volume) are met by buying more units (up to ``max_qty``); the per-unit ones must
be met by every unit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class Need:
    requirement_id: str
    spec_key: str
    required: float
    unit: str
    additive: bool = False


@dataclass
class Selection:
    entry: dict[str, Any] | None
    quantity: int
    meets: list[dict[str, Any]]
    rejected: list[dict[str, str]]


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def _evaluate(entry: dict[str, Any], needs: list[Need], base_qty: int, max_qty: int) -> tuple[bool, int, list[dict[str, Any]], str]:
    qty = base_qty
    for n in needs:
        v = entry["specs"].get(n.spec_key)
        if v is None:
            return False, qty, [], f"{n.spec_key} not published in the cited source, cannot show it meets {n.requirement_id}"
        if n.additive:
            qty = max(qty, math.ceil(n.required / v - 1e-12))
    if qty > max_qty:
        return False, qty, [], f"would need {qty} units (> {max_qty}) to reach the additive requirement"
    meets, fails = [], []
    for n in needs:
        v = entry["specs"][n.spec_key]
        provided = v * qty if n.additive else v
        ok = provided >= n.required
        meets.append(dict(requirement_id=n.requirement_id, required=n.required, provided=float(provided), unit=n.unit,
                          margin=(provided - n.required) / n.required if n.required else 0.0, ok=bool(ok)))
        if not ok:
            fails.append(f"{n.spec_key} {_fmt(provided)} {n.unit} < {_fmt(n.required)} {n.unit} required")
    return (not fails), qty, meets, "; ".join(fails)


def select(entries: list[dict[str, Any]], needs: list[Need], base_qty: int = 1, max_qty: int = 8) -> Selection:
    passing: list[tuple[float, dict, int, list]] = []
    rejected: list[dict[str, str]] = []
    for e in entries:
        ok, qty, meets, why = _evaluate(e, needs, base_qty, max_qty)
        if ok:
            m = e.get("mass_kg")
            passing.append((qty * m if m is not None else math.inf, e, qty, meets))
        else:
            rejected.append(dict(name=e["name"], why_rejected=why))
    if not passing:
        # report the failing rows of the closest-looking entry so the UI can show 'best catalog attempt'
        return Selection(None, base_qty, [], rejected)
    passing.sort(key=lambda t: (t[0], t[1]["id"]))
    mass, best, qty, meets = passing[0]
    for m_, e, q, _ in passing[1:]:
        rejected.append(dict(name=e["name"], why_rejected=f"meets every requirement but heavier: {q} x {_fmt(e['mass_kg'])} kg = {_fmt(m_)} kg "
                                                          f"vs {qty} x {_fmt(best['mass_kg'])} kg = {_fmt(mass)} kg for the choice"
                                                          if math.isfinite(m_) else "meets every requirement but its mass is not published"))
    return Selection(best, qty, meets, rejected)
