# LCA — Life Cycle Assessment

## How LCA is calculated

LCA quantifies environmental impacts over the full lifecycle of the bus fleet, following ISO 14040/14044. The functional unit is **kg CO₂-eq per revenue-kilometre** (GWP is the primary reported category; seven additional categories are tracked in parallel — see [Impact categories](#impact-categories)).

### Lifecycle scopes

| Scope | What it covers |
|---|---|
| `PRODUCTION_AND_EOL` | Manufacturing and end-of-life processing of vehicles, batteries, and charging infrastructure, amortised over their respective lifetimes. |
| `USE_PHASE` | Energy consumption (electricity or diesel) and vehicle maintenance over the operating period. |

### Component calculations

**Vehicles (per vehicle type, fleet-scaled)**

| Sub-item | Method |
|---|---|
| Chassis | `(empty_mass − motor_mass − battery_mass) × chassis_EF/kg ÷ vehicle_lifetime` |
| Motor (BEB) | `(motor_rated_power_kw ÷ motor_power_to_weight_ratio) × motor_EF/kg ÷ vehicle_lifetime` |
| Motor (ICEB) | `diesel_motor_EF/unit ÷ vehicle_lifetime` |
| Maintenance | `maintenance_EF/year × fleet_size` |

Fleet size = `ceil(n_vehicles_in_simulation / eta_avail)`.

**Battery (BEB only, fleet-scaled)**

`battery_mass × battery_EF/kg ÷ battery_lifetime`

Battery mass = `VehicleType.battery_capacity × BatteryType.specific_mass`.

**Energy (use phase, fleet-scaled vehicle-km)**

- **BEB**: `consumption_kwh/km × vehicle_km ÷ (efficiency_mv_to_lv × efficiency_lv_ac_to_dc × charging_efficiency) × electricity_EF/kWh`
- **ICEB**: `diesel_consumption_kg/km × vehicle_km × diesel_EF/kg`

Electricity emission factors are looked up for the analysis `year` from `lca.json` with linear interpolation between defined years.

**Charging infrastructure (production + EoL, per area / station)**

Power units and transformers are scaled from reference power to actual peak power using an 0.8-exponent law:

`impact = impact_ref × (peak_power / ref_power)^0.8`

Per depot area: `power_units + user_units × n_plugs + transformer + control_unit`

Per terminal station: same + `concrete_EF/m³ × foundation_volume/plug × n_plugs`

All infrastructure contributions are amortised over `infrastructure_lifetime_years`.

### Functional unit

All annual fleet emissions are summed, then divided by total annual revenue-km across all vehicle types.

### Impact categories

`DefaultImpactVector` carries eight categories, all sourced from the openLCA export in `lca.json`:

| Field | Unit | Indicator |
|---|---|---|
| `gwp` | kg CO₂-eq | Global warming potential (GWP100) |
| `pm` | kg PM2.5-eq | Particulate matter formation (PMFP) |
| `pocp` | kg NOx-eq | Photochemical ozone creation — human health (HOFP). The human health sub-category is reported following common practice in academic research. |
| `ap` | kg SO₂-eq | Acidification potential (TAP) |
| `ep_freshwater` | kg P-eq | Freshwater eutrophication (FEP) |
| `ep_marine` | kg N-eq | Marine eutrophication (MEP) |
| `fuel` | kg Oil-eq | Fossil resource depletion (FFP) |
| `water` | m³ | Water consumption (WCP) |

---

## `lca.json` parameter reference

This file contains the full openLCA background dataset. It is not hand-authored — it is exported from openLCA and committed to the repository. Replace it only when the ecoinvent version or LCIA method set changes.

All impact vector objects share the same eight-field structure matching the [impact categories](#impact-categories) table above. Fields missing from the JSON default to `0.0`.

> **Unit note:** Electricity emission factors in `lca.json` are stored **per MJ** (as exported by openLCA). They are automatically multiplied by 3.6 on load to convert to per kWh. All other emission factors are in their natural units as described below.

### `metadata`

| Field | Type | Description |
|---|---|---|
| `ecoinvent_version` | string | Version string of the ecoinvent database used. |
| `lcia_method_set` | string | Name and version of the LCIA method set. |
| `description` | string | Free-text description of this dataset. |
| `created_at` | string | ISO 8601 creation timestamp. |
| `eta_avail` | float | Technical availability factor (e.g. `0.9`). Overridable per run; stored here for traceability. |

### `vehicle_production`

Emission factors for vehicle body and drivetrain production + end-of-life.

| Field | Type | Description |
|---|---|---|
| `chassis_per_kg` | impact vector | Production + EoL emissions per kg of chassis mass. |
| `electric_motor_per_kg` | impact vector | Production + EoL emissions per kg of electric motor. |
| `diesel_motor_per_unit` | impact vector | Production + EoL emissions for one complete diesel motor unit. |
| `diesel_motor_mass_kg` | float | Mass of a diesel motor in kg (fixed globally; used for chassis mass subtraction). |

### `battery`

| Field | Type | Description |
|---|---|---|
| `lfp_production_per_kg` | impact vector | LFP cell production emissions per kg. |
| `lfp_eol_transport_per_kg` | impact vector | LFP end-of-life transport emissions per kg. |
| `lfp_eol_disassembly_per_kg` | impact vector | LFP end-of-life disassembly emissions per kg. |
| `nmc_production_per_kg` | impact vector | NMC cell production emissions per kg. |
| `nmc_eol_transport_per_kg` | impact vector | NMC end-of-life transport emissions per kg. |
| `nmc_eol_disassembly_per_kg` | impact vector | NMC end-of-life disassembly emissions per kg. |
| `lifetime_years` | float | Default battery lifetime for LCA amortisation. |

The three LFP sub-fields are summed into a single `lfp_battery_per_kg` vector on load; same for NMC. Chemistry is taken from `BatteryType.chemistry` (set by `fleet.json`): strings starting with `"nmc"` select NMC factors, everything else (including `"lfp"`) selects LFP.

### `use_phase`

| Field | Type | Description |
|---|---|---|
| `electricity_per_kwh_by_year` | object | Year-keyed emission factors for grid electricity. Keys are calendar year strings (e.g. `"2025"`); values are impact vectors **per MJ** (converted to per kWh on load). Supports linear interpolation between defined years. |
| `diesel_per_kg` | impact vector | Well-to-wheel diesel emission factors per kg (production + combustion combined). |
| `efficiency_mv_to_lv` | float | MV → LV transformer efficiency (e.g. `0.99`). |
| `efficiency_lv_ac_to_dc` | float | AC/DC rectification efficiency (e.g. `0.95`). |

### `maintenance`

| Field | Type | Description |
|---|---|---|
| `iceb_per_year` | impact vector | Annual maintenance emissions per diesel bus. |
| `beb_per_year` | impact vector | Annual maintenance emissions per electric bus (already reduced relative to ICEB). |
| `beb_maintenance_reduction_factor` | float | Ratio `beb/iceb` stored for traceability; not used in calculation. |

### `charging_infrastructure`

All entries cover combined production + end-of-life (the two sub-fields are summed on load).

| Field | Type | Description |
|---|---|---|
| `control_unit_production_per_unit` | impact vector | Control unit production emissions per unit. |
| `control_unit_eol_per_unit` | impact vector | Control unit end-of-life emissions per unit. |
| `user_unit_production_per_unit` | impact vector | User unit (plug) production emissions per unit. |
| `user_unit_eol_per_unit` | impact vector | User unit end-of-life emissions per unit. |
| `power_unit.production_per_unit` | impact vector | Power unit production emissions at reference power. |
| `power_unit.eol_per_unit` | impact vector | Power unit end-of-life emissions at reference power. |
| `power_unit.ref_power_kw` | float | Reference power for the power unit LCA dataset (kW). Used as the denominator in the 0.8-exponent scaling law. |
| `transformer.production_per_unit` | impact vector | Transformer production emissions at reference power. |
| `transformer.eol_per_unit` | impact vector | Transformer end-of-life emissions at reference power. |
| `transformer.ref_power_kw` | float | Reference power for the transformer LCA dataset (kW). |
| `concrete_per_m3` | impact vector | Concrete production emissions per m³ (for outdoor terminal foundations). |

---

## `lca_overrides.json` parameter reference

Contains the per-vehicle-type values that are not derivable from openLCA (they depend on the specific bus models in use) and the analysis year. One file per analysis run.

### Top-level fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | int | Must be `1`. |
| `year` | int | Calendar year used to look up electricity emission factors from `lca.json`. Supports interpolation if the year falls between defined data points. |

### `vehicle_type_overrides`

One entry per vehicle type. Matched to the database by `name_short` = `VehicleType.name_short`. Vehicle types absent from this list receive no `lca_parameters` (a warning is emitted).

| Field | Type | Description |
|---|---|---|
| `name_short` | string | Matches `VehicleType.name_short` in the database. |
| `motor_rated_power_kw` | float | Rated motor power in kW. Used to derive electric motor mass (BEB) or for informational purposes (ICEB). |
| `motor_power_to_weight_ratio_kw_per_kg` | float \| null | Electric motor power-to-weight ratio in kW/kg. Required for BEB (used to derive motor mass); `null` for diesel. |
| `vehicle_lifetime_years` | float | Chassis and motor lifetime for LCA amortisation in years. |
| `average_consumption_kwh_per_km` | float | Average energy consumption in kWh/km. For BEB, used in the use-phase electricity calculation. For ICEB, set to `0.0` (unused). |
| `diesel_consumption_kg_per_km` | float \| null | Average diesel consumption in kg/km. Required for ICEB; `null` for BEB. |

### `charging_point_type_overrides`

One entry per charging point type (`"depot"` or `"opportunity"`). Matched by `type`.

| Field | Type | Description |
|---|---|---|
| `type` | `"depot"` \| `"opportunity"` | Matches the charging point type created by `fleet.json`. |
| `infrastructure_lifetime_years` | float | Amortisation lifetime for this infrastructure type in years. |
| `foundation_volume_per_point_m3` | float | Concrete foundation volume per charging point in m³. Typically `0.0` for indoor depot chargers and non-zero for outdoor terminal chargers. |

---

## `LCAResult`

Returned by `calculate_lca()`. Emission vectors in `items` are annual fleet totals — **not** normalised to per-revenue-km. The properties below perform normalisation on the fly.

### Kilometre data

| Attribute | Type | Description |
|---|---|---|
| `revenue_km` | `dict[str, float]` | Annual revenue-km per vehicle type, keyed by `name_short`. |
| `vehicle_km` | `dict[str, float]` | Annual vehicle-km per vehicle type, keyed by `name_short`. |

### Scalar property

| Property | Type | Description |
|---|---|---|
| `total_per_revenue_km` | `DefaultImpactVector` | Fleet-wide total emissions per revenue-km across all scopes and component types. |

### Breakdown properties

| Property | Type | Description |
|---|---|---|
| `emissions_by_scope` | `dict[LCAScope, DefaultImpactVector]` | Per-revenue-km emissions split by `PRODUCTION_AND_EOL` and `USE_PHASE`. All scopes are always present (zero vector if no contributions). |
| `emissions_by_type` | `dict[ItemType, DefaultImpactVector]` | Per-revenue-km emissions split by `VEHICLE`, `BATTERY`, `INFRASTRUCTURE`, and `ENERGY`. All types are always present. |

### Plotting

```python
result.plot_by_scope(save_path="lca_by_scope.png")
result.plot_by_type(save_path="lca_by_type.png")
```

Both methods save a stacked bar chart of GWP (kg CO₂-eq / revenue-km) by the respective breakdown dimension.
