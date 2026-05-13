import warnings
from datetime import datetime
from pathlib import Path
from typing import Union, Optional, Any, Dict, Tuple, List

from sqlalchemy import distinct

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
    ScenarioTCOParams,
    VehicleTypeTCOParams,
    BatteryTypeTCOParams,
    ChargingPointTypeTCOParams,
    ChargingInfrastructureTCOParams,
    TCOParamSet,
    TCOResult,
)
from eflips.impact.utils import create_session, get_scaling_window, get_extraction_window
import logging


def init_tco_params(
    scenario: Union[Scenario, int, Any],
    json_path: Optional[Union[str, Path]] = None,
    database_url: Optional[str] = None,
    scenario_params: Optional[ScenarioTCOParams] = None,
    vehicle_type_params: Optional[List[VehicleTypeTCOParams]] = None,
    battery_type_params: Optional[List[BatteryTypeTCOParams]] = None,
    charging_point_type_params: Optional[List[ChargingPointTypeTCOParams]] = None,
    charging_infra_params: Optional[List[ChargingInfrastructureTCOParams]] = None,
) -> None:
    """Initialize TCO parameters for the given scenario in the database.

    Writes ``tco_parameters`` JSONB on existing rows only. BatteryType and
    ChargingPointType row creation is the responsibility of
    :func:`eflips.impact.utils.fleet_init.init_fleet`; this function will warn
    and skip if a referenced BatteryType or ChargingPointType is missing.

    Pass either ``json_path`` *or* the individual ``*_params`` keyword
    arguments — not both. Providing ``json_path`` together with any
    ``*_params`` argument raises :class:`ValueError`.

    The JSON file must follow the :class:`~eflips.impact.tco.dataclasses.TCOParamSet`
    structure:

    .. code-block:: json

        {
          "scenario": { ... },
          "vehicle_types": [ { "name_short": "EN", ... }, ... ],
          "battery_types": [ { "vehicle_name_short": "EN", ... }, ... ],
          "charging_point_types": [ { "type": "depot", ... }, ... ],
          "charging_infrastructure": [ { "type": "depot", ... }, ... ]
        }

    :param scenario: An eflips.model.Scenario object, a scenario id, or any
        object with a valid scenario id.
    :param json_path: Path to the JSON parameter file. Mutually exclusive with
        the individual ``*_params`` arguments.
    :param database_url: The database URL to connect to.
    :param scenario_params: A :class:`ScenarioTCOParams` instance.
    :param vehicle_type_params: A list of :class:`VehicleTypeTCOParams` instances.
        Matched to existing VehicleTypes in the database by ``name_short``.
    :param battery_type_params: A list of :class:`BatteryTypeTCOParams` instances.
        Matched via ``vehicle_name_short`` to find the associated VehicleType, then
        writes ``tco_parameters`` on the linked BatteryType row. Skips with a warning
        if the VehicleType has no BatteryType assigned (call ``init_fleet`` first).
    :param charging_point_type_params: A list of :class:`ChargingPointTypeTCOParams`
        instances. Matched by ``type`` ("depot" or "opportunity"). Skips with a warning
        if no ChargingPointType of the given type exists in the scenario (call
        ``init_fleet`` first). Assumes at most one ChargingPointType per type per
        scenario.
    :param charging_infra_params: A list of :class:`ChargingInfrastructureTCOParams`
        instances. Converted via ``to_dict()`` and applied to stations by ``type``
        ("station" or "depot").
    :raises ValueError: If ``json_path`` is supplied together with any individual
        ``*_params`` argument.
    """
    individual_params = (
        scenario_params,
        vehicle_type_params,
        battery_type_params,
        charging_point_type_params,
        charging_infra_params,
    )
    if json_path is not None and any(p is not None for p in individual_params):
        raise ValueError(
            "json_path and individual *_params arguments are mutually exclusive. "
            "Pass either json_path or the individual parameters, not both."
        )

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
                        f"eflips.impact.utils.init_fleet first to create and assign "
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
        # Row creation lives in ``init_fleet``; this function only writes ``tco_parameters``.
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
                        f"{scenario.id}. Run eflips.impact.utils.init_fleet first to "
                        f"create and assign ChargingPointType rows. Skipping.",
                        UserWarning,
                    )
                    continue

                existing_cps[0].tco_parameters = cp_param.to_dict()

        # --- Charging infrastructure ---
        #
        # ASSUMPTION: all opportunity-charging stations share the same infrastructure TCO
        # parameters, and all depot stations share the same infrastructure TCO parameters.
        # The same dict is written to every station of the matching type. If per-station
        # parameters are needed in the future, replace the bulk loop below with a per-station
        # lookup and introduce a station identifier (e.g. station name) as a match key in
        # ChargingInfrastructureTCOParams.
        if charging_infra_params is not None:
            for infra_param in charging_infra_params:
                match infra_param.type:
                    case "station":
                        charging_station_ids = (
                            session.query(distinct(Event.station_id))
                            .filter(
                                Event.event_type == EventType.CHARGING_OPPORTUNITY,
                                Event.scenario_id == scenario.id,
                            )
                            .all()
                        )
                        for station_id in charging_station_ids:
                            station = (
                                session.query(Station)
                                .filter(Station.id == station_id[0])
                                .one()
                            )
                            station.tco_parameters = infra_param.to_dict()
                    case "depot":
                        depot_stations = (
                            session.query(Depot.station_id)
                            .filter(Depot.scenario_id == scenario.id)
                            .all()
                        )
                        for station_id in depot_stations:
                            station = (
                                session.query(Station)
                                .filter(Station.id == station_id[0])
                                .one()
                            )
                            station.tco_parameters = infra_param.to_dict()
                    case _:
                        raise ValueError(
                            f"Unknown infrastructure type: {infra_param.type}"
                        )


def calculate_tco(
    scenario: Union[Scenario, int, Any],
    database_url: Optional[str] = None,
    extraction_window: Optional[Tuple[datetime, datetime]] = None,
    scaling_window: Optional[Tuple[datetime, datetime]] = None,
) -> TCOResult:
    """Calculate the Total Cost of Ownership (TCO) for a given scenario.

    :param scenario: A :class:`eflips.model.Scenario` object, an int scenario id,
        or any object with an ``id`` attribute.
    :param database_url: Optional database URL — only consulted when ``scenario``
        is not a Scenario instance.
    :param extraction_window: Optional time window within which events are extracted.
        If not provided, all events in the scenario are considered.
    :param scaling_window: Optional time window whose duration is used to scale to
        an operation year. If not provided, the earliest and latest trip times are used.
    :returns: A :class:`TCOResult` with aggregated totals and per-type costs.
        Use :attr:`TCOResult.tco_by_type_per_vehicle_km` or
        :attr:`TCOResult.tco_by_type_per_revenue_km` for normalised breakdowns.
    """
    tco_calculator = TCOCalculator(
        scenario,
        database_url=database_url,
        energy_consumption_mode="constant",
        scaling_window=scaling_window,
        extraction_window=extraction_window,
    )
    return tco_calculator.calculate()
