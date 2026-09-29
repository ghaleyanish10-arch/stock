"""Application-level NEPSE service.

The rest of the application (routes, background jobs, ...) talks ONLY to
`NepseService`. It:

    * implements the operations the application actually needs
    * caches responses to avoid hammering NEPSE
    * converts raw library payloads into internal models (`models.py`)
    * raises application-level errors (`exceptions.py`)
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from cachetools import TTLCache

from app.config import settings
from app.nepse.cache import TTLResponseCache
from app.nepse.client import NepseClientAdapter
from app.nepse.exceptions import (
    DataNotFoundError,
    NepseInvalidResponseError,
    NepseServiceError,
    SymbolNotFoundError,
)
from app.nepse.models import (
    IndexPoint,
    IndexSummary,
    MarketOverview,
    MarketStatus,
    MarketSummary,
    Stock,
    StockListResponse,
)

logger = logging.getLogger(__name__)

# NEPSE symbols are short uppercase alphanumeric codes (e.g. NABIL, NICA,
# UPPER, SHINE); hyphens appear in a few debenture/mutual-fund symbols.
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,15}$")


def _num(value: Any) -> Optional[float]:
    """Best-effort numeric coercion; library payloads mix str/int/float."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    num = _num(value)
    return int(num) if num is not None else None


def validate_symbol(symbol: str) -> str:
    """Uppercase and validate a user-supplied symbol; raise on nonsense."""
    cleaned = (symbol or "").strip().upper()
    if not SYMBOL_RE.fullmatch(cleaned):
        raise SymbolNotFoundError()
    return cleaned


class _PendingError:
    """Cache marker that re-raises a stored error when read."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def raise_stored(self) -> None:
        raise self._error


class NepseService:
    """One responsibility: retrieve and normalize NEPSE data."""

    def __init__(self, client: Optional[NepseClientAdapter] = None) -> None:
        # Defaults to the process-wide adapter rather than minting a new one, so
        # a service built anywhere in the app still shares a single upstream
        # session and rate limiter. Tests pass their own fake explicitly.
        if client is None:
            from app.nepse.registry import get_adapter

            client = get_adapter()
        self._client = client
        self._cache = TTLResponseCache(
            maxsize=settings.cache_maxsize, ttl=settings.cache_ttl
        )
        # Remembers recent failures so a down NEPSE is not hammered.
        self._error_cache: TTLCache = TTLCache(maxsize=64, ttl=settings.error_ttl)
        self._started = False
        self._start_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        async with self._start_lock:
            if not self._started:
                await self._client.start()
                self._started = True

    async def close(self) -> None:
        await self._client.close()
        self._started = False

    async def health_check(self) -> bool:
        """Cheap liveness probe: no NEPSE call, just client readiness."""
        await self.start()
        return self._client.raw is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _cached(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        """Cache successful results; also remember failures for error_ttl.

        Failure memory turns an outage into fast, uniform errors instead of
        one slow timeout per request. Failures expire after `error_ttl`,
        after which the next request retries NEPSE.
        """
        marker = self._error_cache.get(key)
        if marker is not None:
            logger.info("NEPSE cache hit (recent failure): %s", key)
            marker.raise_stored()

        logger.info("NEPSE cache miss: %s", key)
        try:
            value = await self._cache.get_or_set(key, factory)
        except Exception as exc:
            self._error_cache[key] = _PendingError(exc)
            raise
        return value

    async def _resolve_security_id(self, symbol: str) -> int:
        """Map a symbol to NEPSE's numeric security id via the security list."""
        symbol = validate_symbol(symbol)

        async def _fetch() -> int:
            securities = await self._client.call(
                "get_security_list", self._client.get_security_list
            )
            for item in securities or []:
                if (item.get("symbol") or "").upper() == symbol:
                    sid = _int(item.get("id") or item.get("securityID"))
                    if sid:
                        return sid
            raise SymbolNotFoundError()

        return await self._cached(f"secid:{symbol}", _fetch)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_market_status(self) -> MarketStatus:
        async def _fetch() -> MarketStatus:
            payload = await self._client.call(
                "get_market_status", self._client.get_market_status
            )
            # Payload: {"isOpen": "OPEN"|"CLOSE", "asOf": ...}
            return MarketStatus(
                is_open=(payload or {}).get("isOpen") == "OPEN",
                as_of=(payload or {}).get("asOf"),
            )

        return await self._cached("market_status", _fetch)

    async def get_market_summary(self) -> MarketSummary:
        async def _fetch() -> MarketSummary:
            payload = await self._client.call(
                "get_market_summary", self._client.get_market_summary
            )
            # Payload: [{"detail": "Total Turnover Rs:", "value": ...}, ...]
            by_detail = {
                (item.get("detail") or "").strip().rstrip(":").lower(): item.get("value")
                for item in (payload or [])
                if isinstance(item, dict)
            }

            def _pick(*keywords: str) -> Any:
                for key, value in by_detail.items():
                    if all(k in key for k in keywords):
                        return value
                return None

            return MarketSummary(
                total_turnover=_num(_pick("turnover")),
                total_traded_shares=_int(_pick("traded shares")),
                total_transactions=_int(_pick("transactions")),
                traded_scrips=_int(_pick("scrips")),
            )

        return await self._cached("market_summary", _fetch)

    async def get_market_overview(self) -> MarketOverview:
        """Status plus latest summary and NEPSE index; missing pieces degrade."""
        status = await self.get_market_status()
        summary: Optional[MarketSummary] = None
        index: Optional[IndexSummary] = None
        try:
            summary = await self.get_market_summary()
        except NepseServiceError:
            logger.warning("Market summary unavailable; returning status only")
        try:
            index = await self.get_nepse_index()
        except NepseServiceError:
            logger.warning("NEPSE index unavailable; returning without it")
        return MarketOverview(status=status, summary=summary, nepse_index=index)

    async def get_nepse_index(self) -> IndexSummary:
        """NEPSE index value, handling closed-market payload variants.

        When the market is closed NEPSE serves one of several known shapes:
        a status dict ({"isOpen": ...}), an empty list, or rows without a
        live value. In those cases we fall back to the last known close
        from index history and flag it with is_closed=True, rather than
        reporting the payload as invalid.
        """
        async def _fetch() -> IndexSummary:
            payload = await self._client.call(
                "get_nepse_index", self._client.get_nepse_index
            )
            summary = self._extract_nepse_index(payload)
            if summary is not None:
                return summary

            logger.warning(
                "NEPSE index payload looks closed/empty; falling back to "
                "last known close (payload type: %s)",
                type(payload).__name__,
            )
            return await self._last_known_index()

        return await self._cached("nepse_index", _fetch)

    @staticmethod
    def _extract_nepse_index(payload: Any) -> Optional[IndexSummary]:
        """Pull the NEPSE index out of a live-shape payload; None if absent."""
        # Closed variant: a plain status dict instead of the index list.
        if isinstance(payload, dict):
            return None
        if not isinstance(payload, list) or not payload:
            return None

        chosen = next(
            (p for p in payload
             if isinstance(p, dict)
             and "nepse index" in str(p.get("index") or "").lower()),
            None,
        )
        if chosen is None:
            chosen = next((p for p in payload if isinstance(p, dict)), None)
        if chosen is None:
            return None

        value = _num(
            chosen.get("close")
            or chosen.get("currentValue")
            or chosen.get("value")
        )
        # 0 (or None) means the session just opened and NEPSE has not seeded
        # the live value yet - treat as no data so the closed-market fallback
        # kicks in with the last real close.
        if not value:
            return None  # row exists but carries no live value

        return IndexSummary(
            name=str(chosen.get("index") or "NEPSE Index"),
            value=value,
            change=_num(chosen.get("change") or chosen.get("pointChange")),
            change_percentage=_num(
                chosen.get("perChange") or chosen.get("percentageChange")
            ),
            is_closed=False,
        )

    async def _last_known_index(self) -> IndexSummary:
        """Last known close from index history, marked as closed-market data."""
        try:
            points = await self.get_index_history("nepse")
        except DataNotFoundError:
            # History is empty, so the fallback has nothing either; the
            # truthful error is still the unusable live payload, not
            # "no data for that date".
            raise NepseInvalidResponseError()
        except NepseServiceError:
            # Preserve the specific cause (auth flap, outage, timeout...).
            raise
        # NEPSE seeds the new session's history row with a zero close right
        # after the open; skip zero/None closes so "last close" really is
        # the last real close.
        latest = max(
            (p for p in points if p.business_date is not None and p.close),
            key=lambda p: p.business_date,
            default=None,
        )
        if latest is None or latest.close is None:
            raise NepseInvalidResponseError()
        return IndexSummary(
            name=latest.index_name,
            value=latest.close,
            change=None,
            change_percentage=None,
            is_closed=True,
        )

    async def get_indices(self) -> tuple[IndexSummary, list[IndexSummary]]:
        """NEPSE index plus all sector sub-indices."""
        nepse_index = await self.get_nepse_index()
        try:
            sub_indices = await self.get_sub_indices()
        except NepseServiceError:
            logger.warning("Sub-indices unavailable; returning NEPSE index only")
            sub_indices = []
        return nepse_index, sub_indices

    async def get_sub_indices(self) -> list[IndexSummary]:
        async def _fetch() -> list[IndexSummary]:
            payload = await self._client.call(
                "get_sub_indices", self._client.get_sub_indices
            )
            return [_index_summary(p) for p in (payload or [])]

        return await self._cached("sub_indices", _fetch)

    async def get_market_caps(self, day: Optional[date] = None) -> list[dict]:
        """Market capitalization series; optionally from one business date."""
        key = f"market_caps:{day.isoformat()}" if day else "market_caps"

        async def _fetch() -> list[dict]:
            caps = await self._client.call(
                f"get_marcapbydate({day.isoformat()})" if day else "get_marcapbydate",
                lambda: self._client.get_marcapbydate(
                    day.isoformat() if day else None
                ),
            )
            return [_normalize_keys(c) for c in (caps or [])]

        return await self._cached(key, _fetch)

    async def get_index_history(
        self,
        index: str = "nepse",
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[IndexPoint]:
        """Historical OHLCV for one index between optional dates."""
        label = index.strip().lower() or "nepse"
        cache_key = "index_history:%s:%s:%s" % (
            label,
            start.isoformat() if start else "-",
            end.isoformat() if end else "-",
        )

        async def _fetch() -> list[IndexPoint]:
            payload = await self._client.call(
                f"get_index_history({label})",
                lambda: self._client.get_index_history(
                    label,
                    start.isoformat() if start else None,
                    end.isoformat() if end else None,
                ),
            )
            points = [_index_point(p) for p in (payload or [])]
            if not points:
                raise DataNotFoundError()
            return points

        return await self._cached(cache_key, _fetch)

    # ------------------------------------------------------------------
    # Stocks
    # ------------------------------------------------------------------

    async def get_stocks(self) -> StockListResponse:
        async def _fetch() -> StockListResponse:
            trades = await self._client.call("get_stocks", self._client.get_stocks)
            stocks = _convert_trades(trades)
            if not stocks:
                # The library maps upstream failures (e.g. a 401 flap on the
                # live-market endpoint) to an empty list, and before the
                # 11:00 NPT open the live-market list is empty or carries
                # symbol-less auction placeholder rows. Retry via the
                # price/volume feed, which is served by a different endpoint
                # and always lists every security.
                trades = await self._client.call(
                    "get_price_volume", self._client.get_price_volume
                )
                stocks = _convert_trades(trades)
            return StockListResponse(count=len(stocks), stocks=stocks)

        return await self._cached("stocks", _fetch)

    async def get_stock(self, symbol: str) -> Stock:
        symbol = validate_symbol(symbol)

        async def _fetch() -> Stock:
            # get_stock_info filters the live market list by symbol.
            info = await self._client.call(
                f"get_stock_info({symbol})",
                lambda: self._client.get_stock_info(symbol),
            )
            if isinstance(info, list):
                info = info[0] if info else None
            if not info:
                # Pre-open the live-market list only carries a partial auction
                # snapshot; the price/volume feed lists every security.
                info = await self._client.call(
                    f"find_in_price_volume({symbol})",
                    lambda: self._client.find_in_price_volume(symbol),
                )
            if not info or not (
                info.get("symbol") or info.get("securitySymbol")
            ):
                raise SymbolNotFoundError()
            return _stock_from_trade(info)

        return await self._cached(f"stock:{symbol}", _fetch)

    async def get_stock_live_price(self, symbol: str) -> Stock:
        """Live trade data for one symbol (price/volume list filtered)."""
        symbol = validate_symbol(symbol)

        async def _fetch() -> Stock:
            trades = await self._client.call(
                "get_price_volume", self._client.get_price_volume
            )
            for trade in trades or []:
                if (trade.get("symbol") or "").upper() == symbol:
                    return _stock_from_trade(trade)
            raise SymbolNotFoundError()

        return await self._cached(f"stock_live:{symbol}", _fetch)

    async def get_price_history(
        self, symbol: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> dict:
        """Per-security price history for a date range.

        NEPSE's chart endpoint has been returning HTTP 500 (as of 2026-09),
        in which case we surface an explicit upstream error instead of
        pretending the data exists.
        """
        symbol = validate_symbol(symbol)

        async def _fetch() -> dict:
            security_id = await self._resolve_security_id(symbol)
            chart = await self._client.call(
                f"get_historical_chart({security_id})",
                lambda: self._client.get_historical_chart(
                    security_id,
                    start.isoformat() if start else None,
                    end.isoformat() if end else None,
                ),
            )
            points = [_history_point(p) for p in (chart or [])]
            if not points:
                raise DataNotFoundError()
            return {"symbol": symbol, "history": points}

        return await self._cached(
            "history:%s:%s:%s"
            % (
                symbol,
                start.isoformat() if start else "-",
                end.isoformat() if end else "-",
            ),
            _fetch,
        )

    # ------------------------------------------------------------------
    # Top movers
    # ------------------------------------------------------------------

    async def get_top_gainers(self, limit: int = 10) -> list[dict]:
        async def _fetch() -> list[dict]:
            payload = await self._client.call(
                "get_top_gainers", lambda: self._client.get_top_gainers(limit)
            )
            return [_normalize_keys(p) for p in (payload or [])]

        return await self._cached("top_gainers", _fetch)

    async def get_top_losers(self, limit: int = 10) -> list[dict]:
        async def _fetch() -> list[dict]:
            payload = await self._client.call(
                "get_top_losers", lambda: self._client.get_top_losers(limit)
            )
            return [_normalize_keys(p) for p in (payload or [])]

        return await self._cached("top_losers", _fetch)


# ----------------------------------------------------------------------
# Model converters (library dict payloads -> internal models)
# ----------------------------------------------------------------------

def _normalize_keys(payload: Any) -> Any:
    """Convert camelCase dict keys to snake_case recursively (first level of
    nesting kept as-is for raw passthrough data)."""
    if isinstance(payload, list):
        return [_normalize_keys(p) for p in payload]
    if isinstance(payload, dict):
        import re as _re

        return {
            _re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v
            for k, v in payload.items()
        }
    return payload


def _index_summary(point: Any) -> IndexSummary:
    """Convert one index snapshot from get_nepse_index / get_sub_indices."""
    get = lambda k: (point.get(k) if isinstance(point, dict) else None)  # noqa: E731
    name = get("index") or get("name") or get("indexName") or "NEPSE"
    if not isinstance(name, str):
        name = str(name)
    return IndexSummary(
        name=name,
        # Main index payload uses "close"; sub-index payloads use "currentValue".
        value=_num(get("close") or get("currentValue") or get("value")),
        change=_num(get("change") or get("pointChange")),
        change_percentage=_num(get("perChange") or get("percentageChange")),
    )


def _index_point(point: Any) -> IndexPoint:
    """Convert one row of get_index_history."""
    get = lambda k: (point.get(k) if isinstance(point, dict) else None)  # noqa: E731
    business_date = get("businessDate")
    parsed: Optional[date] = None
    if isinstance(business_date, str):
        try:
            parsed = datetime.strptime(business_date[:10], "%Y-%m-%d").date()
        except ValueError:
            parsed = None
    return IndexPoint(
        index_name=str(get("indexName") or "NEPSE"),
        business_date=parsed,
        open=_num(get("openIndex")),
        high=_num(get("highIndex")),
        low=_num(get("lowIndex")),
        close=_num(get("closingIndex")),
        turnover=_num(get("turnover")),
        volume=_num(get("volume")),
        total_transactions=_int(get("totalTransactions")),
    )


def _convert_trades(trades: Any) -> list[Stock]:
    """Convert live-market rows, skipping malformed ones.

    Pre-open auction snapshots have been seen containing rows without any
    symbol key; one bad row must not fail the whole list.
    """
    if not trades:
        return []
    stocks: list[Stock] = []
    for trade in trades:
        try:
            stocks.append(_stock_from_trade(trade))
        except NepseInvalidResponseError:
            logger.warning("Skipping malformed live-market row: %.200r", trade)
        except Exception as exc:  # defensive: never let one row fail the list
            logger.warning("Skipping live-market row (%s): %.200r", exc, trade)
    return stocks


def _stock_from_trade(trade: Any) -> Stock:
    """Convert a live-market / today-price payload dict into a Stock."""
    if not isinstance(trade, dict):
        raise NepseInvalidResponseError()

    get = lambda k: trade.get(k)  # noqa: E731
    symbol = get("symbol") or get("securitySymbol")
    if not symbol:
        raise NepseInvalidResponseError()
    return Stock(
        symbol=str(symbol).upper(),
        security_id=_int(get("securityId")) or 0,
        security_name=get("securityName"),
        open_price=_num(get("openPrice")),
        high_price=_num(get("highPrice")),
        low_price=_num(get("lowPrice")),
        close_price=_num(get("closePrice")),
        last_traded_price=_num(get("lastTradedPrice") or get("ltp")),
        previous_close=_num(get("previousClose") or get("cp")),
        change_percentage=_num(get("percentageChange")),
        total_traded_quantity=_int(get("totalTradeQuantity")),
        total_traded_value=_num(get("totalTradeValue")),
        total_trades=_int(get("totalTrades")),
        fifty_two_week_high=_num(get("fiftyTwoWeekHigh")),
        fifty_two_week_low=_num(get("fiftyTwoWeekLow")),
        last_updated=get("lastUpdatedTimeStamp") or get("businessDate"),
    )


def _history_point(point: Any) -> dict:
    """Convert one chart row (already plain dict) to a JSON-safe dict."""
    if not isinstance(point, dict):
        return {"value": str(point)}
    return _normalize_keys(point)
