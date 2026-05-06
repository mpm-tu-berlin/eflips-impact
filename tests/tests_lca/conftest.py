"""Pytest fixtures for eflips-lca tests.

Extracts the gzipped sample SQLite database, applies the schema changes
introduced by eflips-model v10.1.0 and v10.2.0 via plain
``ALTER TABLE … ADD COLUMN`` statements (the alembic migration files use
PostgreSQL-specific SQL that cannot run against SQLite), stamps the
alembic version to ``head``, and populates ``lca_params`` on all relevant
ORM entities so that both extraction and calculation tests can run.
"""

from __future__ import annotations

import gzip
import importlib.resources
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

import eflips.model
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
    BatteryTypeLcaParams,
    ChargingPointTypeLcaParams,
    VehicleTypeLcaParams,
)
from eflips.impact.lca.util import DefaultImpactVector

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# Simulation window constants
# ---------------------------------------------------------------------------

SIM_START = datetime(2025, 6, 17, 0, 0, 0, tzinfo=timezone.utc)
SIM_END = datetime(2025, 6, 19, 0, 0, 0, tzinfo=timezone.utc)
SCENARIO_ID = 1
# ---------------------------------------------------------------------------
# Helpers to build realistic lca_params dicts
# ---------------------------------------------------------------------------


def _beb_vehicle_lca_params(
    consumption_kwh_per_km: float,
    motor_rated_power_kw: float,
) -> dict:
    """Return a realistic BEB VehicleTypeLcaParams dict.

    Args:
        consumption_kwh_per_km: Average energy consumption in kWh/km.
        motor_rated_power_kw: Rated motor power in kW.

    Returns:
        A dict suitable for ``VehicleType.lca_params``.
    """
    params = VehicleTypeLcaParams(
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


def _battery_lca_params() -> dict:
    """Return a realistic LFP BatteryTypeLcaParams dict.

    Returns:
        A dict suitable for ``BatteryType.lca_params``.
    """
    params = BatteryTypeLcaParams(
        emission_factors_per_kg=DefaultImpactVector(gwp=100.0),
        battery_lifetime_years=8.0,
    )
    return params.to_dict()


def _charging_point_lca_params() -> dict:
    """Return a realistic 150 kW CCS ChargingPointTypeLcaParams dict.

    Returns:
        A dict suitable for ``ChargingPointType.lca_params``.
    """
    params = ChargingPointTypeLcaParams(
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
    return params.to_dict()


# ---------------------------------------------------------------------------
# Engine fixture
# ---------------------------------------------------------------------------


def _make_alembic_cfg(engine: eflips.model.sqlalchemy.Engine) -> Config:  # type: ignore[name-defined]
    """Build an alembic Config pointing at the eflips-model migration scripts.

    Args:
        engine: The SQLAlchemy engine whose URL to configure.

    Returns:
        A configured ``alembic.config.Config``.
    """
    cfg = Config(str(importlib.resources.files("eflips.model").joinpath("alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.set_main_option(
        "script_location",
        str(importlib.resources.files("eflips.model").joinpath("migrations")),
    )
    return cfg


@pytest.fixture(scope="session")
def db_engine(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[type-arg]
    """Session-scoped engine backed by a schema-upgraded copy of sample.db.

    Extracts ``tests/data/sample.db.gz``, adds the columns introduced by
    eflips-model v10.1.0 (``energy_source``) and v10.2.0 (``lca_params``)
    via plain SQLite ``ALTER TABLE`` statements, and stamps the alembic
    version to ``head``.
    """
    tmp = tmp_path_factory.mktemp("db") / "sample.db"
    with gzip.open(DATA_DIR / "sample.db.gz", "rb") as f_in, open(tmp, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    engine = eflips.model.create_engine(f"sqlite:///{tmp}")

    with engine.begin() as conn:
        # v10.1.0: add energy_source to VehicleType
        conn.execute(text("ALTER TABLE VehicleType ADD COLUMN energy_source TEXT"))
        conn.execute(
            text("UPDATE \"VehicleType\" SET energy_source = 'BATTERY_ELECTRIC'")
        )
        # v10.2.0: add lca_params to three tables
        conn.execute(text("ALTER TABLE VehicleType ADD COLUMN lca_params JSON"))
        conn.execute(text("ALTER TABLE BatteryType ADD COLUMN lca_params JSON"))
        conn.execute(text("ALTER TABLE ChargingPointType ADD COLUMN lca_params JSON"))
        # BatteryType.chemistry is already TEXT in SQLite and the table is
        # empty, so no chemistry migration is needed.

    command.stamp(_make_alembic_cfg(engine), "head")
    return engine


# ---------------------------------------------------------------------------
# Session fixture: populate lca_params and yield
# ---------------------------------------------------------------------------

# Vehicle-type-specific consumption and motor power
_VTYPE_PARAMS: dict[int, tuple[float, float]] = {
    12: (1.2, 200.0),  # Ebusco 3.0 12 m
    13: (1.8, 300.0),  # Solaris Urbino 18 m
    14: (1.5, 250.0),  # Alexander Dennis Enviro500EV (no rotations)
}

# IDs of BEB depot areas and non-depot electrified terminal stations
_BEB_AREA_IDS = [5, 6, 11, 12, 17]
_TERMINAL_STATION_IDS = [3104, 62202, 79221, 195014, 260005, 1102005109]


@pytest.fixture(scope="session")
def db_session(db_engine) -> Generator[Session, None, None]:  # type: ignore[type-arg]
    """Session-scoped SQLAlchemy session with lca_params fully populated.

    Creates one ``ChargingPointType`` (150 kW CCS), one ``BatteryType``
    (LFP), assigns them to the relevant ORM entities, and sets
    ``lca_params`` on all three entity types before yielding the session.
    """
    with Session(db_engine) as session:
        # ---- ChargingPointType ------------------------------------------------
        cpt = ChargingPointType(
            scenario_id=SCENARIO_ID,
            name="CCS 150 kW",
            name_short="CCS150",
            lca_params=_charging_point_lca_params(),
        )
        session.add(cpt)
        session.flush()

        # ---- BatteryType (LFP, 1 kWh/kg → battery_mass = capacity_kWh kg) ----
        bt = BatteryType(
            scenario_id=SCENARIO_ID,
            specific_mass=1.0,
            chemistry="LFP",
            lca_params=_battery_lca_params(),
        )
        session.add(bt)
        session.flush()

        # ---- VehicleTypes -----------------------------------------------------
        for vtype in (
            session.query(VehicleType).filter_by(scenario_id=SCENARIO_ID).all()
        ):
            kwh_per_km, power_kw = _VTYPE_PARAMS[int(vtype.id)]
            vtype.lca_params = _beb_vehicle_lca_params(kwh_per_km, power_kw)
            vtype.battery_type_id = bt.id

        # ---- BEB depot areas --------------------------------------------------
        for area in session.query(Area).filter(Area.id.in_(_BEB_AREA_IDS)).all():
            area.charging_point_type_id = cpt.id

        # ---- Terminal stations ------------------------------------------------
        for station in (
            session.query(Station).filter(Station.id.in_(_TERMINAL_STATION_IDS)).all()
        ):
            station.charging_point_type_id = cpt.id

        session.commit()
        yield session


@pytest.fixture(scope="session")
def scenario_obj(db_session: Session) -> Scenario:
    """Session-scoped Scenario ORM object bound to db_session.

    Returns:
        The ``Scenario`` with id ``SCENARIO_ID`` from the test database.
    """
    return db_session.query(Scenario).filter(Scenario.id == SCENARIO_ID).one()
