"""Pytest fixtures for eflips-impact TCO tests.

Uses ``tests/data/sample.db.gz`` as the test database.  ``db_engine`` is
session-scoped (loaded once per pytest session).  ``db_session`` is
function-scoped: each test receives a fresh ``Session`` backed by the shared
engine; any writes are rolled back on teardown so tests cannot contaminate
each other.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy.orm import Session

from eflips.model import Scenario
from eflips.impact.utils import complete_fleet
from db_setup import setup_sqlite_engine

SIM_START = datetime(2025, 6, 17, 0, 0, 0, tzinfo=timezone.utc)
SIM_END = datetime(2025, 6, 19, 0, 0, 0, tzinfo=timezone.utc)
SCENARIO_ID = 1

# ---------------------------------------------------------------------------
# Shared TCO parameter constants (imported by test_params.py)
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


def _full_fleet_dict() -> dict:
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
# Engine fixture (session-scoped – one database per test session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine(tmp_path_factory: pytest.TempPathFactory):
    engine = setup_sqlite_engine(tmp_path_factory)
    try:
        yield engine
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Session fixture (function-scoped – rolls back after each test)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Function-scoped session; all writes are rolled back on teardown."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def scenario(db_session: Session) -> Scenario:
    return db_session.query(Scenario).filter(Scenario.id == SCENARIO_ID).one()


@pytest.fixture
def fleet_session(db_session: Session, scenario: Scenario, tmp_path: Path) -> Session:
    """Session with fleet topology initialised via :func:`complete_fleet`."""
    fleet_path = tmp_path / "fleet.json"
    fleet_path.write_text(json.dumps(_full_fleet_dict()), encoding="utf-8")
    complete_fleet(scenario, fleet_path, delete_existing_data=False)
    return db_session


@pytest.fixture
def tco_session(fleet_session: Session, scenario: Scenario, tmp_path: Path) -> Session:
    """Fleet session with all tco_parameters written via :func:`init_tco_params`."""
    from eflips.impact.tco import init_tco_params

    params = {
        "scenario": SCENARIO_TCO_PARAMS,
        "vehicle_types": [
            {"name_short": ns, **p} for ns, p in VEHICLE_TYPE_TCO_PARAMS.items()
        ],
        "battery_types": [
            {"vehicle_name_short": ns, **BATTERY_TCO_PARAMS}
            for ns in VEHICLE_TYPE_TCO_PARAMS
        ],
        "charging_point_types": [
            {"type": "depot", **DEPOT_CPT_TCO_PARAMS},
            {"type": "opportunity", **OPPORTUNITY_CPT_TCO_PARAMS},
        ],
        "charging_infrastructure": [
            {"type": "depot", **DEPOT_STATION_TCO_PARAMS},
            {"type": "station", **OPPORTUNITY_STATION_TCO_PARAMS},
        ],
    }
    params_path = tmp_path / "tco_params.json"
    params_path.write_text(json.dumps(params), encoding="utf-8")
    init_tco_params(scenario, params_path)
    return fleet_session
