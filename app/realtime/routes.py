"""Real-time WebSocket routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.auth.deps import CurrentUser, DbSession
from app.realtime.service import RealTimeService, get_realtime_service

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


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


import json
import logging

logger = logging.getLogger(__name__)