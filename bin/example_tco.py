"""Example script: full TCO pipeline.

Pipeline:
1. Init fleet topology (BatteryType + ChargingPointType rows) via ``init_fleet``.
2. Populate ``tco_parameters`` on all DB entities via ``init_tco_parameters_from_json``
   (reads ``tco.json`` for scenario / vehicle / battery / CPT / station parameters).
3. Run ``calculate_tco`` to get cost-per-km by category.
4. Print per-category and total TCO results.

Usage::

    python bin/example_tco.py

The DATABASE_URL environment variable is optional; the URL is hard-coded
below for convenience during development.
"""

from __future__ import annotations

from pathlib import Path

from eflips.impact.tco import calculate_tco, init_tco_parameters_from_json
from eflips.impact.utils import init_fleet

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = "sqlite:////home/shuyao/PycharmProjects/eflips-data/Simulation_term.db"
SCENARIO_ID = 1

# Path to the bundled example preset files.
_DEFAULTS = Path(__file__).parent.parent / "eflips" / "impact" / "defaults" / "example"
TCO_JSON = _DEFAULTS / "tco.json"

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
print("  Fleet topology written to DB.\n")

# ---------------------------------------------------------------------------
# Step 2: Populate tco_parameters via init_tco_parameters_from_json
# ---------------------------------------------------------------------------
print("Step 2: Writing tco_parameters ...")
init_tco_parameters_from_json(
    scenario=SCENARIO_ID,
    json_path=TCO_JSON,
    database_url=DATABASE_URL,
)
print("  tco_parameters written to DB.\n")

# ---------------------------------------------------------------------------
# Step 3: Calculate TCO
# ---------------------------------------------------------------------------
print("Step 3: Running calculate_tco ...")
result_per_vkm = calculate_tco(scenario=SCENARIO_ID, database_url=DATABASE_URL, use_revenue_km=False)
print("  Done.\n")

# ---------------------------------------------------------------------------
# Step 4: Print results
# ---------------------------------------------------------------------------
print("=== TCO Results (EUR / vehicle-km) ===\n")

header = f"{'Category':<20} {'EUR / vehicle-km':>18}"
print(header)
print("-" * len(header))

for category in sorted(result_per_vkm):
    print(f"{category:<20} {result_per_vkm[category]:>18.4f}")

print("-" * len(header))
print(f"{'TOTAL':<20} {sum(result_per_vkm.values()):>18.4f}")
print()
print("Unit: EUR per vehicle-km over the full project duration.")
