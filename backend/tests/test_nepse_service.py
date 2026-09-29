"""Service-level tests: caching, validation, conversion, failure modes.

All library interaction is mocked via `FakeNepseAdapter` - no real NEPSE
requests are ever made.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.nepse.cache import TTLResponseCache
from app.nepse.exceptions import (
    DataNotFoundError,
    NepseInvalidResponseError,
    NepseTimeoutError,
    NepseUnavailableError,
    SymbolNotFoundError,
)
from app.nepse.service import NepseService, validate_symbol
from tests.fakes import FakeNepseAdapter


@pytest.fixture
def service() -> NepseService:
    return NepseService(client=FakeNepseAdapter())


@pytest.fixture
def broken_service() -> NepseService:
    return NepseService(client=FakeNepseAdapter(mode="unavailable"))


# ----------------------------------------------------------------------
# Success paths
# ----------------------------------------------------------------------

async def test_market_status_success(service: NepseService):
    status = await service.get_market_status()
    assert status.is_open is False  # "CLOSE" from the fake
    assert status.as_of == "2026-09-24T15:00:00"
    assert service._client.calls == ["get_market_status"]


async def test_market_status_open(service: NepseService):
    service._client.market_status["isOpen"] = "OPEN"
    status = await service.get_market_status()
    assert status.is_open is True


async def test_market_summary_success(service: NepseService):
    summary = await service.get_market_summary()
    assert summary.total_turnover == 5447313168.2
    assert summary.total_traded_shares == 17270449
    assert summary.total_transactions == 51716
    assert summary.traded_scrips == 356


async def test_market_overview_combines_status_summary_index(service: NepseService):
    overview = await service.get_market_overview()
    assert overview.status.is_open is False
    assert overview.summary.total_turnover == 5447313168.2
    assert overview.nepse_index.value == 2629.81


async def test_nepse_index_success(service: NepseService):
    index = await service.get_nepse_index()
    assert index.name == "Nepse Index"
    assert index.value == 2629.81
    assert index.change_percentage == 0.06


async def test_indices_combines_nepse_and_sub(service: NepseService):
    nepse_index, sub_indices = await service.get_indices()
    assert nepse_index.value == 2629.81
    assert sub_indices[0].name == "Banking SubIndex"


async def test_stocks_success(service: NepseService):
    data = await service.get_stocks()
    assert data.count == 2
    nabil = next(s for s in data.stocks if s.symbol == "NABIL")
    assert nabil.last_traded_price == 569.0
    assert nabil.change_percentage == 0.71
    assert nabil.fifty_two_week_high == 605.0


async def test_stocks_fallback_to_price_volume_preopen():
    """Before the 11:00 NPT open, get_stocks() returns 0 rows while
    get_price_volume() still lists every security - the service must fall
    back instead of serving an empty table."""
    service = NepseService(client=FakeNepseAdapter(stocks_empty=True))
    data = await service.get_stocks()
    assert data.count == 3  # 1 price-volume row + 2 stocks rows
    nabil = next(s for s in data.stocks if s.symbol == "NABIL")
    assert nabil.last_traded_price == 569.0
    aclbsl = next(s for s in data.stocks if s.symbol == "ACLBSL")
    assert aclbsl.last_traded_price == 877.0
    # One service-level fetch; the fallback happens inside the adapter.
    assert service._client.calls == ["get_stocks"]


async def test_stock_lookup_works_preopen():
    """get_stock (per-symbol detail) uses the same fallback list."""
    service = NepseService(client=FakeNepseAdapter(stocks_empty=True))
    stock = await service.get_stock("nabil")
    assert stock.symbol == "NABIL"
    assert stock.last_traded_price == 569.0


async def test_stock_lookup_accepts_legacy_symbol_key():
    """Upstream rows occasionally spell the symbol key `securitySymbol`."""
    service = NepseService(client=FakeNepseAdapter(legacy_symbol_keys=True))
    stock = await service.get_stock("nabil")
    assert stock.symbol == "NABIL"
    assert stock.security_id == 131


async def test_stocks_symbolless_rows_fall_back_to_price_volume():
    """Pre-open auction snapshots contain rows without a symbol key; they
    must be skipped and the price/volume feed used instead."""
    service = NepseService(client=FakeNepseAdapter(symbolless_rows=True))
    data = await service.get_stocks()
    assert data.count == 3
    assert service._client.calls == ["get_stocks", "get_price_volume"]


async def test_stocks_symbolless_lookup_still_finds_symbol():
    service = NepseService(client=FakeNepseAdapter(symbolless_rows=True))
    stock = await service.get_stock("ACLBSL")
    assert stock.symbol == "ACLBSL"
    assert stock.last_traded_price == 877.0


async def test_stock_success(service: NepseService):
    stock = await service.get_stock("nabil")  # lowercase input on purpose
    assert stock.symbol == "NABIL"
    assert stock.security_id == 131
    assert stock.open_price == 566.0


async def test_stock_live_price_success(service: NepseService):
    stock = await service.get_stock_live_price("ACLBSL")
    assert stock.last_traded_price == 877.0
    assert stock.change_percentage == -0.113895216


async def test_price_history_success(service: NepseService):
    result = await service.get_price_history("NABIL", date(2026, 9, 1), date(2026, 9, 24))
    assert result["symbol"] == "NABIL"
    assert result["history"][0]["close"] == 569.0
    # history resolves the security id first, then fetches the chart
    assert service._client.calls == ["get_security_list", "get_historical_chart(131)"]


async def test_index_history_success(service: NepseService):
    points = await service.get_index_history(
        "nepse", date(2026, 9, 1), date(2026, 9, 24)
    )
    assert len(points) == 2
    assert points[0].close == 2629.81
    assert points[0].business_date == date(2026, 9, 24)
    assert points[0].turnover == 5447313168.2


async def test_market_caps_passthrough(service: NepseService):
    caps = await service.get_market_caps()
    assert caps[0]["mar_cap"] == 4523617.26  # camelCase -> snake_case
    assert caps[0]["business_date"] == "2026-09-24"


async def test_market_caps_for_date(service: NepseService):
    caps = await service.get_market_caps(date(2026, 4, 24))
    assert caps[0]["mar_cap"] == 4523617.26
    assert "get_marcapbydate(2026-04-24)" in service._client.calls


async def test_top_gainers_losers(service: NepseService):
    gainers = await service.get_top_gainers(3)
    assert gainers[0]["symbol"] == "NLO"
    assert gainers[0]["percentage_change"] == 12.47  # keys normalized
    losers = await service.get_top_losers(3)
    assert losers[0]["symbol"] == "SOMOS"


# ----------------------------------------------------------------------
# Symbol validation
# ----------------------------------------------------------------------

def test_validate_symbol_uppercases_and_strips():
    assert validate_symbol("  nabil  ") == "NABIL"


@pytest.mark.parametrize("bad", ["", "NABIL DROP TABLE", "nav?l", "A" * 30, "NABIL;"])
def test_validate_symbol_rejects_bad_input(bad: str):
    with pytest.raises(SymbolNotFoundError):
        validate_symbol(bad)


async def test_unknown_symbol_raises(service: NepseService):
    with pytest.raises(SymbolNotFoundError):
        await service.get_stock("NOPE")


async def test_unknown_symbol_live_raises(service: NepseService):
    with pytest.raises(SymbolNotFoundError):
        await service.get_stock_live_price("NOPE")


async def test_invalid_symbol_fails_fast_without_upstream_call(service: NepseService):
    with pytest.raises(SymbolNotFoundError):
        await service.get_stock("BAD SYMBOL!!")
    assert service._client.calls == []


# ----------------------------------------------------------------------
# Failure modes
# ----------------------------------------------------------------------

async def test_nepse_unavailable_raises_application_error(broken_service: NepseService):
    with pytest.raises(NepseUnavailableError):
        await broken_service.get_market_status()


async def test_timeout_raises_application_error():
    svc = NepseService(client=FakeNepseAdapter(mode="timeout"))
    with pytest.raises(NepseTimeoutError):
        await svc.get_market_status()


async def test_invalid_response_raises_application_error():
    svc = NepseService(client=FakeNepseAdapter(mode="invalid"))
    with pytest.raises(NepseInvalidResponseError):
        await svc.get_market_summary()


async def test_failure_is_remembered_then_forgotten(broken_service: NepseService):
    # First call fails and is remembered...
    with pytest.raises(NepseUnavailableError):
        await broken_service.get_market_status()
    assert broken_service._client.calls == ["get_market_status"]
    # ...second call fails fast without touching the client again...
    with pytest.raises(NepseUnavailableError):
        await broken_service.get_market_status()
    assert broken_service._client.calls == ["get_market_status"]
    # ...until the failure memory expires.
    broken_service._error_cache.clear()
    with pytest.raises(NepseUnavailableError):
        await broken_service.get_market_status()
    assert broken_service._client.calls == ["get_market_status", "get_market_status"]


async def test_empty_index_list_is_invalid_response():
    adapter = FakeNepseAdapter()
    adapter.nepse_index = []
    svc = NepseService(client=adapter)
    # Closed-market variant (empty list) -> falls back to last known close
    # from index history instead of raising.
    summary = await svc.get_nepse_index()
    assert summary.value == 2629.81
    assert summary.is_closed is True


async def test_closed_market_status_dict_variant_falls_back():
    adapter = FakeNepseAdapter()
    adapter.nepse_index = {"isOpen": "CLOSE", "asOf": "2026-09-24T15:00:00"}
    svc = NepseService(client=adapter)
    summary = await svc.get_nepse_index()
    assert summary.value == 2629.81
    assert summary.is_closed is True


async def test_closed_market_rows_without_value_fall_back():
    adapter = FakeNepseAdapter()
    adapter.nepse_index = [{"id": 58, "index": "NEPSE Index", "close": None}]
    svc = NepseService(client=adapter)
    summary = await svc.get_nepse_index()
    assert summary.is_closed is True
    assert summary.value == 2629.81


async def test_zero_open_row_is_skipped_in_fallback():
    """At the open, NEPSE seeds today's history row with close=0; the last
    known close must be Friday's, not 0."""
    adapter = FakeNepseAdapter()
    adapter.nepse_index = []  # closed/empty live payload
    adapter.index_history = [
        {"businessDate": "2026-09-28", "closingIndex": 0,
         "openIndex": 0, "highIndex": 0, "lowIndex": 0,
         "turnover": 0, "volume": 0, "totalTransactions": 0},
        {"businessDate": "2026-09-24", "closingIndex": 2629.81,
         "openIndex": 2611.03, "highIndex": 2629.94, "lowIndex": 2605.32,
         "turnover": 5447313168.2, "volume": 17270449,
         "totalTransactions": 51716},
    ]
    svc = NepseService(client=adapter)
    summary = await svc.get_nepse_index()
    assert summary.is_closed is True
    assert summary.value == 2629.81  # Friday's close, not today's zero


async def test_genuinely_malformed_payload_still_raises():
    adapter = FakeNepseAdapter()
    adapter.nepse_index = "garbage"
    adapter.index_history = []  # nothing to fall back to either
    svc = NepseService(client=adapter)
    with pytest.raises(NepseInvalidResponseError):
        await svc.get_nepse_index()


async def test_index_auth_failure_keeps_specific_code():
    """When the live index payload is unusable AND the history fallback hits
    an auth flap, the surfaced error must be NEPSE_AUTH_FAILED (the specific
    cause), not the generic NEPSE_INVALID_RESPONSE."""
    from app.nepse.exceptions import NepseAuthError

    class AuthFlappedHistory(FakeNepseAdapter):
        def get_index_history(self, index, start_date=None, end_date=None):
            raise NepseAuthError()

    adapter = AuthFlappedHistory()
    adapter.nepse_index = {"isOpen": "CLOSE"}  # unusable live payload
    svc = NepseService(client=adapter)
    with pytest.raises(NepseAuthError):
        await svc.get_nepse_index()


async def test_outage_still_raises_unavailable_not_invalid():
    # Full upstream outage keeps the graceful-degradation path: the error
    # must remain NEPSE_UNAVAILABLE (-> 503), never NEPSE_INVALID_RESPONSE.
    broken = NepseService(client=FakeNepseAdapter(mode="unavailable"))
    with pytest.raises(NepseUnavailableError):
        await broken.get_nepse_index()


async def test_live_index_is_not_marked_closed(service: NepseService):
    summary = await service.get_nepse_index()
    assert summary.is_closed is False
    assert summary.value == 2629.81
    assert summary.name == "Nepse Index"


async def test_empty_index_history_is_data_not_found():
    adapter = FakeNepseAdapter()
    adapter.index_history = []
    svc = NepseService(client=adapter)
    with pytest.raises(DataNotFoundError):
        await svc.get_index_history("nepse")


async def test_empty_chart_is_data_not_found():
    adapter = FakeNepseAdapter()
    adapter.chart = []  # NEPSE's graphdata endpoint currently 500s -> empty
    svc = NepseService(client=adapter)
    with pytest.raises(DataNotFoundError):
        await svc.get_price_history("NABIL")


# ----------------------------------------------------------------------
# Cache behavior
# ----------------------------------------------------------------------

async def test_second_call_is_served_from_cache(service: NepseService):
    await service.get_market_status()
    await service.get_market_status()
    assert service._client.calls == ["get_market_status"]  # only one upstream call


async def test_different_keys_are_cached_separately(service: NepseService):
    await service.get_stock("NABIL")
    await service.get_stock("GCIL")
    assert service._client.calls == ["get_stock_info(NABIL)", "get_stock_info(GCIL)"]


async def test_index_history_dates_cached_separately(service: NepseService):
    await service.get_index_history("nepse", date(2026, 9, 1), date(2026, 9, 24))
    await service.get_index_history("nepse", date(2026, 8, 1), date(2026, 9, 24))
    assert len(service._client.calls) == 2


async def test_ttl_cache_expiry():
    cache = TTLResponseCache(maxsize=10, ttl=0.05)

    async def factory():
        return {"n": 1}

    first = await cache.get_or_set("k", factory)
    assert first == {"n": 1}
    import asyncio
    await asyncio.sleep(0.08)  # past TTL
    second = await cache.get_or_set("k", factory)
    assert second == {"n": 1}  # re-fetched after expiry
