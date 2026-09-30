"""Scheduler regression tests.

Three real bugs are locked in here:

* `utcnow()` returns *naive UTC*. The old code called `.astimezone(NPT)` on it
  directly, which makes Python assume the value is in the server's local
  timezone. On a non-UTC host that shifts the date and suppresses or duplicates
  a run.
* The old code took the most recent `JobRun` of any status as "last run", so a
  single failure at 15:36 blocked every retry for the rest of the day.
* The old code treated *any* successful run today as "done for today", so an
  intraday save (or a forced run before the close) suppressed the real
  post-close job and left the archive holding partial bars with null closes.

Plus two data-integrity guards: today must not be written off as a non-session
just because NEPSE has not published the close yet, and the job must refuse to
save anything as final while the exchange reports the market open.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.jobs.scheduler import NPT, market_is_open, should_run_now, to_nepal


class TestToNepal:
    def test_naive_utc_is_treated_as_utc_not_local(self) -> None:
        # 2026-09-27 18:20 UTC is 2026-09-28 00:05 in Nepal: the date rolls
        # forward. If the naive value were read as server-local time (as
        # `.astimezone()` does on its own) the date would be wrong.
        naive_utc = datetime(2026, 9, 27, 18, 20)
        result = to_nepal(naive_utc)
        assert result.date() == datetime(2026, 9, 28).date()
        assert result.hour == 0 and result.minute == 5

    def test_aware_input_is_converted(self) -> None:
        aware = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
        assert to_nepal(aware).hour == 11

    def test_already_nepal_stays_put(self) -> None:
        npt_time = datetime(2026, 9, 28, 11, 0, tzinfo=NPT)
        assert to_nepal(npt_time) == npt_time


class TestShouldRunNow:
    def test_never_before_post_close(self) -> None:
        # should_run_now compares against nepal_now(), which we freeze.
        assert _with_frozen_now(datetime(2026, 9, 28, 10, 0), None) is False
        assert _with_frozen_now(datetime(2026, 9, 28, 15, 29), None) is False

    def test_runs_after_post_close_when_never_run(self) -> None:
        assert _with_frozen_now(datetime(2026, 9, 28, 15, 30), None) is True
        assert _with_frozen_now(datetime(2026, 9, 28, 22, 0), None) is True

    def test_does_not_rerun_after_a_post_close_save(self) -> None:
        # Saved at 15:45 NPT, which is past the 15:30 gate, so the day is done.
        last_ok = datetime(2026, 9, 28, 10, 0)  # naive UTC == 15:45 NPT
        assert _with_frozen_now(datetime(2026, 9, 28, 20, 0), last_ok) is False

    def test_reruns_after_an_intraday_save(self) -> None:
        """An intraday save must not block the real post-close run.

        This is the exact bug: a forced run at 14:17 NPT stored partial rows
        (every close still null) and recorded `ok`, which suppressed the real
        post-close job for the rest of the day. The final figures were never
        fetched, so the archive kept a day of incomplete bars.
        """
        # 08:47 UTC == 14:32 NPT: after the gate's *clock* was irrelevant, but
        # crucially before 15:30 NPT, so this was an intraday save.
        intraday_save = datetime(2026, 9, 28, 8, 47)
        assert to_nepal(intraday_save).hour == 14
        # At 20:00 NPT the job must run again to overwrite the partial rows.
        assert _with_frozen_now(datetime(2026, 9, 28, 20, 0), intraday_save) is True

    def test_intraday_save_still_blocks_before_the_gate(self) -> None:
        """An intraday save does not make the job due at 10:00 either."""
        intraday_save = datetime(2026, 9, 28, 3, 0)  # 08:45 NPT
        assert _with_frozen_now(datetime(2026, 9, 28, 10, 0), intraday_save) is False

    def test_runs_again_the_next_day(self) -> None:
        last_ok = datetime(2026, 9, 27, 10, 0)
        assert _with_frozen_now(datetime(2026, 9, 28, 15, 40), last_ok) is True

    def test_naive_last_run_two_days_ago(self) -> None:
        last_ok = datetime(2026, 9, 26, 23, 30)  # 2026-09-27 05:15 NPT
        assert _with_frozen_now(datetime(2026, 9, 28, 16, 0), last_ok) is True

    def test_bad_hhmm_falls_back_to_default(self) -> None:
        assert _with_frozen_now(datetime(2026, 9, 28, 16, 0), None, hhmm="nonsense") is True
        assert _with_frozen_now(datetime(2026, 9, 28, 10, 0), None, hhmm="nonsense") is False


class TestLastSuccessfulRunSelection:
    @pytest.mark.anyio
    async def test_failed_run_does_not_block_retry(self) -> None:
        """A 15:36 failure must not suppress the rest of the day.

        This is the regression for the old "most recent run of any status"
        lookup. It mirrors the exact query `daily_snapshot` issues.
        """
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker

        from app.db.base import Base, utcnow
        from app.db.models import JobRun

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with Session() as s:
                s.add(JobRun(job_name="daily_snapshot", started_at=utcnow(),
                             finished_at=utcnow(), status="failed", detail="boom"))
                s.commit()

                last_ok = s.scalar(
                    select(JobRun.started_at)
                    .where(JobRun.job_name == "daily_snapshot", JobRun.status == "ok")
                    .order_by(JobRun.started_at.desc())
                    .limit(1)
                )

                # No successful run exists, so the job is still due today.
                assert last_ok is None
                assert should_run_now(last_ok, "00:01") is True
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()

    @pytest.mark.anyio
    async def test_successful_run_does_block_same_day(self) -> None:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker

        from app.db.base import Base, utcnow
        from app.db.models import JobRun

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with Session() as s:
                s.add(JobRun(job_name="daily_snapshot", started_at=utcnow(),
                             finished_at=utcnow(), status="ok", detail="300 rows"))
                s.add(JobRun(job_name="daily_snapshot", started_at=utcnow(),
                             finished_at=utcnow(), status="deferred", detail="later"))
                s.commit()

                last_ok = s.scalar(
                    select(JobRun.started_at)
                    .where(JobRun.job_name == "daily_snapshot", JobRun.status == "ok")
                    .order_by(JobRun.started_at.desc())
                    .limit(1)
                )

                # scalar() must unwrap to a real datetime, not a Row.
                assert isinstance(last_ok, datetime)
                assert last_ok.tzinfo is None
                # Today already succeeded, so even after post-close it waits.
                assert should_run_now(last_ok, "00:01") is False
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


class TestMarketOpenGuard:
    """The job must never write an intraday snapshot as if it were the close."""

    @pytest.mark.anyio
    async def test_reports_open(self) -> None:
        class _Client:
            async def call(self, _op, fn):
                return fn()

            def get_market_status(self) -> dict:
                return {"isOpen": "OPEN", "marketStatus": "OPEN"}

        assert await market_is_open(_Client()) is True

    @pytest.mark.anyio
    async def test_reports_closed(self) -> None:
        class _Client:
            async def call(self, _op, fn):
                return fn()

            def get_market_status(self) -> dict:
                return {"isOpen": "CLOSED"}

        assert await market_is_open(_Client()) is False

    @pytest.mark.anyio
    async def test_snake_case_key_also_accepted(self) -> None:
        class _Client:
            async def call(self, _op, fn):
                return fn()

            def get_market_status(self) -> dict:
                return {"is_open": True}

        assert await market_is_open(_Client()) is True

    @pytest.mark.anyio
    async def test_unknown_status_is_not_treated_as_open(self) -> None:
        """A missing field must defer the job, not block it forever.

        Returning None lets the caller decide. Silently coercing a missing
        value to "open" would stall the archive on a schema change upstream.
        """

        class _Client:
            async def call(self, _op, fn):
                return fn()

            def get_market_status(self) -> dict:
                return {"somethingElse": 1}

        assert await market_is_open(_Client()) is None

    @pytest.mark.anyio
    async def test_upstream_error_defers_rather_than_fails(self) -> None:
        class _Client:
            async def call(self, _op, fn):
                raise RuntimeError("upstream down")

            def get_market_status(self) -> dict:  # pragma: no cover - unused
                return {}

        assert await market_is_open(_Client()) is None

    @pytest.mark.anyio
    async def test_daily_snapshot_does_not_write_when_status_unknown(
        self, tmp_path, monkeypatch
    ) -> None:
        """An unreadable status must not be read as "closed".

        `market_is_open` returning None is ambiguous, so the *job* has to
        choose. Choosing "assume closed" would write a mid-session snapshot as
        the final close on exactly the run where the status check failed; the
        scheduler retries in minutes, so deferring costs nothing.

        Hermetic: runs against a throwaway database, never the real one.
        """
        import app.jobs.scheduler as scheduler
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.db import session as session_module
        from app.db.base import Base
        from app.db.models import DailyBar, JobRun

        engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'sched.sqlite3').as_posix()}")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        monkeypatch.setattr(session_module, "SessionLocal", factory)

        ingested: list[str] = []

        class _Client:
            async def call(self, _op, fn):
                return fn()

            def get_market_status(self) -> dict:
                raise RuntimeError("status endpoint down")

        class _Service:
            client = _Client()

            async def ingest_day(self, session, day, treat_empty_as_non_session=True):
                ingested.append(day)
                raise AssertionError("must not ingest when status is unknown")

        with factory() as session:
            today = scheduler.nepal_now().date().isoformat()
            before = session.scalar(
                select(func.count())
                .select_from(DailyBar)
                .where(DailyBar.business_date == today)
            )
            # Force the run past both gates so the status check is reached.
            monkeypatch.setattr(scheduler, "nepal_now", lambda: datetime(2026, 9, 28, 20, 0, tzinfo=NPT))
            monkeypatch.setattr(scheduler.settings, "post_close_hhmm", "15:30")
            result = await scheduler.daily_snapshot(_Service())
            after = session.scalar(
                select(func.count())
                .select_from(DailyBar)
                .where(DailyBar.business_date == today)
            )
            deferred = session.scalar(
                select(func.count())
                .select_from(JobRun)
                .where(
                    JobRun.job_name == "daily_snapshot", JobRun.status == "deferred"
                )
            )

        engine.dispose()
        assert ingested == []
        assert result["ran"] is False
        assert "status unavailable" in result["reason"]
        assert after == before
        assert deferred is not None and deferred >= 1


def _with_frozen_now(
    frozen: datetime, last_ok, hhmm: str = "15:30"
) -> bool:
    """Run should_run_now with nepal_now() frozen to `frozen` (Nepal time)."""
    import app.jobs.scheduler as scheduler

    original = scheduler.nepal_now
    scheduler.nepal_now = lambda: frozen.replace(tzinfo=NPT)
    try:
        return should_run_now(last_ok, hhmm)
    finally:
        scheduler.nepal_now = original


class TestRepairNullCloses:
    """Phase 3: the post-close job re-checks recent sessions for null closes.

    A day saved before the close stores rows with close = NULL, which blanks
    every indicator window spanning them (and 404s the whole summary page via
    macd). The repair walk re-ingests the most recent affected prior sessions.
    """

    @pytest.fixture()
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.db.base import Base

        engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, future=True)
        with factory() as s:
            yield s
        engine.dispose()

    def _session_day(self, db, business_date: str) -> None:
        from app.db.models import TradingDay

        db.add(TradingDay(business_date=business_date, is_session=True, row_count=1))
        db.commit()

    def _null_close_bar(self, db, business_date: str, symbol: str = "NABIL") -> None:
        from app.db.models import DailyBar

        db.add(DailyBar(business_date=business_date, symbol=symbol, close=None))
        db.commit()

    class _RepairingService:
        """Stands in for the archive service: re-ingest fills the close."""

        def __init__(self) -> None:
            self.ingested: list[str] = []

        async def ingest_day(self, session, day, treat_empty_as_non_session=True):
            from app.db.models import DailyBar

            self.ingested.append(day)
            for bar in session.query(DailyBar).filter_by(business_date=day):
                bar.close = 500.0
            session.commit()

    @pytest.mark.anyio
    async def test_reingests_prior_session_with_null_close(self, db) -> None:
        import app.jobs.scheduler as scheduler

        self._session_day(db, "2026-09-26")
        self._null_close_bar(db, "2026-09-26")
        service = self._RepairingService()

        repaired = await scheduler._repair_null_closes(service, db, "2026-09-28")

        assert service.ingested == ["2026-09-26"]
        assert repaired == ["2026-09-26"]

    @pytest.mark.anyio
    async def test_skips_sessions_without_null_closes(self, db) -> None:
        import app.jobs.scheduler as scheduler
        from app.db.models import DailyBar

        self._session_day(db, "2026-09-26")
        db.add(DailyBar(business_date="2026-09-26", symbol="NABIL", close=500.0))
        db.commit()
        service = self._RepairingService()

        repaired = await scheduler._repair_null_closes(service, db, "2026-09-28")

        assert service.ingested == []  # nothing to fix, nothing fetched
        assert repaired == []

    @pytest.mark.anyio
    async def test_never_touches_today(self, db) -> None:
        """Today was just written by this very run, after the close gate."""
        import app.jobs.scheduler as scheduler

        self._session_day(db, "2026-09-28")
        self._null_close_bar(db, "2026-09-28")
        service = self._RepairingService()

        repaired = await scheduler._repair_null_closes(service, db, "2026-09-28")

        assert service.ingested == []
        assert repaired == []

    @pytest.mark.anyio
    async def test_marks_provisional_when_nulls_survive_repair(self, db) -> None:
        """Phase 3b: a session whose closes stay null is flagged, not final.

        A day with an unresolved null close keeps a `provisional:` note, so the
        next run re-checks it instead of trusting the row count.
        """
        import app.jobs.scheduler as scheduler
        from app.db.models import TradingDay

        self._session_day(db, "2026-09-26")
        self._null_close_bar(db, "2026-09-26")

        class _StubbornService:
            async def ingest_day(self, session, day, treat_empty_as_non_session=True):
                pass  # "NEPSE still has nothing" - the null survives

        repaired = await scheduler._repair_null_closes(_StubbornService(), db, "2026-09-28")

        assert repaired == []
        note = db.get(TradingDay, "2026-09-26").note
        assert note is not None and note.startswith("provisional:")

    @pytest.mark.anyio
    async def test_repair_error_does_not_kill_the_job(self, db) -> None:
        import app.jobs.scheduler as scheduler
        from app.db.models import TradingDay

        self._session_day(db, "2026-09-26")
        self._null_close_bar(db, "2026-09-26")

        class _ExplodingService:
            async def ingest_day(self, session, day, treat_empty_as_non_session=True):
                raise RuntimeError("upstream down")

        repaired = await scheduler._repair_null_closes(_ExplodingService(), db, "2026-09-28")

        assert repaired == []
        assert db.get(TradingDay, "2026-09-26").note.startswith("provisional:")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
