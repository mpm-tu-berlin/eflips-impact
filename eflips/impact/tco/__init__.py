import warnings
from datetime import datetime
from pathlib import Path
from typing import Union, Optional, Any, Tuple

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from eflips.model import (
    Scenario,
    Station,
    VehicleType,
    BatteryType,
    ChargingPointType,
    Area,
    Event,
    EventType,
    Depot,
)

from eflips.impact.tco.calculation import TCOCalculator
from eflips.impact.tco.dataclasses import (
    ChargingInfrastructureTCOParams,
    TCOParamSet,
    TCOResult,
)
from eflips.impact.utils import (
    create_session,
    get_extraction_window,
)
import logging


def _stations_of_type(session: Session, scenario_id: int, infra_type: str) -> set[int]:
    """Return the ids of stations matching a charging-infrastructure type.

    :param session: An open database session.
    :param scenario_id: The scenario to search within.
    :param infra_type: ``"station"`` for opportunity-charging stations (those with
        ``CHARGING_OPPORTUNITY`` events) or ``"depot"`` for stations attached to a depot.
    :returns: The set of matching :class:`~eflips.model.Station` ids.
    :raises ValueError: If ``infra_type`` is neither ``"station"`` nor ``"depot"``.
    """
    match infra_type:
        case "station":
            rows = (
                session.query(distinct(Event.station_id))
                .filter(
                    Event.event_type == EventType.CHARGING_OPPORTUNITY,
                    Event.scenario_id == scenario_id,
                )
                .all()
            )
        case "depot":
            rows = (
                session.query(Depot.station_id)
                .filter(Depot.scenario_id == scenario_id)
                .all()
            )
        case _:
            raise ValueError(f"Unknown infrastructure type: {infra_type}")
    return {row[0] for row in rows}


def init_tco_params(
    scenario: Union[Scenario, int, Any],
    json_path: Union[str, Path],
    database_url: Optional[str] = None,
) -> None:
    """Initialize TCO parameters for the given scenario in the database.

    Writes ``tco_parameters`` JSONB on existing rows only. BatteryType and
    ChargingPointType row creation is the responsibility of
    :func:`eflips.impact.utils.fleet_init.complete_fleet`; this function will warn
    and skip if a referenced BatteryType or ChargingPointType is missing.

    The JSON file must follow the :class:`~eflips.impact.tco.dataclasses.TCOParamSet`
    structure:

    .. code-block:: none

        {
          "scenario": { ... },
          "vehicle_types": [ { "name_short": "EN", ... }, ... ],
          "battery_types": [ { "vehicle_name_short": "EN", ... }, ... ],
          "charging_point_types": [ { "type": "depot", ... }, ... ],
          "charging_infrastructure": [ { "type": "depot", ... }, ... ]
        }

    :param scenario: An eflips.model.Scenario object, a scenario id, or any
        object with a valid scenario id.
    :param json_path: Path to the JSON parameter file.
    :param database_url: The database URL to connect to.
    """
    scenario_params = None
    vehicle_type_params = None
    battery_type_params = None
    charging_point_type_params = None
    charging_infra_params = None

    if json_path is not None:
        params = TCOParamSet.from_json(Path(json_path))
        scenario_params = params.scenario
        vehicle_type_params = params.vehicle_types
        battery_type_params = params.battery_types
        charging_point_type_params = params.charging_point_types
        charging_infra_params = params.charging_infrastructure

    with create_session(scenario, database_url) as (session, scenario):

        # --- Scenario TCO parameters ---
        if scenario_params is not None:
            scenario.tco_parameters = scenario_params.to_dict()

        # --- Vehicle types: match by name_short ---
        if vehicle_type_params is not None:
            for vt_param in vehicle_type_params:
                vt = (
                    session.query(VehicleType)
                    .filter(
                        VehicleType.name_short == vt_param.name_short,
                        VehicleType.scenario_id == scenario.id,
                    )
                    .one_or_none()
                )

                if vt is None:
                    warnings.warn(
                        f"VehicleType with name_short '{vt_param.name_short}' not found "
                        f"in scenario {scenario.id}. Skipping."
                    )
                    continue

                vt.tco_parameters = vt_param.to_dict()

        # --- Battery types: match via vehicle_name_short, write on existing row only ---
        if battery_type_params is not None:
            for bt_param in battery_type_params:
                vt = (
                    session.query(VehicleType)
                    .filter(
                        VehicleType.name_short == bt_param.vehicle_name_short,
                        VehicleType.scenario_id == scenario.id,
                    )
                    .one_or_none()
                )

                if vt is None:
                    warnings.warn(
                        f"VehicleType with name_short '{bt_param.vehicle_name_short}' not found "
                        f"in scenario {scenario.id}. Skipping."
                    )
                    continue

                if vt.battery_type_id is None:
                    warnings.warn(
                        f"VehicleType '{bt_param.vehicle_name_short}' in scenario "
                        f"{scenario.id} has no BatteryType assigned. Run "
                        f"eflips.impact.utils.complete_fleet first to create and assign "
                        f"BatteryType rows. Skipping.",
                        UserWarning,
                    )
                    continue

                battery_type = (
                    session.query(BatteryType)
                    .filter(BatteryType.id == vt.battery_type_id)
                    .one()
                )
                battery_type.tco_parameters = bt_param.to_dict()

        # --- Charging point types: write on existing row only ---
        #
        # Assumes at most one ChargingPointType per ``type`` (depot, opportunity) per scenario.
        # Row creation lives in ``complete_fleet``; this function only writes ``tco_parameters``.
        if charging_point_type_params is not None:
            for cp_param in charging_point_type_params:
                match cp_param.type:
                    case "depot":
                        existing_cps = (
                            session.query(ChargingPointType)
                            .join(
                                Area,
                                Area.charging_point_type_id == ChargingPointType.id,
                            )
                            .filter(Area.scenario_id == scenario.id)
                            .distinct()
                            .all()
                        )
                    case "opportunity":
                        existing_cps = (
                            session.query(ChargingPointType)
                            .join(
                                Station,
                                Station.charging_point_type_id == ChargingPointType.id,
                            )
                            .filter(Station.scenario_id == scenario.id)
                            .distinct()
                            .all()
                        )
                    case _:
                        raise ValueError(
                            f"Unknown charging point type: {cp_param.type}"
                        )

                assert len(existing_cps) <= 1, (
                    f"Expected at most 1 {cp_param.type} ChargingPointType in scenario "
                    f"{scenario.id}, found {len(existing_cps)}."
                )
                if not existing_cps:
                    warnings.warn(
                        f"No '{cp_param.type}' ChargingPointType found in scenario "
                        f"{scenario.id}. Run eflips.impact.utils.complete_fleet first to "
                        f"create and assign ChargingPointType rows. Skipping.",
                        UserWarning,
                    )
                    continue

                existing_cps[0].tco_parameters = cp_param.to_dict()

        # --- Charging infrastructure ---
        #
        # Each ``type`` may have at most one *default* entry (no ``station_ids``), applied
        # to every station of that type, plus any number of *override* entries
        # (``station_ids`` given) that target specific stations. Overrides win over the
        # default, so "these stations get A, everything else of this type gets B" is
        # expressed as one override entry (A) plus one default entry (B).
        #
        # Every affected station is resolved to a single parameter set *before* writing, so
        # the outcome does not depend on the order of entries in the JSON. An override id
        # outside its declared type's set of stations is still written, but warns.
        if charging_infra_params is not None:
            # Station ids in scope for each referenced type (raises on unknown types).
            scopes = {
                infra_type: _stations_of_type(session, scenario.id, infra_type)
                for infra_type in {p.type for p in charging_infra_params}
            }

            resolved: dict[int, ChargingInfrastructureTCOParams] = {}

            # Default layer: at most one no-id entry per type, seeded onto its whole scope.
            for infra_type, scope in scopes.items():
                defaults = [
                    p
                    for p in charging_infra_params
                    if p.type == infra_type and not p.station_ids
                ]
                if len(defaults) > 1:
                    raise ValueError(
                        f"Multiple default charging-infrastructure entries (no "
                        f"station_ids) for type '{infra_type}'; expected at most one."
                    )
                if defaults:
                    for station_id in scope:
                        resolved[station_id] = defaults[0]

            # Override layer wins over defaults; warn on ids outside their type's scope.
            for infra_param in charging_infra_params:
                if not infra_param.station_ids:
                    continue
                for station_id in infra_param.station_ids:
                    if station_id not in scopes[infra_param.type]:
                        warnings.warn(
                            f"Station id {station_id} is not a '{infra_param.type}' "
                            f"charging station in scenario {scenario.id}; writing its "
                            f"TCO parameters anyway."
                        )
                    resolved[station_id] = infra_param

            # Single write per resolved station.
            for station_id, infra_param in resolved.items():
                station = (
                    session.query(Station)
                    .filter(
                        Station.id == station_id,
                        Station.scenario_id == scenario.id,
                    )
                    .one_or_none()
                )
                if station is None:
                    warnings.warn(
                        f"Station with id {station_id} not found in scenario "
                        f"{scenario.id}. Skipping."
                    )
                    continue
                station.tco_parameters = infra_param.to_dict()


def calculate_tco(
    scenario: Union[Scenario, int, Any],
    database_url: Optional[str] = None,
    extraction_window: Optional[Tuple[datetime, datetime]] = None,
    scaling_factor: Optional[float] = None,
) -> TCOResult:
    """Calculate the Total Cost of Ownership (TCO) for a given scenario.

    :param scenario: A :class:`eflips.model.Scenario` object, an int scenario id,
        or any object with an ``id`` attribute.
    :param database_url: Optional database URL — only consulted when ``scenario``
        is not a Scenario instance.
    :param extraction_window: Optional time window within which events are extracted.
        If not provided, all events in the scenario are considered.
    :param scaling_factor: Annualisation factor (``365.0 / simulation_days``).
        If not provided, derived from the resolved extraction window.
    :returns: A :class:`TCOResult` with aggregated totals and per-type costs.
        Use :attr:`TCOResult.tco_by_type_per_vehicle_km` or
        :attr:`TCOResult.tco_by_type_per_revenue_km` for normalised breakdowns.
    """
    tco_calculator = TCOCalculator(
        scenario,
        database_url=database_url,
        energy_consumption_mode="constant",
        scaling_factor=scaling_factor,
        extraction_window=extraction_window,
    )
    return tco_calculator.calculate()
