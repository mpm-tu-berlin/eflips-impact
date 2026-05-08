"""Dataclass definitions for TCO parameters and results."""

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Any, Optional, Union, List


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

    annual_vehicle_mileage: float
    """Annual total fleet mileage (all trips) in km/year."""

    annual_revenue_mileage: float
    """Annual revenue (passenger-trip) mileage in km/year."""

    total_capex: float
    """Total CAPEX (net present value) over the project duration in EUR."""

    total_opex: float
    """Total OPEX (net present value) over the project duration in EUR."""

    tco_over_project_duration: float
    """Total TCO (CAPEX + OPEX, net present value) in EUR."""

    tco_by_type: Dict[str, float]
    """Total TCO (EUR) broken down by cost category (e.g. VEHICLE, ENERGY, STAFF)."""

    @property
    def tco_per_vehicle_km(self) -> float:
        """Specific TCO in EUR per total vehicle-km."""
        return self.tco_over_project_duration / (
            self.annual_vehicle_mileage * self.project_duration
        )

    @property
    def tco_per_revenue_km(self) -> float:
        """Specific TCO in EUR per revenue-km."""
        return self.tco_over_project_duration / (
            self.annual_revenue_mileage * self.project_duration
        )

    def tco_by_type_per_km(self, use_revenue_km: bool = False) -> Dict[str, float]:
        """Return tco_by_type as EUR/km.

        :param use_revenue_km: If True, divide by revenue-km; otherwise by vehicle-km.
        """
        mileage = (
            self.annual_revenue_mileage
            if use_revenue_km
            else self.annual_vehicle_mileage
        )
        total_km = mileage * self.project_duration
        return {k: v / total_km for k, v in self.tco_by_type.items()}


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
