"""Quarterly analysis API routes."""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, DbSession
from app.analytics.quarterly.service import QuarterlyAnalysisService
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService

router = APIRouter(prefix="/api/analytics/quarterly", tags=["quarterly"])

_quarterly = QuarterlyAnalysisService(ReferenceService(get_adapter()))


@router.get("/periods", summary="Get available periods for quarterly analysis")
def get_periods(
    session: DbSession,
    user: CurrentUser,
) -> dict:
    """Get available fiscal years and quarters for analysis."""
    # This would typically query the database for available periods
    # For now return a static structure
    return {
        "fiscal_years": ["2080-2081", "2081-2082", "2082-2083", "2083-2084"],
        "quarters": [1, 2, 3, 4],
        "note": "Nepali fiscal year: Shrawan (mid-Jul) to Ashadh (mid-Jul next year)",
    }


@router.get("/{symbol}", summary="Get quarterly analysis for a symbol")
def get_quarterly_analysis(
    symbol: str,
    session: DbSession,
    user: CurrentUser,
    fiscal_year: Optional[str] = Query(None, description="Fiscal year (e.g., 2080-2081)"),
    quarter: Optional[int] = Query(None, ge=1, le=4, description="Quarter number (1-4)"),
) -> dict:
    """Get quarterly analysis for a symbol."""
    _quarterly = QuarterlyAnalysisService(ReferenceService(get_adapter()))
    
    if fiscal_year and quarter:
        data = _quarterly.get_or_compute(session, symbol, fiscal_year, quarter)
        if not data:
            raise HTTPException(404, "No data for this period")
        return data
    elif fiscal_year:
        data = _quarterly.get_by_fiscal_year(session, symbol, fiscal_year)
        return {"symbol": symbol, "fiscal_year": fiscal_year, "quarters": data}
    else:
        data = _quarterly.get_latest(session, symbol, limit=8)
        return {"symbol": symbol, "history": data}


@router.get("/{symbol}/history", summary="Get all quarterly history for a symbol")
def get_quarterly_history(
    symbol: str,
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Get all available quarterly analyses for a symbol."""
    _quarterly = QuarterlyAnalysisService(ReferenceService(get_adapter()))
    data = _quarterly.get_latest(session, symbol, limit)
    return {
        "symbol": symbol,
        "count": len(data),
        "history": data,
    }