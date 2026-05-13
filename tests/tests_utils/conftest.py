"""Pytest fixtures for eflips.impact.utils tests.

Each test gets a fresh extract of the sample SQLite DB so that mutations in
one test do not leak into the next. The schema upgrade mirrors the one in
``tests/tests_lca/conftest.py``.
"""

from __future__ import annotations

import gzip
import importlib.resources
import shutil
from pathlib import Path
from typing import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

import eflips.model
from eflips.model import Scenario

DATA_DIR = Path(__file__).parent.parent / "tests_lca" / "data"
SCENARIO_ID = 1


def _make_alembic_cfg(engine: eflips.model.sqlalchemy.Engine) -> Config:  # type: ignore[name-defined]
    """Build an alembic Config pointing at the eflips-model migration scripts.

    Args:
        engine: The engine whose URL alembic should target.

    Returns:
        A configured ``alembic.config.Config``.
    """
    cfg = Config(str(importlib.resources.files("eflips.model").joinpath("alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.set_main_option(
        "script_location",
        str(importlib.resources.files("eflips.model").joinpath("migrations")),
    )
    return cfg


@pytest.fixture
def db_engine(tmp_path: Path):  # type: ignore[type-arg]
    """Function-scoped engine backed by a fresh extract of sample.db.

    Each test gets its own DB file. Schema upgrades match
    ``tests/tests_lca/conftest.py``.
    """
    db_path = tmp_path / "sample.db"
    with (
        gzip.open(DATA_DIR / "sample.db.gz", "rb") as f_in,
        open(db_path, "wb") as f_out,
    ):
        shutil.copyfileobj(f_in, f_out)

    engine = eflips.model.create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE VehicleType ADD COLUMN energy_source TEXT"))
        conn.execute(
            text("UPDATE \"VehicleType\" SET energy_source = 'BATTERY_ELECTRIC'")
        )
        conn.execute(text("ALTER TABLE VehicleType ADD COLUMN lca_parameters JSON"))
        conn.execute(text("ALTER TABLE BatteryType ADD COLUMN lca_parameters JSON"))
        conn.execute(text("ALTER TABLE ChargingPointType ADD COLUMN lca_parameters JSON"))

    command.stamp(_make_alembic_cfg(engine), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:  # type: ignore[type-arg]
    """Function-scoped session bound to ``db_engine``.

    Yields the open session; the caller decides whether to commit. The
    session is rolled back and closed on teardown so per-test mutations
    do not leak.
    """
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def scenario(db_session: Session) -> Scenario:
    """Return the single Scenario row from sample.db (id=1)."""
    return db_session.query(Scenario).filter(Scenario.id == SCENARIO_ID).one()
