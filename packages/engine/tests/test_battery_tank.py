"""B-03d: battery and tank parts (`packages/engine/src/kinetra_engine/parts/library/{battery-18650,battery-pack-4s,tank}.json`)
and what a supply does when it is drawn on (`kinetra_engine.parts.supply`).

DoD: capacity and mass, the amount left as it is consumed, and a constant-speed drive's consumption against a hand calculation.
Expected numbers are textbook formulas written out by hand, not read back from the code. The cell's cited numbers are
the Panasonic NCR18650B datasheet's (mass 48.5 g max, nominal 3.6 V, capacity min 3250 mAh); the tank's dimensions and
density, the drive's drag and efficiency, and the flow rate in the tests are our own declarations, not real data.
"""

from __future__ import annotations

import json
import math

import pytest
from gltf_samples import LIBRARY, catalog_material, library_part
from gltf_validate import validate

from kinetra_core import Badge, PartDef, PartRole, Quantity, Unit
from kinetra_engine.parts import (
    PartCache,
    ShapeError,
    Supply,
    SupplyError,
    battery_supply,
    collision_proxy,
    electrical_power,
    mass_properties,
    part_glb,
    tank_supply,
    tank_total_mass,
)
from kinetra_engine.parts.__main__ import main

CELL = library_part("battery-18650")
PACK = library_part("battery-pack-4s")
TANK = library_part("tank")
AL = catalog_material("al6061-t6")
RHO_AL = 2700.0  # al6061-t6 in the B-07 catalog

SRC = {"ref": "B-03d test: the user states this value", "declared_by": "test", "declared_at": "2026-11-12T00:00:00Z"}


def declared(value: float, unit: str) -> Quantity:
    return Quantity(value=value, unit=unit, badge=Badge.DECLARED, source=SRC)


def spec(part: PartDef, name: str):
    return next(s for s in part.specs if s.name == name)


# ---- the cell: cited mass, derived capacity --------------------------------------------------------------------------------


def test_battery_cell_mass_is_the_datasheet_weight_and_needs_no_material():
    r = mass_properties(CELL, None)
    assert r.mass.value == pytest.approx(0.0485, rel=1e-12)  # datasheet 'Weight (max.)' 48.5 g
    assert r.derivation.material_id is None
    assert r.derivation.input_badges == (Badge.CITE, Badge.DEFAULT)  # the cited mass, and our drawn envelope


def test_battery_cell_envelope_volume_and_centre_follow_the_datasheet_dimensions():
    # 18.5 mm diameter x 64.3 mm body + 6.6 mm button 1.0 mm tall (datasheet: max 18.5, max 65.3 total, button 6.6).
    v_body, v_nub = math.pi * 0.00925**2 * 0.0643, math.pi * 0.0033**2 * 0.001
    r = mass_properties(CELL, None)
    assert r.volume.value == pytest.approx(v_body + v_nub, rel=1e-12)
    assert r.center_of_mass.z == pytest.approx(v_nub * (0.5 * 0.0643 + 0.5 * 0.001) / (v_body + v_nub), rel=1e-9)
    assert r.center_of_mass.x == pytest.approx(0.0, abs=1e-15) and r.center_of_mass.y == pytest.approx(0.0, abs=1e-15)
    # Axial inertia: the mass is spread uniformly, so each cylinder carries its volume share; I_zz = sum m_i r_i^2 / 2.
    m = 0.0485
    izz = m * (v_body * 0.00925**2 + v_nub * 0.0033**2) / (2 * (v_body + v_nub))
    assert r.inertia.izz == pytest.approx(izz, rel=1e-9)
    # The cell is 65.3 mm long end to end: body and button.
    ends = [(c.center[2] - c.dimension("length") / 2, c.center[2] + c.dimension("length") / 2) for c in r.derivation.components]
    assert min(lo for lo, _ in ends) == pytest.approx(-0.03215, abs=1e-12)
    assert max(hi for _, hi in ends) == pytest.approx(0.03315, abs=1e-12)
    assert max(hi for _, hi in ends) - min(lo for lo, _ in ends) == pytest.approx(0.0653, abs=1e-12)


def test_battery_cell_energy_is_capacity_times_nominal_voltage_with_honest_badges():
    energy, volts = spec(CELL, "energy_capacity"), spec(CELL, "nominal_voltage")
    assert volts.value == 3.6 and volts.unit is Unit.V and volts.badge is Badge.CITE
    assert energy.unit is Unit.J
    assert energy.value == pytest.approx(3.250 * 3.6 * 3600.0, rel=1e-12)  # 3250 mAh x 3.6 V = 11.7 Wh = 42 120 J
    assert energy.value == 42120.0
    assert energy.badge is Badge.ESTIMATE  # our product of two printed values, not a printed energy
    assert "3250 mAh" in energy.source.ref and "3.6 V" in energy.source.ref
    assert volts.source.url and "NCR18650B" in volts.source.url and volts.source.locator


def test_battery_cell_energy_agrees_with_the_datasheet_energy_density_within_one_percent():
    # Datasheet gravimetric energy density 243 Wh/kg (typical capacity) times the 48.5 g weight.
    printed = 243.0 * 0.0485 * 3600.0
    assert spec(CELL, "energy_capacity").value == pytest.approx(printed, rel=0.01)


def test_battery_pack_is_four_cells_in_series():
    cell_e, cell_v = spec(CELL, "energy_capacity").value, spec(CELL, "nominal_voltage").value
    assert spec(PACK, "energy_capacity").value == pytest.approx(4 * cell_e, rel=1e-12)
    assert spec(PACK, "nominal_voltage").value == pytest.approx(4 * cell_v, rel=1e-12)
    assert spec(PACK, "energy_capacity").badge is spec(PACK, "nominal_voltage").badge is Badge.ESTIMATE
    r = mass_properties(PACK, None)
    assert r.mass.value == pytest.approx(4 * 0.0485, rel=1e-12)
    assert r.derivation.input_badges == (Badge.DEFAULT, Badge.ESTIMATE)  # no 'cite' is claimed for a pack we composed
    # 2 x 2 touching cells: the volume is four cells' volume, the centre sits on the axis.
    v_cell = math.pi * 0.00925**2 * 0.0643 + math.pi * 0.0033**2 * 0.001
    assert r.volume.value == pytest.approx(4 * v_cell, rel=1e-12)
    assert r.center_of_mass.x == pytest.approx(0.0, abs=1e-15)


# ---- battery supply: capacity and what is left ----------------------------------------------------------------------------


def test_battery_supply_starts_full_with_the_capacity_spec():
    s = battery_supply(CELL)
    assert (s.role, s.unit, s.capacity.value, s.remaining, s.fraction) == (PartRole.BATTERY, Unit.J, 42120.0, 42120.0, 1.0)
    assert s.capacity.badge is Badge.ESTIMATE and s.input_badges == (Badge.ESTIMATE,)
    assert not s.empty


@pytest.mark.parametrize("charge", [0.0, 0.25, 0.5, 1.0])
def test_battery_supply_initial_charge_scales_what_is_left_not_the_capacity(charge):
    s = battery_supply(CELL, {"initial_charge": declared(charge, "1")})
    assert s.capacity.value == 42120.0 and s.remaining == pytest.approx(42120.0 * charge, rel=1e-15)
    assert s.empty is (charge == 0.0)


def test_battery_supply_rejects_a_charge_outside_the_range_and_a_part_that_is_not_a_battery():
    with pytest.raises(ShapeError, match="outside the allowed range"):
        battery_supply(CELL, {"initial_charge": declared(1.01, "1")})
    with pytest.raises(ShapeError, match="not a battery"):
        battery_supply(TANK)
    with pytest.raises(ShapeError, match="not a tank"):
        tank_supply(CELL)


def test_battery_constant_speed_drive_consumption_matches_the_hand_calculation():
    """A wheel of radius 0.05 m holds 2 m/s against a steady 5 N drag. Declared numbers, hand calculation:

    torque = 5 N x 0.05 m = 0.25 N*m; speed = 2 / 0.05 = 40 rad/s; mechanical power = 0.25 x 40 = 10 W.
    At efficiency 0.8 the cell supplies 10 / 0.8 = 12.5 W. In 100 s that is 1250 J, so 42 120 - 1250 = 40 870 J remain
    (97.03 %). From full it lasts 42 120 / 12.5 = 3369.6 s."""
    wheel_radius, drag, v, eta = 0.05, 5.0, 2.0, 0.8
    torque, omega = drag * wheel_radius, v / wheel_radius
    assert (torque, omega) == (0.25, 40.0)
    p_el = electrical_power(torque * omega, eta)
    assert p_el == pytest.approx(12.5, rel=1e-12)
    cell = battery_supply(CELL)
    drawn = cell.draw_rate(p_el, 100.0)
    assert drawn.delivered == pytest.approx(1250.0, rel=1e-12) and drawn.satisfied == 1.0
    assert drawn.supply.remaining == pytest.approx(40870.0, rel=1e-12)
    assert drawn.supply.fraction == pytest.approx(40870.0 / 42120.0, rel=1e-12)
    assert cell.time_to_empty(p_el) == pytest.approx(3369.6, rel=1e-12)
    assert cell.remaining == 42120.0  # the cell it was drawn from is a value: unchanged


def test_battery_stepped_consumption_equals_the_closed_form_at_every_step_size():
    p_el = 12.5
    for dt in (1.0, 0.1, 0.01, 1.0 / 240.0):
        s, t, steps = battery_supply(CELL), 0.0, int(round(100.0 / dt))
        for _ in range(steps):
            s = s.draw_rate(p_el, dt).supply
            t += dt
        assert t == pytest.approx(100.0, rel=1e-9)
        assert s.remaining == pytest.approx(42120.0 - p_el * 100.0, rel=1e-9)


def test_battery_runs_flat_at_the_hand_calculated_time_and_never_goes_below_zero():
    s, p_el, dt = battery_supply(CELL), 12.5, 1.0
    t_empty = 42120.0 / 12.5  # 3369.6 s
    t, last = 0.0, None
    while not s.empty:
        last = s.draw_rate(p_el, dt)
        s, t = last.supply, t + dt * last.satisfied  # the final step only runs for the fraction the battery could pay for
        assert s.remaining >= 0.0
    assert t == pytest.approx(t_empty, rel=1e-12)
    assert last.satisfied == pytest.approx(0.6, abs=1e-9)  # 3369 whole seconds, then 0.6 s of the 1 s step
    assert last.delivered == pytest.approx(7.5, abs=1e-9)  # the last 7.5 J of 12.5 J asked
    again = s.draw_rate(p_el, dt)
    assert (again.delivered, again.satisfied, again.supply.remaining) == (0.0, 0.0, 0.0)  # an empty supply gives nothing


def test_battery_two_motors_on_one_battery_spend_the_same_stock():
    s = battery_supply(CELL)
    for _ in range(10):  # two 12.5 W motors over 10 steps of 1 s, drawn in turn from the one supply
        for motor_w in (12.5, 12.5):
            s = s.draw_rate(motor_w, 1.0).supply
    assert s.remaining == pytest.approx(42120.0 - 2 * 12.5 * 10, rel=1e-12)


def test_battery_electrical_power_has_no_regeneration_and_checks_its_inputs():
    assert electrical_power(-10.0, 0.8) == 0.0  # a motor braked by its load takes nothing and gives nothing back
    assert electrical_power(0.0, 1.0) == 0.0
    for bad in (0.0, -0.1, 1.01, math.nan):
        with pytest.raises(ValueError, match="efficiency"):
            electrical_power(10.0, bad)
    with pytest.raises(ValueError, match="finite"):
        electrical_power(math.inf, 0.9)


def test_battery_draw_rejects_a_negative_or_non_finite_amount_and_time():
    s = battery_supply(CELL)
    for bad in (-1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="amount"):
            s.draw(bad)
    with pytest.raises(ValueError, match="time step"):
        s.draw_rate(1.0, -0.1)
    with pytest.raises(ValueError, match="rate"):
        s.time_to_empty(-1.0)
    assert s.time_to_empty(0.0) == math.inf


def test_battery_supply_is_a_checked_value():
    cap = battery_supply(CELL).capacity
    with pytest.raises(ValueError, match="remaining"):
        Supply("x", PartRole.BATTERY, cap, 42121.0, (Badge.ESTIMATE,))
    with pytest.raises(ValueError, match="remaining"):
        Supply("x", PartRole.BATTERY, cap, -1.0, (Badge.ESTIMATE,))
    with pytest.raises(ValueError, match="capacity is in 'kg'"):
        Supply("x", PartRole.TANK, cap, 1.0, (Badge.ESTIMATE,))
    with pytest.raises(ValueError, match="capacity is in 'J'"):
        Supply("x", PartRole.BATTERY, declared(1.0, "kg"), 1.0, (Badge.DECLARED,))
    with pytest.raises(ValueError, match="battery or a tank"):
        Supply("x", PartRole.MOTOR, cap, 1.0, (Badge.ESTIMATE,))
    with pytest.raises(AttributeError):
        battery_supply(CELL).remaining = 0.0  # frozen


# ---- the tank: capacity from its inside, mass with what is left -----------------------------------------------------------------


def inside_volume(radius: float, length: float) -> float:
    return math.pi * (radius - 0.003) ** 2 * (length - 0.006)  # 3 mm wall, fixed in the definition


def test_tank_capacity_is_density_times_the_inside_volume():
    s = tank_supply(TANK)  # defaults: radius 0.06 m, length 0.2 m, 1000 kg/m^3
    expected = 1000.0 * math.pi * 0.057**2 * 0.194
    assert s.capacity.value == pytest.approx(expected, rel=1e-12)
    assert expected == pytest.approx(1.98017, abs=1e-5)  # about 1.98 kg of a water-density liquid
    assert (s.role, s.unit, s.remaining) == (PartRole.TANK, Unit.KG, s.capacity.value)
    assert s.capacity.badge is Badge.SIM and s.input_badges == (Badge.DEFAULT,)  # computed, from defaults only


@pytest.mark.parametrize(("radius", "length", "rho"), [(0.03, 0.05, 1.0), (0.15, 0.6, 2000.0), (0.06, 0.6, 1000.0), (0.1, 0.05, 700.0)])
def test_tank_capacity_follows_the_dimensions_over_the_whole_range(radius, length, rho):
    s = tank_supply(
        TANK,
        {"radius": declared(radius, "m"), "length": declared(length, "m"), "propellant_density": declared(rho, "kg/m^3")},
    )
    assert s.capacity.value == pytest.approx(rho * inside_volume(radius, length), rel=1e-12)
    assert s.input_badges == (Badge.DEFAULT, Badge.DECLARED)  # the shape is ours (default), the sizes were declared (Badge order)


def test_tank_initial_fill_scales_what_is_left_not_the_capacity():
    full = tank_supply(TANK)
    half = tank_supply(TANK, {"initial_fill": declared(0.5, "1")})
    assert half.capacity.value == full.capacity.value and half.remaining == pytest.approx(0.5 * full.capacity.value, rel=1e-15)


def test_tank_propellant_burn_matches_the_hand_calculation():
    """A thruster takes 0.002 kg/s (declared). 100 s burn: 0.2 kg. Left: 1.98017 - 0.2; burn time to empty = left / flow."""
    s = tank_supply(TANK)
    cap = 1000.0 * math.pi * 0.057**2 * 0.194
    drawn = s.draw_rate(0.002, 100.0)
    assert drawn.delivered == pytest.approx(0.2, rel=1e-12) and drawn.satisfied == 1.0
    assert drawn.supply.remaining == pytest.approx(cap - 0.2, rel=1e-12)
    assert s.time_to_empty(0.002) == pytest.approx(cap / 0.002, rel=1e-12)  # about 990.1 s
    over = s.draw_rate(0.002, 2000.0)  # asks for 4 kg of a 1.98 kg tank
    assert over.delivered == pytest.approx(cap, rel=1e-12) and over.supply.empty
    assert over.satisfied == pytest.approx(cap / 4.0, rel=1e-12)


def test_tank_dry_mass_is_the_shell_volume_times_the_material_density():
    # body (r = 0.06, l = 0.2) minus inside (r = 0.057, l = 0.194), neck (r 0.012, 0.03 long), cap 30 x 30 x 15 mm, skirt (r 0.048, 0.01).
    shell = math.pi * 0.06**2 * 0.2 - math.pi * 0.057**2 * 0.194
    v = shell + math.pi * 0.012**2 * 0.03 + 0.03 * 0.03 * 0.015 + math.pi * 0.048**2 * 0.01
    dry = mass_properties(TANK, AL)
    assert dry.volume.value == pytest.approx(v, rel=1e-12)
    assert dry.mass.value == pytest.approx(RHO_AL * v, rel=1e-12)


def test_tank_total_mass_falls_as_propellant_is_burnt_and_conserves_what_was_drawn():
    dry = mass_properties(TANK, AL).mass.value
    s = tank_supply(TANK)
    full = tank_total_mass(dry, s)
    assert full == pytest.approx(dry + 1000.0 * math.pi * 0.057**2 * 0.194, rel=1e-12)
    after = s.draw_rate(0.002, 100.0)
    assert full - tank_total_mass(dry, after.supply) == pytest.approx(after.delivered, rel=1e-9)  # the lost mass is what was drawn
    assert tank_total_mass(dry, after.supply.draw(1e9).supply) == pytest.approx(dry, rel=1e-15)  # empty: the dry mass
    with pytest.raises(ValueError, match="only a tank"):
        tank_total_mass(dry, battery_supply(CELL))
    with pytest.raises(ValueError, match="dry mass"):
        tank_total_mass(0.0, s)


def test_tank_inside_is_filled_in_the_collision_proxy_and_not_drawn_and_says_so():
    proxy = collision_proxy(TANK)
    assert [v.id for v in proxy.filled_voids] == ["inside"]  # the approximation is reported, not hidden
    # The proxy is the solid outside: body, neck, cap, skirt with the inside filled. volume_error = (proxy - recipe) / recipe.
    solid = math.pi * 0.06**2 * 0.2 + math.pi * 0.012**2 * 0.03 + 0.03 * 0.03 * 0.015 + math.pi * 0.048**2 * 0.01
    recipe = solid - math.pi * 0.057**2 * 0.194
    assert proxy.volume_error.value == pytest.approx((solid - recipe) / recipe, rel=1e-9)
    assert proxy.volume_error.value == pytest.approx(5.194, abs=1e-3)  # the shell is 14 % of the solid: the proxy is 6.2x the recipe
    assert mass_properties(TANK, AL).volume.value == pytest.approx(recipe, rel=1e-12)  # the mass counts the empty inside


# ---- the definitions reject what a battery or a tank is not -----------------------------------------------------------------


def _with(part: PartDef, **change) -> dict:
    d = json.loads(part.model_dump_json(exclude_none=True))
    d.update(change)
    return d


def test_battery_definition_needs_energy_and_voltage_specs_in_joules_and_volts():
    d = _with(CELL, specs=[s for s in _with(CELL)["specs"] if s["name"] != "energy_capacity"])
    with pytest.raises(ValueError, match="needs the spec 'energy_capacity'"):
        PartDef.model_validate(d)
    d = _with(CELL, specs=[s for s in _with(CELL)["specs"] if s["name"] != "nominal_voltage"])
    with pytest.raises(ValueError, match="needs the spec 'nominal_voltage'"):
        PartDef.model_validate(d)
    d = _with(CELL)
    d["specs"][0]["unit"] = "W"
    with pytest.raises(ValueError, match="positive number in 'J'"):
        PartDef.model_validate(d)
    d = _with(CELL)
    d["specs"][0]["value"] = 0.0
    with pytest.raises(ValueError, match="positive number in 'J'"):
        PartDef.model_validate(d)


def test_battery_initial_charge_must_be_a_fraction():
    d = _with(CELL)
    for p in d["parameters"]:
        if p["name"] == "initial_charge":
            for k in ("default", "max"):
                p[k]["value"] = 1.5
    with pytest.raises(ValueError, match="is a fraction"):
        PartDef.model_validate(d)


def test_tank_definition_needs_an_inside_and_a_positive_density():
    d = _with(TANK)
    d["shape"]["components"] = [c for c in d["shape"]["components"] if c["operation"] != "subtract"]
    with pytest.raises(ValueError, match="needs a shape with an inside"):
        PartDef.model_validate(d)
    d = _with(TANK, parameters=[p for p in _with(TANK)["parameters"] if p["name"] != "propellant_density"])
    with pytest.raises(ValueError, match="needs the parameter 'propellant_density'"):
        PartDef.model_validate(d)
    d = _with(TANK)
    for p in d["parameters"]:
        if p["name"] == "propellant_density":
            p["min"]["value"] = 0.0
    with pytest.raises(ValueError, match="positive density"):
        PartDef.model_validate(d)
    d = _with(TANK)
    del d["shape"]
    with pytest.raises(ValueError, match="needs a shape with an inside"):
        PartDef.model_validate(d)


# ---- the usual part checks: glb, collision proxy, cache, the check command -------------------------------------------------------


@pytest.mark.parametrize(("part", "material"), [(CELL, None), (PACK, None), (TANK, AL)])
def test_battery_and_tank_parts_compile_to_a_valid_glb(part, material):
    glb = validate(part_glb(part, material))
    assert len(glb.doc["meshes"]) >= 1
    assert collision_proxy(part).volume_error.value >= 0.0


def test_battery_cell_collision_proxy_is_exact_and_has_no_voids():
    for part in (CELL, PACK):
        proxy = collision_proxy(part)
        assert proxy.volume_error.value == 0.0 and proxy.filled_voids == ()


def test_battery_and_tank_results_come_out_of_the_cache_unchanged():
    cache = PartCache(max_entries=8)
    assert cache.mass_properties(CELL, None) == mass_properties(CELL, None)
    assert cache.mass_properties(TANK, AL) == mass_properties(TANK, AL)
    assert cache.part_glb(PACK, None) == part_glb(PACK, None)


def test_battery_and_tank_snap_points_carry_a_pose_with_a_badge_and_a_tag():
    for part in (CELL, PACK, TANK):
        assert part.snap_points and all(s.badge is Badge.DEFAULT and s.accepts for s in part.snap_points)
    assert {s.id for s in CELL.snap_points} >= {"plus", "minus"}
    assert next(s for s in TANK.snap_points if s.id == "outlet").kind == "feed"


def test_battery_and_tank_check_command_reports_each_part(capsys, tmp_path):
    for name, args in (("battery-18650", []), ("battery-pack-4s", []), ("tank", ["--material", "al6061-t6"])):
        code = main([str(LIBRARY / f"{name}.json"), *args, "--out", str(tmp_path)])
        report = json.loads(capsys.readouterr().out)
        assert code == 0 and report["part"] == name
        validate((tmp_path / f"{name}.glb").read_bytes())
    assert report["filled_voids"] == ["inside"]


# ---- B-03f: a request no supply can honour is a SupplyError, whatever the other argument is ---------------------------


@pytest.mark.parametrize("rate", [-1.0, -1e-12, -0.0 - 1.0, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("dt", [0.0, 1.0, 1e-9])
def test_battery_draw_rate_rejects_a_negative_or_non_finite_rate_for_any_time_step(rate, dt):
    s = battery_supply(CELL)
    with pytest.raises(SupplyError, match="a rate drawn"):
        s.draw_rate(rate, dt)
    assert s.remaining == 42120.0


@pytest.mark.parametrize("dt", [-1.0, -1e-12, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("rate", [0.0, 12.5])
def test_battery_draw_rate_rejects_a_negative_or_non_finite_time_step_for_any_rate(rate, dt):
    with pytest.raises(SupplyError, match="a time step"):
        battery_supply(CELL).draw_rate(rate, dt)


def test_battery_draw_rate_negative_rate_with_zero_time_is_the_reported_case():
    """`-1.0 * 0.0` is `-0.0`, which `draw` accepts: the rate has to be checked before the product is formed."""
    assert -1.0 * 0.0 == 0.0 and math.copysign(1.0, -1.0 * 0.0) == -1.0
    with pytest.raises(SupplyError):
        battery_supply(CELL).draw_rate(-1.0, 0.0)
    with pytest.raises(SupplyError):
        tank_supply(TANK).draw_rate(-0.002, 0.0)


def test_battery_zero_rate_or_zero_time_is_a_valid_draw_of_nothing():
    for rate, dt in ((0.0, 5.0), (12.5, 0.0), (0.0, 0.0)):
        drawn = battery_supply(CELL).draw_rate(rate, dt)
        assert (drawn.requested, drawn.delivered, drawn.satisfied, drawn.supply.remaining) == (0.0, 0.0, 1.0, 42120.0)


def test_battery_supply_error_is_a_value_error_and_covers_draw_and_time_to_empty():
    assert issubclass(SupplyError, ValueError)
    s = battery_supply(CELL)
    for bad in (-1.0, math.nan, math.inf):
        with pytest.raises(SupplyError):
            s.draw(bad)
        with pytest.raises(SupplyError):
            s.time_to_empty(bad)
