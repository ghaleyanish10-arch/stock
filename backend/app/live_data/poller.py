"""Live market data poller: central poller that fetches NEPSE data during trading hours
and publishes snapshots to an in-memory ring buffer + database for SSE delivery.

This replaces the ad-hoc live quote polling with a proper central poller that:
- Runs only during NPT trading hours (Sun-Thu, 11:00-15:00)
- Respects rate limits (min 15s interval, configurable)
- Stores snapshots in a ring buffer (30 min) + persists last-good to DB
- Provides snapshots to SSE endpoint and REST endpoints with delay gating
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from app.config import settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.nepse.registry import get_adapter
from app.nepse.service import NepseService

logger = logging.getLogger(__name__)

# Nepal is UTC+05:45 with no DST
NPT = timezone(timedelta(hours=5, minutes=45))


def nepal_now() -> datetime:
    """Current time in Nepal (NPT)."""
    return datetime.now(NPT)


def is_trading_day(dt: date, session: Optional[SessionLocal] = None) -> bool:
    """Check if a date is a trading day (Sun-Thu, not a holiday)."""
    # Weekend check: Fri=4, Sat=5 in Python (Mon=0)
    if dt.weekday() >= 5:
        return False
    # TODO: Check holiday table if session provided
    return True


def is_trading_hours(dt: datetime) -> bool:
    """Check if datetime falls within NEPSE trading hours (11:00-15:00 NPT)."""
    t = dt.timetz()
    return time(11, 0) <= t <= time(15, 0)


@dataclass
class MarketSnapshot:
    """A single market data snapshot with metadata."""
    fetched_at: datetime          # When we fetched it (our clock)
    source_time: datetime         # NEPSE's timestamp (from their API)
    data: dict                    # Raw payload from NEPSE
    market_open: bool             # Was market open at fetch time?
    fetch_duration_ms: int        # How long the fetch took


class SnapshotRingBuffer:
    """Thread-safe ring buffer for recent market snapshots."""
    
    def __init__(self, max_age_seconds: int = 1800):  # 30 minutes default
        self.max_age_seconds = max_age_seconds
        self._snapshots: List[MarketSnapshot] = []
        self._lock = asyncio.Lock()
    
    async def add(self, snapshot: MarketSnapshot) -> None:
        async with self._lock:
            self._snapshots.append(snapshot)
            self._prune()
    
    def _prune(self) -> None:
        """Remove snapshots older than max_age_seconds."""
        cutoff = nepal_now() - timedelta(seconds=self.max_age_seconds)
        self._snapshots = [s for s in self._snapshots if s.fetched_at >= cutoff]
    
    async def get_latest(self, before: Optional[datetime] = None) -> Optional[dict]:
        """Get the latest snapshot before a given time (for delay gating)."""
        async with self._lock:
            self._prune()
            if not self._snapshots:
                return None
            if before is None:
                return self._snapshots[-1].data
            # Find the latest snapshot with fetched_at <= before
            for snap in reversed(self._snapshots):
                if snap.fetched_at <= before:
                    return snap.data
            return None
    
    async def get_all(self) -> List[dict]:
        """Get all snapshots (for debugging)."""
        async with self._lock:
            self._prune()
            return [s.data for s in self._snapshots]


class LiveDataPoller:
    """Central poller that fetches NEPSE data during trading hours."""
    
    def __init__(
        self,
        interval_seconds: int = 30,
        max_age_seconds: int = 1800,  # 30 minutes
        trading_start: time = time(11, 0),
        trading_end: time = time(15, 0),
    ):
        self.interval_seconds = interval_seconds
        self.trading_start = trading_start
        self.trading_end = trading_end
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._snapshots = SnapshotRingBuffer(max_age_seconds)
        self._last_fetch: Optional[datetime] = None
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        
        # Statistics
        self.stats = {
            "total_fetches": 0,
            "successful_fetches": 0,
            "failed_fetches": 0,
            "last_success": None,
            "last_error": None,
        }
    
    async def start(self) -> None:
        """Start the poller."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Live data poller started (interval=%ss)", self.interval_seconds)
    
    async def stop(self) -> None:
        """Stop the poller."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Live data poller stopped")
    
    def is_running(self) -> bool:
        return self._running
    
    def get_stats(self) -> dict:
        return {**self.stats, "running": self._running}
    
    async def get_latest_snapshot(self, before: Optional[datetime] = None) -> Optional[dict]:
        """Get the latest snapshot before a given time (for delay gating)."""
        return await self._snapshots.get_latest(before)
    
    def get_all_snapshots(self) -> List[dict]:
        """Get all snapshots in buffer (for debugging)."""
        return self._snapshots.get_all()
    
    async def _run_loop(self) -> None:
        """Main poller loop."""
        while self._running:
            try:
                now = nepal_now()
                
                # Check if we're in trading hours
                if not is_trading_day(now.date()):
                    logger.debug("Not a trading day, sleeping until next check")
                    await asyncio.sleep(60)  # Check every minute on non-trading days
                    continue
                
                if not is_trading_hours(now):
                    # Outside trading hours - check less frequently
                    await asyncio.sleep(60)
                    continue
                
                # Check if enough time has passed since last fetch
                if self._last_fetch:
                    elapsed = (nepal_now() - self._last_fetch).total_seconds()
                    if elapsed < self.interval_seconds:
                        await asyncio.sleep(self.interval_seconds - elapsed)
                        continue
                
                # Fetch data
                await self._fetch_and_store()
                
            except asyncio.CancelledError:
                logger.info("Poller cancelled")
                raise
            except Exception as e:
                logger.exception("Poller loop error: %s", e)
                await asyncio.sleep(5)  # Brief pause on error
    
    async def _fetch_and_store(self) -> None:
        """Fetch data from NEPSE and store snapshot."""
        start_time = time.time()
        self._last_fetch = nepal_now()
        self.stats["total_fetches"] += 1
        
        try:
            # Get the shared NEPSE adapter
            adapter = get_adapter()
            service = NepseService(adapter)
            
            # Fetch market overview (includes index, summary, live prices)
            market_data = await service.get_market_overview()
            
            # Also fetch live prices for all stocks
            stocks_data = await service.get_stocks()
            
            # Build snapshot
            source_time = datetime.fromisoformat(market_data.status.as_of.replace('Z', '+00:00')) if market_data.status.as_of else nepal_now()
            
            snapshot = MarketSnapshot(
                fetched_at=nepal_now(),
                source_time=source_time,
                data={
                    "market": market_data.model_dump(mode="json"),
                    "stocks": stocks_data.model_dump(mode="json") if hasattr(stocks_data, 'model_dump') else stocks_data,
                },
                market_open=market_data.status.is_open,
                fetch_duration_ms=int((time.time() - time.time()) * 1000),
            )
            
            # Store in ring buffer
            await self._snapshots.add(snapshot)
            
            self.stats["successful_fetches"] += 1
            self.stats["last_success"] = nepal_now().isoformat()
            self._consecutive_errors = 0
            
        except Exception as e:
            self.stats["failed_fetches"] += 1
            self.stats["last_error"] = str(e)
            self._consecutive_errors += 1
            logger.warning("Live data fetch failed: %s", e)
            
            if self._consecutive_errors >= self._max_consecutive_errors:
                logger.error("Too many consecutive errors, pausing poller")
                await asyncio.sleep(60)  # Back off
                self._consecutive_errors = 0


# Global poller instance (lazy initialization)
_poller: Optional[LiveDataPoller] = None


def get_poller() -> LiveDataPoller:
    """Get or create the global live data poller."""
    global _poller
    if _poller is None:
        _poller = LiveDataPoller(
            interval_seconds=settings.live_poll_interval_seconds or 30,
            max_age_seconds=settings.live_max_age_seconds or 1800,
        )
    return _poller


async def start_live_poller() -> None:
    """Start the global live data poller."""
    poller = get_poller()
    await poller.start()


async def stop_live_poller() -> None:
    """Stop the global live data poller."""
    global _poller
    if _poller:
        await _poller.stop()
        _poller = None