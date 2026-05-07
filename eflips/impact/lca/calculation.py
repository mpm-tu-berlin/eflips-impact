"""LCA calculation for electric and diesel bus fleets.

Implements the formulas from the design document:

- Production + End-of-Life (chassis, motor, battery)
- Use phase (electricity / diesel, maintenance)
- Charging infrastructure (depot areas, terminal stations)
- Normalisation to revenue-kilometres (Nutzwagenkilometer)
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime
from typing import Any, Optional, Union

from eflips.model import (
    Area,
    BatteryType,
    ChargeType,
    Depot,
    EnergySource,
    Scenario,
    Station,
    VehicleType,
)

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
    extract_simulation_data,
)
from eflips.impact.lca.util import DefaultImpactVector

logger = logging.getLogger(__name__)


# ===================================================================
# Pattern helpers (design doc §1.3)
# ===================================================================


def mass_based_emissions(
    mass_kg: float, emission_factors_per_kg: DefaultImpactVector
) -> DefaultImpactVector:
    """Pattern A: scale emissions linearly with mass.

    Args:
        mass_kg: Component mass in kg.
        emission_factors_per_kg: Emissions per kg.

    Returns:
        Total emissions for the given mass.
    """
    return emission_factors_per_kg * mass_kg


def amortize(
    total_emissions: DefaultImpactVector, lifetime_years: float
) -> DefaultImpactVector:
    """Pattern C: spread total emissions over operating years.

    Args:
        total_emissions: One-time production/EoL emissions.
        lifetime_years: Lifetime in years.

    Returns:
        Annual emissions.
    """
    return total_emissions / lifetime_years


def efficiency_chain(energy_kwh: float, efficiencies: list[float]) -> float:
    """Pattern D: scale energy upstream through conversion efficiencies.

    Args:
        energy_kwh: Energy at the downstream end (e.g. battery).
        efficiencies: Chain of efficiencies (each in 0..1).

    Returns:
        Energy required at the upstream end.
    """
    result = energy_kwh
    for eta in efficiencies:
        result /= eta
    return result


def normalize_to_revenue_km(
    annual_emissions: DefaultImpactVector, revenue_km_annual: float
) -> DefaultImpactVector:
    """Pattern E: convert annual emissions to per-revenue-km.

    Args:
        annual_emissions: Total annual emissions.
        revenue_km_annual: Annual revenue-kilometres.

    Returns:
        Emissions per revenue-kilometre.
    """
    return annual_emissions / revenue_km_annual


# ===================================================================
# Component calculations — Production + EoL (design doc §1.4)
# ===================================================================


def calculate_battery_mass_kg(
    vehicle_type: VehicleType, battery_type: BatteryType | None
) -> float:
    """Derive battery mass from capacity and specific mass.

    Args:
        vehicle_type: The vehicle type (provides ``battery_capacity``).
        battery_type: The battery type (provides ``specific_mass``), or
            ``None`` for ICEB.

    Returns:
        Battery mass in kg, or ``0.0`` for vehicles without a battery.
    """
    if battery_type is None:
        return 0.0
    return float(vehicle_type.battery_capacity * battery_type.specific_mass)


def calculate_chassis_emissions(
    empty_mass_kg: float,
    motor_mass_kg: float,
    battery_mass_kg: float,
    params: VehicleTypeLcaParams,
) -> DefaultImpactVector:
    """Calculate production + EoL emissions for the chassis (§1.4.2).

    Args:
        empty_mass_kg: Vehicle curb weight in kg.
        motor_mass_kg: Motor mass in kg.
        battery_mass_kg: Battery mass in kg (0 for ICEB).
        params: Vehicle type LCA parameters.

    Returns:
        Total chassis production emissions (not yet amortised).
    """
    chassis_mass = empty_mass_kg - motor_mass_kg - battery_mass_kg
    if chassis_mass <= 0:
        raise ValueError(
            f"Chassis mass is non-positive ({chassis_mass:.1f} kg). "
            f"Check empty_mass ({empty_mass_kg}), motor_mass "
            f"({motor_mass_kg}), battery_mass ({battery_mass_kg})."
        )
    return mass_based_emissions(chassis_mass, params.chassis_emission_factors_per_kg)


def calculate_motor_emissions(
    energy_source: EnergySource, params: VehicleTypeLcaParams
) -> DefaultImpactVector:
    """Calculate production + EoL emissions for the motor (§1.4.3/§1.4.4).

    Args:
        energy_source: The vehicle's energy source.
        params: Vehicle type LCA parameters.

    Returns:
        Total motor production emissions (not yet amortised).
    """
    if energy_source == EnergySource.BATTERY_ELECTRIC:
        if params.motor_emission_factors_per_kg is None:
            raise ValueError("motor_emission_factors_per_kg required for BEB")
        if params.motor_power_to_weight_ratio is None:
            raise ValueError("motor_power_to_weight_ratio required for BEB")
        motor_mass = params.motor_rated_power_kw / params.motor_power_to_weight_ratio
        return mass_based_emissions(motor_mass, params.motor_emission_factors_per_kg)
    else:
        if params.motor_emission_factors_per_unit is None:
            raise ValueError("motor_emission_factors_per_unit required for ICEB")
        return params.motor_emission_factors_per_unit


def calculate_battery_emissions(
    vehicle_type: VehicleType,
    battery_type: BatteryType | None,
) -> tuple[DefaultImpactVector, float]:
    """Calculate battery production emissions and mass (§1.4.5).

    Also checks consistency between LCA and TCO battery lifetimes.

    Args:
        vehicle_type: The vehicle type.
        battery_type: The battery type, or ``None`` for ICEB.

    Returns:
        Tuple of ``(emissions, battery_mass_kg)``.  Both are zero for
        vehicles without a battery.
    """
    if battery_type is None:
        return DefaultImpactVector.zero(), 0.0

    battery_mass = calculate_battery_mass_kg(vehicle_type, battery_type)

    if battery_type.lca_params is None:
        raise ValueError(f"BatteryType {battery_type.id} has no lca_params set.")
    bt_params = BatteryTypeLcaParams.from_dict(battery_type.lca_params)

    # Consistency check
    tco_life = None
    if battery_type.tco_parameters is not None:
        tco_life = battery_type.tco_parameters.get("useful_life")
    bt_params.check_tco_consistency(tco_life)

    emissions = mass_based_emissions(battery_mass, bt_params.emission_factors_per_kg)
    return emissions, battery_mass


def amortize_production(
    e_chassis: DefaultImpactVector,
    e_motor: DefaultImpactVector,
    e_battery: DefaultImpactVector,
    vehicle_lifetime_years: float,
    battery_lifetime_years: float | None,
    energy_source: EnergySource,
) -> DefaultImpactVector:
    """Amortise production emissions to annual values (§1.4.6).

    Args:
        e_chassis: Total chassis emissions.
        e_motor: Total motor emissions.
        e_battery: Total battery emissions.
        vehicle_lifetime_years: Motor + chassis lifetime.
        battery_lifetime_years: Battery lifetime (``None`` for ICEB).
        energy_source: The vehicle's energy source.

    Returns:
        Annual production emissions.
    """
    body = amortize(e_motor + e_chassis, vehicle_lifetime_years)
    if energy_source == EnergySource.BATTERY_ELECTRIC:
        if battery_lifetime_years is None:
            raise ValueError("battery_lifetime_years required for BEB")
        return amortize(e_battery, battery_lifetime_years) + body
    return body


# ===================================================================
# Use phase (design doc §1.5)
# ===================================================================


def calculate_energy_emissions_beb(
    annual_energy_kwh: float,
    charging_efficiency: float,
    params: VehicleTypeLcaParams,
) -> DefaultImpactVector:
    """Calculate electricity use-phase emissions for BEB (§1.5.1).

    Args:
        annual_energy_kwh: Annual energy drawn from the battery in kWh
            (fleet aggregate for all ready vehicles of this type).
        charging_efficiency: Battery charging efficiency (0..1).
        params: Vehicle type LCA parameters.

    Returns:
        Annual electricity emissions (fleet aggregate).
    """
    if params.efficiency_mv_to_lv is None:
        raise ValueError("efficiency_mv_to_lv required for BEB")
    if params.efficiency_lv_ac_to_dc is None:
        raise ValueError("efficiency_lv_ac_to_dc required for BEB")
    if params.electricity_emission_factors_per_kwh is None:
        raise ValueError("electricity_emission_factors_per_kwh required for BEB")

    grid_energy = efficiency_chain(
        annual_energy_kwh,
        [
            params.efficiency_mv_to_lv,
            params.efficiency_lv_ac_to_dc,
            charging_efficiency,
        ],
    )
    return params.electricity_emission_factors_per_kwh * grid_energy


def calculate_energy_emissions_diesel(
    annual_diesel_kg: float, params: VehicleTypeLcaParams
) -> DefaultImpactVector:
    """Calculate diesel use-phase emissions for ICEB (§1.5.2).

    Args:
        annual_diesel_kg: Annual diesel consumption in kg (fleet aggregate).
        params: Vehicle type LCA parameters.

    Returns:
        Annual diesel emissions (fleet aggregate).
    """
    if params.diesel_emission_factors_per_kg is None:
        raise ValueError("diesel_emission_factors_per_kg required for ICEB")
    return params.diesel_emission_factors_per_kg * annual_diesel_kg


# ===================================================================
# Charging infrastructure (design doc §1.6)
# ===================================================================


def power_scaled_emissions(
    ref_emission: DefaultImpactVector,
    peak_power_kw: float,
    ref_power_kw: float,
    exponent: float = 0.8,
) -> DefaultImpactVector:
    """Scale a reference-power LCA emission vector to an actual peak power.

    Applies the six-tenths-rule generalisation:
    ``impact_real = impact_ref * (peak_power / ref_power) ^ exponent``.

    Args:
        ref_emission: Emissions for the component at *ref_power_kw*.
        peak_power_kw: Actual peak power demand in kW.
        ref_power_kw: Reference power for which *ref_emission* was computed
            in kW.
        exponent: Scaling exponent (default ``0.8``).

    Returns:
        Scaled emissions for the actual peak power.
    """
    return ref_emission * float((peak_power_kw / ref_power_kw) ** exponent)


def _get_cpt_params(entity: Any, entity_label: str) -> ChargingPointTypeLcaParams:
    """Load and validate ChargingPointType LCA params from an entity.

    Args:
        entity: An ``Area`` or ``Station`` ORM object with a
            ``charging_point_type`` relationship.
        entity_label: Human-readable label for error messages.

    Returns:
        Deserialised ``ChargingPointTypeLcaParams``.

    Raises:
        ValueError: If the charging point type or its LCA params are
            missing.
    """
    cpt = entity.charging_point_type
    if cpt is None:
        raise ValueError(f"{entity_label} has no charging_point_type assigned.")
    if cpt.lca_params is None:
        raise ValueError(
            f"ChargingPointType {cpt.id} for {entity_label} has no " f"lca_params set."
        )
    return ChargingPointTypeLcaParams.from_dict(cpt.lca_params)


def calculate_depot_area_emissions(
    area: Area,
    area_sim: AreaSimData,
) -> DefaultImpactVector:
    """Calculate annual infrastructure emissions for one depot area (§1.6.2).

    Issues oversizing warnings when the peak vehicle count is
    significantly below the area capacity.

    Args:
        area: The depot ``Area`` ORM object.
        area_sim: Extracted simulation data for this area.

    Returns:
        Annual infrastructure emissions for this area.
    """
    cpt_params = _get_cpt_params(area, f"Area {area.id}")

    # Oversizing check
    capacity = area.capacity
    peak = area_sim.peak_simultaneous_vehicles
    if peak < 0.80 * capacity:
        warnings.warn(
            f"Area {area.id}: peak vehicles ({peak}) is significantly below "
            f"capacity ({capacity}). Infrastructure may be oversized.",
            stacklevel=2,
        )
    elif peak < capacity:
        logger.warning(
            "Area %d: peak vehicles (%d) is mildly below capacity (%d).",
            area.id,
            peak,
            capacity,
        )

    peak_power = area_sim.peak_charging_power_kw

    # TODO: better to use peak for research purpose and n_plugs for real-world estimation? Need to align

    n_plugs = capacity
    # n_plugs = peak
    e_power_units = power_scaled_emissions(
        cpt_params.power_unit_emission,
        peak_power,
        cpt_params.power_unit_rated_power_kw,
    )
    e_transformers = power_scaled_emissions(
        cpt_params.transformer_emissions,
        peak_power,
        cpt_params.transformer_ref_power_kw,
    )
    e_total = (
        e_power_units
        + cpt_params.user_unit_emission * n_plugs
        + e_transformers
        + cpt_params.control_unit_emissions
    )
    return amortize(e_total, cpt_params.infrastructure_lifetime_years)


def calculate_terminal_station_emissions(
    station: Station,
    station_sim: StationSimData,
) -> DefaultImpactVector:
    """Calculate annual infrastructure emissions for a terminal station (§1.6.3).

    Args:
        station: The ``Station`` ORM object.
        station_sim: Extracted simulation data for this station.

    Returns:
        Annual infrastructure emissions for this station.
    """
    cpt_params = _get_cpt_params(station, f"Station {station.id}")

    # Oversizing check
    capacity = station.amount_charging_places
    peak = station_sim.peak_simultaneous_vehicles
    if capacity is not None and peak < 0.80 * capacity:
        warnings.warn(
            f"Station {station.id}: peak vehicles ({peak}) is significantly "
            f"below capacity ({capacity}). Infrastructure may be oversized.",
            stacklevel=2,
        )
    elif capacity is not None and peak < capacity:
        logger.warning(
            "Station %d: peak vehicles (%d) is mildly below capacity (%d).",
            station.id,
            peak,
            capacity,
        )

    peak_power = station_sim.peak_charging_power_kw


    n_plugs = capacity

    # TODO: better to use peak for research purpose and n_plugs for real-world estimation? Need to align
    # n_plugs = peak

    e_power_units = power_scaled_emissions(
        cpt_params.power_unit_emission,
        peak_power,
        cpt_params.power_unit_rated_power_kw,
    )
    e_transformers = power_scaled_emissions(
        cpt_params.transformer_emissions,
        peak_power,
        cpt_params.transformer_ref_power_kw,
    )

    # Concrete foundation (terminal only)
    e_concrete_per_plug = (
        cpt_params.concrete_emissions_per_m3 * cpt_params.foundation_volume_per_point_m3
    )

    e_total = (
        e_power_units
        + cpt_params.user_unit_emission * n_plugs
        + e_transformers
        + e_concrete_per_plug * n_plugs
        + cpt_params.control_unit_emissions
    )
    return amortize(e_total, cpt_params.infrastructure_lifetime_years)


# ===================================================================
# Main orchestrator (design doc §2.6)
# ===================================================================


def calculate_lca(
    scenario: Union[Scenario, int, Any],
    extraction_window: Optional[tuple[datetime, datetime]] = None,
    scaling_window: Optional[tuple[datetime, datetime]] = None,
    eta_avail: float = 0.9,
    database_url: Optional[str] = None,
) -> LcaResult:
    """Calculate the life-cycle assessment for a scenario.

    Takes an eflips-model scenario with populated ``lca_params`` on all
    relevant entities and returns per-revenue-km emissions broken down
    by contributor and vehicle type.

    Args:
        scenario: A :class:`~eflips.model.Scenario` instance, an ``int``
            scenario id, or any object with an ``id`` attribute.
        extraction_window: ``(start, end)`` pair used to filter which trips
            and events are included in the query.  If ``None``, derived
            automatically via
            :func:`~eflips.impact.utils.extraction.get_extraction_window`.
        scaling_window: ``(start, end)`` pair used to compute the
            annualisation factor.  If ``None``, derived automatically via
            :func:`~eflips.impact.utils.extraction.get_scaling_window`.
        eta_avail: Technical availability factor (default ``0.9``).
        database_url: Database URL; falls back to ``$DATABASE_URL`` when
            ``scenario`` is not already bound to a session.

    Returns:
        An ``LcaResult`` with per-revenue-km emissions.

    Raises:
        ValueError: If ``lca_params`` are missing on required entities.
    """
    from eflips.impact.utils.extraction import get_extraction_window, get_scaling_window
    from eflips.impact.utils.session import create_session

    with create_session(scenario, database_url) as (session, scenario_obj):
        scenario_id = int(scenario_obj.id)

        ew = (
            extraction_window
            if extraction_window is not None
            else get_extraction_window(session, scenario_id)
        )
        sw = (
            scaling_window
            if scaling_window is not None
            else get_scaling_window(session, scenario_id)
        )

        # 1. Extract simulation data
        sim_data = extract_simulation_data(session, scenario_id, ew, sw, eta_avail)

        # 2. Query vehicle types
        vehicle_types = (
            session.query(VehicleType)
            .filter(VehicleType.scenario_id == scenario_id)
            .all()
        )

        production_results: dict[int, DefaultImpactVector] = {}
        use_results: dict[int, DefaultImpactVector] = {}
        revenue_km_per_type: dict[int, float] = {}
        total_revenue_km = 0.0
        # Fleet-level unnormalized annual emissions — accumulated across all types
        # for the shared-denominator total (design doc §1.7).
        e_prod_annual_fleet = DefaultImpactVector.zero()
        e_use_annual_fleet = DefaultImpactVector.zero()

        for vtype in vehicle_types:
            vtype_id = int(vtype.id)
            vtype_sim = sim_data.vehicle_type_data.get(vtype_id)
            if vtype_sim is None:
                logger.warning(
                    "VehicleType %d has no simulation data, skipping.", vtype_id
                )
                continue

            if vtype.lca_params is None:
                raise ValueError(f"VehicleType {vtype_id} has no lca_params set.")
            params = VehicleTypeLcaParams.from_dict(
                vtype.lca_params, energy_source=vtype.energy_source
            )

            # TODO potential improvement

            battery_type: BatteryType | None = vtype.battery_type

            if vtype.energy_source == EnergySource.BATTERY_ELECTRIC and battery_type is None:
                warnings.warn(
                    f"VehicleType {vtype_id} is BEB but has no battery_type assigned. "
                    f"Assuming zero battery mass and emissions.",
                    stacklevel=2,
                )

            n_ready = vtype_sim.n_ready
            n_total = n_ready / sim_data.eta_avail
            revenue_km = vtype_sim.annual_revenue_kilometers
            vehicle_km = vtype_sim.annual_vehicle_kilometers
            revenue_km_per_type[vtype_id] = revenue_km
            total_revenue_km += revenue_km

            if revenue_km <= 0:
                logger.warning("VehicleType %d has zero revenue-km, skipping.", vtype_id)
                continue

            # --- Production + EoL ---
            e_battery, battery_mass = calculate_battery_emissions(vtype, battery_type)

            if vtype.energy_source == EnergySource.BATTERY_ELECTRIC:
                if params.motor_power_to_weight_ratio is None:
                    raise ValueError(
                        f"VehicleType {vtype_id}: motor_power_to_weight_ratio required for BEB"
                    )
                motor_mass_for_chassis = (
                    params.motor_rated_power_kw / params.motor_power_to_weight_ratio
                )
            else:
                if params.motor_mass_kg is None:
                    raise ValueError(
                        f"VehicleType {vtype_id}: motor_mass_kg required for DIESEL"
                    )
                motor_mass_for_chassis = params.motor_mass_kg

            e_chassis = calculate_chassis_emissions(
                float(vtype.empty_mass),
                motor_mass_for_chassis,
                battery_mass,
                params,
            )
            e_motor = calculate_motor_emissions(vtype.energy_source, params)

            bt_lifetime: float | None = None
            if battery_type is not None and battery_type.lca_params is not None:
                bt_params = BatteryTypeLcaParams.from_dict(battery_type.lca_params)
                bt_lifetime = bt_params.battery_lifetime_years

            e_prod_annual = amortize_production(
                e_chassis,
                e_motor,
                e_battery,
                params.vehicle_lifetime_years,
                bt_lifetime,
                vtype.energy_source,
            )
            e_prod_fleet = e_prod_annual * n_total
            production_results[vtype_id] = normalize_to_revenue_km(
                e_prod_fleet, revenue_km
            )
            e_prod_annual_fleet = e_prod_annual_fleet + e_prod_fleet

            # --- Use phase ---
            # Energy emissions (fleet aggregate for all ready vehicles)
            if vtype.energy_source == EnergySource.BATTERY_ELECTRIC:
                annual_energy_kwh = params.average_consumption_kwh_per_km * vehicle_km
                e_energy = calculate_energy_emissions_beb(
                    annual_energy_kwh,
                    float(vtype.charging_efficiency),
                    params,
                )
            elif vtype.energy_source == EnergySource.DIESEL:
                if params.diesel_consumption_kg_per_km is None:
                    raise ValueError(
                        f"VehicleType {vtype_id}: diesel_consumption_kg_per_km "
                        f"required for DIESEL"
                    )
                annual_diesel_kg = params.diesel_consumption_kg_per_km * vehicle_km
                e_energy = calculate_energy_emissions_diesel(annual_diesel_kg, params)
            else:
                raise ValueError(f"Unsupported energy source: {vtype.energy_source}")

            # Maintenance (per vehicle × n_total)
            e_maint_per_vehicle = params.maintenance_per_year[vtype.energy_source]

            e_use_fleet = e_energy + e_maint_per_vehicle * n_total
            use_results[vtype_id] = normalize_to_revenue_km(e_use_fleet, revenue_km)
            e_use_annual_fleet = e_use_annual_fleet + e_use_fleet

        # 3. Charging infrastructure (BEB only)
        e_infra_annual = DefaultImpactVector.zero()

        # Depot areas
        areas = (
            session.query(Area)
            .join(Depot, Area.depot_id == Depot.id)
            .join(VehicleType, Area.vehicle_type_id == VehicleType.id)
            .filter(Area.scenario_id == scenario_id)
            .filter(VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC)
            .all()
        )
        for area in areas:
            area_sim = sim_data.area_data.get(int(area.id))
            if area_sim is None:
                logger.warning(
                    "Area %d has no simulation data, skipping infra calc.",
                    area.id,
                )
                continue
            e_infra_annual = e_infra_annual + calculate_depot_area_emissions(
                area, area_sim
            )

        # Terminal stations
        stations = (
            session.query(Station)
            .outerjoin(Depot, Depot.station_id == Station.id)
            .filter(Station.scenario_id == scenario_id)
            .filter(Station.is_electrified.is_(True))
            .filter(Depot.id.is_(None))
            .all()
        )
        for station in stations:
            station_sim = sim_data.station_data.get(int(station.id))
            if station_sim is None:
                logger.warning(
                    "Station %d has no simulation data, skipping infra calc.",
                    station.id,
                )
                continue
            e_infra_annual = e_infra_annual + calculate_terminal_station_emissions(
                station, station_sim
            )

        # Normalise infrastructure to per-revenue-km
        if total_revenue_km > 0:
            e_infra_per_rkm = normalize_to_revenue_km(e_infra_annual, total_revenue_km)
        else:
            e_infra_per_rkm = DefaultImpactVector.zero()

        # 4. Compute fleet-wide total with shared denominator (design doc §1.7)
        if total_revenue_km > 0:
            e_total = (
                normalize_to_revenue_km(
                    e_prod_annual_fleet + e_use_annual_fleet, total_revenue_km
                )
                + e_infra_per_rkm
            )
        else:
            e_total = DefaultImpactVector.zero()

        return LcaResult(
            production=production_results,
            use_phase=use_results,
            infrastructure=e_infra_per_rkm,
            total=e_total,
            revenue_km=revenue_km_per_type,
        )
