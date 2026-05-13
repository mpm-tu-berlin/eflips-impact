# eflips-impact

**eflips-impact** is part of the [eFLIPS](https://github.com/mpm-tu-berlin) tool family for electric bus fleet simulation. It provides two impact analysis modules operating on eFLIPS simulation results:

- **TCO** — Total Cost of Ownership, including capital expenditure (vehicles, batteries, charging infrastructure) and operational expenditure (energy, staff, maintenance, insurance, taxes).
- **LCA** — Life Cycle Assessment of greenhouse gas emissions (GWP, kg CO₂-eq), following ISO 14040/14044. Functional unit: revenue-kilometre (Nutzwagenkilometer).

Both modules read simulation data from an eFLIPS database and accept scenario parameters from JSON configuration files.

---

## Installation

### From PyPI

```bash
pip install eflips-impact
```

### From source

```bash
git clone https://github.com/mpm-tu-berlin/eflips-impact.git
cd eflips-impact
pip install .
```

For development (includes linting, type checking, and docs tools):

```bash
pip install -e ".[dev]"
```

> **Python version**: 3.10 – 3.13.

---

## Quick start

Two example scripts under `bin/` demonstrate the full pipeline end-to-end.

### TCO example

```bash
python bin/example_tco.py
```

Runs the following steps:

1. Initialises fleet topology (battery types, charging point types) from `fleet.json`.
2. Writes TCO parameters to the database from `tco.json`.
3. Calculates TCO and prints a per-category cost table (EUR / revenue-km).
4. Saves a stacked bar chart to `tco_by_type.png`.

### LCA example

```bash
python bin/example_lca.py
```

Runs the following steps:

1. Initialises fleet topology from `fleet.json`.
2. Writes LCA parameters to the database from `lca.json` and `lca_overrides.json`.
3. Calculates LCA and prints GWP results by lifecycle scope and component type.
4. Saves charts to `lca_by_scope.png` and `lca_by_type.png`.

Before running, set the `DATABASE_URL` variable at the top of each script (or via the `DATABASE_URL` environment variable) to point to a populated eFLIPS simulation database.

---

## Input data

eflips-impact requires two types of input:

### 1. eFLIPS simulation data

A PostgreSQL database produced by an eFLIPS simulation run, containing `VehicleType`, `Trip`, `Route`, `Event`, `Area`, `Station`, and related tables. The database URL is passed to all entry-point functions via `database_url` or the `DATABASE_URL` environment variable.

### 2. JSON parameter files

Scenario-specific parameters are supplied through four JSON files. Example files for all four are provided under `eflips/impact/defaults/example/`:

| File | Purpose |
|---|---|
| `fleet.json` | Defines battery types and charging point types; assigns them to vehicle types, depot areas, and opportunity charging stations. |
| `tco.json` | Provides TCO parameters: procurement costs, useful life, energy prices, staff costs, maintenance rates, and financial assumptions. See the *TCO Parameter Reference* (planned) for a full field description. |
| `lca.json` | Raw openLCA matrix export used as the LCA background data source. |
| `lca_overrides.json` | Per-vehicle-type overrides for LCA inputs (motor power, energy consumption) and the analysis year. See the *LCA Parameter Reference* (planned) for a full field description. |

Copy and adapt the example files to your scenario. The matching between JSON entries and database rows uses string keys (`name_short` for vehicle types, `type` for charging infrastructure) — never database-assigned integer IDs.

---

## Calculation workflow

```
eFLIPS simulation DB
        │
        ▼
  init_fleet()                        ← fleet.json
  (creates BatteryType /
   ChargingPointType rows)
        │
        ├─────────────────────────────────────────┐
        │                                         │
        ▼                                         ▼
  init_tco_params()  ← tco.json     init_lca_parameters()  ← lca.json
  (writes tco_parameters                (writes lca_parameters          + lca_overrides.json
   to DB entities)                       to DB entities)
        │                                         │
        ▼                                         ▼
  calculate_tco()                       calculate_lca()
        │                                         │
        ▼                                         ▼
   TCOResult                              LCAResult
```

`init_fleet()` must be called once before the parameter-init functions. The two parameter-init steps (`init_tco_params`, `init_lca_parameters`) and the two calculation steps are independent and can be run separately.

### Public API

```python
from eflips.impact.utils import init_fleet
from eflips.impact.tco import init_tco_params, calculate_tco
from eflips.impact.lca import init_lca_parameters, calculate_lca

# 1. Fleet topology
init_fleet(scenario=1, filepath="fleet.json", delete_existing_data=True, database_url=DATABASE_URL)

# 2a. TCO parameters
init_tco_params(scenario=1, json_path="tco.json", database_url=DATABASE_URL)

# 2b. LCA parameters
init_lca_parameters(scenario=1, lca_json_path="lca.json", overrides_json_path="lca_overrides.json", database_url=DATABASE_URL)

# 3. Calculate
tco_result = calculate_tco(scenario=1, database_url=DATABASE_URL)
lca_result = calculate_lca(scenario=1, database_url=DATABASE_URL)

# 4. Results
print(tco_result.tco_per_revenue_km)   # EUR / revenue-km
print(lca_result.total_per_revenue_km.gwp)  # kg CO₂-eq / revenue-km

# 5. Plots
tco_result.plot(use_revenue_km=True, save_path="tco.png")
lca_result.plot_by_scope(save_path="lca_scope.png")
lca_result.plot_by_type(save_path="lca_type.png")
```

---

## Development

```bash
# Format
black eflips/

# Type check
mypy eflips --explicit-package-bases --strict

# Tests
pytest
```

---

## License

See [LICENSE](LICENSE).
