"""Financial calculators for the NEPSE trading platform."""

from __future__ import annotations

from datetime import date
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class BuySellResult:
    """Result of buy/sell cost calculation."""
    gross_amount: float
    broker_commission: float
    sebon_fee: float
    dp_charge: float
    stt: float  # only for sell
    total_fees: float
    net_amount: float  # amount paid (buy) or received (sell)


@dataclass
class BonusRightResult:
    """Result of bonus/right share calculation."""
    original_quantity: int
    bonus_ratio: float  # e.g., 1:10 = 0.1
    right_ratio: float  # e.g., 1:2 = 0.5
    right_price: Optional[float]
    new_quantity: int
    bonus_shares: int
    right_shares: int
    additional_cost: float  # cost for right shares


@dataclass
class WACCResult:
    """Weighted Average Cost of Capital per share."""
    symbol: str
    total_quantity: int
    total_cost: float
    wacc: float  # weighted average cost per share


@dataclass
class BreakEvenResult:
    """Break-even analysis."""
    symbol: str
    avg_cost: float
    quantity: int
    current_price: Optional[float]
    break_even_price: float
    break_even_pct: float  # percentage from current price


@dataclass
class DividendYieldResult:
    """Dividend yield calculation."""
    symbol: str
    face_value: float
    cash_dividend_pct: float
    ltp: Optional[float]
    dividend_per_share: float
    yield_on_ltp: Optional[float]
    yield_on_cost: Optional[float]


@dataclass
class XIRRResult:
    """XIRR calculation result."""
    xirr: Optional[float]  # annualized rate
    cashflows: List[Tuple[date, float]]
    iterations: int


@dataclass
class BonusRightAdjustedPrice:
    """Price adjusted for bonus/right issues."""
    symbol: str
    original_price: float
    adjusted_price: float
    adjustment_factor: float
    bonus_events: List[dict]  # list of {date, ratio}
    right_events: List[dict]  # list of {date, ratio, price}


# --- Buy/Sell Cost Calculator ---

def calculate_buy_sell_cost(
    quantity: int,
    price: float,
    side: str,  # "buy" or "sell"
    broker_commission_pct: float = 0.00275,  # 0.275%
    sebon_fee_pct: float = 0.00015,  # 0.015%
    dp_charge: float = 25.0,
    stt_pct: float = 0.0015,  # 0.15% on sell only
) -> BuySellResult:
    """
    Calculate total cost/proceeds for a buy/sell transaction.
    
    For BUY: net_amount = gross + fees
    For SELL: net_amount = gross - fees
    """
    if quantity <= 0 or price <= 0:
        raise ValueError("Quantity and price must be positive")
    
    gross_amount = quantity * price
    
    broker_commission = gross_amount * 0.00275  # 0.275%
    sebon_fee = gross_amount * 0.00015  # 0.015%
    dp_charge = 25.0
    
    stt = 0.0
    if side == "sell":
        stt = gross_amount * 0.0015  # 0.15% STT on sell side only
    
    total_fees = broker_commission + sebon_fee + 25.0 + stt
    
    if side == "buy":
        net_amount = gross_amount + total_fees
    else:  # sell
        net_amount = gross_amount - total_fees
    
    return BuySellResult(
        gross_amount=round(gross_amount, 2),
        broker_commission=round(broker_commission, 2),
        sebon_fee=round(sebon_fee, 2),
        dp_charge=round(dp_charge, 2),
        stt=round(stt, 2),
        total_fees=round(total_fees, 2),
        net_amount=round(net_amount, 2),
    )


def calculate_bonus_right(
    original_quantity: int,
    bonus_ratio: float,  # e.g., 1:10 = 0.1
    right_ratio: float = 0.0,  # e.g., 1:2 = 0.5
    right_price: Optional[float] = None,
) -> BonusRightResult:
    """
    Calculate new quantity and cost after bonus/right issue.
    
    Bonus shares: free shares given (e.g., 1:10 = 0.1 means 1 free for every 10 held)
    Right shares: offered at a price (e.g., 1:2 at Rs. 100 means buy 1 share at Rs.100 for every 2 held)
    """
    if original_quantity <= 0:
        raise ValueError("Original quantity must be positive")
    
    bonus_shares = int(original_quantity * bonus_ratio)
    right_shares = int(original_quantity * right_ratio)
    new_quantity = original_quantity + bonus_shares + right_shares
    
    additional_cost = 0.0
    if right_shares > 0 and right_price:
        additional_cost = right_shares * right_price
    
    return BonusRightResult(
        original_quantity=original_quantity,
        bonus_ratio=bonus_ratio,
        right_ratio=right_ratio,
        right_price=right_price,
        new_quantity=new_quantity,
        bonus_shares=bonus_shares,
        right_shares=right_shares,
        additional_cost=round(additional_cost, 2),
    )


def calculate_wacc(
    transactions: list,  # list of (date, side, quantity, price, fees)
) -> 'WACCResult':
    """
    Calculate Weighted Average Cost of Capital (WACC) per share.
    
    transactions: list of (date, side, quantity, price, fees)
    side: "buy" or "sell"
    For sells, we use FIFO to reduce quantity and cost.
    """
    if not transactions:
        raise ValueError("Transactions list cannot be empty")
    
    # Sort by date
    sorted_tx = sorted(transactions, key=lambda x: x[0])
    
    total_qty = 0
    total_cost = 0.0
    
    for tx in sorted_tx:
        date, side, qty, price, fees = tx
        fees = tx[4] if len(tx) > 4 else 0
        
        if side == "buy":
            cost = qty * price + fees
            total_cost += cost
            total_qty += qty
        elif side == "sell":
            # Reduce quantity, keep avg cost same (FIFO assumption)
            if total_qty < qty:
                raise ValueError("Cannot sell more than held")
            # Remove cost proportionally
            cost_removed = (total_cost / total_qty) * qty
            total_cost -= cost_removed
            total_qty -= qty
    
    if total_qty <= 0:
        return WACCResult(
            symbol="",
            total_quantity=0,
            total_cost=0.0,
            wacc=0.0,
        )
    
    wacc = total_cost / total_qty
    
    return WACCResult(
        symbol="",
        total_quantity=total_qty,
        total_cost=round(total_cost, 2),
        wacc=round(wacc, 4),
    )


def calculate_break_even(
    avg_cost: float,
    current_price: Optional[float] = None,
) -> 'BreakEvenResult':
    """
    Calculate break-even price and percentage.
    Break-even price = avg_cost (no profit, no loss)
    """
    if avg_cost <= 0:
        raise ValueError("Average cost must be positive")
    
    break_even_price = avg_cost
    break_even_pct = 0.0
    
    if current_price and current_price > 0:
        break_even_pct = ((break_even_price - current_price) / current_price) * 100
    
    return BreakEvenResult(
        symbol="",
        avg_cost=avg_cost,
        quantity=0,
        current_price=current_price,
        break_even_price=round(break_even_price, 2),
        break_even_pct=round(break_even_pct, 2),
    )


def calculate_dividend_yield(
    face_value: float,
    cash_dividend_pct: float,
    ltp: Optional[float] = None,
    avg_cost: Optional[float] = None,
) -> DividendYieldResult:
    """
    Calculate dividend yield.
    Dividend per share = face_value * (cash_dividend_pct / 100)
    Yield on LTP = dividend_per_share / ltp * 100
    Yield on cost = dividend_per_share / avg_cost * 100
    """
    if face_value <= 0:
        raise ValueError("Face value must be positive")
    
    dividend_per_share = face_value * (cash_dividend_pct / 100.0)
    
    yield_on_ltp = None
    if ltp and ltp > 0:
        yield_on_ltp = (dividend_per_share / ltp) * 100.0
    
    yield_on_cost = None
    if avg_cost and avg_cost > 0:
        yield_on_cost = (dividend_per_share / avg_cost) * 100.0
    
    return DividendYieldResult(
        symbol="",
        face_value=face_value,
        cash_dividend_pct=cash_dividend_pct,
        ltp=ltp,
        dividend_per_share=round(dividend_per_share, 2),
        yield_on_ltp=round(yield_on_ltp, 2) if yield_on_ltp else None,
        yield_on_cost=round(yield_on_cost, 2) if yield_on_cost else None,
    )


def calculate_xirr(
    cashflows: List[Tuple[date, float]],
    guess: float = 0.1,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> XIRRResult:
    """
    Calculate XIRR (Extended Internal Rate of Return).
    
    cashflows: list of (date, amount) where positive = inflow, negative = outflow
    Returns annualized rate.
    """
    if len(cashflows) < 2:
        raise ValueError("At least 2 cashflows required")
    
    # Sort by date
    cashflows = sorted(cashflows, key=lambda x: x[0])
    
    # Check for at least one positive and one negative
    has_positive = any(cf[1] > 0 for cf in cashflows)
    has_negative = any(cf[1] < 0 for cf in cashflows)
    if not (has_positive and has_negative):
        raise ValueError("Cashflows must have at least one positive and one negative value")
    
    # Newton-Raphson method
    rate = 0.1  # initial guess
    iterations = 0
    
    for _ in range(max_iterations):
        npv = 0.0
        dnpv = 0.0  # derivative
        
        for cf_date, amount in cashflows:
            days = (cf_date - cashflows[0][0]).days
            years = days / 365.0
            factor = (1 + rate) ** years
            if factor == 0:
                return XIRRResult(xirr=None, cashflows=cashflows, iterations=0)
            
            npv += amount / factor
            dnpv += -amount * days / 365.0 / (factor * (1 + rate))
        
        if abs(npv) < tolerance:
            break
        
        if abs(dnpv) < 1e-10:
            break
            
        rate = rate - npv / dnpv
        iterations += 1
        
        if rate < -0.99:  # prevent divergence
            return XIRRResult(xirr=None, cashflows=cashflows, iterations=iterations)
    
    return XIRRResult(
        xirr=round(rate, 6) if rate > -0.99 else None,
        cashflows=cashflows,
        iterations=iterations,
    )


def adjust_price_for_bonus_right(
    symbol: str,
    original_price: float,
    bonus_events: List[dict],  # [{"date": date, "ratio": float}, ...]
    right_events: List[dict],  # [{"date": date, "ratio": float, "price": float}, ...]
) -> 'BonusRightAdjustedPrice':
    """
    Calculate adjusted price for bonus/right issues.
    
    Bonus shares: price adjusts by factor 1/(1+bonus_ratio)
    Right shares: price adjusts by factor (1+right_ratio*right_price/original_price)/(1+right_ratio)
    """
    if original_price <= 0:
        raise ValueError("Original price must be positive")
    
    adjusted_price = original_price
    
    # Apply bonus adjustments (chronological order)
    for event in sorted(bonus_events, key=lambda x: x["date"]):
        ratio = event["ratio"]  # e.g., 1:10 = 0.1
        adjusted_price = adjusted_price / (1 + ratio)
    
    # Apply right adjustments
    for event in sorted(right_events, key=lambda x: x["date"]):
        ratio = event["ratio"]  # e.g., 1:2 = 0.5
        right_price = event.get("price", 0)
        if right_price > 0:
            # Theoretical ex-right price
            adjusted_price = (original_price + ratio * right_price) / (1 + ratio)
        else:
            adjusted_price = adjusted_price / (1 + ratio)
    
    adjustment_factor = adjusted_price / original_price
    
    return BonusRightAdjustedPrice(
        symbol="",
        original_price=round(original_price, 2),
        adjusted_price=round(adjusted_price, 2),
        adjustment_factor=round(adjusted_price / original_price, 4),
        bonus_events=bonus_events,
        right_events=right_events,
    )