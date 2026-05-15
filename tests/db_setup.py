"""Shared database-setup helpers for eflips-impact test modules.

Each module conftest imports :func:`setup_sqlite_engine` from here to avoid
duplicating the bootstrapping logic.  This file is importable from any
conftest because ``pythonpath = ["tests", "."]`` is set in ``pyproject.toml``.

Design
------
Extracts ``tests/data/sample.db.gz`` to a per-module temp file, applies the
manual ``ALTER TABLE`` patches that stand in for the PostgreSQL-only alembic
migrations, then stamps alembic to ``heads``.
"""

from __future__ import annotations

import gzip
import importlib.resources
import shutil
from pathlib import Path
from typing import Any

import eflips.model
from alembic import command
from alembic.config import Config
from sqlalchemy import text

DATA_DIR = Path(__file__).parent / "data"

# Manual schema patches for SQLite – the alembic migration files contain
# PostgreSQL-specific DDL that cannot run against SQLite, so we apply the
# equivalent column additions by hand and then stamp alembic to head.
SQLITE_PATCHES: list[str] = [
    "ALTER TABLE VehicleType ADD COLUMN energy_source TEXT",
    "UPDATE \"VehicleType\" SET energy_source = 'BATTERY_ELECTRIC'",
    "ALTER TABLE VehicleType ADD COLUMN lca_parameters JSON",
    "ALTER TABLE BatteryType ADD COLUMN lca_parameters JSON",
    "ALTER TABLE ChargingPointType ADD COLUMN lca_parameters JSON",
]


def _make_alembic_cfg(engine: Any) -> Config:
    cfg = Config(str(importlib.resources.files("eflips.model").joinpath("alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.set_main_option(
        "script_location",
        str(importlib.resources.files("eflips.model").joinpath("migrations")),
    )
    return cfg


def setup_sqlite_engine(tmp_path_factory: Any) -> Any:
    """Extract sample.db.gz to a fresh temp file and return a prepared engine.

    Applies :data:`SQLITE_PATCHES` and stamps alembic to ``heads`` so the
    schema is consistent with what PostgreSQL alembic migrations produce.

    The alembic ``env.py`` in eflips-model overrides ``sqlalchemy.url`` with
    ``DATABASE_URL`` from the environment, so we temporarily unset that
    variable before calling ``command.stamp`` to prevent it from targeting the
    wrong database.
    """
    import os

    tmp = tmp_path_factory.mktemp("db") / "sample.db"
    with gzip.open(DATA_DIR / "sample.db.gz", "rb") as fin, open(tmp, "wb") as fout:
        shutil.copyfileobj(fin, fout)

    engine = eflips.model.create_engine(f"sqlite:///{tmp}")
    with engine.begin() as conn:
        for patch in SQLITE_PATCHES:
            conn.execute(text(patch))

    saved = os.environ.pop("DATABASE_URL", None)
    try:
        command.stamp(_make_alembic_cfg(engine), "heads")
    finally:
        if saved is not None:
            os.environ["DATABASE_URL"] = saved

    return engine
