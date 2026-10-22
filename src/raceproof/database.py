from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from raceproof.config import get_settings
from raceproof.contracts import EventKind
from raceproof.events import EventRecorder
from raceproof.sample.models import Base, Product

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


def reset_database(engine: Engine, initial_stock: int = 1) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        session.add(Product(id=1, sku="DEMO-ONE", available_stock=initial_stock))


def read_final_state(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        stock = connection.execute(
            text("SELECT available_stock FROM products WHERE id = 1")
        ).scalar_one()
        orders = connection.execute(
            text("SELECT count(*) FROM orders WHERE product_id = 1")
        ).scalar_one()
    return int(stock), int(orders)


@contextmanager
def actor_session(factory: sessionmaker[Session], actor: str) -> Iterator[Session]:
    set_sql_actor(actor)
    try:
        with factory() as session:
            yield session
    finally:
        set_sql_actor(None)
