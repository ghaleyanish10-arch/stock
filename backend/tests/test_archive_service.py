"""Archive service: the empty-vs-failed distinction and the walk-back rule.

These tests encode the rule the whole archive rests on: a 200 with no rows is a
holiday, an error is a failure, and neither is ever recorded as "no data".
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.archive.service import (
    ArchiveService,
    DayState,
    bar_from_row,
    daterange,
    parse_date,
)
from app.db.base import Base
from app.db.models import DailyBar, FetchAttempt, TradingDay
from app.nepse.exceptions import (
    NepseDateOutOfRangeError,
    NepseRateLimitedError,
    NepseServiceError,
    NepseUnavailableError,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        yield s
    engine.dispose()


class FakeAdapter:
    """Stands in for the NEPSE adapter, scripted per business date."""

    def __init__(self, script: dict[str, object]) -> None:
        self.script = script
        self.calls: list[str] = []

    def get_today_price_page(self, business_date=None, page=0, size=500):
        self.calls.append(str(business_date))
        outcome = self.script.get(str(business_date), [])
        if isinstance(outcome, Exception):
            raise outcome
        if not outcome:
            return {"content": [], "totalPages": 1}
        return {"content": outcome, "totalPages": 1}

    async def call(self, operation, fn):
        return fn()

    def get_security_price_history_page(self, security_id, page=0, size=100):
        return {"content": [], "totalPages": 0}


def row(symbol="NABIL", date="2025-12-01", close=500.0, **over):
    payload = {
        "symbol": symbol,
        "businessDate": date,
        "openPrice": 495.0,
        "highPrice": 505.0,
        "lowPrice": 490.0,
        "closePrice": close,
        "previousDayClosePrice": 480.0,
        "totalTradedQuantity": 1000,
        "totalTradedValue": 500000.0,
        "totalTrades": 20,
        "averageTradedPrice": 500.0,
        "fiftyTwoWeekHigh": 600.0,
        "fiftyTwoWeekLow": 400.0,
    }
    payload.update(over)
    return payload


class TestDaterange:
    def test_inclusive(self):
        got = daterange(date(2025, 12, 1), date(2025, 12, 3))
        assert got == ["2025-12-01", "2025-12-02", "2025-12-03"]

    def test_reversed_is_empty(self):
        assert daterange(date(2025, 12, 3), date(2025, 12, 1)) == []

    def test_same_day(self):
        assert daterange(date(2025, 12, 1), date(2025, 12, 1)) == ["2025-12-01"]

    def test_parse_date_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_date("not-a-date")


class TestBarFromRow:
    def test_full_row(self):
        bar = bar_from_row(row(), listed_shares=1000)
        assert bar is not None
        assert bar.symbol == "NABIL"
        assert bar.close == 500.0
        assert bar.volume == 1000
        assert bar.market_cap == 500_000.0  # 1000 shares * 500

    def test_market_cap_derivation(self):
        bar = bar_from_row(row(close=512.4), listed_shares=2_000_000)
        assert bar.market_cap == pytest.approx(1_024_800_000.0)

    def test_missing_market_cap_when_no_shares(self):
        # NULL listed shares -> market cap stays unknown, NOT zero.
        bar = bar_from_row(row(), listed_shares=None)
        assert bar.market_cap is None

    def test_missing_close_is_none(self):
        bar = bar_from_row(row(closePrice=None))
        assert bar.close is None
        assert bar.market_cap is None

    def test_empty_string_is_missing_not_zero(self):
        bar = bar_from_row(row(closePrice=""))
        assert bar.close is None

    def test_zero_close_is_preserved(self):
        bar = bar_from_row(row(closePrice=0.0))
        assert bar.close == 0.0

    def test_row_without_symbol_is_skipped(self):
        assert bar_from_row(row(symbol="")) is None

    def test_row_without_date_is_skipped(self):
        assert bar_from_row(row(businessDate="")) is None

    def test_nepse_reported_marcap_is_not_stored(self):
        # NEPSE's own marketCapitalization is in millions NPR, which is a
        # classic unit trap, so it is deliberately not persisted.
        bar = bar_from_row(row(marketCapitalization=3762.85), listed_shares=1000)
        assert bar.market_cap == 500_000.0
        assert not hasattr(bar, "market_cap_reported")


class TestIntradayRowsAreOverwritten:
    """An intraday save must not be sticky.

    NEPSE republishes the same business date all afternoon: an early snapshot
    carries a null close, and the published close carries the real one. The
    archive keys bars on (business_date, symbol), so the later save has to
    replace the earlier values rather than being skipped as a duplicate.
    """

    def test_post_close_save_replaces_intraday_values(self, session):
        date = "2026-09-28"
        partial = row("NABIL", date, close=None, totalTradedQuantity=100)
        svc = ArchiveService(FakeAdapter({date: [partial]}))

        first = asyncio.run(svc.ingest_day(session, date))
        assert first.state is DayState.SESSION
        bar = session.query(DailyBar).filter_by(symbol="NABIL", business_date=date).one()
        assert bar.close is None, "intraday snapshot has no close yet"
        assert bar.volume == 100

        # Same date, now published: close and volume both move.
        final = row("NABIL", date, close=512.0, totalTradedQuantity=9000)
        svc = ArchiveService(FakeAdapter({date: [final]}))
        second = asyncio.run(svc.ingest_day(session, date))

        assert second.state is DayState.SESSION
        # No duplicate row was inserted.
        assert session.query(DailyBar).filter_by(symbol="NABIL", business_date=date).count() == 1
        bar = session.query(DailyBar).filter_by(symbol="NABIL", business_date=date).one()
        assert bar.close == 512.0, "the final close must replace the null"
        assert bar.volume == 9000

    def test_reingesting_the_same_snapshot_is_idempotent(self, session):
        date = "2026-09-28"
        payload = [row("NABIL", date), row("NICA", date)]
        svc = ArchiveService(FakeAdapter({date: payload}))

        asyncio.run(svc.ingest_day(session, date))
        asyncio.run(svc.ingest_day(session, date))

        assert session.query(DailyBar).count() == 2
        assert session.get(TradingDay, date).row_count == 2


class TestIngestDay:
    def test_session_with_rows(self, session):
        svc = ArchiveService(FakeAdapter({"2025-12-01": [row(), row("NICA")]}))
        outcome = asyncio.run(svc.ingest_day(session, "2025-12-01"))
        assert outcome.state is DayState.SESSION
        assert outcome.row_count == 2

        day = session.get(TradingDay, "2025-12-01")
        assert day.is_session is True
        assert day.row_count == 2
        assert session.query(DailyBar).count() == 2

    def test_holiday_is_recorded_as_non_session(self, session):
        """200 with zero rows is a real non-session, not a gap."""
        svc = ArchiveService(FakeAdapter({"2025-10-21": []}))
        outcome = asyncio.run(svc.ingest_day(session, "2025-10-21"))
        assert outcome.state is DayState.NON_SESSION

        day = session.get(TradingDay, "2025-10-21")
        assert day.is_session is False  # explicitly False, not None
        assert day.note

    def test_out_of_range_is_unknown_not_holiday(self, session):
        """A date outside NEPSE's window must NOT be recorded as a holiday."""
        svc = ArchiveService(
            FakeAdapter({"2025-08-24": NepseDateOutOfRangeError()})
        )
        outcome = asyncio.run(svc.ingest_day(session, "2025-08-24"))
        assert outcome.state is DayState.OUT_OF_RANGE

        day = session.get(TradingDay, "2025-08-24")
        assert day.is_session is None  # unknown -> retried
        assert day.row_count is None

    def test_expected_trading_day_with_no_rows_is_deferred(self, session):
        """Today, before NEPSE publishes the close, must stay unknown.

        Recording it as a non-session would permanently suppress the day's real
        data, so the post-close snapshot passes
        treat_empty_as_non_session=False.
        """
        svc = ArchiveService(FakeAdapter({"2026-09-28": []}))
        outcome = asyncio.run(
            svc.ingest_day(session, "2026-09-28", treat_empty_as_non_session=False)
        )
        assert outcome.state is DayState.DEFERRED

        day = session.get(TradingDay, "2026-09-28")
        assert day.is_session is None  # unknown, NOT False
        assert day.row_count is None
        assert "re-check" in (day.note or "")

    def test_deferred_day_is_retried_and_then_stores_rows(self, session):
        """A deferred day must be re-fetchable once the close is published."""
        adapter = FakeAdapter({"2026-09-28": []})
        svc = ArchiveService(adapter)
        first = asyncio.run(
            svc.ingest_day(session, "2026-09-28", treat_empty_as_non_session=False)
        )
        assert first.state is DayState.DEFERRED

        # NEPSE publishes; the same date is fetched again.
        adapter.script["2026-09-28"] = [row(date="2026-09-28")]
        second = asyncio.run(
            svc.ingest_day(session, "2026-09-28", treat_empty_as_non_session=False)
        )
        assert second.state is DayState.SESSION
        assert second.row_count == 1

        day = session.get(TradingDay, "2026-09-28")
        assert day.is_session is True
        assert day.row_count == 1
        assert session.query(DailyBar).count() == 1

    def test_transient_failure_leaves_date_unknown(self, session):
        svc = ArchiveService(FakeAdapter({"2025-12-02": NepseUnavailableError()}))
        outcome = asyncio.run(svc.ingest_day(session, "2025-12-02"))
        assert outcome.state is DayState.FAILED
        assert outcome.error == "NEPSE_UNAVAILABLE"

        day = session.get(TradingDay, "2025-12-02")
        assert day.is_session is None
        assert "NEPSE_UNAVAILABLE" in day.note

    def test_rate_limit_propagates(self, session):
        """A 429 must abort the run so we stop hammering NEPSE."""
        svc = ArchiveService(FakeAdapter({"2025-12-02": NepseRateLimitedError()}))
        with pytest.raises(NepseRateLimitedError):
            asyncio.run(svc.ingest_day(session, "2025-12-02"))

    def test_every_attempt_is_audited(self, session):
        svc = ArchiveService(
            FakeAdapter({"2025-12-01": [row()], "2025-10-21": [], "2025-12-02": NepseUnavailableError()})
        )
        for d in ("2025-12-01", "2025-10-21", "2025-12-02"):
            try:
                asyncio.run(svc.ingest_day(session, d))
            except NepseRateLimitedError:
                pass
        attempts = list(session.scalars(select(FetchAttempt).order_by(FetchAttempt.business_date)))
        assert len(attempts) == 3
        ok_flags = {a.business_date: a.ok for a in attempts}
        # A holiday is a successful fetch; an error is not.
        assert ok_flags["2025-10-21"] is True
        assert ok_flags["2025-12-01"] is True
        assert ok_flags["2025-12-02"] is False

    def test_upsert_does_not_duplicate(self, session):
        svc = ArchiveService(FakeAdapter({"2025-12-01": [row()]}))
        asyncio.run(svc.ingest_day(session, "2025-12-01"))
        asyncio.run(svc.ingest_day(session, "2025-12-01"))
        assert session.query(DailyBar).count() == 1

    def test_refetch_updates_changed_values(self, session):
        adapter = FakeAdapter({"2025-12-01": [row(close=500.0)]})
        svc = ArchiveService(adapter)
        asyncio.run(svc.ingest_day(session, "2025-12-01"))
        adapter.script["2025-12-01"] = [row(close=555.0)]
        asyncio.run(svc.ingest_day(session, "2025-12-01"))
        assert session.query(DailyBar).one().close == 555.0


class TestBackfill:
    def test_skips_known_sessions_without_force(self, session):
        adapter = FakeAdapter(
            {
                "2025-12-03": [row(date="2025-12-03")],
                "2025-12-02": [row(date="2025-12-02")],
                "2025-12-01": [row(date="2025-12-01")],
            }
        )
        svc = ArchiveService(adapter)
        first = asyncio.run(
            svc.backfill(session, "2025-12-01", "2025-12-03", pause_ms=0)
        )
        assert len(first.sessions) == 3
        first_calls = len(adapter.calls)

        second = asyncio.run(
            svc.backfill(session, "2025-12-01", "2025-12-03", pause_ms=0)
        )
        assert second.skipped_existing == 3
        assert len(second.sessions) == 0
        assert len(adapter.calls) == first_calls  # no requests made

    def test_retries_only_failed_dates(self, session):
        adapter = FakeAdapter(
            {
                "2025-12-02": NepseUnavailableError(),
                "2025-12-01": [row(date="2025-12-01")],
            }
        )
        svc = ArchiveService(adapter)
        first = asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-02", pause_ms=0))
        assert len(first.sessions) == 1
        assert len(first.failed) == 1

        # Second run: the failed date is retried, the good one is skipped.
        adapter.script["2025-12-02"] = [row(date="2025-12-02")]
        second = asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-02", pause_ms=0))
        assert len(second.sessions) == 1
        assert second.sessions[0].business_date == "2025-12-02"
        assert second.skipped_existing == 1
        assert second.failed == []

    def test_market_cap_uses_stored_listed_shares(self, session):
        """Enriched securities get a real market cap on archived bars.

        NEPSE's live marketCapitalization is null and its historical one is in
        millions, so the archive derives cap from listed shares instead. Those
        shares are stored by the reference service's enrich step, and backfill
        must read them rather than leaving every cap NULL.
        """
        from app.db.models import Security

        session.add(
            Security(symbol="NABIL", name="Nabil Bank", listed_shares=1000)
        )
        session.add(
            Security(symbol="NOBUY", name="Never Enriched", listed_shares=None)
        )
        session.commit()

        adapter = FakeAdapter(
            {
                "2025-12-01": [
                    row(symbol="NABIL", date="2025-12-01", close=500.0),
                    row(symbol="NOBUY", date="2025-12-01", close=100.0),
                ]
            }
        )
        svc = ArchiveService(adapter)
        asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-01", pause_ms=0))

        enriched = session.query(DailyBar).filter_by(symbol="NABIL").one()
        assert enriched.market_cap == 500_000.0  # 1000 * 500

        # An unenriched symbol must stay NULL, never become 0.
        unenriched = session.query(DailyBar).filter_by(symbol="NOBUY").one()
        assert unenriched.market_cap is None

    def test_listed_shares_map_ignores_nulls(self, session):
        from app.db.models import Security

        session.add_all(
            [
                Security(symbol="A", name="A", listed_shares=500),
                Security(symbol="B", name="B", listed_shares=None),
                Security(symbol="C", name="C", listed_shares=0),
            ]
        )
        session.commit()
        # A reported 0 is a real value, so it is kept; only None is dropped.
        assert ArchiveService._listed_shares_map(session) == {"A": 500, "C": 0}

    def test_out_of_range_stops_and_records_floor(self, session):
        adapter = FakeAdapter(
            {
                "2025-12-02": [row(date="2025-12-02")],
                "2025-12-01": NepseDateOutOfRangeError(),
                "2025-11-30": [row(date="2025-11-30")],  # must never be requested
            }
        )
        svc = ArchiveService(adapter)
        summary = asyncio.run(
            svc.backfill(session, "2025-11-30", "2025-12-02", pause_ms=0)
        )
        assert summary.detected_floor == "2025-12-01"
        assert "2025-11-30" not in adapter.calls  # stopped walking back
        assert session.get(TradingDay, "2025-11-30") is None

    def test_newest_first(self, session):
        adapter = FakeAdapter({d: [row(date=d)] for d in ("2025-12-01", "2025-12-02", "2025-12-03")})
        svc = ArchiveService(adapter)
        asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-03", pause_ms=0))
        assert adapter.calls == ["2025-12-03", "2025-12-02", "2025-12-01"]

    def test_holidays_do_not_block_progress(self, session):
        adapter = FakeAdapter(
            {
                "2025-12-04": [row(date="2025-12-04")],
                "2025-12-03": [],
                "2025-12-02": [row(date="2025-12-02")],
                "2025-12-01": [row(date="2025-12-01")],
            }
        )
        svc = ArchiveService(adapter)
        summary = asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-04", pause_ms=0))
        assert len(summary.sessions) == 3
        assert len(summary.non_sessions) == 1
        assert summary.rows_written == 3
        assert summary.failed == []

    def test_force_refetches(self, session):
        adapter = FakeAdapter({"2025-12-01": [row(date="2025-12-01")]})
        svc = ArchiveService(adapter)
        asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-01", pause_ms=0))
        asyncio.run(svc.backfill(session, "2025-12-01", "2025-12-01", pause_ms=0, force=True))
        assert adapter.calls == ["2025-12-01", "2025-12-01"]


class TestResolveAsOf:
    def _seed(self, session, days):
        for d, is_session in days:
            session.add(TradingDay(business_date=d, is_session=is_session))
        session.commit()

    def test_exact_session(self, session):
        self._seed(session, [("2026-09-24", True), ("2026-09-23", True)])
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, "2026-09-24")
        assert result["resolved"] == "2026-09-24"
        assert result["walked_back"] is False

    def test_holiday_walks_back(self, session):
        self._seed(session, [("2026-09-24", True), ("2026-09-25", False)])
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, "2026-09-25")
        assert result["resolved"] == "2026-09-24"
        assert result["walked_back"] is True
        assert "non-trading day" in result["reason"]

    def test_unarchived_date_walks_back(self, session):
        """The case that matters most: today before NEPSE has closed."""
        self._seed(session, [("2026-09-24", True)])
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, "2026-09-28")
        assert result["resolved"] == "2026-09-24"
        assert "not been archived" in result["reason"]

    def test_unknown_day_explains_itself(self, session):
        self._seed(session, [("2026-09-24", True), ("2026-09-25", None)])
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, "2026-09-25")
        assert result["resolved"] == "2026-09-24"
        assert "not been archived" in result["reason"]

    def test_no_sessions_at_all(self, session):
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, "2026-09-28")
        assert result["resolved"] is None
        assert result["walked_back"] is False

    def test_defaults_to_latest(self, session):
        self._seed(session, [("2026-09-23", True), ("2026-09-24", True)])
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, None)
        assert result["resolved"] == "2026-09-24"

    def test_never_returns_a_date_after_the_request(self, session):
        self._seed(session, [("2026-09-24", True), ("2026-09-28", True)])
        svc = ArchiveService(FakeAdapter({}))
        result = svc.resolve_as_of(session, "2026-09-25")
        assert result["resolved"] == "2026-09-24"
        assert result["resolved"] <= "2026-09-25"


class TestCoverage:
    def test_counts_states_separately(self, session):
        session.add_all(
            [
                TradingDay(business_date="2026-09-23", is_session=True, row_count=400),
                TradingDay(business_date="2026-09-24", is_session=True, row_count=410),
                TradingDay(business_date="2026-09-25", is_session=False),
                TradingDay(business_date="2026-09-22", is_session=None),
            ]
        )
        session.commit()
        svc = ArchiveService(FakeAdapter({}))
        cov = svc.coverage(session)
        assert cov["sessions"] == 2
        assert cov["non_sessions"] == 1
        assert cov["unknown_days"] == 1
        assert cov["known_days"] == 4
        assert cov["first_session"] == "2026-09-23"
        assert cov["last_session"] == "2026-09-24"
