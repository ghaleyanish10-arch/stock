"""Watchlist service: manages user watchlists."""

from __future__ import annotations

from typing import Any, Optional, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Watchlist, WatchlistItem, Security
from app.reference.service import ReferenceService
from app.nepse.registry import get_adapter


class WatchlistService:
    """Manages user watchlists."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service

    def create_watchlist(
        self,
        session: "Session",
        user_id: str,
        name: str,
    ) -> "Watchlist":
        """Create a new watchlist for a user."""
        from app.db.models import Watchlist
        watchlist = Watchlist(user_id=user_id, name=name)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        return watchlist

    def get_watchlist(self, session: "Session", watchlist_id: str, user_id: str) -> Optional["Watchlist"]:
        """Get watchlist by ID, ensuring ownership."""
        from app.db.models import Watchlist
        watchlist = session.get(Watchlist, watchlist_id)
        if watchlist and watchlist.user_id == user_id:
            return watchlist
        return None

    def list_watchlists(self, session: "Session", user_id: str) -> list:
        """List all watchlists for a user."""
        from app.db.models import Watchlist
        return list(
            session.scalars(
                select(Watchlist)
                .where(Watchlist.user_id == user_id)
                .order_by(Watchlist.created_at.desc())
            )
        )

    def update_watchlist(
        self,
        session: "Session",
        watchlist_id: str,
        user_id: str,
        name: Optional[str] = None,
    ) -> Optional["Watchlist"]:
        """Update watchlist name."""
        from app.db.models import Watchlist
        watchlist = session.get(Watchlist, watchlist_id)
        if not watchlist or watchlist.user_id != user_id:
            return None
        if name is not None:
            watchlist.name = name
        session.commit()
        session.refresh(watchlist)
        return watchlist

    def delete_watchlist(self, session: "Session", watchlist_id: str, user_id: str) -> bool:
        """Delete a watchlist."""
        from app.db.models import Watchlist
        watchlist = session.get(Watchlist, watchlist_id)
        if not watchlist or watchlist.user_id != user_id:
            return False
        session.delete(watchlist)
        session.commit()
        return True

    def add_item(
        self,
        session: "Session",
        watchlist_id: str,
        user_id: str,
        symbol: str,
        note: Optional[str] = None,
    ) -> "WatchlistItem":
        """Add a symbol to a watchlist."""
        from app.db.models import WatchlistItem, Security
        watchlist = session.get(Watchlist, watchlist_id)
        if not watchlist or watchlist.user_id != user_id:
            raise ValueError("Watchlist not found")

        symbol = symbol.upper()
        security = session.get(Security, symbol)
        if not security:
            raise ValueError(f"Security {symbol} not found")

        # Check if already exists
        existing = session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.symbol == symbol,
            )
        )
        if existing:
            raise ValueError(f"Symbol {symbol} already in watchlist")

        item = WatchlistItem(
            watchlist_id=watchlist_id,
            symbol=symbol,
            note=note,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    def remove_item(
        self,
        session: "Session",
        watchlist_id: str,
        user_id: str,
        symbol: str,
    ) -> bool:
        """Remove a symbol from a watchlist."""
        from app.db.models import WatchlistItem
        watchlist = session.get(Watchlist, watchlist_id)
        if not watchlist or watchlist.user_id != user_id:
            raise ValueError("Watchlist not found")

        item = session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.symbol == symbol.upper(),
            )
        )
        if not item:
            return False

        session.delete(item)
        session.commit()
        return True

    def get_items(
        self,
        session: "Session",
        watchlist_id: str,
        user_id: str,
    ) -> list:
        """Get all items in a watchlist with latest prices."""
        from app.db.models import WatchlistItem, Security, DailyBar
        from app.nepse.registry import get_adapter
        from app.reference.service import ReferenceService

        watchlist = session.get(Watchlist, watchlist_id)
        if not watchlist or watchlist.user_id != user_id:
            return []

        items = list(
            session.scalars(
                select(WatchlistItem)
                .where(WatchlistItem.watchlist_id == watchlist_id)
                .order_by(WatchlistItem.created_at)
            )
        )

        # Enrich with latest prices
        adapter = get_adapter()
        symbols = [item.symbol for item in items]
        prices = {}
        for symbol in symbols:
            try:
                price_data = self._reference._client.call(
                    f"stock:{symbol}",
                    lambda: self._reference._client.get_stock_info(symbol),
                )
                if price_data:
                    prices[symbol] = price_data.get("last_traded_price")
            except Exception:
                pass

        items_data = []
        for item in items:
            price = prices.get(item.symbol)
            change = None
            change_pct = None
            if price and item.note:
                try:
                    # Try to parse previous close from note
                    pass
                except Exception:
                    pass
            items_data.append({
                "symbol": item.symbol,
                "name": None,
                "price": price,
                "change": change,
                "change_pct": change_pct,
                "note": item.note,
                "added_at": item.created_at.isoformat() if item.created_at else None,
            })

        return items_data

    def reorder_items(
        self,
        session: "Session",
        watchlist_id: str,
        user_id: str,
        symbol: str,
        new_position: int,
    ) -> bool:
        """Reorder items in a watchlist (not implemented - would need position field)."""
        # For now, just return True as a placeholder
        # Would need to add a position field to WatchlistItem
        return True