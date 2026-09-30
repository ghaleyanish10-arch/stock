"""Background jobs: post-close daily snapshot.

A small asyncio task rather than a full scheduler, so the app stays a single
process with no extra infrastructure. NEPSE publishes the final session
figures shortly after 15:00 NPT, so the snapshot runs a few minutes later and
is idempotent: re-running it updates the same day's bars rather than
duplicating them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from app.config import settings
from app.db.models import JobRun
from app.db.base import utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Nepal is UTC+05:45 with no daylight saving, so a fixed offset is exact and
#: avoids a tzdata dependency.
NPT = timezone(timedelta(hours=5, minutes=45))


def nepal_now() -> datetime:
    """Current time in Nepal, regardless of the server's own timezone."""
    return datetime.now(NPT)


def to_nepal(value: datetime) -> datetime:
    """Convert a stored timestamp to Nepal time.

    `app.db.base.utcnow()` returns *naive UTC*, because that is what the
    DateTime columns hold. Calling `.astimezone()` on a naive datetime makes
    Python assume it is in the server's local timezone, which on a non-UTC host
    shifts the date by a day and can suppress or duplicate a run. So the
    timezone is attached explicitly first.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(NPT)
    return value.astimezone(NPT)


def parse_hhmm(hhmm: str) -> time:
    """Parse `HH:MM`, falling back to the 15:30 default on nonsense input."""
    try:
        hour, _, minute = hhmm.partition(":")
        return time(int(hour), int(minute))
    except ValueError:
        return time(15, 30)


def should_run_now(last_success: Optional[datetime], hhmm: str) -> bool:
    """True when the post-close job still owes a *post-close* save for today.

    Two independent conditions must hold:

    1. The Nepal wall clock is at or past `hhmm`. NEPSE closes at 15:00 NPT and
       publishes the final figures shortly after, so saving before then would
       record an intraday snapshot as if it were the close.
    2. No successful run for today has already saved data *after the close*.

    The second condition is deliberately not "no successful run today". An
    intraday save (or a manual/forced run) does not satisfy it: NEPSE keeps
    revising today's rows until the close is published, so the job has to come
    back after `hhmm` and overwrite them. Only a save at or after `hhmm`
    counts as final, because only then is the data the close rather than a
    snapshot of it.

    `last_success` must be the start of a *successful* run only. Failed and
    deferred runs are excluded so a transient upstream failure is retried on
    the next tick instead of being suppressed for the rest of the day.

    Pure and side-effect free so it can be unit tested across times and
    timezones.
    """
    now = nepal_now()
    if now.timetz().replace(tzinfo=None) < parse_hhmm(hhmm):
        return False  # too early: the close is not published yet
    if last_success is None:
        return True
    saved = to_nepal(last_success)
    if saved.date() < now.date():
        return True  # nothing saved today at all
    # Saved today, but before the close: that was an intraday snapshot, so the
    # final figures still have to be fetched.
    return saved.timetz().replace(tzinfo=None) < parse_hhmm(hhmm)


def _record(job: str, status: str, detail: Optional[str] = None) -> None:
    # Resolved late, not at import time: tests rebind
    # app.db.session.SessionLocal to a throwaway database, and an import-time
    # binding would keep this job writing to the real one.
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        session.add(JobRun(job_name=job, started_at=utcnow(), finished_at=utcnow(),
                           status=status, detail=detail))
        session.commit()


async def market_is_open(client: Any) -> Optional[bool]:
    """Whether NEPSE currently reports the market open, or None if unknown.

    This is the hard guard against writing an intraday snapshot as the close.
    The wall-clock check in `should_run_now` is the primary gate, but NEPSE
    also publishes a session on days the exchange reports as trading, and a
    forced or manual invocation can arrive at any hour. If the exchange says
    the market is open, today's rows are still moving and must not be treated
    as final.

    Returns None when the status cannot be read, so an upstream hiccup defers
    the job rather than failing it.
    """
    try:
        payload = await client.call("get_market_status", client.get_market_status)
    except Exception:  # noqa: BLE001 - status is advisory, never fatal
        logger.warning("could not read market status; treating as unknown", exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("isOpen")
    if value is None:
        value = payload.get("is_open")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() == "OPEN"


async def daily_snapshot(archive_service: "ArchiveService") -> dict:
    """Fetch today's session into the archive (or today's last session).

    Only today is attempted: a date older than today is not the post-close
    snapshot's business, and a full backfill is the explicit
    `POST /api/archive/backfill` action.

    After ingesting today, also re-check recent sessions for null closes
    and re-ingest them so indicators never blank out.
    """
    from sqlalchemy import select

    from app.archive.service import DayState
    from app.db.models import DailyBar, TradingDay

    # Resolved late, like in _record(): tests rebind app.db.session.SessionLocal
    # to a throwaway database, and an import-time binding would pin this job to
    # whichever module object was current when scheduler.py was first imported.
    from app.db.session import SessionLocal

    today = nepal_now().date().isoformat()
    with SessionLocal() as session:
        # Only a successful run counts as "done for today". Selecting the most
        # recent run of any status would let a 15:36 failure block every
        # retry until tomorrow.
        last_ok = session.scalar(
            select(JobRun.started_at)
            .where(JobRun.job_name == "daily_snapshot", JobRun.status == "ok")
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        if not should_run_now(last_ok, settings.post_close_hhmm):
            return {"ran": False, "reason": "not due yet or already saved after close today"}

        # Second gate: never write today's rows as final while the exchange
        # still reports the market open, however the run was triggered.
        is_open = await market_is_open(archive_service.client)
        if is_open:
            _record(
                "daily_snapshot",
                "deferred",
                "market is open; today's rows are still moving and are not the close",
            )
            return {"ran": False, "reason": "market is open; refusing to save intraday data as final"}
        if is_open is None:
            # Status unreadable. The safe reading of "I could not confirm the
            # market has closed" is "it may not have closed": a scheduled run
            # will retry, and a manual one can be re-triggered. Writing here
            # would risk stamping a 14:30 snapshot as the final close on the
            # one run where the status check happens to fail.
            logger.warning(
                "market status unavailable; deferring the daily snapshot rather "
                "than assuming the market has closed"
            )
            _record(
                "daily_snapshot",
                "deferred",
                "market status unavailable; not writing an unverified final snapshot",
            )
            return {"ran": False, "reason": "market status unavailable; refusing to save"}

        try:
            # Today is expected to trade, so a zero-row response is treated as
            # "close not published yet" and left unknown rather than being
            # recorded as a non-session. Recording it would suppress the day's
            # real data permanently.
            outcome = await archive_service.ingest_day(
                session, today, treat_empty_as_non_session=False
            )
        except Exception as exc:  # noqa: BLE001 - a job must not kill the loop
            logger.exception("daily snapshot failed")
            _record("daily_snapshot", "failed", str(exc)[:400])
            return {"ran": False, "reason": f"error: {exc}"}

        if outcome.state is DayState.OUT_OF_RANGE:
            # The market has not published a close for today yet.
            _record("daily_snapshot", "deferred", "NEPSE has not published today's close")
            return {"ran": False, "reason": "NEPSE has not published today's session yet"}

        if outcome.state is DayState.DEFERRED:
            _record("daily_snapshot", "deferred", outcome.error or "no rows for today yet")
            return {"ran": False, "reason": outcome.error or "no rows for today yet"}

        if outcome.state is DayState.FAILED:
            _record("daily_snapshot", "failed", outcome.error)
            return {"ran": False, "reason": outcome.error}

        _record(
            "daily_snapshot",
            "ok",
            f"{today}: {outcome.row_count} rows ({outcome.state.value})",
        )

        # --- Re-check recent sessions for null closes and repair them ---
        # A session with any null close breaks indicator windows (SMA, EMA, RSI,
        # ...) and blanks the Technical page. Re-ingest the most recent prior
        # sessions whose bars still carry a null close - never today: today is
        # the session this run just wrote, and the post-close gate above already
        # guarantees it was fetched after the close.
        repaired = await _repair_null_closes(archive_service, session, today)

        return {"ran": True, "date": today, "rows": outcome.row_count,
                "state": outcome.state.value, "repaired_dates": repaired}


async def _repair_null_closes(
    archive_service: "ArchiveService",
    session: "Session",
    today: str,
    lookback: int = 5,
) -> list[str]:
    """Re-ingest recent *prior* sessions whose bars still have a null close.

    A day saved before the close (forced run, crash, partial publish) stores
    rows with `close = NULL`. Those nulls poison every indicator window that
    spans them, so the post-close job walks the most recent prior sessions,
    re-fetches the ones that have any, and verifies the result. Sessions whose
    rows were incomplete but could not be repaired are re-marked with a
    `provisional:` note so the next run retries them.

    Returns the list of dates that were re-ingested (repaired or not).
    """
    from sqlalchemy import func, select

    from app.db.models import DailyBar, TradingDay

    stmt = (
        select(TradingDay.business_date)
        .where(TradingDay.is_session.is_(True))
        .where(TradingDay.business_date < today)  # never today itself
        .order_by(TradingDay.business_date.desc())
        .limit(lookback)
    )
    prior_dates = list(session.scalars(stmt))

    repaired: list[str] = []
    for d in prior_dates:
        null_count = session.scalar(
            select(func.count())
            .select_from(DailyBar)
            .where(DailyBar.business_date == d)
            .where(DailyBar.close.is_(None))
        )
        if not null_count:
            continue
        row = session.get(TradingDay, d)
        rows_before = row.row_count if row is not None else None
        logger.info("daily_snapshot: repairing %d null closes for %s", null_count, d)
        try:
            # A prior date we still expect to have traded: an empty response is
            # "not published / transient", not a holiday, so keep it unknown
            # (DEFERRED) rather than writing the day off as a non-session.
            outcome = await archive_service.ingest_day(
                session, d, treat_empty_as_non_session=False
            )
        except Exception as exc:  # noqa: BLE001 - repair must not kill the job
            logger.warning("daily_snapshot: repair re-ingest failed for %s: %s", d, exc)
            outcome = None

        still_null = session.scalar(
            select(func.count())
            .select_from(DailyBar)
            .where(DailyBar.business_date == d)
            .where(DailyBar.close.is_(None))
        )
        if still_null:
            # Re-ingest did not produce a complete day. Flag the session as
            # provisional so the next run retries it (Phase 3b: a session is
            # only final when every row has a close).
            if row is not None:
                row.note = f"provisional: {still_null} closes still null after repair"
                session.add(row)
            logger.warning(
                "daily_snapshot: %s remains provisional (%d closes still null)",
                d, still_null,
            )
        else:
            if row is not None:
                row.note = None  # fully repaired: the session is final again
                session.add(row)
            repaired.append(d)
            logger.info(
                "daily_snapshot: repaired %s (rows %s -> %s)",
                d, rows_before, outcome.row_count if outcome else None,
            )
    session.commit()
    return repaired


async def job_loop(archive_service: "ArchiveService", interval_seconds: int = 900) -> None:
    """Run the post-close snapshot check on a fixed interval, forever."""
    logger.info("scheduler started (interval=%ss, post-close at %s NPT)",
                interval_seconds, settings.post_close_hhmm)
    while True:
        try:
            result = await daily_snapshot(archive_service)
            if result.get("ran"):
                logger.info("daily snapshot: %s", result)
        except asyncio.CancelledError:
            logger.info("scheduler stopped")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("scheduler iteration failed")
        await asyncio.sleep(interval_seconds)
