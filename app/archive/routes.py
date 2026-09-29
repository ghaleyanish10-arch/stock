"""Archive routes: coverage, as-of resolution, backfill control."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.archive.service import ArchiveService, parse_date
from app.auth.deps import AdminUser, DbSession
from app.config import settings
from app.db.session import SessionLocal
from app.jobs.scheduler import should_run_now
from app.nepse.registry import get_adapter
from app.nepse.service import validate_symbol

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/archive", tags=["archive"])

# Shares the one process-wide NEPSE adapter, so archive requests do not open a
# second upstream session with its own rate limiter.
_archive = ArchiveService(get_adapter())


@router.get("/coverage", summary="How much history is archived")
def coverage(session: DbSession) -> dict[str, Any]:
    return _archive.coverage(session)


@router.get("/as-of", summary="Resolve a date, walking back to the last session")
def as_of(
    session: DbSession,
    date: Optional[str] = Query(
        None, description="Requested date; defaults to today (Nepal time)"
    ),
) -> dict[str, Any]:
    """Never return an empty result for a valid request.

    If the requested date is a weekend, a holiday, an unarchived date, or
    today before NEPSE has published the close, this returns the most recent
    real session and explains the substitution.
    """
    return _archive.resolve_as_of(session, date)


@router.get("/sessions", summary="Known calendar days and their status")
def sessions(
    session: DbSession,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = Query(400, ge=1, le=2000),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import TradingDay

    stmt = select(TradingDay)
    if start:
        stmt = stmt.where(TradingDay.business_date >= start[:10])
    if end:
        stmt = stmt.where(TradingDay.business_date <= end[:10])
    rows = list(session.scalars(stmt.order_by(TradingDay.business_date.desc()).limit(limit)))
    return {
        "days": [
            {
                "business_date": r.business_date,
                "is_session": r.is_session,
                "row_count": r.row_count,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                "note": r.note,
            }
            for r in rows
        ],
        "legend": {
            "true": "trading session with stored bars",
            "false": "published non-trading day (holiday or weekend)",
            "null": "unknown - never fetched, or the last fetch failed; retried",
        },
    }


@router.get("/bars/{symbol}", summary="Archived bars for one symbol")
def bars(
    symbol: str,
    session: DbSession,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = Query(600, ge=1, le=5000),
) -> dict[str, Any]:
    sym = validate_symbol(symbol)
    rows = _archive.get_bars(session, sym, start=start, end=end, limit=limit)
    return {
        "symbol": sym,
        "count": len(rows),
        "first": rows[0].business_date if rows else None,
        "last": rows[-1].business_date if rows else None,
        "bars": [
            {
                "date": r.business_date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "prev_close": r.prev_close,
                "volume": r.volume,
                "turnover": r.turnover,
                "trades": r.trades,
                "vwap": r.vwap,
                "high_52w": r.high_52w,
                "low_52w": r.low_52w,
                "market_cap": r.market_cap,
            }
            for r in rows
        ],
    }


class BackfillRequest(BaseModel):
    start: Optional[str] = Field(None, description="ISO date; defaults to the archive floor")
    end: Optional[str] = Field(None, description="ISO date; defaults to today")
    pause_ms: Optional[int] = Field(None, ge=0, le=10000)
    force: bool = Field(False, description="Re-fetch dates that are already stored")
    symbol: Optional[str] = Field(
        None, description="Backfill one symbol from the per-symbol endpoint instead"
    )


@router.post("/backfill", summary="Backfill archived history")
async def backfill(
    payload: BackfillRequest,
    background: BackgroundTasks,
    session: DbSession,
    admin: AdminUser,
) -> dict[str, Any]:
    """Ingest history from NEPSE into the local archive.

    Fetches every date from `start` to `end`. Dates already stored are skipped
    unless `force` is set, so an interrupted run resumes cheaply. Weekends and
    holidays are recorded as non-sessions; failed dates are recorded as
    *unknown* and retried on the next run rather than being recorded as
    "no data".

    Requires an admin account because it issues hundreds of upstream requests.
    """
    for field in ("start", "end"):
        value = getattr(payload, field)
        if value:
            try:
                parse_date(value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.symbol:
        return await _backfill_symbol(session, payload.symbol)

    # The task must own its own session. FastAPI closes the request-scoped one
    # as soon as the response is sent, which is before a background task runs,
    # so passing `session` in here would use a closed session.
    background.add_task(
        _run_backfill,
        payload.start,
        payload.end,
        payload.pause_ms,
        payload.force,
    )
    return {
        "detail": (
            "Backfill started in the background. Track progress with "
            "GET /api/archive/coverage and GET /api/archive/runs."
        ),
        "start": payload.start,
        "end": payload.end,
    }


async def _run_backfill(
    start: Optional[str],
    end: Optional[str],
    pause_ms: Optional[int],
    force: bool,
) -> None:
    """Backfill entry point for the background task, with its own session."""
    with SessionLocal() as session:
        try:
            result = await _archive.backfill(session, start, end, pause_ms, force)
        except Exception:
            # A background task failure is otherwise silent; the run row stays
            # unfinished, so surface it in the log and let the next run resume.
            logger.exception("background backfill failed")
            return
        logger.info("background backfill finished: %s", result)


async def _backfill_symbol(session, symbol: str) -> dict[str, Any]:
    """Per-symbol backfill, resolving the security id first."""
    from app.db.models import Security
    from sqlalchemy import select

    sym = validate_symbol(symbol)
    security = session.get(Security, sym)
    security_id = getattr(security, "nepse_security_id", None) if security else None
    if security_id is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No NEPSE security id stored for {sym}. Sync the security "
                f"master first: POST /api/reference/sync"
            ),
        )
    return await _archive.backfill_symbol(session, sym, int(security_id))


@router.get("/runs", summary="Backfill history")
def runs(session: DbSession, limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import BackfillRun

    rows = list(
        session.scalars(select(BackfillRun).order_by(BackfillRun.started_at.desc()).limit(limit))
    )
    return {
        "runs": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "sessions": r.dates_ok,
                "non_sessions": r.dates_empty,
                "failed": r.dates_failed,
                "rows_written": r.rows_written,
                "note": r.note,
            }
            for r in rows
        ]
    }


@router.get("/jobs", summary="Scheduled job history (post-close snapshot)")
def job_runs(
    session: DbSession,
    limit: int = Query(20, ge=1, le=200),
    job: str | None = Query(None, description="Filter by job name, e.g. daily_snapshot"),
) -> dict[str, Any]:
    """Recent runs of the background scheduler.

    This is how you confirm the post-close snapshot actually fired: every tick
    records a row, including `deferred` (NEPSE has not published the close yet)
    and `failed`, so a day with no bars is distinguishable from a day where the
    job never ran at all.
    """
    from sqlalchemy import select

    from app.db.models import JobRun
    from app.jobs.scheduler import nepal_now, to_nepal

    stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    if job:
        stmt = stmt.where(JobRun.job_name == job)
    rows = list(session.scalars(stmt))

    now = nepal_now()
    latest_ok = next(
        (r for r in rows if r.job_name == "daily_snapshot" and r.status == "ok"), None
    )
    return {
        "now_nepal": now.isoformat(),
        # What the scheduler is waiting for, in Nepal time.
        "post_close_time": settings.post_close_hhmm,
        "enabled": True,
        "last_success_nepal": to_nepal(latest_ok.started_at).isoformat() if latest_ok else None,
        "due_now": should_run_now(latest_ok.started_at if latest_ok else None, settings.post_close_hhmm),
        "jobs": [
            {
                "id": r.id,
                "job": r.job_name,
                "started_at": r.started_at.isoformat(),
                "started_at_nepal": to_nepal(r.started_at).isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "detail": r.detail,
            }
            for r in rows
        ],
    }
