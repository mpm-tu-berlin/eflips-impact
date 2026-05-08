"""Generic DB-session helper used across ``utils/``, ``tco/``, and ``lca/``.

The legacy ``eflips.impact.tco.util.create_session`` lived in tco/ and was
copied informally; this module is its canonical home.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator, Optional, Tuple, Union

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from eflips.model import Scenario, create_engine


@contextmanager
def create_session(
    scenario: Union[Scenario, int, Any],
    database_url: Optional[str] = None,
) -> Generator[Tuple[Session, Scenario], None, None]:
    """Resolve a polymorphic ``scenario`` argument to ``(session, Scenario)``.

    If ``scenario`` is a :class:`Scenario`, yields its bound session and the
    same object; the caller's transaction is preserved (no commit, no close).

    Otherwise opens a fresh session via ``create_engine(database_url)``, looks
    up the scenario by id, yields it, and on successful exit commits and
    disposes of both session and engine.

    :param scenario: A :class:`Scenario` instance, an ``int`` id, or any object
        with an ``id`` attribute.
    :param database_url: Database URL used when ``scenario`` is not already
        bound to a session. Falls back to ``$DATABASE_URL``.
    :yields: Tuple ``(session, scenario)``. ``scenario`` is guaranteed to be a
        :class:`Scenario` instance from the yielded session.
    :raises ValueError: If ``scenario`` is not a Scenario / int / id-bearing
        object, if a passed Scenario has no bound session, or if no
        ``database_url`` is available when one is needed.
    """
    if isinstance(scenario, Scenario):
        session = sa_inspect(scenario).session
        if session is None:
            raise ValueError("Scenario object is not bound to an active session.")
        yield session, scenario
        return

    if isinstance(scenario, int):
        scenario_id: int = scenario
    elif hasattr(scenario, "id"):
        scenario_id = int(scenario.id)
    else:
        raise ValueError(
            "scenario must be a Scenario object, an int, or an object with an 'id' attribute."
        )

    url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if url is None:
        raise ValueError("No database URL specified and DATABASE_URL is not set.")

    engine = create_engine(url)
    session = Session(engine)
    try:
        scenario_obj = session.query(Scenario).filter(Scenario.id == scenario_id).one()
        yield session, scenario_obj
        session.commit()
    finally:
        session.close()
        engine.dispose()
