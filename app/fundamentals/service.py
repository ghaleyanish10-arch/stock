"""Fundamentals CSV import service."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import FundamentalsImport, FundamentalsImportRow, Security, User
from app.reference.service import ReferenceService


class FundamentalsImportService:
    """Service for importing fundamentals data from CSV."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service

    # Required columns in the CSV
    REQUIRED_COLUMNS = ["symbol", "fiscal_year", "quarter"]
    OPTIONAL_COLUMNS = ["revenue", "net_profit", "eps", "book_value_per_share"]

    def validate_csv(
        self,
        content: bytes,
        session: Session,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate CSV content and return (valid_rows, invalid_rows).
        
        Each row has: symbol, fiscal_year, quarter, revenue, net_profit, eps, book_value_per_share
        """
        # Decode CSV
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("CSV must be UTF-8 encoded")
        
        reader = csv.DictReader(io.StringIO(text))
        
        if not reader.fieldnames:
            raise ValueError("CSV has no headers")
        
        # Check required columns
        missing = set(self.REQUIRED_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")
        
        valid_rows = []
        invalid_rows = []
        
        for row_num, row in enumerate(reader, start=2):  # 1-indexed + header
            errors = []
            warnings = []
            
            # Validate required fields
            symbol = row.get("symbol", "").strip().upper()
            if not symbol:
                errors.append("Symbol is required")
            
            fiscal_year = row.get("fiscal_year", "").strip()
            if not fiscal_year:
                errors.append("Fiscal year is required")
            
            quarter_str = row.get("quarter", "").strip()
            quarter = None
            if quarter_str:
                try:
                    quarter = int(quarter_str)
                    if quarter not in (1, 2, 3, 4):
                        errors.append("Quarter must be 1, 2, 3, or 4")
                except ValueError:
                    errors.append("Quarter must be an integer")
            
            # Validate optional numeric fields
            revenue = self._parse_float(row.get("revenue"), "revenue", errors)
            net_profit = self._parse_float(row.get("net_profit"), "net_profit", errors)
            eps = self._parse_float(row.get("eps"), "eps", errors)
            book_value = self._parse_float(row.get("book_value_per_share"), "book_value_per_share", errors)
            
            # Check if symbol exists in NEPSE (if reference data available)
            if symbol:
                sec = session.get(Security, symbol)
                if not sec:
                    warnings.append(f"Symbol {symbol} not found in NEPSE securities")
            
            is_valid = len(errors) == 0
            
            if is_valid:
                valid_rows.append({
                    "symbol": symbol,
                    "fiscal_year": fiscal_year,
                    "quarter": quarter,
                    "revenue": revenue,
                    "net_profit": net_profit,
                    "eps": eps,
                    "book_value_per_share": book_value,
                    "raw_data": row,
                })
            else:
                invalid_rows.append({
                    "row_number": row_num,
                    "symbol": symbol,
                    "fiscal_year": fiscal_year,
                    "quarter": quarter,
                    "errors": errors,
                    "warnings": warnings,
                    "raw_data": row,
                })
        
        return valid_rows, invalid_rows

    def _parse_float(self, value: Optional[str], field_name: str, errors: List[str]) -> Optional[float]:
        """Parse a float value, return None if empty."""
        if value is None or value.strip() == "":
            return None
        try:
            return float(value.strip())
        except ValueError:
            errors.append(f"{field_name} must be a number")
            return None

    async def import_csv(
        self,
        session: Session,
        content: bytes,
        user_id: str,
        source_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import fundamentals from CSV."""
        from app.db.models import Security
        
        valid_rows, invalid_rows = self.validate_csv(content, session)
        
        # Create import record
        import_record = FundamentalsImport(
            symbol="",  # Will be set per row
            fiscal_year="",
            quarter=None,
            source="csv_import",
            source_file=source_file or "upload.csv",
            imported_by=user_id,
        )
        
        # We need to create one import per unique (symbol, fiscal_year, quarter)
        # Group valid rows by composite key
        from collections import defaultdict
        grouped = defaultdict(list)
        for row in valid_rows:
            key = (row["symbol"], row["fiscal_year"], row["quarter"])
            grouped[key].append(row)
        
        total_imported = 0
        total_updated = 0
        import_rows = []
        
        for (symbol, fiscal_year, quarter), rows in grouped.items():
            # Take the last row for this combination (last one wins)
            row = rows[-1]
            
            # Check if already exists
            existing = session.scalar(
                select(FundamentalsImport).where(
                    FundamentalsImport.symbol == symbol,
                    FundamentalsImport.fiscal_year == fiscal_year,
                    FundamentalsImport.quarter == quarter,
                )
            )
            
            if existing:
                existing.revenue = row["revenue"]
                existing.net_profit = row["net_profit"]
                existing.eps = row["eps"]
                existing.book_value_per_share = row["book_value_per_share"]
                existing.source = "csv_import"
                existing.source_file = source_file or "upload.csv"
                existing.row_number = row.get("row_number")
                existing.updated_at = datetime.utcnow()
                total_updated += 1
                import_id = existing.id
            else:
                import_record = FundamentalsImport(
                    symbol=symbol,
                    fiscal_year=fiscal_year,
                    quarter=quarter,
                    revenue=row["revenue"],
                    net_profit=row["net_profit"],
                    eps=row["eps"],
                    book_value_per_share=row["book_value_per_share"],
                    source="csv_import",
                    source_file=source_file or "upload.csv",
                    row_number=row.get("row_number"),
                    imported_by=user_id,
                )
                session.add(import_record)
                session.flush()
                import_id = import_record.id
                total_imported += 1
            
            # Create import row record
            import_rows.append(FundamentalsImportRow(
                import_id=import_id,
                row_number=rows[-1].get("row_number", 0),
                symbol=symbol,
                fiscal_year=fiscal_year,
                quarter=quarter,
                raw_data=rows[-1]["raw_data"],
                is_valid=True,
                errors=None,
                warnings=None,
            ))
        
        # Add invalid rows
        for row in invalid_rows:
            import_rows.append(FundamentalsImportRow(
                import_id=None,  # Will be set after flush
                row_number=row["row_number"],
                symbol=row["symbol"],
                fiscal_year=row["fiscal_year"],
                quarter=row["quarter"],
                raw_data=row["raw_data"],
                is_valid=False,
                errors=row["errors"],
                warnings=row["warnings"],
            ))
        
        session.add_all(import_rows)
        session.commit()
        
        return {
            "imported": total_imported,
            "updated": total_updated,
            "invalid_rows": len(invalid_rows),
            "total_rows": len(valid_rows) + len(invalid_rows),
        }

    def list_imports(
        self,
        session: Session,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List recent imports."""
        imports = list(
            session.scalars(
                select(FundamentalsImport)
                .order_by(FundamentalsImport.imported_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = session.scalar(
            select(func.count()).select_from(FundamentalsImport)
        )
        
        return {
            "imports": [
                {
                    "id": imp.id,
                    "symbol": imp.symbol,
                    "fiscal_year": imp.fiscal_year,
                    "quarter": imp.quarter,
                    "source_file": imp.source_file,
                    "imported_at": imp.imported_at.isoformat() if imp.imported_at else None,
                    "imported_by": imp.imported_by,
                }
                for imp in imports
            ],
            "total": total or 0,
            "limit": limit,
            "offset": offset,
        }

    def get_import_details(
        self,
        session: Session,
        import_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get details of a specific import."""
        imp = session.get(FundamentalsImport, import_id)
        if not imp:
            return None
        
        rows = list(
            session.scalars(
                select(FundamentalsImportRow)
                .where(FundamentalsImportRow.import_id == import_id)
                .order_by(FundamentalsImportRow.row_number)
            )
        )
        
        return {
            "id": imp.id,
            "symbol": imp.symbol,
            "fiscal_year": imp.fiscal_year,
            "quarter": imp.quarter,
            "revenue": imp.revenue,
            "net_profit": imp.net_profit,
            "eps": imp.eps,
            "book_value_per_share": imp.book_value_per_share,
            "source": imp.source,
            "source_file": imp.source_file,
            "imported_at": imp.imported_at.isoformat() if imp.imported_at else None,
            "imported_by": imp.imported_by,
            "rows": [
                {
                    "row_number": r.row_number,
                    "symbol": r.symbol,
                    "fiscal_year": r.fiscal_year,
                    "quarter": r.quarter,
                    "is_valid": r.is_valid,
                    "errors": r.errors,
                    "warnings": r.warnings,
                }
                for r in rows
            ],
        }


