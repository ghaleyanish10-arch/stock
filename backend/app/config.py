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


# --- AI Disclosure -------------------------------------------------------
# Changing the disclosure text MUST bump this version. The frontend stores the
# version the user agreed to; a mismatch forces re-consent.
AI_DISCLOSURE_VERSION = "1.0"
AI_DISCLOSURE_TEXT = (
    "Your portfolio data will be sent to the AI provider for analysis. "
    "The following fields are included:\n\n"
    "Portfolio identification\n"
    "- Portfolio name, base currency, creation date\n\n"
    "Valuation summary\n"
    "- Total portfolio value, total cost basis, unrealized P&L (amount and %)\n"
    "- Per-holding: symbol, quantity, average cost, total cost, last traded price, market value, unrealized P&L (amount and %)\n\n"
    "Performance\n"
    "- XIRR (annualized return) if computable\n"
    "- Sector allocation (cost per sector)\n"
    "- Concentration metrics: top holding %, top 5 holdings %, holding count\n\n"
    "Transaction history (last 50)\n"
    "- Per transaction: symbol, side (buy/sell), quantity, price, trade date, fees\n\n"
    "Data sources\n"
    "- Portfolio data from your private archive\n"
    "- Live market data from NEPSE (if available)\n"
    "- Reference data (security names, sectors)\n\n"
    "Provider\n"
    "The data is sent to the configured AI provider (see AI Status page for current provider and model).\n\n"
    "Your rights\n"
    "- You can revoke consent at any time from Settings or the AI Consent screen\n"
    "- Revoking consent immediately blocks all AI features until re-granted\n"
    "- Data is sent only when you explicitly invoke an AI feature (Ask, Stream, Portfolio Review)\n"
    "- We do not send data for training; it is used only for your single request"
)

# --- Corporate Actions (B1) ------------------------------------------------
# Eligibility cutoff: book close minus N settlement days (Nepal T+2 default).
# UNVERIFIED - verify current settlement cycle with your broker.
CA_ELIGIBILITY_CUTOFF_DAYS = _get_int("APP_CA_ELIGIBILITY_CUTOFF_DAYS", 2)

# Acquisition date for bonus shares: "book_close" or "agm_date" or "ex_date".
# UNVERIFIED - verify with your broker/tax advisor.
CA_BONUS_ACQUISITION_DATE = os.getenv("APP_CA_BONUS_ACQUISITION_DATE", "book_close")

# Fractional bonus shares rounding: "floor" (drop fractions), "round" (standard),
# or "ceil" (round up). UNVERIFIED - verify with your broker.
CA_FRACTIONAL_BONUS_ROUNDING = os.getenv("APP_CA_FRACTIONAL_BONUS_ROUNDING", "floor")

# Fee/tax rates with UNVERIFIED marks (must have source or UNVERIFIED label)
# These are defaults - override via env or database FeeTaxRate table.
# Broker commission (percent). UNVERIFIED - verify with your broker.
FEE_BROKER_COMMISSION_PCT = _get_int("APP_FEE_BROKER_COMMISSION_PCT", 35) / 10000  # 0.35%
# SEBON fee (percent). UNVERIFIED - verify with SEBON.
FEE_SEBON_PCT = _get_int("APP_FEE_SEBON_PCT", 15) / 10000  # 0.15%
# NEPSE fee (percent). UNVERIFIED - verify with NEPSE.
FEE_NEPSE_PCT = _get_int("APP_FEE_NEPSE_PCT", 5) / 10000  # 0.05%
# DP charge (fixed Rs per transaction). UNVERIFIED - verify with your DP.
FEE_DP_CHARGE = _get_int("APP_FEE_DP_CHARGE", 25)
# DP transaction fee (fixed Rs per transaction). UNVERIFIED - verify with your DP.
FEE_DP_TRANSACTION = _get_int("APP_FEE_DP_TRANSACTION", 5)

# Capital gains tax rates (UNVERIFIED - verify with IRD Nepal)
# Individual long-term (>1 year holding)
CGT_INDIVIDUAL_LONG_PCT = _get_int("APP_CGT_INDIVIDUAL_LONG_PCT", 5) / 100  # 5%
# Individual short-term (<=1 year holding)
CGT_INDIVIDUAL_SHORT_PCT = _get_int("APP_CGT_INDIVIDUAL_SHORT_PCT", 7) / 100  # 7%
# Entity (company/trust)
CGT_ENTITY_PCT = _get_int("APP_CGT_ENTITY_PCT", 10) / 100  # 10%

settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
