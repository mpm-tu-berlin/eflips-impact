"""eflips-lca: Life Cycle Assessment for eFLIPS bus simulations.

Calculates per-revenue-km environmental impacts of electric (BEB) and
diesel (ICEB) bus fleets across their full life cycle, following
ISO 14040/14044.
"""

from eflips.impact.lca.calculation import calculate_lca
from eflips.impact.lca.dataclasses import (
    BatteryTypeLcaParams,
    ChargingPointTypeLcaParams,
    LcaResult,
    VehicleTypeLcaParams,
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
    OpenLcaData,
    VehicleTypeOverrides,
    YearSeries,
    init_lca_params,
    populate_lca_params_from_data,
)
from eflips.impact.lca.util import DefaultImpactVector, ImpactVector

__all__ = [
    "ImpactVector",
    "DefaultImpactVector",
    "VehicleTypeLcaParams",
    "BatteryTypeLcaParams",
    "ChargingPointTypeLcaParams",
    "LcaResult",
    "ScenarioSimData",
    "VehicleTypeSimData",
    "AreaSimData",
    "StationSimData",
    "extract_simulation_data",
    "calculate_lca",
    "OpenLcaData",
    "YearSeries",
    "VehicleTypeOverrides",
    "ChargingPointTypeOverrides",
    "init_lca_params",
    "populate_lca_params_from_data",
]
