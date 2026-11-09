"""Selection (lightest passing, custom when none passes), gas sizing, parts sizing, catalog integrity."""
from __future__ import annotations

import copy

import pytest

from kinetra_engine import catalog as cat
from kinetra_engine.design import common, gas, parts, selection as sel


def E(id, mass, **specs):
    return dict(id=id, name=id, vendor="v", specs=specs, mass_kg=mass, unit_cost_usd=None, source_url="https://x", verified=True)


def test_selects_lightest_passing_entry():
    entries = [E("heavy", 5.0, t=100.0), E("light_fail", 0.1, t=50.0), E("light_ok", 1.0, t=100.0), E("mid", 2.0, t=300.0)]
    s = sel.select(entries, [sel.Need("r", "t", 90.0, "N")])
    assert s.entry["id"] == "light_ok"
    assert all(m["ok"] for m in s.meets)
    names = {r["name"]: r["why_rejected"] for r in s.rejected}
    assert "50" in names["light_fail"] and "<" in names["light_fail"]
    assert "heavier" in names["heavy"] and "heavier" in names["mid"]


def test_none_passes_gives_custom_or_needs_sourcing():
    entries = [E("a", 1.0, t=10.0), E("b", 2.0, t=20.0)]
    s = sel.select(entries, [sel.Need("r", "t", 500.0, "N")])
    assert s.entry is None
    comp = common.catalog_component("x", "thruster", 10, entries, [sel.Need("r", "t", 500.0, "N")], placeholder_mass_each=2.0)
    assert comp["choice"] is None and comp["ok"] is False and comp["needs_sourcing"] is True and comp["mass_source"] == "estimate"


def test_missing_spec_cannot_meet():
    s = sel.select([E("a", 1.0, t=None)], [sel.Need("r", "t", 1.0, "N")])
    assert s.entry is None and "not published" in s.rejected[0]["why_rejected"]


def test_additive_requirement_buys_more_units():
    s = sel.select([E("small", 1.0, v=3.0), E("big", 10.0, v=40.0)], [sel.Need("vol", "v", 20.0, "L", additive=True)], max_qty=12)
    # 7 x 1 kg = 7 kg beats 1 x 10 kg
    assert s.entry["id"] == "small" and s.quantity == 7 and s.meets[0]["provided"] == 21.0


def test_every_meets_row_is_consistent():
    s = sel.select([E("a", 1.0, t=100.0, u=5.0)], [sel.Need("r1", "t", 80.0, "N"), sel.Need("r2", "u", 5.0, "x")])
    for m in s.meets:
        assert m["ok"] == (m["provided"] >= m["required"])
        assert m["margin"] == pytest.approx((m["provided"] - m["required"]) / m["required"])


def test_catalogs_carry_sources_and_never_invent_prices():
    for t in ("rocket_car", "humanoid_jump"):
        c = cat.components(t)
        n = 0
        for cname, entries in c["categories"].items():
            for e in entries:
                n += 1
                assert e["source_url"].startswith("https://") and e["checked_on"]
                assert e["unit_cost_usd"] is None          # no cited price anywhere
                assert isinstance(e["verified"], bool)
        assert n > 0
    assert cat.components("rocket_car")["materials"]["6061-T6"]["yield_MPa"] == 276


def test_gas_real_vs_ideal_and_tank_volume():
    rho_i, rho_r = gas.rho_ideal(300.0, 293.15), gas.rho_vdw(300.0, 293.15)
    assert 330 < rho_i < 360 and rho_r < rho_i          # real N2 at 300 bar is less dense than ideal here? (vdW b-term -> lower)
    v = gas.tank_volume_l(10.0, 300.0, 10.0)
    assert v["used"] == max(v["ideal"], v["vdw"]) and v["used"] > 30.0


def test_parts_checks_pass_and_scale_with_load():
    a, b = parts.size_bracket(3000.0), parts.size_bracket(9000.0)
    for p in (a, b):
        assert p["check"]["ok"] and p["check"]["stress_MPa"] <= p["check"]["allow_MPa"] and "needs FEA" in p["check"]["label"]
    assert b["params"]["plate_t_mm"] > a["params"]["plate_t_mm"] and b["mass_kg"] > a["mass_kg"]
    s = parts.size_shank_link(200.0)
    assert s["check"]["ok"] and s["mass_kg"] == pytest.approx(parts.tube_volume_mm3(s["params"]) * 1e-9 * 2700)
