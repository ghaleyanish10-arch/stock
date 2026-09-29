"""Internal application models for NEPSE data.

The `nepse-data-api` library returns plain dicts whose key names mirror
whatever NEPSE's current API returns. The rest of the application only ever
sees the models in this file, so the data source can be swapped out later
without touching anything else.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class MarketStatus(BaseModel):
    """Whether the NEPSE market is currently open."""

    is_open: bool
    as_of: Optional[str] = Field(
        default=None,
        description="Timestamp the status was reported by NEPSE (raw string).",
    )


class MarketSummary(BaseModel):
    """Turnover summary for the latest trading session."""

    business_date: Optional[date] = None
    total_turnover: Optional[float] = None
    total_traded_shares: Optional[int] = None
    total_transactions: Optional[int] = None
    traded_scrips: Optional[int] = None


class IndexSummary(BaseModel):
    """One index snapshot (value + change)."""

    name: str
    value: Optional[float] = None
    change: Optional[float] = None
    change_percentage: Optional[float] = None
    is_closed: Optional[bool] = Field(
        default=None,
        description="True when `value` is the last known close (market closed "
        "or NEPSE serving a closed-market variant), not a live tick.",
    )


class MarketOverview(BaseModel):
    """Status plus latest summary and the NEPSE index in one payload."""

    status: MarketStatus
    summary: Optional[MarketSummary] = None
    nepse_index: Optional[IndexSummary] = None


class IndexPoint(BaseModel):
    """One day of an index's history (OHLCV)."""

    index_name: str
    business_date: Optional[date] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    turnover: Optional[float] = None
    volume: Optional[float] = None
    total_transactions: Optional[int] = None


class Stock(BaseModel):
    """One security with its daily trading figures."""

    symbol: str
    security_id: int
    security_name: Optional[str] = None
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    last_traded_price: Optional[float] = None
    previous_close: Optional[float] = None
    change_percentage: Optional[float] = None
    total_traded_quantity: Optional[int] = None
    total_traded_value: Optional[float] = None
    total_trades: Optional[int] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    # Passed through as the raw string NEPSE reports.
    last_updated: Optional[str] = None


class StockListResponse(BaseModel):
    """All securities that traded today."""

    count: int
    stocks: list[Stock]
