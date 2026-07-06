# TCO — Total Cost of Ownership

## How TCO is calculated

TCO aggregates all capital and operational expenditure over a project horizon and converts it to a single specific cost figure: **EUR per revenue-kilometre**.

### Cost categories

**CAPEX** — discounted procurement costs, replacing assets when their useful life expires within the project duration.

| Category | Quantity source | Unit cost source |
|---|---|---|
| Vehicles | `ceil(n_vehicles_in_simulation / eta_avail)` per vehicle type | `procurement_cost` in `vehicle_types` |
| Batteries | Same fleet size as vehicle | `procurement_cost` (EUR/kWh) × `VehicleType.battery_capacity` (kWh) |
| Charging points | Peak simultaneous vehicles per area/station from simulation | `procurement_cost` in `charging_point_types` |
| Charging infrastructure | Number of depot stations / opportunity-charging stations from simulation | `procurement_cost` in `charging_infrastructure` |

`eta_avail` (technical availability, default 0.9) inflates fleet size to account for vehicles in maintenance.

**OPEX** — annual costs, escalated year-by-year and discounted to present value.

| Category | Driver |
|---|---|
| Staff | Total annual driver hours (driving + opportunity charging + standby-at-stop) × `staff_cost` |
| Energy | Annual vehicle-km per type × per-type consumption × `fuel_cost` |
| Vehicle maintenance | Annual vehicle-km by energy source × `vehicle_maint_cost` |
| Infrastructure maintenance | Total charging slots × `infra_maint_cost` |
| Insurance | Total fleet size × `insurance` per vehicle |
| Taxes | Total fleet size × `taxes` per vehicle |

### Discounting and escalation

Each CAPEX item is converted to an **annuity** using `interest_rate`, then discounted to the base year using `inflation_rate`. Replacements within the project duration are included at their escalated price (`cost_escalation`). When the last replacement's useful life extends beyond the project end, only the fraction actually used is charged.

Each OPEX item is escalated annually by its category-specific rate from `cost_escalation_rate`, then discounted to the base year using `inflation_rate`.

### Functional unit

The final result is divided by `annual_revenue_km × project_duration`, yielding **EUR per revenue-kilometre**.

---

## `tco.json` parameter reference

The file contains five top-level keys. All monetary values are in **EUR**; all rates are **annual fractions** (e.g. `0.04` = 4 %).

### `scenario`

Scenario-level financial parameters applied to the whole fleet.

| Field | Type | Description |
|---|---|---|
| `project_duration` | int | Planning horizon in years. |
| `interest_rate` | float | Nominal interest rate (includes inflation) used to annualise CAPEX. |
| `inflation_rate` | float | Discount rate used to convert future cash flows to present value. |
| `eta_avail` | float | Technical availability factor (default `0.9`). Fleet size = `ceil(n_simulated / eta_avail)`. |
| `staff_cost` | float | Driver cost in EUR per hour. |
| `fuel_cost` | object | Energy prices. Keys: `"diesel"` (EUR/l), `"electricity"` (EUR/kWh). |
| `vehicle_maint_cost` | object | Vehicle maintenance rate. Keys: `"diesel"` and `"electricity"` (EUR/vehicle-km). |
| `infra_maint_cost` | float | Annual maintenance cost per charging slot (EUR/year). |
| `cost_escalation_rate` | object | Annual cost escalation rates by category (see below). |
| `insurance` | float | Annual insurance cost per vehicle (EUR/year). |
| `taxes` | float | Annual taxes per vehicle (EUR/year). |

**`cost_escalation_rate` keys:**

| Key | Applied to |
|---|---|
| `general` | Vehicle maintenance, infrastructure maintenance, taxes |
| `staff` | Staff cost |
| `diesel` | Diesel energy cost |
| `electricity` | Electricity energy cost |
| `insurance` | Insurance cost |

---

### `vehicle_types`

One entry per vehicle type. Matched to the database by `name_short` = `VehicleType.name_short`.

| Field | Type | Description |
|---|---|---|
| `name_short` | string | Matches `VehicleType.name_short` in the database. |
| `useful_life` | int | Asset lifetime in years. Triggers replacement when exceeded within `project_duration`. |
| `procurement_cost` | float | Total vehicle purchase price (EUR per vehicle). |
| `cost_escalation` | float | Annual change in purchase price (negative = cost reduction over time). |
| `average_electricity_consumption` | float \| omit | Average energy use (kWh/vehicle-km). Set for battery-electric vehicles; omit for diesel. |
| `average_diesel_consumption` | float \| omit | Average fuel use (l/vehicle-km). Set for diesel vehicles; omit for electric. Exactly one of the two consumption fields must be present. |

---

### `battery_types`

One entry per battery-electric vehicle type. Matched by `vehicle_name_short` = `VehicleType.name_short`.

| Field | Type | Description |
|---|---|---|
| `vehicle_name_short` | string | Matches `VehicleType.name_short` of the corresponding BEB. |
| `procurement_cost` | float | Battery purchase price in **EUR/kWh**. Total cost = `procurement_cost × VehicleType.battery_capacity`. |
| `useful_life` | int | Battery lifetime in years. |
| `cost_escalation` | float | Annual change in battery price (typically negative). |

---

### `charging_point_types`

One entry per charging point type (`"depot"` or `"opportunity"`). The quantity of charging points is derived from simulation peak occupancy — it does not appear in this file.

| Field | Type | Description |
|---|---|---|
| `type` | `"depot"` \| `"opportunity"` | Matches the charging point type created by `fleet.json`. |
| `procurement_cost` | float | Cost per individual charging point unit (EUR). |
| `useful_life` | int | Charger lifetime in years. |
| `cost_escalation` | float | Annual change in charger price. |

---

### `charging_infrastructure`

Civil and building infrastructure costs, separate from the individual charger units above. A `type` may have one **default** entry (applied to every station of that type) plus any number of **override** entries that target specific stations by id.

| Field | Type | Description |
|---|---|---|
| `type` | `"depot"` \| `"station"` | `"depot"` targets depot stations; `"station"` targets opportunity-charging stations. |
| `procurement_cost` | float | Civil infrastructure cost per site (EUR). The number of sites is counted from the simulation. |
| `useful_life` | int | Infrastructure lifetime in years. |
| `cost_escalation` | float | Annual change in construction cost. |
| `station_ids` | list[int] \| omit | Optional. `Station.id` values this entry applies to. Omit to make the entry the type's default (applies to all stations of that type). |

**Default vs. override entries.** For each `type`:

- The entry with **no** `station_ids` is the *default* — its parameters are written to every station of that type. At most one default per type is allowed (more than one raises `ValueError`).
- Each entry **with** `station_ids` is an *override* — its parameters are written only to the listed stations, taking precedence over the default. Express "these stations get A, all others of this type get B" as one override entry (A, with `station_ids`) plus one default entry (B, without).

Every affected station is resolved to a single parameter set *before* anything is written, so the result does not depend on the order of entries in the list. An override `station_id` that is not actually a station of its declared `type` in the scenario is still written, but emits a warning; an id that matches no `Station` in the scenario is skipped with a warning.

**Example** — a default depot cost plus a higher-cost override for three specific depot stations:

```json
"charging_infrastructure": [
  { "type": "depot", "procurement_cost": 2397989.95, "useful_life": 20, "cost_escalation": 0.02 },
  { "type": "depot", "procurement_cost": 3000000.0, "useful_life": 20, "cost_escalation": 0.02,
    "station_ids": [1102005186, 1102005187, 1102005188] },
  { "type": "station", "procurement_cost": 269773.87, "useful_life": 20, "cost_escalation": 0.02 }
]
```

> **Note:** `charging_point_types` and `charging_infrastructure` both use a `type` field, but with different vocabularies. `charging_point_types` uses `"depot"` / `"opportunity"` (matching `fleet.json`); `charging_infrastructure` uses `"depot"` / `"station"` (referring to physical sites).

---

## `TCOResult`

Returned by `calculate_tco()`. All cost figures are **net present values in EUR** discounted to the base year.

### Scalar properties

| Property | Type | Description |
|---|---|---|
| `total_capex` | float | Sum of all CAPEX items (vehicles + batteries + infrastructure). |
| `total_opex` | float | Sum of all OPEX items (staff + energy + maintenance + insurance + taxes). |
| `tco_over_project_duration` | float | Total TCO = `total_capex + total_opex`. |
| `tco_per_revenue_km` | float | Specific TCO in EUR/revenue-km (primary functional unit). |
| `tco_per_vehicle_km` | float | Specific TCO in EUR/vehicle-km (includes dead runs). |
| `annual_revenue_km` | float | Annual fleet revenue-km extracted from simulation. |
| `annual_vehicle_km` | float | Annual fleet vehicle-km extracted from simulation. |

### Breakdown properties

| Property | Type | Description |
|---|---|---|
| `tco_by_type` | `dict[CapexItemType \| OpexItemType, float]` | Total NPV cost per category. Categories: `VEHICLE`, `BATTERY`, `INFRASTRUCTURE` (CAPEX); `STAFF`, `ENERGY`, `MAINTENANCE`, `OTHER` (OPEX). |
| `tco_by_type_per_revenue_km` | `dict[CapexItemType \| OpexItemType, float]` | Same breakdown, normalised to EUR/revenue-km. |
| `tco_by_type_per_vehicle_km` | `dict[CapexItemType \| OpexItemType, float]` | Same breakdown, normalised to EUR/vehicle-km. |

### Plotting

```python
result.plot(use_revenue_km=True, save_path="tco_by_type.png")
```

Saves a stacked bar chart of specific cost by category. Set `use_revenue_km=False` to normalise by vehicle-km instead.
