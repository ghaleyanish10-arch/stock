"""Watchlist API routes."""

from __future__ import annotations

from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, DbSession
from app.watchlist.service import WatchlistService
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"], redirect_slashes=True)

_watchlist = WatchlistService(ReferenceService(get_adapter()))


class CreateWatchlistRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@router.post("", summary="Create a new watchlist")
def create_watchlist(
    session: DbSession,
    user: CurrentUser,
    request: CreateWatchlistRequest,
) -> dict:
    watchlist = _watchlist.create_watchlist(session, user.id, request.name)
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "created_at": watchlist.created_at.isoformat() if watchlist.created_at else None,
    }


@router.get("", summary="List user's watchlists")
def list_watchlists(
    session: DbSession,
    user: CurrentUser,
) -> dict:
    watchlists = _watchlist.list_watchlists(session, user.id)
    return {
        "watchlists": [
            {
                "id": w.id,
                "name": w.name,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }
            for w in watchlists
        ]
    }


@router.get("/{watchlist_id}", summary="Get watchlist details")
def get_watchlist(
    watchlist_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    watchlist = _watchlist.get_watchlist(session, watchlist_id, user.id)
    if not watchlist:
        raise HTTPException(404, "Watchlist not found")
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "created_at": watchlist.created_at.isoformat() if watchlist.created_at else None,
    }


@router.patch("/{watchlist_id}", summary="Update watchlist")
def update_watchlist(
    watchlist_id: str,
    session: DbSession,
    user: CurrentUser,
    name: str,
) -> dict:
    watchlist = _watchlist.update_watchlist(session, watchlist_id, user.id, name)
    if not watchlist:
        raise HTTPException(404, "Watchlist not found")
    return {
        "id": watchlist.id,
        "name": watchlist.name,
    }


@router.delete("/{watchlist_id}", summary="Delete watchlist")
def delete_watchlist(
    watchlist_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _watchlist.delete_watchlist(session, watchlist_id, user.id)
    if not deleted:
        raise HTTPException(404, "Watchlist not found")
    return {"detail": "Watchlist deleted"}


# --- Items ---


@router.post("/{watchlist_id}/items", summary="Add symbol to watchlist")
def add_item(
    watchlist_id: str,
    session: DbSession,
    user: CurrentUser,
    symbol: str,
    note: Optional[str] = None,
) -> dict:
    try:
        item = _watchlist.add_item(session, watchlist_id, user.id, symbol, note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "symbol": item.symbol,
        "note": item.note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.delete("/{watchlist_id}/items/{symbol}", summary="Remove symbol from watchlist")
def remove_item(
    watchlist_id: str,
    symbol: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _watchlist.remove_item(session, watchlist_id, user.id, symbol)
    if not deleted:
        raise HTTPException(404, "Item not found in watchlist")
    return {"detail": "Item removed"}


@router.get("/{watchlist_id}/items", summary="Get watchlist items with prices")
def get_items(
    watchlist_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    items = _watchlist.get_items(session, watchlist_id, user.id)
    return {
        "items": items,
    }


@router.patch("/{watchlist_id}/items/{symbol}/reorder", summary="Reorder item")
def reorder_item(
    watchlist_id: str,
    symbol: str,
    session: DbSession,
    user: CurrentUser,
    position: int = Query(..., ge=0),
) -> dict:
    ok = _watchlist.reorder_items(session, watchlist_id, user.id, symbol, position)
    if not ok:
        raise HTTPException(400, "Could not reorder")
    return {"detail": "Item reordered"}