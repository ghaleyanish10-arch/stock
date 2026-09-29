"""Tests for schema migrations and the admin CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.cli import main
from app.db.migrations import apply_migrations


@pytest.fixture
def engine(tmp_path):
    # A file-backed database: SQLite's ALTER TABLE RENAME needs a real file, and
    # `:memory:` scoped to a single connection is fragile across connections.
    eng = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'db.sqlite3').as_posix()}")
    yield eng
    eng.dispose()


def _columns(eng, table: str) -> set[str]:
    return {c["name"] for c in inspect(eng).get_columns(table)}


def _exec(eng, *statements: str) -> None:
    """Run raw DDL. SQLAlchemy 2.x removed `Engine.execute`."""
    with eng.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def test_rename_step_is_skipped_when_nothing_to_do(engine):
    from app.db import models  # noqa: F401
    from app.db.base import Base
    Base.metadata.create_all(bind=engine)
    assert apply_migrations(engine) == []


def test_rename_step_is_skipped_when_table_absent(engine):
    # No tables at all - migrations should do nothing
    assert apply_migrations(engine) == []


def test_rename_step_renames_legacy_column(engine):
    # Create a securities table with all current columns EXCEPT the legacy one.
    # This simulates an old database that had the rename applied but not the new columns.
    # Actually, we want to test the rename step, so create a table with the legacy column
    # but WITH all the new columns already present (so ADD steps are skipped).
    _exec(
        engine,
        "CREATE TABLE securities ("
        "symbol TEXT PRIMARY KEY, "
        "neopse_security_id INTEGER, "
        "name TEXT, "
        "sector_code TEXT, "
        "isin TEXT, "
        "tick_size REAL, "
        "face_value REAL, "
        "listing_date TEXT, "
        "credit_rating TEXT, "
        "listed_shares INTEGER, "
        "promoter_shares REAL, "
        "public_shares REAL, "
        "promoter_pct REAL, "
        "public_pct REAL, "
        "security_type TEXT, "
        "board TEXT, "
        "is_active INTEGER DEFAULT 1, "
        "updated_at TEXT"
        ")",
    )
    assert "neopse_security_id" in _columns(engine, "securities")

    applied = apply_migrations(engine)

    assert applied == ["rename_securities_neopse_security_id"]
    cols = _columns(engine, "securities")
    assert "nepse_security_id" in cols
    assert "neopse_security_id" not in cols


def test_rename_step_preserves_existing_values(engine):
    _exec(
        engine,
        "CREATE TABLE securities (symbol TEXT PRIMARY KEY, neopse_security_id INTEGER)",
        "INSERT INTO securities VALUES ('NABIL', 131)",
    )

    apply_migrations(engine)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT nepse_security_id FROM securities WHERE symbol='NABIL'")
        ).scalar()
    assert value == 131


def test_migrations_are_idempotent(engine):
    # Create a securities table with all current columns EXCEPT the legacy one
    _exec(
        engine,
        "CREATE TABLE securities ("
        "symbol TEXT PRIMARY KEY, "
        "neopse_security_id INTEGER, "
        "name TEXT, "
        "sector_code TEXT, "
        "isin TEXT, "
        "tick_size REAL, "
        "face_value REAL, "
        "listing_date TEXT, "
        "credit_rating TEXT, "
        "listed_shares INTEGER, "
        "promoter_shares REAL, "
        "public_shares REAL, "
        "promoter_pct REAL, "
        "public_pct REAL, "
        "security_type TEXT, "
        "board TEXT, "
        "is_active INTEGER DEFAULT 1, "
        "updated_at TEXT"
        ")",
    )
    first = apply_migrations(engine)
    second = apply_migrations(engine)
    assert first == ["rename_securities_neopse_security_id"]
    assert second == []


def test_conflicting_columns_are_left_alone(engine):
    from app.db import models  # noqa: F401
    from app.db.base import Base
    Base.metadata.create_all(bind=engine)
    # Both names present: renaming would lose data, so the step must refuse.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE securities ADD COLUMN neopse_security_id INTEGER"))
    assert apply_migrations(engine) == []
    cols = _columns(engine, "securities")
    assert {"neopse_security_id", "nepse_security_id"} <= cols


def test_cli_grants_admin(monkeypatch, tmp_path):
    import app.cli as cli

    monkeypatch.setattr(cli, "session_scope", _scoped_session(tmp_path / "cli.db"))

    assert cli.create_admin("boss@example.com", "Str0ng-Passw0rd!") == 0
    assert cli.list_users() == 0
    assert cli.create_admin("boss@example.com", "Str0ng-Passw0rd!") == 1
    assert cli.grant_admin("nobody@example.com") == 1


def test_cli_accepts_any_password(monkeypatch, tmp_path):
    import app.cli as cli

    monkeypatch.setattr(cli, "session_scope", _scoped_session(tmp_path / "weak.db", monkeypatch))
    # With relaxed policy, any non-empty password is accepted
    assert cli.create_admin("weak@example.com", "password") == 0


def test_cli_grant_admin_promotes_and_bumps_token_version(monkeypatch, tmp_path):
    import app.cli as cli

    monkeypatch.setattr(cli, "session_scope", _scoped_session(tmp_path / "promote.db", monkeypatch))
    assert cli.create_admin("first@example.com", "Str0ng-Passw0rd!") == 0
    assert cli.grant_admin("first@example.com") == 0

    from app.db.models import User
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        user = session.query(User).filter_by(email="first@example.com").one()
        assert user.is_admin is True
        # The version bump is what forces a re-login after a privilege change.
        assert user.token_version == 1
    finally:
        session.close()


def _scoped_session(db_path: Path, monkeypatch=None):
    """Point `app.db.session.SessionLocal` at a throwaway database.

    The rebind MUST go through monkeypatch when given: these tests run before
    tests that resolve `SessionLocal` at call time (the scheduler writes its
    JobRun rows that way), and a permanent rebind left every later test
    reading an empty throwaway DB while its job wrote to the real one.
    """
    from sqlalchemy.orm import sessionmaker

    import app.db.session as session_module

    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
    from app.db import models  # noqa: F401
    from app.db.base import Base

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    if monkeypatch is not None:
        monkeypatch.setattr(session_module, "SessionLocal", factory)
        monkeypatch.setattr(session_module, "session_scope", _scope_from(factory))
    else:  # legacy callers that only want the scope helper
        session_module.SessionLocal = factory
    return session_module.session_scope


def _scope_from(factory):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return scope


def test_main_parses_create_admin(monkeypatch):
    called: list[str] = []

    monkeypatch.setattr("app.cli.create_admin", lambda email, pw: called.append(email) or 0)
    assert main(["create-admin", "--email", "x@example.com", "--password", "p"]) == 0
    assert called == ["x@example.com"]
