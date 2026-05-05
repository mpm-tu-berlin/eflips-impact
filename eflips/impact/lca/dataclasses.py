"""LCA parameter dataclasses and result container.

Defines the typed structures stored in ``lca_params`` JSONB columns on
eflips-model entities, plus the ``LcaResult`` output of the calculation.
"""

from __future__ import annotations

import warnings
from dataclasses import InitVar, dataclass, field
from typing import Any

from eflips.model import EnergySource

from eflips.impact.lca.util import DefaultImpactVector

# ---------------------------------------------------------------------------
# Helpers for (de)serialising EnergySource-keyed dicts and nested vectors
# ---------------------------------------------------------------------------


def _serialise_maintenance(
    data: dict[EnergySource, DefaultImpactVector],
) -> dict[str, dict[str, float]]:
    """Convert an ``EnergySource``-keyed dict to a JSON-safe form.

    Args:
        data: Maintenance emissions keyed by ``EnergySource``.

    Returns:
        A dict with string keys (enum member names) and nested dicts.
    """
    return {k.name: v.to_dict() for k, v in data.items()}


def _deserialise_maintenance(
    raw: dict[str, Any],
) -> dict[EnergySource, DefaultImpactVector]:
    """Reconstruct an ``EnergySource``-keyed dict from JSON.

    Args:
        raw: A dict with string keys and nested impact-vector dicts.

    Returns:
        A dict keyed by ``EnergySource`` enum members.
    """
    return {EnergySource[k]: DefaultImpactVector.from_dict(v) for k, v in raw.items()}


def _iv_or_none_to_dict(
    iv: DefaultImpactVector | None,
) -> dict[str, float] | None:
    """Serialize an optional ImpactVector.

    Args:
        iv: An ImpactVector or ``None``.

    Returns:
        A dict or ``None``.
    """
    return iv.to_dict() if iv is not None else None


def _iv_or_none_from_dict(
    raw: dict[str, Any] | None,
) -> DefaultImpactVector | None:
    """Deserialize an optional ImpactVector.

    Args:
        raw: A dict or ``None``.

    Returns:
        A ``DefaultImpactVector`` or ``None``.
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

        Args:useful_life
            energy_source: The vehicle type's energy source, used for
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

        Returns:
            A JSON-compatible dictionary.
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

        Args:
            data: The raw dictionary from the JSONB column.
            energy_source: Optional energy source for validation.

        Returns:
            A populated ``VehicleTypeLcaParams``.
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

    Attributes:
        emission_factors_per_kg: Prod+EoL emissions per kg of battery pack.
        battery_lifetime_years: Battery lifetime for LCA amortisation
            (default 8).
    """

    emission_factors_per_kg: DefaultImpactVector
    battery_lifetime_years: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSONB storage.

        Returns:
            A JSON-compatible dictionary.
        """
        return {
            "emission_factors_per_kg": self.emission_factors_per_kg.to_dict(),
            "battery_lifetime_years": self.battery_lifetime_years,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatteryTypeLcaParams:
        """Deserialize from a JSONB dict.

        Args:
            data: The raw dictionary from the JSONB column.

        Returns:
            A populated ``BatteryTypeLcaParams``.
        """
        return cls(
            emission_factors_per_kg=DefaultImpactVector.from_dict(
                data["emission_factors_per_kg"]
            ),
            battery_lifetime_years=float(data["battery_lifetime_years"]),
        )

    def check_tco_consistency(self, tco_useful_life: float | None) -> None:
        """Emit a warning if the TCO useful life differs from LCA lifetime.

        Args:
            tco_useful_life: The ``useful_life`` value from
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

    Attributes:
        control_unit_emissions: Per-unit emissions for one control unit.
        power_unit_emission: Per-unit emissions for one power unit at its
            reference power.
        power_unit_rated_power_kw: Rated power of the reference power unit
            in kW; used as the reference power for the 0.8-exponent scaling
            law.
        user_unit_emission: Per-unit emissions for one user unit (plug).
        transformer_emissions: Per-unit emissions for one transformer at its
            reference power.
        transformer_ref_power_kw: Reference power for the transformer LCA
            dataset in kW; used as the reference power for the 0.8-exponent
            scaling law.
        concrete_emissions_per_m3: Per-m³ emissions for concrete foundation.
        foundation_volume_per_point_m3: Concrete volume per charging point
            in m³ (terminal only).
        infrastructure_lifetime_years: Lifetime for amortisation.
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

        Returns:
            A JSON-compatible dictionary.
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

        Args:
            data: The raw dictionary from the JSONB column.

        Returns:
            A populated ``ChargingPointTypeLcaParams``.
        """
        return cls(
            control_unit_emissions=DefaultImpactVector.from_dict(
                data["control_unit_emissions"]
            ),
            power_unit_emission=DefaultImpactVector.from_dict(
                data["power_unit_emission"]
            ),
            power_unit_rated_power_kw=float(data["power_unit_rated_power_kw"]),
            user_unit_emission=DefaultImpactVector.from_dict(data["user_unit_emission"]),
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


# ---------------------------------------------------------------------------
# LcaResult
# ---------------------------------------------------------------------------


@dataclass
class LcaResult:
    """Output of :func:`eflips.lca.calculate_lca`.

    Attributes:
        production: Per-revenue-km production emissions, keyed by
            ``VehicleType.id``.  Normalised by that type's own Nwkm.
        use_phase: Per-revenue-km use-phase emissions, keyed by
            ``VehicleType.id``.  Normalised by that type's own Nwkm.
        infrastructure: Fleet-wide per-revenue-km infrastructure emissions.
            Normalised by total fleet Nwkm.
        total: Fleet-wide per-revenue-km total.  Production and use are
            normalised by total fleet Nwkm (shared denominator), so this is
            **not** equal to ``Σ production[t] + Σ use_phase[t] + infrastructure``
            for multi-type fleets.
        revenue_km: Annual revenue-kilometres per vehicle type, keyed by
            ``VehicleType.id``.  Exposed so callers can reconstruct the
            correct fleet-wide formula.
    """

    production: dict[int, DefaultImpactVector] = field(default_factory=dict)
    use_phase: dict[int, DefaultImpactVector] = field(default_factory=dict)
    infrastructure: DefaultImpactVector = field(
        default_factory=DefaultImpactVector.zero
    )
    total: DefaultImpactVector = field(default_factory=DefaultImpactVector.zero)
    revenue_km: dict[int, float] = field(default_factory=dict)
