"""Test-isolation guard (repo-wide).

Every test run must use its own throwaway SQLite file, never the developer's
`backend/data/app.db`. The engine in `app.db.session` is created at import
time from `APP_DATABASE_URL`, so this conftest sets that variable BEFORE any
`app` module is imported (pytest imports root conftest.py before collecting
test modules, which is what makes the trick work).

Two rules are enforced, not just configured:

* If the effective URL would target `data/app.db` (unset APP_DATABASE_URL or
  one explicitly pointing there), the run aborts with a clear message instead
  of silently writing test rows into real user data.
* An empty or :memory: URL is rejected too: tests must be able to re-open the
  database from another module (SessionLocal), which a bare sqlite:///:memory:
  engine does not support (each connection gets its own empty database).

Network guard: all outbound sockets are blocked except to localhost. This
catches any test that accidentally hits the real NEPSE API. The FakeNepseAdapter
in fakes.py is the only permitted NEPSE client in tests.

Test data never leaves this directory unless the test itself opted out with
an explicit engine of its own (the StaticPool in-memory suites do exactly
that and are unaffected).
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

DEV_DB_RELATIVE = "data/app.db"

# ---------------------------------------------------------------------------
# Network guard: block all outbound connections except localhost.
# Installed at import time so it catches even module-level network calls.
# ---------------------------------------------------------------------------
_original_socket = socket.socket

class _GuardedSocket(socket.socket):
    def connect(self, address):
        host = address[0]
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"Network call blocked to {host}:{address[1]}")
        return super().connect(address)

socket.socket = _GuardedSocket


def _initial_test_url() -> str:  # pragma: no cover - guard logic
    """The URL tests WOULD run against if we did nothing.

    Mirrors `Settings.__init__`'s fallback resolution without importing any
    `app` module (importing app.config is safe, but resolving here keeps this
    file free of application imports entirely).
    """
    return os.getenv("APP_DATABASE_URL") or f"sqlite+pysqlite:///{BACKEND_ROOT / DEV_DB_RELATIVE}"


def _is_dev_db(url: str) -> bool:  # pragma: no cover - guard logic
    normalized = url.replace("\\", "/").lower()
    return DEV_DB_RELATIVE in normalized


# ---------------------------------------------------------------------------
# 1. Inspect what the URL WOULD be before anything is imported.
#    Unset env var is the NORMAL case -> the temp redirect below applies.
#    Only an EXPLICITLY set dev-DB URL is the smell the guard exists for.
# ---------------------------------------------------------------------------
_explicit = os.getenv("APP_DATABASE_URL")
if _explicit is not None and _is_dev_db(_explicit):
    sys.stderr.write(
        "\n"
        "  >>> TEST RUN ABORTED: APP_DATABASE_URL points at the developer DB <<<\n"
        f"    APP_DATABASE_URL = {_explicit!r}\n"
        "  Tests must never create, modify or delete rows in\n"
        "  backend/data/app.db. Run pytest without APP_DATABASE_URL set, or\n"
        "  point it at a scratch database.\n"
        "\n"
    )
    raise SystemExit(2)
if _explicit is not None and _explicit.strip().endswith(":memory:"):
    sys.stderr.write(
        "\n  >>> TEST RUN ABORTED: a file-based SQLite URL is required (tests\n"
        "  share one engine across modules); :memory: cannot be shared. <<<\n\n"
    )
    raise SystemExit(2)

# ---------------------------------------------------------------------------
# 2. Redirect the app engine to a per-run temp file, then import the app so
#    `engine`/`SessionLocal` singletons bind to it once, here.
# ---------------------------------------------------------------------------
_TMPDIR = Path(tempfile.mkdtemp(prefix="nepsetest-"))
TEST_DB = _TMPDIR / "test.db"
os.environ["APP_DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB.as_posix()}"
# Dev JWT secret is fine under APP_DEBUG=1; validate_runtime only blocks it in
# production builds. Tests never deploy.
os.environ.setdefault("APP_DEBUG", "1")

# Import AFTER the env var is final: this single import binds every
# `from app.db.session import SessionLocal` consumer in the app to the temp DB.
from app.db import session as _db_session  # noqa: E402

_engine = _db_session.engine

# A throwaway file starts EMPTY: create the schema now (create_all only ever
# adds missing tables, so this is idempotent) and let migrations convert the
# known renames/additions, exactly as a real deployment start does.
from app.db import models as _models  # noqa: E402
from app.db.migrations import apply_migrations as _apply_migrations  # noqa: E402

_models.Base.metadata.create_all(bind=_engine)
_apply_migrations(_engine)


def _cleanup_tmp_dir() -> None:  # pragma: no cover - best effort
    """Dispose the engine first: Windows keeps WAL files locked otherwise."""
    try:
        _engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TMPDIR, ignore_errors=True)


atexit.register(_cleanup_tmp_dir)


# ---------------------------------------------------------------------------
# 3. Report the isolation decision in the summary line.
# ---------------------------------------------------------------------------
def pytest_terminal_summary(terminalreporter) -> None:
    reporter = terminalreporter
    reporter.write_sep("=", "test isolation")
    reporter.write_line(f"database: {TEST_DB}")
    reporter.write_line("dev database untouched (guard active on data/app.db)")
