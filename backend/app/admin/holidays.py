"""Admin API routes for the holiday calendar (WP1).

A separate router from fee/tax rates so each admin resource has its own
prefix: `/api/admin/holidays`. All endpoints are admin-only (AdminUser
dependency) — the calendar is reference data, and public read access goes
through `/api/reference/calendar` instead.
"""

from __future__ import annotations

import csv
import io
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import AdminUser, DbSession
from app.db.models import Holiday

router = APIRouter(prefix="/api/admin/holidays", tags=["admin"], redirect_slashes=True)


class HolidayUpsert(BaseModel):
    # NOTE: annotated with the aliased import because the field is named
    # `date`; under `from __future__ import annotations` pydantic would
    # otherwise resolve the string "date" against the class namespace.
    date: _date = Field(..., description="ISO holiday date")
    name: str = Field(..., min_length=1, max_length=200)
    is_half_day: bool = Field(default=False)
    source: str = Field(default="manual", max_length=64)
    source_url: Optional[str] = Field(default=None, max_length=500)
    verification_status: str = Field(
        default="unverified", description="verified or unverified"
    )


def _holiday_dict(h: Holiday) -> dict:
    return {
        "date": h.date,
        "name": h.name,
        "is_half_day": h.is_half_day,
        "source": h.source,
        "source_url": h.source_url,
        "verification_status": h.verification_status,
    }


@router.get("", summary="List holidays (admin)")
def list_holidays(
    session: DbSession,
    user: AdminUser,
    year: Optional[int] = None,
) -> dict:
    """List holiday rows, optionally filtered to a calendar year."""
    stmt = select(Holiday).order_by(Holiday.date)
    if year is not None:
        stmt = stmt.where(Holiday.date >= f"{year}-01-01", Holiday.date <= f"{year}-12-31")
    rows = session.execute(stmt).scalars().all()
    return {"holidays": [_holiday_dict(h) for h in rows], "count": len(rows)}


@router.put("", summary="Create or update a holiday (admin)")
def upsert_holiday(
    payload: HolidayUpsert,
    session: DbSession,
    user: AdminUser,
) -> dict:
    """Create or update one holiday row. Idempotent on the date key."""
    if payload.verification_status not in ("verified", "unverified"):
        raise HTTPException(422, "verification_status must be verified or unverified")
    iso = payload.date.isoformat()
    row = session.get(Holiday, iso)
    if row is None:
        row = Holiday(date=iso)
        session.add(row)
    row.name = payload.name
    row.is_half_day = payload.is_half_day
    row.source = payload.source
    row.source_url = payload.source_url
    row.verification_status = payload.verification_status
    session.commit()
    return _holiday_dict(row)


@router.delete("/{iso_date}", summary="Delete a holiday (admin)")
def delete_holiday(iso_date: str, session: DbSession, user: AdminUser) -> dict:
    row = session.get(Holiday, iso_date)
    if not row:
        raise HTTPException(404, "Holiday not found")
    session.delete(row)
    session.commit()
    return {"detail": "Holiday deleted"}


@router.post("/import", summary="Bulk CSV holiday import (admin)")
async def import_holidays_csv(
    session: DbSession,
    user: AdminUser,
    file: UploadFile = File(
        ...,
        description="CSV with header date,name[,is_half_day,source,source_url,verification_status]",
    ),
    mark: str = Query(
        "unverified", description="Default verification status for rows without one"
    ),
) -> dict:
    """Bulk import holidays from CSV.

    Header: `date,name[,is_half_day,source,source_url,verification_status]`.
    Rows are upserted (idempotent). Row-level errors are reported per line and
    good rows are still imported — a single bad line does not reject the file.
    """
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV has no header row")
    fields = {f.strip().lower() for f in reader.fieldnames}
    if "date" not in fields or "name" not in fields:
        raise HTTPException(422, 'CSV must have "date" and "name" columns')

    imported, errors = 0, []
    for lineno, r in enumerate(reader, start=2):
        try:
            d = str(r.get("date") or "").strip()
            name = str(r.get("name") or "").strip()
            if not d or not name:
                raise ValueError("date and name are required")
            parsed = _date.fromisoformat(d)
            iso = parsed.isoformat()
            half = str(r.get("is_half_day") or "").strip().lower() in ("1", "true", "yes")
            source = str(r.get("source") or "").strip() or "csv_import"
            url = str(r.get("source_url") or "").strip() or None
            status = str(r.get("verification_status") or mark).strip().lower()
            if status not in ("verified", "unverified"):
                raise ValueError("verification_status must be verified or unverified")
            row = session.get(Holiday, iso)
            if row is None:
                row = Holiday(date=iso)
                session.add(row)
            row.name = name
            row.is_half_day = half
            row.source = source
            row.source_url = url
            row.verification_status = status
            # Commit per row: a later bad row must not roll back earlier good
            # rows (a whole-transaction rollback here discarded them).
            session.commit()
            imported += 1
        except Exception as exc:  # noqa: BLE001 — row-level error reporting
            session.rollback()
            errors.append({"line": lineno, "error": str(exc)})
    return {"imported": imported, "errors": errors, "count": imported + len(errors)}
