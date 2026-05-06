"""Read-only simulation queries and aggregated data containers shared by ``tco/`` and ``lca/``.

All functions in this module are pure database reads and never mutate any
row.  Low-level query bricks and the shared aggregation containers
(:class:`VehicleTypeSimData`, :class:`ScenarioSimData`) live here;
domain-specific cost and impact assembly stays in ``tco/`` and ``lca/``.

Import direction: this module imports only from ``eflips.model``,
``eflips.eval``, ``sqlalchemy``, and stdlib.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

import sqlalchemy
from eflips.eval.output.prepare import power_and_occupancy
from eflips.model import (
    Area,
    Depot,
    EnergySource,
    Event,
    Rotation,
    Route,
    Station,
    Trip,
    TripType,
    VehicleType,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AreaSimData:
    """Extracted simulation data for one depot charging area.

    Attributes:
        area_id: The ``Area`` primary key.
        peak_charging_power_kw: Maximum simultaneous charging power in kW.
        peak_simultaneous_vehicles: Maximum number of vehicles present at
            the same time (``occupancy_total``).
    """

    area_id: int
    peak_charging_power_kw: float
    peak_simultaneous_vehicles: int


@dataclass
class StationSimData:
    """Extracted simulation data for one terminal charging station.

    Attributes:
        station_id: The ``Station`` primary key.
        peak_charging_power_kw: Maximum simultaneous charging power in kW.
        peak_simultaneous_vehicles: Maximum number of vehicles present at
            the same time (``occupancy_total``).
    """

    station_id: int
    peak_charging_power_kw: float
    peak_simultaneous_vehicles: int


# ---------------------------------------------------------------------------
# Annual-scaling helpers
# ---------------------------------------------------------------------------


def _simulation_start_and_end(
    session: Session,
    scenario_id: int,
) -> tuple[datetime, datetime]:
    """Determine the full-day simulation window from Trip data.

    Queries ``min(Trip.departure_time)`` and ``max(Trip.arrival_time)`` for
    the scenario, then trims to whole calendar days to avoid partial-day
    bias in annualisation:

    - *start_time*: ``00:00:00`` of the first calendar day whose midnight
      start is at or after the earliest departure time.
    - *end_time*: ``23:59:59`` of the last calendar day that is fully
      enclosed within the simulation period, i.e. the day before the
      calendar date of ``max(Trip.arrival_time)``.

    The formula for the last full day D is ``overall_end.date() - 1 day``,
    which holds in all cases:

    - ``overall_end = Jan 21 00:00`` → D = Jan 20 ✓
    - ``overall_end = Jan 20 22:00`` → D = Jan 19 ✓  (Jan 20 not fully covered)

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.

    Returns:
        Pair ``(start_time, end_time)`` with ``start_time < end_time``.

    Raises:
        ValueError: If the scenario contains no trips, or if the trip span
            covers fewer than two calendar days (no full day enclosed).
    """
    row = session.execute(
        select(func.min(Trip.departure_time), func.max(Trip.arrival_time)).where(
            Trip.scenario_id == scenario_id
        )
    ).one()

    overall_start: Optional[datetime] = row[0]
    overall_end: Optional[datetime] = row[1]

    if overall_start is None or overall_end is None:
        raise ValueError(f"Scenario {scenario_id} contains no trips.")

    tz = overall_start.tzinfo

    first_day: date = overall_start.date()
    if overall_start != datetime.combine(first_day, time(0, 0, 0), tzinfo=tz):
        first_day = first_day + timedelta(days=1)

    last_day: date = overall_end.date() - timedelta(days=1)

    start_dt = datetime.combine(first_day, time(0, 0, 0), tzinfo=tz)
    end_dt = datetime.combine(last_day, time(23, 59, 59), tzinfo=tz)

    if end_dt <= start_dt:
        raise ValueError(
            f"Simulation window for scenario {scenario_id} contains no full calendar "
            f"days (overall_start={overall_start}, overall_end={overall_end})."
        )

    return start_dt, end_dt


def _annual_scaling_factor(scaling_window: tuple[datetime, datetime]) -> float:
    """Compute the factor to scale simulation-period values to annual.

    Args:
        scaling_window: ``(start, end)`` pair defining the reference period
            for annualisation.

    Returns:
        ``365.0 / window_duration_days``.

    Raises:
        ValueError: If the window duration is non-positive.
    """
    sim_start_time, sim_end_time = scaling_window
    duration = sim_end_time - sim_start_time
    duration_days = duration.total_seconds() / 86_400.0
    if duration_days <= 0:
        raise ValueError(
            f"scaling_window end must be after start, got duration {duration}"
        )
    return 365.0 / duration_days


# ---------------------------------------------------------------------------
# Per-vehicle-type queries
# ---------------------------------------------------------------------------


def extract_vehicle_and_revenue_kilometers(
    session: Session,
    scenario_id: int,
    extraction_window: tuple[datetime, datetime],
    scaling_window: tuple[datetime, datetime],
) -> dict[int, tuple[float, float]]:
    """Query annual vehicle-km and revenue-km per vehicle type.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        extraction_window: ``(start, end)`` pair used to filter trips included
            in the calculation.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor via :func:`_annual_scaling_factor`.

    Returns:
        Dict mapping ``VehicleType.id`` to
        ``(annual_vehicle_km, annual_revenue_km)``.
    """
    sim_start_time, sim_end_time = extraction_window
    scaling = _annual_scaling_factor(scaling_window)
    stmt = (
        select(
            Rotation.vehicle_type_id,
            Trip.trip_type,
            func.sum(Route.distance).label("total_distance_m"),
        )
        .join(Rotation, Trip.rotation_id == Rotation.id)
        .join(Route, Trip.route_id == Route.id)
        .where(Rotation.scenario_id == scenario_id)
        .where(Trip.departure_time >= sim_start_time)
        .where(Trip.arrival_time <= sim_end_time)
        .group_by(Rotation.vehicle_type_id, Trip.trip_type)
    )

    rows = session.execute(stmt).all()

    vkm: dict[int, float] = {}
    rkm: dict[int, float] = {}
    for vtype_id, trip_type, total_m in rows:
        km = (total_m / 1000.0) * scaling
        vkm[vtype_id] = vkm.get(vtype_id, 0.0) + km
        if trip_type == TripType.PASSENGER:
            rkm[vtype_id] = rkm.get(vtype_id, 0.0) + km

    all_ids = set(vkm) | set(rkm)
    return {vid: (vkm.get(vid, 0.0), rkm.get(vid, 0.0)) for vid in all_ids}


def extract_vehicle_count_per_type(
    session: Session,
    scenario_id: int,
    extraction_window: tuple[datetime, datetime],
) -> dict[int, int]:
    """Count distinct vehicles operated per vehicle type within a time window.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        extraction_window: ``(start, end)`` pair used to filter trips.

    Returns:
        Dict mapping ``VehicleType.id`` to the count of distinct vehicles
        that operated at least one trip within the window.
    """
    sim_start_time, sim_end_time = extraction_window
    stmt = (
        select(
            Rotation.vehicle_type_id,
            func.count(sqlalchemy.distinct(Rotation.vehicle_id)).label("n"),
        )
        .join(Trip, Trip.rotation_id == Rotation.id)
        .where(Rotation.scenario_id == scenario_id)
        .where(Trip.departure_time >= sim_start_time)
        .where(Trip.arrival_time <= sim_end_time)
        .where(Rotation.vehicle_id.isnot(None))
        .group_by(Rotation.vehicle_type_id)
    )
    rows = session.execute(stmt).all()
    return {vtype_id: int(n) for vtype_id, n in rows}


# ---------------------------------------------------------------------------
# Peak charging queries
# ---------------------------------------------------------------------------


def extract_area_peaks(
    session: Session,
    scenario_id: int,
    extraction_window: tuple[datetime, datetime],
) -> dict[int, AreaSimData]:
    """Extract peak charging power and vehicle occupancy for BEV depot areas.

    Only includes areas whose associated ``VehicleType`` has
    ``energy_source == BATTERY_ELECTRIC``.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        extraction_window: ``(start, end)`` pair used to filter events.

    Returns:
        Dict mapping ``Area.id`` to :class:`AreaSimData`.
    """
    sim_start_time, sim_end_time = extraction_window
    areas = (
        session.query(Area)
        .join(Depot, Area.depot_id == Depot.id)
        .join(VehicleType, Area.vehicle_type_id == VehicleType.id)
        .filter(Area.scenario_id == scenario_id)
        .filter(VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC)
        .all()
    )

    result: dict[int, AreaSimData] = {}
    for area in areas:
        try:
            df = power_and_occupancy(
                area_id=area.id,
                session=session,
                sim_start_time=sim_start_time,
                sim_end_time=sim_end_time,
            )
        except ValueError:
            logger.warning("No events found for area %d, skipping.", area.id)
            continue

        peak_power = float(df["power"].max()) if not df.empty else 0.0
        peak_vehicles = int(df["occupancy_total"].max()) if not df.empty else 0
        result[area.id] = AreaSimData(
            area_id=area.id,
            peak_charging_power_kw=peak_power,
            peak_simultaneous_vehicles=peak_vehicles,
        )
    return result


def extract_station_peaks(
    session: Session,
    scenario_id: int,
    extraction_window: tuple[datetime, datetime],
) -> dict[int, StationSimData]:
    """Extract peak charging power and vehicle occupancy for terminal stations.

    Only processes electrified stations that are **not** associated with a
    depot (i.e. ``Depot.station_id`` does not reference this station).

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        extraction_window: ``(start, end)`` pair used to filter events.

    Returns:
        Dict mapping ``Station.id`` to :class:`StationSimData`.
    """
    sim_start_time, sim_end_time = extraction_window
    stations = (
        session.query(Station)
        .outerjoin(Depot, Depot.station_id == Station.id)
        .filter(Station.scenario_id == scenario_id)
        .filter(Station.is_electrified.is_(True))
        .filter(Depot.id.is_(None))
        .all()
    )

    result: dict[int, StationSimData] = {}
    for station in stations:
        try:
            df = power_and_occupancy(
                area_id=[],
                station_id=station.id,
                session=session,
                sim_start_time=sim_start_time,
                sim_end_time=sim_end_time,
            )
        except ValueError:
            logger.warning("No events found for station %d, skipping.", station.id)
            continue

        peak_power = float(df["power"].max()) if not df.empty else 0.0
        peak_vehicles = int(df["occupancy_total"].max()) if not df.empty else 0
        result[station.id] = StationSimData(
            station_id=station.id,
            peak_charging_power_kw=peak_power,
            peak_simultaneous_vehicles=peak_vehicles,
        )
    return result


# ---------------------------------------------------------------------------
# Public window constructors
# ---------------------------------------------------------------------------


def get_extraction_window(
    session: Session,
    scenario_id: int,
) -> tuple[datetime, datetime]:
    """Return the extraction window for a scenario.

    Queries ``min(Event.time_start)`` and ``max(Event.time_end)`` across
    all events in the scenario.  This spans the full simulation including
    depot charging and standby periods beyond the first/last trip times.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.

    Returns:
        ``(min_time_start, max_time_end)`` across all events.

    Raises:
        ValueError: If the scenario contains no events.
    """
    row = session.execute(
        select(func.min(Event.time_start), func.max(Event.time_end)).where(
            Event.scenario_id == scenario_id
        )
    ).one()

    earliest: Optional[datetime] = row[0]
    latest: Optional[datetime] = row[1]

    if earliest is None or latest is None:
        raise ValueError(f"Scenario {scenario_id} contains no events.")

    return earliest, latest


def get_scaling_window(
    session: Session,
    scenario_id: int,
) -> tuple[datetime, datetime]:
    """Return the scaling window for a scenario.

    Queries ``min(Trip.departure_time)`` and ``max(Trip.departure_time)`` for
    the scenario.  Using departure times for both bounds anchors the reference
    period to scheduled service, excluding any deadhead or idle time after the
    last trip departs.  The result is suitable to pass as ``scaling_window``
    to :func:`extract_vehicle_and_revenue_kilometers` and related functions.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.

    Returns:
        ``(min_departure_time, max_departure_time)``.

    Raises:
        ValueError: If the scenario contains no trips, or if all trips share
            the same departure time (degenerate window).
    """
    row = session.execute(
        select(func.min(Trip.departure_time), func.max(Trip.departure_time)).where(
            Trip.scenario_id == scenario_id
        )
    ).one()

    earliest: Optional[datetime] = row[0]
    latest: Optional[datetime] = row[1]

    if earliest is None or latest is None:
        raise ValueError(f"Scenario {scenario_id} contains no trips.")

    if earliest == latest:
        raise ValueError(
            f"Scenario {scenario_id} has only one unique departure time; "
            "cannot form a non-degenerate scaling window."
        )

    return earliest, latest


# ---------------------------------------------------------------------------
# Aggregated simulation data containers
# ---------------------------------------------------------------------------


@dataclass
class VehicleTypeSimData:
    """Extracted simulation data for one vehicle type.

    Attributes:
        vehicle_type_id: The ``VehicleType`` primary key.
        annual_vehicle_kilometers: Total vehicle-km (all trips), annualised.
        annual_revenue_kilometers: Total revenue vehicle-km (passenger trips
            only), annualised.
        n_ready: Number of operationally ready vehicles (distinct vehicles
            used in rotations within the simulation window).
    """

    vehicle_type_id: int
    annual_vehicle_kilometers: float
    annual_revenue_kilometers: float
    n_ready: int


@dataclass
class ScenarioSimData:
    """All extracted simulation data for a scenario.

    Attributes:
        vehicle_type_data: Per-vehicle-type data, keyed by
            ``VehicleType.id``.
        area_data: Per-depot-area data, keyed by ``Area.id``.
        station_data: Per-terminal-station data, keyed by ``Station.id``.
        eta_avail: Technical availability factor.
    """

    vehicle_type_data: dict[int, VehicleTypeSimData] = field(default_factory=dict)
    area_data: dict[int, AreaSimData] = field(default_factory=dict)
    station_data: dict[int, StationSimData] = field(default_factory=dict)
    eta_avail: float = 0.9


def extract_simulation_data(
    session: Session,
    scenario_id: int,
    extraction_window: tuple[datetime, datetime],
    scaling_window: tuple[datetime, datetime],
    eta_avail: float = 0.9,
) -> ScenarioSimData:
    """Extract all simulation outputs needed for LCA and TCO calculations.

    Queries the eflips-model database for vehicle/revenue kilometres,
    fleet size, and peak charging infrastructure utilisation.

    Args:
        session: SQLAlchemy session connected to an eflips-model database.
        scenario_id: ID of the scenario to analyse.
        extraction_window: ``(start, end)`` pair used to filter which trips
            and events are included in the query.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor.
        eta_avail: Technical availability factor (default ``0.9``).

    Returns:
        A :class:`ScenarioSimData` containing all extracted values.

    Raises:
        ValueError: If either window has non-positive duration.
    """
    km_data = extract_vehicle_and_revenue_kilometers(
        session, scenario_id, extraction_window, scaling_window
    )
    n_ready_data = extract_vehicle_count_per_type(
        session, scenario_id, extraction_window
    )

    vtype_sim: dict[int, VehicleTypeSimData] = {}
    for vtype_id in set(km_data) | set(n_ready_data):
        vkm, rkm = km_data.get(vtype_id, (0.0, 0.0))
        vtype_sim[vtype_id] = VehicleTypeSimData(
            vehicle_type_id=vtype_id,
            annual_vehicle_kilometers=vkm,
            annual_revenue_kilometers=rkm,
            n_ready=n_ready_data.get(vtype_id, 0),
        )

    area_data = extract_area_peaks(session, scenario_id, extraction_window)
    station_data = extract_station_peaks(session, scenario_id, extraction_window)

    return ScenarioSimData(
        vehicle_type_data=vtype_sim,
        area_data=area_data,
        station_data=station_data,
        eta_avail=eta_avail,
    )
