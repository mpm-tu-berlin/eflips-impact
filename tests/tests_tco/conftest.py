"""Pytest fixtures for eflips.impact.tco tests.

Uses the same sample.db.gz as tests_lca. Each test gets a fresh function-scoped
DB so that mutations don't leak between tests.
"""

from __future__ import annotations

import gzip
import importlib.resources
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import distinct, text
from sqlalchemy.orm import Session

import eflips.model
from eflips.model import (
    Event,
    EventType,
    Process,
    Scenario,
    Area,
    VehicleType,
)
from eflips.impact.utils import init_fleet

DATA_DIR = Path(__file__).parent.parent / "tests_lca" / "data"
SCENARIO_ID = 1
SIM_START = datetime(2025, 6, 17, 0, 0, 0, tzinfo=timezone.utc)
SIM_END = datetime(2025, 6, 19, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Shared parameter constants
# ---------------------------------------------------------------------------

SCENARIO_TCO_PARAMS: dict = {
    "project_duration": 14,
    "interest_rate": 0.04,
    "inflation_rate": 0.02,
    "staff_cost": 35.0,
    "fuel_cost": {"diesel": 1.0, "electricity": 0.15},
    "vehicle_maint_cost": {"diesel": 0.5, "electricity": 0.20},
    "infra_maint_cost": 5000.0,
    "cost_escalation_rate": {
        "general": 0.02,
        "staff": 0.02,
        "diesel": 0.07,
        "electricity": 0.03,
        "insurance": 0.02,
    },
    "insurance": 3000.0,
    "taxes": 0.0,
    "eta_avail": 0.9,
}

VEHICLE_TYPE_TCO_PARAMS: dict[str, dict] = {
    "EN": {
        "useful_life": 14,
        "procurement_cost": 340_000.0,
        "cost_escalation": -0.02,
        "average_electricity_consumption": 1.48,
    },
    "DD": {
        "useful_life": 14,
        "procurement_cost": 603_000.0,
        "cost_escalation": -0.02,
        "average_electricity_consumption": 2.16,
    },
    "GN": {
        "useful_life": 14,
        "procurement_cost": 650_000.0,
        "cost_escalation": -0.02,
        "average_electricity_consumption": 2.16,
    },
}

BATTERY_TCO_PARAMS: dict = {
    "procurement_cost": 190.0,
    "useful_life": 7,
    "cost_escalation": -0.03,
}

DEPOT_CPT_TCO_PARAMS: dict = {
    "procurement_cost": 100_000.0,
    "useful_life": 20,
    "cost_escalation": 0.0,
}

OPPORTUNITY_CPT_TCO_PARAMS: dict = {
    "procurement_cost": 250_000.0,
    "useful_life": 20,
    "cost_escalation": 0.0,
}

DEPOT_STATION_TCO_PARAMS: dict = {
    "procurement_cost": 2_000_000.0,
    "useful_life": 20,
    "cost_escalation": 0.0,
}

OPPORTUNITY_STATION_TCO_PARAMS: dict = {
    "procurement_cost": 500_000.0,
    "useful_life": 20,
    "cost_escalation": 0.0,
}

# ---------------------------------------------------------------------------
# Fleet topology helper
# ---------------------------------------------------------------------------


def _full_fleet_dict() -> dict:
    """Return a fleet.json payload matching the sample DB topology.

    Sample DB has BEB VehicleTypes with name_short EN, DD, GN, plus depot
    charging Areas and CHARGING_OPPORTUNITY events.
    """
    return {
        "schema_version": 1,
        "battery_types": [
            {"vehicle_name_short": "EN", "specific_mass": 6.0, "chemistry": "lfp"},
            {"vehicle_name_short": "DD", "specific_mass": 6.0, "chemistry": "lfp"},
            {"vehicle_name_short": "GN", "specific_mass": 6.0, "chemistry": "lfp"},
        ],
        "charging_point_types": [
            {"type": "depot", "name": "Depot CP", "name_short": "DCP"},
            {"type": "opportunity", "name": "Opportunity CP", "name_short": "OCP"},
        ],
    }


# ---------------------------------------------------------------------------
# Alembic helper
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


# ---------------------------------------------------------------------------
# Engine fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine(tmp_path: Path):  # type: ignore[type-arg]
    """Function-scoped engine backed by a fresh extract of sample.db.

    Applies the same schema upgrades used in tests_lca/conftest.py so that
    the alembic version can be stamped to head.
    """
    db_path = tmp_path / "sample.db"
    with (
        gzip.open(DATA_DIR / "sample.db.gz", "rb") as f_in,
        open(db_path, "wb") as f_out,
    ):
        shutil.copyfileobj(f_in, f_out)

    engine = eflips.model.create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE VehicleType ADD COLUMN energy_source TEXT"))
        conn.execute(
            text("UPDATE \"VehicleType\" SET energy_source = 'BATTERY_ELECTRIC'")
        )
        conn.execute(text("ALTER TABLE VehicleType ADD COLUMN lca_params JSON"))
        conn.execute(text("ALTER TABLE BatteryType ADD COLUMN lca_params JSON"))
        conn.execute(text("ALTER TABLE ChargingPointType ADD COLUMN lca_params JSON"))

    command.stamp(_make_alembic_cfg(engine), "head")
    try:
        yield engine
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:  # type: ignore[type-arg]
    """Function-scoped session; mutations are rolled back on teardown."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def scenario(db_session: Session) -> Scenario:
    """The single Scenario from sample.db (id=1)."""
    return db_session.query(Scenario).filter(Scenario.id == SCENARIO_ID).one()


# ---------------------------------------------------------------------------
# Fleet topology fixture (BatteryType + ChargingPointType rows)
# ---------------------------------------------------------------------------


@pytest.fixture
def fleet_session(db_session: Session, scenario: Scenario, tmp_path: Path) -> Session:
    """Session with fleet topology initialised via :func:`init_fleet`.

    Creates one BatteryType per BEB VehicleType (EN, DD, GN) and two
    ChargingPointType rows (depot, opportunity), assigning them to the
    relevant VehicleType / Area / Station rows.
    """
    fleet_path = tmp_path / "fleet.json"
    fleet_path.write_text(json.dumps(_full_fleet_dict()), encoding="utf-8")
    init_fleet(scenario, fleet_path, delete_existing_data=False)
    return db_session


# ---------------------------------------------------------------------------
# Fully-populated TCO fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def tco_session(fleet_session: Session, scenario: Scenario) -> Session:
    """Fleet session with all tco_parameters written via :func:`init_tco_parameters`.

    Sets tco_parameters on the Scenario, all VehicleTypes, all BatteryTypes,
    both ChargingPointTypes, and all charging-station Station rows.
    """
    from eflips.impact.tco.params import init_tco_parameters
    from eflips.impact.tco.dataclasses import (
        ScenarioTCOParameter,
        VehicleTypeTCOParameter,
        BatteryTypeTCOParameter,
        ChargingPointTypeTCOParameter,
        ChargingInfrastructureTCOParameter,
    )

    init_tco_parameters(
        scenario,
        scenario_params=ScenarioTCOParameter.from_dict(SCENARIO_TCO_PARAMS),
        vehicle_type_params=[
            VehicleTypeTCOParameter.from_dict({"name_short": ns, **params})
            for ns, params in VEHICLE_TYPE_TCO_PARAMS.items()
        ],
        battery_type_params=[
            BatteryTypeTCOParameter(
                vehicle_name_short=ns,
                procurement_cost=BATTERY_TCO_PARAMS["procurement_cost"],
                useful_life=BATTERY_TCO_PARAMS["useful_life"],
                cost_escalation=BATTERY_TCO_PARAMS["cost_escalation"],
            )
            for ns in VEHICLE_TYPE_TCO_PARAMS
        ],
        charging_point_type_params=[
            ChargingPointTypeTCOParameter.from_dict({"type": "depot", **DEPOT_CPT_TCO_PARAMS}),
            ChargingPointTypeTCOParameter.from_dict(
                {"type": "opportunity", **OPPORTUNITY_CPT_TCO_PARAMS}
            ),
        ],
        charging_infra_params=[
            ChargingInfrastructureTCOParameter.from_dict(
                {"type": "depot", **DEPOT_STATION_TCO_PARAMS}
            ),
            ChargingInfrastructureTCOParameter.from_dict(
                {"type": "station", **OPPORTUNITY_STATION_TCO_PARAMS}
            ),
        ],
    )
    return fleet_session
