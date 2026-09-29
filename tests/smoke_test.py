#!/usr/bin/env python
"""End-to-end smoke tests for Phase 5 features.

Run against a running server: python tests/smoke_test.py

Not a unit test: it needs a live server on 127.0.0.1:8000 (and NEPSE to be
reachable for the health check), so pytest must not collect it.
"""

import pytest

pytestmark = pytest.mark.skip(reason="E2E script; run against a live server: python tests/smoke_test.py")

import asyncio
import httpx
import json
import sys
import os

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
TIMEOUT = 30.0

async def test_health():
    """Test basic health endpoints."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # Root
        r = await client.get("/")
        assert r.status_code in (200, 404), f"Root failed: {r.status_code}"
        
        # Health
        r = await client.get("/api/nepse/health")
        assert r.status_code == 200, f"Health failed: {r.status_code}"
        data = r.json()
        assert data.get("success") == True
        assert data.get("data", {}).get("status") == "available"
        print("[OK] Health endpoints work")

async def test_ai_endpoints():
    """Test AI endpoints with fake client."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # AI status (public endpoint)
        r = await client.get("/api/ai/status/public")
        assert r.status_code == 200, f"AI status failed: {r.status_code}"
        data = r.json()
        assert "configured" in data
        assert "provider" in data
        assert data["configured"] == False  # fake mode
        print("[OK] AI status endpoint works")
        
        # AI ask (requires auth - will fail without token, but we test structure)
        r = await client.post("/api/ai/ask", json={
            "question": "What is NEPSE?",
            "symbols": [],
            "data_sources": [],
            "privacy_consent": True
        })
        # Should be 401 without auth, but endpoint should exist
        assert r.status_code in (200, 401, 422), f"AI ask failed: {r.status_code}"
        print("[OK] AI ask endpoint exists")

async def test_realtime_endpoints():
    """Test real-time WebSocket endpoints exist."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        r = await client.get("/api/realtime/status")
        assert r.status_code == 200, f"Realtime status failed: {r.status_code}"
        data = r.json()
        assert "running" in data
        print("[OK] Real-time status endpoint works")

async def test_portfolio_ai_review():
    """Test Portfolio AI Review endpoint structure."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # Need auth, but test that endpoint exists
        r = await client.post("/api/portfolio/test-portfolio/ai-review", json={
            "question": "How is my portfolio doing?",
            "privacy_consent": True
        })
        # Should be 401 without auth
        assert r.status_code in (401, 422), f"Portfolio AI review failed: {r.status_code}"
        print("[OK] Portfolio AI review endpoint exists")

async def test_fundamentals_import():
    """Test fundamentals import endpoint structure."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # Need admin auth, but test endpoint exists
        r = await client.post("/api/fundamentals/import", files={"file": ("test.csv", b"symbol,fiscal_year,quarter\nNABIL,2083/84,1", "text/csv")})
        # Should be 401 without admin auth
        assert r.status_code in (401, 422), f"Fundamentals import failed: {r.status_code}"
        print("[OK] Fundamentals import endpoint exists")

async def test_core_endpoints():
    """Test core Phase 1-4 endpoints still work."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        endpoints = [
            "/api/archive/coverage",
            "/api/analytics/indicators/NABIL",
            "/api/reference/securities",
            "/api/reference/sectors",
            "/api/analytics/screener",
            "/api/analytics/visualisation/heatmap",
            "/api/reference/companies/NABIL",
            "/api/analytics/quarterly/NABIL",
            "/api/news/",
            "/api/calculator/buy-sell",
        ]
        
        for ep in endpoints:
            r = await client.get(ep) if "buy-sell" not in ep else await client.post(ep, json={"quantity": 100, "price": 500, "side": "buy"})
            assert r.status_code in (200, 401, 422), f"{ep} failed: {r.status_code}"
        
        print(f"[OK] {len(endpoints)} core endpoints accessible")

async def main():
    print(f"Running smoke tests against {BASE_URL}")
    print("=" * 50)
    
    try:
        await test_health()
        await test_ai_endpoints()
        await test_realtime_endpoints()
        await test_portfolio_ai_review()
        await test_fundamentals_import()
        await test_core_endpoints()
        
        print("=" * 50)
        print("All smoke tests PASSED")
        return 0
    except Exception as e:
        print(f"SMOKE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))