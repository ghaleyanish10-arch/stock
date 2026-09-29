"""SQLAlchemy models for the whole app.

Design notes that matter for data honesty:

* Every market-data column is **nullable and defaults to NULL**, never 0. A
  missing price is `NULL`; a reported 0 is `0`. Queries that compute averages
  therefore use `COALESCE`-free aggregates and the API layer decides how to
  phrase a gap.
* `trading_days.is_session` records *why* a date has no bars. A date is either
  a real session with rows, a confirmed non-session (holiday/weekend), or a
  date whose fetch failed. The archive never silently treats an error as "no
  change" -- that distinction is the whole point of the table.
* `fetch_attempts` keeps a per-date audit trail so a failed backfill can be
  retried without re-downloading dates that already succeeded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    iso_date,
    new_id,
    side_enum,
    status_enum,
    utcnow,
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    # scrypt digest and salt, hex encoded. Never the password itself.
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Bumped to invalidate every issued token for this user (sign-out all).
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: Light/dark/system preference.
    theme: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class Sector(Base):
    __tablename__ = "sectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: NEPSE's own sector index symbol where one exists.
    index_symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Security(Base):
    """A tradable symbol (equity, mutual fund share, index, etc.)."""

    __tablename__ = "securities"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    sector_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    #: NEPSE's numeric security id. Required for the per-symbol price history
    #: and corporate-actions endpoints, which are keyed by id, not symbol.
    #: Column was misspelled `neopse_security_id`; `app.db.migrations` renames
    #: it in place, so existing databases carry the corrected name over.
    nepse_security_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    isin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tick_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    face_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    listing_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    credit_rating: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: 0 is a genuine value (a company can have no listed shares of a class);
    #: NULL means NEPSE did not report it.
    listed_shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Promoter/public shareholding from `nots/security/{id}` (VERIFIED
    #: 2026-09-28 for NABIL: promoterShares=158121099, publicShares=112448885,
    #: promoterPercentage=58.44, publicPercentage=41.56; shares sum exactly to
    #: stockListedShares). NULL = not enriched yet, distinct from a real zero.
    promoter_shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    public_shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    promoter_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    public_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    security_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    board: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Broker(Base):
    """Official NEPSE member registry (`nots/member`)."""

    __tablename__ = "brokers"

    member_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    member_name: Mapped[str] = mapped_column(String(240), nullable=False)
    is_dealer: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, index=True)
    province: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    district: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Fund(Base):
    """Mutual fund scheme. NAV is nullable because NEPSE does not publish it."""

    __tablename__ = "funds"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    manager: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Fund metadata from NEPSE security detail (enrich_security)
    scheme_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    scheme_name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    close_ended: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    maturity_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    face_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # stockListedShares
    fund_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # units * face_value
    listing_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    isin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # NAV fields
    nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nav_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    nav_status: Mapped[Any] = mapped_column(status_enum, nullable=False, default="not_published")
    nav_source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class FundNavPoint(Base):
    """Historical NAV, imported from CSV or entered by the user."""

    __tablename__ = "fund_nav_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code"), nullable=False, index=True)
    nav_date: Mapped[str] = mapped_column(String(10), nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("fund_code", "nav_date", name="uq_fund_nav_point"),)


class CorporateAction(Base):
    """Dividends and bonus shares from NEPSE's corporate-actions endpoint."""

    __tablename__ = "corporate_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fiscal_year: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    #: Percentages. 0 means "declared as zero"; NULL means not reported.
    cash_dividend_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bonus_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: Rights issue percentage, from the same rows (`rightPercentage`). Needed
    #: (with bonus) to derive an adjustment factor for ADJUSTED candles.
    right_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    book_close: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    agm_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="nepse:corporate-actions")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "fiscal_year", name="uq_corporate_action"),
        Index("ix_corporate_action_symbol_fy", "symbol", "fiscal_year"),
    )


class Announcement(Base):
    """Company news/notices from NEPSE's `application/company-news/{id}`.

    VERIFIED 2026-09-28 for NABIL: 39 items; each row wraps a `companyNews`
    object with `newsHeadline`, `newsBody` (may be HTML), `newsType`,
    `newsSource` and `addedDate` (the timestamp; `newsDate` itself is null in
    practice).

    Dividend/book-closure/AGM details often live only in the news *text*
    (`Cash Dividend: 10.8%`, `Book Close Date: 30/09/2026`), while the
    corporate-actions endpoint carries only the bonus figures. Both are stored:
    the raw body verbatim, plus a parsed, labelled extraction that never
    invents a value.
    """

    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: NEPSE's own announcement id (companyNews.id), for deduplication.
    nepse_news_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    headline: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    news_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    news_source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: Parsed, labelled extras. Keys that are genuinely absent from the text
    #: are absent here too - never empty strings, never zeros.
    parsed: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "nepse_news_id", name="uq_announcement_symbol_news"),
        Index("ix_announcement_symbol_published", "symbol", "published_at"),
    )


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


class TradingDay(Base):
    """One row per calendar date the backfill has looked at.

    `is_session` is NULL while the date is unknown (never fetched, or the last
    fetch failed). The three cases are intentionally distinct:

    * is_session=1 -> bars exist for this date.
    * is_session=0 -> source confirmed a non-session (holiday/weekend).
    * is_session=None -> unknown; must be retried, never shown as "no change".
    """

    __tablename__ = "trading_days"

    business_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    is_session: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DailyBar(Base):
    """Session OHLCV for one symbol. All value columns nullable by design."""

    __tablename__ = "daily_bars"

    business_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    #: Composite key (business_date, symbol): one row per symbol per session.
    #: Both parts must be primary keys, or a re-run would overwrite the whole
    #: day with a single symbol.
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prev_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vwap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_52w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_52w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: Derived as listed_shares * close, because NEPSE's live marketCap is null.
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="nepse:today-price")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_daily_bars_symbol_date", "symbol", "business_date"),
        Index("ix_daily_bars_date_symbol", "business_date", "symbol"),
    )


class FetchAttempt(Base):
    """Audit trail so a failed date can be retried without refetching all."""

    __tablename__ = "fetch_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    business_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class BackfillRun(Base):
    __tablename__ = "backfill_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    dates_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dates_empty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dates_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class JobRun(Base):
    """Generic observability for scheduled work (daily snapshot, backfill)."""

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# User-owned, saveable objects
# ---------------------------------------------------------------------------


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_watchlist_item_symbol", "symbol"),)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="NPR")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[Any] = mapped_column(side_enum, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    fees: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=None)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_transaction_portfolio_date", "portfolio_id", "trade_date"),)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    #: e.g. price_above, price_below, volume_spike, rsi_above, macd_cross, rsi_60_40.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SavedScreen(Base):
    __tablename__ = "saved_screens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ChartLayout(Base):
    __tablename__ = "chart_layouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (Index("ix_chart_layout_user_symbol", "user_id", "symbol"),)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Holding(Base):
    """Current holding in a portfolio. One row per portfolio-symbol combination."""
    __tablename__ = "holdings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Weighted average cost per share (for WACC calculation)
    avg_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Total cost basis (quantity * avg_cost)
    total_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # First purchase date
    first_bought_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Last transaction date
    last_transacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", name="uq_holding_portfolio_symbol"),
        Index("ix_holding_portfolio_symbol", "portfolio_id", "symbol"),
    )


class AlertChannel(Base):
    """Notification channel for alerts (email, telegram, in-app)."""
    __tablename__ = "alert_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # Channel type: "email", "telegram", "in_app"
    channel_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Channel-specific config (email address, telegram chat_id, etc.)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verification_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_alert_channel_user_type", "user_id", "channel_type"),
    )


class AlertRule(Base):
    """Alert rule definition. Evaluated by background job."""
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    channel_id: Mapped[Optional[str]] = mapped_column(ForeignKey("alert_channels.id"), nullable=True)
    # Rule type: price_above, price_below, pct_change, volume_spike, rsi_cross,
    # macd_cross, announcement, book_closure, agm_approaching
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    # Rule parameters (threshold, period, etc.)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Cooldown period in seconds
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    # One-shot or repeating
    is_one_shot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_alert_rule_user_active", "user_id", "is_active"),
    )


class AlertEvent(Base):
    """Record of an alert being triggered."""
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    # Snapshot of params at trigger time
    triggered_params: Mapped[dict] = mapped_column(JSON, nullable=False)
    # The value that triggered the alert
    trigger_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Channel delivery status
    delivery_status: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_alert_event_rule_time", "rule_id", "triggered_at"),
        Index("ix_alert_event_user_time", "user_id", "triggered_at"),
    )


class FundamentalsImport(Base):
    """Admin-imported fundamentals data (quarterly financials)."""
    __tablename__ = "fundamentals_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fiscal_year: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Financial metrics
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    book_value_per_share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Metadata
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="csv_import")
    source_file: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    row_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imported_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "fiscal_year", "quarter", name="uq_fundamentals_import"),
        Index("ix_fundamentals_import_symbol_fy", "symbol", "fiscal_year"),
    )


class FundamentalsImportRow(Base):
    """Row-level validation results for fundamentals CSV import."""
    __tablename__ = "fundamentals_import_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_id: Mapped[str] = mapped_column(ForeignKey("fundamentals_imports.id"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(32), nullable=False)
    quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Raw row data
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Validation result
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    errors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_fundamentals_import_row_import", "import_id"),
    )


class NewsItem(Base):
    """News/announcement item from NEPSE news feed."""
    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Nepse news ID for deduplication
    nepse_news_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # Symbol if company-specific, None for market-wide
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    headline: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    news_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    news_source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    # Parsed structured data from body
    parsed: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_news_item_symbol_published", "symbol", "published_at"),
        Index("ix_news_item_published", "published_at"),
    )


class QuarterlyAnalysis(Base):
    """Quarterly analysis results for a symbol (cached)."""
    __tablename__ = "quarterly_analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fiscal_year: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    # Price-based metrics
    quarterly_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Fundamental metrics (if available)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    book_value_per_share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Sector comparison
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sector_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outperformed_sector: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Metadata
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="archive")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "fiscal_year", "quarter", name="uq_quarterly_analysis"),
        Index("ix_quarterly_analysis_symbol_fy", "symbol", "fiscal_year"),
    )


class CalculatorTemplate(Base):
    """Saved calculator templates for users."""
    __tablename__ = "calculator_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    calculator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Saved inputs
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class FeeTaxRate(Base):
    """Versioned fee/tax rates with effective dates.
    
    Rates are stored with effective_from date so that historical transactions
    can use the rate that was in force at the time of the transaction.
    """
    __tablename__ = "fee_tax_rates"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Rate type: broker_commission, sebon_fee, nepse_fee, stt, cgt_individual_long,
    # cgt_individual_short, cgt_entity, dp_charge, dp_transaction, sebon_fee_pct, etc.
    rate_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # The rate value (e.g., 0.00275 for 0.275%, 0.05 for 5%)
    rate_value: Mapped[float] = mapped_column(Float, nullable=False)
    # Unit: "percent", "per_transaction", "fixed_rs"
    rate_unit: Mapped[str] = mapped_column(String(32), nullable=False, default="percent")
    # Applies to: "individual", "entity", "all"
    applies_to: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    # Description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Source: "sebon", "ird", "nepse", "cds", "cds_clearing"
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Source URL
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Verification status: "verified", "unverified"
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified")
    # Probe date when last verified
    probe_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Effective from date (inclusive)
    effective_from: Mapped[date] = mapped_column(DateTime, nullable=False, index=True)
    # Effective to date (exclusive, NULL means current)
    effective_to: Mapped[Optional[date]] = mapped_column(DateTime, nullable=True)
    # Created/updated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    
    __table_args__ = (
        Index("ix_fee_tax_rate_type_effective", "rate_type", "effective_from"),
    )


__all__ = [
    "Base",
    "User",
    "Sector",
    "Security",
    "Broker",
    "Fund",
    "FundNavPoint",
    "CorporateAction",
    "TradingDay",
    "DailyBar",
    "FetchAttempt",
    "BackfillRun",
    "JobRun",
    "Watchlist",
    "WatchlistItem",
    "Portfolio",
    "Transaction",
    "Alert",
    "SavedScreen",
    "ChartLayout",
    "Note",
    "FeeTaxRate",
    "Holding",
    "AlertChannel",
    "AlertRule",
    "AlertEvent",
    "FundamentalsImport",
    "FundamentalsImportRow",
    "NewsItem",
    "QuarterlyAnalysis",
    "CalculatorTemplate",
    "iso_date",
    "utcnow",
]
