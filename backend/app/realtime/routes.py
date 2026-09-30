"""Real-time routes: WebSocket streams plus cache readouts.

The REST endpoints serve the shared poller's in-memory price cache, so reading
them costs zero extra NEPSE calls no matter how many browsers poll them - the
one upstream request per interval is made by RealTimeService regardless.
"""

from __future__ import annotations

import json
import logging

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.auth.deps import CurrentUser, DbSession
from app.realtime.service import RealTimeService, get_realtime_service

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

logger = logging.getLogger(__name__)


def _update_payload(u) -> dict[str, Any]:
    """One PriceUpdate as JSON, with an ISO timestamp."""
    return {
        "symbol": u.symbol,
        "ltp": u.ltp,
        "change": u.change,
        "change_pct": u.change_pct,
        "volume": u.volume,
        "turnover": u.turnover,
        "high": u.high,
        "low": u.low,
        "timestamp": u.timestamp.isoformat(),
    }


@router.get("/prices")
async def realtime_prices(
    realtime: RealTimeService = Depends(get_realtime_service),
    symbols: str = Query("", description="Optional comma-separated filter"),
) -> dict[str, Any]:
    """Live prices from the shared poller's cache (no new NEPSE calls).

    Empty `quotes` means the poller has not completed a pass yet or the market
    feed is closed/pre-open - not an error.
    """
    wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    cache = realtime.get_all_cached_prices()
    quotes = [
        _update_payload(u)
        for sym, u in sorted(cache.items())
        if not wanted or sym in wanted
    ]
    return {
        "quotes": quotes,
        "count": len(quotes),
        "requested": sorted(wanted) if wanted else None,
        "as_of": max((u.timestamp for u in cache.values()), default=None).isoformat()
        if cache
        else None,
    }


@router.get("/prices/{symbol}")
async def realtime_price(
    symbol: str,
    realtime: RealTimeService = Depends(get_realtime_service),
) -> dict[str, Any]:
    """One symbol's live price from the poller cache; 404 only if never seen."""
    u = realtime.get_cached_price(symbol.strip().upper())
    if u is None:
        raise HTTPException(404, f"No live price cached for {symbol.upper()} yet.")
    return _update_payload(u)


@router.websocket("/ws/watchlist/{watchlist_id}")
async def watchlist_ws(
    websocket: WebSocket,
    watchlist_id: str,
    session: DbSession,
    user: CurrentUser,
    realtime: RealTimeService = Depends(get_realtime_service),
):
    """
    WebSocket endpoint for real-time watchlist updates.
    
    Client connects, subscribes to a watchlist, receives price updates
    as they arrive from the shared poller.
    """
    await websocket.accept()
    realtime.subscribe_watchlist(watchlist_id, websocket)
    
    try:
        # Send initial confirmation
        await websocket.send_text(json.dumps({
            "type": "subscribed",
            "watchlist_id": watchlist_id,
            "message": f"Subscribed to watchlist {watchlist_id}"
        }))
        
        # Keep connection alive, handle incoming messages
        while True:
            try:
                data = await websocket.receive_text()
                msg = json.loads(data)
                
                # Handle ping/pong for keepalive
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg.get("type") == "unsubscribe":
                    break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning(f"WebSocket error: {e}")
                break
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        realtime.unsubscribe_watchlist(watchlist_id, websocket)


@router.websocket("/ws/symbol/{symbol}")
async def symbol_ws(
    websocket: WebSocket,
    symbol: str,
    session: DbSession,
    user: CurrentUser,
    realtime: RealTimeService = Depends(get_realtime_service),
):
    """
    WebSocket endpoint for real-time symbol updates.
    
    Client connects, subscribes to a symbol, receives price updates.
    """
    symbol = symbol.upper()
    await websocket.accept()
    realtime.subscribe_symbol(symbol, websocket)
    
    try:
        await websocket.send_text(json.dumps({
            "type": "subscribed",
            "symbol": symbol,
            "message": f"Subscribed to {symbol}"
        }))
        
        while True:
            try:
                data = await websocket.receive_text()
                msg = json.loads(data)
                
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg.get("type") == "unsubscribe":
                    break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning(f"WebSocket error: {e}")
                break
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        realtime.unsubscribe_symbol(symbol, websocket)


@router.get("/status")
async def realtime_status(
    realtime: RealTimeService = Depends(get_realtime_service),
) -> dict[str, Any]:
    """Get real-time service status and subscriber counts."""
    return {
        "running": realtime._running,
        "cached_symbols": len(realtime._price_cache),
        "subscribers": realtime.get_subscriber_counts(),
    }