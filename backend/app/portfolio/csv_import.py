"""CSV import for portfolio transactions (B2/B3).

Features:
- Dry-run mode
- Row limits
- Duplicate detection on symbol+side+date+qty+price
- Flag sells above held qty
- Replay after import
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.db.models import Transaction, Holding, Portfolio, Security
from app.portfolio.ledger import LedgerService
from app.reference.service import ReferenceService


class ImportStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    INSUFFICIENT_HOLDINGS = "insufficient_holdings"


@dataclass
class CSVImportRow:
    """Single row from CSV import."""
    row_number: int
    symbol: str
    side: str
    quantity: int
    price: float
    trade_date: date
    fees: Optional[float]
    note: Optional[str]
    status: ImportStatus = ImportStatus.PENDING
    errors: List[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


@dataclass
class CSVImportResult:
    """Result of CSV import operation."""
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    insufficient_holdings_rows: int
    rows: List[CSVImportRow]
    imported_count: int = 0
    dry_run: bool = False


class CSVImporter:
    """Imports transactions from CSV with validation and duplicate detection."""

    MAX_ROWS = 10000  # Hard limit

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service
        self._ledger = LedgerService(reference_service)

    def parse_csv(self, content: str) -> List[CSVImportRow]:
        """Parse CSV content into rows with basic validation."""
        rows = []
        reader = csv.DictReader(io.StringIO(content))

        required_fields = {"symbol", "side", "quantity", "price", "trade_date"}
        if not required_fields.issubset(set(reader.fieldnames or [])):
            missing = required_fields - set(reader.fieldnames or [])
            raise ValueError(f"Missing required columns: {missing}")

        for i, row in enumerate(reader, start=1):
            if i > self.MAX_ROWS:
                break

            parsed = self._parse_row(i, row)
            rows.append(parsed)

        return rows

    def _parse_row(self, row_number: int, row: Dict[str, str]) -> CSVImportRow:
        """Parse a single CSV row."""
        errors = []
        warnings = []

        # Symbol
        symbol = row.get("symbol", "").strip().upper()
        if not symbol:
            errors.append("Symbol is required")

        # Side
        side = row.get("side", "").strip().lower()
        if side not in ("buy", "sell"):
            errors.append(f"Side must be 'buy' or 'sell', got '{side}'")

        # Quantity
        try:
            quantity = int(row.get("quantity", "0"))
            if quantity <= 0:
                errors.append("Quantity must be positive")
        except ValueError:
            errors.append("Quantity must be an integer")
            quantity = 0

        # Price
        try:
            price = float(row.get("price", "0"))
            if price <= 0:
                errors.append("Price must be positive")
        except ValueError:
            errors.append("Price must be a number")
            price = 0.0

        # Trade date
        trade_date_str = row.get("trade_date", "").strip()
        try:
            trade_date = date.fromisoformat(trade_date_str)
        except ValueError:
            errors.append(f"Invalid date format (use YYYY-MM-DD): {trade_date_str}")
            trade_date = date.today()

        # Fees (optional)
        fees = None
        fees_str = row.get("fees", "").strip()
        if fees_str:
            try:
                fees = float(fees_str)
                if fees < 0:
                    warnings.append("Fees should not be negative")
            except ValueError:
                warnings.append(f"Invalid fees value, ignoring: {fees_str}")

        # Note (optional)
        note = row.get("note", "").strip() or None

        status = ImportStatus.INVALID if errors else ImportStatus.VALID

        return CSVImportRow(
            row_number=row_number,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            trade_date=trade_date,
            fees=fees,
            note=note,
            status=status,
            errors=errors,
            warnings=warnings,
        )

    def validate_rows(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        rows: List[CSVImportRow],
    ) -> List[CSVImportRow]:
        """Validate rows against portfolio holdings and existing transactions."""
        # Get existing transactions for duplicate detection
        existing_txns = session.scalars(
            select(Transaction).where(Transaction.portfolio_id == portfolio_id)
        ).all()

        existing_keys = set()
        for txn in existing_txns:
            key = (txn.symbol, txn.side, txn.trade_date, txn.quantity, txn.price)
            existing_keys.add(key)

        # Get current holdings for sell validation
        holdings = session.scalars(
            select(Holding).where(Holding.portfolio_id == portfolio_id)
        ).all()
        holding_qty = {h.symbol: h.quantity for h in holdings}

        # Track pending sells per symbol to validate against available qty
        pending_sells = {}

        for row in rows:
            if row.status != ImportStatus.VALID:
                continue

            # Check symbol exists
            security = session.get(Security, row.symbol)
            if not security:
                row.status = ImportStatus.INVALID
                row.errors.append(f"Security {row.symbol} not found in reference data")
                continue

            # Duplicate detection
            key = (row.symbol, row.side, row.trade_date.isoformat(), row.quantity, row.price)
            if key in existing_keys:
                row.status = ImportStatus.DUPLICATE
                row.errors.append("Duplicate transaction (symbol+side+date+qty+price already exists)")
                continue

            # Check sell against available holdings
            if row.side == "sell":
                available = holding_qty.get(row.symbol, 0) - pending_sells.get(row.symbol, 0)
                if available < row.quantity:
                    row.status = ImportStatus.INSUFFICIENT_HOLDINGS
                    row.errors.append(
                        f"Insufficient holdings to sell {row.quantity} of {row.symbol} "
                        f"(available: {available})"
                    )
                    continue
                pending_sells[row.symbol] = pending_sells.get(row.symbol, 0) + row.quantity
            else:  # buy
                pending_sells[row.symbol] = pending_sells.get(row.symbol, 0)

        return rows

    def import_rows(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        rows: List[CSVImportRow],
        dry_run: bool = False,
    ) -> CSVImportResult:
        """Import validated rows into the portfolio."""
        valid_rows = [r for r in rows if r.status == ImportStatus.VALID]
        imported = 0

        if not dry_run:
            for row in valid_rows:
                txn = Transaction(
                    portfolio_id=portfolio_id,
                    symbol=row.symbol,
                    side=row.side,
                    quantity=row.quantity,
                    price=row.price,
                    trade_date=row.trade_date.isoformat(),
                    fees=row.fees,
                    note=row.note,
                )
                session.add(txn)
                session.flush()

                # Create ledger event
                self._ledger.create_event_from_transaction(session, txn, user_id)
                imported += 1

            if imported > 0:
                # Replay portfolio
                self._ledger.replay_portfolio(session, portfolio_id, user_id, triggered_by=user_id, trigger_reason="csv_import")
                session.commit()

        stats = {
            "total_rows": len(rows),
            "valid_rows": len([r for r in rows if r.status == ImportStatus.VALID]),
            "invalid_rows": len([r for r in rows if r.status == ImportStatus.INVALID]),
            "duplicate_rows": len([r for r in rows if r.status == ImportStatus.DUPLICATE]),
            "insufficient_holdings_rows": len([r for r in rows if r.status == ImportStatus.INSUFFICIENT_HOLDINGS]),
        }

        return CSVImportResult(
            total_rows=stats["total_rows"],
            valid_rows=stats["valid_rows"],
            invalid_rows=stats["invalid_rows"],
            duplicate_rows=stats["duplicate_rows"],
            insufficient_holdings_rows=stats["insufficient_holdings_rows"],
            rows=rows,
            imported_count=imported,
            dry_run=dry_run,
        )

    def import_csv(
        self,
        session: Session,
        portfolio_id: str,
        user_id: str,
        content: str,
        dry_run: bool = False,
    ) -> CSVImportResult:
        """Full CSV import pipeline: parse, validate, import."""
        rows = self.parse_csv(content)
        rows = self.validate_rows(session, portfolio_id, user_id, rows)
        return self.import_rows(session, portfolio_id, user_id, rows, dry_run)


def get_csv_template() -> str:
    """Get CSV template with headers and example row."""
    return "symbol,side,quantity,price,trade_date,fees,note\nNABIL,buy,100,500.0,2026-01-15,10.0,Initial purchase\n"