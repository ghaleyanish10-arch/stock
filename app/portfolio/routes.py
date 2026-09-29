"""Portfolio API routes."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, DbSession
from app.portfolio.service import PortfolioService
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService
from app.ai.service import AIService
from app.ai.routes import get_ai_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"], redirect_slashes=True)

_portfolio = PortfolioService(ReferenceService(get_adapter()))


class PortfolioReviewRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="Question for AI review")
    privacy_consent: bool = Field(..., description="User consent to send portfolio data to AI")


class CreatePortfolioRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    base_currency: str = Field(default="NPR", pattern="^[A-Z]{3}$")


class CreateTransactionRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: int = Field(..., ge=1)
    price: float = Field(..., gt=0)
    trade_date: date
    fees: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("", summary="Create a new portfolio")
def create_portfolio(
    session: DbSession,
    user: CurrentUser,
    request: CreatePortfolioRequest,
) -> dict:
    portfolio = _portfolio.create_portfolio(session, user.id, request.name, request.base_currency)
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "base_currency": portfolio.base_currency,
        "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
    }


@router.get("", summary="List user's portfolios")
def list_portfolios(
    session: DbSession,
    user: CurrentUser,
) -> dict:
    portfolios = _portfolio.list_portfolios(session, user.id)
    return {
        "portfolios": [
            {
                "id": p.id,
                "name": p.name,
                "base_currency": p.base_currency,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in portfolios
        ]
    }


@router.get("/{portfolio_id}", summary="Get portfolio details")
def get_portfolio(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    portfolio = _portfolio.get_portfolio(session, portfolio_id, user.id)
    if not portfolio:
        raise HTTPException(404, "Portfolio not found")
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "base_currency": portfolio.base_currency,
        "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
    }


@router.patch("/{portfolio_id}", summary="Update portfolio")
def update_portfolio(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
    name: Optional[str] = None,
    base_currency: Optional[str] = None,
) -> dict:
    portfolio = _portfolio.update_portfolio(session, portfolio_id, user.id, name, base_currency)
    if not portfolio:
        raise HTTPException(404, "Portfolio not found")
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "base_currency": portfolio.base_currency,
    }


@router.delete("/{portfolio_id}", summary="Delete portfolio")
def delete_portfolio(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _portfolio.delete_portfolio(session, portfolio_id, user.id)
    if not deleted:
        raise HTTPException(404, "Portfolio not found")
    return {"detail": "Portfolio deleted"}


# --- Transactions ---


@router.post("/{portfolio_id}/transactions", summary="Add transaction")
def add_transaction(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
    request: CreateTransactionRequest,
) -> dict:
    try:
        tx = _portfolio.add_transaction(
            session, portfolio_id, user.id, request.symbol, request.side, request.quantity, request.price, request.trade_date, request.fees, request.note
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "id": tx.id,
        "symbol": tx.symbol,
        "side": tx.side,
        "quantity": tx.quantity,
        "price": tx.price,
        "trade_date": tx.trade_date,
        "fees": tx.fees,
        "note": tx.note,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


@router.get("/{portfolio_id}/transactions", summary="List transactions")
def list_transactions(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
    symbol: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    txs = _portfolio.get_transactions(session, portfolio_id, user.id, symbol, limit, offset)
    return {
        "transactions": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "trade_date": t.trade_date,
                "fees": t.fees,
                "note": t.note,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txs
        ]
    }


@router.patch("/{portfolio_id}/transactions/{transaction_id}", summary="Update transaction")
def update_transaction(
    portfolio_id: str,
    transaction_id: str,
    session: DbSession,
    user: CurrentUser,
    **updates: Any,
) -> dict:
    tx = _portfolio.update_transaction(session, portfolio_id, user.id, transaction_id, **updates)
    if not tx:
        raise HTTPException(404, "Transaction not found")
    return {
        "id": tx.id,
        "symbol": tx.symbol,
        "side": tx.side,
        "quantity": tx.quantity,
        "price": tx.price,
        "trade_date": tx.trade_date,
    }


@router.delete("/{portfolio_id}/transactions/{transaction_id}", summary="Delete transaction")
def delete_transaction(
    portfolio_id: str,
    transaction_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _portfolio.delete_transaction(session, portfolio_id, user.id, transaction_id)
    if not deleted:
        raise HTTPException(404, "Transaction not found")
    return {"detail": "Transaction deleted"}


# --- Holdings ---


@router.get("/{portfolio_id}/holdings", summary="Get portfolio holdings")
def get_holdings(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    holdings = _portfolio.get_holdings(session, portfolio_id, user.id)
    return {
        "holdings": [
            {
                "symbol": h.symbol,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
                "total_cost": h.total_cost,
                "first_bought_at": h.first_bought_at.isoformat() if h.first_bought_at else None,
                "last_transacted_at": h.last_transacted_at.isoformat() if h.last_transacted_at else None,
            }
            for h in holdings
        ]
    }


@router.get("/{portfolio_id}/valuation", summary="Get portfolio valuation with P/L")
def get_valuation(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    val = _portfolio.get_portfolio_valuation(session, portfolio_id, user.id)
    if not val:
        raise HTTPException(404, "Portfolio not found")
    return val


@router.get("/{portfolio_id}/xirr", summary="Get portfolio XIRR")
def get_xirr(
    portfolio_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    xirr = _portfolio.get_portfolio_xirr(session, portfolio_id, user.id)
    return {
        "xirr": xirr,
        "xirr_pct": round(xirr * 100, 2) if xirr else None,
    }


@router.post("/{portfolio_id}/ai-review", summary="Get AI-powered portfolio review")
async def portfolio_ai_review(
    portfolio_id: str,
    request: PortfolioReviewRequest,
    session: DbSession,
    user: CurrentUser,
    ai_service: AIService = Depends(get_ai_service),
) -> dict:
    """Get AI-powered portfolio review with grounded analysis."""
    if not request.privacy_consent:
        raise HTTPException(403, "Privacy consent required for AI portfolio review")
    
    try:
        review = await _portfolio.get_ai_portfolio_review(
            session, portfolio_id, user.id, request.question, ai_service
        )
        return {"review": review}
    except Exception as e:
        raise HTTPException(500, f"AI review failed: {str(e)}")