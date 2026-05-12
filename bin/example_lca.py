"""Example script: full LCA pipeline.

Pipeline:
1. Load ``lca.json`` into ``OpenLcaData``.
2. Populate ``lca_params`` on all DB entities via ``init_lca_params``
   (reads ``lca_overrides.json`` for per-vehicle overrides and CPT
   infrastructure parameters).
3. Extract simulation data and run ``calculate_lca``.
4. Print per-scope and fleet-total GWP results.

Usage::

    python bin/example_lca.py

The DATABASE_URL environment variable is optional; the URL is hard-coded
below for convenience during development.
"""

from __future__ import annotations

from pathlib import Path

from eflips.impact.lca import calculate_lca, init_lca_params
from eflips.impact.utils import init_fleet

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# TODO delete this before release
DATABASE_URL = "sqlite:////home/shuyao/PycharmProjects/eflips-data/Simulation_term.db"
SCENARIO_ID = 1

# Path to the bundled example preset files.
_DEFAULTS = Path(__file__).parent.parent / "eflips" / "impact" / "defaults" / "example"
LCA_JSON = _DEFAULTS / "lca.json"
LCA_OVERRIDES_JSON = _DEFAULTS / "lca_overrides.json"


# ---------------------------------------------------------------------------
# Step 1: Init fleet
# ---------------------------------------------------------------------------
print("Step 1: Init fleet ...")
init_fleet(
    scenario=SCENARIO_ID,
    filepath=_DEFAULTS / "fleet.json",
    delete_existing_data=True,
    database_url=DATABASE_URL,
)


# ---------------------------------------------------------------------------
# Step 2: populate lca_params via init_lca_params
# ---------------------------------------------------------------------------
init_lca_params(
    scenario=SCENARIO_ID,
    lca_json_path=LCA_JSON,
    overrides_json_path=LCA_OVERRIDES_JSON,
    database_url=DATABASE_URL,
)
print("  lca_params written to DB.\n")

# ---------------------------------------------------------------------------
# Step 3: calculate LCA
# ---------------------------------------------------------------------------
print("Step 3: running calculate_lca ...")
result = calculate_lca(scenario=SCENARIO_ID, database_url=DATABASE_URL)

# ---------------------------------------------------------------------------
# Step 4: print results
# ---------------------------------------------------------------------------
print("\n=== LCA Results (GWP, kg CO₂-eq / revenue-km) ===\n")

total_rkm = sum(result.revenue_km.values())
by_scope = result.emissions_by_scope
by_type = result.emissions_by_type
total = result.total_per_revenue_km

header = f"{'Category':<30} {'GWP (kg CO₂-eq/Nwkm)':>24}"
sep = "-" * (30 + 1 + 24)

print("-- By lifecycle scope --")
print(header)
print(sep)
for scope, iv in by_scope.items():
    print(f"{scope.name:<30} {iv.gwp:>24.6f}")

print("\n-- By component type --")
print(header)
print(sep)
for itype, iv in by_type.items():
    print(f"{itype.name:<30} {iv.gwp:>24.6f}")

print(sep)
print(f"\n{'Total (fleet):':<30} {total.gwp:>24.6f} kg CO₂-eq / Nwkm")
print(f"{'Total fleet Nwkm/a:':<30} {total_rkm:>24.0f}")
