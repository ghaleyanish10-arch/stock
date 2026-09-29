"""Endpoint tests through the ASGI app, no server and no real NEPSE calls.

We use httpx 0.18's own `ASGITransport` instead of starlette's TestClient:
the pinned old httpx predates the TestClient API. The routes' module-level
service is swapped for a fake-backed one before each request.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

import app.api.routes as routes
from app.main import app
from app.nepse.service import NepseService
from tests.fakes import FakeNepseAdapter


@pytest.fixture
def fake_service(monkeypatch):
    """Replace the routes' service with one backed by the fake adapter."""
    fake = FakeNepseAdapter()
    service = NepseService(client=fake)
    monkeypatch.setattr(routes, "service", service)
    return service


def make_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


async def test_health_available(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == {"service": "nepse", "status": "available"}


async def test_root_landing(fake_service):
    async with make_client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    # Serves the built React dashboard (HTML) when present, else JSON.
    content_type = resp.headers.get("content-type", "")
    if "html" in content_type:
        assert "<div id=\"root\">" in resp.text
    else:
        assert resp.json()["success"] is True


async def test_market_status_envelope(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["is_open"] is False
    assert body["data"]["as_of"] == "2026-09-24T15:00:00"


async def test_market_overview(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/market")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"]["is_open"] is False
    assert data["summary"]["total_turnover"] == 5447313168.2
    assert data["nepse_index"]["value"] == 2629.81


async def test_market_summary_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/market/summary")
    assert resp.status_code == 200
    assert resp.json()["data"]["total_turnover"] == 5447313168.2


async def test_indices_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/indices")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["nepse"]["value"] == 2629.81
    assert data["sub_indices"][0]["name"] == "Banking SubIndex"


async def test_index_history_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get(
            "/api/nepse/indices/nepse/history?start=2026-09-01&end=2026-09-24"
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    assert data["history"][0]["close"] == 2629.81


async def test_stocks_list(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    assert {s["symbol"] for s in data["stocks"]} == {"NABIL", "GCIL"}


async def test_stock_detail(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks/NABIL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "NABIL"
    assert data["last_traded_price"] == 569.0


async def test_stock_live_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks/ACLBSL/live")
    assert resp.status_code == 200
    assert resp.json()["data"]["last_traded_price"] == 877.0


async def test_stock_history_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get(
            "/api/nepse/stocks/NABIL/history?start=2026-09-01&end=2026-09-24"
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "NABIL"
    assert data["history"][0]["close"] == 569.0


async def test_top_gainers_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/top-gainers?limit=3")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["symbol"] == "NLO"


async def test_top_losers_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/top-losers")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["symbol"] == "SOMOS"


async def test_stock_not_found(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks/NOPE")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NEPSE_SYMBOL_NOT_FOUND"


async def test_invalid_symbol_returns_404_envelope(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks/invalid%20symbol!!")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NEPSE_SYMBOL_NOT_FOUND"


async def test_nepse_down_returns_503(monkeypatch):
    service = NepseService(client=FakeNepseAdapter(mode="unavailable"))
    monkeypatch.setattr(routes, "service", service)
    async with make_client() as client:
        resp = await client.get("/api/nepse/status")
    assert resp.status_code == 503
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NEPSE_UNAVAILABLE"


async def test_nepse_timeout_returns_504(monkeypatch):
    service = NepseService(client=FakeNepseAdapter(mode="timeout"))
    monkeypatch.setattr(routes, "service", service)
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks")
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "NEPSE_TIMEOUT"


async def test_nepse_invalid_response_returns_502(monkeypatch):
    service = NepseService(client=FakeNepseAdapter(mode="invalid"))
    monkeypatch.setattr(routes, "service", service)
    async with make_client() as client:
        resp = await client.get("/api/nepse/stocks/NABIL")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "NEPSE_INVALID_RESPONSE"


async def test_market_caps_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/market-caps")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["mar_cap"] == 4523617.26


async def test_market_caps_with_date_endpoint(fake_service):
    async with make_client() as client:
        resp = await client.get("/api/nepse/market-caps?day=2026-04-24")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["business_date"] == "2026-09-24"


async def test_history_rejects_bad_date():
    async with make_client() as client:
        resp = await client.get("/api/nepse/indices/nepse/history?start=not-a-date")
    assert resp.status_code == 422


# -- SPA fallback ------------------------------------------------------------

async def test_spa_fallback_serves_index_html_for_known_routes(fake_service):
    """Non-API routes return the React index.html when built."""
    async with make_client() as client:
        resp = await client.get("/treemap")
    assert resp.status_code == 200
    # Should serve HTML (the built React app)
    content_type = resp.headers.get("content-type", "")
    assert "html" in content_type or resp.text.startswith("{")


async def test_spa_fallback_serves_index_html_for_chart_route(fake_service):
    """Dynamic routes like /chart/NABIL return index.html for SPA routing."""
    async with make_client() as client:
        resp = await client.get("/chart/NABIL")
    assert resp.status_code == 200
    content_type = resp.headers.get("content-type", "")
    assert "html" in content_type or resp.text.startswith("{")


async def test_spa_fallback_returns_404_json_for_unknown_api_routes(fake_service):
    """Unknown /api/* routes return JSON 404, not HTML."""
    async with make_client() as client:
        resp = await client.get("/api/does/not/exist")
    assert resp.status_code == 404
    content_type = resp.headers.get("content-type", "")
    assert "json" in content_type
    assert resp.json()["detail"] == "Not found"


async def test_spa_fallback_root_returns_html_or_json(fake_service):
    """Root path returns HTML when built, else JSON."""
    async with make_client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    content_type = resp.headers.get("content-type", "")
    assert "html" in content_type or "json" in content_type
