"""Market visualisation: treemap and sector pie, computed from the archive.

Both views read the same `SymbolMetrics` the screener uses, so a tile's colour
and the same symbol's screener row can never disagree.

Periods are calendar windows measured back from each symbol's own latest bar.
When the archive is not old enough for the requested window the symbol is
reported in `skipped` with the reason, and `coverage` states the archived range
in the response, so the UI can warn before the user trusts a 1Y number.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.analytics.screening import (
    NOT_ENOUGH_HISTORY,
    PERIOD_DAYS,
    PERIOD_LABELS,
    SCREENER_COLUMNS,
    SIZE_METRICS,
    ScreenerFilter,
    SymbolMetrics,
    apply_screener_filters,
    build_series,
    compute_metrics,
    sector_breakdown,
    sort_screener,
    treemap_tiles,
)
from app.archive.service import ArchiveService
from app.auth.deps import DbSession
from app.db.models import DailyBar, Security
from app.db.session import SessionLocal
from app.nepse.registry import get_adapter


router = APIRouter(prefix="/api/analytics", tags=["visualisation"])
_archive = ArchiveService(get_adapter())

#: The colour legend is fixed at +/-6% so colours mean the same thing in every
#: period and every sizing mode. Beyond +/-6% the colour clamps, and the tile
#: still prints the true number.
LEGEND_MAX_PCT = 6.0


def _archived_coverage() -> dict[str, Any]:
    from sqlalchemy import func

    with SessionLocal() as s:
        lo, hi = s.execute(
            select(func.min(DailyBar.business_date), func.max(DailyBar.business_date))
        ).one()
        sessions = s.execute(
            select(func.count(func.distinct(DailyBar.business_date)))
        ).scalar_one()
    return {
        "first": lo,
        "last": hi,
        "sessions": sessions or 0,
        "note": (
            "Periods are measured back from the latest archived session. A window "
            "longer than the archive holds is reported as unavailable rather than "
            "being silently shortened."
        ),
    }


def _coverage_days(coverage: dict[str, Any]) -> Optional[int]:
    """Longest return window the archive can measure, in calendar days.

    A `days`-long return needs a base bar on or before `as_of - days`, so the
    ceiling is the gap *between* the first and last archived bar - not their
    inclusive count. An archive from 2025-09-28 to 2026-09-28 spans 365 days
    and therefore cannot supply the 366-day anchor a 1Y return needs, even
    though it holds 366 distinct dates.
    """
    first, last = coverage.get("first"), coverage.get("last")
    if not first or not last:
        return None
    return (date.fromisoformat(last) - date.fromisoformat(first)).days


def _load_metrics(session: DbSession) -> list[SymbolMetrics]:
    """Every symbol's full metric set, from one scan of the bars table."""
    bars = session.execute(select(DailyBar)).scalars().all()
    securities = {
        s.symbol: s for s in session.execute(select(Security)).scalars().all()
    }
    series = build_series(bars, securities)
    return [compute_metrics(s) for s in series.values()]


@router.get("/visualisation/periods", summary="Available periods and sizing metrics")
async def periods() -> dict[str, Any]:
    """The selector options, with the coverage that limits them.

    Availability is measured against the archive rather than assumed. The 1Y
    window is 366 calendar days, and an archive that spans 365 of them cannot
    produce a truthful 1Y return for *any* symbol; advertising the option
    anyway would hand the user a map that silently draws nothing.
    """
    coverage = _archived_coverage()
    options: list[dict[str, Any]] = []
    for key in PERIOD_DAYS:
        days = PERIOD_DAYS[key]
        entry: dict[str, Any] = {
            "value": key,
            "label": PERIOD_LABELS[key],
            "calendar_days": days,
            "available": True,
            "reason": None,
        }
        if days is not None:
            have = _coverage_days(coverage)
            if have is not None and days > have:
                entry["available"] = False
                entry["reason"] = (
                    f"A {PERIOD_LABELS[key]} return needs {days} days of archived "
                    f"prices; the archive holds {have} "
                    f"({coverage['first']} to {coverage['last']}). Backfill more "
                    f"sessions to enable it."
                )
        options.append(entry)
    return {
        "periods": options,
        "size_metrics": [
            {"value": "market_cap", "label": "Market cap"},
            {"value": "volume", "label": "Volume"},
            {"value": "turnover", "label": "Turnover"},
        ],
        "legend": {"min_pct": -LEGEND_MAX_PCT, "max_pct": LEGEND_MAX_PCT},
        "coverage": _archived_coverage(),
    }


@router.get("/visualisation/heatmap", summary="Treemap tiles and sector shares")
async def heatmap(
    session: DbSession,
    period: str = Query("1D", description="1D | 1W | 1M | 3M | 6M | 1Y | YTD"),
    size: str = Query("market_cap", description="market_cap | volume | turnover"),
    limit: int = Query(250, ge=10, le=568),
) -> dict[str, Any]:
    """Tiles for the treemap plus the sector aggregation for the pie view.

    Tiles are capped by `limit` because a 568-tile treemap is unreadable; the
    cap is reported in `truncated` so the UI can say what it left out instead of
    presenting a partial map as the whole market.
    """
    if period not in PERIOD_DAYS:
        raise HTTPException(400, f"Unknown period {period!r}. Expected one of {sorted(PERIOD_DAYS)}.")
    if size not in SIZE_METRICS:
        raise HTTPException(400, f"Unknown size {size!r}. Expected one of {list(SIZE_METRICS)}.")

    metrics = _load_metrics(session)
    if not metrics:
        raise HTTPException(
            404,
            "The archive is empty. Run POST /api/archive/backfill to populate it.",
        )

    tiles, skipped = treemap_tiles(metrics, period, size)
    truncated = max(0, len(tiles) - limit)
    sectors = sector_breakdown(metrics, period, size)

    coverage = _archived_coverage()
    # When *nothing* can be drawn, say why in one place. The per-symbol
    # `skipped` list is still returned, but an empty canvas with 480 identical
    # reasons reads as a broken map rather than a coverage limit.
    unavailability: Optional[str] = None
    if not tiles:
        days = PERIOD_DAYS[period]
        have = _coverage_days(coverage)
        if days is not None and have is not None and days > have:
            unavailability = (
                f"A {PERIOD_LABELS[period]} return needs {days} days of archived "
                f"prices; the archive holds {have} "
                f"({coverage['first']} to {coverage['last']}). Backfill more "
                f"sessions, or pick a shorter period."
            )

    return {
        "period": period,
        "period_label": PERIOD_LABELS[period],
        "size": size,
        "legend": {"min_pct": -LEGEND_MAX_PCT, "max_pct": LEGEND_MAX_PCT},
        "tiles": tiles[:limit],
        "sectors": sectors,
        "counts": {
            "scanned": len(metrics),
            "drawn": min(len(tiles), limit),
            "skipped": len(skipped),
            "truncated": truncated,
        },
        "skipped": skipped[:50],
        "unavailable_reason": unavailability,
        "coverage": coverage,
        "notes": {
            "market_cap": (
                "Market cap is listed shares x LTP. NEPSE publishes listed shares "
                "for only some securities, so symbols without them are skipped "
                "with a reason instead of being drawn at zero size."
            ),
            "colour": (
                f"Colour is the period return, clamped to +/-{LEGEND_MAX_PCT:.0f}%. "
                "The tile always prints the true percentage."
            ),
            "unavailable_period": NOT_ENOUGH_HISTORY,
        },
    }


@router.get("/screener", summary="Filter and rank by price, volume and technicals")
async def screener(
    session: DbSession,
    sector: Optional[str] = Query(None, description="Exact sector code"),
    min_ltp: Optional[float] = None,
    max_ltp: Optional[float] = None,
    min_market_cap: Optional[float] = None,
    max_market_cap: Optional[float] = None,
    min_change_pct: Optional[float] = None,
    max_change_pct: Optional[float] = None,
    min_volume: Optional[float] = None,
    min_turnover: Optional[float] = None,
    min_ret_5d: Optional[float] = None,
    max_ret_5d: Optional[float] = None,
    min_ret_1m: Optional[float] = None,
    max_ret_1m: Optional[float] = None,
    min_ret_3m: Optional[float] = None,
    max_ret_3m: Optional[float] = None,
    min_ret_6m: Optional[float] = None,
    max_ret_6m: Optional[float] = None,
    min_ret_1y: Optional[float] = None,
    max_ret_1y: Optional[float] = None,
    min_ret_ytd: Optional[float] = None,
    max_ret_ytd: Optional[float] = None,
    min_rsi: Optional[float] = Query(None, ge=0, le=100),
    max_rsi: Optional[float] = Query(None, ge=0, le=100),
    min_day_low: Optional[float] = None,
    max_day_high: Optional[float] = None,
    above_vwap_180d: Optional[bool] = Query(
        None, description="True = LTP above the 180-day VWAP"
    ),
    sort: str = Query("market_cap", description="Column to sort by"),
    descending: bool = Query(True),
    limit: int = Query(100, ge=1, le=568),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Rank securities on archived price, volume and technical data only.

    Deliberately no fundamentals: NEPSE publishes no reliable fundamentals API,
    so a P/E or EPS filter would be fabrications. The response carries a
    `fundamentals` block marking the provider as a stub and `earnings` marked
    disabled with its reason, so the UI can show those controls greyed out
    rather than pretending they are available.
    """
    filters: list[ScreenerFilter] = []
    for field_name, lo, hi in (
        ("ltp", min_ltp, max_ltp),
        ("market_cap", min_market_cap, max_market_cap),
        ("change_pct", min_change_pct, max_change_pct),
        ("volume", min_volume, None),
        ("turnover", min_turnover, None),
        ("ret_5d", min_ret_5d, max_ret_5d),
        ("ret_1m", min_ret_1m, max_ret_1m),
        ("ret_3m", min_ret_3m, max_ret_3m),
        ("ret_6m", min_ret_6m, max_ret_6m),
        ("ret_1y", min_ret_1y, max_ret_1y),
        ("ret_ytd", min_ret_ytd, max_ret_ytd),
        ("rsi_14", min_rsi, max_rsi),
        ("day_low", min_day_low, None),
        ("day_high", None, max_day_high),
    ):
        if lo is not None or hi is not None:
            filters.append(ScreenerFilter(field=field_name, min=lo, max=hi))
    if sector:
        filters.append(ScreenerFilter(field="sector", min=sector))  # type: ignore[arg-type]
    if above_vwap_180d is not None:
        filters.append(
            ScreenerFilter(field="ltp", above_vwap=above_vwap_180d)
        )

    metrics = _load_metrics(session)
    if not metrics:
        raise HTTPException(404, "The archive is empty. Run POST /api/archive/backfill first.")

    filtered, rejections, null_drops = apply_screener_filters(metrics, filters)
    if sort not in SCREENER_COLUMNS:
        # A bad column is the caller's mistake, not a server fault: 500 here
        # would read as "the screener is broken".
        raise HTTPException(
            400,
            f"Unknown sort column {sort!r}. Sortable: {', '.join(SCREENER_COLUMNS)}.",
        )
    ordered = sort_screener(filtered, sort, descending)
    page = ordered[offset : offset + limit]

    return {
        "rows": [m.to_dict() for m in page],
        "total": len(ordered),
        "offset": offset,
        "limit": limit,
        "sort": sort,
        "descending": descending,
        "columns": [
            {"field": f, "label": label} for f, label in SCREENER_COLUMNS.items()
        ],
        "rejected_by": [{"field": r.field, "count": r.count} for r in rejections],
        "undecidable": null_drops,
        "coverage": _archived_coverage(),
        "fundamentals": {
            "available": False,
            "status": "stub",
            "reason": (
                "No fundamentals provider is configured. NEPSE publishes no "
                "reliable fundamentals API, so P/E, EPS, ROE and book value "
                "filters are not offered rather than being filled with guesses."
            ),
        },
        "earnings": {
            "available": False,
            "reason": (
                "NEPSE publishes no earnings calendar or results feed. Quarterly "
                "earnings filters are disabled until a provider is configured."
            ),
        },
        "notes": {
            "missing_values": (
                "A null cell is missing, not zero. Rows without the value a filter "
                "needs are excluded from that filter and counted in `undecidable`."
            ),
            "vwap": "180D VWAP uses typical price (H+L+C)/3 weighted by volume.",
        },
    }


