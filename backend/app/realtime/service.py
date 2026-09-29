"""Real-time shared poller: single upstream poll, fan-out to WebSocket clients."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.config import settings
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService

logger = logging.getLogger(__name__)


@dataclass
class PriceUpdate:
    """Single price update for a symbol."""
    symbol: str
    ltp: float
    change: float
    change_pct: float
    volume: int
    turnover: float
    high: float
    low: float
    timestamp: datetime


@dataclass
class WatchlistSnapshot:
    """Aggregated snapshot for a watchlist."""
    watchlist_id: str
    user_id: str
    items: List[PriceUpdate]
    timestamp: datetime


class RealTimeService:
    """
    Single shared poller that fetches live prices from NEPSE and fans out
    to subscribed WebSocket clients.
    
    Architecture:
    - One background task polls NEPSE at configured interval (default 30s)
    - Multiple WebSocket clients subscribe to specific watchlists/symbols
    - When poll completes, updates are broadcast to relevant subscribers
    - This ensures exactly ONE upstream call per poll interval regardless of client count
    """

    def __init__(self):
        self._adapter = get_adapter()
        self._reference = ReferenceService(self._adapter)
        self._poll_interval = settings.outbound_min_interval_ms * 2  # ~240ms minimum, but we use 30s
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Subscriptions: watchlist_id -> set of WebSocket connections
        self._watchlist_subscribers: Dict[str, Set[WebSocket]] = {}
        # Symbol-level subscriptions for direct symbol tracking
        self._symbol_subscribers: Dict[str, Set[WebSocket]] = {}
        # Cache of last known prices
        self._price_cache: Dict[str, PriceUpdate] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the shared poller."""
        if self._running:
            return
        await self._adapter.start()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Real-time poller started")

    async def stop(self):
        """Stop the shared poller."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Close all WebSocket connections
        await self._close_all_connections()
        logger.info("Real-time poller stopped")

    async def _close_all_connections(self):
        """Close all active WebSocket connections."""
        for ws_set in self._watchlist_subscribers.values():
            for ws in ws_set:
                try:
                    await ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
        for ws_set in self._symbol_subscribers.values():
            for ws in ws_set:
                try:
                    await ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
        self._watchlist_subscribers.clear()
        self._symbol_subscribers.clear()

    def subscribe_watchlist(self, watchlist_id: str, ws: WebSocket):
        """Subscribe a WebSocket to a watchlist's updates."""
        if watchlist_id not in self._watchlist_subscribers:
            self._watchlist_subscribers[watchlist_id] = set()
        self._watchlist_subscribers[watchlist_id].add(ws)

    def unsubscribe_watchlist(self, watchlist_id: str, ws: WebSocket):
        """Unsubscribe a WebSocket from a watchlist."""
        if watchlist_id in self._watchlist_subscribers:
            self._watchlist_subscribers[watchlist_id].discard(ws)
            if not self._watchlist_subscribers[watchlist_id]:
                del self._watchlist_subscribers[watchlist_id]

    def subscribe_symbol(self, symbol: str, ws: WebSocket):
        """Subscribe a WebSocket to a symbol's updates."""
        symbol = symbol.upper()
        if symbol not in self._symbol_subscribers:
            self._symbol_subscribers[symbol] = set()
        self._symbol_subscribers[symbol].add(ws)

    def unsubscribe_symbol(self, symbol: str, ws: WebSocket):
        """Unsubscribe a WebSocket from a symbol."""
        symbol = symbol.upper()
        if symbol in self._symbol_subscribers:
            self._symbol_subscribers[symbol].discard(ws)
            if not self._symbol_subscribers[symbol]:
                del self._symbol_subscribers[symbol]

    async def _poll_loop(self):
        """Main poll loop: fetch live market, update cache, broadcast to subscribers."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Real-time poll error: {e}")
            
            # Wait for next poll interval (configurable, default 30s)
            await asyncio.sleep(30)

    async def _poll_once(self):
        """Single poll: fetch live market data and broadcast updates."""
        try:
            # Get live market data from NEPSE
            live_data = await self._adapter.call(
                "live_market",
                lambda: self._adapter.get_live_market()
            )
            
            if not live_data or not isinstance(live_data, list):
                logger.warning("Live market returned empty or invalid data")
                return

            updates: List[PriceUpdate] = []
            now = datetime.utcnow()

            for item in live_data:
                symbol = item.get("symbol")
                if not symbol:
                    continue
                
                ltp = item.get("last_traded_price") or item.get("close_price")
                if ltp is None:
                    continue

                # Calculate change
                prev_close = item.get("previous_close")
                change = ltp - prev_close if prev_close else 0
                change_pct = (change / prev_close * 100) if prev_close else 0

                update = PriceUpdate(
                    symbol=symbol.upper(),
                    ltp=ltp,
                    change=change,
                    change_pct=change_pct,
                    volume=item.get("total_traded_quantity") or 0,
                    turnover=item.get("total_traded_value") or 0.0,
                    high=item.get("high_price") or ltp,
                    low=item.get("low_price") or ltp,
                    timestamp=now,
                )
                updates.append(update)

                # Update cache
                async with self._lock:
                    self._price_cache[symbol.upper()] = update

            if not updates:
                return

            # Broadcast to symbol subscribers
            await self._broadcast_symbol_updates(updates)

            # Also broadcast to watchlist subscribers (requires mapping watchlist -> symbols)
            await self._broadcast_watchlist_updates(updates)

            logger.debug(f"Real-time poll: updated {len(updates)} symbols")

        except Exception as e:
            logger.error(f"Error in _poll_once: {e}")

    async def _broadcast_symbol_updates(self, updates: List[PriceUpdate]):
        """Broadcast updates to WebSocket subscribers for specific symbols."""
        for update in updates:
            symbol = update.symbol
            if symbol not in self._symbol_subscribers:
                continue
            
            message = {
                "type": "price_update",
                "data": {
                    "symbol": update.symbol,
                    "ltp": update.ltp,
                    "change": update.change,
                    "change_pct": update.change_pct,
                    "volume": update.volume,
                    "turnover": update.turnover,
                    "high": update.high,
                    "low": update.low,
                    "timestamp": update.timestamp.isoformat(),
                }
            }
            
            dead_connections = set()
            for ws in self._symbol_subscribers[symbol]:
                try:
                    await ws.send_text(json.dumps(message))
                except Exception:
                    dead_connections.add(ws)
            
            # Clean up dead connections
            for ws in dead_connections:
                self._symbol_subscribers[symbol].discard(ws)

    async def _broadcast_watchlist_updates(self, updates: List[PriceUpdate]):
        """Broadcast updates to watchlist subscribers."""
        # Build a quick lookup
        update_map = {u.symbol: u for u in updates}
        
        for watchlist_id, ws_set in self._watchlist_subscribers.items():
            # In a real implementation, we'd fetch the watchlist's symbols
            # For now, we broadcast all updates to all watchlist subscribers
            # A more optimized version would filter by watchlist contents
            
            if not ws_set:
                continue

            message = {
                "type": "watchlist_update",
                "watchlist_id": watchlist_id,
                "data": [
                    {
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
                    for u in updates
                ],
                "timestamp": datetime.utcnow().isoformat(),
            }

            dead_connections = set()
            for ws in ws_set:
                try:
                    await ws.send_text(json.dumps(message))
                except Exception:
                    dead_connections.add(ws)

            # Clean up dead connections
            for ws in dead_connections:
                ws_set.discard(ws)

    def get_cached_price(self, symbol: str) -> Optional[PriceUpdate]:
        """Get the latest cached price for a symbol."""
        return self._price_cache.get(symbol.upper())

    def get_all_cached_prices(self) -> Dict[str, PriceUpdate]:
        """Get all cached prices."""
        return dict(self._price_cache)

    def get_subscriber_counts(self) -> Dict[str, int]:
        """Get subscriber counts for monitoring."""
        return {
            "watchlists": {wl: len(ws) for wl, ws in self._watchlist_subscribers.items()},
            "symbols": {sym: len(ws) for sym, ws in self._symbol_subscribers.items()},
        }


# Global instance
_realtime_service: Optional[RealTimeService] = None


def get_realtime_service() -> RealTimeService:
    """Get or create the global real-time service."""
    global _realtime_service
    if _realtime_service is None:
        _realtime_service = RealTimeService()
    return _realtime_service


async def start_realtime_service():
    """Start the global real-time service."""
    service = get_realtime_service()
    await service.start()


async def stop_realtime_service():
    """Stop the global real-time service."""
    global _realtime_service
    if _realtime_service:
        await _realtime_service.stop()
        _realtime_service = None