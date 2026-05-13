"""eflips-lca: Life Cycle Assessment for eFLIPS bus simulations.

Calculates per-revenue-km environmental impacts of electric (BEB) and
diesel (ICEB) bus fleets across their full life cycle, following
ISO 14040/14044.
"""

from eflips.impact.lca.calculation import calculate_lca
from eflips.impact.lca.dataclasses import (
    BatteryTypeLCAParams,
    ChargingPointTypeLCAParams,
    ItemType,
    LCAItem,
    LCAResult,
    LCAScope,
    VehicleTypeLCAParams,
)
from eflips.impact.utils.extraction import (
    AreaSimData,
    ScenarioSimData,
    StationSimData,
    VehicleTypeSimData,
    extract_simulation_data,
)
from eflips.impact.lca.open_lca_data import (
    ChargingPointTypeOverrides,
    OpenLCAData,
    VehicleTypeOverrides,
    YearSeries,
    init_lca_parameters,
    populate_lca_parameters_from_data,
)
from eflips.impact.lca.util import DefaultImpactVector, ImpactVector

__all__ = [
    "ImpactVector",
    "DefaultImpactVector",
    "VehicleTypeLCAParams",
    "BatteryTypeLCAParams",
    "ChargingPointTypeLCAParams",
    "LCAItem",
    "LCAResult",
    "LCAScope",
    "ItemType",
    "ScenarioSimData",
    "VehicleTypeSimData",
    "AreaSimData",
    "StationSimData",
    "extract_simulation_data",
    "calculate_lca",
    "OpenLCAData",
    "YearSeries",
    "VehicleTypeOverrides",
    "ChargingPointTypeOverrides",
    "init_lca_parameters",
    "populate_lca_parameters_from_data",
]
