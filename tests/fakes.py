"""Shared fakes for NEPSE tests.

The `nepse-data-api` library is replaced by `FakeNepseAdapter` - no test
ever touches the real NEPSE network API. Payload shapes mirror what the
library actually returns (verified live against nepalstock.com.np).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.nepse.client import NepseClientAdapter
from app.nepse.exceptions import SymbolNotFoundError


class _RawLibStub:
    """Stands in for the underlying nepse-data-api `Nepse` object.

    The real adapter accessors call `self.raw.<method>(use_cache=False)`;
    the stub accepts any kwargs and serves the fake's in-memory data. Using
    a stub (instead of overriding every accessor) means the adapter's own
    logic - e.g. the get_stocks() pre-open fallback - is exercised.
    """

    def __init__(self, fake: FakeNepseAdapter) -> None:
        self._fake = fake

    def get_stocks(self, **_kwargs) -> list:
        if self._fake.stocks_empty:
            return []
        if self._fake.symbolless_rows:
            return [
                {"securityId": 1, "lastTradedPrice": 100.0},
                {"securityId": 2},
            ]
        rows = [dict(item) for item in self._fake.stocks]
        if self._fake.legacy_symbol_keys:
            for row in rows:
                row["securitySymbol"] = row.pop("symbol")
        return rows

    def get_price_volume(self, **_kwargs) -> list:
        return [dict(item) for item in self._fake.price_volume]

    def get_security_list(self, **_kwargs) -> list:
        return [dict(item) for item in self._fake.security_list]


class FakeNepseAdapter(NepseClientAdapter):
    """In-memory replacement for NepseClientAdapter - no network at all.

    `call()` records operation names and routes to the configured
    behavior; tests flip `mode` to simulate failures.
    """

    def __init__(
        self,
        mode: str = "ok",
        stocks_empty: bool = False,
        legacy_symbol_keys: bool = False,
        symbolless_rows: bool = False,
    ) -> None:
        super().__init__(timeout=1)
        self.mode = mode
        self.stocks_empty = stocks_empty
        # Simulate upstream rows that use the legacy `securitySymbol` key
        # instead of `symbol`.
        self.legacy_symbol_keys = legacy_symbol_keys
        # Simulate pre-open auction snapshots: rows with no symbol key at
        # all (must be skipped, not fail the list).
        self.symbolless_rows = symbolless_rows
        self.calls: list[str] = []
        self.stocks = [
            {
                "securityId": "131",
                "securityName": "Nabil Bank Limited",
                "symbol": "NABIL",
                "openPrice": 566.0,
                "highPrice": 570.0,
                "lowPrice": 560.0,
                "closePrice": 569.0,
                "lastTradedPrice": 569.0,
                "previousClose": 565.0,
                "percentageChange": 0.71,
                "totalTradeQuantity": 70749,
                "totalTradeValue": 40123456.0,
                "totalTrades": 495,
                "fiftyTwoWeekHigh": 605.0,
                "fiftyTwoWeekLow": 410.0,
                "businessDate": "2026-09-24",
            },
            {
                "securityId": "9193",
                "securityName": "Ghorahi Cement Industry Limited",
                "symbol": "GCIL",
                "openPrice": 370.1,
                "highPrice": 409.0,
                "lowPrice": 370.0,
                "closePrice": 405.0,
                "lastTradedPrice": 405.0,
                "previousClose": 371.0,
                "percentageChange": 9.16,
                "totalTradeQuantity": 184579,
                "totalTradeValue": 73352345.0,
                "totalTrades": 1200,
            },
        ]
        self.price_volume = [
            {
                "securityId": "2790",
                "securityName": "Aarambha Chautari Laghubitta",
                "symbol": "ACLBSL",
                "totalTradeQuantity": 281,
                "lastTradedPrice": 877.0,
                "percentageChange": -0.113895216,
                "previousClose": 878.0,
                "closePrice": 877.0,
            }
        ] + self.stocks
        self.market_status = {"isOpen": "CLOSE", "asOf": "2026-09-24T15:00:00", "id": 80}
        self.market_summary = [
            {"detail": "Total Turnover Rs:", "value": 5447313168.2},
            {"detail": "Total Traded Shares", "value": 17270449.0},
            {"detail": "Total Transactions", "value": 51716.0},
            {"detail": "Total Scrips Traded", "value": 356.0},
        ]
        self.nepse_index = [{
            "index": "Nepse Index", "close": 2629.81, "change": 1.55,
            "perChange": 0.06,
        }]
        self.sub_indices = [
            {"index": "Banking SubIndex", "close": 1042.19, "change": -2.03,
             "perChange": -0.19},
        ]
        self.security_list = [
            {"id": 131, "symbol": "NABIL", "securityName": "Nabil Bank Limited"},
            {"id": 9193, "symbol": "GCIL", "securityName": "Ghorahi Cement"},
        ]
        self.security_details = {"securityDailyTradeDto": {"securityId": "131"}}
        self.marcap = [
            {"businessDate": "2026-09-24", "marCap": 4523617.26,
             "senMarCap": 2103487.81, "floatMarCap": 1532456.1,
             "senFloatMarCap": 836657.13},
            {"businessDate": "2026-09-23", "marCap": 4503363.28,
             "senMarCap": 2096523.98, "floatMarCap": 1521234.5,
             "senFloatMarCap": 830123.4},
        ]
        self.index_history = [
            {"businessDate": "2026-09-24", "closingIndex": 2629.81,
             "openIndex": 2611.03, "highIndex": 2629.94, "lowIndex": 2605.32,
             "turnover": 5447313168.2, "volume": 17270449,
             "totalTransactions": 51716},
            {"businessDate": "2026-09-23", "closingIndex": 2605.12,
             "openIndex": 2612.4, "highIndex": 2618.0, "lowIndex": 2599.1,
             "turnover": 5123456789.0, "volume": 16543210,
             "totalTransactions": 49870},
        ]
        self.chart = [
            {"businessDate": "2026-09-24", "open": 566.0, "high": 570.0,
             "low": 560.0, "close": 569.0, "volume": 70749},
        ]
        self.top_gainers = [
            {"symbol": "NLO", "ltp": 271.3, "cp": 241.22,
             "pointChange": 30.08, "percentageChange": 12.47,
             "securityName": "Nepal Lube Oil Limited", "securityId": 198},
        ]
        self.top_losers = [
            {"symbol": "SOMOS", "ltp": 100.1, "cp": 110.0,
             "pointChange": -9.9, "percentageChange": -9.0,
             "securityName": "Somoso Laghubitta", "securityId": 210},
        ]
        # Available immediately: test fixtures never await start().
        self._client = _RawLibStub(self)

    async def start(self) -> None:  # skip real client creation
        if self._client is None:
            self._client = _RawLibStub(self)

    async def close(self) -> None:
        self._client = None

    async def call(self, operation: str, fn: Callable[[], Any]) -> Any:
        self.calls.append(operation)
        if self.mode == "timeout":
            from app.nepse.exceptions import NepseTimeoutError
            raise NepseTimeoutError()
        if self.mode == "unavailable":
            from app.nepse.exceptions import NepseUnavailableError
            raise NepseUnavailableError()
        if self.mode == "invalid":
            from app.nepse.exceptions import NepseInvalidResponseError
            raise NepseInvalidResponseError()
        # The real library is synchronous; the adapter runs it via
        # asyncio.to_thread, so fn() is a plain (non-awaitable) call here.
        return fn()

    # ---- library-shaped accessors (all return plain dicts/lists) ----

    def get_market_status(self) -> dict:
        return dict(self.market_status)

    def get_market_summary(self) -> list:
        return [dict(item) for item in self.market_summary]

    def get_nepse_index(self) -> Any:
        # Pass through as-is so tests can set closed-market variant shapes
        # (dict, empty list, rows without values) as well as the live shape.
        if isinstance(self.nepse_index, list):
            return [dict(item) if isinstance(item, dict) else item for item in self.nepse_index]
        return self.nepse_index

    def get_sub_indices(self) -> list:
        return [dict(item) for item in self.sub_indices]

    def get_stocks(self) -> list:
        # Exercise the base class (pre-open fallback) via the raw stub.
        return NepseClientAdapter.get_stocks(self)

    def get_stock_info(self, symbol: str) -> Any:
        return NepseClientAdapter.get_stock_info(self, symbol)

    def get_price_volume(self) -> list:
        # The real library's use_cache=False path hits the network; the fake
        # just serves the in-memory list either way.
        return [dict(item) for item in self.price_volume]

    def get_security_details(self, security_id: int) -> dict:
        return dict(self.security_details)

    def get_security_list(self) -> list:
        return [dict(item) for item in self.security_list]

    def get_marcapbydate(self, date: str = None) -> list:
        return [dict(item) for item in self.marcap]

    def get_index_history(self, index, start_date=None, end_date=None) -> list:
        return [dict(item) for item in self.index_history]

    def get_historical_chart(self, security_id, start_date=None, end_date=None) -> list:
        return [dict(item) for item in self.chart]

    def get_top_gainers(self, limit=None) -> list:
        return [dict(item) for item in self.top_gainers]

    def get_top_losers(self, limit=None) -> list:
        return [dict(item) for item in self.top_losers]
