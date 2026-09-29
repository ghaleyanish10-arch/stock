"""Historical archive: ingest NEPSE sessions and answer questions about them.

The single most important rule in this module: **an empty response and a failed
request are not the same thing.**

NEPSE's `today-price` endpoint answers three very different ways, and each one
means something different to the archive:

    rows > 0                     -> the date was a trading session
    200 with zero rows           -> the date was a real non-session (holiday/weekend)
    500 "Searched Date is not valid"
                                 -> the date is older than NEPSE's ~227-session
                                    window; permanent, and it marks the floor
    timeout / 5xx / 429 / 401   -> the fetch failed; retry later, keep the date
                                    marked UNKNOWN

The `nepse-data-api` library cannot make this distinction because it catches
every exception and returns `[]`, which is why this module uses the adapter's
raising accessors instead of the library's helpers.

A date whose state is unknown stays `is_session = NULL` and is retried. It is
never stored as "no data", so the UI can say *we don't know yet* instead of
implying the market did not trade.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import BackfillRun, DailyBar, FetchAttempt, TradingDay
from app.db.base import utcnow
from app.nepse.client import NepseClientAdapter
from app.nepse.exceptions import (
    NepseDateOutOfRangeError,
    NepseRateLimitedError,
    NepseServiceError,
)

logger = logging.getLogger(__name__)

#: NEPSE pages `today-price`; 500 rows per page is well above the ~441
#: securities it serves, so one page normally covers a whole session.
PAGE_SIZE = 500


class DayState(str, Enum):
    """What we know about one calendar date."""

    #: The source returned rows; the date was a trading session.
    SESSION = "session"
    #: The source returned 200 with no rows: a holiday or weekend.
    NON_SESSION = "non_session"
    #: Older than the history NEPSE publishes. Permanent, not retryable.
    OUT_OF_RANGE = "out_of_range"
    #: The request failed. Retryable; the date stays unknown until it succeeds.
    FAILED = "failed"
    #: The source returned no rows for a date we still expect to trade, so the
    #: day is left *unknown* and re-checked instead of being written off.
    DEFERRED = "deferred"


@dataclass(slots=True)
class DayOutcome:
    """Result of ingesting one date."""

    business_date: str
    state: DayState
    row_count: int = 0
    error: Optional[str] = None

    @property
    def stored(self) -> bool:
        return self.state is DayState.SESSION


@dataclass(slots=True)
class BackfillSummary:
    """Aggregate result of a backfill run."""

    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    sessions: list[DayOutcome] = field(default_factory=list)
    non_sessions: list[DayOutcome] = field(default_factory=list)
    out_of_range: list[DayOutcome] = field(default_factory=list)
    failed: list[DayOutcome] = field(default_factory=list)
    skipped_existing: int = 0
    rows_written: int = 0
    #: Earliest date NEPSE will serve, discovered by walking back.
    detected_floor: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "sessions_stored": len(self.sessions),
            "non_sessions": len(self.non_sessions),
            "out_of_range": len(self.out_of_range),
            "failed": len(self.failed),
            "skipped_existing": self.skipped_existing,
            "rows_written": self.rows_written,
            "detected_floor": self.detected_floor,
            "failed_dates": [o.business_date for o in self.failed][:50],
        }


def daterange(start: date, end: date) -> list[str]:
    """Inclusive list of ISO date strings from `start` to `end`."""
    if end < start:
        return []
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def _num(value: Any) -> Optional[float]:
    """Coerce to float, preserving None. An empty string is missing, not 0."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    num = _num(value)
    return int(num) if num is not None else None


def bar_from_row(row: dict, listed_shares: Optional[int] = None) -> Optional[DailyBar]:
    """Map one `today-price` row to a `DailyBar`.

    Market cap is **derived** as `listed_shares * close` because NEPSE's own
    `marketCapitalization` field is denominated in millions of NPR (verified:
    ACLBSL 1010.0 close, reported 3762.85) and is null for the live feed. The
    reported figure is not stored, so there is no unit ambiguity downstream.
    """
    symbol = (row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    business_date = (row.get("businessDate") or "")[:10]
    if not business_date:
        return None

    close = _num(row.get("closePrice"))
    market_cap: Optional[float] = None
    if listed_shares and close is not None:
        market_cap = listed_shares * close

    return DailyBar(
        business_date=business_date,
        symbol=symbol,
        open=_num(row.get("openPrice")),
        high=_num(row.get("highPrice")),
        low=_num(row.get("lowPrice")),
        close=close,
        prev_close=_num(row.get("previousDayClosePrice")),
        volume=_int(row.get("totalTradedQuantity")),
        turnover=_num(row.get("totalTradedValue")),
        trades=_int(row.get("totalTrades")),
        vwap=_num(row.get("averageTradedPrice")),
        high_52w=_num(row.get("fiftyTwoWeekHigh")),
        low_52w=_num(row.get("fiftyTwoWeekLow")),
        market_cap=market_cap,
        source="nepse:today-price",
    )


# ---------------------------------------------------------------------------
# Archive service
# ---------------------------------------------------------------------------


class ArchiveService:
    """Owns the historical bar store and the backfill job."""

    def __init__(self, client: NepseClientAdapter) -> None:
        self._client = client

    @property
    def client(self) -> NepseClientAdapter:
        """The shared upstream adapter.

        Exposed so callers that need an upstream capability the archive itself
        does not wrap (the post-close job reading market status) can reach it
        without duplicating the client.
        """
        return self._client

    # -- reading -------------------------------------------------------

    def get_bars(
        self,
        session: Session,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 1000,
    ) -> list[DailyBar]:
        """Bars for one symbol, oldest first."""
        stmt = select(DailyBar).where(DailyBar.symbol == symbol.strip().upper())
        if start:
            stmt = stmt.where(DailyBar.business_date >= start)
        if end:
            stmt = stmt.where(DailyBar.business_date <= end)
        stmt = stmt.order_by(DailyBar.business_date.asc()).limit(limit)
        return list(session.scalars(stmt))

    def latest_session_on_or_before(
        self, session: Session, on_or_before: Optional[str] = None
    ) -> Optional[str]:
        """The most recent date we have stored bars for, at or before a date.

        This is the "empty day walks back" rule: if a user asks for
        2026-09-27 and that was a Sunday, or asks for today's date before
        NEPSE has published the close, we return the last session that actually
        happened instead of an empty chart.
        """
        if on_or_before:
            stmt = (
                select(TradingDay.business_date)
                .where(TradingDay.is_session.is_(True))
                .where(TradingDay.business_date <= on_or_before)
                .order_by(TradingDay.business_date.desc())
                .limit(1)
            )
        else:
            stmt = (
                select(TradingDay.business_date)
                .where(TradingDay.is_session.is_(True))
                .order_by(TradingDay.business_date.desc())
                .limit(1)
            )
        return session.scalar(stmt)

    def resolve_as_of(self, session: Session, requested: Optional[str] = None) -> dict[str, Any]:
        """Explain which date a request resolved to, and why.

        Returns the resolved date plus the reason it differs from what was
        asked for, so the UI can say "Showing 2026-09-24, the last session
        (2026-09-27 was a holiday)" rather than silently substituting.
        """
        wanted = requested or date.today().isoformat()
        exact = session.get(TradingDay, wanted)
        if exact is not None and exact.is_session:
            return {
                "requested": wanted,
                "resolved": wanted,
                "walked_back": False,
                "reason": None,
            }
        resolved = self.latest_session_on_or_before(session, wanted)
        if exact is not None and exact.is_session is False:
            reason = f"{wanted} is a published non-trading day."
        elif exact is not None and exact.is_session is None:
            reason = (
                f"{wanted} has not been archived yet, so the last known session is shown."
            )
        elif exact is None:
            reason = f"{wanted} has not been archived yet, so the last known session is shown."
        else:
            reason = f"{wanted} has no stored session data."
        return {
            "requested": wanted,
            "resolved": resolved,
            "walked_back": resolved is not None and resolved != wanted,
            "reason": reason if resolved is not None else f"No archived session found on or before {wanted}.",
        }

    def coverage(self, session: Session) -> dict[str, Any]:
        """How much history we hold, and where the gaps are."""
        total_days = session.scalar(select(func.count()).select_from(TradingDay))
        sessions = session.scalar(
            select(func.count()).select_from(TradingDay).where(TradingDay.is_session.is_(True))
        )
        non_sessions = session.scalar(
            select(func.count()).select_from(TradingDay).where(TradingDay.is_session.is_(False))
        )
        unknown = session.scalar(
            select(func.count()).select_from(TradingDay).where(TradingDay.is_session.is_(None))
        )
        bar_count = session.scalar(select(func.count()).select_from(DailyBar))
        symbol_count = session.scalar(select(func.count(DailyBar.symbol.distinct())))
        first, last = session.execute(
            select(func.min(TradingDay.business_date), func.max(TradingDay.business_date)).where(
                TradingDay.is_session.is_(True)
            )
        ).one()
        return {
            "first_session": first,
            "last_session": last,
            "known_days": total_days,
            "sessions": sessions,
            "non_sessions": non_sessions,
            "unknown_days": unknown,
            "bars": bar_count,
            "symbols": symbol_count,
            "nepse_published_floor": settings.archive_floor,
            "note": (
                "NEPSE only serves roughly the last 227 sessions. Anything older "
                "can only be built by this app's own archive over time."
            ),
        }

    # -- writing -------------------------------------------------------

    async def ingest_day(
        self,
        session: Session,
        business_date: str,
        listed_shares: Optional[dict[str, int]] = None,
        treat_empty_as_non_session: bool = True,
    ) -> DayOutcome:
        """Fetch and store one date, recording why it succeeded or failed.

        `treat_empty_as_non_session=False` is for dates we still expect to
        trade - notably today, right after the close check but before NEPSE has
        published. A 200-with-no-rows response for such a date is recorded as
        *unknown* and retried, because writing it off as a holiday would
        permanently suppress the day's real data.
        """
        try:
            rows = await self._fetch_rows(business_date)
        except NepseDateOutOfRangeError:
            self._record(session, business_date, DayState.OUT_OF_RANGE, 0,
                         "Older than the history NEPSE publishes.")
            return DayOutcome(business_date, DayState.OUT_OF_RANGE)
        except NepseRateLimitedError as exc:
            # Transient, but stop the whole run: hammering makes it worse.
            self._record(session, business_date, DayState.FAILED, 0, str(exc) or exc.message)
            raise
        except NepseServiceError as exc:
            self._record(session, business_date, DayState.FAILED, 0, f"{exc.code}: {exc.message}")
            logger.warning("archive fetch failed for %s: %s", business_date, exc.code)
            return DayOutcome(business_date, DayState.FAILED, error=exc.code)

        if not rows:
            if not treat_empty_as_non_session:
                # Left unknown on purpose: `is_session` stays NULL, so the
                # as-of walk-back and the next backfill both retry it.
                self._record(
                    session, business_date, DayState.DEFERRED, 0,
                    "No rows yet for an expected trading day; will re-check.",
                )
                return DayOutcome(
                    business_date, DayState.DEFERRED,
                    error="no rows yet for an expected trading day",
                )
            # 200 with no rows is a genuine non-session. Marked as such, which
            # is the opposite of "no change".
            self._record(session, business_date, DayState.NON_SESSION, 0, "Source returned no rows.")
            return DayOutcome(business_date, DayState.NON_SESSION)

        written = 0
        for row in rows:
            symbol = (row.get("symbol") or "").strip().upper()
            bar = bar_from_row(row, (listed_shares or {}).get(symbol))
            if bar is None:
                continue
            # Upsert by primary key so a re-run updates rather than duplicates.
            session.merge(bar)
            written += 1
        self._record(session, business_date, DayState.SESSION, written, None)
        return DayOutcome(business_date, DayState.SESSION, row_count=written)

    async def _fetch_rows(self, business_date: str) -> list[dict]:
        """All rows for one date, following NEPSE's pagination."""
        rows: list[dict] = []
        page = 0
        while True:
            envelope = await self._client.call(
                f"today_price_page:{business_date}:{page}",
                lambda p=page: self._client.get_today_price_page(business_date, page, PAGE_SIZE),
            )
            content = envelope.get("content") if isinstance(envelope, dict) else envelope
            content = content or []
            rows.extend(content)
            total_pages = (envelope or {}).get("totalPages") or 1
            if not content or page + 1 >= int(total_pages):
                break
            page += 1
        return rows

    def _record(
        self,
        session: Session,
        business_date: str,
        state: DayState,
        row_count: int,
        error: Optional[str],
    ) -> None:
        """Upsert the calendar row and append a fetch attempt."""
        if state is DayState.SESSION:
            is_session: Optional[bool] = True
        elif state is DayState.NON_SESSION:
            is_session = False
        else:
            is_session = None  # unknown: out of range or failed

        row = session.get(TradingDay, business_date)
        if row is None:
            row = TradingDay(business_date=business_date)
            session.add(row)
        row.is_session = is_session
        row.row_count = row_count if state is DayState.SESSION else row.row_count
        row.source = "nepse:today-price"
        row.fetched_at = utcnow()
        row.note = error
        session.add(
            FetchAttempt(
                business_date=business_date,
                source="nepse:today-price",
                ok=(state in (DayState.SESSION, DayState.NON_SESSION)),
                row_count=row_count,
                error=error,
            )
        )
        session.commit()

    @staticmethod
    def _listed_shares_map(session: Session) -> dict[str, int]:
        """`{symbol: listed_shares}` for every security we have a count for.

        Read once per backfill rather than per symbol per day, so deriving
        market cap costs one query instead of thousands.
        """
        from app.db.models import Security

        rows = session.execute(
            select(Security.symbol, Security.listed_shares).where(
                Security.listed_shares.is_not(None)
            )
        ).all()
        return {symbol: int(shares) for symbol, shares in rows if shares is not None}

    async def backfill(
        self,
        session: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        pause_ms: Optional[int] = None,
        force: bool = False,
        progress: Optional[Any] = None,
    ) -> BackfillSummary:
        """Ingest every date in `[start, end]`.

        `start` defaults to the configured archive floor; `end` to today.
        `force=False` skips dates already stored as sessions, so a resumed
        backfill only retries what is actually missing.

        On the first out-of-range response the run stops and records
        `detected_floor`: every earlier date is equally unservable, so there is
        no point paying for the requests.
        """
        start_date = start or settings.archive_floor
        end_date = end or date.today().isoformat()
        pause = (pause_ms if pause_ms is not None else settings.archive_pause_ms) / 1000.0

        # Market cap is derived from listed shares, which NEPSE only publishes
        # per symbol via `nots/security/{id}` (stored by the reference service's
        # enrich step). Reading them once here means enriched symbols get a real
        # market cap on every archived bar, and unenriched ones stay honestly
        # NULL rather than becoming zero.
        listed_shares = self._listed_shares_map(session)

        run = BackfillRun(status="running")
        session.add(run)
        session.commit()
        summary = BackfillSummary(run_id=run.id, started_at=run.started_at)

        # Newest first: today's close matters most, and a partial run is still
        # useful if it is interrupted.
        for business_date in sorted(daterange(parse_date(start_date), parse_date(end_date)), reverse=True):
            if not force:
                existing = session.get(TradingDay, business_date)
                if existing is not None and existing.is_session is True and existing.row_count:
                    summary.skipped_existing += 1
                    continue

            outcome = await self.ingest_day(
                session, business_date, listed_shares=listed_shares
            )
            if outcome.state is DayState.SESSION:
                summary.sessions.append(outcome)
                summary.rows_written += outcome.row_count
            elif outcome.state is DayState.NON_SESSION:
                summary.non_sessions.append(outcome)
            elif outcome.state is DayState.OUT_OF_RANGE:
                summary.out_of_range.append(outcome)
                # Every earlier date is also out of range. Stop and record the
                # floor rather than issuing hundreds of doomed requests.
                summary.detected_floor = business_date
                break
            else:
                summary.failed.append(outcome)

            if pause > 0:
                await asyncio.sleep(pause)
            if progress is not None:
                progress(outcome)

        summary.finished_at = utcnow()
        run.finished_at = summary.finished_at
        run.dates_ok = len(summary.sessions)
        run.dates_empty = len(summary.non_sessions)
        run.dates_failed = len(summary.failed)
        run.rows_written = summary.rows_written
        run.status = "completed" if not summary.failed else "completed_with_errors"
        run.note = (
            f"floor={summary.detected_floor}" if summary.detected_floor else None
        )
        session.add(run)
        session.commit()
        logger.info("backfill %s finished: %s", run.id, summary.as_dict())
        return summary

    async def backfill_symbol(
        self, session: Session, symbol: str, security_id: int
    ) -> dict[str, Any]:
        """Fill one symbol from the per-symbol endpoint, newest first.

        Complements the market-wide backfill: cheaper when a single symbol is
        needed, and it reaches back to the start of NEPSE's window without
        pulling 227 whole-market days.
        """
        symbol = symbol.strip().upper()
        from app.db.models import Security  # local import avoids a cycle

        security = session.get(Security, symbol)
        listed_shares = security.listed_shares if security else None
        rows_written = 0
        pages = 0
        while True:
            try:
                envelope = await self._client.call(
                    f"sec_price:{security_id}:{pages}",
                    lambda p=pages: self._client.get_security_price_history_page(
                        security_id, p, 100
                    ),
                )
            except NepseServiceError as exc:
                return {
                    "symbol": symbol,
                    "ok": False,
                    "error": exc.code,
                    "rows_written": rows_written,
                }
            content = (envelope or {}).get("content") or []
            pages += 1
            for row in content:
                bar = bar_from_row(row, listed_shares)
                if bar is not None:
                    session.merge(bar)
                    rows_written += 1
            total_pages = int((envelope or {}).get("totalPages") or 1)
            if not content or pages >= total_pages:
                break
        session.commit()
        return {
            "symbol": symbol,
            "ok": True,
            "rows_written": rows_written,
            "pages_fetched": pages,
        }

    def clear(self, session: Session) -> dict[str, int]:
        """Delete all archived data. Used by tests and a manual rebuild."""
        bars = session.execute(delete(DailyBar)).rowcount or 0
        days = session.execute(delete(TradingDay)).rowcount or 0
        attempts = session.execute(delete(FetchAttempt)).rowcount or 0
        session.commit()
        return {"daily_bars": bars, "trading_days": days, "fetch_attempts": attempts}


def parse_date(value: str) -> date:
    """Parse an ISO date, raising ValueError with a clear message."""
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError as exc:
        raise ValueError(f"Expected an ISO date like 2026-09-28, got {value!r}") from exc
