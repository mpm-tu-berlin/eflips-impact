"""LCA parameter dataclasses and result container.

Defines the typed structures stored in ``lca_params`` JSONB columns on
eflips-model entities, plus the ``LcaResult`` output of the calculation.
"""

from __future__ import annotations

import warnings
from dataclasses import InitVar, dataclass, field
from typing import Any
from enum import Enum, auto

from eflips.model import EnergySource

from eflips.impact.lca.util import DefaultImpactVector

# ---------------------------------------------------------------------------
# Helpers for (de)serialising EnergySource-keyed dicts and nested vectors
# ---------------------------------------------------------------------------


def _serialise_maintenance(
    data: dict[EnergySource, DefaultImpactVector],
) -> dict[str, dict[str, float]]:
    """Convert an ``EnergySource``-keyed dict to a JSON-safe form.

    :param data: Maintenance emissions keyed by ``EnergySource``.
    :returns: A dict with string keys (enum member names) and nested dicts.
    """
    return {k.name: v.to_dict() for k, v in data.items()}


def _deserialise_maintenance(
    raw: dict[str, Any],
) -> dict[EnergySource, DefaultImpactVector]:
    """Reconstruct an ``EnergySource``-keyed dict from JSON.

    :param raw: A dict with string keys and nested impact-vector dicts.
    :returns: A dict keyed by ``EnergySource`` enum members.
    """
    return {EnergySource[k]: DefaultImpactVector.from_dict(v) for k, v in raw.items()}


def _iv_or_none_to_dict(
    iv: DefaultImpactVector | None,
) -> dict[str, float] | None:
    """Serialize an optional ImpactVector.

    :param iv: An ImpactVector or ``None``.
    :returns: A dict or ``None``.
    """
    return iv.to_dict() if iv is not None else None


def _iv_or_none_from_dict(
    raw: dict[str, Any] | None,
) -> DefaultImpactVector | None:
    """Deserialize an optional ImpactVector.

    :param raw: A dict or ``None``.
    :returns: A ``DefaultImpactVector`` or ``None``.
    """
    return DefaultImpactVector.from_dict(raw) if raw is not None else None


# ---------------------------------------------------------------------------
# VehicleTypeLcaParams
# ---------------------------------------------------------------------------


@dataclass
class VehicleTypeLcaParams:
    """LCA parameters stored on ``VehicleType.lca_params``.

    Attributes are grouped by lifecycle phase.  Fields that are irrelevant
    for a given ``EnergySource`` must be ``None`` (enforced by
    ``__post_init__`` when *energy_source* is supplied).
    """

    # --- Production: Chassis ---
    chassis_emission_factors_per_kg: DefaultImpactVector
    """Prod+EoL emissions per kg of chassis (openLCA)."""

    # --- Production: Motor (electric) ---
    motor_rated_power_kw: float
    """Rated motor power in kW."""

    motor_emission_factors_per_kg: DefaultImpactVector | None
    """Prod+EoL emissions per kg of electric motor. ``None`` for diesel."""

    motor_power_to_weight_ratio: float | None
    """kW/kg power-to-weight ratio for deriving motor mass. ``None`` for diesel."""

    # --- Production: Motor (diesel / shared) ---
    motor_emission_factors_per_unit: DefaultImpactVector | None
    """Prod+EoL emissions for one complete diesel motor. ``None`` for electric."""

    motor_mass_kg: float | None
    """Diesel motor mass in kg (given).  ``None`` for BEB (derived at calc time
    from ``motor_rated_power_kw / motor_power_to_weight_ratio``)."""

    # --- Production: Lifetime ---
    vehicle_lifetime_years: float
    """Motor + chassis lifetime for amortisation (default 12)."""

    # --- Use phase: Electricity (BEB) ---
    efficiency_mv_to_lv: float | None
    """MV→LV transformer efficiency (default 0.99). ``None`` for diesel."""

    efficiency_lv_ac_to_dc: float | None
    """AC/DC rectification efficiency (default 0.95). ``None`` for diesel."""

    electricity_emission_factors_per_kwh: DefaultImpactVector | None
    """Emissions per kWh of grid electricity. ``None`` for diesel."""

    # --- Use phase: Diesel (ICEB) ---
    diesel_emission_factors_per_kg: DefaultImpactVector | None
    """Well-to-wheel emissions per kg diesel (production + combustion).
    ``None`` for electric."""

    # --- Use phase: Consumption ---
    average_consumption_kwh_per_km: float
    """Average energy consumption in kWh/km used for LCA.

    May differ from the worst-case simulation value.  Cross-checked
    against ``tco_parameters`` when available.
    """

    diesel_consumption_kg_per_km: float | None
    """Per-km diesel consumption in kg. ``None`` for BEB."""

    # --- Use phase: Maintenance ---
    maintenance_per_year: dict[EnergySource, DefaultImpactVector]
    """Annual maintenance emissions per vehicle, keyed by energy source."""

    # --- Validation-only (not stored) ---
    energy_source: InitVar[EnergySource | None] = None

    def __post_init__(self, energy_source: EnergySource | None) -> None:
        """Validate field consistency with the vehicle's energy source.

        :param energy_source: The vehicle type's energy source, used for
            cross-field validation.  ``None`` skips validation (e.g.
            during raw deserialisation).
        """
        if energy_source is None:
            return

        if energy_source == EnergySource.BATTERY_ELECTRIC:
            if self.motor_emission_factors_per_unit is not None:
                raise ValueError(
                    "motor_emission_factors_per_unit must be None for BATTERY_ELECTRIC"
                )
            if self.motor_mass_kg is not None:
                raise ValueError(
                    "motor_mass_kg must be None for BATTERY_ELECTRIC "
                    "(mass is derived from motor_rated_power_kw / motor_power_to_weight_ratio)"
                )
            if self.diesel_emission_factors_per_kg is not None:
                raise ValueError(
                    "diesel_emission_factors_per_kg must be None "
                    "for BATTERY_ELECTRIC"
                )
            if self.diesel_consumption_kg_per_km is not None:
                raise ValueError(
                    "diesel_consumption_kg_per_km must be None for BATTERY_ELECTRIC"
                )
            if EnergySource.BATTERY_ELECTRIC not in self.maintenance_per_year:
                raise ValueError("maintenance_per_year must contain BATTERY_ELECTRIC")

        elif energy_source == EnergySource.DIESEL:
            if self.motor_emission_factors_per_kg is not None:
                raise ValueError(
                    "motor_emission_factors_per_kg must be None for DIESEL"
                )
            if self.motor_power_to_weight_ratio is not None:
                raise ValueError("motor_power_to_weight_ratio must be None for DIESEL")
            if self.motor_mass_kg is None:
                raise ValueError("motor_mass_kg is required for DIESEL")
            if self.electricity_emission_factors_per_kwh is not None:
                raise ValueError(
                    "electricity_emission_factors_per_kwh must be None for DIESEL"
                )
            if self.efficiency_mv_to_lv is not None:
                raise ValueError("efficiency_mv_to_lv must be None for DIESEL")
            if self.efficiency_lv_ac_to_dc is not None:
                raise ValueError("efficiency_lv_ac_to_dc must be None for DIESEL")
            if self.diesel_consumption_kg_per_km is None:
                raise ValueError("diesel_consumption_kg_per_km is required for DIESEL")
            if EnergySource.DIESEL not in self.maintenance_per_year:
                raise ValueError("maintenance_per_year must contain DIESEL")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSONB storage.

        :returns: A JSON-compatible dictionary.
        """
        return {
            "chassis_emission_factors_per_kg": self.chassis_emission_factors_per_kg.to_dict(),
            "motor_rated_power_kw": self.motor_rated_power_kw,
            "motor_emission_factors_per_kg": _iv_or_none_to_dict(
                self.motor_emission_factors_per_kg
            ),
            "motor_power_to_weight_ratio": self.motor_power_to_weight_ratio,
            "motor_emission_factors_per_unit": _iv_or_none_to_dict(
                self.motor_emission_factors_per_unit
            ),
            "motor_mass_kg": self.motor_mass_kg,
            "vehicle_lifetime_years": self.vehicle_lifetime_years,
            "efficiency_mv_to_lv": self.efficiency_mv_to_lv,
            "efficiency_lv_ac_to_dc": self.efficiency_lv_ac_to_dc,
            "electricity_emission_factors_per_kwh": _iv_or_none_to_dict(
                self.electricity_emission_factors_per_kwh
            ),
            "diesel_emission_factors_per_kg": _iv_or_none_to_dict(
                self.diesel_emission_factors_per_kg
            ),
            "average_consumption_kwh_per_km": self.average_consumption_kwh_per_km,
            "diesel_consumption_kg_per_km": self.diesel_consumption_kg_per_km,
            "maintenance_per_year": _serialise_maintenance(self.maintenance_per_year),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        energy_source: EnergySource | None = None,
    ) -> VehicleTypeLcaParams:
        """Deserialize from a JSONB dict.

        :param data: The raw dictionary from the JSONB column.
        :param energy_source: Optional energy source for validation.
        :returns: A populated ``VehicleTypeLcaParams``.
        """
        return cls(
            chassis_emission_factors_per_kg=DefaultImpactVector.from_dict(
                data["chassis_emission_factors_per_kg"]
            ),
            motor_rated_power_kw=float(data["motor_rated_power_kw"]),
            motor_emission_factors_per_kg=_iv_or_none_from_dict(
                data.get("motor_emission_factors_per_kg")
            ),
            motor_power_to_weight_ratio=(
                float(data["motor_power_to_weight_ratio"])
                if data.get("motor_power_to_weight_ratio") is not None
                else None
            ),
            motor_emission_factors_per_unit=_iv_or_none_from_dict(
                data.get("motor_emission_factors_per_unit")
            ),
            motor_mass_kg=(
                float(data["motor_mass_kg"])
                if data.get("motor_mass_kg") is not None
                else None
            ),
            vehicle_lifetime_years=float(data["vehicle_lifetime_years"]),
            efficiency_mv_to_lv=(
                float(data["efficiency_mv_to_lv"])
                if data.get("efficiency_mv_to_lv") is not None
                else None
            ),
            efficiency_lv_ac_to_dc=(
                float(data["efficiency_lv_ac_to_dc"])
                if data.get("efficiency_lv_ac_to_dc") is not None
                else None
            ),
            electricity_emission_factors_per_kwh=_iv_or_none_from_dict(
                data.get("electricity_emission_factors_per_kwh")
            ),
            diesel_emission_factors_per_kg=_iv_or_none_from_dict(
                data.get("diesel_emission_factors_per_kg")
            ),
            average_consumption_kwh_per_km=float(
                data["average_consumption_kwh_per_km"]
            ),
            diesel_consumption_kg_per_km=(
                float(data["diesel_consumption_kg_per_km"])
                if data.get("diesel_consumption_kg_per_km") is not None
                else None
            ),
            maintenance_per_year=_deserialise_maintenance(data["maintenance_per_year"]),
            energy_source=energy_source,
        )


# ---------------------------------------------------------------------------
# BatteryTypeLcaParams
# ---------------------------------------------------------------------------


@dataclass
class BatteryTypeLcaParams:
    """LCA parameters stored on ``BatteryType.lca_params``.

    :ivar emission_factors_per_kg: Prod+EoL emissions per kg of battery pack.
    :ivar battery_lifetime_years: Battery lifetime for LCA amortisation (default 8).
    """

    emission_factors_per_kg: DefaultImpactVector
    battery_lifetime_years: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSONB storage.

        :returns: A JSON-compatible dictionary.
        """
        return {
            "emission_factors_per_kg": self.emission_factors_per_kg.to_dict(),
            "battery_lifetime_years": self.battery_lifetime_years,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatteryTypeLcaParams:
        """Deserialize from a JSONB dict.

        :param data: The raw dictionary from the JSONB column.
        :returns: A populated ``BatteryTypeLcaParams``.
        """
        return cls(
            emission_factors_per_kg=DefaultImpactVector.from_dict(
                data["emission_factors_per_kg"]
            ),
            battery_lifetime_years=float(data["battery_lifetime_years"]),
        )

    def check_tco_consistency(self, tco_useful_life: float | None) -> None:
        """Emit a warning if the TCO useful life differs from LCA lifetime.

        :param tco_useful_life: The ``useful_life`` value from
            ``BatteryType.tco_parameters``, or ``None`` if unset.
        """
        if (
            tco_useful_life is not None
            and tco_useful_life != self.battery_lifetime_years
        ):
            warnings.warn(
                f"BatteryType TCO useful_life ({tco_useful_life}) differs from "
                f"LCA battery_lifetime_years ({self.battery_lifetime_years}). "
                f"Verify that the mismatch is intentional.",
                stacklevel=2,
            )


# ---------------------------------------------------------------------------
# ChargingPointTypeLcaParams
# ---------------------------------------------------------------------------


@dataclass
class ChargingPointTypeLcaParams:
    """LCA parameters stored on ``ChargingPointType.lca_params``.

    :ivar control_unit_emissions: Per-unit emissions for one control unit.
    :ivar power_unit_emission: Per-unit emissions for one power unit at its
        reference power.
    :ivar power_unit_rated_power_kw: Rated power of the reference power unit
        in kW; used as the reference power for the 0.8-exponent scaling law.
    :ivar user_unit_emission: Per-unit emissions for one user unit (plug).
    :ivar transformer_emissions: Per-unit emissions for one transformer at its
        reference power.
    :ivar transformer_ref_power_kw: Reference power for the transformer LCA
        dataset in kW; used as the reference power for the 0.8-exponent scaling law.
    :ivar concrete_emissions_per_m3: Per-m³ emissions for concrete foundation.
    :ivar foundation_volume_per_point_m3: Concrete volume per charging point
        in m³ (terminal only).
    :ivar infrastructure_lifetime_years: Lifetime for amortisation.
    """

    control_unit_emissions: DefaultImpactVector
    power_unit_emission: DefaultImpactVector
    power_unit_rated_power_kw: float
    user_unit_emission: DefaultImpactVector
    transformer_emissions: DefaultImpactVector
    transformer_ref_power_kw: float
    concrete_emissions_per_m3: DefaultImpactVector
    foundation_volume_per_point_m3: float
    infrastructure_lifetime_years: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSONB storage.

        :returns: A JSON-compatible dictionary.
        """
        return {
            "control_unit_emissions": self.control_unit_emissions.to_dict(),
            "power_unit_emission": self.power_unit_emission.to_dict(),
            "power_unit_rated_power_kw": self.power_unit_rated_power_kw,
            "user_unit_emission": self.user_unit_emission.to_dict(),
            "transformer_emissions": self.transformer_emissions.to_dict(),
            "transformer_ref_power_kw": self.transformer_ref_power_kw,
            "concrete_emissions_per_m3": self.concrete_emissions_per_m3.to_dict(),
            "foundation_volume_per_point_m3": self.foundation_volume_per_point_m3,
            "infrastructure_lifetime_years": self.infrastructure_lifetime_years,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChargingPointTypeLcaParams:
        """Deserialize from a JSONB dict.

        :param data: The raw dictionary from the JSONB column.
        :returns: A populated ``ChargingPointTypeLcaParams``.
        """
        return cls(
            control_unit_emissions=DefaultImpactVector.from_dict(
                data["control_unit_emissions"]
            ),
            power_unit_emission=DefaultImpactVector.from_dict(
                data["power_unit_emission"]
            ),
            power_unit_rated_power_kw=float(data["power_unit_rated_power_kw"]),
            user_unit_emission=DefaultImpactVector.from_dict(
                data["user_unit_emission"]
            ),
            transformer_emissions=DefaultImpactVector.from_dict(
                data["transformer_emissions"]
            ),
            transformer_ref_power_kw=float(data["transformer_ref_power_kw"]),
            concrete_emissions_per_m3=DefaultImpactVector.from_dict(
                data["concrete_emissions_per_m3"]
            ),
            foundation_volume_per_point_m3=float(
                data["foundation_volume_per_point_m3"]
            ),
            infrastructure_lifetime_years=float(data["infrastructure_lifetime_years"]),
        )


class LcaScope(Enum):

    PRODUCTION_AND_EOL = auto()
    USE_PHASE = auto()


class ItemType(Enum):

    VEHICLE = auto()
    BATTERY = auto()
    INFRASTRUCTURE = auto()
    ENERGY = auto()


@dataclass
class LcaItem:
    """One normalised emission contribution in an LCA result.

    :ivar name: ``VehicleType.name_short`` for vehicle/battery/energy/
        maintenance items; an entity label (e.g. ``"depot_area_5"``) for
        infrastructure items.
    :ivar type: Component category.
    :ivar scope: Lifecycle scope.
    :ivar emission_vector: Annual fleet emissions (amortised where applicable,
        fleet-scaled).  **Not** normalised to per-revenue-km.
    """

    name: str
    type: ItemType
    scope: LcaScope
    emission_vector: DefaultImpactVector


# ---------------------------------------------------------------------------
# LcaResult
# ---------------------------------------------------------------------------


@dataclass
class LcaResult:
    """Output of :func:`eflips.lca.calculate_lca`.

    :ivar items: Annual fleet emission items (not normalised).  Sum any subset
        and divide by ``sum(revenue_km.values())`` to obtain per-revenue-km
        values.
    :ivar revenue_km: Annual revenue-kilometres per vehicle type, keyed by
        ``VehicleType.name_short``.
    :ivar vehicle_km: Annual vehicle-kilometres per vehicle type, keyed by
        ``VehicleType.name_short``.
    """

    items: list[LcaItem] = field(default_factory=list)
    revenue_km: dict[str, float] = field(default_factory=dict)
    vehicle_km: dict[str, float] = field(default_factory=dict)

    @property
    def total_per_revenue_km(self) -> DefaultImpactVector:
        """Fleet-wide total emissions per revenue-km.

        Sums all item emission vectors and divides by the total fleet
        revenue-km.  Returns a zero vector if revenue-km is zero.

        :returns: Total emissions per revenue-kilometre.
        """
        total_rkm = sum(self.revenue_km.values())
        if total_rkm <= 0:
            return DefaultImpactVector.zero()
        total = DefaultImpactVector.zero()
        for item in self.items:
            total = total + item.emission_vector
        return total / total_rkm

    @property
    def emissions_by_scope(self) -> dict[LcaScope, DefaultImpactVector]:
        """Emissions per revenue-km grouped by lifecycle scope.

        All ``LcaScope`` members are present as keys (zero vector if no items
        for that scope).  Returns zero vectors if revenue-km is zero.

        :returns: Mapping from ``LcaScope`` to per-revenue-km emissions.
        """
        total_rkm = sum(self.revenue_km.values())
        accumulated = {scope: DefaultImpactVector.zero() for scope in LcaScope}
        for item in self.items:
            accumulated[item.scope] = accumulated[item.scope] + item.emission_vector
        if total_rkm <= 0:
            return accumulated
        return {scope: v / total_rkm for scope, v in accumulated.items()}

    @property
    def emissions_by_type(self) -> dict[ItemType, DefaultImpactVector]:
        """Emissions per revenue-km grouped by component type.

        All ``ItemType`` members are present as keys (zero vector if no items
        for that type).  Returns zero vectors if revenue-km is zero.

        :returns: Mapping from ``ItemType`` to per-revenue-km emissions.
        """
        total_rkm = sum(self.revenue_km.values())
        accumulated = {itype: DefaultImpactVector.zero() for itype in ItemType}
        for item in self.items:
            accumulated[item.type] = accumulated[item.type] + item.emission_vector
        if total_rkm <= 0:
            return accumulated
        return {itype: v / total_rkm for itype, v in accumulated.items()}
