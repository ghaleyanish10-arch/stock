"""Portfolio ledger service: replays events to rebuild holdings.

This is the core of B1 - the ledger stores inputs only, and holdings
are rebuilt by replaying all events in chronological order.
"""

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any
from collections import defaultdict

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from app.db.models import (
    Portfolio,
    Transaction,
    Holding,
    LedgerEvent,
    LedgerReplayLog,
    LedgerEventType,
    Security,
    CorporateAction,
    User,
)
from app.reference.service import ReferenceService


class LedgerService:
    """Service for managing portfolio ledger events and replaying them."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service

    # --- Event Creation ---

    def create_ledger_event(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        symbol: str,
        event_type: str,
        event_date: date,
        quantity: int,
        price: Optional[float] = None,
        fees: Optional[float] = None,
        source: str = "manual",
        corporate_action_id: Optional[str] = None,
        subscription_details: Optional[dict] = None,
        fractional_handling: Optional[str] = None,
    ) -> LedgerEvent:
        """Create a new ledger event."""
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            raise ValueError("Portfolio not found or access denied")

        event = LedgerEvent(
            portfolio_id=portfolio_id,
            symbol=symbol.upper(),
            event_type=event_type,
            event_date=event_date.isoformat(),
            quantity=quantity,
            price=price,
            fees=fees,
            source=source,
            corporate_action_id=corporate_action_id,
            subscription_details=subscription_details,
            fractional_handling=fractional_handling,
            created_by=user_id,
        )
        session.add(event)
        session.flush()
        return event

    def create_event_from_transaction(
        self,
        session: Session,
        transaction: Transaction,
        user_id: str,
    ) -> LedgerEvent:
        """Create a ledger event from an existing transaction."""
        return self.create_ledger_event(
            session=session,
            portfolio_id=transaction.portfolio_id,
            user_id=user_id,
            symbol=transaction.symbol,
            event_type=transaction.side,  # "buy" or "sell"
            event_date=date.fromisoformat(transaction.trade_date),
            quantity=transaction.quantity if transaction.side == "buy" else -transaction.quantity,
            price=transaction.price,
            fees=transaction.fees,
            source=f"transaction:{transaction.id}",
        )

    # --- Replay Logic ---

    def replay_portfolio(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        triggered_by: str = "system",
        trigger_reason: str = "manual",
    ) -> Dict[str, Any]:
        """Replay all ledger events for a portfolio to rebuild holdings.
        
        This is the core replay function. It:
        1. Deletes all existing holdings for the portfolio
        2. Replays all non-reversed ledger events in date order
        3. Rebuilds holdings with correct WAC and realized P&L
        4. Logs the replay operation
        """
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            raise ValueError("Portfolio not found or access denied")

        # Start replay log
        replay_log = LedgerReplayLog(
            portfolio_id=portfolio_id,
            triggered_by=triggered_by,
            trigger_reason=trigger_reason,
            events_processed=0,
            status="running",
            started_at=datetime.utcnow(),
        )
        session.add(replay_log)
        session.flush()

        try:
            # Get all non-reversed events for this portfolio, ordered by date then created_at
            events = list(session.scalars(
                select(LedgerEvent)
                .where(
                    and_(
                        LedgerEvent.portfolio_id == portfolio_id,
                        LedgerEvent.is_reversed == False,
                    )
                )
                .order_by(LedgerEvent.event_date, LedgerEvent.created_at)
            ))

            # Delete existing holdings - they will be rebuilt
            session.execute(
                Holding.__table__.delete().where(Holding.portfolio_id == portfolio_id)
            )

            # Replay state: tracks holdings and FIFO lots per symbol
            holdings_state: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
                "quantity": 0,
                "total_cost": 0.0,
                "avg_cost": 0.0,
                "first_bought_at": None,
                "last_transacted_at": None,
                # FIFO lots for capital gains tax (holding period tracking)
                "lots": [],  # list of {"qty": int, "cost": float, "date": date, "event_id": str}
            })

            realized_pnl = 0.0

            for event in events:
                self._replay_event(session, portfolio_id, event, holdings_state)
                realized_pnl += holdings_state[event.symbol].get("realized_pnl_delta", 0.0)

            # Create Holding records from replayed state
            for symbol, state in holdings_state.items():
                if state["quantity"] > 0:
                    holding = Holding(
                        portfolio_id=portfolio_id,
                        symbol=symbol,
                        quantity=state["quantity"],
                        avg_cost=state["avg_cost"] if state["quantity"] > 0 else None,
                        total_cost=state["total_cost"],
                        first_bought_at=state["first_bought_at"],
                        last_transacted_at=state["last_transacted_at"],
                    )
                    session.add(holding)

            # Update replay log
            replay_log.events_processed = len(events)
            replay_log.status = "success"
            replay_log.finished_at = datetime.utcnow()

            session.commit()

            return {
                "success": True,
                "events_processed": len(events),
                "holdings_rebuilt": len([s for s in holdings_state.values() if s["quantity"] > 0]),
                "realized_pnl": realized_pnl,
            }

        except Exception as e:
            replay_log.status = "failed"
            replay_log.error_message = str(e)
            replay_log.finished_at = datetime.utcnow()
            session.commit()
            raise

    def _replay_event(
        self,
        session: Session,
        portfolio_id: str,
        event: LedgerEvent,
        holdings_state: Dict[str, Dict[str, Any]],
    ) -> None:
        """Replay a single event, updating holdings state."""
        symbol = event.symbol
        state = holdings_state[symbol]
        event_date = datetime.fromisoformat(event.event_date)

        if event.event_type in ("buy", "sell"):
            self._replay_buy_sell(event, state, event_date)
        elif event.event_type == "bonus":
            self._replay_bonus(event, state, event_date)
        elif event.event_type == "rights":
            self._replay_rights(event, state, event_date)
        elif event.event_type == "cash_dividend":
            # Cash dividends don't affect holdings (they're cash flow)
            pass
        elif event.event_type in ("stock_split", "reverse_split"):
            self._replay_split(event, state, event_date)
        elif event.event_type in ("merger", "spinoff"):
            # Complex corporate actions - handled as combination of sell + buy
            self._replay_complex_ca(event, state, event_date)

    def _replay_buy_sell(
        self,
        event: LedgerEvent,
        state: Dict[str, Any],
        event_date: datetime,
    ) -> None:
        """Replay a buy or sell event using WAC for avg cost, FIFO for lots."""
        qty = event.quantity  # positive for buy, negative for sell
        price = event.price
        fees = event.fees or 0.0

        if qty > 0:  # BUY
            # WAC calculation
            new_total_cost = state["total_cost"] + (qty * price) + fees
            new_qty = state["quantity"] + qty
            state["avg_cost"] = new_total_cost / new_qty if new_qty > 0 else 0.0
            state["total_cost"] = new_total_cost
            state["quantity"] = new_qty

            # FIFO lot tracking
            state["lots"].append({
                "qty": qty,
                "cost": price,
                "fees": fees,
                "date": event_date,
                "event_id": event.id,
            })

            if state["first_bought_at"] is None:
                state["first_bought_at"] = event_date
            state["last_transacted_at"] = event_date

        else:  # SELL
            sell_qty = abs(qty)
            if state["quantity"] < sell_qty:
                raise ValueError(f"Insufficient holdings to sell {sell_qty} of {event.symbol}")

            # WAC: reduce quantity, keep avg_cost
            state["total_cost"] = state["avg_cost"] * (state["quantity"] - sell_qty)
            state["quantity"] -= sell_qty
            state["last_transacted_at"] = event_date

            # FIFO: consume from oldest lots, calculate realized P&L
            remaining = sell_qty
            realized_pnl_delta = 0.0
            new_lots = []

            for lot in state["lots"]:
                if remaining <= 0:
                    new_lots.append(lot)
                    continue

                if lot["qty"] <= remaining:
                    # Consume entire lot
                    lot_pnl = (price - lot["cost"]) * lot["qty"]
                    realized_pnl_delta += lot_pnl
                    remaining -= lot["qty"]
                else:
                    # Partially consume lot
                    consumed_qty = remaining
                    lot_pnl = (price - lot["cost"]) * consumed_qty
                    realized_pnl_delta += lot_pnl
                    lot["qty"] -= consumed_qty
                    new_lots.append(lot)
                    remaining = 0

            state["lots"] = new_lots
            state["realized_pnl_delta"] = realized_pnl_delta

            if state["quantity"] == 0:
                state["first_bought_at"] = None

    def _replay_bonus(
        self,
        event: LedgerEvent,
        state: Dict[str, Any],
        event_date: datetime,
    ) -> None:
        """Replay a bonus share event.
        
        Bonus shares: quantity increases, total cost UNCHANGED (WAC decreases).
        This is the key rule - bonus shares are free, so cost basis doesn't change.
        """
        bonus_qty = event.quantity  # positive
        if state["quantity"] <= 0:
            return  # No holding to bonus

        # Total cost stays the same, quantity increases
        state["quantity"] += bonus_qty
        state["avg_cost"] = state["total_cost"] / state["quantity"]
        state["last_transacted_at"] = event_date

        # FIFO: add bonus shares as zero-cost lots
        state["lots"].append({
            "qty": bonus_qty,
            "cost": 0.0,
            "fees": 0.0,
            "date": event_date,
            "event_id": event.id,
            "is_bonus": True,
        })

    def _replay_rights(
        self,
        event: LedgerEvent,
        state: Dict[str, Any],
        event_date: datetime,
    ) -> None:
        """Replay a rights issue event.
        
        Rights: user subscribes to new shares at a given price.
        Quantity increases, total cost increases by (qty * price).
        """
        rights_qty = event.quantity  # positive (subscribed quantity)
        price = event.price or 0.0
        fees = event.fees or 0.0

        # Add to holdings at subscription price
        new_total_cost = state["total_cost"] + (rights_qty * price) + fees
        new_qty = state["quantity"] + rights_qty
        state["avg_cost"] = new_total_cost / new_qty if new_qty > 0 else 0.0
        state["total_cost"] = new_total_cost
        state["quantity"] = new_qty
        state["last_transacted_at"] = event_date

        # FIFO: add rights shares at subscription price
        state["lots"].append({
            "qty": rights_qty,
            "cost": price,
            "fees": fees,
            "date": event_date,
            "event_id": event.id,
            "is_rights": True,
        })

        if state["first_bought_at"] is None:
            state["first_bought_at"] = event_date

    def _replay_split(
        self,
        event: LedgerEvent,
        state: Dict[str, Any],
        event_date: datetime,
    ) -> None:
        """Replay a stock split or reverse split.
        
        Split ratio stored in subscription_details as {"ratio": 2.0} for 2:1 split.
        Quantity multiplies by ratio, avg_cost divides by ratio.
        Total cost stays the same.
        """
        if state["quantity"] <= 0:
            return

        ratio = 1.0
        if event.subscription_details and "ratio" in event.subscription_details:
            ratio = float(event.subscription_details["ratio"])

        if ratio <= 0:
            return

        # Adjust quantity and avg_cost, total_cost unchanged
        state["quantity"] = int(state["quantity"] * ratio)
        state["avg_cost"] = state["avg_cost"] / ratio if ratio > 0 else 0.0
        state["total_cost"] = state["avg_cost"] * state["quantity"]
        state["last_transacted_at"] = event_date

        # Adjust FIFO lots
        for lot in state["lots"]:
            lot["qty"] = int(lot["qty"] * ratio)
            lot["cost"] = lot["cost"] / ratio if ratio > 0 else 0.0

    def _replay_complex_ca(
        self,
        event: LedgerEvent,
        state: Dict[str, Any],
        event_date: datetime,
    ) -> None:
        """Replay complex corporate action (merger/spinoff).
        
        These are handled as a sell of old shares + buy of new shares.
        Details in subscription_details.
        """
        # For now, treat as sell then buy based on subscription_details
        if not event.subscription_details:
            return

        details = event.subscription_details
        # Sell old symbol
        if "sell_symbol" in details and "sell_qty" in details:
            old_symbol = details["sell_symbol"]
            sell_qty = details["sell_qty"]
            old_state = holdings_state[old_symbol]
            # ... (simplified for now)
            pass

    # --- Undo/Reverse ---

    def reverse_event(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        event_id: str,
    ) -> LedgerEvent:
        """Mark an event as reversed (undo).
        
        The original event stays in the ledger (audit trail) but is
        skipped during replay. No new event is created - the reversal
        is simply the act of marking the original as reversed.
        """
        event = session.get(LedgerEvent, event_id)
        if not event or event.portfolio_id != portfolio_id:
            raise ValueError("Event not found or access denied")

        if event.is_reversed:
            raise ValueError("Event already reversed")

        # Mark original as reversed
        event.is_reversed = True
        event.reversed_by = new_id()

        # Trigger replay - the reversed event will be skipped
        self.replay_portfolio(session, portfolio_id, user_id, triggered_by=user_id, trigger_reason="reversal")

        return event

    # --- Corporate Action Integration ---

    def get_pending_corporate_actions(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """Get corporate actions that are eligible but not yet applied.
        
        Returns actions where the user holds the symbol and the action
        hasn't been applied to the ledger yet. These show as "pending
        your confirmation" in the UI.
        """
        portfolio = session.get(Portfolio, portfolio_id)
        if not portfolio or portfolio.user_id != user_id:
            return []

        # Get current holdings
        holdings = session.scalars(
            select(Holding).where(Holding.portfolio_id == portfolio_id)
        ).all()
        held_symbols = {h.symbol for h in holdings}

        # Get corporate actions for held symbols
        actions = session.scalars(
            select(CorporateAction).where(CorporateAction.symbol.in_(held_symbols))
        ).all()

        pending = []
        for ca in actions:
            # Check if already applied
            existing = session.scalar(
                select(LedgerEvent).where(
                    and_(
                        LedgerEvent.portfolio_id == portfolio_id,
                        LedgerEvent.corporate_action_id == ca.id,
                        LedgerEvent.is_reversed == False,
                    )
                )
            )
            if existing:
                continue

            # Check eligibility (book close date vs holding period)
            # This is simplified - real implementation would check settlement days
            pending.append({
                "corporate_action_id": ca.id,
                "symbol": ca.symbol,
                "fiscal_year": ca.fiscal_year,
                "cash_dividend_pct": ca.cash_dividend_pct,
                "bonus_pct": ca.bonus_pct,
                "right_pct": ca.right_pct,
                "book_close": ca.book_close,
                "agm_date": ca.agm_date,
                "status": "pending_confirmation",
            })

        return pending

    def apply_corporate_action(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        corporate_action_id: str,
        event_type: str,  # "bonus" or "rights"
        quantity: int,
        price: Optional[float] = None,
        fees: Optional[float] = None,
        subscription_details: Optional[dict] = None,
        fractional_handling: Optional[str] = None,
    ) -> LedgerEvent:
        """Apply a corporate action to the ledger after user confirmation."""
        ca = session.get(CorporateAction, corporate_action_id)
        if not ca:
            raise ValueError("Corporate action not found")

        # Determine event date (book close or AGM date)
        event_date_str = ca.book_close or ca.agm_date
        if not event_date_str:
            raise ValueError("Corporate action has no valid date")
        event_date = date.fromisoformat(event_date_str)

        return self.create_ledger_event(
            session=session,
            portfolio_id=portfolio_id,
            user_id=user_id,
            symbol=ca.symbol,
            event_type=event_type,
            event_date=event_date,
            quantity=quantity,
            price=price,
            fees=fees,
            source=f"corporate_action:{corporate_action_id}",
            corporate_action_id=corporate_action_id,
            subscription_details=subscription_details,
            fractional_handling=fractional_handling,
        )

    # --- Sync from Transactions ---

    def sync_transactions_to_ledger(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
    ) -> int:
        """Sync existing transactions to ledger events.
        
        Creates ledger events for transactions that don't have them yet.
        Returns count of events created.
        """
        transactions = session.scalars(
            select(Transaction).where(Transaction.portfolio_id == portfolio_id)
        ).all()

        created = 0
        for txn in transactions:
            # Check if ledger event already exists for this transaction
            existing = session.scalar(
                select(LedgerEvent).where(
                    and_(
                        LedgerEvent.portfolio_id == portfolio_id,
                        LedgerEvent.source == f"transaction:{txn.id}",
                        LedgerEvent.is_reversed == False,
                    )
                )
            )
            if not existing:
                self.create_event_from_transaction(session, txn, user_id)
                created += 1

        if created > 0:
            session.commit()
            self.replay_portfolio(session, portfolio_id, user_id, triggered_by=user_id, trigger_reason="sync")

        return created


# Import new_id here to avoid circular import
from app.db.base import new_id