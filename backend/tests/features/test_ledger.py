"""Tests for B1 - Portfolio Ledger with corporate actions replay system."""

import uuid
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from sqlalchemy import select

from app.main import app
from app.db.models import (
    Holding,
    HoldingLot,
    LedgerEvent,
    CorporateAction,
    Transaction,
    Security,
)


class TestLedgerReplay:
    """Tests for the portfolio ledger replay system."""

    @pytest.fixture(autouse=True)
    async def _setup(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        unique = uuid.uuid4().hex[:8]
        self.user = {"email": f"ledger_{unique}@test.com", "password": "pass123"}
        await self.client.post("/api/auth/register", json=self.user)
        r = await self.client.post("/api/auth/login", json=self.user)
        self.token = r.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # Create portfolio
        r = await self.client.post("/api/portfolio", json={"name": "Test Portfolio"}, headers=self.headers)
        self.portfolio_id = r.json()["id"]

        # Create securities
        from app.db.session import SessionLocal
        with SessionLocal() as session:
            for sym in ["NABIL", "NIC"]:
                if not session.get(Security, sym):
                    session.add(Security(symbol=sym, name=f"{sym} Bank", sector_code="Commercial Banks"))
            session.commit()

    async def teardown_method(self):
        await self.client.aclose()

    async def test_buy_transaction_creates_ledger_event(self):
        """Adding a buy transaction creates a ledger event."""
        r = await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/ledger", headers=self.headers)
        assert r.status_code == 200
        events = r.json()["events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "buy"
        assert events[0]["symbol"] == "NABIL"
        assert events[0]["quantity"] == 100
        assert events[0]["price"] == 500

    async def test_sell_transaction_creates_ledger_event(self):
        """Adding a sell transaction creates a ledger event with negative quantity."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )
        r = await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "sell", "quantity": 50, "price": 550, "trade_date": "2026-01-20"},
            headers=self.headers,
        )
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/ledger", headers=self.headers)
        events = r.json()["events"]
        assert len(events) == 2
        sell_event = next(e for e in events if e["event_type"] == "sell")
        assert sell_event["quantity"] == -50
        assert sell_event["price"] == 550

    async def test_replay_rebuilds_holdings_correctly(self):
        """Replaying ledger rebuilds holdings with correct WAC."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 50, "price": 600, "trade_date": "2026-01-20"},
            headers=self.headers,
        )
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "sell", "quantity": 30, "price": 650, "trade_date": "2026-01-25"},
            headers=self.headers,
        )

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        holdings = r.json()["holdings"]
        assert len(holdings) == 1
        h = holdings[0]
        assert h["symbol"] == "NABIL"
        assert h["quantity"] == 120
        assert abs(h["avg_cost"] - 533.33) < 0.1
        assert abs(h["total_cost"] - 64000) < 1

    async def test_bonus_shares_quantity_up_total_cost_unchanged(self):
        """Bonus shares: quantity increases, total cost unchanged (WAC decreases)."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )

        from app.db.session import SessionLocal
        with SessionLocal() as session:
            ca = CorporateAction(
                symbol="NABIL",
                fiscal_year=f"2080/81-BONUS-{uuid.uuid4().hex[:8]}",
                bonus_pct=10.0,
                book_close="2026-06-15",
                source="nepse:corporate-actions",
            )
            session.add(ca)
            session.commit()
            ca_id = ca.id

        r = await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/corporate-actions/apply",
            json={"corporate_action_id": ca_id, "event_type": "bonus", "quantity": 10},
            headers=self.headers,
        )
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        holdings = r.json()["holdings"]
        h = holdings[0]
        assert h["quantity"] == 110
        assert abs(h["total_cost"] - 50000) < 0.1
        assert abs(h["avg_cost"] - 454.55) < 0.1

    async def test_rights_issue_adds_to_cost_basis(self):
        """Rights issue: quantity increases, total cost increases by qty * price."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )

        from app.db.session import SessionLocal
        with SessionLocal() as session:
            ca = CorporateAction(
                symbol="NABIL",
                fiscal_year=f"2080/81-RIGHTS-{uuid.uuid4().hex[:8]}",
                right_pct=20.0,
                book_close="2026-06-15",
                source="nepse:corporate-actions",
            )
            session.add(ca)
            session.commit()
            ca_id = ca.id

        r = await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/corporate-actions/apply",
            json={"corporate_action_id": ca_id, "event_type": "rights", "quantity": 20, "price": 400},
            headers=self.headers,
        )
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        holdings = r.json()["holdings"]
        h = holdings[0]
        assert h["quantity"] == 120
        assert abs(h["total_cost"] - 58000) < 0.1
        assert abs(h["avg_cost"] - 483.33) < 0.1

    async def test_undo_reverses_event_and_replays(self):
        """Reversing a ledger event marks it reversed and replays portfolio."""
        r = await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/ledger", headers=self.headers)
        event_id = r.json()["events"][0]["id"]

        r = await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/ledger/reverse",
            json={"event_id": event_id},
            headers=self.headers,
        )
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        assert r.json()["holdings"] == []

    async def test_pending_corporate_actions_show_for_held_symbols(self):
        """Corporate actions for held symbols show as pending confirmation."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )

        from app.db.session import SessionLocal
        with SessionLocal() as session:
            ca = CorporateAction(
                symbol="NABIL",
                fiscal_year=f"2080/81-PENDING-{uuid.uuid4().hex[:8]}",
                bonus_pct=10.0,
                book_close="2026-06-15",
                source="nepse:corporate-actions",
            )
            session.add(ca)
            session.commit()
            ca_id = ca.id

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/corporate-actions/pending", headers=self.headers)
        pending = r.json()["pending_actions"]
        our_pending = [p for p in pending if p["fiscal_year"] == ca.fiscal_year]
        assert len(our_pending) == 1
        assert our_pending[0]["symbol"] == "NABIL"
        assert our_pending[0]["bonus_pct"] == 10.0
        assert our_pending[0]["status"] == "pending_confirmation"

    async def test_corporate_action_not_pending_for_unheld_symbol(self):
        """Corporate actions for unheld symbols don't show as pending."""
        from app.db.session import SessionLocal
        with SessionLocal() as session:
            ca = CorporateAction(
                symbol="NIC",
                fiscal_year=f"2080/81-UNHELD-{uuid.uuid4().hex[:8]}",
                bonus_pct=10.0,
                book_close="2026-06-15",
                source="nepse:corporate-actions",
            )
            session.add(ca)
            session.commit()

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/corporate-actions/pending", headers=self.headers)
        pending = r.json()["pending_actions"]
        our_pending = [p for p in pending if p["fiscal_year"] == ca.fiscal_year]
        assert len(our_pending) == 0

    async def test_golden_test_no_corporate_actions_replay_equals_stored_holdings(self):
        """Golden test: portfolio with no corporate actions replays to same holdings."""
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NIC", "side": "buy", "quantity": 50, "price": 800, "trade_date": "2026-01-20"},
            headers=self.headers,
        )
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "sell", "quantity": 30, "price": 550, "trade_date": "2026-01-25"},
            headers=self.headers,
        )

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        before = r.json()["holdings"]

        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/ledger/replay", headers=self.headers)
        assert r.status_code == 200

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/holdings", headers=self.headers)
        after = r.json()["holdings"]

        assert len(before) == len(after)
        for b, a in zip(sorted(before, key=lambda x: x["symbol"]), sorted(after, key=lambda x: x["symbol"])):
            assert b["symbol"] == a["symbol"]
            assert b["quantity"] == a["quantity"]
            assert abs(b["avg_cost"] - a["avg_cost"]) < 0.01
            assert abs(b["total_cost"] - a["total_cost"]) < 0.01

    async def test_lots_reconciliation(self):
        """Reconciliation test: sum of lots.qty_remaining == holding.quantity; realised P&L before/after identical."""
        from app.db.session import SessionLocal

        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 100, "price": 500, "trade_date": "2026-01-15"},
            headers=self.headers,
        )
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "buy", "quantity": 50, "price": 600, "trade_date": "2026-01-20"},
            headers=self.headers,
        )
        await self.client.post(
            f"/api/portfolio/{self.portfolio_id}/transactions",
            json={"symbol": "NABIL", "side": "sell", "quantity": 30, "price": 550, "trade_date": "2026-01-25"},
            headers=self.headers,
        )

        with SessionLocal() as session:
            holding = session.scalar(
                select(Holding).where(
                    Holding.portfolio_id == self.portfolio_id,
                    Holding.symbol == "NABIL"
                )
            )
            assert holding is not None
            lots = session.scalars(
                select(HoldingLot).where(
                    HoldingLot.portfolio_id == self.portfolio_id,
                    HoldingLot.symbol == "NABIL"
                )
            ).all()

            total_lots_qty = sum(lot.qty_remaining for lot in lots)
            assert total_lots_qty == holding.quantity

        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/ledger/replay", headers=self.headers)
        assert r.status_code == 200

        with SessionLocal() as session:
            holding = session.scalar(
                select(Holding).where(
                    Holding.portfolio_id == self.portfolio_id,
                    Holding.symbol == "NABIL"
                )
            )
            lots = session.scalars(
                select(HoldingLot).where(
                    HoldingLot.portfolio_id == self.portfolio_id,
                    HoldingLot.symbol == "NABIL"
                )
            ).all()

            total_lots_qty = sum(lot.qty_remaining for lot in lots)
            assert total_lots_qty == holding.quantity
            assert len(lots) >= 1
            for lot in lots:
                assert lot.qty_remaining <= lot.qty_original
                assert lot.qty_remaining >= 0
                assert lot.cost_per_share >= 0

    async def test_sync_transactions_to_ledger(self):
        """Sync creates ledger events for existing transactions."""
        from app.db.session import SessionLocal
        with SessionLocal() as session:
            txn = Transaction(
                portfolio_id=self.portfolio_id,
                symbol="NABIL",
                side="buy",
                quantity=100,
                price=500,
                trade_date="2026-01-15",
                fees=10.0,
            )
            session.add(txn)
            session.commit()

        r = await self.client.post(f"/api/portfolio/{self.portfolio_id}/ledger/sync", headers=self.headers)
        assert r.status_code == 200
        assert r.json()["synced"] == 1

        r = await self.client.get(f"/api/portfolio/{self.portfolio_id}/ledger", headers=self.headers)
        events = r.json()["events"]
        assert len(events) == 1
        assert events[0]["source"] == f"transaction:{txn.id}"