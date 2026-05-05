"""Tests for eflips.lca.dataclasses (param serialisation and validation)."""

from __future__ import annotations

import pytest

from eflips.model import EnergySource

from eflips.impact.lca.dataclasses import (
    BatteryTypeLcaParams,
    ChargingPointTypeLcaParams,
    VehicleTypeLcaParams,
)
from eflips.impact.lca.util import DefaultImpactVector

# ---------------------------------------------------------------------------
# Shared param builders
# ---------------------------------------------------------------------------


def _beb_params() -> VehicleTypeLcaParams:
    return VehicleTypeLcaParams(
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
        energy_source=EnergySource.BATTERY_ELECTRIC,
    )


def _diesel_params() -> VehicleTypeLcaParams:
    return VehicleTypeLcaParams(
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
        energy_source=EnergySource.DIESEL,
    )


# ---------------------------------------------------------------------------
# VehicleTypeLcaParams
# ---------------------------------------------------------------------------


def test_vehicle_lca_params_beb_roundtrip() -> None:
    p = _beb_params()
    restored = VehicleTypeLcaParams.from_dict(p.to_dict())
    assert restored.motor_rated_power_kw == pytest.approx(200.0)
    assert restored.average_consumption_kwh_per_km == pytest.approx(1.2)
    assert restored.electricity_emission_factors_per_kwh is not None
    assert restored.electricity_emission_factors_per_kwh.gwp == pytest.approx(0.434)
    assert restored.diesel_consumption_kg_per_km is None
    assert EnergySource.BATTERY_ELECTRIC in restored.maintenance_per_year


def test_vehicle_lca_params_diesel_roundtrip() -> None:
    p = _diesel_params()
    restored = VehicleTypeLcaParams.from_dict(p.to_dict())
    assert restored.diesel_consumption_kg_per_km == pytest.approx(0.28)
    assert restored.motor_emission_factors_per_unit is not None
    assert restored.motor_emission_factors_per_unit.gwp == pytest.approx(3000.0)
    assert restored.electricity_emission_factors_per_kwh is None
    assert EnergySource.DIESEL in restored.maintenance_per_year


def test_vehicle_lca_params_beb_rejects_diesel_fields() -> None:
    with pytest.raises(ValueError, match="diesel_emission_factors_per_kg"):
        VehicleTypeLcaParams(
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
            diesel_emission_factors_per_kg=DefaultImpactVector(gwp=3.76),
            average_consumption_kwh_per_km=1.2,
            diesel_consumption_kg_per_km=None,
            maintenance_per_year={
                EnergySource.BATTERY_ELECTRIC: DefaultImpactVector(gwp=500.0)
            },
            energy_source=EnergySource.BATTERY_ELECTRIC,
        )


def test_vehicle_lca_params_beb_rejects_motor_mass_kg() -> None:
    with pytest.raises(ValueError, match="motor_mass_kg must be None"):
        VehicleTypeLcaParams(
            chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
            motor_rated_power_kw=200.0,
            motor_emission_factors_per_kg=DefaultImpactVector(gwp=5.0),
            motor_power_to_weight_ratio=2.0,
            motor_emission_factors_per_unit=None,
            motor_mass_kg=100.0,
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
            energy_source=EnergySource.BATTERY_ELECTRIC,
        )


def test_vehicle_lca_params_diesel_requires_motor_mass_kg() -> None:
    with pytest.raises(ValueError, match="motor_mass_kg is required for DIESEL"):
        VehicleTypeLcaParams(
            chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
            motor_rated_power_kw=180.0,
            motor_emission_factors_per_kg=None,
            motor_power_to_weight_ratio=None,
            motor_emission_factors_per_unit=DefaultImpactVector(gwp=3000.0),
            motor_mass_kg=None,
            vehicle_lifetime_years=12.0,
            efficiency_mv_to_lv=None,
            efficiency_lv_ac_to_dc=None,
            electricity_emission_factors_per_kwh=None,
            diesel_emission_factors_per_kg=DefaultImpactVector(gwp=3.76),
            average_consumption_kwh_per_km=0.0,
            diesel_consumption_kg_per_km=0.28,
            maintenance_per_year={EnergySource.DIESEL: DefaultImpactVector(gwp=800.0)},
            energy_source=EnergySource.DIESEL,
        )


def test_vehicle_lca_params_diesel_rejects_beb_fields() -> None:
    with pytest.raises(ValueError, match="motor_emission_factors_per_kg"):
        VehicleTypeLcaParams(
            chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
            motor_rated_power_kw=180.0,
            motor_emission_factors_per_kg=DefaultImpactVector(gwp=5.0),
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
            energy_source=EnergySource.DIESEL,
        )


def test_vehicle_lca_params_diesel_requires_consumption() -> None:
    with pytest.raises(ValueError, match="diesel_consumption_kg_per_km"):
        VehicleTypeLcaParams(
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
            diesel_consumption_kg_per_km=None,  # missing!
            maintenance_per_year={EnergySource.DIESEL: DefaultImpactVector(gwp=800.0)},
            energy_source=EnergySource.DIESEL,
        )


# ---------------------------------------------------------------------------
# BatteryTypeLcaParams
# ---------------------------------------------------------------------------


def test_battery_lca_params_roundtrip() -> None:
    p = BatteryTypeLcaParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    )
    restored = BatteryTypeLcaParams.from_dict(p.to_dict())
    assert restored.battery_lifetime_years == pytest.approx(8.0)
    assert restored.emission_factors_per_kg.gwp == pytest.approx(100.0)


def test_battery_tco_consistency_warning() -> None:
    p = BatteryTypeLcaParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    )
    with pytest.warns(UserWarning, match="TCO useful_life"):
        p.check_tco_consistency(tco_useful_life=10.0)


def test_battery_tco_consistency_no_warning_when_equal(
    recwarn: pytest.WarningsChecker,
) -> None:
    p = BatteryTypeLcaParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    )
    p.check_tco_consistency(tco_useful_life=8.0)
    assert len(recwarn) == 0


def test_battery_tco_consistency_no_warning_when_none(
    recwarn: pytest.WarningsChecker,
) -> None:
    p = BatteryTypeLcaParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    )
    p.check_tco_consistency(tco_useful_life=None)
    assert len(recwarn) == 0


# ---------------------------------------------------------------------------
# ChargingPointTypeLcaParams
# ---------------------------------------------------------------------------


def test_charging_point_lca_params_roundtrip() -> None:
    p = ChargingPointTypeLcaParams(
        control_unit_emissions=DefaultImpactVector(gwp=500.0),
        power_unit_emission=DefaultImpactVector(gwp=9000.0),
        power_unit_rated_power_kw=150.0,
        user_unit_emission=DefaultImpactVector(gwp=600.0),
        transformer_emissions=DefaultImpactVector(gwp=2000.0),
        transformer_ref_power_kw=315.0,
        concrete_emissions_per_m3=DefaultImpactVector(gwp=300.0),
        foundation_volume_per_point_m3=0.5,
        infrastructure_lifetime_years=15.0,
    )
    restored = ChargingPointTypeLcaParams.from_dict(p.to_dict())
    assert restored.power_unit_rated_power_kw == pytest.approx(150.0)
    assert restored.infrastructure_lifetime_years == pytest.approx(15.0)
    assert restored.concrete_emissions_per_m3.gwp == pytest.approx(300.0)
    assert restored.transformer_emissions.gwp == pytest.approx(2000.0)
