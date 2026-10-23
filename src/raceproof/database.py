from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from raceproof.config import get_settings
from raceproof.contracts import EventKind
from raceproof.events import EventRecorder

_actor_context = threading.local()


def set_sql_actor(actor: str | None) -> None:
    _actor_context.actor = actor


def create_database_engine(url: str | None = None, recorder: EventRecorder | None = None) -> Engine:
    engine = create_engine(
        url or get_settings().database_url,
        isolation_level="READ COMMITTED",
        pool_pre_ping=True,
        future=True,
    )
    if recorder is not None:

        @event.listens_for(engine, "before_cursor_execute")
        def capture_sql(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _executemany: bool,
        ) -> None:
            compact = " ".join(statement.split())
            recorder.add(
                EventKind.SQL,
                stage="execute",
                actor=getattr(_actor_context, "actor", None),
                action="sql",
                detail={"statement": compact[:600]},
            )

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


@contextmanager
def actor_session(engine: Engine, actor: str) -> Iterator[Session]:
    set_sql_actor(actor)
    try:
        with session_factory(engine).begin() as session:
            yield session
    finally:
        set_sql_actor(None)
