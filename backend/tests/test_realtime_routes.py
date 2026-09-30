"""Tests for the realtime cache readout endpoints.

Hermetic: the global RealTimeService singleton is replaced with a stub whose
price cache is pre-seeded, so no server, no NEPSE calls, no background tasks.
The singleton lives on `app.realtime.service`, and the routes resolve their
dependency through `get_realtime_service()`, which returns the module global
when set - that is the seam these tests patch (patching the routes module
would not work: FastAPI captured the dependency callable at import time).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from app.main import app
from app.realtime import service as realtime_service_module
from app.realtime.service import PriceUpdate


class _StubRealtime:
    """Just the two read accessors the REST endpoints use."""

    def __init__(self, cache: dict[str, PriceUpdate]):
        self._cache = cache

    def get_cached_price(self, symbol: str):
        return self._cache.get(symbol.upper())

    def get_all_cached_prices(self):
        return dict(self._cache)


def _update(symbol: str, ltp: float, change: float, minute: int) -> PriceUpdate:
    return PriceUpdate(
        symbol=symbol,
        ltp=ltp,
        change=change,
        change_pct=change / ltp * 100 if ltp else 0.0,
        volume=12_345,
        turnover=1_234_567.0,
        high=ltp + 2,
        low=ltp - 2,
        timestamp=datetime(2026, 9, 30, 10, minute),
    )


@pytest.fixture
def seeded(monkeypatch):
    cache = {
        "NABIL": _update("NABIL", 566.0, -1.0, 5),
        "HPC": _update("HPC", 501.0, 6.36, 6),
    }
    monkeypatch.setattr(
        realtime_service_module, "_realtime_service", _StubRealtime(cache)
    )
    return cache


@pytest.fixture
def empty(monkeypatch):
    monkeypatch.setattr(
        realtime_service_module, "_realtime_service", _StubRealtime({})
    )


def make_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


async def test_prices_lists_seeded_quotes(seeded):
    async with make_client() as client:
        resp = await client.get("/api/realtime/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert [q["symbol"] for q in body["quotes"]] == ["HPC", "NABIL"]  # sorted
    nabil = body["quotes"][1]
    assert nabil["ltp"] == 566.0
    assert nabil["change"] == -1.0
    assert body["as_of"] == "2026-09-30T10:06:00"  # max timestamp


async def test_prices_symbol_filter(seeded):
    async with make_client() as client:
        resp = await client.get("/api/realtime/prices?symbols=nabil")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["quotes"][0]["symbol"] == "NABIL"
    assert body["requested"] == ["NABIL"]


async def test_prices_empty_cache_is_ok_not_error(empty):
    async with make_client() as client:
        resp = await client.get("/api/realtime/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quotes"] == []
    assert body["count"] == 0
    assert body["as_of"] is None


async def test_price_single_symbol(seeded):
    async with make_client() as client:
        resp = await client.get("/api/realtime/prices/NABIL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "NABIL"
    assert body["ltp"] == 566.0
    assert body["timestamp"] == "2026-09-30T10:05:00"


async def test_price_unknown_symbol_404(seeded):
    async with make_client() as client:
        resp = await client.get("/api/realtime/prices/ZZZZ")
    assert resp.status_code == 404
