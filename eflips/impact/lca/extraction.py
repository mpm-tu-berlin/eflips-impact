"""Extract simulation outputs from an eflips-model database.

Queries an eflips-model database for vehicle kilometres, revenue
kilometres, fleet size, and peak charging infrastructure utilisation.
Energy and diesel consumption are computed in the calculation step from
``lca_params`` values and the kilometres extracted here.

Low-level query helpers (annual scaling, per-vehicle-type kilometres,
peak area/station utilisation) live in
:mod:`eflips.impact.utils.extraction`.  This module provides the
LCA-specific aggregation container :class:`ScenarioSimData` and the
public entry point :func:`extract_simulation_data`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from eflips.impact.utils.extraction import (
    AreaSimData,
    StationSimData,
    extract_area_peaks,
    extract_station_peaks,
    extract_vehicle_and_revenue_kilometers,
    extract_vehicle_count_per_type,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LCA-specific data structures
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_simulation_data(
    session: Session,
    scenario_id: int,
    extraction_window: tuple[datetime, datetime],
    scaling_window: tuple[datetime, datetime],
    eta_avail: float = 0.9,
) -> ScenarioSimData:
    """Extract all simulation outputs needed for the LCA calculation.

    Queries the eflips-model database for vehicle/revenue kilometres,
    fleet size, and peak charging infrastructure utilisation.  Energy
    and fuel consumption are **not** extracted here — they are derived
    from ``lca_params`` in the calculation step.

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
