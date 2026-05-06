"""Example script: full LCA pipeline.

Pipeline:
1. Load ``lca.json`` into ``OpenLcaData``.
2. Populate ``lca_params`` on all DB entities via ``init_lca_params``
   (reads ``lca_overrides.json`` for per-vehicle overrides and CPT
   infrastructure parameters).
3. Extract simulation data and run ``calculate_lca``.
4. Print per-vehicle-type and fleet-total GWP results.

Usage::

    python bin/example_lca.py

The DATABASE_URL environment variable is optional; the URL is hard-coded
below for convenience during development.
"""

from __future__ import annotations

from pathlib import Path

import eflips.model
from eflips.impact.lca import calculate_lca, init_lca_params
from eflips.model import VehicleType
from eflips.impact.utils import init_fleet
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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
init_fleet(scenario=SCENARIO_ID, filepath=_DEFAULTS / "fleet.json",
           delete_existing_data=True, database_url=DATABASE_URL)


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

engine = eflips.model.create_engine(DATABASE_URL)
with Session(engine) as session:
    # ---------------------------------------------------------------------------
    # Step 4: print results
    # ---------------------------------------------------------------------------

    print("\n=== LCA Results (GWP, kg CO₂-eq / revenue-km) ===\n")

    vtypes = {
        int(vt.id): vt
        for vt in session.query(VehicleType)
        .filter(VehicleType.scenario_id == SCENARIO_ID)
        .all()
    }

    header = f"{'VehicleType':<30} {'Production':>14} {'Use phase':>14} {'Nwkm/a':>14}"
    print(header)
    print("-" * len(header))

    for vtype_id in sorted(result.revenue_km):
        name = vtypes[vtype_id].name if vtype_id in vtypes else str(vtype_id)
        prod = result.production.get(vtype_id)
        use = result.use_phase.get(vtype_id)
        nwkm = result.revenue_km[vtype_id]
        prod_gwp = prod.gwp if prod is not None else float("nan")
        use_gwp = use.gwp if use is not None else float("nan")
        print(f"{name:<30} {prod_gwp:>14.4f} {use_gwp:>14.4f} {nwkm:>14.0f}")

    print("-" * len(header))
    print(f"\nInfrastructure (fleet):  {result.infrastructure.gwp:.4f} kg CO₂-eq / Nwkm")
    print(f"Total (fleet):           {result.total.gwp:.4f} kg CO₂-eq / Nwkm")
