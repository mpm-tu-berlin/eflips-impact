"""Pytest fixtures for eflips-impact LCA tests.

Uses ``tests/data/sample.db.gz`` as the test database.  The engine is
session-scoped (loaded once per pytest session).  ``db_session`` is also
session-scoped: it writes ``lca_parameters``, ``BatteryType``, and
``ChargingPointType`` rows once and all LCA tests share that committed state
(they are read-only after the setup commit).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator

import pytest
from sqlalchemy.orm import Session

from eflips.model import (
    Area,
    BatteryType,
    ChargingPointType,
    EnergySource,
    Scenario,
    Station,
    VehicleType,
)
from eflips.impact.lca.dataclasses import (
    BatteryTypeLCAParams,
    ChargingPointTypeLCAParams,
    VehicleTypeLCAParams,
)
from eflips.impact.lca.util import DefaultImpactVector
from db_setup import setup_sqlite_engine

SIM_START = datetime(2025, 6, 17, 0, 0, 0, tzinfo=timezone.utc)
SIM_END = datetime(2025, 6, 19, 0, 0, 0, tzinfo=timezone.utc)
SCENARIO_ID = 1

_VTYPE_PARAMS: dict[int, tuple[float, float]] = {
    12: (1.2, 200.0),
    13: (1.8, 300.0),
    14: (1.5, 250.0),
}
_BEB_AREA_IDS = [5, 6, 11, 12, 17]
_TERMINAL_STATION_IDS = [3104, 62202, 79221, 195014, 260005, 1102005109]


def _beb_vehicle_lca_parameters(
    consumption_kwh_per_km: float,
    motor_rated_power_kw: float,
) -> dict:
    params = VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=DefaultImpactVector(gwp=10.0),
        motor_rated_power_kw=motor_rated_power_kw,
        motor_emission_factors_per_kg=DefaultImpactVector(gwp=5.0),
        motor_power_to_weight_ratio=2.0,
        motor_emission_factors_per_unit=None,
        motor_mass_kg=None,
        vehicle_lifetime_years=12.0,
        efficiency_mv_to_lv=0.99,
        efficiency_lv_ac_to_dc=0.95,
        electricity_emission_factors_per_kwh=DefaultImpactVector(gwp=0.434),
        diesel_emission_factors_per_kg=None,
        average_consumption_kwh_per_km=consumption_kwh_per_km,
        diesel_consumption_kg_per_km=None,
        maintenance_per_year={
            EnergySource.BATTERY_ELECTRIC: DefaultImpactVector(gwp=500.0)
        },
        energy_source=EnergySource.BATTERY_ELECTRIC,
    )
    return params.to_dict()


def _battery_lca_parameters() -> dict:
    return BatteryTypeLCAParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    ).to_dict()


def _charging_point_lca_parameters() -> dict:
    return ChargingPointTypeLCAParams(
        control_unit_emissions=DefaultImpactVector(gwp=500.0),
        power_unit_emission=DefaultImpactVector(gwp=9000.0),
        power_unit_rated_power_kw=150.0,
        user_unit_emission=DefaultImpactVector(gwp=600.0),
        transformer_emissions=DefaultImpactVector(gwp=2000.0),
        transformer_ref_power_kw=315.0,
        concrete_emissions_per_m3=DefaultImpactVector(gwp=300.0),
        foundation_volume_per_point_m3=0.5,
        infrastructure_lifetime_years=15.0,
    ).to_dict()


@pytest.fixture(scope="session")
def db_engine(tmp_path_factory: pytest.TempPathFactory):
    engine = setup_sqlite_engine(tmp_path_factory)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def db_session(db_engine) -> Generator[Session, None, None]:
    """Session-scoped SQLAlchemy session with lca_parameters fully populated."""
    with Session(db_engine) as session:
        cpt = ChargingPointType(
            scenario_id=SCENARIO_ID,
            name="CCS 150 kW",
            name_short="CCS150",
            lca_parameters=_charging_point_lca_parameters(),
        )
        session.add(cpt)
        session.flush()

        bt = BatteryType(
            scenario_id=SCENARIO_ID,
            specific_mass=1.0,
            chemistry="LFP",
            lca_parameters=_battery_lca_parameters(),
        )
        session.add(bt)
        session.flush()

        for vtype in (
            session.query(VehicleType).filter_by(scenario_id=SCENARIO_ID).all()
        ):
            kwh_per_km, power_kw = _VTYPE_PARAMS[int(vtype.id)]
            vtype.lca_parameters = _beb_vehicle_lca_parameters(kwh_per_km, power_kw)
            vtype.battery_type_id = bt.id

        for area in session.query(Area).filter(Area.id.in_(_BEB_AREA_IDS)).all():
            area.charging_point_type_id = cpt.id

        for station in (
            session.query(Station).filter(Station.id.in_(_TERMINAL_STATION_IDS)).all()
        ):
            station.charging_point_type_id = cpt.id

        session.commit()
        yield session


@pytest.fixture(scope="session")
def scenario_obj(db_session: Session) -> Scenario:
    return db_session.query(Scenario).filter(Scenario.id == SCENARIO_ID).one()
