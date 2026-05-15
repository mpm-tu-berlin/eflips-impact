"""Example script: full TCO pipeline.

Pipeline:
1. Init fleet topology (BatteryType + ChargingPointType rows) via ``complete_fleet``.
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

from eflips.impact.tco import calculate_tco, init_tco_params
from eflips.impact.utils import complete_fleet

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = "your_database_url_here"  # e.g. "sqlite:////path/to/your/database.db"
SCENARIO_ID = 1

# Path to the bundled example preset files.
_DEFAULTS = Path(__file__).parent.parent / "eflips" / "impact" / "defaults" / "example"
TCO_JSON = _DEFAULTS / "tco.json"

# ---------------------------------------------------------------------------
# Step 1: Init fleet
# ---------------------------------------------------------------------------
print("Step 1: Add BatteryType and ChargingPointType data if they are not in the database. "
      "Skip this step if these information are already in the database.\n")
complete_fleet(
    scenario=SCENARIO_ID,
    filepath=_DEFAULTS / "fleet.json",
    delete_existing_data=True,
    database_url=DATABASE_URL,
)
print("  Fleet topology written to DB.\n")

# ---------------------------------------------------------------------------
# Step 2: Populate tco_parameters via init_tco_parameters_from_json
# ---------------------------------------------------------------------------
print("Step 2: running init_tco_params. This will read tco.json, "
      "and write the resulting tco_parameters to the database. Skip this step if tco_parameters are already in the database.\n")
init_tco_params(
    scenario=SCENARIO_ID,
    json_path=TCO_JSON,
    database_url=DATABASE_URL,
)
print("  tco_parameters written to DB.\n")

# ---------------------------------------------------------------------------
# Step 3: Calculate TCO
# ---------------------------------------------------------------------------
print("Step 3: Running calculate_tco ...")
result = calculate_tco(scenario=SCENARIO_ID, database_url=DATABASE_URL)
print("  Done.\n")

# ---------------------------------------------------------------------------
# Step 4: Print results
# ---------------------------------------------------------------------------
per_rkm = result.tco_by_type_per_revenue_km

print("=== TCO Results (EUR / revenue-km) ===\n")
header = f"{'Category':<20} {'EUR / revenue-km':>18}"
sep = "-" * len(header)
print(header)
print(sep)

for category in sorted(per_rkm, key=lambda k: k.name):
    print(f"{category.name:<20} {per_rkm[category]:>18.4f}")

print(sep)
print(f"{'TOTAL':<20} {result.tco_per_revenue_km:>18.4f}")
print()
print(f"Project duration : {result.project_duration} years")
print(f"Annual revenue-km: {result.annual_revenue_km:,.0f}")
print(f"Total TCO (NPV)  : EUR {result.tco_over_project_duration:,.0f}")

# ---------------------------------------------------------------------------
# Step 5: Plot
# ---------------------------------------------------------------------------
result.plot(use_revenue_km=True, save_path="tco_by_type.png")
print("Plot saved to tco_by_type.png")
