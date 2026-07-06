"""Tests for per-station charging-infrastructure TCO parameters.

``init_tco_params`` resolves the ``charging_infrastructure`` section into a single
parameter set per affected :class:`~eflips.model.Station` before writing:

* a *default* entry (no ``station_ids``) applies to every station of its ``type``;
* an *override* entry (``station_ids`` given) applies only to the listed stations
  and wins over the default;
* the outcome is independent of the order of entries in the JSON.

Station ids are read from the sample database at run time rather than hard-coded,
so the tests stay valid if the fixture data changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from eflips.model import Depot, Event, EventType, Scenario, Station

from eflips.impact.tco import init_tco_params
from tests.tests_tco.conftest import SCENARIO_ID, SCENARIO_TCO_PARAMS

# An id guaranteed not to match any Station in the scenario.
NONEXISTENT_STATION_ID = 999_999_999


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _depot_station_ids(session: Session) -> list[int]:
    return sorted(
        sid
        for (sid,) in session.query(Depot.station_id)
        .filter(Depot.scenario_id == SCENARIO_ID)
        .all()
    )


def _opportunity_station_ids(session: Session) -> list[int]:
    return sorted(
        sid
        for (sid,) in session.query(distinct(Event.station_id))
        .filter(
            Event.scenario_id == SCENARIO_ID,
            Event.event_type == EventType.CHARGING_OPPORTUNITY,
        )
        .all()
        if sid is not None
    )


def _station_id_outside_both_types(session: Session) -> int:
    """A real Station that is neither a depot nor an opportunity-charging station."""
    excluded = set(_depot_station_ids(session)) | set(_opportunity_station_ids(session))
    sid = (
        session.query(Station.id)
        .filter(Station.scenario_id == SCENARIO_ID, Station.id.notin_(excluded))
        .first()
    )
    assert sid is not None, "sample DB has no station outside both infra types"
    return sid[0]


def _params(session: Session, sid: int) -> dict | None:
    return session.query(Station).filter(Station.id == sid).one().tco_parameters


def _cost(session: Session, sid: int) -> float:
    params = _params(session, sid)
    assert params is not None
    return params["procurement_cost"]


def _entry(
    cost: float,
    infra_type: str = "depot",
    station_ids: list[int] | None = None,
) -> dict:
    d = {
        "type": infra_type,
        "procurement_cost": cost,
        "useful_life": 20,
        "cost_escalation": 0.0,
    }
    if station_ids is not None:
        d["station_ids"] = station_ids
    return d


def _run(
    session: Session, scenario: Scenario, tmp_path: Path, entries: list[dict]
) -> None:
    params_path = tmp_path / "params.json"
    params_path.write_text(
        json.dumps(
            {"scenario": SCENARIO_TCO_PARAMS, "charging_infrastructure": entries}
        ),
        encoding="utf-8",
    )
    init_tco_params(scenario, params_path)
    session.flush()


# ---------------------------------------------------------------------------
# Default + override resolution
# ---------------------------------------------------------------------------


def test_default_plus_override_fills_the_rest(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """Override wins on its stations; the default covers every other station."""
    ids = _depot_station_ids(fleet_session)
    assert len(ids) >= 2
    target = ids[0]
    _run(
        fleet_session,
        scenario,
        tmp_path,
        [_entry(111.0, station_ids=[target]), _entry(222.0)],
    )
    assert _cost(fleet_session, target) == pytest.approx(111.0)
    for sid in ids[1:]:
        assert _cost(fleet_session, sid) == pytest.approx(222.0)


def test_order_independent(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """Listing the default before the override gives the same result."""
    ids = _depot_station_ids(fleet_session)
    target = ids[0]
    _run(
        fleet_session,
        scenario,
        tmp_path,
        [_entry(222.0), _entry(111.0, station_ids=[target])],
    )
    assert _cost(fleet_session, target) == pytest.approx(111.0)
    for sid in ids[1:]:
        assert _cost(fleet_session, sid) == pytest.approx(222.0)


def test_override_only_leaves_others_untouched(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """With no default entry, only the listed stations receive parameters."""
    ids = _depot_station_ids(fleet_session)
    assert len(ids) >= 2
    target, others = ids[0], ids[1:]
    before = {
        sid: (dict(p) if (p := _params(fleet_session, sid)) is not None else None)
        for sid in others
    }
    _run(fleet_session, scenario, tmp_path, [_entry(111.0, station_ids=[target])])
    assert _cost(fleet_session, target) == pytest.approx(111.0)
    # Stations not named by any entry keep whatever parameters they already had.
    for sid in others:
        assert _params(fleet_session, sid) == before[sid]


def test_multiple_overrides_target_disjoint_stations(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """Several override entries each write only to their own station ids."""
    ids = _depot_station_ids(fleet_session)
    assert len(ids) >= 3
    a, b, rest = ids[0], ids[1], ids[2:]
    _run(
        fleet_session,
        scenario,
        tmp_path,
        [
            _entry(333.0),
            _entry(111.0, station_ids=[a]),
            _entry(222.0, station_ids=[b]),
        ],
    )
    assert _cost(fleet_session, a) == pytest.approx(111.0)
    assert _cost(fleet_session, b) == pytest.approx(222.0)
    for sid in rest:
        assert _cost(fleet_session, sid) == pytest.approx(333.0)


def test_override_targets_opportunity_station(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """``station``-type overrides resolve against opportunity-charging stations."""
    ids = _opportunity_station_ids(fleet_session)
    assert len(ids) >= 2
    target = ids[0]
    _run(
        fleet_session,
        scenario,
        tmp_path,
        [
            _entry(500.0, infra_type="station"),
            _entry(999.0, infra_type="station", station_ids=[target]),
        ],
    )
    assert _cost(fleet_session, target) == pytest.approx(999.0)
    for sid in ids[1:]:
        assert _cost(fleet_session, sid) == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Error / warning paths
# ---------------------------------------------------------------------------


def test_two_defaults_same_type_raises(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """At most one default (no ``station_ids``) per type is allowed."""
    with pytest.raises(ValueError, match="Multiple default"):
        _run(fleet_session, scenario, tmp_path, [_entry(1.0), _entry(2.0)])


def test_override_id_outside_type_scope_warns_but_writes(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """A real station that is not of the entry's type is written, with a warning."""
    outsider = _station_id_outside_both_types(fleet_session)
    with pytest.warns(UserWarning, match="is not a 'depot'"):
        _run(
            fleet_session,
            scenario,
            tmp_path,
            [_entry(222.0), _entry(111.0, station_ids=[outsider])],
        )
    assert _cost(fleet_session, outsider) == pytest.approx(111.0)
    for sid in _depot_station_ids(fleet_session):
        assert _cost(fleet_session, sid) == pytest.approx(222.0)


def test_override_id_not_in_scenario_is_skipped_with_warning(
    fleet_session: Session, scenario: Scenario, tmp_path: Path
) -> None:
    """An id matching no Station is skipped; real stations are still written."""
    ids = _depot_station_ids(fleet_session)
    with pytest.warns(UserWarning, match="not found"):
        _run(
            fleet_session,
            scenario,
            tmp_path,
            [_entry(222.0), _entry(111.0, station_ids=[NONEXISTENT_STATION_ID])],
        )
    # The default still applies to every real depot station.
    for sid in ids:
        assert _cost(fleet_session, sid) == pytest.approx(222.0)
