"""Quarterly analysis service: computes quarterly metrics from archive data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional, Dict
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.db.models import DailyBar, QuarterlyAnalysis, Security
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService


class QuarterlyAnalysisService:
    """Computes and caches quarterly analysis from archive data."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service

    def get_or_compute(
        self,
        session: "Session",
        symbol: str,
        fiscal_year: str,
        quarter: int,
    ) -> Optional[dict]:
        """Get quarterly analysis, computing if not cached."""
        symbol = symbol.upper()
        
        # Check cache
        cached = session.scalar(
            select(QuarterlyAnalysis).where(
                QuarterlyAnalysis.symbol == symbol,
                QuarterlyAnalysis.fiscal_year == fiscal_year,
                QuarterlyAnalysis.quarter == quarter,
            )
        )
        if cached:
            return self._to_dict(cached)

        # Compute if not cached
        return self._compute_and_cache(session, symbol, fiscal_year, quarter)

    def _compute_and_cache(
        self,
        session: "Session",
        symbol: str,
        fiscal_year: str,
        quarter: int,
    ) -> Optional[dict]:
        """Compute quarterly analysis from archive data."""
        # Determine quarter date range
        q_start, q_end = self._quarter_date_range(fiscal_year, quarter)
        if not q_start or not q_end:
            return None

        # Get bars for the quarter
        bars = session.scalars(
            select(DailyBar)
            .where(
                DailyBar.symbol == symbol.upper(),
                DailyBar.business_date >= q_start,
                DailyBar.business_date <= q_end,
            )
            .order_by(DailyBar.business_date)
        ).all()

        if not bars:
            return None

        # Compute metrics
        closes = [b.close for b in bars if b.close is not None]
        highs = [b.high for b in bars if b.high is not None]
        lows = [b.low for b in bars if b.low is not None]
        volumes = [b.volume for b in bars if b.volume is not None]

        if not closes:
            return None

        quarterly_return = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] else 0
        high = max(highs) if highs else None
        low = min(lows) if lows else None
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        volatility = self._calculate_volatility(closes) if len(closes) > 1 else None

        # Try to get fundamental data if available
        from app.db.models import FundamentalsImport
        from sqlalchemy import select as sq_select
        fundamentals = session.scalars(
            select(FundamentalsImport).where(
                FundamentalsImport.symbol == symbol.upper(),
                FundamentalsImport.fiscal_year == fiscal_year,
                FundamentalsImport.quarter == quarter,
            )
        ).first()

        # Save to cache
        analysis = QuarterlyAnalysis(
            symbol=symbol.upper(),
            fiscal_year=fiscal_year,
            quarter=quarter,
            quarterly_return=round(quarterly_return, 2) if quarterly_return else None,
            high=round(high, 2) if high else None,
            low=round(low, 2) if low else None,
            avg_volume=round(avg_volume, 2) if avg_volume else None,
            volatility=round(volatility, 4) if volatility else None,
            revenue=fundamentals.revenue if fundamentals else None,
            net_profit=fundamentals.net_profit if fundamentals else None,
            eps=fundamentals.eps if fundamentals else None,
            book_value_per_share=fundamentals.book_value_per_share if fundamentals else None,
        )
        session.add(analysis)
        session.commit()

        return self._to_dict(analysis)

    def _quarter_date_range(self, fiscal_year: str, quarter: int) -> tuple[Optional[str], Optional[str]]:
        """Convert fiscal year and quarter to date range.
        
        Nepal fiscal year: Shrawan (mid-July) to Ashadh (mid-July next year)
        Q1: Shrawan-Bhadra (mid-Jul to mid-Oct)
        Q2: Ashwin-Kartik (mid-Oct to mid-Jan)
        Q3: Mangsir-Poush (mid-Jan to mid-Apr)
        Q4: Chaitra-Baishakh (mid-Apr to mid-Jul)
        
        Approximate Gregorian mapping:
        """
        # Parse fiscal year (e.g., "2080-2081" or "2081")
        try:
            fy_start = int(fiscal_year.split("-")[0]) if "-" in fiscal_year else int(fiscal_year)
        except (ValueError, IndexError):
            return None, None

        # Approximate Gregorian dates for Nepali fiscal quarters
        quarter_map = {
            1: (f"{fy_start - 57}-07-16", f"{fy_start - 57}-10-17"),  # Shrawan-Bhadra
            2: (f"{fy_start - 57}-10-18", f"{fy_start - 56}-01-14"),  # Ashwin-Kartik
            3: (f"{fy_start - 56}-01-15", f"{fy_start - 56}-04-13"),  # Mangsir-Poush
            4: (f"{fy_start - 56}-04-14", f"{fy_start - 56}-07-15"),  # Chaitra-Baishakh
        }
        return quarter_map.get(quarter, (None, None))

    def _calculate_volatility(self, closes: list) -> Optional[float]:
        """Calculate standard deviation of daily returns."""
        if len(closes) < 2:
            return None
        returns = []
        for i in range(1, len(closes)):
            if closes[i-1]:
                ret = (closes[i] - closes[i-1]) / closes[i-1]
                returns.append(ret)
        if not returns:
            return None
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5

    def get_latest(
        self,
        session: "Session",
        symbol: str,
        limit: int = 4,
    ) -> list:
        """Get latest quarterly analyses for a symbol."""
        analyses = session.scalars(
            select(QuarterlyAnalysis)
            .where(QuarterlyAnalysis.symbol == symbol.upper())
            .order_by(QuarterlyAnalysis.fiscal_year.desc(), QuarterlyAnalysis.quarter.desc())
            .limit(limit)
        ).all()
        return [self._to_dict(a) for a in analyses]

    def get_by_fiscal_year(
        self,
        session: "Session",
        symbol: str,
        fiscal_year: str,
    ) -> list:
        """Get all quarters for a fiscal year."""
        analyses = session.scalars(
            select(QuarterlyAnalysis)
            .where(
                QuarterlyAnalysis.symbol == symbol.upper(),
                QuarterlyAnalysis.fiscal_year == fiscal_year,
            )
            .order_by(QuarterlyAnalysis.quarter)
        ).all()
        return [self._to_dict(a) for a in analyses]

    def _to_dict(self, analysis: "QuarterlyAnalysis") -> dict:
        return {
            "symbol": analysis.symbol,
            "fiscal_year": analysis.fiscal_year,
            "quarter": analysis.quarter,
            "quarterly_return": analysis.quarterly_return,
            "high": analysis.high,
            "low": analysis.low,
            "avg_volume": analysis.avg_volume,
            "volatility": analysis.volatility,
            "revenue": analysis.revenue,
            "net_profit": analysis.net_profit,
            "eps": analysis.eps,
            "book_value_per_share": analysis.book_value_per_share,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        }