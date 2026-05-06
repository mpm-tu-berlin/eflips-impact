import warnings
from typing import List, Any, Optional, Union

from eflips.model import (
    Station,
    VehicleType,
    BatteryType,
    Scenario,
    ChargingPointType,
    Area,
    Event,
    EventType,
    Depot,
)

from sqlalchemy import distinct

from eflips.impact.utils import create_session


def init_tco_parameters(
    scenario: Union[Scenario, int, Any],
    database_url: Optional[str] = None,
    scenario_params: Optional["ScenarioTCOParameter"] = None,
    vehicle_type_params: Optional[List["VehicleTypeTCOParameter"]] = None,
    battery_type_params: Optional[List["BatteryTypeTCOParameter"]] = None,
    charging_point_type_params: Optional[List["ChargingPointTypeTCOParameter"]] = None,
    charging_infra_params: Optional[List["ChargingInfrastructureTCOParameter"]] = None,
):
    """
    Initialize the TCO parameters for the given scenario in the database.

    Writes ``tco_parameters`` JSONB on existing rows only. BatteryType and
    ChargingPointType row creation is the responsibility of
    :func:`eflips.impact.utils.fleet_init.init_fleet`; this function will warn
    and skip if a referenced BatteryType or ChargingPointType is missing.

    :param scenario: An eflips.model.Scenario object or any object containing a valid scenario id.
    :param database_url: The database URL to connect to.
    :param scenario_params: A :class:`ScenarioTCOParameter` instance.
    :param vehicle_type_params: A list of :class:`VehicleTypeTCOParameter` instances. Matched to
        existing VehicleTypes in the database by ``name_short``.
    :param battery_type_params: A list of :class:`BatteryTypeTCOParameter` instances. Matched via
        ``vehicle_name_short`` to find the associated VehicleType, then writes ``tco_parameters``
        on the linked BatteryType row. Skips with a warning if the VehicleType has no BatteryType
        assigned (call ``init_fleet`` first).
    :param charging_point_type_params: A list of :class:`ChargingPointTypeTCOParameter` instances.
        Matched by ``type`` ("depot" or "opportunity"). Skips with a warning if no
        ChargingPointType of the given type exists in the scenario (call ``init_fleet`` first).
        Assumes at most one ChargingPointType per type per scenario.
    :param charging_infra_params: A list of :class:`ChargingInfrastructureTCOParameter` instances.
        Converted via ``to_dict()`` and applied to stations by ``type`` ("station" or "depot").
    """

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
        # ChargingInfrastructureTCOParameter.
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


def init_tco_parameters_from_json(
    scenario: Union[Scenario, int, Any],
    json_path: Union[str, "Path"],
    database_url: Optional[str] = None,
) -> None:
    """Initialize TCO parameters from a JSON file.

    Convenience wrapper around :func:`init_tco_parameters` that loads all
    parameters from a JSON file via :class:`TcoParamSet`.

    The JSON file must have the structure produced by the default parameter
    files in ``eflips/tco/default_params/``:

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
    :param json_path: Path to the JSON parameter file.
    :param database_url: The database URL to connect to.
    """
    from pathlib import Path
    from eflips.impact.tco.dataclasses import TcoParamSet

    params = TcoParamSet.from_json(Path(json_path))
    init_tco_parameters(
        scenario=scenario,
        database_url=database_url,
        scenario_params=params.scenario,
        vehicle_type_params=params.vehicle_types,
        battery_type_params=params.battery_types,
        charging_point_type_params=params.charging_point_types,
        charging_infra_params=params.charging_infrastructure,
    )
