"""Reference data routes: securities, sectors, brokers, funds, dividends."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.auth.deps import AdminUser, DbSession
from app.core.provenance import NOT_PUBLISHED_BY_NEPSE, ValueStatus
from app.db.models import DailyBar, FundNavPoint, Security
from app.nepse.registry import get_adapter
from app.nepse.service import validate_symbol
from app.reference.service import ReferenceNotFoundError, ReferenceService
from app.db.base import utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reference", tags=["reference"])

_reference = ReferenceService(get_adapter())


@router.get("/securities", summary="Security master")
def securities(
    session: DbSession,
    search: Optional[str] = Query(None, description="Symbol or name substring"),
    active_only: bool = Query(True),
) -> dict[str, Any]:
    rows = _reference.list_securities(session, active_only=active_only, search=search)
    return {
        "count": len(rows),
        "securities": [
            {
                "symbol": s.symbol,
                "name": s.name,
                "sector": s.sector_code,
                "type": s.security_type,
                "listed_shares": s.listed_shares,
                "isin": s.isin,
                "tick_size": s.tick_size,
                "face_value": s.face_value,
                "listing_date": s.listing_date,
                "credit_rating": s.credit_rating,
                "is_active": s.is_active,
            }
            for s in rows
        ],
    }


@router.get("/security/{symbol}", summary="One security, with its sector")
def security(symbol: str, session: DbSession) -> dict[str, Any]:
    sym = validate_symbol(symbol)
    row = session.get(Security, sym)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"{sym} is not in the security master yet. Run POST /api/reference/sync.",
        )
    return {
        "symbol": row.symbol,
        "name": row.name,
        "sector": row.sector_code,
        "type": row.security_type,
        "nepse_security_id": row.nepse_security_id,
        "listed_shares": row.listed_shares,
        "isin": row.isin,
        "tick_size": row.tick_size,
        "face_value": row.face_value,
        "listing_date": row.listing_date,
        "credit_rating": row.credit_rating,
        "is_active": row.is_active,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/sectors", summary="Sectors")
def sectors(session: DbSession) -> dict[str, Any]:
    rows = _reference.list_sectors(session)
    return {
        "count": len(rows),
        "sectors": [{"code": s.code, "name": s.name, "index": s.index_symbol} for s in rows],
    }


@router.get("/brokers", summary="Official broker/member directory")
def brokers(
    session: DbSession,
    province: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = False,
) -> dict[str, Any]:
    """The NEPSE member registry (VERIFIED 92 members).

    This is genuine official reference data: names, dealer flags, contact
    details and provinces. It is *not* trade attribution - see the
    `attribution` note in the response, and docs/data-sources.md.
    """
    rows = _reference.list_brokers(
        session, active_only=active_only, province=province, search=search
    )
    return {
        "count": len(rows),
        "brokers": [
            {
                "member_code": b.member_code,
                "member_name": b.member_name,
                "is_dealer": b.is_dealer,
                "is_active": b.is_active,
                "province": b.province,
                "district": b.district,
                "phone": b.phone,
                "email": b.email,
                "website": b.website,
            }
            for b in rows
        ],
        "provinces": _reference.broker_provinces(session),
        "attribution": {
            "available": False,
            "reason": NOT_PUBLISHED_BY_NEPSE["broker_attribution"],
        },
    }


@router.get("/funds", summary="Mutual funds, with NAV status")
def funds(
    session: DbSession,
    tab: Optional[str] = Query(None, description="Filter: close_ended, open_ended, matured"),
) -> dict[str, Any]:
    """Mutual fund schemes with tabs for Close-Ended / Open-Ended / Matured.

    NEPSE does not publish NAV, so each fund reports `not_published` with the
    reason rather than a bare dash. Premium/discount stays inactive until a NAV
    is supplied by CSV import or manual entry.

    Close-ended vs open-ended is derived from scheme_description:
    - close_ended: scheme_description contains "close" and ("end" or "maturity")
    - matured: close_ended=True and maturity_date is in the past
    """
    rows = _reference.list_funds(session)
    fund_codes = {f.code for f in rows}
    
    # Find unsynced CDS securities
    from app.db.models import Security
    cds_secs = list(session.scalars(select(Security).where(Security.security_type == "CDS")))
    unsynced = []
    for s in cds_secs:
        if s.symbol not in fund_codes:
            reason = "Not synced — run POST /api/reference/sync to create fund row"
            unsynced.append({
                "symbol": s.symbol,
                "name": s.name,
                "reason": reason,
                "nepse_security_id": s.nepse_security_id,
                "listed_shares": s.listed_shares,
                "promoter_pct": s.promoter_pct,
                "public_pct": s.public_pct,
            })
    
    today = datetime.now().date().isoformat()
    filtered = []
    for f in rows:
        # Apply tab filter
        if tab == "close_ended" and not f.close_ended:
            continue
        if tab == "open_ended" and f.close_ended:
            continue
        if tab == "matured" and (not f.close_ended or not f.maturity_date or f.maturity_date >= today):
            continue
        # Compute premium/discount if NAV and LTP exist
        premium_discount = None
        premium_discount_status = "requires_nav"
        premium_discount_reason = "NAV not available"
        if f.nav is not None:
            # Would need LTP from archive - not available in this endpoint
            premium_discount_status = "requires_ltp"
            premium_discount_reason = "NAV available but LTP not in this endpoint"
        filtered.append(
            {
                "code": f.code,
                "name": f.name,
                "manager": f.manager,
                "category": f.category,
                "scheme_description": f.scheme_description,
                "scheme_name": f.scheme_name,
                "close_ended": f.close_ended,
                "maturity_date": f.maturity_date,
                "face_value": f.face_value,
                "units": f.units,
                "fund_size": f.fund_size,
                "listing_date": f.listing_date,
                "isin": f.isin,
                "nav": _reference.fund_nav_measured(f).model_dump(),
                "premium_discount": premium_discount,
                "premium_discount_status": premium_discount_status,
                "premium_discount_reason": premium_discount_reason,
                "dividend_count": len(_reference.corporate_actions(session, f.code)),
            }
        )
    return {
        "count": len(filtered),
        "total": len(rows),
        "tab": tab,
        "funds": filtered,
        "nav_note": NOT_PUBLISHED_BY_NEPSE["fund_nav"],
        "unsynced": unsynced,
        "unsynced_count": len(unsynced),
    }


@router.get("/dividends/{symbol}", summary="Dividends and bonus shares")
def dividends(symbol: str, session: DbSession) -> dict[str, Any]:
    sym = validate_symbol(symbol)
    rows = _reference.corporate_actions(session, sym)
    return {
        "symbol": sym,
        "count": len(rows),
        "actions": [
            {
                "fiscal_year": a.fiscal_year,
                "cash_dividend_pct": _reference.dividend_measured(a, "cash").model_dump(),
                "bonus_pct": _reference.dividend_measured(a, "bonus").model_dump(),
                "book_close": a.book_close,
                "agm_date": a.agm_date,
                "source": a.source,
            }
            for a in rows
        ],
        "note": (
            "A zero here is a declared zero (the year had no dividend), which "
            "is different from the source not reporting the field."
        ),
    }


@router.get("/dividends/analysis", summary="Dividend analysis across all symbols")
def dividend_analysis(
    session: DbSession,
    fiscal_year: Optional[str] = Query(None, description="Filter by fiscal year"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    min_consecutive: Optional[int] = Query(None, description="Minimum consecutive years paid"),
) -> dict[str, Any]:
    """Comprehensive dividend analysis across all symbols.

    Returns dividend data with computed fields:
    - total_pct = cash_pct + bonus_pct
    - dividend_per_unit = cash_pct% * face_value
    - yield_on_ltp = dividend_per_unit / LTP * 100
    - consecutive_years_paid: streak of years with any dividend
    - distribution_date: parsed from announcements if available
    """
    from app.db.models import Security
    from app.analytics.screening import build_series, compute_metrics

    # Get symbols to analyze
    if symbol:
        sym = validate_symbol(symbol)
        symbols = [sym]
    else:
        rows = _reference.list_securities(session, active_only=True)
        symbols = [r.symbol for r in rows]

    results = []
    for sym in symbols:
        security = session.get(Security, sym)
        if not security:
            continue

        div_rows = _reference.corporate_actions(session, sym)
        if not div_rows:
            continue

        # Get LTP for yield calculation
        ltp = None
        bars = session.scalars(
            select(DailyBar).where(DailyBar.symbol == sym).order_by(DailyBar.business_date.desc())
        ).first()
        if bars:
            ltp = bars.close

        # Get face value
        face_value = security.face_value

        # Build dividend history for this symbol
        div_history = []
        consecutive_years = 0
        max_consecutive = 0
        current_streak = 0

        # Sort by fiscal year descending
        sorted_divs = sorted(div_rows, key=lambda x: x.fiscal_year or "", reverse=True)

        for i, a in enumerate(sorted_divs):
            cash_pct = float(a.cash_dividend_pct) if a.cash_dividend_pct is not None else 0.0
            bonus_pct = float(a.bonus_pct) if a.bonus_pct is not None else 0.0
            total_pct = cash_pct + bonus_pct

            has_dividend = cash_pct > 0 or bonus_pct > 0

            # Track consecutive years
            if has_dividend:
                current_streak += 1
                max_consecutive = max(max_consecutive, current_streak)
            else:
                current_streak = 0

            dividend_per_unit = None
            yield_on_ltp = None
            if cash_pct > 0 and face_value:
                dividend_per_unit = (cash_pct / 100.0) * face_value
                if ltp and ltp > 0:
                    yield_on_ltp = (dividend_per_unit / ltp) * 100.0

            # Parse distribution date from announcements if available
            distribution_date = None
            distribution_reason = "Not announced"
            if a.agm_date:
                distribution_date = a.agm_date
                distribution_reason = "AGM date"
            elif a.book_close:
                distribution_date = a.book_close
                distribution_reason = "Book close date"

            div_history.append({
                "fiscal_year": a.fiscal_year,
                "cash_pct": cash_pct,
                "bonus_pct": bonus_pct,
                "total_pct": total_pct,
                "book_close": a.book_close,
                "agm_date": a.agm_date,
                "distribution_date": distribution_date,
                "distribution_reason": distribution_reason,
                "dividend_per_unit": dividend_per_unit,
                "yield_on_ltp": yield_on_ltp,
                "has_dividend": has_dividend,
                "source": a.source,
            })

        if not div_history:
            continue

        # Apply fiscal year filter
        if fiscal_year:
            div_history = [d for d in div_history if d["fiscal_year"] == fiscal_year]
            if not div_history:
                continue

        # Apply min_consecutive filter
        if min_consecutive and max_consecutive < min_consecutive:
            continue

        results.append({
            "symbol": sym,
            "name": security.name,
            "sector": security.sector_code,
            "face_value": face_value,
            "ltp": ltp,
            "dividend_history": div_history,
            "consecutive_years_paid": max_consecutive,
            "latest_dividend": div_history[0] if div_history else None,
            "total_dividend_years": len([d for d in div_history if d["has_dividend"]]),
        })

    # Sort by yield_on_ltp descending for ranking
    results_with_yield = [r for r in results if r["latest_dividend"] and r["latest_dividend"]["yield_on_ltp"]]
    results_with_yield.sort(key=lambda x: x["latest_dividend"]["yield_on_ltp"] or 0, reverse=True)

    # Build ranking cards
    ranking = {
        "highest_yield": results_with_yield[:5] if results_with_yield else [],
        "most_consistent": sorted(results, key=lambda x: x["consecutive_years_paid"], reverse=True)[:5],
        "recent_payers": sorted(
            [r for r in results if r["latest_dividend"] and r["latest_dividend"]["has_dividend"]],
            key=lambda x: x["latest_dividend"]["fiscal_year"] or "",
            reverse=True
        )[:5],
    }

    return {
        "count": len(results),
        "symbols": results,
        "ranking": ranking,
        "filters": {"fiscal_year": fiscal_year, "symbol": symbol, "min_consecutive": min_consecutive},
    }


@router.get("/holidays/{year}", summary="NEPSE holiday list")
async def holidays(year: int, session: DbSession) -> dict[str, Any]:
    dates = await _reference.sync_holidays(session, year)
    return {"year": year, "count": len(dates), "dates": sorted(dates)}


@router.post("/enrich/{symbol}", summary="Fetch full metadata for one symbol")
async def enrich(symbol: str, session: DbSession) -> dict[str, Any]:
    """Pull sector, instrument type, ISIN, tick size and listed shares.

    These are only available per symbol from `nots/security/{id}`, so this is
    an on-demand call rather than part of the bulk sync (enriching all 568
    securities would mean 568 upstream requests).

    `stockListedShares` matters most: the archive derives market cap from it,
    because NEPSE's live `marketCapitalization` is null and its historical one
    is denominated in millions of NPR.
    """
    try:
        return await _reference.enrich_security(session, symbol)
    except ReferenceNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No NEPSE security id is known for {symbol.upper()}.",
        ) from exc


@router.post("/sync", summary="Refresh all reference data")
async def sync(session: DbSession, admin: AdminUser) -> dict[str, Any]:
    """Re-pull securities, sectors and brokers from NEPSE.

    Three bulk calls total. Per-symbol detail (sector, listed shares) is not
    included; use `POST /api/reference/enrich/{symbol}` for that.
    """
    securities_count = await _reference.sync_securities(session)
    sectors_count = await _reference.sync_sectors(session)
    brokers_count = await _reference.sync_brokers(session)
    funds_count = _reference.sync_funds_from_securities(session)
    return {
        "securities": securities_count,
        "sectors": sectors_count,
        "brokers": brokers_count,
        "funds": funds_count,
        "hint": (
            "Per-symbol metadata (sector, listed shares) needs one call each: "
            "POST /api/reference/enrich/{symbol}"
        ),
    }


@router.post("/enrich-all", summary="Enrich all symbols missing listed shares (paced, resumable)")
async def enrich_all(
    session: DbSession,
    admin: AdminUser,
    limit: Optional[int] = Query(None, description="Max symbols to attempt"),
    resume: bool = Query(True, description="Skip symbols that already have listed shares"),
) -> dict[str, Any]:
    """Bulk-fetch `stockListedShares` (and promoter/public split) for all symbols.

    Market cap is `listed shares x LTP`, and NEPSE exposes listed shares only
    on the per-security detail endpoint. At the adapter's pacing (~120ms/call)
    the full 568-symbol master takes ~1 minute of upstream traffic.

    `resume=True` (default) skips symbols that already have listed shares, so
    an interrupted run can be re-invoked. Failures are counted and the loop
    continues: one dead symbol must not abandon the other 480.

    Returns a summary including symbols that could not be enriched.
    """
    return await _reference.enrich_missing_listed_shares(session, limit=limit, resume=resume)


@router.get("/funds/{symbol}", summary="Full fund detail")
def fund_detail(symbol: str, session: DbSession) -> dict[str, Any]:
    """Full fund detail including metadata, NAV, and dividend history."""
    sym = validate_symbol(symbol)
    fund = session.get(Fund, sym)
    if fund is None:
        raise HTTPException(
            status_code=404,
            detail=f"Fund {sym} not found. Run POST /api/reference/sync first.",
        )
    # Get dividends
    div_rows = _reference.corporate_actions(session, sym)
    div_actions = [
        {
            "fiscal_year": a.fiscal_year,
            "cash_dividend_pct": _reference.dividend_measured(a, "cash").model_dump(),
            "bonus_pct": _reference.dividend_measured(a, "bonus").model_dump(),
            "book_close": a.book_close,
            "agm_date": a.agm_date,
            "source": a.source,
        }
        for a in div_rows
    ]
    # Get NAV history
    nav_points = session.scalars(
        select(FundNavPoint).where(FundNavPoint.fund_code == sym).order_by(FundNavPoint.nav_date)
    ).all()
    nav_history = [
        {"nav_date": p.nav_date, "nav": p.nav, "source": p.source}
        for p in nav_points
    ]
    # Compute premium/discount if NAV and LTP exist
    premium_discount = None
    premium_discount_status = "requires_nav"
    premium_discount_reason = "NAV not available"
    if fund.nav is not None:
        # We'd need LTP from the archive - for now show as unavailable
        premium_discount_status = "requires_ltp"
        premium_discount_reason = "NAV available but LTP not in this endpoint"
    return {
        "code": fund.code,
        "name": fund.name,
        "manager": fund.manager,
        "category": fund.category,
        "scheme_description": fund.scheme_description,
        "scheme_name": fund.scheme_name,
        "close_ended": fund.close_ended,
        "maturity_date": fund.maturity_date,
        "face_value": fund.face_value,
        "units": fund.units,
        "fund_size": fund.fund_size,
        "listing_date": fund.listing_date,
        "isin": fund.isin,
        "nav": _reference.fund_nav_measured(fund).model_dump(),
        "premium_discount": premium_discount,
        "premium_discount_status": premium_discount_status,
        "premium_discount_reason": premium_discount_reason,
        "dividends": {
            "count": len(div_actions),
            "actions": div_actions,
        },
        "nav_history": nav_history,
        "updated_at": fund.updated_at.isoformat() if fund.updated_at else None,
    }


@router.post("/funds/{symbol}/nav", summary="Import NAV for a fund (admin)")
async def import_nav(
    symbol: str,
    payload: dict,
    session: DbSession,
    admin: AdminUser,
) -> dict[str, Any]:
    """Import a NAV point for a fund. Admin only.

    Payload: {"nav": 10.5, "nav_date": "2026-09-28", "source": "manual"}
    """
    sym = validate_symbol(symbol)
    fund = session.get(Fund, sym)
    if fund is None:
        raise HTTPException(status_code=404, detail=f"Fund {sym} not found")
    nav = payload.get("nav")
    nav_date = payload.get("nav_date")
    source = payload.get("source", "manual")
    if nav is None or nav_date is None:
        raise HTTPException(status_code=400, detail="nav and nav_date are required")
    try:
        nav_val = float(nav)
        if nav_val <= 0:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="nav must be a positive number")
    # Validate date format YYYY-MM-DD
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", nav_date):
        raise HTTPException(status_code=400, detail="nav_date must be YYYY-MM-DD")
    # Upsert NAV point
    existing = session.scalar(
        select(FundNavPoint).where(
            FundNavPoint.fund_code == sym, FundNavPoint.nav_date == nav_date
        )
    )
    if existing is None:
        existing = FundNavPoint(fund_code=sym, nav_date=nav_date, nav=nav_val, source=source)
        session.add(existing)
    else:
        existing.nav = nav_val
        existing.source = source
    # Update fund's current NAV
    fund.nav = nav_val
    fund.nav_date = nav_date
    fund.nav_status = ValueStatus.OK
    fund.nav_source = source
    fund.updated_at = utcnow()
    session.commit()
    return {"code": sym, "nav": nav_val, "nav_date": nav_date, "source": source}


@router.get("/funds/{symbol}/nav-history", summary="NAV history for a fund")
def nav_history(symbol: str, session: DbSession) -> dict[str, Any]:
    """Return all NAV points for a fund, ordered by date."""
    sym = validate_symbol(symbol)
    fund = session.get(Fund, sym)
    if fund is None:
        raise HTTPException(status_code=404, detail=f"Fund {sym} not found")
    nav_points = session.scalars(
        select(FundNavPoint).where(FundNavPoint.fund_code == sym).order_by(FundNavPoint.nav_date)
    ).all()
    return {
        "code": sym,
        "name": fund.name,
        "count": len(nav_points),
        "points": [
            {"nav_date": p.nav_date, "nav": p.nav, "source": p.source, "created_at": p.created_at.isoformat() if p.created_at else None}
            for p in nav_points
        ],
    }


@router.get("/corporate-actions", summary="Market-wide corporate actions feed")
def corporate_actions_feed(
    session: DbSession,
    sector: Optional[str] = Query(None, description="Filter by sector"),
    action_type: Optional[str] = Query(None, description="Filter: dividend, bonus, right, book_close, agm, ipo, fpo"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    upcoming_only: bool = Query(False, description="Show only upcoming book closures and AGMs"),
) -> dict[str, Any]:
    """Market-wide corporate actions feed from stored announcements and corporate actions.

    Combines data from:
    - Corporate actions endpoint (dividends, bonus, right issues)
    - Company announcements (book closures, AGMs, IPO/right/FPO notices)
    - Market-wide news feed

    All dates are verbatim as published by NEPSE (DD/MM/YYYY).
    """
    from app.db.models import Announcement

    results = []

    # 1. Corporate actions from all symbols
    securities = _reference.list_securities(session, active_only=True)
    for sec in securities:
        ca_rows = _reference.corporate_actions(session, sec.symbol)
        for ca in ca_rows:
            action_types = []
            if ca.cash_dividend_pct is not None and ca.cash_dividend_pct > 0:
                action_types.append("dividend")
            if ca.bonus_pct is not None and ca.bonus_pct > 0:
                action_types.append("bonus")
            if ca.right_pct is not None and ca.right_pct > 0:
                action_types.append("right")

            if action_type and action_type not in action_types:
                continue

            if sector and sec.sector_code != sector:
                continue

            # Build base entry
            base_entry = {
                "symbol": sec.symbol,
                "name": sec.name,
                "sector": sec.sector_code,
                "fiscal_year": ca.fiscal_year,
                "cash_dividend_pct": ca.cash_dividend_pct,
                "bonus_pct": ca.bonus_pct,
                "right_pct": ca.right_pct,
                "book_close": ca.book_close,
                "agm_date": ca.agm_date,
                "source": ca.source,
                "action_types": action_types,
            }

            # Apply date filters
            if date_from or date_to:
                action_date = ca.book_close or ca.agm_date
                if action_date:
                    if date_from and action_date < date_from:
                        continue
                    if date_to and action_date > date_to:
                        continue
                else:
                    # No date available, skip if date filter is active
                    if date_from or date_to:
                        continue

            # Check upcoming filter
            if upcoming_only:
                today = datetime.now().date().isoformat()
                action_date = ca.book_close or ca.agm_date
                if not action_date or action_date <= today:
                    continue

            results.append(base_entry)

    # 2. Announcements from all symbols (for IPO, right, FPO, book_close, AGM details)
    # This requires querying announcements table directly
    ann_query = select(Announcement).order_by(Announcement.published_at.desc())
    if sector:
        # Need to join with Security to filter by sector
        ann_query = ann_query.join(Security, Announcement.symbol == Security.symbol).where(Security.sector_code == sector)

    announcements = session.scalars(ann_query.limit(5000)).all()

    for ann in announcements:
        # Parse action type from news_type
        action_types = []
        news_type = (ann.news_type or "").lower()
        if "dividend" in news_type:
            action_types.append("dividend")
        if "bonus" in news_type:
            action_types.append("bonus")
        if "right" in news_type or "right share" in news_type:
            action_types.append("right")
        if "ipo" in news_type:
            action_types.append("ipo")
        if "fpo" in news_type:
            action_types.append("fpo")
        if "book close" in news_type or "book closure" in news_type:
            action_types.append("book_close")
        if "agm" in news_type or "annual general meeting" in news_type:
            action_types.append("agm")

        if action_type and action_type not in action_types:
            continue

        if sector:
            sec = session.get(Security, ann.symbol)
            if not sec or sec.sector_code != sector:
                continue

        # Parse dates from announcement body
        parsed = ann.parsed or {}
        book_close = parsed.get("book_close")
        agm_date = parsed.get("agm_date")

        action_date = book_close or agm_date or (ann.published_at.date().isoformat() if ann.published_at else None)

        if date_from and action_date and action_date < date_from:
            continue
        if date_to and action_date and action_date > date_to:
            continue

        if upcoming_only:
            today = datetime.now().date().isoformat()
            if not action_date or action_date <= today:
                continue

        results.append({
            "symbol": ann.symbol,
            "name": None,  # Would need to join Security
            "sector": None,
            "fiscal_year": parsed.get("fiscal_year"),
            "cash_dividend_pct": None,
            "bonus_pct": None,
            "right_pct": None,
            "book_close": book_close,
            "agm_date": agm_date,
            "source": ann.news_source or "nepse:announcement",
            "action_types": action_types,
            "headline": ann.headline,
            "body_preview": ann.body[:200] if ann.body else None,
            "published_at": ann.published_at.isoformat() if ann.published_at else None,
        })

    # Sort by action date descending
    results.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    # Get unique sectors for filter dropdown
    sectors = session.scalars(select(Security.sector_code).distinct().where(Security.sector_code.is_not(None)).where(Security.is_active == True)).all()

    # Get unique action types
    action_type_options = ["dividend", "bonus", "right", "book_close", "agm", "ipo", "fpo"]

    return {
        "count": len(results),
        "results": results,
        "sectors": sectors,
        "action_types": action_type_options,
        "filters": {
            "sector": sector,
            "action_type": action_type,
            "date_from": date_from,
            "date_to": date_to,
            "upcoming_only": upcoming_only,
        },
    }


@router.get("/corporate-actions/upcoming", summary="Upcoming book closures and AGMs")
def upcoming_corporate_actions(
    session: DbSession,
    days: int = Query(30, description="Days ahead to look"),
) -> dict[str, Any]:
    """List upcoming book closures and AGMs within the specified days."""
    from app.db.models import Announcement
    from app.db.models import CorporateAction

    today = datetime.now().date()
    end_date = today + timedelta(days=days)
    today_iso = today.isoformat()
    end_iso = end_date.isoformat()

    upcoming = []

    # From corporate actions
    securities = _reference.list_securities(session, active_only=True)
    for sec in securities:
        ca_rows = _reference.corporate_actions(session, sec.symbol)
        for ca in ca_rows:
            for date_field, event_type in [(ca.book_close, "book_close"), (ca.agm_date, "agm")]:
                if not date_field:
                    continue
                if today_iso <= date_field <= end_iso:
                    upcoming.append({
                        "symbol": sec.symbol,
                        "name": sec.name,
                        "sector": sec.sector_code,
                        "event_type": event_type,
                        "date": date_field,
                        "fiscal_year": ca.fiscal_year,
                        "source": ca.source,
                    })

    # From announcements
    ann_query = select(Announcement).order_by(Announcement.published_at.desc())
    announcements = session.scalars(ann_query.limit(5000)).all()

    for ann in announcements:
        parsed = ann.parsed or {}
        for date_field, event_type in [(parsed.get("book_close"), "book_close"), (parsed.get("agm_date"), "agm")]:
            if not date_field:
                continue
            if today_iso <= date_field <= end_iso:
                sec = session.get(Security, ann.symbol)
                upcoming.append({
                    "symbol": ann.symbol,
                    "name": sec.name if sec else None,
                    "sector": sec.sector_code if sec else None,
                    "event_type": event_type,
                    "date": date_field,
                    "fiscal_year": parsed.get("fiscal_year"),
                    "headline": ann.headline,
                    "source": ann.news_source or "nepse:announcement",
                })

    # Sort by date
    upcoming.sort(key=lambda x: x["date"])

    return {
        "count": len(upcoming),
        "period": f"{today_iso} to {end_iso}",
        "upcoming": upcoming,
    }
