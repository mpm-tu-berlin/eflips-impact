# eflips-impact
This project is a combination of eflips-lca and eflips-tco, which goal is to calculate lifecycle assessment and 
total cost of ownership for eFLIPS electric and diesel bus fleet simulations, following ISO 14040/14044. 
Functional unit: revenue-kilometre (Nutzwagenkilometer).


## Project layout

```
eflips/impact/
    /tco       # Original eflips-tco code, refactored to fit the new structure.
               # Writes Scenario/VehicleType/BatteryType/ChargingPointType/Station.tco_parameters
               # on existing rows. Does NOT create or delete rows.
    /lca       # Original eflips-lca code, refactored to fit the new structure.
               # Writes VehicleType/BatteryType/ChargingPointType.lca_params on existing
               # rows. Does NOT create or delete rows.
    /utils     # Shared utilities. See section below.
    /defaults
        /example/
            fleet.json                     # BatteryType + ChargingPointType row creation/assignment
            tco.json                       # TCO parameters (TcoParamSet shape)
            lca.json                       # raw openLCA dump (current bus_results.json content)
            vehicle_type_overrides.json    # per-VehicleType overrides + year for LCA
```

## /utils design

Two responsibilities, two modules. Anything that does not fit one of these belongs in `tco/` or `lca/`, not here.

### `utils/fleet_init.py` — fleet topology (BatteryType, ChargingPointType)

Reads `fleet.json` and brings the BatteryType / ChargingPointType rows of a scenario into the state described by the file. Owns *only* row creation and FK assignment; does not touch `tco_parameters` or `lca_params` columns.

**Public API**:

```python
def init_fleet(
    scenario: Union[Scenario, int, Any],
    filepath: Path,
    delete_existing_data: bool,
    database_url: Optional[str] = None,
) -> None: ...
```

Scenario resolution is delegated to the shared `eflips.impact.utils.create_session` context manager:

- If `scenario` is a `Scenario`, the helper yields its bound session and does not commit or close it (caller owns the transaction).
- If `scenario` is an `int` or any object with an `id` attribute, `database_url` (or `os.environ["DATABASE_URL"]`) is used to build `Session(create_engine(url))` locally; on success the session is committed, then both session and engine are disposed.

The legacy `eflips.impact.tco.util.create_session` is removed; TCO and LCA entry points import the helper from `eflips.impact.utils` instead.

**Behavior**:

1. **Pre-flight validation** (always, before any mutation). On any failure: `warnings.warn(UserWarning, ...)` and `return None`. No partial state.

   - **BatteryType validation**: filter DB VehicleTypes by `energy_source == BATTERY_ELECTRIC`, take the set of `name_short`. Compare against the `vehicle_name_short` set in fleet.json's battery entries. If DB ⊄ JSON (i.e. some BEB VehicleType has no matching battery in the JSON), warn and return. Extra entries in JSON whose `vehicle_name_short` does not match any BEB VehicleType are silently skipped (not written to DB).
   - **ChargingPointType validation**: detect actual charging in the DB:
     - `has_depot`: any `Area` in the scenario whose `Process.electric_power IS NOT NULL`.
     - `has_opportunity`: any `Event.event_type == CHARGING_OPPORTUNITY` in the scenario.
     - Build the expected set: `{"depot"}` if `has_depot`, plus `{"opportunity"}` if `has_opportunity`.
     - The set of `type` values in fleet.json's CPT entries must equal this expected set. Otherwise warn and return.
   - **Chemistry validation**: every BatteryType entry must have `chemistry` in `{"lfp", "nmc"}` (lowercase, strict). Unknown chemistry → warn and return. NMC variants (NMC811, NMC622) are not yet supported.
   - **Required fields**: BatteryType entries in fleet.json *must* set `chemistry` and `specific_mass`. fleet.json uses its own dataclass; do not reuse `BatteryTypeTCOParameter` (whose `chemistry`/`specific_mass` fields have been removed — TCO no longer creates BatteryType rows).

2. **Existing-data handling**:
   - `delete_existing_data=False`: if any BatteryType or ChargingPointType already exists in the scenario, `warnings.warn("Existing BatteryType / ChargingPointType found in scenario X; pass delete_existing_data=True to replace, or skip this call if topology is already initialized.")` and `return None`. If no existing rows, proceed with creation.
   - `delete_existing_data=True`: in a single transaction (the `create_session` with-block, or the caller's existing session):
     1. NULL `VehicleType.battery_type_id` for all VehicleTypes in scenario.
     2. NULL `Area.charging_point_type_id` and `Station.charging_point_type_id` for all rows in scenario.
     3. Delete all BatteryType rows where `scenario_id == scenario.id`.
     4. Delete all ChargingPointType rows where `scenario_id == scenario.id`.
     5. Create new BatteryType rows from fleet.json (skipping JSON entries with no matching BEB VehicleType). Match by `vehicle_name_short` to set `VehicleType.battery_type_id`.
     6. Create new ChargingPointType rows from fleet.json. Assignment:
        - `type == "depot"` → assign to every `Area` where `Process.electric_power IS NOT NULL` and `scenario_id == scenario.id`.
        - `type == "opportunity"` → assign to every `Station` referenced by a `CHARGING_OPPORTUNITY` event in this scenario.

3. **Scenario-scoping is mandatory**: every query filters by `scenario.id`. A bare `session.query(BatteryType).all()` would corrupt other scenarios in the same DB.

4. **Hard constraints inherited from existing TCO code**: at most one depot ChargingPointType and at most one opportunity ChargingPointType per scenario. fleet.json's schema therefore allows at most one CPT entry per `type`. If multi-CPT-per-type is needed in the future, the schema and the assignment logic both need to change.

**Open issue (intentionally deferred)**: when `delete_existing_data=True`, existing `tco_parameters` and `lca_params` on VehicleType / Area / Station rows reference the deleted BatteryType / ChargingPointType and become stale. For now this is documented in the function's docstring as a caller responsibility ("re-run init_tco_parameters and populate_lca_params after"). A future revision should detect non-empty stale params and warn explicitly. Do not auto-clear.

### `utils/extraction.py` — low-level simulation queries

Pure read-only functions that translate raw simulation data (Trip, Route, Event, Area, Station) into per-vehicle-type / per-area / per-station scalars. No domain dataclasses (those stay in `lca/` and `tco/`); return plain dicts, ORM objects, or stdlib types.

Exposed queries (to be finalized as `tco/` and `lca/` are refactored to depend on them):

- vehicle kilometers and revenue kilometers (per vehicle type and fleet total)
- driving hours
- peak charging power and peak simultaneous occupancy per Area and per Station (wraps `eflips.eval.power_and_occupancy`)
- annual scaling factor from a simulation window
- simulation period detection (earliest `time_start` to latest `time_end` of `EventType.DRIVING`)

The LCA-specific aggregation (`ScenarioSimData`, `_annual_scaling_factor`) and TCO-specific aggregation (`load_capex_items_*`) stay in their respective domain modules and call into `extraction.py`. Share the bricks, not the houses.

### `utils/` — also home for

- `create_session` (moved from `tco/util.py`) — generic DB-session context manager, used by `fleet_init`, `tco/data_queries`, `tco/tco_calculator`, and `lca/`.

Domain-specific value types (`ImpactVector`, `DefaultImpactVector`, `plot_tco_comparison`) stay in `lca/util.py` and `tco/util.py` respectively. Do not bulk-move "util.py" files into `utils/`.

### Import direction

`utils/` may import from `eflips.model`, `eflips.eval`, `sqlalchemy`, and stdlib only. Per-module: `fleet_init.py` and `session.py` need `eflips.model` + `sqlalchemy`; `extraction.py` is the only consumer of `eflips.eval`. `tco/` and `lca/` import from `utils/` + `eflips.model` + their own internal modules. Never the reverse — `utils/` must not import from `tco/` or `lca/`, ever.

### Conventions

- User-facing soft failures: `warnings.warn(..., UserWarning)` (catchable in tests, promotable to error). Do not use `logger.warning()` for these.
- Return type for mutators: `-> None`. No ad-hoc int return codes.
- Scenario parameter type: `Union[Scenario, int, Any]`, resolved via `eflips.impact.utils.create_session`.
- Chemistry strings: lowercase, strict allow-list `{"lfp", "nmc"}`, validated at fleet.json load.

## /defaults design

Four JSON files per preset, each with its own concern. Independent change cycles. All files carry `"schema_version": 1` for future migrations.

### File responsibilities

| File | Purpose | Authoritative source | Change cadence |
|---|---|---|---|
| `fleet.json` | BatteryType + ChargingPointType row creation, FK assignment to VehicleType / Area / Station | hand-curated per scenario | rarely (when fleet topology changes) |
| `tco.json` | Scenario / VehicleType / BatteryType / ChargingPointType / Station `tco_parameters` JSONB content | hand-curated per region/operator | when cost surveys update |
| `lca.json` | Raw openLCA matrix export — *current `bus_results.json` content moves here verbatim* | exported from openLCA | when ecoinvent version or LCIA method changes |
| `vehicle_type_overrides.json` | Per-VehicleType LCA overrides (motor power, consumption) and analysis `year` | hand-curated per scenario | when fleet config or analysis year changes |

Note: `lca.json` is **not** a thin overlay; it carries the full openLCA dump (column/index/data matrix). The thin per-scenario knobs are in `vehicle_type_overrides.json`.

### Cross-file matching keys

All files use **string matching keys**, never database-assigned integer ids:

| Key | Found in | Resolves to |
|---|---|---|
| `vehicle_name_short` (battery) | fleet.json, tco.json | `VehicleType.name_short` → `VehicleType.battery_type_id` |
| `name_short` (vehicle_type) | tco.json, vehicle_type_overrides.json | `VehicleType.name_short` |
| `type` (CPT) | fleet.json, tco.json | `"depot"` (→ Areas with charging Process) or `"opportunity"` (→ Stations with `CHARGING_OPPORTUNITY` events) |
| `type` (infrastructure) | tco.json only | `"depot"` (→ Stations linked via Depot) or `"station"` (→ charging Stations) — **different vocabulary, same word as CPT** |

The init functions for tco and lca cross-check that their `vehicle_name_short` / `type` values agree with the topology fleet.json built. Mismatches → `warnings.warn(UserWarning, ...)` + `return None`, same pattern as `init_fleet`.

### vehicle_type_overrides.json shape

```json
{
  "schema_version": 1,
  "year": 2025,
  "vehicle_type_overrides": [
    {
      "name_short": "EN",
      "motor_rated_power_kw": 200.0,
      "average_consumption_kwh_per_km": 1.2,
      "diesel_consumption_kg_per_km": null
    }
  ]
}
```

`diesel_consumption_kg_per_km`: `null` for BEB, required for diesel. Validated against `VehicleType.energy_source` (read from the DB row) at load time.

### Required code change (parked)

The current `populate_lca_params_from_data` keys overrides by `VehicleType.id` (`dict[int, VehicleTypeOverrides]` — see `eflips/impact/lca/open_lca_data.py:843-881`). This does **not** work for hand-authored JSON: ids are auto-increment PKs that change across DB rebuilds. Switch the key to `name_short`:

- Either change `populate_lca_params_from_data` signature to `dict[str, VehicleTypeOverrides]`, or add a wrapper that resolves `name_short` → `id` before calling the existing function.
- Update tests in `tests/tests_lca/test_open_lca_data.py` (`test_populate_from_data`, `test_populate_from_file`, `test_interpolated_electricity_year`, `test_missing_override_warns`) to use `name_short` keys.
- Drop the hard-coded id list in `tests/tests_lca/conftest.py:187-191`; switch to a `name_short`-keyed dict.

This change is required before `vehicle_type_overrides.json` can be loaded end-to-end.

### Conventions

- Match by string keys (`name_short`, `vehicle_name_short`, `type`), never by `id`. Database-assigned PKs are not stable across rebuilds.
- One preset folder = one full configuration. No file-level fallbacks; users supply all four files per preset.
- `lca.json` and `vehicle_type_overrides.json` together produce one analysis run for one year. Multi-year evaluation = multiple `vehicle_type_overrides.json` files (one per year).
- Diesel VehicleTypes are not referenced in `fleet.json` (no battery, no charging assignment) but **are** in `tco.json` and `vehicle_type_overrides.json`.

### Open issues (parked, raise if asked)

- `lca.json` currently coexists with two near-duplicate variants (`bus_results_added_transformer.json`, `bus_results_orig.json`) under `eflips/impact/lca/open_lca_data/`. Decide canonical and remove the others.
- `make_charging_point_type_lca_params()` returns identical params for every CPT in a scenario (no per-depot vs per-opportunity differentiation). If this matters, schema needs CPT overrides keyed by `type`. Park as known limitation.

## Key dependencies

- `eflips-model` — ORM classes (`VehicleType`, `BatteryType`, `Area`, `Station`, etc.)
- `eflips-eval` — `power_and_occupancy()` for peak charging power/occupancy extraction
- `EnergySource` enum from `eflips.model` is used as dict key type in `maintenance_per_year`

## Development rules

- `poetry` is in use. If your `python` in the $PATH looks weird, run `$(poetry env activate)`. Current venv is Python 3.13 (constraint `>=3.10,<3.14`).
- Code formatted with `black`
- All code must have type annotations and pass `mypy eflips --explicit-package-bases --strict`
- All methods need a Google-Style (markdown) docstring
- All code has tests using `pytest`

        

