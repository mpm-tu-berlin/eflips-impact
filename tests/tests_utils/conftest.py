"""Pytest fixtures for eflips-impact utils tests.

Uses ``tests/data/sample.db.gz`` as the test database.  ``db_engine`` is
session-scoped (loaded once per pytest session).  ``db_session`` is
function-scoped: each test receives a fresh ``Session`` backed by the shared
engine; any writes are rolled back on teardown so tests cannot contaminate
each other.
"""

from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy.orm import Session

from eflips.model import Scenario
from db_setup import setup_sqlite_engine

SCENARIO_ID = 1


@pytest.fixture(scope="session")
def db_engine(tmp_path_factory: pytest.TempPathFactory):
    engine = setup_sqlite_engine(tmp_path_factory)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Function-scoped session; all writes are rolled back on teardown."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def scenario(db_session: Session) -> Scenario:
    return db_session.query(Scenario).filter(Scenario.id == SCENARIO_ID).one()
