"""Unit tests for eflips.impact.tco.dataclasses parameter dataclasses."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from eflips.impact.tco.dataclasses import (
    BatteryTypeTCOParameter,
    ChargingInfrastructureTCOParameter,
    ChargingPointTypeTCOParameter,
    ScenarioTCOParameter,
    TcoParamSet,
    VehicleTypeTCOParameter,
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
# VehicleTypeTCOParameter
# ---------------------------------------------------------------------------


def test_vehicle_type_electric_roundtrip() -> None:
    p = VehicleTypeTCOParameter(
        name_short="EN",
        useful_life=14,
        procurement_cost=340_000.0,
        cost_escalation=-0.02,
        average_electricity_consumption=1.48,
    )
    d = p.to_dict()
    assert d["useful_life"] == 14
    assert d["procurement_cost"] == pytest.approx(340_000.0)
    assert "average_electricity_consumption" in d
    assert "average_diesel_consumption" not in d


def test_vehicle_type_diesel_roundtrip() -> None:
    p = VehicleTypeTCOParameter(
        name_short="DI",
        useful_life=12,
        procurement_cost=250_000.0,
        cost_escalation=0.0,
        average_diesel_consumption=0.28,
    )
    d = p.to_dict()
    assert "average_diesel_consumption" in d
    assert "average_electricity_consumption" not in d


def test_vehicle_type_both_consumption_raises() -> None:
    with pytest.raises(ValueError, match="Exactly one"):
        VehicleTypeTCOParameter(
            name_short="X",
            useful_life=10,
            procurement_cost=100_000.0,
            cost_escalation=0.0,
            average_electricity_consumption=1.0,
            average_diesel_consumption=0.28,
        )


def test_vehicle_type_neither_consumption_raises() -> None:
    with pytest.raises(ValueError, match="Exactly one"):
        VehicleTypeTCOParameter(
            name_short="X",
            useful_life=10,
            procurement_cost=100_000.0,
            cost_escalation=0.0,
        )


def test_vehicle_type_from_dict_electric() -> None:
    d = {
        "name_short": "EN",
        "useful_life": 14,
        "procurement_cost": 340_000.0,
        "cost_escalation": -0.02,
        "average_electricity_consumption": 1.48,
    }
    p = VehicleTypeTCOParameter.from_dict(d)
    assert p.name_short == "EN"
    assert p.average_electricity_consumption == pytest.approx(1.48)
    assert p.average_diesel_consumption is None


# ---------------------------------------------------------------------------
# BatteryTypeTCOParameter
# ---------------------------------------------------------------------------


def test_battery_type_roundtrip() -> None:
    p = BatteryTypeTCOParameter(
        vehicle_name_short="EN",
        procurement_cost=190.0,
        useful_life=7,
        cost_escalation=-0.03,
    )
    d = p.to_dict()
    assert "procurement_cost" in d
    assert "useful_life" in d
    assert "cost_escalation" in d
    assert "vehicle_name_short" not in d  # not stored in the DB dict


def test_battery_type_from_dict() -> None:
    d = {
        "vehicle_name_short": "DD",
        "procurement_cost": 200.0,
        "useful_life": 8,
        "cost_escalation": -0.02,
    }
    p = BatteryTypeTCOParameter.from_dict(d)
    assert p.vehicle_name_short == "DD"
    assert p.useful_life == 8


# ---------------------------------------------------------------------------
# ChargingPointTypeTCOParameter
# ---------------------------------------------------------------------------


def test_cpt_roundtrip() -> None:
    p = ChargingPointTypeTCOParameter(
        type="depot", procurement_cost=100_000.0, useful_life=20, cost_escalation=0.0
    )
    d = p.to_dict()
    assert d["procurement_cost"] == pytest.approx(100_000.0)
    assert d["useful_life"] == 20
    assert "type" not in d  # type is the match key, not stored in the DB dict


def test_cpt_from_dict() -> None:
    d = {
        "type": "opportunity",
        "procurement_cost": 250_000.0,
        "useful_life": 20,
        "cost_escalation": 0.0,
    }
    p = ChargingPointTypeTCOParameter.from_dict(d)
    assert p.type == "opportunity"


# ---------------------------------------------------------------------------
# ScenarioTCOParameter
# ---------------------------------------------------------------------------


def test_scenario_to_dict_includes_eta_avail() -> None:
    p = ScenarioTCOParameter(
        project_duration=14,
        interest_rate=0.04,
        inflation_rate=0.02,
        staff_cost=35.0,
        fuel_cost={"diesel": 1.0, "electricity": 0.15},
        vehicle_maint_cost={"diesel": 0.5, "electricity": 0.20},
        infra_maint_cost=5000.0,
        cost_escalation_rate={
            "general": 0.02,
            "staff": 0.02,
            "diesel": 0.07,
            "electricity": 0.03,
            "insurance": 0.02,
        },
        insurance=3000.0,
        taxes=0.0,
        eta_avail=0.9,
    )
    d = p.to_dict()
    assert d["eta_avail"] == pytest.approx(0.9)
    assert d["project_duration"] == 14


def test_scenario_default_eta_avail() -> None:
    p = ScenarioTCOParameter(
        project_duration=14,
        interest_rate=0.04,
        inflation_rate=0.02,
        staff_cost=35.0,
        fuel_cost={"diesel": 1.0, "electricity": 0.15},
        vehicle_maint_cost={"diesel": 0.5, "electricity": 0.20},
        infra_maint_cost=5000.0,
        cost_escalation_rate={
            "general": 0.02,
            "staff": 0.02,
            "diesel": 0.07,
            "electricity": 0.03,
            "insurance": 0.02,
        },
        insurance=3000.0,
        taxes=0.0,
    )
    assert p.eta_avail == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# TcoParamSet.from_json
# ---------------------------------------------------------------------------


def test_tco_param_set_from_json_loads() -> None:
    params = TcoParamSet.from_json(DEFAULTS_JSON)
    assert params.scenario.project_duration == 14
    assert params.scenario.eta_avail == pytest.approx(0.9)
    assert len(params.vehicle_types) == 3
    assert len(params.battery_types) == 3
    assert len(params.charging_point_types) == 2
    assert len(params.charging_infrastructure) == 2


def test_tco_param_set_vehicle_type_names() -> None:
    params = TcoParamSet.from_json(DEFAULTS_JSON)
    name_shorts = {vt.name_short for vt in params.vehicle_types}
    assert name_shorts == {"EN", "DD", "GN"}


def test_tco_param_set_cpt_types() -> None:
    params = TcoParamSet.from_json(DEFAULTS_JSON)
    types = {cpt.type for cpt in params.charging_point_types}
    assert types == {"depot", "opportunity"}
