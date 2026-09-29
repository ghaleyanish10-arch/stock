"""NEPSE REST endpoints.

Every endpoint returns the shared envelope (`app.api.responses`) and never
leaks library payloads, stack traces, or internals to the frontend.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from app.api.responses import fail, nepse_error_response, ok
from app.nepse.exceptions import NepseServiceError
from app.nepse.registry import get_adapter
from app.nepse.service import NepseService, validate_symbol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nepse")

# One service instance per process, sharing the process-wide NEPSE adapter so
# the legacy endpoints, the archive, reference data and the scheduler all use a
# single upstream session and a single rate limiter.
service = NepseService(get_adapter())


@router.get("/status")
async def market_status():
    """Whether the NEPSE market is currently open."""
    try:
        data = await service.get_market_status()
        return ok(data.model_dump(mode="json"))
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/market")
async def market_overview():
    """Market status plus latest summary and the NEPSE index."""
    try:
        data = await service.get_market_overview()
        return ok(data.model_dump(mode="json"))
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/market/summary")
async def market_summary():
    """Latest market turnover summary (turnover, shares, transactions)."""
    try:
        data = await service.get_market_summary()
        return ok(data.model_dump(mode="json"))
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/indices")
async def indices():
    """NEPSE index plus all sector sub-indices (live values)."""
    try:
        nepse_index, sub_indices = await service.get_indices()
        return ok({"nepse": nepse_index.model_dump(mode="json"),
                   "sub_indices": [i.model_dump(mode="json") for i in sub_indices]})
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/indices/{index_name}/history")
async def index_history(
    index_name: str,
    start: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Historical daily OHLCV for one index (e.g. nepse, banking, hydropower)."""
    try:
        points = await service.get_index_history(index_name, start, end)
        return ok({
            "index": index_name.lower(),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "count": len(points),
            "history": [p.model_dump(mode="json") for p in points],
        })
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/market-caps")
async def market_caps(
    day: Optional[date] = Query(None, description="Return series from this date"),
):
    """Market capitalization series (optionally from one business date)."""
    try:
        data = await service.get_market_caps(day)
        return ok(data)
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/stocks")
async def stocks():
    """All securities that traded today, with daily figures."""
    try:
        data = await service.get_stocks()
        return ok(data.model_dump(mode="json"))
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/stocks/{symbol}")
async def stock(symbol: str):
    """One security's daily trading figures."""
    try:
        data = await service.get_stock(symbol)
        return ok(data.model_dump(mode="json"))
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/stocks/{symbol}/live")
async def stock_live(symbol: str):
    """One security's live trade data (price/volume list, filtered)."""
    try:
        data = await service.get_stock_live_price(symbol)
        return ok(data.model_dump(mode="json"))
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/stocks/{symbol}/history")
async def stock_history(
    symbol: str,
    start: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Per-security price history for a date range."""
    try:
        data = await service.get_price_history(symbol, start, end)
        return ok(data)
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/top-gainers")
async def top_gainers(
    limit: int = Query(10, ge=1, le=50, description="Max results"),
):
    """Top gaining securities of the latest session."""
    try:
        data = await service.get_top_gainers(limit)
        return ok(data)
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/top-losers")
async def top_losers(
    limit: int = Query(10, ge=1, le=50, description="Max results"),
):
    """Top losing securities of the latest session."""
    try:
        data = await service.get_top_losers(limit)
        return ok(data)
    except NepseServiceError as exc:
        return nepse_error_response(exc)


@router.get("/health")
async def health():
    """Cheap liveness probe - does NOT call NEPSE, so it is never expensive."""
    try:
        ready = await service.health_check()
        return ok({"service": "nepse", "status": "available" if ready else "unavailable"})
    except Exception:  # noqa: BLE001 - health must never 500
        logger.exception("NEPSE health check failed unexpectedly")
        return fail("NEPSE_SERVICE_ERROR", "NEPSE service failed to initialize")
