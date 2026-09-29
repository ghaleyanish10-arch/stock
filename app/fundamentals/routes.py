"""Fundamentals CSV import routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.fundamentals.service import FundamentalsImportService
from app.reference.service import ReferenceService
from app.nepse.registry import get_adapter

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])

_fundamentals = FundamentalsImportService(ReferenceService(get_adapter()))


@router.post("/import", summary="Import fundamentals from CSV (admin)")
async def import_fundamentals(
    session: DbSession,
    user: AdminUser,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Import fundamentals data from CSV file. Admin only.
    
    CSV must have columns: symbol, fiscal_year, quarter
    Optional columns: revenue, net_profit, eps, book_value_per_share
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")
    
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    
    try:
        result = await _fundamentals.import_csv(
            session,
            content,
            user.id,
            source_file=file.filename,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Import failed: {str(e)}")


@router.get("/imports", summary="List recent fundamentals imports (admin)")
def list_imports(
    session: DbSession,
    user: AdminUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """List recent fundamentals imports. Admin only."""
    return _fundamentals.list_imports(session, limit, offset)


@router.get("/imports/{import_id}", summary="Get import details (admin)")
def get_import_details(
    import_id: str,
    session: DbSession,
    user: AdminUser,
) -> dict:
    """Get details of a specific import including row-level validation results."""
    details = _fundamentals.get_import_details(session, import_id)
    if not details:
        raise HTTPException(404, "Import not found")
    return details