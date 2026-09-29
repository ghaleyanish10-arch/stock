"""News service: fetches and manages news from NEPSE."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import NewsItem, Security
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService


class NewsService:
    """Manages news items from NEPSE."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service
        self._adapter = get_adapter()

    # --- CRUD ---

    def get_news(
        self,
        session: "Session",
        user_id: Optional[str] = None,
        symbol: Optional[str] = None,
        news_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Get news items with filters."""
        from app.db.models import NewsItem

        query = select(NewsItem).order_by(NewsItem.published_at.desc())

        if symbol:
            query = query.where(NewsItem.symbol == symbol.upper())
        if news_type:
            query = query.where(NewsItem.news_type == news_type)
        if date_from:
            query = query.where(NewsItem.published_at >= date_from)
        if date_to:
            query = query.where(NewsItem.published_at <= date_to)

        total = session.scalar(
            select(func.count()).select_from(query.subquery())
        )

        items = list(
            session.scalars(
                query.limit(limit).offset(offset)
            )
        )

        return {
            "total": total or 0,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": item.id,
                    "symbol": item.symbol,
                    "headline": item.headline,
                    "body": item.body,
                    "news_type": item.news_type,
                    "news_source": item.news_source,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "parsed": item.parsed,
                }
                for item in items
            ],
        }

    def get_news_item(self, session: "Session", news_id: str) -> Optional[dict]:
        """Get a single news item by ID."""
        from app.db.models import NewsItem
        item = session.get(NewsItem, news_id)
        if not item:
            return None
        return {
            "id": item.id,
            "symbol": item.symbol,
            "headline": item.headline,
            "body": item.body,
            "news_type": item.news_type,
            "news_source": item.news_source,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "parsed": item.parsed,
        }

    # --- Sync from NEPSE ---

    async def sync_news(
        self,
        session: "Session",
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        """Sync news from NEPSE for a symbol or market-wide."""
        total_synced = 0

        if symbol:
            # Sync company-specific news for a single symbol
            synced = await self._sync_company_news(session, symbol.upper(), limit)
            total_synced += synced
        else:
            # Sync market-wide news
            synced = await self._sync_market_news(session, limit)
            total_synced += synced

            # Also sync company-specific news for all enriched securities
            from app.db.models import Security
            securities = session.scalars(
                select(Security).where(Security.nepse_security_id.is_not(None))
            ).all()

            for security in securities:
                synced = await self._sync_company_news(session, security.symbol, limit)
                total_synced += synced

        return {"synced": total_synced}

    async def _sync_market_news(self, session: "Session", limit: int) -> int:
        """Sync market-wide news from NEPSE."""
        adapter = get_adapter()
        await adapter.start()

        news_data = await self._adapter.call(
            "market_news",
            lambda: self._adapter.get_json("news/media/news-and-alerts"),
        )

        rows = news_data if isinstance(news_data, list) else []
        synced = 0

        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue

            news = row  # Market-wide news has fields directly on the row

            if not isinstance(news, dict):
                continue

            nepse_news_id = str(news.get("id") or news.get("messageId"))
            if not nepse_news_id:
                continue

            from app.db.models import NewsItem
            existing = session.scalar(
                select(NewsItem).where(NewsItem.nepse_news_id == nepse_news_id)
            )
            if existing:
                continue

            headline = news.get("messageTitle")
            body = news.get("messageBody")
            news_type = news.get("messageType")
            news_source = None  # Not available in market-wide feed
            published_at = None
            added_date = news.get("addedDate")
            if added_date:
                try:
                    from datetime import datetime
                    published_at = datetime.fromisoformat(added_date.replace("Z", "+00:00"))
                except Exception:
                    pass

            parsed = None
            if body:
                from app.reference.service import _parse_notice_body
                parsed = _parse_notice_body(body)

            item = NewsItem(
                symbol=None,
                nepse_news_id=nepse_news_id,
                headline=headline,
                body=body,
                news_type=news_type,
                news_source=None,
                published_at=published_at,
                parsed=parsed,
            )
            session.add(item)
            synced += 1

        session.commit()
        return synced

    async def _sync_company_news(self, session: "Session", symbol: str, limit: int) -> int:
        """Sync company-specific news for a symbol."""
        from app.db.models import Security
        adapter = get_adapter()
        await adapter.start()

        security = session.get(Security, symbol.upper())
        if not security or not security.nepse_security_id:
            return 0

        news_data = await self._adapter.call(
            f"company_news:{symbol}",
            lambda: self._adapter.get_json(f"application/company-news/{security.nepse_security_id}"),
        )

        rows = news_data if isinstance(news_data, list) else []
        synced = 0

        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue

            if "companyNews" in row and isinstance(row["companyNews"], dict):
                news = row["companyNews"]
            else:
                continue  # Skip if not company news format

            if not isinstance(news, dict):
                continue

            nepse_news_id = str(news.get("id") or news.get("newsId"))
            if not nepse_news_id:
                continue

            from app.db.models import NewsItem
            existing = session.scalar(
                select(NewsItem).where(NewsItem.nepse_news_id == nepse_news_id)
            )
            if existing:
                continue

            headline = news.get("newsHeadline")
            body = news.get("newsBody")
            news_type = news.get("newsType")
            news_source = news.get("newsSource")
            published_at = None
            added_date = news.get("addedDate")
            if added_date:
                try:
                    from datetime import datetime
                    published_at = datetime.fromisoformat(added_date.replace("Z", "+00:00"))
                except Exception:
                    pass

            parsed = None
            if body:
                from app.reference.service import _parse_notice_body
                parsed = _parse_notice_body(body)

            item = NewsItem(
                symbol=symbol.upper(),
                nepse_news_id=nepse_news_id,
                headline=headline,
                body=body,
                news_type=news_type,
                news_source=news_source,
                published_at=published_at,
                parsed=parsed,
            )
            session.add(item)
            synced += 1

        session.commit()
        return synced

    def search_news(
        self,
        session: "Session",
        query: str,
        limit: int = 20,
    ) -> list:
        """Search news by keyword in headline or body."""
        from app.db.models import NewsItem
        from sqlalchemy import or_

        query_str = f"%{query}%"
        items = list(
            session.scalars(
                select(NewsItem)
                .where(
                    or_(
                        NewsItem.headline.ilike(query_str),
                        NewsItem.body.ilike(query_str),
                    )
                )
                .order_by(NewsItem.published_at.desc())
                .limit(limit)
            )
        )
        return [
            {
                "id": item.id,
                "symbol": item.symbol,
                "headline": item.headline,
                "news_type": item.news_type,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
            for item in items
        ]