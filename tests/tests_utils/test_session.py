"""Tests for :func:`eflips.impact.utils.session.create_session`."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from eflips.model import Scenario
from eflips.impact.utils import create_session

SCENARIO_ID = 1


class TestPolymorphicScenarioParam:
    """``create_session`` accepts Scenario / int / object-with-id."""

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Scenario object"):
            with create_session("not-a-scenario"):
                pass

    def test_int_without_database_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValueError, match="No database URL"):
            with create_session(1):
                pass

    def test_unbound_scenario_raises(
        self, db_session: Session, scenario: Scenario
    ) -> None:
        db_session.expunge(scenario)
        with pytest.raises(ValueError, match="not bound"):
            with create_session(scenario):
                pass

    def test_passing_bound_scenario_yields_its_session(
        self, db_session: Session, scenario: Scenario
    ) -> None:
        with create_session(scenario) as (session, resolved):
            assert session is db_session
            assert resolved is scenario


class TestObjectWithIdAttribute:
    """``create_session`` accepts any object exposing ``.id``."""

    def test_object_with_id_without_database_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)

        class FakeScenario:
            id = SCENARIO_ID

        with pytest.raises(ValueError, match="No database URL"):
            with create_session(FakeScenario()):
                pass
