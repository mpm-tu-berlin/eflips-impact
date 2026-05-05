"""Tests for eflips.impact.utils.extraction."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from eflips.impact.utils.extraction import (
    _annual_scaling_factor,
    _simulation_start_and_end,
    extract_vehicle_and_revenue_kilometers,
    extract_vehicle_count_per_type,
    get_extraction_window,
    get_scaling_window,
)

SCENARIO_ID = 1

# ---------------------------------------------------------------------------
# _annual_scaling_factor
# ---------------------------------------------------------------------------


def test_scaling_one_day() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    assert _annual_scaling_factor((start, end)) == pytest.approx(365.0)


def test_scaling_two_days() -> None:
    start = datetime(2025, 6, 17, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    assert _annual_scaling_factor((start, end)) == pytest.approx(365.0 / 2.0)


def test_scaling_one_year() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _annual_scaling_factor((start, end)) == pytest.approx(1.0, rel=1e-3)


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
# _simulation_start_and_end
# ---------------------------------------------------------------------------


def test_sim_bounds_start_at_midnight(db_session: Session) -> None:
    start, _ = _simulation_start_and_end(db_session, SCENARIO_ID)
    assert start.time() == time(0, 0, 0)


def test_sim_bounds_end_at_end_of_day(db_session: Session) -> None:
    _, end = _simulation_start_and_end(db_session, SCENARIO_ID)
    assert end.time() == time(23, 59, 59)


def test_sim_bounds_start_before_end(db_session: Session) -> None:
    start, end = _simulation_start_and_end(db_session, SCENARIO_ID)
    assert start < end


def test_sim_bounds_same_timezone(db_session: Session) -> None:
    start, end = _simulation_start_and_end(db_session, SCENARIO_ID)
    assert start.tzinfo == end.tzinfo


def test_sim_bounds_no_trips_raises(db_session: Session) -> None:
    # Scenario 999 does not exist → no trips → ValueError
    with pytest.raises(ValueError, match="contains no trips"):
        _simulation_start_and_end(db_session, 999)


# ---------------------------------------------------------------------------
# extract_vehicle_and_revenue_kilometers
# ---------------------------------------------------------------------------


def test_vkm_keys_are_vehicle_type_ids(db_session: Session) -> None:
    window = _simulation_start_and_end(db_session, SCENARIO_ID)
    result = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, window, window
    )
    assert len(result) > 0
    for vtype_id, (vkm, rkm) in result.items():
        assert isinstance(vtype_id, int)
        assert vkm >= rkm >= 0.0


def test_vkm_revenue_le_vehicle(db_session: Session) -> None:
    window = _simulation_start_and_end(db_session, SCENARIO_ID)
    result = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, window, window
    )
    for vkm, rkm in result.values():
        assert vkm >= rkm


def test_vkm_scaling_proportional(db_session: Session) -> None:
    """A half-length scaling window should double the km values vs. the full window."""
    start, end = _simulation_start_and_end(db_session, SCENARIO_ID)
    from datetime import timedelta

    mid = start + (end - start) / 2
    half_window = (start, mid)
    full_window = (start, end)
    result_full = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, full_window, full_window
    )
    result_half_scale = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, full_window, half_window
    )
    for vid in result_full:
        vkm_full, rkm_full = result_full[vid]
        vkm_half, rkm_half = result_half_scale[vid]
        assert vkm_half == pytest.approx(vkm_full * 2, rel=1e-6)
        assert rkm_half == pytest.approx(rkm_full * 2, rel=1e-6)


# ---------------------------------------------------------------------------
# extract_vehicle_count_per_type
# ---------------------------------------------------------------------------


def test_vehicle_count_positive(db_session: Session) -> None:
    window = _simulation_start_and_end(db_session, SCENARIO_ID)
    result = extract_vehicle_count_per_type(db_session, SCENARIO_ID, window)
    assert len(result) > 0
    for count in result.values():
        assert count > 0


def test_vehicle_count_keys_match_km_keys(db_session: Session) -> None:
    window = _simulation_start_and_end(db_session, SCENARIO_ID)
    km_result = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, window, window
    )
    count_result = extract_vehicle_count_per_type(db_session, SCENARIO_ID, window)
    # Every type with trips should also have vehicles
    assert set(km_result.keys()) == set(count_result.keys())


# ---------------------------------------------------------------------------
# get_extraction_window
# ---------------------------------------------------------------------------


def test_extraction_window_start_before_end(db_session: Session) -> None:
    start, end = get_extraction_window(db_session, SCENARIO_ID)
    assert start < end


def test_extraction_window_start_is_min_departure(db_session: Session) -> None:
    start, _ = get_extraction_window(db_session, SCENARIO_ID)
    # start must equal min(departure_time): no trip departs before it
    from eflips.model import Trip
    from sqlalchemy import func, select

    min_dep = db_session.execute(
        select(func.min(Trip.departure_time)).where(Trip.scenario_id == SCENARIO_ID)
    ).scalar()
    assert start == min_dep


def test_extraction_window_end_is_max_arrival(db_session: Session) -> None:
    _, end = get_extraction_window(db_session, SCENARIO_ID)
    from eflips.model import Trip
    from sqlalchemy import func, select

    max_arr = db_session.execute(
        select(func.max(Trip.arrival_time)).where(Trip.scenario_id == SCENARIO_ID)
    ).scalar()
    assert end == max_arr


def test_extraction_window_no_trips_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="contains no trips"):
        get_extraction_window(db_session, 999)


# ---------------------------------------------------------------------------
# get_scaling_window
# ---------------------------------------------------------------------------


def test_scaling_window_start_before_end(db_session: Session) -> None:
    start, end = get_scaling_window(db_session, SCENARIO_ID)
    assert start < end


def test_scaling_window_both_are_departure_times(db_session: Session) -> None:
    start, end = get_scaling_window(db_session, SCENARIO_ID)
    from eflips.model import Trip
    from sqlalchemy import func, select

    min_dep, max_dep = db_session.execute(
        select(func.min(Trip.departure_time), func.max(Trip.departure_time)).where(
            Trip.scenario_id == SCENARIO_ID
        )
    ).one()
    assert start == min_dep
    assert end == max_dep


def test_scaling_window_end_le_extraction_window_end(db_session: Session) -> None:
    _, ext_end = get_extraction_window(db_session, SCENARIO_ID)
    _, sc_end = get_scaling_window(db_session, SCENARIO_ID)
    # Last departure cannot be later than last arrival
    assert sc_end <= ext_end


def test_scaling_window_no_trips_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="contains no trips"):
        get_scaling_window(db_session, 999)
