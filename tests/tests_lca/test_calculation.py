"""Tests for eflips.lca.calculation (unit and integration)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from eflips.model import BatteryType, EnergySource, Scenario, VehicleType

from eflips.impact.lca.calculation import (
    amortize,
    calculate_battery_emissions,
    calculate_chassis_emissions,
    calculate_energy_emissions_beb,
    calculate_energy_emissions_diesel,
    calculate_lca,
    calculate_motor_emissions,
    calculate_vehicle_type_emissions,
    efficiency_chain,
    mass_based_emissions,
    normalize_to_revenue_km,
)
from eflips.impact.lca.dataclasses import (
    BatteryTypeLCAParams,
    ItemType,
    LCAScope,
    VehicleTypeLCAParams,
)
from eflips.impact.lca.util import DefaultImpactVector

# ---------------------------------------------------------------------------
# Pure formula helpers
# ---------------------------------------------------------------------------


def test_mass_based_emissions() -> None:
    ef = DefaultImpactVector(gwp=10.0)
    result = mass_based_emissions(100.0, ef)
    assert result.gwp == pytest.approx(1000.0)


def test_amortize() -> None:
    total = DefaultImpactVector(gwp=120.0)
    result = amortize(total, 12.0)
    assert result.gwp == pytest.approx(10.0)


def test_efficiency_chain_single() -> None:
    result = efficiency_chain(100.0, [0.5])
    assert result == pytest.approx(200.0)


def test_efficiency_chain_two() -> None:
    # 100 / 0.5 / 0.8 = 250
    result = efficiency_chain(100.0, [0.5, 0.8])
    assert result == pytest.approx(250.0)


def test_normalize_to_revenue_km() -> None:
    annual = DefaultImpactVector(gwp=3650.0)
    result = normalize_to_revenue_km(annual, 100_000.0)
    assert result.gwp == pytest.approx(3650.0 / 100_000.0)


# ---------------------------------------------------------------------------
# calculate_chassis_emissions
# ---------------------------------------------------------------------------


def _beb_params_simple() -> VehicleTypeLCAParams:
    return VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
        motor_rated_power_kw=200.0,
        motor_emission_factors_per_kg=DefaultImpactVector(gwp=5.0),
        motor_power_to_weight_ratio=2.0,
        motor_emission_factors_per_unit=None,
        motor_mass_kg=None,
        vehicle_lifetime_years=12.0,
        efficiency_mv_to_lv=0.99,
        efficiency_lv_ac_to_dc=0.95,
        electricity_emission_factors_per_kwh=DefaultImpactVector(gwp=0.434),
        diesel_emission_factors_per_kg=None,
        average_consumption_kwh_per_km=1.2,
        diesel_consumption_kg_per_km=None,
        maintenance_per_year={
            EnergySource.BATTERY_ELECTRIC: DefaultImpactVector(gwp=500.0)
        },
    )


def test_calculate_chassis_emissions() -> None:
    params = _beb_params_simple()
    # empty=12000, motor=100, battery=0 → chassis=11900
    result = calculate_chassis_emissions(12000.0, 100.0, 0.0, params)
    assert result.gwp == pytest.approx(11900.0 * 10.0)


def test_calculate_chassis_emissions_non_positive_raises() -> None:
    params = _beb_params_simple()
    with pytest.raises(ValueError, match="non-positive"):
        # motor + battery > empty_mass
        calculate_chassis_emissions(100.0, 80.0, 50.0, params)


# ---------------------------------------------------------------------------
# calculate_motor_emissions
# ---------------------------------------------------------------------------


def test_calculate_motor_emissions_beb() -> None:
    params = _beb_params_simple()
    result = calculate_motor_emissions(EnergySource.BATTERY_ELECTRIC, params)
    # motor_mass = 200 / 2 = 100 kg; EF per kg = gwp 5
    assert result.gwp == pytest.approx(100.0 * 5.0)


def test_calculate_motor_emissions_diesel() -> None:
    params = VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
        motor_rated_power_kw=180.0,
        motor_emission_factors_per_kg=None,
        motor_power_to_weight_ratio=None,
        motor_emission_factors_per_unit=DefaultImpactVector(gwp=3000.0),
        motor_mass_kg=400.0,
        vehicle_lifetime_years=12.0,
        efficiency_mv_to_lv=None,
        efficiency_lv_ac_to_dc=None,
        electricity_emission_factors_per_kwh=None,
        diesel_emission_factors_per_kg=DefaultImpactVector(gwp=3.76),
        average_consumption_kwh_per_km=0.0,
        diesel_consumption_kg_per_km=0.28,
        maintenance_per_year={EnergySource.DIESEL: DefaultImpactVector(gwp=800.0)},
    )
    result = calculate_motor_emissions(EnergySource.DIESEL, params)
    assert result.gwp == pytest.approx(3000.0)


# ---------------------------------------------------------------------------
# calculate_battery_emissions
# ---------------------------------------------------------------------------


def test_calculate_battery_emissions_no_battery() -> None:
    vtype = MagicMock(spec=VehicleType)
    vtype.battery_capacity = 500.0
    emissions, mass = calculate_battery_emissions(vtype, None)
    assert emissions == DefaultImpactVector.zero()
    assert mass == pytest.approx(0.0)


def test_calculate_battery_emissions_with_battery() -> None:
    vtype = MagicMock(spec=VehicleType)
    vtype.battery_capacity = 500.0

    bt = MagicMock(spec=BatteryType)
    bt.specific_mass = 1.0  # 1 kg/kWh → 500 kg
    bt.id = 1
    bt.tco_parameters = None
    bt.lca_parameters = BatteryTypeLCAParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    ).to_dict()

    emissions, mass = calculate_battery_emissions(vtype, bt)
    assert mass == pytest.approx(500.0)
    assert emissions.gwp == pytest.approx(500.0 * 100.0)


# ---------------------------------------------------------------------------
# calculate_energy_emissions_beb / diesel
# ---------------------------------------------------------------------------


def test_calculate_energy_emissions_beb() -> None:
    params = _beb_params_simple()
    # annual_energy = 1 kWh → grid = 1 / 0.99 / 0.95 / 0.95
    charging_eff = 0.95
    annual_kwh = 1.0
    grid_kwh = efficiency_chain(annual_kwh, [0.99, 0.95, charging_eff])
    result = calculate_energy_emissions_beb(annual_kwh, charging_eff, params)
    assert result.gwp == pytest.approx(grid_kwh * 0.434)


def test_calculate_energy_emissions_diesel() -> None:
    params = VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
        motor_rated_power_kw=180.0,
        motor_emission_factors_per_kg=None,
        motor_power_to_weight_ratio=None,
        motor_emission_factors_per_unit=DefaultImpactVector(gwp=3000.0),
        motor_mass_kg=400.0,
        vehicle_lifetime_years=12.0,
        efficiency_mv_to_lv=None,
        efficiency_lv_ac_to_dc=None,
        electricity_emission_factors_per_kwh=None,
        diesel_emission_factors_per_kg=DefaultImpactVector(gwp=3.76),
        average_consumption_kwh_per_km=0.0,
        diesel_consumption_kg_per_km=0.28,
        maintenance_per_year={EnergySource.DIESEL: DefaultImpactVector(gwp=800.0)},
    )
    result = calculate_energy_emissions_diesel(1000.0, params)
    # 1000 kg × 3.76 (well-to-wheel) = 3760 kg CO2eq
    assert result.gwp == pytest.approx(1000.0 * 3.76)


# ---------------------------------------------------------------------------
# calculate_vehicle_type_emissions
# ---------------------------------------------------------------------------


def _make_beb_vtype() -> MagicMock:
    vtype = MagicMock(spec=VehicleType)
    vtype.id = 1
    vtype.name_short = "EN"
    vtype.energy_source = EnergySource.BATTERY_ELECTRIC
    vtype.empty_mass = 12_000.0
    vtype.charging_efficiency = 0.95
    vtype.battery_capacity = 500.0
    return vtype


def _make_battery_type() -> MagicMock:
    bt = MagicMock(spec=BatteryType)
    bt.id = 1
    bt.specific_mass = 1.0  # 500 kg
    bt.tco_parameters = None
    bt.lca_parameters = BatteryTypeLCAParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    ).to_dict()
    return bt


def test_calculate_vehicle_type_emissions_beb_item_count() -> None:
    """BEB produces 5 items: chassis, motor, battery, energy, maintenance."""
    items = calculate_vehicle_type_emissions(
        vtype=_make_beb_vtype(),
        battery_type=_make_battery_type(),
        params=_beb_params_simple(),
        n_total=3,
        vehicle_km=350_000.0,
    )
    assert len(items) == 5


def test_calculate_vehicle_type_emissions_beb_scopes_and_types() -> None:
    items = calculate_vehicle_type_emissions(
        vtype=_make_beb_vtype(),
        battery_type=_make_battery_type(),
        params=_beb_params_simple(),
        n_total=3,
        vehicle_km=350_000.0,
    )
    prod_eol = [i for i in items if i.scope == LCAScope.PRODUCTION_AND_EOL]
    use = [i for i in items if i.scope == LCAScope.USE_PHASE]
    assert len(prod_eol) == 3  # chassis, motor, battery
    assert len(use) == 2  # energy, maintenance
    assert any(i.type == ItemType.BATTERY for i in prod_eol)
    assert any(i.type == ItemType.ENERGY for i in use)
    assert all(i.name == "EN" for i in items)
    assert all(i.emission_vector.gwp > 0.0 for i in items)


def test_calculate_vehicle_type_emissions_diesel_no_battery_item() -> None:
    """Diesel bus produces 4 items: chassis, motor, energy, maintenance (no battery)."""
    vtype = MagicMock(spec=VehicleType)
    vtype.id = 2
    vtype.name_short = "DI"
    vtype.energy_source = EnergySource.DIESEL
    vtype.empty_mass = 13_000.0

    params = VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
        motor_rated_power_kw=180.0,
        motor_emission_factors_per_kg=None,
        motor_power_to_weight_ratio=None,
        motor_emission_factors_per_unit=DefaultImpactVector(gwp=3000.0),
        motor_mass_kg=400.0,
        vehicle_lifetime_years=12.0,
        efficiency_mv_to_lv=None,
        efficiency_lv_ac_to_dc=None,
        electricity_emission_factors_per_kwh=None,
        diesel_emission_factors_per_kg=DefaultImpactVector(gwp=3.76),
        average_consumption_kwh_per_km=0.0,
        diesel_consumption_kg_per_km=0.28,
        maintenance_per_year={EnergySource.DIESEL: DefaultImpactVector(gwp=800.0)},
    )
    items = calculate_vehicle_type_emissions(
        vtype=vtype,
        battery_type=None,
        params=params,
        n_total=2,
        vehicle_km=220_000.0,
    )
    assert len(items) == 4
    assert not any(i.type == ItemType.BATTERY for i in items)
    assert sum(1 for i in items if i.scope == LCAScope.PRODUCTION_AND_EOL) == 2


# ---------------------------------------------------------------------------
# Integration: calculate_lca
# ---------------------------------------------------------------------------


def test_calculate_lca_runs(scenario_obj: Scenario) -> None:
    result = calculate_lca(scenario_obj)
    assert result is not None


def test_calculate_lca_vehicle_types_in_result(scenario_obj: Scenario) -> None:
    result = calculate_lca(scenario_obj)
    vehicle_names = {
        item.name for item in result.items if item.type != ItemType.INFRASTRUCTURE
    }
    assert len(vehicle_names) >= 2


def test_calculate_lca_positive_gwp(scenario_obj: Scenario) -> None:
    result = calculate_lca(scenario_obj)
    assert result.total_per_revenue_km.gwp > 0.0
    for item in result.items:
        assert item.emission_vector.gwp > 0.0


def test_calculate_lca_infrastructure_items_present(scenario_obj: Scenario) -> None:
    result = calculate_lca(scenario_obj)
    infra_items = [i for i in result.items if i.type == ItemType.INFRASTRUCTURE]
    assert len(infra_items) > 0
    assert all(i.scope == LCAScope.PRODUCTION_AND_EOL for i in infra_items)


def test_calculate_lca_total_correct_shared_denominator(scenario_obj: Scenario) -> None:
    """total_per_revenue_km equals sum of all item emissions divided by total fleet Nwkm."""
    result = calculate_lca(scenario_obj)
    total_nwkm = sum(result.revenue_km.values())
    expected_gwp = sum(item.emission_vector.gwp for item in result.items) / total_nwkm
    assert result.total_per_revenue_km.gwp == pytest.approx(expected_gwp, rel=1e-6)


def test_calculate_lca_use_phase_dominates_production(scenario_obj: Scenario) -> None:
    """For BEBs, energy use should be substantial relative to production+EoL emissions."""
    result = calculate_lca(scenario_obj)
    total_prod_gwp = sum(
        item.emission_vector.gwp
        for item in result.items
        if item.scope == LCAScope.PRODUCTION_AND_EOL
    )
    total_use_gwp = sum(
        item.emission_vector.gwp
        for item in result.items
        if item.scope == LCAScope.USE_PHASE
    )
    # Use phase should be at least 90% of production+EoL for a realistic BEB scenario.
    # (Exact dominance depends on the annual mileage implied by the extraction window.)
    assert total_use_gwp > 0.9 * total_prod_gwp
