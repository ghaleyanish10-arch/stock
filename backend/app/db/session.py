"""SQLAlchemy engine/session wiring.

The project ships on SQLite so `python -m app.main` works with no external
service, but every URL is honoured by SQLAlchemy, so Postgres is a config
change (`APP_DATABASE_URL=postgresql+psycopg://...`) and not a code change.
Two details make that switch safe:

* SQLite gets WAL mode and a busy timeout so the archive backfill (many
  concurrent-ish writes) cannot corrupt itself with "database is locked".
* Nothing below uses SQLite-specific SQL; the DDL sticks to portable types.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")


def _make_engine() -> Engine:
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}
    if _is_sqlite:
        # check_same_thread=False: FastAPI runs sync endpoints in a threadpool
        # and the backfill job runs in its own thread; SQLAlchemy's own pool
        # still guarantees one connection per checkout.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
    return create_engine(settings.database_url, **kwargs)


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        """WAL + a generous busy timeout + real foreign keys.

        Without WAL, a long backfill write blocks every reader (the dashboard
        polls constantly). Without the busy timeout, concurrent writers raise
        "database is locked" instead of waiting.
        """
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create the SQLite file's parent directory, all tables, then migrate.

    `create_all` cannot rename or alter an existing column, so the pending
    migrations run afterwards - see `app.db.migrations`.
    """
    # Imported here to keep module import order simple and avoid a cycle
    # between `app.db.base` and `app.db.models`.
    from app.db import models  # noqa: F401
    from app.db.migrations import apply_migrations

    path = settings.sqlite_path
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    models.Base.metadata.create_all(bind=engine)
    apply_migrations(engine)
    logger.info(
        "database ready at %s%s",
        settings.database_url,
        " (SQLite, WAL)" if _is_sqlite else "",
    )
