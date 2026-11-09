"""Shared helpers: component line construction from a Selection, mass bookkeeping, label constants."""
from __future__ import annotations

from typing import Any

from . import selection as sel

SIMPLIFIED_FEA = "simplified model, needs FEA"
SIMPLIFIED = "simplified model, needs precise validation"


def choice_dict(entry: dict[str, Any]) -> dict[str, Any]:
    return dict(name=entry["name"], vendor=entry.get("vendor", ""), specs=dict(entry["specs"]), mass_kg=entry.get("mass_kg"),
                unit_cost_usd=entry.get("unit_cost_usd"), source=entry["source_url"], verified=bool(entry["verified"]))


def catalog_component(cid: str, role: str, qty: int, entries: list[dict], needs: list[sel.Need], *, additive_ok_qty: int = 8,
                      placeholder_mass_each: float | None = None, placeholder_note: str = "", unmet_note: str = "") -> dict[str, Any]:
    """One component line: lightest catalog entry meeting all ``needs``; otherwise needs-sourcing with a flagged placeholder mass."""
    s = sel.select(entries, needs, base_qty=qty, max_qty=additive_ok_qty)
    rej = [dict(name=r["name"], why_rejected=r["why_rejected"]) for r in s.rejected]
    if s.entry is not None:
        e = s.entry
        meets = [dict(m) for m in s.meets]
        has_mass = e.get("mass_kg") is not None
        return dict(id=cid, role=role, quantity=int(s.quantity), choice=choice_dict(e), meets=meets, ok=all(m["ok"] for m in meets),
                    alternatives=rej, custom=False, needs_sourcing=False, mass_kg_each=e.get("mass_kg") if has_mass else placeholder_mass_each,
                    mass_source="catalog" if has_mass else "estimate", note=(f"Selected: lightest catalog entry meeting every requirement. {unmet_note}").strip(), cad=None)
    return dict(id=cid, role=role, quantity=int(qty), choice=None, meets=[], ok=False, alternatives=rej, custom=False, needs_sourcing=True,
                mass_kg_each=placeholder_mass_each, mass_source="estimate" if placeholder_mass_each is not None else "none",
                note=(unmet_note + (" " if unmet_note else "") + placeholder_note).strip(), cad=None)


def mass_totals(components: list[dict[str, Any]]) -> dict[str, float]:
    added = est = 0.0
    for c in components:
        m = c.get("mass_kg_each")
        if m is None:
            continue
        tot = float(m) * int(c["quantity"])
        added += tot
        if c.get("mass_source") == "estimate":
            est += tot
    return dict(mass_added_kg=added, mass_estimated_kg=est)


def count_unpriced(components: list[dict[str, Any]]) -> int:
    return sum(1 for c in components if c["choice"] is None or c["choice"].get("unit_cost_usd") is None)
