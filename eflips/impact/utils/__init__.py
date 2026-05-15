"""Shared utilities for eflips-impact.

Two responsibilities, two modules:

- :mod:`eflips.impact.utils.fleet_init` — creates BatteryType / ChargingPointType
  rows for a scenario from ``fleet.json`` and assigns them to VehicleType / Area
  / Station.
- :mod:`eflips.impact.utils.extraction` — read-only simulation queries shared by
  ``tco/`` and ``lca/``.

Plus the shared :func:`create_session` context manager used by all three of
``utils/``, ``tco/``, and ``lca/`` to resolve a polymorphic ``scenario``
argument into ``(session, Scenario)``.
"""

from eflips.impact.utils.extraction import (
    AreaSimData,
    ScenarioSimData,
    StationSimData,
    VehicleTypeSimData,
    _annual_scaling_factor,
    _simulation_start_and_end,
    extract_area_peaks,
    extract_simulation_data,
    extract_station_peaks,
    extract_vehicle_and_revenue_kilometers,
    extract_vehicle_count_per_type,
    get_extraction_window,
    get_scaling_window,
)
from eflips.impact.utils.fleet_init import complete_fleet
from eflips.impact.utils.session import create_session

__all__ = [
    "AreaSimData",
    "ScenarioSimData",
    "StationSimData",
    "VehicleTypeSimData",
    "_annual_scaling_factor",
    "_simulation_start_and_end",
    "create_session",
    "extract_area_peaks",
    "extract_simulation_data",
    "extract_station_peaks",
    "extract_vehicle_and_revenue_kilometers",
    "extract_vehicle_count_per_type",
    "get_extraction_window",
    "get_scaling_window",
    "complete_fleet",
]
