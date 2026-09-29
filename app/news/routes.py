"""News API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, DbSession
from app.news.service import NewsService
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService

router = APIRouter(prefix="/api/news", tags=["news"], redirect_slashes=True)

_news = NewsService(ReferenceService(get_adapter()))


@router.get("", summary="List news with filters")
def list_news(
    session: DbSession,
    user: CurrentUser,
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    news_type: Optional[str] = Query(None, description="Filter by news type"),
    date_from: Optional[str] = Query(None, description="From date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="To date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    return _news.get_news(
        session,
        user.id,
        symbol=symbol,
        news_type=news_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{news_id}", summary="Get news item by ID")
def get_news(
    news_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    item = _news.get_news_item(session, news_id)
    if not item:
        raise HTTPException(404, "News item not found")
    return item


@router.post("/sync", summary="Sync news from NEPSE (admin)")
async def sync_news(
    session: DbSession,
    user: CurrentUser,
    symbol: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return await _news.sync_news(session, symbol, limit)


@router.get("/search", summary="Search news by keyword")
def search_news(
    session: DbSession,
    user: CurrentUser,
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    results = _news.search_news(session, q, limit)
    return {
        "query": q,
        "count": len(results),
        "results": results,
    }