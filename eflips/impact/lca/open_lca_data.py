"""Intermediate openLCA data layer for eflips-lca.

Provides the ``OpenLCAData`` dataclass that captures all openLCA-derived
emission factors and scalar parameters, serializes to/from JSON, and
supports year-specific electricity emission factors with interpolation.

Data flow::

    openLCA (offline) --> bin/export_openlca.py --> data/*.json (git-tracked)
                                                         |
                                          populate_lca_parameters_from_file()
                                                         |
                                          lca_parameters JSONB on eflips-model
                                                         |
                                          calculation.py (unchanged)
"""

from __future__ import annotations

import dataclasses
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union, get_type_hints

from sqlalchemy.orm import Session

from eflips.model import EnergySource, Scenario

from eflips.impact.lca.dataclasses import (
    BatteryTypeLCAParams,
    ChargingPointTypeLCAParams,
    VehicleTypeLCAParams,
)
from eflips.impact.lca.util import DefaultImpactVector

# ===================================================================
# YearSeries
# ===================================================================


@dataclass
class YearSeries:
    """Year-indexed series of ``DefaultImpactVector`` values.

    Maps calendar years to impact vectors, with linear interpolation
    for years between defined data points and clamping (with a warning)
    for years outside the defined range.

    :ivar data: Mapping from calendar year to ``DefaultImpactVector``.
    """

    data: dict[int, DefaultImpactVector]

    def at_year(self, year: int) -> DefaultImpactVector:
        """Look up or interpolate an impact vector for a given year.

        :param year: The calendar year to query.
        :returns: The exact or interpolated ``DefaultImpactVector``.
        :raises ValueError: If the series is empty.
        """
        if not self.data:
            raise ValueError("YearSeries is empty")

        if year in self.data:
            return self.data[year]

        sorted_years = sorted(self.data.keys())

        if year < sorted_years[0]:
            warnings.warn(
                f"Year {year} is before the earliest data point "
                f"({sorted_years[0]}), clamping.",
                stacklevel=2,
            )
            return self.data[sorted_years[0]]

        if year > sorted_years[-1]:
            warnings.warn(
                f"Year {year} is after the latest data point "
                f"({sorted_years[-1]}), clamping.",
                stacklevel=2,
            )
            return self.data[sorted_years[-1]]

        # Linear interpolation between two surrounding years
        lo_year = max(y for y in sorted_years if y <= year)
        hi_year = min(y for y in sorted_years if y >= year)
        t = (year - lo_year) / (hi_year - lo_year)
        iv_lo = self.data[lo_year]
        iv_hi = self.data[hi_year]
        return iv_lo * (1.0 - t) + iv_hi * t

    def to_dict(self) -> dict[str, dict[str, float]]:
        """Serialize to a JSON-compatible dict with string year keys.

        :returns: A dict mapping year strings to impact vector dicts.
        """
        return {str(year): iv.to_dict() for year, iv in self.data.items()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> YearSeries:
        """Deserialize from a dict with string year keys.

        :param raw: A dict mapping year strings to impact vector dicts.
        :returns: A ``YearSeries`` instance.
        """
        data = {
            int(year_str): DefaultImpactVector.from_dict(iv_dict)
            for year_str, iv_dict in raw.items()
        }
        return cls(data=data)


# ===================================================================
# OpenLCAData
# ===================================================================


@dataclass
class OpenLCAData:
    """All openLCA-derived emission factors and scalar parameters.

    Captures the 14 ImpactVectors from openLCA plus scalar/literature
    parameters needed to populate ``lca_parameters`` on eflips-model entities.

    :ivar ecoinvent_version: Version string for the ecoinvent database.
    :ivar lcia_method_set: Name/version of the LCIA method set used.
    :ivar description: Free-text description of this dataset.
    :ivar created_at: ISO 8601 timestamp of creation.
    :ivar chassis_per_kg: Chassis emission factors per kg.
    :ivar electric_motor_per_kg: Electric motor emission factors per kg.
    :ivar diesel_motor_per_unit: Diesel motor emission factors per unit.
    :ivar lfp_battery_per_kg: LFP battery emission factors per kg.
    :ivar nmc_battery_per_kg: NMC battery emission factors per kg.
    :ivar electricity_per_kwh: Year-varying electricity emission factors per kWh.
    :ivar diesel_per_kg: Diesel well-to-wheel emission factors per kg
        (production + combustion combined).
    :ivar maintenance_iceb_per_year: ICEB maintenance emission factors per bus-year.
    :ivar maintenance_beb_per_year: BEB maintenance emission factors per bus-year.
    :ivar control_unit: Charging control unit emission factors per unit.
    :ivar power_unit: Charging power unit emission factors per unit.
    :ivar user_unit: Charging user unit emission factors per unit.
    :ivar transformer: Transformer emission factors per unit.
    :ivar concrete_per_m3: Concrete emission factors per m3.
    :ivar diesel_motor_mass_kg: Diesel motor mass in kg.
    :ivar efficiency_mv_to_lv: MV to LV transformer efficiency.
    :ivar efficiency_lv_ac_to_dc: AC/DC rectification efficiency.
    :ivar battery_lifetime_years: Battery lifetime for amortisation.
    :ivar beb_maintenance_reduction_factor: BEB maintenance reduction factor
        relative to ICEB (stored for traceability; the already-reduced value is
        in ``maintenance_beb_per_year``).
    :ivar power_unit_rated_power_kw: Rated power of one power unit in kW.
    :ivar transformer_ref_power_kw: Reference power of the transformer LCA
        dataset in kW; used as the denominator in the 0.8-exponent scaling law.
    :ivar eta_avail: Technical availability factor used to scale n_ready to
        total fleet size (``n_total = ceil(n_ready / eta_avail)``).
    """

    # Metadata
    ecoinvent_version: str
    lcia_method_set: str
    description: str
    created_at: str

    # Emission factor ImpactVectors
    chassis_per_kg: DefaultImpactVector
    electric_motor_per_kg: DefaultImpactVector
    diesel_motor_per_unit: DefaultImpactVector
    lfp_battery_per_kg: DefaultImpactVector
    nmc_battery_per_kg: DefaultImpactVector
    electricity_per_kwh: YearSeries
    diesel_per_kg: DefaultImpactVector
    maintenance_iceb_per_year: DefaultImpactVector
    maintenance_beb_per_year: DefaultImpactVector
    control_unit: DefaultImpactVector
    power_unit: DefaultImpactVector
    user_unit: DefaultImpactVector
    transformer: DefaultImpactVector
    concrete_per_m3: DefaultImpactVector

    # Scalar / literature parameters
    efficiency_lv_ac_to_dc: float
    battery_lifetime_years: float
    beb_maintenance_reduction_factor: float
    power_unit_rated_power_kw: float
    transformer_ref_power_kw: float
    diesel_motor_mass_kg: float
    efficiency_mv_to_lv: float
    eta_avail: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Dispatches by resolved type annotation: ``str`` and ``float``
        fields pass through; ``DefaultImpactVector`` and ``YearSeries``
        fields delegate to their own ``to_dict()``.

        :returns: A dict suitable for ``json.dumps()``.
        """
        hints = get_type_hints(type(self))
        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            hint = hints[f.name]
            if hint is str or hint is float:
                result[f.name] = value
            elif hint is DefaultImpactVector or hint is YearSeries:
                result[f.name] = value.to_dict()
            else:
                raise TypeError(f"Unsupported field type {hint!r} for field '{f.name}'")
        return result

    @classmethod
    def from_json_lca(cls, path: str | Path) -> OpenLCAData:
        """Load an ``OpenLCAData`` from the structured lca.json format.

        Reads the section-based format used by eflips-impact defaults
        (``metadata``, ``vehicle_production``, ``battery``, ``use_phase``,
        ``maintenance``, ``charging_infrastructure``).  Battery and
        charging-infrastructure entries are stored split by lifecycle phase
        (production vs. EoL); this method sums each pair before storing.

        Electricity emission factors in the file are stored per MJ (copied
        verbatim from the openLCA export).  They are multiplied by 3.6 on
        load to convert to per kWh, matching the convention used by all
        other ``OpenLCAData`` construction paths.

        ``foundation_volume_per_point_m3`` and
        ``infrastructure_lifetime_years`` are per-CPT overrides supplied
        via ``lca_overrides.json``, not stored in ``lca.json``; the
        dataclass defaults apply for those two fields.

        :param path: Path to the lca.json file.
        :returns: An ``OpenLCAData`` instance.
        :raises KeyError: If a required section or field is missing from the file.
        """
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        def _iv(d: dict[str, Any]) -> DefaultImpactVector:
            """Build a ``DefaultImpactVector`` from a raw dict, treating null as 0.0."""
            return DefaultImpactVector(
                gwp=float(d.get("gwp") or 0.0),
                pm=float(d.get("pm") or 0.0),
                pocp=float(d.get("pocp") or 0.0),
                ap=float(d.get("ap") or 0.0),
                ep_freshwater=float(d.get("ep_freshwater") or 0.0),
                ep_marine=float(d.get("ep_marine") or 0.0),
                fuel=float(d.get("fuel") or 0.0),
                water=float(d.get("water") or 0.0),
            )

        meta = raw["metadata"]
        vp = raw["vehicle_production"]
        bat = raw["battery"]
        use = raw["use_phase"]
        maint = raw["maintenance"]
        ci = raw["charging_infrastructure"]

        mj_per_kwh = 3.6
        electricity_per_kwh = YearSeries(
            data={
                int(year_str): _iv(iv_dict) * mj_per_kwh
                for year_str, iv_dict in use["electricity_per_kwh_by_year"].items()
            }
        )

        return cls(
            ecoinvent_version=meta["ecoinvent_version"],
            lcia_method_set=meta["lcia_method_set"],
            description=meta["description"],
            created_at=meta["created_at"],
            chassis_per_kg=_iv(vp["chassis_per_kg"]),
            electric_motor_per_kg=_iv(vp["electric_motor_per_kg"]),
            diesel_motor_per_unit=_iv(vp["diesel_motor_per_unit"]),
            diesel_motor_mass_kg=float(vp["diesel_motor_mass_kg"]),
            lfp_battery_per_kg=(
                _iv(bat["lfp_production_per_kg"])
                + _iv(bat["lfp_eol_transport_per_kg"])
                + _iv(bat["lfp_eol_disassembly_per_kg"])
            ),
            nmc_battery_per_kg=(
                _iv(bat["nmc_production_per_kg"])
                + _iv(bat["nmc_eol_transport_per_kg"])
                + _iv(bat["nmc_eol_disassembly_per_kg"])
            ),
            battery_lifetime_years=float(bat["lifetime_years"]),
            electricity_per_kwh=electricity_per_kwh,
            diesel_per_kg=_iv(use["diesel_per_kg"]),
            efficiency_mv_to_lv=float(use["efficiency_mv_to_lv"]),
            efficiency_lv_ac_to_dc=float(use["efficiency_lv_ac_to_dc"]),
            maintenance_iceb_per_year=_iv(maint["iceb_per_year"]),
            maintenance_beb_per_year=_iv(maint["beb_per_year"]),
            beb_maintenance_reduction_factor=float(
                maint["beb_maintenance_reduction_factor"]
            ),
            control_unit=(
                _iv(ci["control_unit_production_per_unit"])
                + _iv(ci["control_unit_eol_per_unit"])
            ),
            user_unit=(
                _iv(ci["user_unit_production_per_unit"])
                + _iv(ci["user_unit_eol_per_unit"])
            ),
            power_unit=(
                _iv(ci["power_unit"]["production_per_unit"])
                + _iv(ci["power_unit"]["eol_per_unit"])
            ),
            power_unit_rated_power_kw=float(ci["power_unit"]["ref_power_kw"]),
            transformer=(
                _iv(ci["transformer"]["production_per_unit"])
                + _iv(ci["transformer"]["eol_per_unit"])
            ),
            transformer_ref_power_kw=float(ci["transformer"]["ref_power_kw"]),
            concrete_per_m3=_iv(ci["concrete_per_m3"]),
            eta_avail=float(meta["eta_avail"]),
        )

    def make_vehicle_type_lca_parameters_beb(
        self,
        year: int,
        overrides: VehicleTypeOverrides,
    ) -> VehicleTypeLCAParams:
        """Construct BEB ``VehicleTypeLCAParams`` from this dataset.

        :param year: Calendar year for selecting the electricity emission factor.
        :param overrides: Per-vehicle-model values not derivable from openLCA.
        :returns: A validated ``VehicleTypeLCAParams`` for a BEB.
        """
        if overrides.motor_power_to_weight_ratio_kw_per_kg is None:
            raise ValueError(
                "motor_power_to_weight_ratio_kw_per_kg is required for BATTERY_ELECTRIC "
                "vehicle types but is None in the provided overrides."
            )
        return _create_vehicle_type_lca_parameters_beb(
            chassis_ef_per_kg=self.chassis_per_kg,
            motor_ef_per_kg=self.electric_motor_per_kg,
            motor_rated_power_kw=overrides.motor_rated_power_kw,
            motor_power_to_weight_ratio=overrides.motor_power_to_weight_ratio_kw_per_kg,
            electricity_ef_per_kwh=self.electricity_per_kwh.at_year(year),
            maintenance_beb_per_year=self.maintenance_beb_per_year,
            average_consumption_kwh_per_km=overrides.average_consumption_kwh_per_km,
            vehicle_lifetime_years=overrides.vehicle_lifetime_years,
            efficiency_mv_to_lv=self.efficiency_mv_to_lv,
            efficiency_lv_ac_to_dc=self.efficiency_lv_ac_to_dc,
        )

    def make_vehicle_type_lca_parameters_diesel(
        self,
        overrides: VehicleTypeOverrides,
    ) -> VehicleTypeLCAParams:
        """Construct ICEB ``VehicleTypeLCAParams`` from this dataset.

        :param overrides: Per-vehicle-model values not derivable from openLCA.
            ``overrides.diesel_consumption_kg_per_km`` must not be ``None``.
        :returns: A validated ``VehicleTypeLCAParams`` for an ICEB.
        :raises ValueError: If ``overrides.diesel_consumption_kg_per_km`` is ``None``.
        """
        if overrides.diesel_consumption_kg_per_km is None:
            raise ValueError(
                "diesel_consumption_kg_per_km is required for DIESEL vehicle types"
            )
        return _create_vehicle_type_lca_parameters_diesel(
            chassis_ef_per_kg=self.chassis_per_kg,
            motor_ef_per_unit=self.diesel_motor_per_unit,
            motor_mass_kg=self.diesel_motor_mass_kg,
            diesel_ef_per_kg=self.diesel_per_kg,
            maintenance_diesel_per_year=self.maintenance_iceb_per_year,
            average_consumption_kwh_per_km=overrides.average_consumption_kwh_per_km,
            diesel_consumption_kg_per_km=overrides.diesel_consumption_kg_per_km,
            motor_rated_power_kw=overrides.motor_rated_power_kw,
            vehicle_lifetime_years=overrides.vehicle_lifetime_years,
        )

    def make_battery_type_lca_parameters(
        self,
        chemistry: str | None,
    ) -> BatteryTypeLCAParams:
        """Construct ``BatteryTypeLCAParams`` from this dataset.

        :param chemistry: Battery cell chemistry string from
            ``BatteryType.chemistry`` (e.g. ``"NMC622"``, ``"LFP"``).
            Strings starting with ``"NMC"`` (case-insensitive) select
            ``nmc_battery_per_kg``; all other values (including ``None``)
            select ``lfp_battery_per_kg``.
        :returns: A ``BatteryTypeLCAParams``.
        """
        if chemistry is not None and chemistry.upper().startswith("NMC"):
            ef = self.nmc_battery_per_kg
        else:
            ef = self.lfp_battery_per_kg
        return _create_battery_type_lca_parameters(
            emission_factors_per_kg=ef,
            battery_lifetime_years=self.battery_lifetime_years,
        )

    def make_charging_point_type_lca_parameters(
        self,
        overrides: ChargingPointTypeOverrides,
    ) -> ChargingPointTypeLCAParams:
        """Construct ``ChargingPointTypeLCAParams`` from this dataset.

        :param overrides: Infrastructure lifetime and foundation volume, read
            from ``lca_overrides.json``.
        :returns: A ``ChargingPointTypeLCAParams``.

        .. note::

            Emits a ``UserWarning`` if ``transformer`` or ``concrete_per_m3``
            are zero vectors, meaning those emission contributions will be
            silently omitted from the LCA calculation.
        """
        if self.transformer == DefaultImpactVector.zero():
            warnings.warn(
                "OpenLCAData.transformer is a zero vector — transformer "
                "production emissions will be omitted from the LCA.",
                stacklevel=2,
            )
        if self.concrete_per_m3 == DefaultImpactVector.zero():
            warnings.warn(
                "OpenLCAData.concrete_per_m3 is a zero vector — concrete "
                "foundation emissions will be omitted from the LCA.",
                stacklevel=2,
            )
        return _create_charging_point_type_lca_parameters(
            control_unit_emissions=self.control_unit,
            power_unit_emission=self.power_unit,
            power_unit_rated_power_kw=self.power_unit_rated_power_kw,
            user_unit_emission=self.user_unit,
            transformer_emissions=self.transformer,
            transformer_ref_power_kw=self.transformer_ref_power_kw,
            concrete_emissions_per_m3=self.concrete_per_m3,
            foundation_volume_per_point_m3=overrides.foundation_volume_per_point_m3,
            infrastructure_lifetime_years=overrides.infrastructure_lifetime_years,
        )

    @staticmethod
    def _read_bus_results_columns(
        raw: dict[str, Any],
    ) -> dict[str, DefaultImpactVector]:
        """Extract a ``DefaultImpactVector`` for every column in bus_results.json.

        The bus_results.json is in DataFrame orientation: ``data[row_idx][col_idx]``,
        where rows correspond to impact categories (``"index"``) and columns
        correspond to openLCA processes or electricity-year scenarios
        (``"columns"``).

        Impact categories are identified by the parenthesised acronym in their
        label (e.g. ``"(GWP100)"``).  Only the eight categories that map to
        ``DefaultImpactVector`` fields are used; all remaining index rows are
        ignored (see inline comment for the full skipped list).

        Note on categories with more than one sub-type in the index:

        * *Photochemical oxidant formation* — two sub-types are present:
          ``EOFP`` (terrestrial ecosystems) and ``HOFP`` (human health).
          See the TODO below.
        * *Ecotoxicity* — three sub-types exist (``FETP`` / ``METP`` /
          ``TETP``); none map to a ``DefaultImpactVector`` field and all
          are skipped.
        * *Human toxicity* — two sub-types exist (``HTPnc`` / ``HTPc``);
          neither maps to a ``DefaultImpactVector`` field and both are
          skipped.

        :param raw: Parsed ``bus_results.json`` dict with ``"columns"``,
            ``"index"``, and ``"data"`` keys.
        :returns: A dict mapping each column name to its ``DefaultImpactVector``.
        :raises ValueError: If a required impact-category acronym is absent from
            the index.
        """
        columns: list[str] = raw["columns"]
        index: list[str] = raw["index"]
        data: list[list[float]] = raw["data"]

        def _row(acronym: str) -> int:
            """Return the index row whose label contains ``(acronym)``."""
            for i, label in enumerate(index):
                if f"({acronym})" in label:
                    return i
            raise ValueError(
                f"Impact category with acronym ({acronym}) not found in index"
            )

        row_gwp = _row("GWP100")  # climate change – global warming potential
        row_pm = _row("PMFP")  # particulate matter formation
        row_pocp = _row("HOFP")  # photochemical oxidant formation: human health
        row_ap = _row("TAP")  # acidification: terrestrial
        row_ep_freshwater = _row("FEP")  # eutrophication: freshwater
        row_ep_marine = _row("MEP")  # eutrophication: marine
        row_fuel = _row("FFP")  # energy resources: non-renewable, fossil
        row_water = _row("WCP")  # water use

        # Skipped index rows (no corresponding DefaultImpactVector field):
        #   FETP / METP / TETP  – ecotoxicity freshwater / marine / terrestrial
        #   LOP                 – land use
        #   ODPinfinite         – ozone depletion
        #   SOP                 – material resources: metals/minerals
        #   HTPnc / HTPc        – human toxicity non-carcinogenic / carcinogenic
        #   IRP                 – ionising radiation
        #   EOFP                – photochemical oxidant formation: terrestrial ecosystems

        return {
            col: DefaultImpactVector(
                gwp=data[row_gwp][j],
                pm=data[row_pm][j],
                pocp=data[row_pocp][j],
                ap=data[row_ap][j],
                ep_freshwater=data[row_ep_freshwater][j],
                ep_marine=data[row_ep_marine][j],
                fuel=data[row_fuel][j],
                water=data[row_water][j],
            )
            for j, col in enumerate(columns)
        }


# ===================================================================
# VehicleTypeOverrides
# ===================================================================


@dataclass
class VehicleTypeOverrides:
    """Per-vehicle-type values not from openLCA.

    These differ per bus model and must be provided alongside the
    ``OpenLCAData`` when populating ``lca_parameters``.

    :ivar motor_rated_power_kw: Rated motor power in kW.
    :ivar vehicle_lifetime_years: Vehicle (chassis + motor) lifetime for
        amortisation in years.
    :ivar motor_power_to_weight_ratio_kw_per_kg: Electric motor power-to-weight
        ratio in kW/kg, used to derive motor mass.  ``None`` for diesel
        (motor mass is fixed globally in ``OpenLCAData.diesel_motor_mass_kg``).
    :ivar average_consumption_kwh_per_km: Average energy consumption in kWh/km for LCA.
    :ivar diesel_consumption_kg_per_km: Average diesel consumption in kg/km,
        or ``None`` for BEB.
    """

    motor_rated_power_kw: float
    vehicle_lifetime_years: float
    motor_power_to_weight_ratio_kw_per_kg: float | None = None
    average_consumption_kwh_per_km: float = 0.0
    diesel_consumption_kg_per_km: float | None = None


@dataclass
class ChargingPointTypeOverrides:
    """Per-type overrides for charging-point infrastructure LCA parameters.

    :ivar infrastructure_lifetime_years: Infrastructure amortisation lifetime in years.
    :ivar foundation_volume_per_point_m3: Concrete foundation volume per
        charging point in m³ (typically non-zero for outdoor opportunity
        chargers, zero for indoor depot chargers).
    """

    infrastructure_lifetime_years: float
    foundation_volume_per_point_m3: float


# ===================================================================
# Parameter construction helpers
# ===================================================================


def _create_vehicle_type_lca_parameters_beb(
    chassis_ef_per_kg: DefaultImpactVector,
    motor_ef_per_kg: DefaultImpactVector,
    motor_rated_power_kw: float,
    motor_power_to_weight_ratio: float,
    electricity_ef_per_kwh: DefaultImpactVector,
    maintenance_beb_per_year: DefaultImpactVector,
    average_consumption_kwh_per_km: float,
    vehicle_lifetime_years: float,
    efficiency_mv_to_lv: float,
    efficiency_lv_ac_to_dc: float,
) -> VehicleTypeLCAParams:
    """Create LCA parameters for a battery-electric vehicle type.

    :param chassis_ef_per_kg: Chassis emission factors per kg.
    :param motor_ef_per_kg: Electric motor emission factors per kg.
    :param motor_rated_power_kw: Rated motor power in kW.
    :param motor_power_to_weight_ratio: Motor power-to-weight ratio (kW/kg).
    :param electricity_ef_per_kwh: Grid electricity emission factors per kWh.
    :param maintenance_beb_per_year: Annual maintenance emissions per vehicle.
    :param average_consumption_kwh_per_km: Average energy consumption in
        kWh/km for LCA purposes.
    :param vehicle_lifetime_years: Vehicle lifetime in years.
    :param efficiency_mv_to_lv: MV->LV transformer efficiency.
    :param efficiency_lv_ac_to_dc: AC/DC rectification efficiency.
    :returns: A validated ``VehicleTypeLCAParams`` for a BEB.
    """
    return VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=chassis_ef_per_kg,
        motor_rated_power_kw=motor_rated_power_kw,
        motor_emission_factors_per_kg=motor_ef_per_kg,
        motor_power_to_weight_ratio=motor_power_to_weight_ratio,
        motor_emission_factors_per_unit=None,
        motor_mass_kg=None,
        vehicle_lifetime_years=vehicle_lifetime_years,
        efficiency_mv_to_lv=efficiency_mv_to_lv,
        efficiency_lv_ac_to_dc=efficiency_lv_ac_to_dc,
        electricity_emission_factors_per_kwh=electricity_ef_per_kwh,
        diesel_emission_factors_per_kg=None,
        average_consumption_kwh_per_km=average_consumption_kwh_per_km,
        diesel_consumption_kg_per_km=None,
        maintenance_per_year={EnergySource.BATTERY_ELECTRIC: maintenance_beb_per_year},
        energy_source=EnergySource.BATTERY_ELECTRIC,
    )


def _create_vehicle_type_lca_parameters_diesel(
    chassis_ef_per_kg: DefaultImpactVector,
    motor_ef_per_unit: DefaultImpactVector,
    motor_mass_kg: float,
    diesel_ef_per_kg: DefaultImpactVector,
    maintenance_diesel_per_year: DefaultImpactVector,
    average_consumption_kwh_per_km: float,
    diesel_consumption_kg_per_km: float,
    motor_rated_power_kw: float,
    vehicle_lifetime_years: float,
) -> VehicleTypeLCAParams:
    """Create LCA parameters for a diesel vehicle type.

    :param chassis_ef_per_kg: Chassis emission factors per kg.
    :param motor_ef_per_unit: Diesel motor emission factors (per complete motor).
    :param motor_mass_kg: Diesel motor mass in kg.
    :param diesel_ef_per_kg: Well-to-wheel emissions per kg diesel
        (production + combustion combined).
    :param maintenance_diesel_per_year: Annual maintenance emissions per vehicle.
    :param average_consumption_kwh_per_km: Average energy consumption in
        kWh/km (for comparability; not used in diesel energy calc).
    :param diesel_consumption_kg_per_km: Diesel consumption in kg/km.
    :param motor_rated_power_kw: Rated motor power in kW.
    :param vehicle_lifetime_years: Vehicle lifetime in years.
    :returns: A validated ``VehicleTypeLCAParams`` for an ICEB.
    """
    return VehicleTypeLCAParams(
        chassis_emission_factors_per_kg=chassis_ef_per_kg,
        motor_rated_power_kw=motor_rated_power_kw,
        motor_emission_factors_per_kg=None,
        motor_power_to_weight_ratio=None,
        motor_emission_factors_per_unit=motor_ef_per_unit,
        motor_mass_kg=motor_mass_kg,
        vehicle_lifetime_years=vehicle_lifetime_years,
        efficiency_mv_to_lv=None,
        efficiency_lv_ac_to_dc=None,
        electricity_emission_factors_per_kwh=None,
        diesel_emission_factors_per_kg=diesel_ef_per_kg,
        average_consumption_kwh_per_km=average_consumption_kwh_per_km,
        diesel_consumption_kg_per_km=diesel_consumption_kg_per_km,
        maintenance_per_year={EnergySource.DIESEL: maintenance_diesel_per_year},
        energy_source=EnergySource.DIESEL,
    )


def _create_battery_type_lca_parameters(
    emission_factors_per_kg: DefaultImpactVector,
    battery_lifetime_years: float,
) -> BatteryTypeLCAParams:
    """Create LCA parameters for a battery type.

    :param emission_factors_per_kg: Prod+EoL emissions per kg of battery pack.
    :param battery_lifetime_years: Battery lifetime for LCA amortisation.
    :returns: A ``BatteryTypeLCAParams``.
    """
    return BatteryTypeLCAParams(
        emission_factors_per_kg=emission_factors_per_kg,
        battery_lifetime_years=battery_lifetime_years,
    )


def _create_charging_point_type_lca_parameters(
    control_unit_emissions: DefaultImpactVector,
    power_unit_emission: DefaultImpactVector,
    power_unit_rated_power_kw: float,
    user_unit_emission: DefaultImpactVector,
    transformer_emissions: DefaultImpactVector,
    transformer_ref_power_kw: float,
    concrete_emissions_per_m3: DefaultImpactVector,
    foundation_volume_per_point_m3: float,
    infrastructure_lifetime_years: float,
) -> ChargingPointTypeLCAParams:
    """Create LCA parameters for a charging point type.

    :param control_unit_emissions: Per-unit emissions for one control unit.
    :param power_unit_emission: Per-unit emissions for one power unit at its
        reference power.
    :param power_unit_rated_power_kw: Rated power of the reference power unit
        in kW; also used as the reference power for scaling.
    :param user_unit_emission: Per-unit emissions for one user unit (plug).
    :param transformer_emissions: Per-unit emissions for one transformer at its
        reference power.
    :param transformer_ref_power_kw: Reference power of the transformer LCA
        dataset in kW; used as the denominator in the 0.8-exponent scaling law.
    :param concrete_emissions_per_m3: Per-m3 emissions for concrete foundation.
    :param foundation_volume_per_point_m3: Concrete volume per charging point in m3.
    :param infrastructure_lifetime_years: Lifetime for amortisation.
    :returns: A ``ChargingPointTypeLCAParams``.
    """
    return ChargingPointTypeLCAParams(
        control_unit_emissions=control_unit_emissions,
        power_unit_emission=power_unit_emission,
        power_unit_rated_power_kw=power_unit_rated_power_kw,
        user_unit_emission=user_unit_emission,
        transformer_emissions=transformer_emissions,
        transformer_ref_power_kw=transformer_ref_power_kw,
        concrete_emissions_per_m3=concrete_emissions_per_m3,
        foundation_volume_per_point_m3=foundation_volume_per_point_m3,
        infrastructure_lifetime_years=infrastructure_lifetime_years,
    )


# ===================================================================
# Population functions
# ===================================================================


def populate_lca_parameters_from_data(
    session: Session,
    scenario_id: int,
    open_lca_data: OpenLCAData,
    year: int,
    vehicle_type_overrides: dict[str, VehicleTypeOverrides],
    cpt_overrides: ChargingPointTypeOverrides | None = None,
) -> None:
    """Populate ``lca_parameters`` on eflips-model entities from an ``OpenLCAData``.

    Builds ``VehicleTypeLCAParams``, ``BatteryTypeLCAParams``, and
    ``ChargingPointTypeLCAParams`` and writes the resulting dicts to the
    JSONB columns.

    .. note::

        Identical ``ChargingPointTypeLCAParams`` are applied to every
        ``ChargingPointType`` in the scenario (depot and opportunity are not
        differentiated).

    :param session: SQLAlchemy session connected to an eflips-model database.
    :param scenario_id: ID of the scenario whose entities to populate.
    :param open_lca_data: The openLCA dataset.
    :param year: Calendar year for year-specific values (electricity mix).
    :param vehicle_type_overrides: Per-vehicle-type overrides, keyed by
        ``VehicleType.name_short``.
    :param cpt_overrides: Infrastructure lifetime and foundation volume, read
        from ``lca_overrides.json``.  Required when the scenario has
        any ``ChargingPointType`` rows; may be ``None`` for
        diesel-only scenarios.
    :raises ValueError: If the scenario has ``ChargingPointType`` rows but
        ``cpt_overrides`` is ``None``.
    """
    from eflips.model import BatteryType, ChargingPointType, VehicleType

    d = open_lca_data

    # --- VehicleTypes ---
    vehicle_types = (
        session.query(VehicleType).filter(VehicleType.scenario_id == scenario_id).all()
    )
    for vtype in vehicle_types:
        name_short = str(vtype.name_short)
        if name_short not in vehicle_type_overrides:
            warnings.warn(
                f"VehicleType {name_short!r} has no entry in vehicle_type_overrides "
                f"and will have no lca_parameters set.",
                stacklevel=2,
            )
            continue
        ovr = vehicle_type_overrides[name_short]

        if vtype.energy_source == EnergySource.BATTERY_ELECTRIC:
            params = d.make_vehicle_type_lca_parameters_beb(year, ovr)
        elif vtype.energy_source == EnergySource.DIESEL:
            params = d.make_vehicle_type_lca_parameters_diesel(ovr)
        else:
            raise ValueError(f"Unsupported energy source: {vtype.energy_source}")

        vtype.lca_parameters = params.to_dict()

    # --- BatteryTypes ---
    # Row creation is the responsibility of eflips.impact.utils.complete_fleet
    # (driven by fleet.json). This function only writes lca_parameters on rows
    # that already exist.
    battery_types = (
        session.query(BatteryType).filter(BatteryType.scenario_id == scenario_id).all()
    )
    for bt in battery_types:
        bt.lca_parameters = d.make_battery_type_lca_parameters(
            getattr(bt, "chemistry", None)
        ).to_dict()

    # --- ChargingPointTypes ---
    # Row creation is the responsibility of eflips.impact.utils.complete_fleet
    # (driven by fleet.json). This function only writes lca_parameters on rows
    # that already exist.
    charging_point_types = (
        session.query(ChargingPointType)
        .filter(ChargingPointType.scenario_id == scenario_id)
        .all()
    )
    if charging_point_types and cpt_overrides is None:
        raise ValueError(
            "cpt_overrides is required when the scenario has ChargingPointType rows."
        )
    for cpt in charging_point_types:
        assert cpt_overrides is not None  # guaranteed by check above
        cpt.lca_parameters = d.make_charging_point_type_lca_parameters(cpt_overrides).to_dict()

    session.flush()


def init_lca_params(
    scenario: Union[Scenario, int, Any],
    lca_json_path: str | Path,
    overrides_json_path: str | Path,
    database_url: Optional[str] = None,
) -> None:
    """Populate ``lca_parameters`` on all eflips-model entities for a scenario.

    Reads an openLCA emission-factor export (``lca.json``) and a per-scenario
    overrides file (``lca_overrides.json``), validates that every BEB
    ``VehicleType`` in the scenario has a matching entry in the overrides, and
    writes ``VehicleTypeLCAParams``, ``BatteryTypeLCAParams``, and
    ``ChargingPointTypeLCAParams`` to the corresponding JSONB columns.

    Pre-flight validation warns and returns ``None`` without writing if any
    BEB ``VehicleType`` in the scenario lacks a ``name_short`` entry in
    ``vehicle_type_overrides``.

    .. note::

        All ``ChargingPointType`` rows in the scenario receive identical
        params (depot vs. opportunity not yet differentiated).  The opportunity
        overrides entry is used if present, otherwise the first available entry.

    :param scenario: A :class:`~eflips.model.Scenario` instance, an ``int``
        scenario id, or any object with an ``id`` attribute.
    :param lca_json_path: Path to the openLCA emission-factor JSON (``lca.json``).
    :param overrides_json_path: Path to the per-scenario overrides JSON
        (``lca_overrides.json``).
    :param database_url: Database URL; falls back to ``$DATABASE_URL`` when
        ``scenario`` is not already bound to a session.
    """
    from eflips.impact.utils.session import create_session

    lca_json_path = Path(lca_json_path)
    overrides_json_path = Path(overrides_json_path)

    data = OpenLCAData.from_json_lca(lca_json_path)

    with open(overrides_json_path, "r", encoding="utf-8") as f:
        raw_overrides: dict[str, Any] = json.load(f)

    year = int(raw_overrides["year"])

    vehicle_type_overrides: dict[str, VehicleTypeOverrides] = {}
    for entry in raw_overrides.get("vehicle_type_overrides", []):
        name_short = str(entry["name_short"])
        vehicle_type_overrides[name_short] = VehicleTypeOverrides(
            motor_rated_power_kw=float(entry["motor_rated_power_kw"]),
            vehicle_lifetime_years=float(entry["vehicle_lifetime_years"]),
            motor_power_to_weight_ratio_kw_per_kg=entry.get(
                "motor_power_to_weight_ratio_kw_per_kg"
            ),
            average_consumption_kwh_per_km=float(
                entry.get("average_consumption_kwh_per_km", 0.0)
            ),
            diesel_consumption_kg_per_km=entry.get("diesel_consumption_kg_per_km"),
        )

    # Pick CPT overrides: prefer opportunity entry (has foundation volume),
    # fall back to first entry.  Known limitation: same params for all CPTs.
    cpt_overrides: ChargingPointTypeOverrides | None = None
    cpt_entries: list[dict[str, Any]] = raw_overrides.get(
        "charging_point_type_overrides", []
    )
    if cpt_entries:
        opp = next(
            (e for e in cpt_entries if e.get("type") == "opportunity"),
            cpt_entries[0],
        )
        cpt_overrides = ChargingPointTypeOverrides(
            infrastructure_lifetime_years=float(opp["infrastructure_lifetime_years"]),
            foundation_volume_per_point_m3=float(opp["foundation_volume_per_point_m3"]),
        )

    with create_session(scenario, database_url) as (session, scenario_obj):
        scenario_id = int(scenario_obj.id)

        from eflips.model import VehicleType

        beb_name_shorts = {
            str(vt.name_short)
            for vt in session.query(VehicleType)
            .filter(VehicleType.scenario_id == scenario_id)
            .all()
            if vt.energy_source == EnergySource.BATTERY_ELECTRIC
        }
        missing = beb_name_shorts - set(vehicle_type_overrides.keys())
        if missing:
            warnings.warn(
                f"BEB VehicleTypes {sorted(missing)} have no entry in "
                f"{overrides_json_path.name}; lca_parameters will not be written.",
                UserWarning,
                stacklevel=2,
            )
            return

        populate_lca_parameters_from_data(
            session=session,
            scenario_id=scenario_id,
            open_lca_data=data,
            year=year,
            vehicle_type_overrides=vehicle_type_overrides,
            cpt_overrides=cpt_overrides,
        )
