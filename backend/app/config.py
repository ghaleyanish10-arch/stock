"""Application configuration loaded from environment variables.

No credentials are needed for NEPSE's public API. The only secret this app
introduces is the JWT signing key, which must be set explicitly in production
(see `docs/setup.md`); a development fallback keeps `python -m app.main`
working out of the box.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

# Development-only fallback. Refused at startup when DEBUG is off (see
# `Settings.validate_runtime`), so a production deploy cannot silently run with
# a publicly known signing key.
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"


def _get_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to `default` when unset/invalid."""
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        logging.getLogger(__name__).warning(
            "Invalid value %r for %s, using default %s", raw, name, default
        )
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


class Settings:
    """Simple settings container. Values come from environment variables."""

    def __init__(self) -> None:
        # --- NEPSE upstream (unchanged) --------------------------------
        # Timeout (seconds) applied to every NEPSE request.
        self.timeout = _get_int("NEPSE_TIMEOUT", 15)
        # TTL (seconds) of the service-level response cache.
        self.cache_ttl = _get_int("NEPSE_CACHE_TTL", 30)
        # TTL (seconds) for remembering that the NEPSE API is unreachable,
        # so we fail fast instead of hammering a down service.
        self.error_ttl = _get_int("NEPSE_ERROR_TTL", 60)
        # Cache size (number of cached responses).
        self.cache_maxsize = _get_int("NEPSE_CACHE_MAXSIZE", 512)
        self.log_level = os.getenv("NEPSE_LOG_LEVEL", "INFO").upper()

        # --- Outbound rate limiting ------------------------------------
        # NEPSE throttles bursts by closing the connection (observed 2026-09
        # while enumerating 568 securities), so the adapter paces itself.
        self.outbound_min_interval_ms = _get_int("NEPSE_OUTBOUND_MIN_INTERVAL_MS", 120)
        self.outbound_max_concurrency = _get_int("NEPSE_OUTBOUND_MAX_CONCURRENCY", 1)

        # --- Database ---------------------------------------------------
        # SQLite by default (zero setup). Any SQLAlchemy URL works, so
        # Postgres is a config change and not a code change.
        self.database_url = os.getenv(
            "APP_DATABASE_URL", f"sqlite+pysqlite:///{BASE_DIR / 'data' / 'app.db'}"
        )
        self.db_echo = _get_bool("APP_DB_ECHO", False)

        # --- Auth -------------------------------------------------------
        self.jwt_secret = os.getenv("APP_JWT_SECRET", DEV_JWT_SECRET)
        self.jwt_algorithm = "HS256"
        self.jwt_ttl_minutes = _get_int("APP_JWT_TTL_MINUTES", 60 * 24 * 7)
        self.debug = _get_bool("APP_DEBUG", True)

        # --- Archive ----------------------------------------------------
        # NEPSE only serves ~227 sessions ending today, so the backfill
        # window is bounded upstream. `archive_floor` is the earliest date
        # known to be served; the backfill stops when a date fails hard.
        self.archive_floor = os.getenv("APP_ARCHIVE_FLOOR", "2025-09-28")
        # Pause between backfill date fetches (NEPSE throttles bursts).
        self.archive_pause_ms = _get_int("APP_ARCHIVE_PAUSE_MS", 900)
        # Post-close snapshot time, Nepal time (HH:MM). NEPSE closes at 15:00
        # NPT and publishes the final session figures shortly after; 15:30
        # gives the figures time to land without racing the close.
        self.post_close_hhmm = os.getenv("APP_POST_CLOSE_HHMM", "15:30")

    @property
    def sqlite_path(self) -> Path | None:
        """Filesystem path when using SQLite, else None (Postgres/etc.)."""
        prefix = "sqlite+pysqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix):])
        return None

    def validate_runtime(self) -> list[str]:
        """Return configuration problems that should stop a real deployment.

        Called during startup. Development defaults are intentionally allowed so
        the project runs with no `.env` at all.
        """
        problems: list[str] = []
        if not self.debug and self.jwt_secret == DEV_JWT_SECRET:
            problems.append(
                "APP_JWT_SECRET is unset while APP_DEBUG is off. "
                "Set a strong random value before deploying."
            )
        if not self.jwt_secret or len(self.jwt_secret) < 16:
            problems.append("APP_JWT_SECRET must be at least 16 characters.")
        return problems


settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
