"""Engine factory: SQLite gets foreign-key enforcement (it is off by default)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event


def make_engine(url: str) -> Engine:
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
