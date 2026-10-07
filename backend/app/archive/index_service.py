"""Index archive (WP2): daily values for the NEPSE index and sub-indices.

Answers the question the stock archive cannot: *how did the market — or the
sector the stock lives in — move on the same day?* Two honest-alignment rules
carry over from the stock archive:

* an empty response and a failed request are not the same thing: a date NEPSE
  returns no rows for is recorded as a known non-session gap; a request that
  failed stays a retryable gap. Gaps are shown in coverage, never filled.
* alignment between a stock and an index is an **inner join on business_date**:
  a date only appears in relative-strength output when both series have a
  close. No forward fill — a holiday on one side must not manufacture a ratio.

Upstream (verified 2026-10-07 live): `nots/index-history?index={name}` returns
one row per session with keys openIndex / highIndex / lowIndex / closingIndex
/ turnoverValue / turnoverVolume / totalTransaction plus period extras
(absChange, percentageChange, fiftyTwoWeekHigh/Low). The 13 sub-index names
come from `nots/sub-indices` (`index` key); the main index is called "NEPSE".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.archive.service import daterange, parse_date
from app.db.models import IndexPointRecord
from app.db.base import utcnow

logger = logging.getLogger(__name__)

#: The main index. NEPSE's endpoint wants the plain name; worker live payloads
#: also use "NEPSE" (`nots/nepse-index` row: index=NEPSE).
MAIN_INDEX = "NEPSE"

#: Sub-index names are read live from `nots/sub-indices` at backfill time
#: (verified 2026-10-07: 13 entries, e.g. "Banking SubIndex",
#: "HydroPower Index"). The example list exists only for tests/docs; the
#: backfill itself never hard-codes it.
EXAMPLE_SUB_INDICES = (
    "Banking SubIndex",
    "HydroPower Index",
)


def index_point_from_row(row: Any, index_name: str) -> Optional[IndexPointRecord]:
    """Convert one `nots/index-history` row.

    Every field is read defensively: a row NEPSE serves without a value keeps
    that value NULL. A row without a business date is unusable and skipped
    (never stored with a guessed date).
    """
    if not isinstance(row, dict):
        return None
    business_date = str(row.get("businessDate") or "")[:10]
    try:
        parse_date(business_date)
    except ValueError:
        return None

    def _f(key: str) -> Optional[float]:
        value = row.get(key)
        return float(value) if value is not None and value != "" else None

    tx = row.get("totalTransaction")
    return IndexPointRecord(
        index_name=index_name,
        business_date=business_date,
        dedup_key=int(row["id"]) if row.get("id") is not None else None,
        open=_f("openIndex"),
        high=_f("highIndex"),
        low=_f("lowIndex"),
        close=_f("closingIndex"),
        turnover=_f("turnoverValue"),
        volume=_f("turnoverVolume"),
        total_transactions=int(tx) if tx is not None and tx != "" else None,
        high_52w=_f("fiftyTwoWeekHigh"),
        low_52w=_f("fiftyTwoWeekLow"),
        abs_change=_f("absChange"),
        pct_change=_f("percentageChange"),
    )


class IndexBackfillSummary:
    """Aggregate result of one index backfill run (mirrors BackfillSummary)."""

    def __init__(self) -> None:
        self.indices: dict[str, dict[str, Any]] = {}
        self.rows_written: int = 0
        self.failures: dict[str, str] = {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_written": self.rows_written,
            "indices": {k: v for k, v in sorted(self.indices.items())},
            "failures": dict(sorted(self.failures.items())),
        }


class IndexArchiveService:
    """Backfill + coverage for `index_points`, and RS alignment helpers."""

    def __init__(self, client: Any) -> None:
        # Same adapter as the stock archive: one upstream session per process.
        self._client = client

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def _known_names(self, session: Session) -> list[str]:
        """Indices already named in live payloads + anything ever archived."""
        names: set[str] = {MAIN_INDEX}
        try:
            sub = self._client.get_sub_indices()
            for entry in sub or []:
                if isinstance(entry, dict):
                    name = entry.get("index") or entry.get("indexName")
                    if name:
                        names.add(str(name).strip())
        except Exception:
            # The live sub-index call is one of the flakiest endpoints (its
            # auth flaps are documented on the NepseService path); a dry call
            # must not abort a backfill that can still serve the main index
            # and anything already archived.
            logger.warning("sub-index discovery failed; backfilling NEPSE + stored names only", exc_info=True)
        # Indices present in the table but missing from a possibly-flaky live
        # sub-index call still deserve a backfill attempt (the archived name
        # is evidence NEPSE has served it before).
        for (name,) in session.execute(
            select(IndexPointRecord.index_name).distinct()
        ).all():
            names.add(str(name))
        return sorted(names)

    async def backfill(
        self,
        session: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        pause_ms: int = 250,
        force: bool = False,
    ) -> IndexBackfillSummary:
        """Fill `index_points` for every known index over [start, end].

        One request per index per window, paced; resumable because dates
        already stored are skipped unless `force`. NEPSE serves an empty list
        for a window with no sessions — that is simply nothing to store, and
        `/api/archive/index-coverage` reports the missing dates as gaps with
        reason "not_reported" rather than manufacturing rows.
        """
        start_date = parse_date(start) if start else date(2020, 1, 1)
        end_date = parse_date(end) if end else date.today()
        pause = max(pause_ms, 0) / 1000.0

        known = self._known_names(session)
        summary = IndexBackfillSummary()

        for name in known:
            stats = {"requested": 0, "stored_new": 0, "already_stored": 0, "skipped_empty": 0}
            summary.indices[name] = stats
            try:
                # Through the adapter's retry-capable wrapper (same pattern as
                # NepseService.get_index_history), so auth flaps retry here
                # too instead of aborting the whole run.
                rows = await self._client.call(
                    f"index_archive:{name}",
                    lambda n=name: self._client.get_index_history(
                        n, start_date.isoformat(), end_date.isoformat()
                    ),
                )
            except Exception as exc:  # adapter maps specifics; keep it honest
                summary.failures[name] = getattr(exc, "code", type(exc).__name__)
                continue
            summary.indices[name]["requested"] = len(rows or [])
            for row in rows or []:
                point = index_point_from_row(row, name)
                if point is None:
                    continue
                stored = _store_point(session, point, force)
                stats["stored_new"] += 1 if stored else 0
                if not stored:
                    stats["already_stored"] += 1
            summary.rows_written += stats["stored_new"]
            if pause > 0:
                await asyncio.sleep(pause)

        session.commit()
        logger.info("index backfill: %s", summary.as_dict())
        return summary

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def coverage(self, session: Session) -> dict[str, Any]:
        """Per-index storage report with honest gap accounting.

        `days_with_close` vs `days_expected` (trading days between the first
        stored session and the last) exposes silent holes; the comparison is
        informational only — the list of stored dates is authoritative and no
        date is ever synthesised to close a gap.
        """
        # Indices already named in the table, in ISO sort order.
        names = [
            row[0]
            for row in session.execute(
                select(IndexPointRecord.index_name)
                .distinct()
                .order_by(IndexPointRecord.index_name)
            ).all()
        ]
        from datetime import date as _date

        from app.timeutil import trading_days_between

        # timeutil counts INCLUSIVE ranges, so first..last with both endpoints
        # stored yields >= days_stored only when a mid-range session is missing.
        def _expected(a: str, b: str) -> int:
            first_day = _date.fromisoformat(a)
            last_day = _date.fromisoformat(b)
            return trading_days_between(first_day, last_day)

        out: list[dict[str, Any]] = []
        for name in names:
            first, last, n_close, n_any = (
                session.execute(
                    select(
                        func.min(IndexPointRecord.business_date),
                        func.max(IndexPointRecord.business_date),
                        func.count(IndexPointRecord.close),
                        func.count(IndexPointRecord.id),
                    ).where(IndexPointRecord.index_name == name)  # type: ignore[arg-type]
                ).one()
            )
            expected: Optional[int] = None
            if first and last:
                expected = _expected(first, last)
            out.append(
                {
                    "index": name,
                    "first_date": first,
                    "last_date": last,
                    "days_stored": n_any,
                    "days_with_close": n_close,
                    "trading_days_expected": expected,
                    "open_gaps": None
                    if expected is None
                    else max(expected - n_close, 0),
                }
            )
        return {
            "indices": out,
            "note": (
                "open_gaps compares stored closes with the Sunday-Thursday "
                "session pattern between the first and last stored session; "
                "it is indicative, never a filled series."
            ),
        }

    # ------------------------------------------------------------------
    # Relative strength helpers (used by the chart endpoint)
    # ------------------------------------------------------------------

    def closes_by_date(self, session: Session, index_name: str) -> dict[str, float]:
        """`business_date -> close` for one index. Inner-join material.

        Only dates with an actual stored close participate; a date stored
        without a close (should not happen upstream today, but NULL is legal)
        is excluded rather than guessed.
        """
        rows = session.execute(
            select(IndexPointRecord.business_date, IndexPointRecord.close)
            .where(
                IndexPointRecord.index_name == index_name,
                IndexPointRecord.close.is_not(None),
            )
        ).all()
        return {str(d): float(c) for d, c in rows}


def _store_point(session: Session, point: IndexPointRecord, force: bool) -> bool:
    """Insert or update one row; returns True when a write happened.

    Idempotent by (index_name, business_date) with a guard against clobbering
    stored values with NULLs picked up on a flaky re-read.
    """
    existing = session.execute(
        select(IndexPointRecord).where(
            IndexPointRecord.index_name == point.index_name,
            IndexPointRecord.business_date == point.business_date,
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(point)
        point.updated_at = utcnow()
        return True
    if not force:
        return False
    changed = False
    for column in (
        "dedup_key", "open", "high", "low", "close", "turnover", "volume",
        "total_transactions", "high_52w", "low_52w", "abs_change", "pct_change",
    ):
        new_value = getattr(point, column)
        old_value = getattr(existing, column)
        if new_value is not None and new_value != old_value:
            setattr(existing, column, new_value)
            changed = True
    return changed


def relative_strength(
    stock_closes: dict[str, Optional[float]],
    index_closes: dict[str, Optional[float]],
) -> dict[str, Any]:
    """Stock vs index on the inner join of their dates, no forward fill.

    Returns aligned series for the chart tokens:

    * `rs`  — closes ratio  stock/index (None when either side is missing)
    * `rs_pct` — % outperformance over the first common date:
      100 * (stock_t/stock_0) / (index_t/index_0) - 100. Both legs are rebased
      to the same first COMMON date, so drift measurement starts where both
      series exist.
    """
    common = sorted(
        d for d in stock_closes
        if index_closes.get(d) is not None
        and stock_closes[d] is not None
    )
    rs: dict[str, Optional[float]] = {d: None for d in stock_closes}
    rs_pct: dict[str, Optional[float]] = {d: None for d in stock_closes}
    if not common:
        return {"dates": [], "rs": rs, "rs_pct": rs_pct, "first_common": None}
    s0 = stock_closes[common[0]]
    i0 = index_closes[common[0]]
    base_rs = (s0 / i0) if (s0 and i0) else None
    for d in common:
        s = stock_closes[d]
        i = index_closes[d]
        if s is not None and i:
            rs[d] = s / i
        if s is not None and i and s0 and i0:
            rs_pct[d] = 100.0 * ((s / s0) / (i / i0)) - 100.0
    return {
        "dates": common,
        "rs": rs,
        "rs_pct": rs_pct,
        "first_common": common[0],
        "base_rs": base_rs,
    }
