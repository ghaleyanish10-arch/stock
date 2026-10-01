"""Tests for B2/B3 - CSV Import with dry-run, validation, duplicate detection, and replay."""

import uuid
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from app.main import app


class TestCSVImport:
    """Tests for CSV transaction import."""

    @pytest.fixture(autouse=True)
    async def _setup(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        unique = uuid.uuid4().hex[:8]
        self.user = {"email": f"csv_{unique}@test.com", "password": "pass123"}
        await self.client.post("/api/auth/register", json=self.user)
        r = await self.client.post("/api/auth/login", json=self.user)
        self.token = r.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        r = await self.client.post("/api/portfolio", json={"name": "Test Portfolio"}, headers=self.headers)
        self.portfolio_id = r.json()["id"]

        from app.db.session import SessionLocal
        from app.db.models import Security
        with SessionLocal() as session:
            for sym in ["NABIL", "NIC"]:
                if not session.get(Security, sym):
                    session.add(Security(symbol=sym, name=f"{sym} Bank", sector_code="Commercial Banks"))
            session.commit()

    async def teardown_method(self):
        await self.client.aclose()

    async def test_get_import_template(self):
        """Get CSV import template."""
        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/import/template", headers=self.headers)
        assert r.status_code == 200
        assert "template" in r.json()
        assert "symbol,side,quantity,price,trade_date,fees,note" in r.json()["template"]

    async def test_preview_valid_csv(self):
        """Preview valid CSV import (dry-run)."""
        csv_content = """symbol,side,quantity,price,trade_date,fees,note
NABIL,buy,100,500,2026-01-15,10,First buy
NIC,buy,50,800,2026-01-20,5,Second buy
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import/preview", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total_rows"] == 2
        assert data["valid_rows"] == 2
        assert data["invalid_rows"] == 0
        assert data["duplicate_rows"] == 0
        assert data["imported_count"] == 0
        assert data["dry_run"] is True
        assert len(data["rows"]) == 2
        assert all(r["status"] == "valid" for r in data["rows"])

    async def test_preview_invalid_csv(self):
        """Preview CSV with invalid rows."""
        csv_content = """symbol,side,quantity,price,trade_date,fees,note
NABIL,buy,100,500,2026-01-15,10,Valid
INVALID,buy,100,500,2026-01-15,10,Invalid symbol
NABIL,invalid_side,100,500,2026-01-15,10,Invalid side
NABIL,buy,-10,500,2026-01-15,10,Negative quantity
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import/preview", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total_rows"] == 4
        assert data["valid_rows"] == 1
        assert data["invalid_rows"] == 3
        assert data["rows"][0]["status"] == "valid"
        assert data["rows"][1]["status"] == "invalid"
        assert data["rows"][2]["status"] == "invalid"
        assert data["rows"][3]["status"] == "invalid"

    async def test_preview_duplicate_detection(self):
        """Preview detects duplicates against existing transactions."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )

        csv_content = """symbol,side,quantity,price,trade_date,fees,note
NABIL,buy,100,500,2026-01-15,10,Duplicate
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import/preview", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["duplicate_rows"] == 1
        assert data["rows"][0]["status"] == "duplicate"

    async def test_preview_insufficient_holdings(self):
        """Preview flags sells above held quantity."""
        csv_content = """symbol,side,quantity,price,trade_date,fees,note
NABIL,sell,100,550,2026-01-20,10,Sell without holdings
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import/preview", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["insufficient_holdings_rows"] == 1
        assert data["rows"][0]["status"] == "insufficient_holdings"

    async def test_import_valid_csv(self):
        """Import valid CSV creates transactions and replays."""
        csv_content = """symbol,side,quantity,price,trade_date,fees,note
NABIL,buy,100,500,2026-01-15,10,First buy
NABIL,buy,50,600,2026-01-20,5,Second buy
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["imported_count"] == 2
        assert data["dry_run"] is False

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        holdings = r.json()["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["quantity"] == 150
        assert abs(holdings[0]["avg_cost"] - 533.43) < 0.1

    async def test_import_with_sell(self):
        """Import with sell after buy."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )

        csv_content = """symbol,side,quantity,price,trade_date,fees,note
NABIL,sell,30,550,2026-01-20,5,Partial sell
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["imported_count"] == 1

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        holdings = r.json()["holdings"]
        assert holdings[0]["quantity"] == 70

    async def test_import_row_limit(self):
        """Import respects row limit."""
        rows = []
        for i in range(10001):
            rows.append(f"NABIL,buy,1,500,2026-01-{(i%28)+1:02d},0,Row {i}")
        csv_content = "symbol,side,quantity,price,trade_date,fees,note\n" + "\n".join(rows)

        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import/preview", files=files, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total_rows"] <= 10000

    async def test_import_missing_columns(self):
        """Import fails with missing required columns."""
        csv_content = """symbol,side,quantity
NABIL,buy,100
"""
        files = {"file": ("test.csv", csv_content, "text/csv")}
        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/import/preview", files=files, headers=self.headers)
        assert r.status_code == 400
        assert "Missing required columns" in r.text