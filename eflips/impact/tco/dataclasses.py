"""Dataclass definitions for TCO parameters and results."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, Optional, Union, List

from eflips.impact.tco.cost_items import CapexItemType, OpexItemType


@dataclass
class VehicleTypeTCOParameter:
    """TCO parameters for a vehicle type."""

    name_short: str
    useful_life: int
    procurement_cost: float
    cost_escalation: float
    name: Optional[str] = None
    average_electricity_consumption: Optional[float] = None
    average_diesel_consumption: Optional[float] = None

    def __post_init__(self):
        if (self.average_electricity_consumption is None) == (
            self.average_diesel_consumption is None
        ):
            raise ValueError(
                "Exactly one of average_electricity_consumption or average_diesel_consumption must be set."
            )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "useful_life": self.useful_life,
            "procurement_cost": self.procurement_cost,
            "cost_escalation": self.cost_escalation,
        }
        if self.average_electricity_consumption is not None:
            d["average_electricity_consumption"] = self.average_electricity_consumption
        else:
            d["average_diesel_consumption"] = self.average_diesel_consumption
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VehicleTypeTCOParameter":
        return cls(
            name_short=d["name_short"],
            useful_life=int(d["useful_life"]),
            procurement_cost=float(d["procurement_cost"]),
            cost_escalation=float(d["cost_escalation"]),
            name=d.get("name"),
            average_electricity_consumption=d.get("average_electricity_consumption"),
            average_diesel_consumption=d.get("average_diesel_consumption"),
        )


@dataclass
class BatteryTypeTCOParameter:
    """TCO parameters for a battery type.

    Used to write ``BatteryType.tco_parameters`` on rows that already exist in
    the database. BatteryType row creation has moved to
    :func:`eflips.impact.utils.fleet_init.init_fleet`; ``specific_mass`` and
    ``chemistry`` are no longer fields here.
    """

    vehicle_name_short: str
    procurement_cost: float
    useful_life: int
    cost_escalation: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procurement_cost": self.procurement_cost,
            "useful_life": self.useful_life,
            "cost_escalation": self.cost_escalation,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BatteryTypeTCOParameter":
        return cls(
            vehicle_name_short=d["vehicle_name_short"],
            procurement_cost=float(d["procurement_cost"]),
            useful_life=int(d["useful_life"]),
            cost_escalation=float(d["cost_escalation"]),
        )


@dataclass
class ChargingPointTypeTCOParameter:
    """TCO parameters for a charging point type.

    Used to write ``ChargingPointType.tco_parameters`` on rows that already
    exist in the database. ChargingPointType row creation has moved to
    :func:`eflips.impact.utils.fleet_init.init_fleet`; ``name`` is no longer
    a field here.
    """

    type: str
    procurement_cost: float
    useful_life: int
    cost_escalation: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procurement_cost": self.procurement_cost,
            "useful_life": self.useful_life,
            "cost_escalation": self.cost_escalation,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChargingPointTypeTCOParameter":
        return cls(
            type=d["type"],
            procurement_cost=float(d["procurement_cost"]),
            useful_life=int(d["useful_life"]),
            cost_escalation=float(d["cost_escalation"]),
        )


@dataclass
class ChargingInfrastructureTCOParameter:
    """TCO parameters for charging infrastructure."""

    type: str
    procurement_cost: float
    useful_life: int
    cost_escalation: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procurement_cost": self.procurement_cost,
            "useful_life": self.useful_life,
            "cost_escalation": self.cost_escalation,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChargingInfrastructureTCOParameter":
        return cls(
            type=d["type"],
            procurement_cost=float(d["procurement_cost"]),
            useful_life=int(d["useful_life"]),
            cost_escalation=float(d["cost_escalation"]),
        )


@dataclass
class ScenarioTCOParameter:
    """TCO parameters for a scenario.

    Format follows eflips-opt transition planning convention.

    Required fields:
    - project_duration, interest_rate, inflation_rate: financial framing
    - staff_cost: driver cost per hour
    - fuel_cost: dict with "diesel" and "electricity" keys (EUR/l and EUR/kWh)
    - vehicle_maint_cost: dict with "diesel" and "electricity" keys (EUR/km)
    - infra_maint_cost: annual infrastructure maintenance per charging point
    - cost_escalation_rate: dict with "general", "staff", "diesel", "electricity",
      "insurance" keys (annual rate)
    - insurance: annual insurance per vehicle
    - taxes: annual taxes per vehicle

    Optional fields (used by transition planner):
    - annual_budget_limit: max annual investment budget
    - depot_time_plan: dict mapping depot name to electrification year
    - current_year: base year for the planning horizon
    - max_station_construction_per_year: max new stations per year
    """

    project_duration: int
    interest_rate: float
    inflation_rate: float
    staff_cost: float
    fuel_cost: Dict[str, float]
    vehicle_maint_cost: Dict[str, float]
    infra_maint_cost: float
    cost_escalation_rate: Dict[str, float]
    insurance: float
    taxes: float
    eta_avail: float = 0.9

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Remove None optional fields so they don't clutter the stored dict
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScenarioTCOParameter":
        return cls(**d)


@dataclass
class TCOResult:
    """Aggregated TCO results for a scenario, produced by :class:`TCOCalculator.calculate`."""

    project_duration: int
    """Project duration in years."""

    tco_by_type: Dict[Union[CapexItemType, OpexItemType], float]
    """Total TCO (EUR, NPV) over the project duration, broken down by cost category."""

    annual_revenue_km: float
    """Annual fleet revenue-km total (km/year)."""

    annual_vehicle_km: float
    """Annual fleet vehicle-km total (all trips, km/year)."""

    @property
    def total_capex(self) -> float:
        """Total CAPEX (NPV) over the project duration in EUR."""
        return sum(v for k, v in self.tco_by_type.items() if isinstance(k, CapexItemType))

    @property
    def total_opex(self) -> float:
        """Total OPEX (NPV) over the project duration in EUR."""
        return sum(v for k, v in self.tco_by_type.items() if isinstance(k, OpexItemType))

    @property
    def tco_over_project_duration(self) -> float:
        """Total TCO (CAPEX + OPEX, NPV) in EUR."""
        return sum(self.tco_by_type.values())

    @property
    def tco_per_vehicle_km(self) -> float:
        """Specific TCO in EUR per total vehicle-km."""
        return self.tco_over_project_duration / (self.annual_vehicle_km * self.project_duration)

    @property
    def tco_per_revenue_km(self) -> float:
        """Specific TCO in EUR per revenue-km."""
        return self.tco_over_project_duration / (self.annual_revenue_km * self.project_duration)

    @property
    def tco_by_type_per_vehicle_km(self) -> Dict[Union[CapexItemType, OpexItemType], float]:
        """TCO per vehicle-km by cost category (EUR/km).

        :returns: Dict mapping each cost category to EUR per total vehicle-km.
        """
        total_km = self.annual_vehicle_km * self.project_duration
        return {k: v / total_km for k, v in self.tco_by_type.items()}

    @property
    def tco_by_type_per_revenue_km(self) -> Dict[Union[CapexItemType, OpexItemType], float]:
        """TCO per revenue-km by cost category (EUR/km).

        :returns: Dict mapping each cost category to EUR per revenue-km.
        """
        total_km = self.annual_revenue_km * self.project_duration
        return {k: v / total_km for k, v in self.tco_by_type.items()}

    def plot(
        self,
        use_revenue_km: bool = True,
        save_path: str = "tco_by_type.png",
    ) -> None:
        """Plot a stacked bar chart of TCO by cost category.

        :param use_revenue_km: If ``True``, normalise by revenue-km; otherwise
            by vehicle-km.
        :param save_path: File path for the saved figure.
        """
        import matplotlib.pyplot as plt

        color_map: Dict[Union[CapexItemType, OpexItemType], str] = {
            OpexItemType.STAFF: "lightcoral",
            OpexItemType.ENERGY: "lightcyan",
            OpexItemType.MAINTENANCE: "lightyellow",
            OpexItemType.OTHER: "lightpink",
            CapexItemType.VEHICLE: "lightgray",
            CapexItemType.BATTERY: "lightgreen",
            CapexItemType.INFRASTRUCTURE: "skyblue",
        }

        per_km = (
            self.tco_by_type_per_revenue_km
            if use_revenue_km
            else self.tco_by_type_per_vehicle_km
        )
        total = self.tco_per_revenue_km if use_revenue_km else self.tco_per_vehicle_km
        km_label = "revenue-km" if use_revenue_km else "vehicle-km"

        fig, ax = plt.subplots(figsize=(6, 8))
        bottom = 0.0

        for category, color in color_map.items():
            cost = per_km.get(category, 0.0)
            if cost == 0.0:
                continue
            bar = ax.bar(
                "Total TCO",
                cost,
                bottom=bottom,
                label=category.name,
                width=0.2,
                color=color,
                edgecolor="gray",
            )
            ax.bar_label(bar, label_type="center", padding=3, fmt="%.2f")
            bottom += cost

        ax.text(
            0,
            total + 0.05,
            str(round(total, 2)),
            ha="center",
            va="bottom",
            fontweight="bold",
        )
        ax.set_ylabel(f"Specific Cost (EUR/{km_label})")
        ax.set_xlim(left=-0.5, right=0.5)
        ax.set_title("Total Cost of Ownership by Type")
        ax.legend()
        plt.savefig(save_path)
        plt.close(fig)


@dataclass
class TcoParamSet:
    """All TCO parameters for a scenario, loadable from a JSON file.

    Bundles the five parameter lists consumed by :func:`init_tco_parameters`.
    Not part of the public API — use :func:`init_tco_parameters_from_json`
    unless you need to inspect or modify parameters before writing to the DB.

    :ivar scenario: Scenario-level financial parameters.
    :ivar vehicle_types: Per-vehicle-type parameters.
    :ivar battery_types: Per-battery-type parameters.
    :ivar charging_point_types: Per-charging-point-type parameters.
    :ivar charging_infrastructure: Per-charging-infrastructure parameters.
    """

    scenario: ScenarioTCOParameter
    vehicle_types: List[VehicleTypeTCOParameter]
    battery_types: List[BatteryTypeTCOParameter]
    charging_point_types: List[ChargingPointTypeTCOParameter]
    charging_infrastructure: List[ChargingInfrastructureTCOParameter]

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "TcoParamSet":
        """Load a ``TcoParamSet`` from a JSON file.

        :param path: Path to the JSON file.
        :returns: A ``TcoParamSet`` instance.
        """
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: Dict[str, Any]) -> "TcoParamSet":
        """Construct a ``TcoParamSet`` from a parsed JSON dict.

        :param raw: Dict with keys ``scenario``, ``vehicle_types``,
            ``battery_types``, ``charging_point_types``,
            ``charging_infrastructure``.
        :returns: A ``TcoParamSet`` instance.
        """
        return cls(
            scenario=ScenarioTCOParameter.from_dict(raw["scenario"]),
            vehicle_types=[
                VehicleTypeTCOParameter.from_dict(d)
                for d in raw.get("vehicle_types", [])
            ],
            battery_types=[
                BatteryTypeTCOParameter.from_dict(d)
                for d in raw.get("battery_types", [])
            ],
            charging_point_types=[
                ChargingPointTypeTCOParameter.from_dict(d)
                for d in raw.get("charging_point_types", [])
            ],
            charging_infrastructure=[
                ChargingInfrastructureTCOParameter.from_dict(d)
                for d in raw.get("charging_infrastructure", [])
            ],
        )
