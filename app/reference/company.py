"""Company profile pages.

Assembles one security's everything into a single response so the company page
needs one request instead of five, and so every unavailable section carries its
reason in the same place as the data that *is* available.

The hard rule here: a section NEPSE does not publish is returned as an explicit
`{"available": false, "reason": ...}` block, never as a field that is null with
no explanation and never as a zero. A promoter split of "0%" and a missing
promoter split look identical on a page and mean completely different things.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.analytics.screening import build_series, compute_metrics
from app.archive.service import ArchiveService
from app.auth.deps import DbSession
from app.core.provenance import NOT_PUBLISHED_BY_NEPSE
from app.db.models import DailyBar, Security
from app.nepse.exceptions import NepseInvalidResponseError, NepseServiceError
from app.nepse.registry import get_adapter
from app.nepse.service import validate_symbol
from app.reference.service import ReferenceService

router = APIRouter(prefix="/api/reference", tags=["companies"])

_reference = ReferenceService(get_adapter())
_archive = ArchiveService(get_adapter())

logger = logging.getLogger(__name__)


def _unavailable(key: str) -> dict[str, Any]:
    return {"available": False, "status": "not_published", "reason": NOT_PUBLISHED_BY_NEPSE[key]}


@router.get("/companies/{symbol}", summary="Full company profile in one response")
async def company(symbol: str, session: DbSession) -> dict[str, Any]:
    """Profile, dividends, valuation and the sections NEPSE does not publish.

    Valuation is restricted to what the market feed can actually support.
    Market cap (listed shares x LTP) and a dividend yield derived from declared
    cash dividends are computable. P/E, P/B, ROE and EPS are **not**, because
    NEPSE publishes neither earnings nor book value in its market feed, so they
    are reported as unavailable rather than estimated.
    """
    sym = validate_symbol(symbol)
    security = session.get(Security, sym)
    if security is None:
        raise HTTPException(404, f"Unknown symbol {sym}. Try /api/reference/securities?search={sym}")

    # -- price and market cap, from the archive -----------------------------
    rows = session.scalars(
        select(DailyBar).where(DailyBar.symbol == sym).order_by(DailyBar.business_date)
    ).all()
    series = build_series(rows, {sym: security}).get(sym)
    metrics = compute_metrics(series) if series is not None else None

    actions = _reference.corporate_actions(session, sym)

    # -- lazy enrichment: one paced upstream call each, persisted for next time
    # The promoter/public split and the announcement list are per-symbol
    # endpoints, so a symbol nobody has enriched yet triggers the enrich here
    # (the same paced path POST /api/reference/enrich uses). Failures leave the
    # sections to their explicit unavailable reasons rather than 500-ing.
    if security.listed_shares is None or security.promoter_shares is None:
        try:
            await _reference.enrich_security(session, sym)
            security = session.get(Security, sym)
        except Exception as exc:  # noqa: BLE001 - degrade to reasons, not 500
            logger.info("lazy enrich failed for %s: %s", sym, exc)
    announcements = _reference.announcements(session, sym)
    if not announcements:
        try:
            await _reference.sync_announcements(session, sym)
            announcements = _reference.announcements(session, sym)
        except Exception as exc:  # noqa: BLE001
            logger.info("announcement sync failed for %s: %s", sym, exc)

    # -- profile -----------------------------------------------------------
    profile: dict[str, Any] = {
        "symbol": sym,
        "name": security.name,
        "sector": security.sector_code,
        "isin": security.isin,
        "security_type": security.security_type,
        "board": security.board,
        "tick_size": security.tick_size,
        "face_value": security.face_value,
        "listing_date": security.listing_date,
        "credit_rating": security.credit_rating,
        "is_active": security.is_active,
    }
    # Fields that only exist after a per-security enrich, so the page can offer
    # to fetch them rather than showing an unexplained blank.
    for field_name in ("sector", "isin", "security_type", "tick_size", "face_value",
                       "listing_date", "credit_rating", "listed_shares"):
        if getattr(security, field_name, None) is None:
            profile.setdefault("needs_enrichment", []).append(field_name)

    # -- valuation: only what the feed supports ----------------------------
    valuation: dict[str, Any] = {}
    if metrics is not None and metrics.ltp is not None:
        valuation["ltp"] = {"value": metrics.ltp, "as_of": metrics.as_of}
        if metrics.market_cap is not None:
            valuation["market_cap"] = {
                "value": metrics.market_cap,
                "formula": "listed shares x LTP",
                "as_of": metrics.as_of,
            }
        else:
            valuation["market_cap"] = {
                "value": None,
                "reason": metrics.missing.get("market_cap", "Listed shares unknown."),
            }
    else:
        valuation["ltp"] = {"value": None, "reason": "No archived price for this symbol."}

    # Dividend yield: NEPSE declares cash dividend as a percentage of paid-up
    # (par) capital, so a per-share figure needs the face value. Without a face
    # value this is not computable and stays None.
    declared = [a for a in actions if a.cash_dividend_pct is not None]

    # Fallback: parse cash dividend from announcement text. NEPSE's
    # corporate-actions rows are BONUS-ONLY (verified 2026-09-28); cash
    # dividend, book close date, and AGM date exist only as labelled lines
    # inside announcement text (newsBody).
    if not declared:
        for ann in announcements:
            if ann.parsed and ann.parsed.get("cash_dividend"):
                # Parse the percentage value (e.g. "10.8%")
                txt = ann.parsed["cash_dividend"].strip()
                if txt.endswith("%"):
                    txt = txt[:-1]
                try:
                    pct = float(txt)
                    # Create a synthetic action-like object for the fallback
                    class _ParsedDividend:
                        cash_dividend_pct = pct
                        fiscal_year = ann.parsed.get("fiscal_year") or "parsed"
                    declared.append(_ParsedDividend())
                    break  # use the most recent announcement with cash dividend
                except ValueError:
                    pass

    if declared and security.face_value and metrics and metrics.ltp:
        latest = max(declared, key=lambda a: a.fiscal_year or "")
        dps = (float(latest.cash_dividend_pct) / 100.0) * float(security.face_value)
        basis = "declared cash dividend per share (pct of par) / LTP"
        if hasattr(latest, 'fiscal_year') and latest.fiscal_year == "parsed":
            basis = "parsed from announcement text"
        valuation["dividend_yield_pct"] = {
            "value": dps / float(metrics.ltp) * 100.0,
            "fiscal_year": latest.fiscal_year,
            "cash_dividend_pct": latest.cash_dividend_pct,
            "face_value": security.face_value,
            "basis": basis,
        }
    else:
        valuation["dividend_yield_pct"] = {
            "value": None,
            "reason": (
                "Needs both a declared cash dividend (from corporate-actions or "
                "parsed from announcement text) and a known face value to "
                "convert a par percentage into a per-share yield."
            ),
        }

    # Every standard ratio is explicitly unavailable, with the reason. NEPSE
    # publishes no earnings and no book value, so none of these can be computed
    # without inventing the denominator.
    ratio_reasons = {
        "pe": NOT_PUBLISHED_BY_NEPSE["eps"],
        "pb": NOT_PUBLISHED_BY_NEPSE["book_value_per_share"],
        "eps": NOT_PUBLISHED_BY_NEPSE["eps"],
        "roe": NOT_PUBLISHED_BY_NEPSE["quarterly_statements"],
        "book_value_per_share": NOT_PUBLISHED_BY_NEPSE["book_value_per_share"],
    }
    valuation["ratios"] = {
        key: {"available": False, "reason": reason} for key, reason in ratio_reasons.items()
    }

    # -- the sections NEPSE does not publish --------------------------------
    return {
        "symbol": sym,
        "profile": profile,
        "price": {
            "as_of": metrics.as_of if metrics else None,
            "sessions": metrics.sessions if metrics else 0,
            "change": metrics.change if metrics else None,
            "change_pct": metrics.change_pct if metrics else None,
            "day_high": metrics.day_high if metrics else None,
            "day_low": metrics.day_low if metrics else None,
            "high_52w": metrics.high_52w if metrics else None,
            "low_52w": metrics.low_52w if metrics else None,
            "volume": metrics.volume if metrics else None,
            "turnover": metrics.turnover if metrics else None,
            "reasons": metrics.missing if metrics else {"all": "No archived bars."},
        },
        "valuation": valuation,
        "dividends": {
            "count": len(actions),
            "actions": [
                {
                    "fiscal_year": a.fiscal_year,
                    "cash_dividend_pct": _reference.dividend_measured(a, "cash").model_dump(),
                    "bonus_pct": _reference.dividend_measured(a, "bonus").model_dump(),
                    "book_close": a.book_close,
                    "agm_date": a.agm_date,
                    "source": a.source,
                }
                for a in actions
            ],
            "coverage_note": NOT_PUBLISHED_BY_NEPSE["corporate_actions_complete"],
        },
        "promoter_public_split": _split_section(security),
        "news": _news_section(announcements, sym),
        "book_closure": _notice_fact(announcements, "book_close",
            "Book-closure dates are published inside announcement text "
            "('Book Close Date: ...'); none of the stored announcements for "
            "this symbol carries one."),
        "agm": _notice_fact(announcements, "agm_date",
            "AGM dates are published inside announcement text "
            "('AGM Date: ...'); none of the stored announcements for this "
            "symbol carries one."),
        "market_depth": await _depth_section(security, sym),
        "notes": [
            "Every unavailable section states why, so a blank is never a bare "
            "'N/A' and never a zero.",
            "Bonus shares (BS) come from NEPSE's corporate-actions rows; cash "
            "dividends (AD), book closure and AGM dates arrive as announcement "
            "text and are also stored parsed, verbatim, under 'parsed'.",
        ],
    }


def _split_section(security: Security) -> dict[str, Any]:
    """Promoter/public shareholding, from nots/security/{id} via the enrich."""
    if (
        security.promoter_shares is not None
        or security.public_shares is not None
        or security.promoter_pct is not None
    ):
        return {
            "available": True,
            "promoter_shares": security.promoter_shares,
            "public_shares": security.public_shares,
            "promoter_pct": security.promoter_pct,
            "public_pct": security.public_pct,
            "source": "nepse:nots/security/{id}",
            "as_of": security.updated_at.isoformat() if security.updated_at else None,
        }
    return {
        "available": False,
        "status": "pending",
        "reason": NOT_PUBLISHED_BY_NEPSE["promoter_public_split"],
    }


def _news_section(announcements: list[Any], sym: str) -> dict[str, Any]:
    """Stored company announcements, newest first. An empty list after a
    successful sync is a real empty - the feed exists, NEPSE has simply
    published nothing for this symbol."""
    if announcements:
        return {
            "available": True,
            "count": len(announcements),
            "source": "nepse:application/company-news/{id}",
            "items": [
                {
                    "id": a.nepse_news_id,
                    "headline": a.headline,
                    "type": a.news_type,
                    "source": a.news_source,
                    "published_at": a.published_at.isoformat() if a.published_at else None,
                    "parsed": a.parsed,
                    "body": a.body,
                }
                for a in announcements
            ],
        }
    return {
        "available": False,
        "status": "not_reported",
        "reason": (
            f"NEPSE's company-news feed is reachable, but has published no "
            f"announcements for {sym}. An empty feed is not an unavailable feed."
        ),
    }


def _notice_fact(announcements: list[Any], key: str, absence_reason: str) -> dict[str, Any]:
    """A fact (book closure, AGM date) that lives inside announcement text.

    Returns the most recent announcement whose parsed text carries the label,
    with the announcement it came from, so the value is always traceable.
    """
    for a in announcements:
        if a.parsed and a.parsed.get(key):
            return {
                "available": True,
                "value": a.parsed[key],
                "verbatim": True,
                "from_headline": a.headline,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "note": "Stored exactly as printed in the announcement text.",
            }
    return {"available": False, "status": "not_reported", "reason": absence_reason}


async def _depth_section(security: Security, sym: str) -> dict[str, Any]:
    """Live order book, attempted live so an open market gets real rows.

    Verified 2026-09-28: `nots/nepse-data/marketdepth/{id}` answers HTTP 200
    with an EMPTY body outside the session. The adapter now returns None for
    this case, which we treat as 'no live order book right now' with the check
    time - never as a zero-depth book.
    """
    from datetime import datetime, timezone
    if security.nepse_security_id is None:
        return {
            "available": False,
            "status": "pending",
            "reason": "NEPSE's numeric security id for this symbol is unknown; "
            "the depth endpoint is keyed by id.",
        }
    adapter = get_adapter()
    try:
        payload = await adapter.call(
            f"market_depth:{sym}",
            lambda: adapter.get_market_depth(security.nepse_security_id),
        )
    except NepseInvalidResponseError:
        return {
            "available": False,
            "status": "upstream_unavailable",
            "reason": NOT_PUBLISHED_BY_NEPSE["market_depth"],
        }
    except NepseServiceError as exc:
        return {
            "available": False,
            "status": "upstream_unavailable",
            "reason": f"NEPSE depth endpoint failed: {exc.detail if hasattr(exc, 'detail') else exc}",
        }
    if payload is None:
        return {
            "available": False,
            "status": "upstream_unavailable",
            "reason": (
                "NEPSE's market depth endpoint returned an empty body at last check. "
                "The order book is only served during trading hours."
            ),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "available": True,
        "source": "nepse:nots/nepse-data/marketdepth/{id}",
        "payload": payload,
        "note": "Raw order book as NEPSE returns it; row shape is unverified "
        "until observed during a live session.",
    }
