import logging
from datetime import datetime
from typing import Optional

from eflips.model import (
    Scenario,
    VehicleType,
    EnergySource,
)

logger = logging.getLogger(__name__)

from eflips.impact.tco.data_queries import (
    load_capex_items_vehicle,
    load_capex_items_battery,
    load_capex_items_infrastructure,
    get_annual_fleet_mileage,
    calculate_total_driver_hours,
    calc_energy_consumption_simulated,
    get_mileage_per_vehicle_type,
)

from eflips.impact.tco.cost_items import (
    CapexItem,
    OpexItem,
    CapexItemType,
    OpexItemType,
    net_present_value,
)
from eflips.impact.tco.tco_parameter_config import TCOResult
from eflips.impact.utils import create_session

import pandas as pd


class TCOCalculator:
    """
    This class is used to calculate the total cost of ownership based on the input data provided in the dictionaries.
    It contains methods to calculate the CAPEX and OPEX sections of the TCO.
    """

    def __init__(
        self,
        scenario,
        extraction_window: tuple[datetime, datetime],
        scaling_window: tuple[datetime, datetime],
        database_url: Optional[str] = None,
        energy_consumption_mode: str = "simulated",
        capex_items=None,
        opex_items=None,
    ):
        """Initialise the TCO calculator and load all cost data from the DB.

        Args:
            scenario: An eflips-model Scenario object or integer scenario id.
            extraction_window: ``(start, end)`` pair used to filter which
                trips and events are included in cost calculations.
            scaling_window: ``(start, end)`` pair used to compute the
                annualisation factor applied to simulation-period values.
            database_url: SQLAlchemy database URL; falls back to
                ``DATABASE_URL`` environment variable when omitted.
            energy_consumption_mode: ``"simulated"`` (use SoC data from DB)
                or ``"constant"`` (use ``average_*_consumption`` parameters).
            capex_items: Reserved; must be ``None`` (not yet implemented).
            opex_items: Reserved; must be ``None`` (not yet implemented).
        """
        self._extraction_window = extraction_window
        self._scaling_window = scaling_window
        # create session
        with create_session(scenario, database_url) as (session, scenario):
            self.scenario = (
                session.query(Scenario).filter(Scenario.id == scenario.id).one()
            )

            vehicle_km, revenue_km = get_annual_fleet_mileage(
                session, self.scenario, extraction_window, scaling_window
            )
            self.annual_vehicle_mileage = vehicle_km
            self.annual_revenue_mileage = revenue_km
            self.energy_consumption_mode = energy_consumption_mode

            # Build const_consumption for all vehicle types
            vehicle_types = (
                session.query(VehicleType)
                .filter(VehicleType.scenario_id == self.scenario.id)
                .all()
            )
            for vt in vehicle_types:
                if vt.energy_source is None:
                    vt.energy_source = EnergySource.BATTERY_ELECTRIC
                    session.add(vt)
            session.flush()

            const_consumption: dict[VehicleType, float] = {}
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
            self.const_consumption = const_consumption

            # Mileage per vehicle type and derived mileage by energy source
            self.mileage_per_vt = get_mileage_per_vehicle_type(
                session, self.scenario, extraction_window, scaling_window
            )
            mileage_by_energy_source: dict[str, float] = {}
            for vt, mileage in self.mileage_per_vt.items():
                # TODO what if we dont have an energy source? Should we just ignore it or put it in an "unknown" category?
                key = vt.energy_source.name
                mileage_by_energy_source[key] = (
                    mileage_by_energy_source.get(key, 0.0) + mileage
                )
            self.mileage_by_energy_source = mileage_by_energy_source

            if capex_items is None:
                self._load_capex_items_from_db(session, extraction_window)

            else:
                raise NotImplementedError(
                    "Using your own list of dictonary then setting up list of capex items is not implemented yet. Please use the database to load the capex items."
                )
            if opex_items is None:
                self._load_opex_items_from_db(session, scaling_window)
            else:
                raise NotImplementedError(
                    "Using your own list of dictonary then setting up list of opex items is not implemented yet. Please use the database to load the opex items."
                )

            # initialize scenario related data
            self.project_duration = self.scenario.tco_parameters["project_duration"]
            self.interest_rate = self.scenario.tco_parameters["interest_rate"]
            self.inflation_rate = self.scenario.tco_parameters["inflation_rate"]

            self.result: Optional[TCOResult] = None
            self.tco_by_item: Optional[pd.DataFrame] = None

    def calculate(self) -> TCOResult:
        """
        Calculate the total cost of ownership.

        :return: A :class:`TCOResult` with aggregated totals and per-type specific costs
            (EUR/km). The detailed itemised breakdown is also stored in ``self.tco_by_item``.
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

        self.tco_by_item = pd.DataFrame({"Item": list_of_items, "Cost": list_of_costs})
        self.tco_by_item["type"] = self.tco_by_item["Item"].apply(lambda x: x.type.name)

        tco_by_type = {
            t: float(self.tco_by_item[self.tco_by_item["type"] == t]["Cost"].sum())
            for t in set(self.tco_by_item["type"].values)
        }

        self.result = TCOResult(
            project_duration=self.project_duration,
            annual_vehicle_mileage=self.annual_vehicle_mileage,
            annual_revenue_mileage=self.annual_revenue_mileage,
            total_capex=total_capex,
            total_opex=total_opex,
            tco_over_project_duration=tco,
            tco_by_type=tco_by_type,
        )
        return self.result

    def visualize(self):
        """
        Visualize the TCO results.
        """

        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 8))
        bottom = 0

        category_color_mapping = {
            "STAFF": "lightcoral",
            "ENERGY": "lightcyan",
            "MAINTENANCE": "lightyellow",
            "OTHER": "lightpink",
            "VEHICLE": "lightgray",
            "BATTERY": "lightgreen",
            "INFRASTRUCTURE": "skyblue",
        }

        def _fuel_tag(item_name: str) -> str:
            if "(Diesel)" in item_name:
                return "diesel"
            if "(Electric)" in item_name:
                return "electric"
            return "other"

        total_vehicle_km = self.annual_vehicle_mileage * self.project_duration
        df = self.tco_by_item.copy()
        df["Specific Cost"] = df["Cost"] / total_vehicle_km
        df["fuel"] = df["Item"].apply(lambda x: _fuel_tag(x.name))

        seen_labels = set()
        for category, color in category_color_mapping.items():
            cat_df = df[df["type"] == category]
            if cat_df.empty:
                continue
            # electric/other first (solid), diesel second (hatched)
            for fuel, hatch in [("electric", ""), ("other", ""), ("diesel", "///")]:
                subset = cat_df[cat_df["fuel"] == fuel]
                if subset.empty:
                    continue
                cost = subset["Specific Cost"].sum()
                if fuel == "diesel":
                    label = f"{category} (Diesel)"
                elif fuel == "electric":
                    label = f"{category} (Electric)"
                else:
                    label = category
                current_bar = ax.bar(
                    "Total TCO",
                    cost,
                    bottom=bottom,
                    label=label if label not in seen_labels else "_nolegend_",
                    width=0.2,
                    color=color,
                    hatch=hatch,
                    edgecolor="gray",
                )
                seen_labels.add(label)
                bottom += cost
                ax.bar_label(current_bar, label_type="center", padding=3, fmt="%.2f")

        total = self.result.tco_per_vehicle_km
        ax.text(
            0,
            total + 0.05,
            str(round(total, 2)),
            ha="center",
            va="bottom",
            fontweight="bold",
        )
        ax.set_ylabel("Specific Cost (EUR/km)")
        ax.set_xlim(left=-0.5, right=0.5)
        ax.set_title("Total Cost of Ownership by Type")
        ax.legend()
        plt.savefig("tco_by_type.png")

    def _load_capex_items_from_db(
        self,
        session,
        extraction_window: tuple[datetime, datetime],
    ) -> None:
        assets_vehicle = load_capex_items_vehicle(session, self.scenario)
        assets_battery = load_capex_items_battery(session, self.scenario)
        assets_infrastructure, total_slots = load_capex_items_infrastructure(
            session, self.scenario, extraction_window
        )

        capex_items = (
            list(assets_vehicle) + list(assets_battery) + list(assets_infrastructure)
        )
        self.capex_items = capex_items
        self.total_slots = total_slots

    def _load_opex_items_from_db(
        self,
        session,
        scaling_window: tuple[datetime, datetime],
    ) -> None:
        """Load all OPEX items from the database."""

        list_opex_items = []

        scenario_params = self.scenario.tco_parameters
        escalation = scenario_params["cost_escalation_rate"]

        electric_mileage = self.mileage_by_energy_source.get("BATTERY_ELECTRIC", 0.0)
        diesel_mileage = self.mileage_by_energy_source.get("DIESEL", 0.0)

        # Staff cost
        total_driver_hours = calculate_total_driver_hours(
            session, self.scenario, scaling_window
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
                electric_consumption = sum(
                    self.const_consumption.get(vt, 0.0)
                    * self.mileage_per_vt.get(vt, 0.0)
                    for vt in self.const_consumption
                    if vt.energy_source == EnergySource.BATTERY_ELECTRIC
                )
                diesel_consumption = sum(
                    self.const_consumption.get(vt, 0.0)
                    * self.mileage_per_vt.get(vt, 0.0)
                    for vt in self.const_consumption
                    if vt.energy_source == EnergySource.DIESEL
                )
            case "simulated":
                electric_consumption = calc_energy_consumption_simulated(
                    session, self.scenario, scaling_window
                )
                if diesel_mileage > 0:
                    logger.warning(
                        "Diesel mileage detected in 'simulated' mode. "
                        "Diesel energy consumption will be estimated from "
                        "average_diesel_consumption in VehicleType.tco_parameters."
                    )
                    diesel_consumption = sum(
                        self.const_consumption.get(vt, 0.0)
                        * self.mileage_per_vt.get(vt, 0.0)
                        for vt in self.const_consumption
                        if vt.energy_source == EnergySource.DIESEL
                    )
                else:
                    diesel_consumption = 0.0
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
