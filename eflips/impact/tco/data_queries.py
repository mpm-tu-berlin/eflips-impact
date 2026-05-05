import datetime
import logging
import warnings
from typing import List, Tuple, Any, Dict, Optional, Union

from eflips.model import (
    Vehicle,
    Station,
    VehicleType,
    BatteryType,
    Scenario,
    ChargingPointType,
    Area,
    Event,
    EventType,
    Depot,
    EnergySource,
)

logger = logging.getLogger(__name__)

from sqlalchemy import or_, and_, distinct
from sqlalchemy import func

from eflips.impact.tco.cost_items import CapexItemType, CapexItem, OpexItem
from eflips.impact.utils import create_session
from eflips.impact.utils.extraction import (
    AreaSimData,
    StationSimData,
    _annual_scaling_factor,
    extract_area_peaks,
    extract_station_peaks,
    extract_vehicle_and_revenue_kilometers,
)


def load_capex_items_vehicle(session, scenario):
    # Get the number of vehicles grouped by vehicle type
    list_vt_count_parameter = (
        session.query(VehicleType, func.count(Vehicle.id), VehicleType.tco_parameters)
        .join(Vehicle, Vehicle.vehicle_type_id == VehicleType.id)
        .filter(Vehicle.scenario_id == scenario.id)
        .group_by(VehicleType.id)
        .all()
    )

    # Write the results in a dictionary and return the dictionary
    list_vt_asset = []
    for vehicle_type, vehicle_count, tco_parameters in list_vt_count_parameter:
        # Get the total annual mileage for the respective vehicle type
        fuel_suffix = (
            "(Diesel)"
            if vehicle_type.energy_source == EnergySource.DIESEL
            else "(Electric)"
        )
        asset_this_vtype = CapexItem(
            name=f"{vehicle_type.name} {fuel_suffix}",
            type=CapexItemType.VEHICLE,
            useful_life=tco_parameters["useful_life"],
            procurement_cost=tco_parameters["procurement_cost"],
            cost_escalation=tco_parameters["cost_escalation"],
            quantity=vehicle_count,
        )
        list_vt_asset.append(asset_this_vtype)

    return list_vt_asset


def load_capex_items_battery(session, scenario):
    """
    This method gets the battery size from the session provided and returns it in a dictionary.
    :param session: A session object.
    :param scenario: A scenario object.
    :return: A dictionary including the name if the vehicle using this battery, battery capacity and the tco parameters.
    """
    list_vt_battery = (
        session.query(
            VehicleType,
            VehicleType.battery_capacity,
            BatteryType.tco_parameters,
            func.count(Vehicle.id),
        )
        .join(BatteryType, BatteryType.id == VehicleType.battery_type_id)
        .join(Vehicle, Vehicle.vehicle_type_id == VehicleType.id)
        .filter(
            VehicleType.scenario_id == scenario.id,
            VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC,
        )
        .group_by(VehicleType.id, VehicleType.battery_capacity, BatteryType.id)
        .all()
    )

    list_battery_asset = []
    for vehicle_type, battery_capacity, tco_battery, number in list_vt_battery:
        asset_this_battery = CapexItem(
            name="Battery type " + str(vehicle_type.battery_type_id),
            type=CapexItemType.BATTERY,
            useful_life=tco_battery["useful_life"],
            procurement_cost=tco_battery["procurement_cost"] * battery_capacity,
            cost_escalation=tco_battery["cost_escalation"],
            quantity=number,
        )
        list_battery_asset.append(asset_this_battery)
    return list_battery_asset


# This function returns the number of the charging slots and stations including the tco parameters grouped by the
# charging infrastructure type.
def load_capex_items_infrastructure(
    session,
    scenario,
    extraction_window: tuple[datetime.datetime, datetime.datetime],
):
    """Calculate the number of charging infrastructure items required.

    Args:
        session: A Session object.
        scenario: A Scenario object.
        extraction_window: ``(start, end)`` pair used to filter events for
            peak occupancy calculation.

    Returns:
        A tuple ``(list_of_capex_items, total_slots)``.
    """
    area_peaks: dict[int, AreaSimData] = extract_area_peaks(
        session, scenario.id, extraction_window
    )
    station_peaks: dict[int, StationSimData] = extract_station_peaks(
        session, scenario.id, extraction_window
    )

    charging_point_types = scenario.charging_point_types
    list_asset_charging_infra = []
    total_slots = 0

    for charging_point_type in charging_point_types:
        total_count = 0
        if charging_point_type.areas is not None:
            for area in charging_point_type.areas:
                sim_data = area_peaks.get(area.id)
                if sim_data is not None:
                    total_count += sim_data.peak_simultaneous_vehicles

        if charging_point_type.stations is not None:
            for station in charging_point_type.stations:
                sim_data_st = station_peaks.get(station.id)
                if sim_data_st is not None:
                    total_count += sim_data_st.peak_simultaneous_vehicles

        if total_count != 0:
            total_slots += total_count
            asset_charging_point_type = CapexItem(
                name=charging_point_type.name,
                type=CapexItemType.INFRASTRUCTURE,
                useful_life=charging_point_type.tco_parameters["useful_life"],
                procurement_cost=charging_point_type.tco_parameters["procurement_cost"],
                cost_escalation=charging_point_type.tco_parameters["cost_escalation"],
                quantity=int(total_count),
            )
            list_asset_charging_infra.append(asset_charging_point_type)

    # Get the charging stations and the respective tco parameters.

    depots = (
        session.query(
            func.count(func.distinct(Station.id)),
            Station.tco_parameters,
        )
        .join(Event, Event.station_id == Station.id)
        .filter(
            Station.scenario_id == scenario.id,
            or_(
                Event.event_type == "CHARGING_DEPOT",
            ),
        )
        .group_by(Station.tco_parameters)
        .all()
    )

    stations = (
        session.query(
            func.count(func.distinct(Station.id)),
            Station.tco_parameters,
        )
        .join(Event, Event.station_id == Station.id)
        .filter(
            Station.scenario_id == scenario.id,
            or_(
                Event.event_type == "CHARGING_OPPORTUNITY",
            ),
        )
        .group_by(Station.tco_parameters)
        .all()
    )

    # Add all stations grouped by type and tco parameters to the infrastructure dictionary.

    for depot_count, tco_parameters in depots:
        asset_depot = CapexItem(
            name="Depot",
            type=CapexItemType.INFRASTRUCTURE,
            useful_life=tco_parameters["useful_life"],
            procurement_cost=tco_parameters["procurement_cost"],
            cost_escalation=tco_parameters["cost_escalation"],
            quantity=int(depot_count),
        )
        list_asset_charging_infra.append(asset_depot)

    for station_count, tco_parameters in stations:
        asset_station = CapexItem(
            name="Station",
            type=CapexItemType.INFRASTRUCTURE,
            useful_life=tco_parameters["useful_life"],
            procurement_cost=tco_parameters["procurement_cost"],
            cost_escalation=tco_parameters["cost_escalation"],
            quantity=int(station_count),
        )
        list_asset_charging_infra.append(asset_station)

    return list_asset_charging_infra, total_slots


# Get the total fuel / Energy consumption from the database.
def calc_energy_consumption_simulated(
    session,
    scenario,
    scaling_window: tuple[datetime.datetime, datetime.datetime],
):
    """Return total annual energy consumption from simulation SoC data.

    Args:
        session: A session object.
        scenario: A scenario object.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor.

    Returns:
        Total annual energy consumption in kWh.
    """

    # Obtain the energy consumption as the difference in state of charge before and after the charging events.
    # This difference is then multiplied by the battery capacity and divided by the charging efficiency
    # to account for the Energy lost during charging.
    result = (
        session.query(
            func.sum(
                (Event.soc_end - Event.soc_start)
                * VehicleType.battery_capacity
                / VehicleType.charging_efficiency
            )
        )
        .select_from(Event)
        .join(VehicleType, Event.vehicle_type_id == VehicleType.id)
        .filter(
            or_(
                Event.event_type == "CHARGING_DEPOT",
                Event.event_type == "CHARGING_OPPORTUNITY",
            ),
            Event.scenario_id == scenario.id,
            VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC,
        )
        .one()
    )

    # Calculate the annual energy consumption
    energy_consumption = result[0] * _annual_scaling_factor(scaling_window)

    return energy_consumption


# Get the fleet mileage by vehicle type in km.


def get_annual_fleet_mileage(
    session,
    scenario,
    extraction_window: tuple[datetime.datetime, datetime.datetime],
    scaling_window: tuple[datetime.datetime, datetime.datetime],
) -> tuple[float, float]:
    """Return total annual vehicle-km and revenue-km for the scenario.

    Args:
        session: A session object.
        scenario: A scenario object.
        extraction_window: ``(start, end)`` pair used to filter trips.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor.

    Returns:
        ``(total_vehicle_km, total_revenue_km)`` annualised.
    """
    km_data = extract_vehicle_and_revenue_kilometers(
        session, scenario.id, extraction_window, scaling_window
    )
    total_vkm = sum(v for v, _ in km_data.values())
    total_rkm = sum(r for _, r in km_data.values())
    return total_vkm, total_rkm


def get_mileage_per_vehicle_type(
    session,
    scenario,
    extraction_window: tuple[datetime.datetime, datetime.datetime],
    scaling_window: tuple[datetime.datetime, datetime.datetime],
) -> Dict[VehicleType, float]:
    """Return annual vehicle-km keyed by VehicleType ORM object.

    Args:
        session: A session object.
        scenario: A scenario object.
        extraction_window: ``(start, end)`` pair used to filter trips.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor.

    Returns:
        Dict mapping each ``VehicleType`` to its annual vehicle-km.
    """
    km_data = extract_vehicle_and_revenue_kilometers(
        session, scenario.id, extraction_window, scaling_window
    )
    vtypes = {
        vt.id: vt
        for vt in session.query(VehicleType)
        .filter(VehicleType.scenario_id == scenario.id)
        .all()
    }
    return {vtypes[vid]: vkm for vid, (vkm, _) in km_data.items() if vid in vtypes}


# Calculate the annual driver hours.
def calculate_total_driver_hours(
    session,
    scenario,
    scaling_window: tuple[datetime.datetime, datetime.datetime],
    annual_hours_per_driver: int = 1600,
    buffer: float = 0.1,
) -> float:
    """Return total annual driver hours required for the scenario.

    Args:
        session: A session object.
        scenario: A scenario object.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor.
        annual_hours_per_driver: Contractual hours per driver per year.
        buffer: Fractional overhead for absences and reliefs.

    Returns:
        Total annual driver hours (including buffer), rounded up to a full
        driver allocation.
    """
    driver_hours = datetime.timedelta(seconds=0)
    driving_and_opcharge_events = (
        session.query(Event)
        .filter(
            Event.scenario_id == scenario.id,
            or_(
                Event.event_type == EventType.DRIVING,
                Event.event_type == EventType.CHARGING_OPPORTUNITY,
                and_(
                    Event.event_type == EventType.STANDBY_DEPARTURE,
                    Event.area_id.is_(None),
                ),
                and_(Event.event_type == EventType.STANDBY, Event.area_id.is_(None)),
            ),
        )
        .all()
    )

    for event in driving_and_opcharge_events:
        driver_hours += event.time_end - event.time_start
    annual_driver_hours = (
        _annual_scaling_factor(scaling_window)
        * driver_hours.total_seconds()
        / 3600
    )

    number_drivers = (annual_driver_hours * (1 + buffer)) // annual_hours_per_driver
    actual_driver_hours = annual_hours_per_driver * (number_drivers + 1)
    return actual_driver_hours


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
    from eflips.impact.tco.tco_parameter_config import TcoParamSet

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
