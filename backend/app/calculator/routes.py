"""Calculator API routes."""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth.deps import CurrentUser, DbSession
from app.calculator.service import (
    calculate_buy_sell_cost,
    calculate_bonus_right,
    calculate_wacc,
    calculate_break_even,
    calculate_dividend_yield,
    calculate_xirr,
    adjust_price_for_bonus_right,
    BuySellResult,
    BonusRightResult,
    WACCResult,
    BreakEvenResult,
    DividendYieldResult,
    XIRRResult,
    BonusRightAdjustedPrice,
)
from app.reference.service import ReferenceService
from app.nepse.registry import get_adapter

router = APIRouter(prefix="/api/calculator", tags=["calculator"])


# --- Request/Response Models ---

class BuySellRequest(BaseModel):
    quantity: int
    price: float
    side: str  # "buy" or "sell"

class BonusRightRequest(BaseModel):
    original_quantity: int
    bonus_ratio: float = 0.0  # e.g., 0.1 for 1:10
    right_ratio: float = 0.0  # e.g., 0.5 for 1:2
    right_price: Optional[float] = None

class WACCRequest(BaseModel):
    transactions: List[dict]  # [{"date": "2026-01-01", "side": "buy", "quantity": 100, "price": 500, "fees": 100}, ...]

class BreakEvenRequest(BaseModel):
    avg_cost: float
    current_price: Optional[float] = None

class DividendYieldRequest(BaseModel):
    face_value: float
    cash_dividend_pct: float
    ltp: Optional[float] = None
    avg_cost: Optional[float] = None

class XIRRRequest(BaseModel):
    cashflows: List[dict]  # [{"date": "2026-01-01", "amount": -10000}, {"date": "2026-06-01", "amount": 500}, ...]

class AdjustPriceRequest(BaseModel):
    symbol: str
    original_price: float
    bonus_events: List[dict] = []  # [{"date": "2026-01-01", "ratio": 0.1}, ...]
    right_events: List[dict] = []  # [{"date": "2026-01-01", "ratio": 0.5, "price": 100}, ...]


@router.post("/buy-sell", summary="Calculate buy/sell cost with fees", response_model=dict)
def calc_buy_sell(request: BuySellRequest) -> dict:
    """Calculate buy/sell cost including all fees (broker, SEBON, DP, STT)."""
    try:
        result = calculate_buy_sell_cost(
            quantity=request.quantity,
            price=request.price,
            side=request.side,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "gross_amount": result.gross_amount,
        "broker_commission": result.broker_commission,
        "sebon_fee": result.sebon_fee,
        "dp_charge": result.dp_charge,
        "stt": result.stt,
        "total_fees": result.total_fees,
        "net_amount": result.net_amount,
    }


@router.post("/bonus-right", summary="Calculate bonus/right share impact", response_model=dict)
def calc_bonus_right(request: BonusRightRequest) -> dict:
    """Calculate new quantity and cost after bonus/right issue."""
    try:
        result = calculate_bonus_right(
            original_quantity=request.original_quantity,
            bonus_ratio=request.bonus_ratio,
            right_ratio=request.right_ratio,
            right_price=request.right_price,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "original_quantity": result.original_quantity,
        "bonus_shares": result.bonus_shares,
        "right_shares": result.right_shares,
        "new_quantity": result.new_quantity,
        "additional_cost": result.additional_cost,
    }


@router.post("/wacc", summary="Calculate Weighted Average Cost (WACC)", response_model=dict)
def calc_wacc(request: WACCRequest) -> dict:
    """Calculate Weighted Average Cost per share using FIFO method."""
    try:
        # Convert dict transactions to tuples
        transactions = []
        for tx in request.transactions:
            date_obj = date.fromisoformat(tx["date"])
            transactions.append((
                date_obj,
                tx["side"],
                tx["quantity"],
                tx["price"],
                tx.get("fees", 0),
            ))
        result = calculate_wacc(transactions)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "symbol": result.symbol,
        "total_quantity": result.total_quantity,
        "total_cost": result.total_cost,
        "wacc": result.wacc,
    }


@router.post("/break-even", summary="Calculate break-even price", response_model=dict)
def calc_break_even(request: BreakEvenRequest) -> dict:
    """Calculate break-even price and percentage from current price."""
    try:
        result = calculate_break_even(
            avg_cost=request.avg_cost,
            current_price=request.current_price,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "symbol": result.symbol,
        "avg_cost": result.avg_cost,
        "break_even_price": result.break_even_price,
        "break_even_pct": result.break_even_pct,
    }


@router.post("/dividend-yield", summary="Calculate dividend yield", response_model=dict)
def calc_dividend_yield(request: DividendYieldRequest) -> dict:
    """Calculate dividend yield on LTP and on cost basis."""
    try:
        result = calculate_dividend_yield(
            face_value=request.face_value,
            cash_dividend_pct=request.cash_dividend_pct,
            ltp=request.ltp,
            avg_cost=request.avg_cost,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "symbol": result.symbol,
        "face_value": result.face_value,
        "cash_dividend_pct": result.cash_dividend_pct,
        "dividend_per_share": result.dividend_per_share,
        "yield_on_ltp": result.yield_on_ltp,
        "yield_on_cost": result.yield_on_cost,
        "ltp": result.ltp,
        "avg_cost": request.avg_cost,
    }


@router.post("/xirr", summary="Calculate XIRR from cashflows", response_model=dict)
def calc_xirr(request: XIRRRequest) -> dict:
    """Calculate Extended Internal Rate of Return (XIRR) from cashflows."""
    try:
        cashflows = [(date.fromisoformat(cf["date"]), cf["amount"]) for cf in request.cashflows]
        result = calculate_xirr(cashflows)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "xirr": result.xirr,
        "xirr_pct": round(result.xirr * 100, 2) if result.xirr else None,
        "iterations": result.iterations,
        "cashflows": [
            {"date": cf[0].isoformat(), "amount": cf[1]}
            for cf in result.cashflows
        ],
    }


@router.post("/adjust-price", summary="Adjust price for bonus/right issues", response_model=dict)
def calc_adjust_price(request: AdjustPriceRequest) -> dict:
    """Calculate adjusted price after bonus/right issues."""
    try:
        result = adjust_price_for_bonus_right(
            symbol=request.symbol,
            original_price=request.original_price,
            bonus_events=request.bonus_events,
            right_events=request.right_events,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "symbol": result.symbol,
        "original_price": result.original_price,
        "adjusted_price": result.adjusted_price,
        "adjustment_factor": result.adjustment_factor,
    }