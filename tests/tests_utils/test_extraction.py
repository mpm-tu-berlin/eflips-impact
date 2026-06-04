"""Tests for eflips.impact.utils.extraction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from eflips.impact.utils.extraction import (
    _annual_scaling_factor,
    _default_scaling_factor,
    extract_vehicle_and_revenue_kilometers,
    extract_vehicle_count_per_type,
    get_extraction_window,
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
# _default_scaling_factor
# ---------------------------------------------------------------------------


def test_default_scaling_factor_positive(db_session: Session) -> None:
    sf = _default_scaling_factor(db_session, SCENARIO_ID)
    assert sf > 0.0


def test_default_scaling_factor_invalid_scenario_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="no trips"):
        _default_scaling_factor(db_session, 999)


# ---------------------------------------------------------------------------
# extract_vehicle_and_revenue_kilometers
# ---------------------------------------------------------------------------


def test_vkm_keys_are_vehicle_type_ids(db_session: Session) -> None:
    window = get_extraction_window(db_session, SCENARIO_ID)
    result = extract_vehicle_and_revenue_kilometers(
        db_session,
        SCENARIO_ID,
        window,
        _default_scaling_factor(db_session, SCENARIO_ID),
    )
    assert len(result) > 0
    for vtype_id, (vkm, rkm) in result.items():
        assert isinstance(vtype_id, int)
        assert vkm >= rkm >= 0.0


def test_vkm_revenue_le_vehicle(db_session: Session) -> None:
    window = get_extraction_window(db_session, SCENARIO_ID)
    result = extract_vehicle_and_revenue_kilometers(
        db_session,
        SCENARIO_ID,
        window,
        _default_scaling_factor(db_session, SCENARIO_ID),
    )
    for vkm, rkm in result.values():
        assert vkm >= rkm


def test_vkm_scaling_proportional(db_session: Session) -> None:
    """A half-length scaling factor should double the km values vs. the full factor."""
    start, end = get_extraction_window(db_session, SCENARIO_ID)
    mid = start + (end - start) / 2
    full_window = (start, end)
    sf_full = _annual_scaling_factor(full_window)
    sf_half = _annual_scaling_factor((start, mid))
    result_full = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, full_window, sf_full
    )
    result_half_scale = extract_vehicle_and_revenue_kilometers(
        db_session, SCENARIO_ID, full_window, sf_half
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
    window = get_extraction_window(db_session, SCENARIO_ID)
    result = extract_vehicle_count_per_type(db_session, SCENARIO_ID, window)
    assert len(result) > 0
    for count in result.values():
        assert count > 0


def test_vehicle_count_keys_match_km_keys(db_session: Session) -> None:
    window = get_extraction_window(db_session, SCENARIO_ID)
    km_result = extract_vehicle_and_revenue_kilometers(
        db_session,
        SCENARIO_ID,
        window,
        _default_scaling_factor(db_session, SCENARIO_ID),
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


def test_extraction_window_start_is_min_event_time(db_session: Session) -> None:
    start, _ = get_extraction_window(db_session, SCENARIO_ID)
    from eflips.model import Event
    from sqlalchemy import func, select

    min_ts = db_session.execute(
        select(func.min(Event.time_start)).where(Event.scenario_id == SCENARIO_ID)
    ).scalar()
    assert start == min_ts


def test_extraction_window_end_is_max_event_time(db_session: Session) -> None:
    _, end = get_extraction_window(db_session, SCENARIO_ID)
    from eflips.model import Event
    from sqlalchemy import func, select

    max_te = db_session.execute(
        select(func.max(Event.time_end)).where(Event.scenario_id == SCENARIO_ID)
    ).scalar()
    assert end == max_te


def test_extraction_window_no_events_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="contains no events"):
        get_extraction_window(db_session, 999)
