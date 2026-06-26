import datetime
import logging
import math
import warnings
from typing import List, Optional, Union, Dict

from sqlalchemy import or_, and_, distinct, func

from eflips.model import (
    Area,
    BatteryType,
    Depot,
    EnergySource,
    Event,
    EventType,
    Scenario,
    Station,
    VehicleType,
)

logger = logging.getLogger(__name__)

from eflips.impact.utils.extraction import (
    AreaSimData,
    ScenarioSimData,
    StationSimData,
    _default_scaling_factor,
    extract_simulation_data,
    get_extraction_window,
)
from eflips.impact.tco.cost_items import (
    CapexItem,
    OpexItem,
    CapexItemType,
    OpexItemType,
    net_present_value,
)
from eflips.impact.tco.dataclasses import TCOResult
from eflips.impact.utils import create_session


def _load_capex_items_vehicle(
    vehicle_types: List[VehicleType],
    sim_data: ScenarioSimData,
    eta_avail: float,
) -> List[CapexItem]:
    """Build vehicle CAPEX items from pre-loaded vehicle types and SimData.

    :param vehicle_types: All ``VehicleType`` ORM objects for the scenario.
    :param sim_data: Pre-built scenario simulation data.
    :param eta_avail: Technical availability factor; fleet size =
        ``ceil(n_ready / eta_avail)``.
    :returns: List of :class:`CapexItem` with one entry per vehicle type.
    """
    list_vt_asset = []
    for vt in vehicle_types:
        vd = sim_data.vehicle_type_data.get(int(vt.id))
        if vd is None:
            continue
        count = math.ceil(vd.n_ready / eta_avail)
        fuel_suffix = (
            "(Diesel)" if vt.energy_source == EnergySource.DIESEL else "(Electric)"
        )
        tco_parameters = vt.tco_parameters or {}
        asset = CapexItem(
            name=f"{vt.name} {fuel_suffix}",
            type=CapexItemType.VEHICLE,
            useful_life=tco_parameters["useful_life"],
            procurement_cost=tco_parameters["procurement_cost"],
            cost_escalation=tco_parameters["cost_escalation"],
            quantity=count,
        )
        list_vt_asset.append(asset)
    return list_vt_asset


def _load_capex_items_battery(
    session,
    vehicle_types: List[VehicleType],
    sim_data: ScenarioSimData,
    eta_avail: float,
) -> List[CapexItem]:
    """Build battery CAPEX items from pre-loaded vehicle types and SimData.

    :param session: SQLAlchemy session (used to query ``BatteryType`` by id).
    :param vehicle_types: All ``VehicleType`` ORM objects for the scenario.
    :param sim_data: Pre-built scenario simulation data.
    :param eta_avail: Technical availability factor; battery count per type =
        ``ceil(n_ready / eta_avail)``.
    :returns: List of :class:`CapexItem` with one entry per BEB vehicle type that
        has a battery assigned.
    """
    list_battery_asset = []
    for vt in vehicle_types:
        if vt.energy_source != EnergySource.BATTERY_ELECTRIC:
            continue
        if vt.battery_type_id is None:
            continue
        vd = sim_data.vehicle_type_data.get(int(vt.id))
        if vd is None:
            continue
        count = math.ceil(vd.n_ready / eta_avail)
        battery_type = session.get(BatteryType, vt.battery_type_id)
        if battery_type is None:
            continue
        tco_battery = battery_type.tco_parameters or {}
        asset = CapexItem(
            name="Battery type " + str(vt.battery_type_id),
            type=CapexItemType.BATTERY,
            useful_life=tco_battery["useful_life"],
            procurement_cost=tco_battery["procurement_cost"] * vt.battery_capacity,
            cost_escalation=tco_battery["cost_escalation"],
            quantity=count,
        )
        list_battery_asset.append(asset)
    return list_battery_asset


def _load_capex_items_infrastructure(
    session,
    scenario,
    area_data: dict[int, AreaSimData],
    station_data: dict[int, StationSimData],
):
    """Calculate the number of charging infrastructure items required.

    :param session: A Session object.
    :param scenario: A Scenario object.
    :param area_data: Pre-built per-area peak data from :class:`ScenarioSimData`.
    :param station_data: Pre-built per-station peak data from :class:`ScenarioSimData`.
    :returns: A tuple ``(list_of_capex_items, total_slots)``.
    """

    charging_point_types = scenario.charging_point_types
    list_asset_charging_infra = []
    total_slots = 0

    for charging_point_type in charging_point_types:
        total_count = 0
        if charging_point_type.areas is not None:
            for area in charging_point_type.areas:
                sim_data = area_data.get(area.id)
                area_capacity = area.capacity
                area_peak = sim_data.peak_simultaneous_vehicles

                if area_capacity is not None and area_peak < 0.80 * area_capacity:
                    warnings.warn(
                        f"Area {area.id}: peak vehicles ({area_peak}) is significantly "
                        f"below capacity ({area_capacity}). The calculation will used capacity, "
                        f"but infrastructure may be oversized.",
                        stacklevel=2,
                    )
                elif area_capacity is not None and area_peak < area_capacity:
                    logger.warning(
                        "Area %d: peak vehicles (%d) is mildly below capacity (%d).",
                        area.id,
                        area_peak,
                        area_capacity,
                    )

                if sim_data is not None:
                    total_count += area_capacity

        if charging_point_type.stations is not None:
            for station in charging_point_type.stations:
                sim_data_st = station_data.get(station.id)
                station_peak = sim_data_st.peak_simultaneous_vehicles
                station_capacity = station.amount_charging_places
                if (
                    station_capacity is not None
                    and station_peak < 0.80 * station_capacity
                ):
                    warnings.warn(
                        f"Station {station.id}: peak vehicles ({station_peak}) is significantly "
                        f"below capacity ({station_capacity}). Infrastructure may be oversized.",
                        stacklevel=2,
                    )
                elif station_capacity is not None and station_peak < station_capacity:
                    logger.warning(
                        "Station %d: peak vehicles (%d) is mildly below capacity (%d).",
                        station.id,
                        station_peak,
                        station_capacity,
                    )

                if sim_data_st is not None:
                    total_count += station_capacity

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


def _calc_energy_consumption_simulated(
    session,
    scenario,
    scaling_factor: float,
) -> float:
    """Return total annual energy consumption from simulation SoC data.

    :param session: A session object.
    :param scenario: A scenario object.
    :param scaling_factor: Annualisation factor (``365.0 / simulation_days``).
    :returns: Total annual energy consumption in kWh.
    """
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
    return result[0] * scaling_factor


def _calculate_total_driver_hours(
    session,
    scenario,
    scaling_factor: float,
    extraction_window: tuple[datetime.datetime, datetime.datetime],
    annual_hours_per_driver: int = 1600,
    buffer: float = 0.1,
) -> float:
    """Return total annual driver hours required for the scenario.

    :param session: A session object.
    :param scenario: A scenario object.
    :param scaling_factor: Annualisation factor (``365.0 / simulation_days``).
    :param extraction_window: ``(start, end)`` pair used to filter which events
        are included in the driver hours calculation.
    :param annual_hours_per_driver: Contractual hours per driver per year.
    :param buffer: Fractional overhead for absences and reliefs.
    :returns: Total annual driver hours (including buffer), rounded up to a full
        driver allocation.
    """
    extract_start, extract_end = extraction_window
    driver_hours = datetime.timedelta(seconds=0)
    driving_and_opcharge_events = (
        session.query(Event)
        .filter(
            Event.scenario_id == scenario.id,
            Event.time_start >= extract_start,
            Event.time_end <= extract_end,
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
    annual_driver_hours = scaling_factor * driver_hours.total_seconds() / 3600

    number_drivers = (annual_driver_hours * (1 + buffer)) // annual_hours_per_driver
    actual_driver_hours = annual_hours_per_driver * (number_drivers + 1)
    return actual_driver_hours


class TCOCalculator:
    """Calculate the total cost of ownership from scenario-level CAPEX and OPEX data."""

    def __init__(
        self,
        scenario,
        extraction_window: Optional[tuple[datetime.datetime, datetime.datetime]] = None,
        scaling_factor: Optional[float] = None,
        database_url: Optional[str] = None,
        energy_consumption_mode: str = "constant",
        capex_items=None,
        opex_items=None,
    ):
        """Initialise the TCO calculator and load all cost data from the DB.

        :param scenario: An eflips-model Scenario object or integer scenario id.
        :param extraction_window: ``(start, end)`` pair used to filter which
            trips and events are included in cost calculations. If
            ``None``, auto-detected from the earliest and latest event
            times in the scenario.
        :param scaling_factor: Annualisation factor (``365.0 / simulation_days``).
            If ``None``, computed automatically from the earliest and latest
            trip departure times via ``_default_scaling_factor``.
        :param database_url: SQLAlchemy database URL; falls back to
            ``DATABASE_URL`` environment variable when omitted.
        :param energy_consumption_mode: ``"simulated"`` (use SoC data from DB)
            or ``"constant"`` (use ``average_*_consumption`` parameters).
        :param capex_items: Reserved; must be ``None`` (not yet implemented).
        :param opex_items: Reserved; must be ``None`` (not yet implemented).
        """

        with create_session(scenario, database_url) as (session, scenario):
            self.scenario = (
                session.query(Scenario).filter(Scenario.id == scenario.id).one()
            )

            if extraction_window is None:
                self._extraction_window = get_extraction_window(session, scenario.id)
            else:
                self._extraction_window = extraction_window

            self._scaling_factor: float = (
                scaling_factor
                if scaling_factor is not None
                else _default_scaling_factor(session, scenario.id)
            )

            # Read eta_avail from scenario TCO parameters
            self.eta_avail: float = float(self.scenario.tco_parameters.get("eta_avail"))

            # Build SimData (vehicle-km, revenue-km, fleet counts, area/station peaks)
            self.sim_data: ScenarioSimData = extract_simulation_data(
                session,
                int(self.scenario.id),
                self._extraction_window,
                self._scaling_factor,
                self.eta_avail,
            )

            # Fleet totals derived directly from SimData — no separate DB query
            self.annual_vehicle_km: float = sum(
                vd.annual_vehicle_kilometers
                for vd in self.sim_data.vehicle_type_data.values()
            )
            self.annual_revenue_km: float = sum(
                vd.annual_revenue_kilometers
                for vd in self.sim_data.vehicle_type_data.values()
            )
            self.energy_consumption_mode = energy_consumption_mode

            # Query all VehicleTypes once; set missing energy_source in the same pass
            vehicle_types = (
                session.query(VehicleType)
                .filter(VehicleType.scenario_id == self.scenario.id)
                .all()
            )

            self.vehicle_types: list[VehicleType] = vehicle_types

            # Build const_consumption and mileage_by_energy_source in one loop
            const_consumption: dict[VehicleType, float] = {}
            mileage_by_energy_source: dict[str, float] = {}
            for vt in vehicle_types:
                params = vt.tco_parameters or {}
                if vt.energy_source == EnergySource.DIESEL:
                    consumption = params.get("average_diesel_consumption")
                else:
                    consumption = params.get("average_electricity_consumption")
                if consumption is None:
                    logger.warning(
                        f"VehicleType '{vt.name}' (id={vt.id}) has no consumption in "
                        "tco_parameters. It will be treated as 0."
                    )
                    consumption = 0.0
                const_consumption[vt] = consumption

                vd = self.sim_data.vehicle_type_data.get(int(vt.id))
                if vd is not None:
                    key = vt.energy_source.name
                    mileage_by_energy_source[key] = (
                        mileage_by_energy_source.get(key, 0.0)
                        + vd.annual_vehicle_kilometers
                    )
            self.const_consumption = const_consumption
            self.mileage_by_energy_source = mileage_by_energy_source

            if capex_items is None:
                self._load_capex_items_from_db(session)
            else:
                raise NotImplementedError(
                    "Using your own list of dictonary then setting up list of capex items is not implemented yet. Please use the database to load the capex items."
                )
            if opex_items is None:
                self._load_opex_items_from_db(session)
            else:
                raise NotImplementedError(
                    "Using your own list of dictonary then setting up list of opex items is not implemented yet. Please use the database to load the opex items."
                )

            self.project_duration = self.scenario.tco_parameters["project_duration"]
            self.interest_rate = self.scenario.tco_parameters["interest_rate"]
            self.inflation_rate = self.scenario.tco_parameters["inflation_rate"]

            self.result: Optional[TCOResult] = None

    def calculate(self) -> TCOResult:
        """Calculate the total cost of ownership.

        :returns: A :class:`TCOResult` with aggregated totals and per-type specific costs.
        """
        list_of_items = []
        list_of_costs = []
        total_capex = 0.0
        total_opex = 0.0

        for capex_item in self.capex_items:
            cost = (
                capex_item.calculate_total_procurement_cost(
                    project_duration=self.project_duration,
                    interest_rate=self.interest_rate,
                    net_discount_rate=self.inflation_rate,
                )
                * capex_item.quantity
            )
            list_of_items.append(capex_item)
            list_of_costs.append(cost)
            total_capex += cost

        for opex_item in self.opex_items:

            # convert to net present value for each year independently and sum up over the project duration
            cost = sum(
                net_present_value(
                    opex_item.future_cost(year), year, self.inflation_rate
                )
                for year in range(self.project_duration)
            )
            list_of_items.append(opex_item)
            list_of_costs.append(cost)
            total_opex += cost

        tco = total_capex + total_opex

        tco_by_type: dict[CapexItemType | OpexItemType, float] = {}
        for item, cost in zip(list_of_items, list_of_costs):
            tco_by_type[item.type] = tco_by_type.get(item.type, 0.0) + cost

        self.result = TCOResult(
            project_duration=self.project_duration,
            tco_by_type=tco_by_type,
            annual_revenue_km=self.annual_revenue_km,
            annual_vehicle_km=self.annual_vehicle_km,
        )
        return self.result

    def _load_capex_items_from_db(self, session) -> None:
        """Load and build all CAPEX items from the database.

        :param session: SQLAlchemy session.
        """
        assets_vehicle = _load_capex_items_vehicle(
            self.vehicle_types, self.sim_data, self.eta_avail
        )
        assets_battery = _load_capex_items_battery(
            session, self.vehicle_types, self.sim_data, self.eta_avail
        )
        assets_infrastructure, total_slots = _load_capex_items_infrastructure(
            session,
            self.scenario,
            self.sim_data.area_data,
            self.sim_data.station_data,
        )

        capex_items = (
            list(assets_vehicle) + list(assets_battery) + list(assets_infrastructure)
        )
        self.capex_items = capex_items
        self.total_slots = total_slots

    def _load_opex_items_from_db(
        self,
        session,
    ) -> None:
        """Load all OPEX items from the database.

        :param session: SQLAlchemy session.
        """

        list_opex_items = []

        scenario_params = self.scenario.tco_parameters
        escalation = scenario_params["cost_escalation_rate"]

        electric_mileage = self.mileage_by_energy_source.get("BATTERY_ELECTRIC", 0.0)
        diesel_mileage = self.mileage_by_energy_source.get("DIESEL", 0.0)

        # Staff cost
        total_driver_hours = _calculate_total_driver_hours(
            session, self.scenario, self._scaling_factor, self._extraction_window
        )
        list_opex_items.append(
            OpexItem(
                name="Staff Cost",
                type=OpexItemType.STAFF,
                unit_cost=scenario_params["staff_cost"],
                usage_amount=total_driver_hours,
                cost_escalation=escalation["staff"],
            )
        )

        # Energy cost
        match self.energy_consumption_mode:
            case "constant":
                electric_consumption = 0.0
                diesel_consumption = 0.0
                for vt in self.vehicle_types:
                    vd = self.sim_data.vehicle_type_data.get(int(vt.id))
                    if vd is None:
                        continue
                    c = (
                        self.const_consumption.get(vt, 0.0)
                        * vd.annual_vehicle_kilometers
                    )
                    if vt.energy_source == EnergySource.BATTERY_ELECTRIC:
                        electric_consumption += c
                    elif vt.energy_source == EnergySource.DIESEL:
                        diesel_consumption += c
            case "simulated":
                raise NotImplementedError(
                    "Simulated energy consumption mode is not implemented yet. "
                    "Please use 'constant' mode or implement the simulated mode in the TCOCalculator class."
                )
            case _:
                raise ValueError(
                    f"Unknown energy consumption mode: {self.energy_consumption_mode}"
                )

        if electric_mileage > 0:
            list_opex_items.append(
                OpexItem(
                    name="Energy Cost (Electric)",
                    type=OpexItemType.ENERGY,
                    unit_cost=scenario_params["fuel_cost"]["electricity"],
                    usage_amount=electric_consumption,
                    cost_escalation=escalation["electricity"],
                )
            )

        if diesel_mileage > 0:
            list_opex_items.append(
                OpexItem(
                    name="Energy Cost (Diesel)",
                    type=OpexItemType.ENERGY,
                    unit_cost=scenario_params["fuel_cost"]["diesel"],
                    usage_amount=diesel_consumption,
                    cost_escalation=escalation["diesel"],
                )
            )

        # Vehicle maintenance cost
        if electric_mileage > 0:
            list_opex_items.append(
                OpexItem(
                    name="Maintenance Cost Vehicles (Electric)",
                    type=OpexItemType.MAINTENANCE,
                    unit_cost=scenario_params["vehicle_maint_cost"]["electricity"],
                    usage_amount=electric_mileage,
                    cost_escalation=escalation["general"],
                )
            )

        if diesel_mileage > 0:
            list_opex_items.append(
                OpexItem(
                    name="Maintenance Cost Vehicles (Diesel)",
                    type=OpexItemType.MAINTENANCE,
                    unit_cost=scenario_params["vehicle_maint_cost"]["diesel"],
                    usage_amount=diesel_mileage,
                    cost_escalation=escalation["general"],
                )
            )

        # Insurance
        total_number_vehicles = sum(
            asset.quantity
            for asset in self.capex_items
            if asset.type == CapexItemType.VEHICLE
        )
        list_opex_items.append(
            OpexItem(
                name="Insurance",
                type=OpexItemType.OTHER,
                unit_cost=scenario_params["insurance"],
                usage_amount=total_number_vehicles,
                cost_escalation=escalation["insurance"],
            )
        )

        # Taxes
        list_opex_items.append(
            OpexItem(
                name="Taxes",
                type=OpexItemType.OTHER,
                unit_cost=scenario_params["taxes"],
                usage_amount=total_number_vehicles,
                cost_escalation=escalation["general"],
            )
        )

        # Infrastructure maintenance cost
        list_opex_items.append(
            OpexItem(
                name="Maintenance Cost Infrastructure",
                type=OpexItemType.MAINTENANCE,
                unit_cost=scenario_params["infra_maint_cost"],
                usage_amount=self.total_slots,
                cost_escalation=escalation["general"],
            )
        )

        self.opex_items = list_opex_items
