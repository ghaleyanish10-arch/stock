"""WP2 test suite: index archive + relative strength.

Hand-computed expectations throughout; the stock-vs-index alignment rule is
the inner join: a date only produces an RS value when BOTH sides have a close
that day. Gaps are never forward-filled -- a holiday on either side leaves the
point None on the chart too.

Pure classes use in-memory SQLite (as in test_archive_service.py); endpoint
tests run against the live dev DB with self-cleaning rows (same convention as
tests/test_timeutil.py) because the archive routes use the app's real
dependency graph.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.archive.index_service import (
    MAIN_INDEX,
    IndexArchiveService,
    index_point_from_row,
    relative_strength,
)
from app.db.base import Base
from app.db.models import IndexPointRecord


# ---------------------------------------------------------------------------
# Fixture data: real upstream row shape (verified live 2026-10-07)
# ---------------------------------------------------------------------------


def index_row(d: str, close: float, **over) -> dict:
    """One `nots/index-history` row for NEPSE, faithful to the live keys."""
    payload = {
        "businessDate": d,
        "closingIndex": close,
        "openIndex": close - 10.0,
        "highIndex": close + 5.0,
        "lowIndex": close - 15.0,
        "turnoverValue": 3_000_000_000.0,
        "turnoverVolume": 8_000_000,
        "totalTransaction": 40_000,
        "id": abs(hash(d)) % 100000,
        "fiftyTwoWeekHigh": 2960.4,
        "fiftyTwoWeekLow": 2487.17,
        "absChange": 11.96,
        "percentageChange": 0.46,
    }
    payload.update(over)
    return payload


class FakeIndexAdapter:
    """Scripted the way the pathologic archive tests script theirs."""

    def __init__(self, script: dict[str, dict[str, list[dict]]]):
        self.script = script  # {index_name: {window_key: rows}}
        self.calls: list[tuple[str, str]] = []

    def get_sub_indices(self) -> list[dict]:
        return [
            {"index": "Banking SubIndex", "close": 1200.0},
            {"index": "HydroPower Index", "close": 500.0},
        ]

    def get_index_history(self, index: str, start_date=None, end_date=None) -> list[dict]:
        self.calls.append((index, f"{start_date}..{end_date}"))
        per_index = self.script.get(index, {})
        window = per_index.get("all", [])
        wanted_start = (start_date or "")[:10]
        wanted_end = (end_date or "")[:10]
        return [
            r
            for r in window
            if wanted_start <= str(r.get("businessDate", ""))[:10] <= wanted_end
        ]

    async def call(self, operation, fn):
        return fn()


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


class TestIndexPointFromRow:
    def test_full_row_maps_every_verified_key(self):
        point = index_point_from_row(index_row("2026-10-06", 2578.73), "NEPSE")
        assert point.index_name == "NEPSE"
        assert point.business_date == "2026-10-06"
        assert point.open == pytest.approx(2568.73)
        assert point.high == pytest.approx(2583.73)
        assert point.low == pytest.approx(2563.73)
        assert point.close == pytest.approx(2578.73)
        assert point.volume == 8_000_000
        assert point.total_transactions == 40_000
        assert point.pct_change == pytest.approx(0.46)
        assert point.high_52w == pytest.approx(2960.4)

    def test_missing_values_stay_none_never_zero(self):
        # A row without OHLC must not become a zero-value day (real zeros are
        # reported zeros; missing values are NULL, per archive rules).
        point = index_point_from_row(
            {"businessDate": "2026-10-06", "closingIndex": None}, "NEPSE"
        )
        assert point.close is None
        assert point.open is None
        assert point.volume is None
        assert point.total_transactions is None

    def test_row_without_date_is_unusable(self):
        assert index_point_from_row({"closingIndex": 2600.0}, "NEPSE") is None

    def test_garbage_row_is_none(self):
        assert index_point_from_row("not a dict", "NEPSE") is None

    def test_sub_index_name_is_kept_verbatim(self):
        row = index_row("2026-10-06", 1240.5)
        point = index_point_from_row(row, "Banking SubIndex")
        assert point.index_name == "Banking SubIndex"


# ---------------------------------------------------------------------------
# Relative strength helper (pure)
# ---------------------------------------------------------------------------


class TestRelativeStrength:
    def test_hand_computed_first_and_last(self):
        # Mon-Thu NEPSE week, Nov 2026: Sun 1, Mon 2, Tue 3, Thu 5.
        stock = {
            "2026-11-01": 100.0,
            "2026-11-02": 105.0,
            "2026-11-03": 110.0,
            "2026-11-05": 120.0,
        }
        index = {
            "2026-11-01": 1000.0,
            "2026-11-02": 1010.0,
            "2026-11-03": 1030.0,
            "2026-11-05": 1050.0,
        }
        rs = relative_strength(stock, index)
        assert rs["dates"] == [
            "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-05"
        ]
        # raw ratios: 100/1000 = 0.1; 105/1010 = 0.10396; 110/1030; 120/1050.
        assert rs["rs"]["2026-11-01"] == pytest.approx(0.1)
        assert rs["rs"]["2026-11-05"] == pytest.approx(120.0 / 1050.0)
        # pct legs: stock 1.00, 1.05, 1.10, 1.20; index 1.000, 1.010, 1.030, 1.050
        # rs_pct = 100 * (s_t/s_0) / (i_t/i_0) - 100
        assert rs["rs_pct"]["2026-11-02"] == pytest.approx(
            100.0 * (1.05 / 1.01) - 100.0
        )
        assert rs["rs_pct"]["2026-11-05"] == pytest.approx(
            100.0 * (1.20 / 1.05) - 100.0
        )  # +14.2857%
        assert rs["base_rs"] == pytest.approx(0.1)
        assert rs["first_common"] == "2026-11-01"

    def test_index_missing_date_leaves_point_none(self):
        # Stock has Tue-Fri; the index skips Wednesday (a non-session on the
        # index side, e.g. a gap in the archive). Wednesday stays None: the
        # chart must not interpolate an index value the market never reported.
        stock = {
            "2026-11-02": 100.0,
            "2026-11-03": 110.0,
            "2026-11-04": 120.0,
        }
        index = {"2026-11-02": 1000.0, "2026-11-04": 1020.0}
        rs = relative_strength(stock, index)
        assert rs["rs"]["2026-11-03"] is None
        assert rs["rs"]["2026-11-04"] == pytest.approx(120.0 / 1020.0)
        # The stock close alone never manufactures an rs_pct either.
        assert rs["rs_pct"]["2026-11-03"] is None

    def test_disjoint_dates_give_empty_result(self):
        rs = relative_strength({"2026-11-02": 100.0}, {"2026-11-03": 1000.0})
        assert rs["dates"] == []
        assert rs["rs"] == {"2026-11-02": None}
        assert rs["first_common"] is None

    def test_zero_index_close_is_not_a_ratio(self):
        # A close of 0 (real zero or corrupt row) can't be divided by: the day
        # is skipped rather than dividing to infinity.
        rs = relative_strength(
            {"2026-11-02": 100.0, "2026-11-03": 110.0},
            {"2026-11-02": 1000.0, "2026-11-03": 0.0},
        )
        assert rs["rs"]["2026-11-03"] is None


# ---------------------------------------------------------------------------
# Backfill + coverage with a scripted adapter (pure DB, in-memory)
# ---------------------------------------------------------------------------


class _ServiceTestBase:
    def _session(self):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        return factory()


class TestBackfill(_ServiceTestBase):
    async def test_no_invented_dates(self):
        # Scripted rows exist for Oct 5 and Oct 6 only -- the backfill must
        # write exactly those two rows for NEPSE, never a filled calendar.
        adapter = FakeIndexAdapter(
            {
                MAIN_INDEX: {
                    "all": [
                        index_row("2026-10-05", 2500.0),
                        index_row("2026-10-06", 2578.73),
                    ]
                }
            }
        )
        service = IndexArchiveService(adapter)
        s = self._session()
        summary = await service.backfill(s, "2026-09-01", "2026-10-07")
        assert summary.failures == {}
        rows = list(
            s.scalars(
                select(IndexPointRecord)
                .where(IndexPointRecord.index_name == MAIN_INDEX)
                .order_by(IndexPointRecord.business_date)
            )
        )
        assert [r.business_date for r in rows] == ["2026-10-05", "2026-10-06"]
        assert summary.rows_written == 2
        s.close()

    async def test_resumable_skips_stored_dates(self):
        rows = [
            index_row("2026-10-05", 2500.0),
            index_row("2026-10-06", 2578.73),
        ]
        adapter = FakeIndexAdapter({MAIN_INDEX: {"all": rows}})
        service = IndexArchiveService(adapter)
        s = self._session()
        await service.backfill(s, "2026-09-01", "2026-10-07")
        # Second run: same window, no force -- everything already stored.
        summary = await service.backfill(s, "2026-09-01", "2026-10-07")
        stats = summary.indices[MAIN_INDEX]
        assert stats["already_stored"] == 2
        assert stats["stored_new"] == 0
        assert summary.rows_written == 0
        n = len(list(s.scalars(select(IndexPointRecord))))
        assert n == 2
        s.close()

    async def test_force_overwrites_closed_values(self):
        adapter = FakeIndexAdapter(
            {MAIN_INDEX: {"all": [index_row("2026-10-06", 2500.0)]}}
        )
        service = IndexArchiveService(adapter)
        s = self._session()
        await service.backfill(s, "2026-10-01", "2026-10-07")

        # Upstream revised the closing value to 2578.73 (as if the row updated); force re-read.
        adapter.script[MAIN_INDEX]["all"] = [index_row("2026-10-06", 2578.73)]
        summary = await service.backfill(s, "2026-10-01", "2026-10-07", force=True)
        assert summary.rows_written >= 1
        row = s.scalars(
            select(IndexPointRecord).where(IndexPointRecord.business_date == "2026-10-06")
        ).one()
        assert row.close == pytest.approx(2578.73)
        s.close()

    async def test_sub_indices_are_discovered_and_stored(self):
        adapter = FakeIndexAdapter(
            {
                "Banking SubIndex": {
                    "all": [index_row("2026-10-06", 1234.5)]
                },
                MAIN_INDEX: {"all": [index_row("2026-10-06", 2578.73)]},
            }
        )
        service = IndexArchiveService(adapter)
        s = self._session()
        summary = await service.backfill(s, "2026-10-01", "2026-10-07")
        assert set(summary.indices) == {
            MAIN_INDEX,
            "Banking SubIndex",
            "HydroPower Index",
        }  # NEPSE + both scripted names, HydroPower left absent (no rows made)
        n_bank = len(
            list(
                s.scalars(
                    select(IndexPointRecord).where(
                        IndexPointRecord.index_name == "Banking SubIndex"
                    )
                )
            )
        )
        assert n_bank == 1
        s.close()

    async def test_upstream_failure_is_recorded_not_silent(self):
        class _Broken(FakeIndexAdapter):
            def get_index_history(self, index, start_date=None, end_date=None):
                if index == MAIN_INDEX:
                    raise RuntimeError("NEPSE_DOWN")
                return []

        adapter = _Broken({})
        service = IndexArchiveService(adapter)
        s = self._session()
        summary = await service.backfill(s, "2026-10-01", "2026-10-07")
        assert MAIN_INDEX in summary.failures
        s.close()


class TestCoverage(_ServiceTestBase):
    def _store(self, session, rows):
        for d, c in rows:
            session.add(
                IndexPointRecord(
                    index_name="NEPSE",
                    business_date=d,
                    close=c,
                )
            )
        session.commit()

    def test_gaps_reported_not_filled(self):
        s = self._session()
        service = IndexArchiveService(FakeIndexAdapter({}))
        self._store(s, [("2026-10-05", 2500.0), ("2026-10-06", 2578.73)])
        body = service.coverage(s)
        nepse = next(i for i in body["indices"] if i["index"] == "NEPSE")
        # Oct 5 (Mon) to Oct 6 (Tue): exactly two trading days (inclusive
        # count, not span+1), both stored.
        assert nepse["days_stored"] == 2
        assert nepse["days_with_close"] == 2
        assert nepse["trading_days_expected"] == 2
        assert nepse["open_gaps"] == 0
        s.close()

    def test_open_gap_detected_over_a_weekend_sweep(self):
        # Stored: Fri Oct 9 and Mon Oct 12. In-range expected trading days
        # via the Sun-Thu rule: Oct 9 (Fri? -- NO, Friday is NOT a NEPSE
        # session; see the weekend note below) -- so instead Fri/Mon over the
        # western weekend is a poor fixture for this calendar: use Thu-Mon
        # (Oct 8 -> Oct 12): Thu 8, Sun 11, Mon 12 = 3 trading days if
        # nothing else existed; we store just Thu 8 and Mon 12, leaving Sun
        # 11 as the hole.
        s = self._session()
        service = IndexArchiveService(FakeIndexAdapter({}))
        self._store(s, [("2026-10-08", 2600.0), ("2026-10-12", 2620.0)])
        body = service.coverage(s)
        nepse = next(i for i in body["indices"] if i["index"] == "NEPSE")
        assert nepse["days_stored"] == 2
        assert nepse["days_with_close"] == 2
        # Sessions in [Thu 8, Mon 12]: Thu 8, Sun 11, Mon 12 = 3. Friday 9 and
        # Saturday 10 are the Nepali weekend, NOT sessions. Sun 11 is stored
        # on neither side here, so exactly one open gap.
        assert nepse["trading_days_expected"] == 3
        assert nepse["open_gaps"] == 1
        s.close()


# ---------------------------------------------------------------------------
# Metrics: the chart endpoint's rs/rs_pct tokens (pure geometry)
# ---------------------------------------------------------------------------


class TestChartTokensGeometry(_ServiceTestBase):
    """Token routing decisions that don't need HTTP."""

    def test_no_forward_fill(self):
        # Repeated from the helper level for discoverability: a missing index
        # date between two stored ones must not be interpolated on the chart.
        rs = relative_strength(
            {"2026-11-01": 100.0, "2026-11-02": 105.0, "2026-11-03": 110.0},
            {"2026-11-01": 1000.0, "2026-11-03": 1010.0},
        )
        assert rs["rs"]["2026-11-02"] is None
        assert rs["dates"] == ["2026-11-01", "2026-11-03"]


# ---------------------------------------------------------------------------
# Endpoint tests against the live dev DB (self-cleaning, WP1 convention)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexEndpoints:
    """HTTP behaviour of /api/archive/backfill-indices + index-coverage."""

    @pytest.fixture(autouse=True)
    async def _setup(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        self.client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        unique = "idxarc_" + uuid.uuid4().hex[:8]
        self.created_dates: list[tuple[str, str]] = []
        # ASGITransport does not run app lifespan, so init_db() never fires in
        # these tests; ensure the WP2 table exists before the endpoint writes.
        from app.db import models as db_models
        from app.db import session as db_session

        db_models.Base.metadata.create_all(bind=db_session.engine)
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
        # A parked non-admin user must also receive 403.
        self.plain = {"email": f"{unique}_p@test.com", "password": "pass123"}
        await self.client.post("/api/auth/register", json=self.plain)
        r = await self.client.post("/api/auth/login", json=self.plain)
        self.plain_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        try:
            yield
        finally:
            # Cleanup in the fixture's finally, NOT in teardown_method:
            # pytest never awaits old-style teardown_method coroutines under
            # asyncio_mode=auto (the WP1 lesson).
            from app.db.session import SessionLocal
            from app.db.models import IndexPointRecord, User

            with SessionLocal() as session:
                for name, iso in self.created_dates:
                    row = session.execute(
                        select(IndexPointRecord).where(
                            IndexPointRecord.index_name == name,
                            IndexPointRecord.business_date == iso,
                        )
                    ).scalar_one_or_none()
                    if row is not None:
                        session.delete(row)
                for email in (self.admin["email"], self.plain["email"]):
                    u = session.query(User).filter(User.email == email).first()
                    if u is not None:
                        session.delete(u)
                session.commit()
            await self.client.aclose()

    def _track(self, report: dict) -> int:
        from app.db.session import SessionLocal
        from app.db.models import IndexPointRecord

        tracked = 0
        with SessionLocal() as session:
            for name, stats in report.get("indices", {}).items():
                if not stats.get("stored_new"):
                    continue
                rows = list(
                    session.scalars(
                        select(IndexPointRecord).where(IndexPointRecord.index_name == name)
                    )
                )
                for row in rows:
                    self.created_dates.append((row.index_name, row.business_date))
                    tracked += 1
        return tracked

    async def test_backfill_requires_admin(self):
        # Anonymous -> 401; enabled non-admin -> 403 (WP1 admin-router rule).
        r = await self.client.post("/api/archive/backfill-indices", json={})
        assert r.status_code == 401
        r = await self.client.post(
            "/api/archive/backfill-indices", json={}, headers=self.plain_headers
        )
        assert r.status_code == 403

    async def test_backfill_api_and_coverage(self):
        # Scripted adapter (offline-deterministic, same pattern as
        # test_nepse_api.py's monkeypatched service): real upstream row shape.
        import app.archive.routes as archive_routes

        scripted = IndexArchiveService(
            FakeIndexAdapter(
                {
                    MAIN_INDEX: {
                        "all": [
                            index_row("2026-10-05", 2500.0),
                            index_row("2026-10-06", 2578.73),
                        ]
                    },
                    "Banking SubIndex": {"all": [index_row("2026-10-06", 1234.5)]},
                }
            )
        )
        original = archive_routes._index_archive
        archive_routes._index_archive = scripted
        try:
            payload = {"start": "2026-10-04", "end": "2026-10-06", "pause_ms": 0}
            r = await self.client.post(
                "/api/archive/backfill-indices",
                json=payload,
                headers=self.admin_headers,
            )
        finally:
            archive_routes._index_archive = original
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True, body
        tracked = self._track(body)
        assert tracked == 3, f"expected 3 scripted rows to land: {body}"

        # Coverage reads whatever is in the dev DB now.
        r = await self.client.get("/api/archive/index-coverage")
        assert r.status_code == 200
        cov = r.json()
        assert cov["indices"], "coverage should list stored indices"
        nepse = next(
            (i for i in cov["indices"] if i["index"] == "NEPSE"),
            None,
        )
        assert nepse is not None, "NEPSE must be among the stored indices"
        assert nepse["last_date"] >= "2026-10-05"

    async def test_backfill_bad_date_is_422(self):
        r = await self.client.post(
            "/api/archive/backfill-indices",
            json={"start": "not-a-date"},
            headers=self.admin_headers,
        )
        assert r.status_code == 422
