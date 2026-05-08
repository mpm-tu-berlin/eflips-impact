"""Tests for eflips.impact.tco.params (init_tco_parameters / from_json)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from eflips.model import BatteryType, ChargingPointType, Scenario, VehicleType
from eflips.impact.tco.dataclasses import (
    BatteryTypeTCOParameter,
    ChargingInfrastructureTCOParameter,
    ChargingPointTypeTCOParameter,
    ScenarioTCOParameter,
    VehicleTypeTCOParameter,
)
from eflips.impact.tco.params import init_tco_parameters, init_tco_parameters_from_json

from tests.tests_tco.conftest import (
    BATTERY_TCO_PARAMS,
    DEPOT_CPT_TCO_PARAMS,
    DEPOT_STATION_TCO_PARAMS,
    OPPORTUNITY_CPT_TCO_PARAMS,
    OPPORTUNITY_STATION_TCO_PARAMS,
    SCENARIO_ID,
    SCENARIO_TCO_PARAMS,
    VEHICLE_TYPE_TCO_PARAMS,
)

DEFAULTS_JSON = (
    Path(__file__).parent.parent.parent
    / "eflips"
    / "impact"
    / "defaults"
    / "example"
    / "tco.json"
)


# ---------------------------------------------------------------------------
# init_tco_parameters — scenario
# ---------------------------------------------------------------------------


def test_scenario_params_written(fleet_session: Session, scenario: Scenario) -> None:
    init_tco_parameters(
        scenario,
        scenario_params=ScenarioTCOParameter.from_dict(SCENARIO_TCO_PARAMS),
    )
    fleet_session.flush()
    fleet_session.refresh(scenario)
    assert scenario.tco_parameters["project_duration"] == 14
    assert scenario.tco_parameters["eta_avail"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# init_tco_parameters — vehicle types
# ---------------------------------------------------------------------------


def test_vehicle_type_params_written(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters(
        scenario,
        vehicle_type_params=[
            VehicleTypeTCOParameter.from_dict({"name_short": ns, **params})
            for ns, params in VEHICLE_TYPE_TCO_PARAMS.items()
        ],
    )
    fleet_session.flush()
    en = (
        fleet_session.query(VehicleType)
        .filter(VehicleType.name_short == "EN", VehicleType.scenario_id == SCENARIO_ID)
        .one()
    )
    assert en.tco_parameters["useful_life"] == 14
    assert en.tco_parameters["average_electricity_consumption"] == pytest.approx(1.48)


def test_unknown_vehicle_name_short_warns(
    fleet_session: Session, scenario: Scenario
) -> None:
    with pytest.warns(UserWarning, match="UNKNOWN_VT"):
        init_tco_parameters(
            scenario,
            vehicle_type_params=[
                VehicleTypeTCOParameter(
                    name_short="UNKNOWN_VT",
                    useful_life=10,
                    procurement_cost=100_000.0,
                    cost_escalation=0.0,
                    average_electricity_consumption=1.0,
                )
            ],
        )


# ---------------------------------------------------------------------------
# init_tco_parameters — battery types
# ---------------------------------------------------------------------------


def test_battery_type_params_written(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters(
        scenario,
        battery_type_params=[
            BatteryTypeTCOParameter(
                vehicle_name_short=ns,
                procurement_cost=BATTERY_TCO_PARAMS["procurement_cost"],
                useful_life=BATTERY_TCO_PARAMS["useful_life"],
                cost_escalation=BATTERY_TCO_PARAMS["cost_escalation"],
            )
            for ns in VEHICLE_TYPE_TCO_PARAMS
        ],
    )
    fleet_session.flush()
    bts = (
        fleet_session.query(BatteryType)
        .filter(BatteryType.scenario_id == SCENARIO_ID)
        .all()
    )
    assert len(bts) > 0
    for bt in bts:
        assert bt.tco_parameters is not None
        assert bt.tco_parameters["procurement_cost"] == pytest.approx(190.0)
        assert bt.tco_parameters["useful_life"] == 7


def test_battery_missing_assignment_warns(
    db_session: Session, scenario: Scenario
) -> None:
    """VehicleType without battery_type_id → skip with UserWarning."""
    # No BatteryType created, so battery_type_id is None for all VehicleTypes.
    with pytest.warns(UserWarning, match="no BatteryType assigned"):
        init_tco_parameters(
            scenario,
            battery_type_params=[
                BatteryTypeTCOParameter(
                    vehicle_name_short="EN",
                    procurement_cost=190.0,
                    useful_life=7,
                    cost_escalation=-0.03,
                )
            ],
        )


# ---------------------------------------------------------------------------
# init_tco_parameters — charging point types
# ---------------------------------------------------------------------------


def test_charging_point_type_params_written(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters(
        scenario,
        charging_point_type_params=[
            ChargingPointTypeTCOParameter.from_dict(
                {"type": "depot", **DEPOT_CPT_TCO_PARAMS}
            ),
            ChargingPointTypeTCOParameter.from_dict(
                {"type": "opportunity", **OPPORTUNITY_CPT_TCO_PARAMS}
            ),
        ],
    )
    fleet_session.flush()
    cpts = (
        fleet_session.query(ChargingPointType)
        .filter(ChargingPointType.scenario_id == SCENARIO_ID)
        .all()
    )
    assert len(cpts) == 2
    for cpt in cpts:
        assert cpt.tco_parameters is not None
        assert cpt.tco_parameters["useful_life"] == 20


def test_missing_cpt_warns(db_session: Session, scenario: Scenario) -> None:
    """No ChargingPointType rows → skip with UserWarning."""
    with pytest.warns(UserWarning, match="'depot' ChargingPointType"):
        init_tco_parameters(
            scenario,
            charging_point_type_params=[
                ChargingPointTypeTCOParameter.from_dict(
                    {"type": "depot", **DEPOT_CPT_TCO_PARAMS}
                )
            ],
        )


# ---------------------------------------------------------------------------
# init_tco_parameters — charging infrastructure (Station.tco_parameters)
# ---------------------------------------------------------------------------


def test_charging_infra_params_written(
    fleet_session: Session, scenario: Scenario
) -> None:
    from sqlalchemy import distinct
    from eflips.model import Depot, Event, EventType, Station

    init_tco_parameters(
        scenario,
        charging_infra_params=[
            ChargingInfrastructureTCOParameter.from_dict(
                {"type": "depot", **DEPOT_STATION_TCO_PARAMS}
            ),
            ChargingInfrastructureTCOParameter.from_dict(
                {"type": "station", **OPPORTUNITY_STATION_TCO_PARAMS}
            ),
        ],
    )
    fleet_session.flush()

    # All depot stations (via Depot.station_id) should have tco_parameters set.
    depot_station_ids = [
        sid
        for (sid,) in fleet_session.query(Depot.station_id)
        .filter(Depot.scenario_id == SCENARIO_ID)
        .all()
    ]
    assert len(depot_station_ids) > 0
    for sid in depot_station_ids:
        st = fleet_session.query(Station).filter(Station.id == sid).one()
        assert st.tco_parameters is not None
        assert st.tco_parameters["procurement_cost"] == pytest.approx(2_000_000.0)

    # All opportunity-charging stations should have tco_parameters set.
    opp_station_ids = [
        sid
        for (sid,) in fleet_session.query(distinct(Event.station_id))
        .filter(
            Event.scenario_id == SCENARIO_ID,
            Event.event_type == EventType.CHARGING_OPPORTUNITY,
        )
        .all()
        if sid is not None
    ]
    assert len(opp_station_ids) > 0
    for sid in opp_station_ids:
        st = fleet_session.query(Station).filter(Station.id == sid).one()
        assert st.tco_parameters is not None
        assert st.tco_parameters["procurement_cost"] == pytest.approx(500_000.0)


def test_battery_unknown_vehicle_name_short_warns(
    db_session: Session, scenario: Scenario
) -> None:
    """vehicle_name_short not in DB → skip with warning."""
    with pytest.warns(UserWarning, match="UNKNOWN"):
        init_tco_parameters(
            scenario,
            battery_type_params=[
                BatteryTypeTCOParameter(
                    vehicle_name_short="UNKNOWN",
                    procurement_cost=190.0,
                    useful_life=7,
                    cost_escalation=-0.03,
                )
            ],
        )


# ---------------------------------------------------------------------------
# init_tco_parameters_from_json
# ---------------------------------------------------------------------------


def test_init_from_json_writes_scenario_params(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters_from_json(scenario, DEFAULTS_JSON)
    fleet_session.flush()
    fleet_session.refresh(scenario)
    assert scenario.tco_parameters["project_duration"] == 14
    assert scenario.tco_parameters["eta_avail"] == pytest.approx(0.9)


def test_init_from_json_writes_vehicle_type_params(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters_from_json(scenario, DEFAULTS_JSON)
    fleet_session.flush()
    en = (
        fleet_session.query(VehicleType)
        .filter(VehicleType.name_short == "EN", VehicleType.scenario_id == SCENARIO_ID)
        .one()
    )
    assert en.tco_parameters is not None
    assert en.tco_parameters["procurement_cost"] == pytest.approx(340_000.0)


def test_init_from_json_writes_battery_type_params(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters_from_json(scenario, DEFAULTS_JSON)
    fleet_session.flush()
    bts = (
        fleet_session.query(BatteryType)
        .filter(BatteryType.scenario_id == SCENARIO_ID)
        .all()
    )
    assert len(bts) > 0
    for bt in bts:
        assert bt.tco_parameters is not None
        assert bt.tco_parameters["procurement_cost"] == pytest.approx(190.0)


def test_init_from_json_writes_cpt_params(
    fleet_session: Session, scenario: Scenario
) -> None:
    init_tco_parameters_from_json(scenario, DEFAULTS_JSON)
    fleet_session.flush()
    cpts = (
        fleet_session.query(ChargingPointType)
        .filter(ChargingPointType.scenario_id == SCENARIO_ID)
        .all()
    )
    assert len(cpts) == 2
    for cpt in cpts:
        assert cpt.tco_parameters is not None
