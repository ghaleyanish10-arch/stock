"""Portfolio service: manages portfolios, transactions, and holdings."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, List
from uuid import UUID

from sqlalchemy import func, select, and_
from sqlalchemy.orm import Session

from app.db.models import (
    Portfolio,
    Transaction,
    Holding,
    Security,
    DailyBar,
    FeeTaxRate,
    User,
)
from app.reference.service import ReferenceService
from app.nepse.registry import get_adapter
from app.ai.service import AIService, GroundingContext


class PortfolioService:
    """Manages portfolios, transactions, and holdings."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service

    # --- Portfolio CRUD ---

    def create_portfolio(
        self,
        session: Session,
        user_id: str,
        name: str,
        base_currency: str = "NPR",
    ) -> Portfolio:
        """Create a new portfolio for a user."""
        portfolio = Portfolio(
            user_id=user_id,
            name=name,
            base_currency=base_currency,
        )
        session.add(portfolio)
        session.commit()
        session.refresh(portfolio)
        return portfolio

    def get_portfolio(self, session: Session, portfolio_id: str, user_id: str) -> Optional[Portfolio]:
        """Get portfolio by ID, ensuring ownership."""
        portfolio = session.get(Portfolio, portfolio_id)
        if portfolio and portfolio.user_id == user_id:
            return portfolio
        return None

    def list_portfolios(self, session: Session, user_id: str) -> List[Portfolio]:
        """List all portfolios for a user."""
        return list(
            session.scalars(
                select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.created_at.desc())
            )
        )

    def update_portfolio(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        name: Optional[str] = None,
        base_currency: Optional[str] = None,
    ) -> Optional[Portfolio]:
        """Update portfolio details."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return None
        if name is not None:
            portfolio.name = name
        if base_currency is not None:
            portfolio.base_currency = base_currency
        portfolio.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(portfolio)
        return portfolio

    def delete_portfolio(self, session: Session, portfolio_id: str, user_id: str) -> bool:
        """Delete a portfolio (cascades to transactions and holdings)."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return False
        session.delete(portfolio)
        session.commit()
        return True

    # --- Transaction CRUD ---

    def add_transaction(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        symbol: str,
        side: str,  # "buy" or "sell"
        quantity: int,
        price: float,
        trade_date: date,
        fees: Optional[float] = None,
        note: Optional[str] = None,
    ) -> Transaction:
        """Add a transaction and update holdings."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            raise ValueError("Portfolio not found or access denied")

        symbol = symbol.upper()
        security = session.get(Security, symbol)
        if not security:
            raise ValueError(f"Security {symbol} not found")

        # Validate side
        if side not in ("buy", "sell"):
            raise ValueError("Side must be 'buy' or 'sell'")

        # Check sufficient quantity for sell
        if side == "sell":
            holding = session.scalar(
                select(Holding).where(
                    Holding.portfolio_id == portfolio_id,
                    Holding.symbol == symbol,
                )
            )
            if not holding or holding.quantity < quantity:
                raise ValueError("Insufficient holdings to sell")

        transaction = Transaction(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            trade_date=trade_date.isoformat(),
            fees=fees,
            note=note,
        )
        session.add(transaction)

        # Update holdings
        self._update_holding_from_transaction(session, portfolio_id, transaction)

        session.commit()
        return transaction

    def _update_holding_from_transaction(
        self,
        session: Session,
        portfolio_id: str,
        transaction: Transaction,
    ) -> None:
        """Update holdings based on a new transaction."""
        symbol = transaction.symbol
        side = transaction.side
        quantity = transaction.quantity
        price = transaction.price

        holding = session.scalar(
            select(Holding).where(
                Holding.portfolio_id == portfolio_id,
                Holding.symbol == transaction.symbol,
            )
        )

        if side == "buy":
            if holding is None:
                holding = Holding(
                    portfolio_id=portfolio_id,
                    symbol=transaction.symbol,
                    quantity=0,
                    avg_cost=0.0,
                    total_cost=0.0,
                )
                session.add(holding)

            # Update weighted average cost
            total_cost = holding.total_cost + (quantity * price)
            total_qty = holding.quantity + quantity
            holding.avg_cost = total_cost / total_qty if total_qty > 0 else 0
            holding.total_cost = total_cost
            holding.quantity = total_qty

            if holding.first_bought_at is None:
                holding.first_bought_at = datetime.utcnow()
            holding.last_transacted_at = datetime.utcnow()

        else:  # sell
            if not holding or holding.quantity < quantity:
                raise ValueError("Insufficient holdings")

            # Reduce quantity, keep avg_cost
            holding.quantity -= quantity
            if holding.quantity == 0:
                session.delete(holding)
            else:
                holding.total_cost = holding.avg_cost * holding.quantity
            holding.last_transacted_at = datetime.utcnow()

    def get_transactions(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Transaction]:
        """Get transactions for a portfolio."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return []

        stmt = (
            select(Transaction)
            .where(Transaction.portfolio_id == portfolio_id)
            .order_by(Transaction.trade_date.desc(), Transaction.created_at.desc())
        )
        if symbol:
            stmt = stmt.where(Transaction.symbol == symbol.upper())

        return list(session.scalars(stmt.limit(limit).offset(offset)))

    def update_transaction(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        transaction_id: str,
        **updates: Any,
    ) -> Optional[Transaction]:
        """Update a transaction (recalculates holdings)."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return None

        transaction = session.get(Transaction, transaction_id)
        if not transaction or transaction.portfolio_id != portfolio_id:
            return None

        # Store old values for rollback
        old_symbol = transaction.symbol
        old_side = transaction.side
        old_quantity = transaction.quantity
        old_price = transaction.price

        # Apply updates
        for key, value in updates.items():
            if hasattr(transaction, key):
                setattr(transaction, key, value)

        # Recalculate holdings: reverse old, apply new
        self._reverse_holding_change(session, portfolio_id, old_symbol, old_side, old_quantity, old_price)
        self._update_holding_from_transaction(session, portfolio_id, transaction)

        session.commit()
        session.refresh(transaction)
        return transaction

    def delete_transaction(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        transaction_id: str,
    ) -> bool:
        """Delete a transaction and reverse its effect on holdings."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return False

        transaction = session.get(Transaction, transaction_id)
        if not transaction or transaction.portfolio_id != portfolio_id:
            return False

        # Reverse the holding change
        self._reverse_holding_change(
            session,
            portfolio_id,
            transaction.symbol,
            transaction.side,
            transaction.quantity,
            transaction.price,
        )

        session.delete(transaction)
        session.commit()
        return True

    def _reverse_holding_change(
        self,
        session: Session,
        portfolio_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
    ) -> None:
        """Reverse the effect of a transaction on holdings."""
        holding = session.scalar(
            select(Holding).where(
                Holding.portfolio_id == portfolio_id,
                Holding.symbol == symbol,
            )
        )
        if not holding:
            return

        if side == "buy":
            # Reverse a buy: reduce quantity and adjust cost
            if holding.quantity < quantity:
                # Shouldn't happen, but handle gracefully
                session.delete(holding)
                return

            holding.total_cost -= quantity * price
            holding.quantity -= quantity
            if holding.quantity <= 0:
                session.delete(holding)
            else:
                holding.avg_cost = holding.total_cost / holding.quantity
        else:
            # Reverse a sell: add back the sold shares at the original price
            holding.quantity += quantity
            holding.total_cost += quantity * price
            holding.avg_cost = holding.total_cost / holding.quantity

    # --- Holdings ---

    def get_holdings(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> List[Holding]:
        """Get all holdings for a portfolio."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return []

        return list(
            session.scalars(
                select(Holding)
                .where(Holding.portfolio_id == portfolio_id)
                .order_by(Holding.symbol)
            )
        )

    def get_holding(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        symbol: str,
    ) -> Optional[Holding]:
        """Get a specific holding."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return None

        return session.scalar(
            select(Holding).where(
                Holding.portfolio_id == portfolio_id,
                Holding.symbol == symbol.upper(),
            )
        )

    # --- Portfolio Valuation ---

    def get_portfolio_valuation(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> dict:
        """Get current portfolio valuation with P/L."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return {}

        holdings = self.get_holdings(session, portfolio_id, user_id)
        if not holdings:
            return {
                "portfolio_id": portfolio_id,
                "total_value": 0.0,
                "total_cost": 0.0,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "holdings": [],
            }

        # Get latest prices
        symbols = [h.symbol for h in holdings]
        adapter = get_adapter()
        prices = {}
        for symbol in symbols:
            try:
                price_data = adapter.get_stock_info(symbol)
                if price_data:
                    prices[symbol] = price_data.get("last_traded_price") or price_data.get("close_price")
            except Exception:
                pass

        total_value = 0.0
        total_cost = 0.0
        holdings_data = []

        for holding in holdings:
            ltp = prices.get(holding.symbol)
            market_value = (ltp or 0) * holding.quantity if ltp else 0
            cost = holding.total_cost
            pnl = market_value - cost if market_value > 0 and cost > 0 else 0
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0

            total_value += market_value
            total_cost += cost

            holdings_data.append({
                "symbol": holding.symbol,
                "quantity": holding.quantity,
                "avg_cost": holding.avg_cost,
                "total_cost": cost,
                "ltp": ltp,
                "market_value": market_value,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
            })

        unrealized_pnl = total_value - total_cost
        unrealized_pnl_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0

        return {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "total_value": total_value,
            "total_cost": total_cost,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "holdings": holdings_data,
        }

    # --- Performance Metrics ---

    def calculate_xirr(
        self,
        cashflows: List[tuple[date, float]],
        guess: float = 0.1,
    ) -> Optional[float]:
        """Calculate XIRR for a series of cash flows.
        
        cashflows: list of (date, amount) where positive = inflow (sell/dividend), negative = outflow (buy)
        Returns annualized rate as decimal (e.g., 0.15 for 15%).
        """
        if len(cashflows) < 2:
            return None

        # Newton-Raphson method for XIRR
        def npv(rate: float) -> float:
            npv = 0.0
            for cf_date, amount in cashflows:
                days = (cf_date - cashflows[0][0]).days
                npv += amount / ((1 + rate) ** (days / 365.0))
            return npv

        rate = 0.1  # initial guess
        for _ in range(100):
            npv_val = npv(rate)
            if abs(npv_val) < 0.0001:
                return rate
            # Derivative
            deriv = 0.0
            for cf_date, amount in cashflows:
                days = (cf_date - cashflows[0][0]).days
                deriv -= (days / 365.0) * amount / ((1 + rate) ** (days / 365.0 + 1))
            if deriv == 0:
                break
            rate = rate - npv_val / deriv
            if rate < -0.99:
                return None

        return rate if rate > -0.99 else None

    def get_portfolio_cashflows(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> List[tuple[date, float]]:
        """Get cash flows for XIRR calculation: buys are negative, sells/dividends are positive."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return []

        transactions = self.get_transactions(session, portfolio_id, user_id, limit=10000)
        cashflows = []

        for t in transactions:
            date_obj = date.fromisoformat(t.trade_date)
            amount = -t.quantity * t.price - (t.fees or 0) if t.side == "buy" else t.quantity * t.price
            cashflows.append((date_obj, amount))

        # Add dividend income as positive cash flow
        from app.db.models import CorporateAction
        dividends = session.scalars(
            select(CorporateAction)
            .where(
                CorporateAction.symbol.in_([h.symbol for h in self.get_holdings(session, portfolio_id, 0)]),
                CorporateAction.cash_dividend_pct.is_not(None),
                CorporateAction.cash_dividend_pct > 0,
            )
        ).all()
        for ca in dividends:
            # Simplified: assume dividend received on ex-date
            pass

        return cashflows

    def get_portfolio_xirr(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> Optional[float]:
        """Calculate portfolio XIRR."""
        cashflows = self.get_portfolio_cashflows(session, portfolio_id, user_id)
        if len(cashflows) < 2:
            return None
        return self.calculate_xirr(cashflows)

    # --- AI Portfolio Review ---

    def get_portfolio_review_data(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> dict:
        """Gather all portfolio data for AI review."""
        valuation = self.get_portfolio_valuation(session, portfolio_id, user_id)
        if not valuation:
            return {}
        
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return {}
        
        # Get XIRR
        xirr = self.get_portfolio_xirr(session, portfolio_id, user_id)
        
        # Get transactions
        transactions = self.get_transactions(session, portfolio_id, user_id, limit=50)
        
        # Get sector allocation
        holdings = self.get_holdings(session, portfolio_id, user_id)
        sector_allocation = {}
        for h in holdings:
            try:
                sec = session.get(Security, h.symbol)
                if sec and sec.sector_code:
                    sector = sec.sector_code
                    sector_allocation[sector] = sector_allocation.get(sector, 0) + h.total_cost
            except Exception:
                pass
        
        # Concentration metrics
        total_cost = valuation.get("total_cost", 0)
        if total_cost > 0:
            top_holding_pct = max((h.get("total_cost", 0) / total_cost * 100) for h in valuation.get("holdings", [])) if valuation.get("holdings") else 0
            top_5_pct = sum(sorted([h.get("total_cost", 0) for h in valuation.get("holdings", [])], reverse=True)[:5]) / total_cost * 100 if valuation.get("holdings") else 0
        else:
            top_holding_pct = 0
            top_5_pct = 0
        
        return {
            "portfolio_name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
            "valuation": valuation,
            "xirr": xirr,
            "xirr_pct": round(xirr * 100, 2) if xirr else None,
            "transactions": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "trade_date": t.trade_date,
                    "fees": t.fees,
                }
                for t in transactions
            ],
            "sector_allocation": sector_allocation,
            "concentration": {
                "top_holding_pct": round(top_holding_pct, 2),
                "top_5_pct": round(top_5_pct, 2),
                "holding_count": len(valuation.get("holdings", [])),
            },
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def get_ai_portfolio_review(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        question: str,
        ai_service,
    ) -> str:
        """Get AI-powered portfolio review."""
        data = self.get_portfolio_review_data(session, portfolio_id, user_id)
        if not data:
            return "No portfolio data available for review."
        
        # Build question with context
        context = f"Portfolio Review Data:\n{json.dumps(data, indent=2, default=str)}\n\nUser Question: {question}"
        
        # Use AI service to get grounded answer
        grounding_context = None  # We don't need external grounding for portfolio review
        answer = await ai_service.ask(
            user_id=user_id,
            question=context,
            grounding=grounding_context,
            privacy_consent=True,
        )
        return answer