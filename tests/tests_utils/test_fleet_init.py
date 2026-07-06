"""Tests for :func:`eflips.impact.utils.fleet_init.complete_fleet`."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from eflips.model import (
    Area,
    BatteryType,
    ChargingPointType,
    EnergySource,
    Event,
    EventType,
    Process,
    Scenario,
    Station,
    VehicleType,
)
from eflips.impact.utils import complete_fleet

SCENARIO_ID = 1


# ---------------------------------------------------------------------------
# fleet.json builders
# ---------------------------------------------------------------------------


def _full_fleet_dict() -> dict:
    """Return a fleet.json dict that matches the sample DB topology.

    Sample DB has BEB VehicleTypes with name_short ``EN``, ``GN``, ``DD``,
    plus depot charging Areas and CHARGING_OPPORTUNITY events — so both
    ``depot`` and ``opportunity`` CPT entries are required.
    """
    return {
        "schema_version": 1,
        "battery_types": [
            {"vehicle_name_short": "EN", "specific_mass": 6.0, "chemistry": "lfp"},
            {"vehicle_name_short": "GN", "specific_mass": 6.0, "chemistry": "lfp"},
            {"vehicle_name_short": "DD", "specific_mass": 6.0, "chemistry": "lfp"},
        ],
        "charging_point_types": [
            {"type": "depot", "name": "Depot CP", "name_short": "DCP"},
            {"type": "opportunity", "name": "Opportunity CP", "name_short": "OCP"},
        ],
    }


def _write_fleet_json(tmp_path: Path, data: dict) -> Path:
    """Write ``data`` to ``tmp_path/fleet.json`` and return the path."""
    p = tmp_path / "fleet.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Empty scenario, valid fleet.json, ``delete_existing_data=False``."""

    def test_creates_battery_types_and_assigns_to_vehicle_types(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        path = _write_fleet_json(tmp_path, _full_fleet_dict())

        complete_fleet(scenario, path, delete_existing_data=False)

        bts = (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .all()
        )
        assert len(bts) == 3
        assert {bt.chemistry for bt in bts} == {"lfp"}
        assert {bt.specific_mass for bt in bts} == {6.0}

        vts = (
            db_session.query(VehicleType)
            .filter(VehicleType.scenario_id == SCENARIO_ID)
            .all()
        )
        assert all(vt.battery_type_id is not None for vt in vts)
        # Each VehicleType should reference a distinct BatteryType row.
        assert len({vt.battery_type_id for vt in vts}) == 3

    def test_creates_charging_point_types_and_assigns_to_areas_and_stations(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        path = _write_fleet_json(tmp_path, _full_fleet_dict())

        complete_fleet(scenario, path, delete_existing_data=False)

        cpts = (
            db_session.query(ChargingPointType)
            .filter(ChargingPointType.scenario_id == SCENARIO_ID)
            .all()
        )
        assert {cpt.name for cpt in cpts} == {"Depot CP", "Opportunity CP"}
        cpt_by_name = {cpt.name: cpt for cpt in cpts}

        # Depot CPT assigned to every Area whose Process has electric_power.
        charging_areas = (
            db_session.query(Area)
            .filter(
                Area.scenario_id == SCENARIO_ID,
                Area.processes.any(Process.electric_power.isnot(None)),
            )
            .all()
        )
        assert len(charging_areas) > 0
        assert all(
            a.charging_point_type_id == cpt_by_name["Depot CP"].id
            for a in charging_areas
        )

        # Opportunity CPT assigned to every Station referenced by a
        # CHARGING_OPPORTUNITY event in the scenario.
        opp_station_ids = {
            sid
            for (sid,) in db_session.query(distinct(Event.station_id))
            .filter(
                Event.scenario_id == SCENARIO_ID,
                Event.event_type == EventType.CHARGING_OPPORTUNITY,
            )
            .all()
        }
        assert len(opp_station_ids) > 0
        for sid in opp_station_ids:
            station = db_session.query(Station).filter(Station.id == sid).one()
            assert station.charging_point_type_id == cpt_by_name["Opportunity CP"].id

    def test_silently_skips_extra_battery_entries(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        data = _full_fleet_dict()
        data["battery_types"].append(
            {"vehicle_name_short": "ZZ", "specific_mass": 5.0, "chemistry": "nmc"}
        )
        path = _write_fleet_json(tmp_path, data)

        complete_fleet(scenario, path, delete_existing_data=False)

        bts = (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .all()
        )
        # Extra entry has no matching BEB VehicleType → silently dropped.
        assert len(bts) == 3


# ---------------------------------------------------------------------------
# Validation: warn-and-return without mutation
# ---------------------------------------------------------------------------


class TestValidation:
    """All pre-flight failures must warn and leave the DB unmodified."""

    def test_missing_battery_for_beb_vehicle_type_warns(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        data = _full_fleet_dict()
        # Drop the entry for "GN" so a BEB VehicleType is uncovered.
        data["battery_types"] = [
            bt for bt in data["battery_types"] if bt["vehicle_name_short"] != "GN"
        ]
        path = _write_fleet_json(tmp_path, data)

        with pytest.warns(UserWarning, match="GN"):
            complete_fleet(scenario, path, delete_existing_data=False)

        assert (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .count()
            == 0
        )
        assert (
            db_session.query(ChargingPointType)
            .filter(ChargingPointType.scenario_id == SCENARIO_ID)
            .count()
            == 0
        )

    def test_cpt_topology_mismatch_warns(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        data = _full_fleet_dict()
        # Drop the opportunity entry — sample DB has CHARGING_OPPORTUNITY
        # events, so this set will not match.
        data["charging_point_types"] = [
            c for c in data["charging_point_types"] if c["type"] != "opportunity"
        ]
        path = _write_fleet_json(tmp_path, data)

        with pytest.warns(UserWarning, match="fully provide"):
            complete_fleet(scenario, path, delete_existing_data=False)

        assert (
            db_session.query(ChargingPointType)
            .filter(ChargingPointType.scenario_id == SCENARIO_ID)
            .count()
            == 0
        )

    def test_unknown_chemistry_warns(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        data = _full_fleet_dict()
        data["battery_types"][0]["chemistry"] = "LFP"  # uppercase → not in allow-list
        path = _write_fleet_json(tmp_path, data)

        with pytest.warns(UserWarning, match="chemistry"):
            complete_fleet(scenario, path, delete_existing_data=False)

        assert (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .count()
            == 0
        )

    def test_missing_specific_mass_warns(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        data = _full_fleet_dict()
        del data["battery_types"][0]["specific_mass"]
        path = _write_fleet_json(tmp_path, data)

        with pytest.warns(UserWarning, match="specific_mass"):
            complete_fleet(scenario, path, delete_existing_data=False)

        assert (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .count()
            == 0
        )

    def test_duplicate_cpt_type_warns(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        data = _full_fleet_dict()
        data["charging_point_types"].append(
            {"type": "depot", "name": "Second Depot CP", "name_short": "DCP2"}
        )
        path = _write_fleet_json(tmp_path, data)

        with pytest.warns(UserWarning, match="same 'type'"):
            complete_fleet(scenario, path, delete_existing_data=False)

        assert (
            db_session.query(ChargingPointType)
            .filter(ChargingPointType.scenario_id == SCENARIO_ID)
            .count()
            == 0
        )


# ---------------------------------------------------------------------------
# Existing-data handling
# ---------------------------------------------------------------------------


class TestExistingData:
    """Behavior around BatteryType / ChargingPointType rows already present."""

    def test_warns_and_returns_when_battery_exists_and_delete_false(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        # Pre-create a BatteryType.
        existing = BatteryType(
            scenario_id=SCENARIO_ID, specific_mass=1.0, chemistry="nmc"
        )
        db_session.add(existing)
        db_session.flush()
        existing_id = existing.id

        path = _write_fleet_json(tmp_path, _full_fleet_dict())

        with pytest.warns(UserWarning, match="Existing BatteryType"):
            complete_fleet(scenario, path, delete_existing_data=False)

        # Pre-existing row untouched, no new rows created.
        bts = (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .all()
        )
        assert len(bts) == 1
        assert bts[0].id == existing_id

    def test_replaces_existing_when_delete_true(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        # Pre-create a BatteryType and a ChargingPointType, assign each.
        old_bt = BatteryType(
            scenario_id=SCENARIO_ID, specific_mass=99.0, chemistry="nmc"
        )
        old_cpt = ChargingPointType(scenario_id=SCENARIO_ID, name="Old CP")
        db_session.add_all([old_bt, old_cpt])
        db_session.flush()
        old_bt_id = old_bt.id
        old_cpt_id = old_cpt.id

        # Wire up one VehicleType and one Area to the old rows.
        a_vt = (
            db_session.query(VehicleType)
            .filter(VehicleType.scenario_id == SCENARIO_ID)
            .first()
        )
        assert a_vt is not None
        a_vt.battery_type_id = old_bt.id

        a_charging_area = (
            db_session.query(Area)
            .filter(
                Area.scenario_id == SCENARIO_ID,
                Area.processes.any(Process.electric_power.isnot(None)),
            )
            .first()
        )
        assert a_charging_area is not None
        a_charging_area.charging_point_type_id = old_cpt.id
        db_session.flush()

        path = _write_fleet_json(tmp_path, _full_fleet_dict())

        complete_fleet(scenario, path, delete_existing_data=True)

        # Exactly 3 BatteryType + 2 ChargingPointType rows now exist for this scenario.
        bts = (
            db_session.query(BatteryType)
            .filter(BatteryType.scenario_id == SCENARIO_ID)
            .all()
        )
        cpts = (
            db_session.query(ChargingPointType)
            .filter(ChargingPointType.scenario_id == SCENARIO_ID)
            .all()
        )
        assert len(bts) == 3
        assert len(cpts) == 2
        # Old content is gone — old BT had chemistry "nmc"/specific_mass=99,
        # old CPT had name "Old CP". The new rows do not carry those values.
        assert all(bt.chemistry == "lfp" for bt in bts)
        assert all(bt.specific_mass == 6.0 for bt in bts)
        assert "Old CP" not in {cpt.name for cpt in cpts}

        # FKs now point at the new rows (specifically, rows in the new id sets).
        db_session.refresh(a_vt)
        db_session.refresh(a_charging_area)
        new_bt_ids = {bt.id for bt in bts}
        new_cpt_ids = {cpt.id for cpt in cpts}
        assert a_vt.battery_type_id in new_bt_ids
        assert a_charging_area.charging_point_type_id in new_cpt_ids


# ---------------------------------------------------------------------------
# Scenario resolution
# ---------------------------------------------------------------------------


class TestScenarioResolution:
    """Inline session resolution honors the polymorphic scenario param."""

    def test_invalid_scenario_type_raises(self, tmp_path: Path) -> None:
        path = _write_fleet_json(tmp_path, _full_fleet_dict())
        with pytest.raises(ValueError, match="Scenario object"):
            complete_fleet("not-a-scenario", path, delete_existing_data=False)

    def test_int_without_database_url_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        path = _write_fleet_json(tmp_path, _full_fleet_dict())
        with pytest.raises(ValueError, match="No database URL"):
            complete_fleet(SCENARIO_ID, path, delete_existing_data=False)

    def test_unbound_scenario_raises(
        self, db_session: Session, scenario: Scenario, tmp_path: Path
    ) -> None:
        # Detach from session.
        db_session.expunge(scenario)
        path = _write_fleet_json(tmp_path, _full_fleet_dict())
        with pytest.raises(ValueError, match="not bound"):
            complete_fleet(scenario, path, delete_existing_data=False)
