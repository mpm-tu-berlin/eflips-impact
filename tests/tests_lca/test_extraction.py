"""Tests for eflips.impact.utils.extraction (SimData containers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from eflips.impact.utils.extraction import (
    ScenarioSimData,
    _annual_scaling_factor,
    _default_scaling_factor,
    extract_simulation_data,
)

SCENARIO_ID = 1
SIM_START = datetime(2025, 6, 17, 0, 0, 0, tzinfo=timezone.utc)
SIM_END = datetime(2025, 6, 19, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# _annual_scaling_factor
# ---------------------------------------------------------------------------


def test_scaling_one_day() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    assert _annual_scaling_factor((start, end)) == pytest.approx(365.0)


def test_scaling_one_year() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _annual_scaling_factor((start, end)) == pytest.approx(
        365.0 / 365.0, rel=1e-3
    )


def test_scaling_two_days() -> None:
    start = datetime(2025, 6, 17, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    assert _annual_scaling_factor((start, end)) == pytest.approx(365.0 / 2.0)


def test_scaling_zero_duration_raises() -> None:
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        _annual_scaling_factor((t, t))


def test_scaling_negative_duration_raises() -> None:
    start = datetime(2025, 1, 2, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        _annual_scaling_factor((start, end))


# ---------------------------------------------------------------------------
# _default_scaling_factor
# ---------------------------------------------------------------------------


def test_default_scaling_factor_positive(db_session: Session) -> None:
    sf = _default_scaling_factor(db_session, SCENARIO_ID)
    assert sf > 0.0


def test_default_scaling_factor_invalid_scenario_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="no trips"):
        _default_scaling_factor(db_session, 999)


# ---------------------------------------------------------------------------
# extract_simulation_data – vehicle-type level
# ---------------------------------------------------------------------------


def test_vehicle_types_present(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    # vtype 12 and 13 have rotations; vtype 14 does not
    assert 12 in data.vehicle_type_data
    assert 13 in data.vehicle_type_data


def test_revenue_km_less_than_vehicle_km(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    for vt in data.vehicle_type_data.values():
        assert vt.annual_vehicle_kilometers > 0
        assert vt.annual_revenue_kilometers > 0
        # Empty/deadhead trips make vehicle-km ≥ revenue-km
        assert vt.annual_vehicle_kilometers >= vt.annual_revenue_kilometers


def test_n_ready_positive(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    for vt in data.vehicle_type_data.values():
        assert vt.n_ready > 0


def test_scaling_halves_km(db_session: Session) -> None:
    """A scaling_factor of 365 should give ~2x the annual km of a factor of 365/2."""
    sf_1d = _annual_scaling_factor((SIM_START, SIM_START + timedelta(days=1)))
    sf_2d = _annual_scaling_factor((SIM_START, SIM_END))
    data_1d = extract_simulation_data(
        db_session,
        SCENARIO_ID,
        (SIM_START, SIM_END),
        sf_1d,
    )
    data_2d = extract_simulation_data(
        db_session,
        SCENARIO_ID,
        (SIM_START, SIM_END),
        sf_2d,
    )
    for vid in [12, 13]:
        km_1d = data_1d.vehicle_type_data[vid].annual_vehicle_kilometers
        km_2d = data_2d.vehicle_type_data[vid].annual_vehicle_kilometers
        # 1-day factor (365) → 2x the km of 2-day factor (365/2)
        assert km_1d == pytest.approx(km_2d * 2.0, rel=1e-6)


# ---------------------------------------------------------------------------
# extract_simulation_data – area and station peaks
# ---------------------------------------------------------------------------


def test_area_peaks_present(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    assert len(data.area_data) > 0
    for area_sim in data.area_data.values():
        assert area_sim.peak_charging_power_kw >= 0.0
        assert area_sim.peak_simultaneous_vehicles >= 0


def test_beb_area_ids_extracted(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    # Areas 5, 6, 11, 12, 17 are the BEB depot areas in the sample scenario
    expected_beb_areas = {5, 6, 11, 12, 17}
    assert expected_beb_areas.issubset(data.area_data.keys())


def test_area_peak_power_positive(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    total_peak = sum(a.peak_charging_power_kw for a in data.area_data.values())
    assert total_peak > 0.0


def test_station_peaks_present(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    assert len(data.station_data) > 0
    for st_sim in data.station_data.values():
        assert st_sim.peak_charging_power_kw >= 0.0


def test_terminal_station_ids_extracted(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID))
    expected = {3104, 62202, 79221, 195014, 260005, 1102005109}
    assert expected.issubset(data.station_data.keys())


def test_eta_avail_stored(db_session: Session) -> None:
    window = (SIM_START, SIM_END)
    data = extract_simulation_data(
        db_session, SCENARIO_ID, window, _default_scaling_factor(db_session, SCENARIO_ID), eta_avail=0.85
    )
    assert data.eta_avail == pytest.approx(0.85)
