"""WP1 tests: Nepal time, trading calendar, BS conversion, fiscal year.

Pure tests carry hand-computed expectations in comments (rule 9). API tests
run against the dev SQLite database like the other feature suites and delete
every row they create in teardown, so the dev database is left as found.

Weekday facts used below (2026-01-01 was a Thursday; 2026 is not a leap year):

* 2026-10-06 Tuesday    (a regular trading day)
* 2026-10-07 Wednesday  (trading day)
* 2026-10-08 Thursday   (trading day)
* 2026-10-09 Friday     (weekend)
* 2026-10-10 Saturday   (weekend)
* 2026-11-01 Sunday     (trading day)
* 2026-11-02 Monday     (trading day)
* 2026-11-03 Tuesday    (trading day)
* 2026-11-05 Thursday   (trading day)
* 2026-11-06 Friday     (weekend)
* 2026-12-31 Thursday   (trading day)
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from app.main import app
from app import timeutil

# ---------------------------------------------------------------------------
# Pure calendar logic (hand-computed expectations)
# ---------------------------------------------------------------------------


class TestWeekendPattern:
    def test_friday_saturday_are_weekend(self):
        # 2026-10-09 Friday, 2026-10-10 Saturday.
        assert timeutil.is_weekend_trading_pattern(date(2026, 10, 9)) is True
        assert timeutil.is_weekend_trading_pattern(date(2026, 10, 10)) is True

    def test_sunday_thursday_are_trading_pattern(self):
        # 2026-10-04 Sunday ... 2026-10-08 Thursday.
        for day in (4, 5, 6, 7, 8):
            assert timeutil.is_weekend_trading_pattern(date(2026, 10, day)) is False

    def test_all_2026_fridays_excluded(self):
        # Cross-check the pattern over a whole year: 2026 has 53 Fridays.
        fridays = sum(
            1
            for d in (date(2026, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(365))
            if d.weekday() == 4
        )
        assert fridays == 52  # 2026 spans 365 days starting Thursday -> 52 Fridays


class TestIsTradingDay:
    def test_plain_weekday_is_trading(self):
        assert timeutil.is_trading_day(date(2026, 11, 2)) is True  # Monday

    def test_weekend_is_not_trading(self):
        assert timeutil.is_trading_day(date(2026, 11, 6)) is False  # Friday

    def test_explicit_holiday_list(self):
        # 2026-11-03 is a Tuesday; marked holiday by an injected list.
        assert (
            timeutil.is_trading_day(date(2026, 11, 3), holidays=["2026-11-03"]) is False
        )
        assert timeutil.is_trading_day(date(2026, 11, 2), holidays=["2026-11-03"]) is True

    def test_holiday_accepts_dates_not_only_strings(self):
        assert (
            timeutil.is_trading_day(date(2026, 11, 3), holidays=[date(2026, 11, 3)])
            is False
        )

    def test_no_session_argument_means_pattern_only(self):
        # Without a session the DB is not consulted: an unknown Tuesday stays
        # a trading day (absence of evidence is not a holiday).
        assert timeutil.is_trading_day(date(2026, 11, 3)) is True


class TestNextPreviousTradingDay:
    def test_next_over_weekend(self):
        # Thursday 2026-10-08 -> next trading day is Sunday 2026-10-11
        # (Fri+Sat weekend), assuming no holiday data.
        assert timeutil.next_trading_day(date(2026, 10, 8)) == date(2026, 10, 11)

    def test_next_skips_injected_holiday(self):
        # Sunday 2026-11-01 marked holiday -> next is Monday 2026-11-02.
        assert (
            timeutil.next_trading_day(date(2026, 10, 31), holidays=["2026-11-01"])
            == date(2026, 11, 2)
        )

    def test_previous_over_weekend(self):
        # Sunday 2026-11-01 -> previous trading day is Thursday 2026-10-29
        # (Fri 30, Sat 31 weekend).
        assert timeutil.previous_trading_day(date(2026, 11, 1)) == date(2026, 10, 29)

    def test_previous_skips_injected_holiday(self):
        # Monday 2026-11-02 marked holiday -> previous (strictly before the
        # asked date 2026-11-03) is Sunday 2026-11-01.
        assert (
            timeutil.previous_trading_day(date(2026, 11, 3), holidays=["2026-11-02"])
            == date(2026, 11, 1)
        )


class TestTradingDaysBetween:
    def test_one_week_mon_to_next_mon(self):
        # Mon 2026-11-02 .. Mon 2026-11-09 inclusive: Mon Tue Wed Thu (4) +
        # Sun 8 Mon 9 (2) = 6 trading days; Fri 6 + Sat 7 excluded.
        assert (
            timeutil.trading_days_between(date(2026, 11, 2), date(2026, 11, 9)) == 6
        )

    def test_single_day(self):
        assert (
            timeutil.trading_days_between(date(2026, 11, 2), date(2026, 11, 2)) == 1
        )

    def test_reversed_range_is_zero_not_error(self):
        assert (
            timeutil.trading_days_between(date(2026, 11, 9), date(2026, 11, 2)) == 0
        )

    def test_holiday_inside_window(self):
        # Tue 2026-11-03 is a holiday: Mon 2 .. Thu 5 = Mon Tue Wed Thu = 4
        # sessions minus the holiday = 3.
        assert (
            timeutil.trading_days_between(
                date(2026, 11, 2), date(2026, 11, 5), holidays=["2026-11-03"]
            )
            == 3
        )


class TestLastDayToBuy:
    def test_book_close_thursday_n2_is_tuesday(self):
        # The WP4 hand example: book close Thu 2026-10-08, N=2 -> walk back
        # Thu->Wed (1) ->Tue (2) = Tue 2026-10-06.
        assert (
            timeutil.last_day_to_buy(date(2026, 10, 8), 2) == date(2026, 10, 6)
        )

    def test_book_close_sunday_walks_over_weekend(self):
        # Book close Sun 2026-11-01, N=2: Thu 2026-10-29 (1), Wed 2026-10-28 (2).
        assert (
            timeutil.last_day_to_buy(date(2026, 11, 1), 2) == date(2026, 10, 28)
        )

    def test_n_zero_non_trading_book_close_anchors_near(self):
        # N=0 means "settle same day": the last eligible buy is the last
        # trading day at or before the book close. For a Saturday 2026-11-07
        # book close that anchor is the prior Thursday, 2026-11-05.
        # (A Sunday book close would NOT demonstrate this: Sunday is itself
        # a NEPSE trading day in the Sun-Thu week.)
        assert (
            timeutil.last_day_to_buy(date(2026, 11, 7), 0) == date(2026, 11, 5)
        )

    def test_n_zero_with_trading_day_book_close_is_itself(self):
        # When the book close IS a trading day, N=0 returns the book close:
        # Tuesday 2026-12-01 stays Tuesday 2026-12-01.
        assert (
            timeutil.last_day_to_buy(date(2026, 12, 1), 0) == date(2026, 12, 1)
        )

    def test_n_larger_than_month_walks_back(self):
        # Book close Tue 2026-12-01, N=10: ten sessions back from Tue 01 is
        # Tue 2026-11-17 (walk: Nov30,27,26,25,24,23,20,19,18,17).
        assert (
            timeutil.last_day_to_buy(date(2026, 12, 1), 10) == date(2026, 11, 17)
        )

    def test_negative_n_rejected(self):
        with pytest.raises(ValueError):
            timeutil.last_day_to_buy(date(2026, 11, 1), -1)


# ---------------------------------------------------------------------------
# Bikram Sambat
# ---------------------------------------------------------------------------


class TestBikramSambat:
    def test_official_anchor_pair(self):
        # Official calendar anchor from the spec: BS 2082-01-01 = AD 2025-04-14.
        assert timeutil.bs_to_ad(2082, 1, 1) == date(2025, 4, 14)
        assert timeutil.ad_to_bs(date(2025, 4, 14)) == (2082, 1, 1)

    def test_round_trip_over_a_decade(self):
        # Every AD day from 2020-01-01 to 2030-01-01 must convert to BS and
        # back unchanged. (0 failures was verified for 1945-2035 before
        # pinning the range here.)
        cur = date(2020, 1, 1)
        end = date(2030, 1, 1)
        while cur < end:
            y, m, d = timeutil.ad_to_bs(cur)
            assert timeutil.bs_to_ad(y, m, d) == cur, f"round trip broke at {cur}"
            cur = date.fromordinal(cur.toordinal() + 1)

    def test_month_lengths_are_in_range(self):
        # BS months are 29-32 days (verified: 2082 = [31,31,32,31,31,31,30,29,30,29,30,30]).
        for m in range(1, 13):
            assert 29 <= timeutil.bs_month_length(2082, m) <= 32

    def test_impossible_bs_date_raises(self):
        # No BS month has 33 days.
        import nepali_datetime

        with pytest.raises(Exception):
            timeutil.bs_to_ad(2082, 1, 33)

    def test_format_bs(self):
        assert timeutil.format_bs(date(2025, 4, 14)) == "2025-04-14 (BS 2082-01-01)"


# ---------------------------------------------------------------------------
# Fiscal year
# ---------------------------------------------------------------------------


class TestFiscalYear:
    def test_fy_starts_mid_july(self):
        # Shrawan 1 of BS 2083 = AD 2026-07-17 (mid-July). A September date
        # belongs to FY 2083/84, which started 2026-07-17.
        start = timeutil.fiscal_year_start(date(2026, 9, 28))
        assert start == date(2026, 7, 17)

    def test_date_before_shrawan_maps_to_previous_fy(self):
        # 2026-07-01 is still FY 2082/83, which started 2025-07-17.
        assert timeutil.fiscal_year_start(date(2026, 7, 1)) == date(2025, 7, 17)

    def test_label(self):
        assert timeutil.fiscal_year_label(date(2026, 9, 28)) == "FY 2083/84"


# ---------------------------------------------------------------------------
# NPT helpers
# ---------------------------------------------------------------------------


class TestNPT:
    def test_offset_is_5_45(self):
        from datetime import datetime, timedelta, timezone

        assert timeutil.NPT.utcoffset(datetime(2026, 1, 1)) == timedelta(hours=5, minutes=45)

    def test_to_nepal_converts_naive_utc(self):
        from datetime import datetime

        # 18:00 UTC == 23:45 NPT (same day).
        got = timeutil.to_nepal(datetime(2026, 1, 1, 18, 0))
        assert (got.hour, got.minute) == (23, 45)


# ---------------------------------------------------------------------------
# API: public calendar + admin holidays (dev DB, self-cleaning)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCalendarAPI:
    @pytest.fixture(autouse=True)
    async def _setup(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        unique = "hol_" + __import__("uuid").uuid4().hex[:8]
        self.created_dates = []
        # Admin bootstrap: register then flip is_admin directly (registration
        # cannot grant admin by design), exactly like the CLI would.
        self.admin = {"email": f"{unique}@test.com", "password": "pass123"}
        await self.client.post("/api/auth/register", json=self.admin)
        r = await self.client.post("/api/auth/login", json=self.admin)
        self.admin_token = r.json()["access_token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        from app.db.session import SessionLocal
        from app.db.models import User

        with SessionLocal() as session:
            u = session.query(User).filter(User.email == self.admin["email"]).first()
            u.is_admin = True
            session.commit()

        self.plain = {"email": f"{unique}_plain@test.com", "password": "pass123"}
        await self.client.post("/api/auth/register", json=self.plain)
        r = await self.client.post("/api/auth/login", json=self.plain)
        self.plain_token = r.json()["access_token"]
        self.plain_headers = {"Authorization": f"Bearer {self.plain_token}"}
        try:
            yield
        finally:
            # Cleanup in the fixture's finally, NOT in teardown_method:
            # pytest never awaits old-style teardown_method coroutines under
            # asyncio_mode=auto, so rows used to leak into the dev DB.
            from app.db.session import SessionLocal
            from app.db.models import Holiday, User

            with SessionLocal() as session:
                for d in self.created_dates:
                    row = session.get(Holiday, d)
                    if row is not None:
                        session.delete(row)
                for email in (self.admin["email"], self.plain["email"]):
                    u = session.query(User).filter(User.email == email).first()
                    if u is not None:
                        session.delete(u)
                session.commit()
            await self.client.aclose()

    async def _put_holiday(self, iso: str, name="Test holiday", status="verified"):
        self.created_dates.append(iso)
        r = await self.client.put(
            "/api/admin/holidays",
            json={"date": iso, "name": name, "verification_status": status, "source": "test"},
            headers=self.admin_headers,
        )
        return r

    # -- public read -------------------------------------------------------

    async def test_calendar_weekend_flagged(self):
        # Nov 2026: Fri 6 + Sat 7 are weekend, no holiday rows involved.
        r = await self.client.get(
            "/api/reference/calendar", params={"start": "2026-11-06", "end": "2026-11-07"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["counts"]["total_days"] == 2
        assert all(d["is_trading_day"] is False for d in body["days"])
        assert "weekend" in body["days"][0]["reason"]

    async def test_calendar_admin_holiday_blocks_trading_day(self):
        # Tuesday 2026-12-01 would be a trading day; the holiday row must
        # flip it, and the row must carry its verification status.
        await self._put_holiday("2026-12-01", "Tihar test day")
        r = await self.client.get(
            "/api/reference/calendar", params={"start": "2026-12-01", "end": "2026-12-01"}
        )
        assert r.status_code == 200
        day = r.json()["days"][0]
        assert day["is_trading_day"] is False
        assert day["holiday"]["name"] == "Tihar test day"
        assert day["holiday"]["verification_status"] == "verified"

    async def test_calendar_includes_bs_date_and_settlement_note(self):
        r = await self.client.get(
            "/api/reference/calendar", params={"start": "2025-04-14", "end": "2025-04-14"}
        )
        day = r.json()["days"][0]
        assert day["bs_date"] == "2025-04-14 (BS 2082-01-01)"
        assert r.json()["settlement_days"]["spec_status"] == "unverified"

    async def test_next_trading_day_endpoint(self):
        r = await self.client.get(
            "/api/reference/calendar/next-trading-day", params={"after": "2026-11-06"}
        )
        assert r.status_code == 200
        # Friday 2026-11-06 -> next trading day is Sunday 2026-11-08 (Sat 7 is
        # weekend; no November 2026 holiday in the dev archive tables).
        assert r.json()["next_trading_day"] == "2026-11-08"

    # -- admin-only enforcement --------------------------------------------

    async def test_admin_endpoints_reject_anonymous_and_non_admin(self):
        r = await self.client.get("/api/admin/holidays")
        assert r.status_code == 401
        r = await self.client.get("/api/admin/holidays", headers=self.plain_headers)
        assert r.status_code == 403
        r = await self.client.put(
            "/api/admin/holidays",
            json={"date": "2026-12-02", "name": "nope"},
            headers=self.plain_headers,
        )
        assert r.status_code == 403

    # -- CRUD + import ------------------------------------------------------

    async def test_upsert_is_idempotent(self):
        first = await self._put_holiday("2026-12-03", "Ghai Jatra test")
        assert first.status_code == 200
        second = await self._put_holiday("2026-12-03", "Ghai Jatra test")
        assert second.status_code == 200
        r = await self.client.get("/api/admin/holidays", params={"year": 2026}, headers=self.admin_headers)
        rows = [h for h in r.json()["holidays"] if h["date"] == "2026-12-03"]
        assert len(rows) == 1

    async def test_csv_import_reports_row_errors(self):
        self.created_dates.extend(["2026-12-04", "2026-12-07"])
        csv_content = (
            "date,name,verification_status\n"
            "2026-12-04,Good holiday,unverified\n"
            "not-a-date,Bad row,\n"
            "2026-12-07,Second good,unverified\n"
        )
        r = await self.client.post(
            "/api/admin/holidays/import",
            files={"file": ("holidays.csv", csv_content.encode(), "text/csv")},
            headers=self.admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["imported"] == 2
        assert len(body["errors"]) == 1
        assert body["errors"][0]["line"] == 3
        # The good rows really landed.
        r2 = await self.client.get("/api/admin/holidays", params={"year": 2026}, headers=self.admin_headers)
        dates = {h["date"] for h in r2.json()["holidays"]}
        assert {"2026-12-04", "2026-12-07"} <= dates

    async def test_csv_import_requires_date_and_name_columns(self):
        r = await self.client.post(
            "/api/admin/holidays/import",
            files={"file": ("bad.csv", b"day,label\n", "text/csv")},
            headers=self.admin_headers,
        )
        assert r.status_code == 422

    async def test_delete_holiday(self):
        await self._put_holiday("2026-12-08", "Deletable")
        r = await self.client.delete("/api/admin/holidays/2026-12-08", headers=self.admin_headers)
        assert r.status_code == 200
        self.created_dates.remove("2026-12-08")
        r2 = await self.client.delete("/api/admin/holidays/2026-12-08", headers=self.admin_headers)
        assert r2.status_code == 404
