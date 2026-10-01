"""Admin API routes for fee/tax rate management."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from app.auth.deps import AdminUser, DbSession
from app.db.models import FeeTaxRate

router = APIRouter(prefix="/api/admin/fee-tax-rates", tags=["admin"], redirect_slashes=True)


class FeeTaxRateCreate(BaseModel):
    rate_type: str = Field(..., min_length=1, max_length=64, description="Rate type identifier")
    rate_value: float = Field(..., description="Rate value (e.g., 0.00275 for 0.275%)")
    rate_unit: str = Field(default="percent", description="Unit: percent, per_transaction, fixed_rs")
    applies_to: str = Field(default="all", description="Applies to: individual, entity, all")
    description: Optional[str] = Field(default=None, max_length=500)
    source: str = Field(..., min_length=1, max_length=32, description="Source: sebon, ird, nepse, cds, cds_clearing")
    source_url: Optional[str] = Field(default=None, max_length=500)
    verification_status: str = Field(default="unverified", description="verified or unverified")
    effective_from: date
    effective_to: Optional[date] = None


class FeeTaxRateUpdate(BaseModel):
    rate_value: Optional[float] = None
    rate_unit: Optional[str] = None
    applies_to: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    verification_status: Optional[str] = None
    effective_to: Optional[date] = None


class FeeTaxRateResponse(BaseModel):
    id: str
    rate_type: str
    rate_value: float
    rate_unit: str
    applies_to: str
    description: Optional[str]
    source: str
    source_url: Optional[str]
    verification_status: str
    probe_date: Optional[str]
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str


@router.get("", summary="List all fee/tax rates (admin)")
def list_rates(
    session: DbSession,
    user: AdminUser,
    rate_type: Optional[str] = None,
    active_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List all fee/tax rates with optional filtering."""
    stmt = select(FeeTaxRate).order_by(FeeTaxRate.effective_from.desc())
    
    if rate_type:
        stmt = stmt.where(FeeTaxRate.rate_type == rate_type)
    
    if active_only:
        today = date.today()
        stmt = stmt.where(
            and_(
                FeeTaxRate.effective_from <= today,
                or_(FeeTaxRate.effective_to.is_(None), FeeTaxRate.effective_to > today),
            )
        )
    
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rates = list(session.scalars(stmt.limit(limit).offset(offset)))
    
    return {
        "total": total,
        "rates": [
            {
                "id": r.id,
                "rate_type": r.rate_type,
                "rate_value": r.rate_value,
                "rate_unit": r.rate_unit,
                "applies_to": r.applies_to,
                "description": r.description,
                "source": r.source,
                "source_url": r.source_url,
                "verification_status": r.verification_status,
                "probe_date": r.probe_date.isoformat() if r.probe_date else None,
                "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                "effective_to": r.effective_to.isoformat() if r.effective_to else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rates
        ],
    }


@router.post("", summary="Create fee/tax rate (admin)")
def create_rate(
    session: DbSession,
    user: AdminUser,
    request: FeeTaxRateCreate,
) -> FeeTaxRateResponse:
    """Create a new fee/tax rate."""
    # Validate rate_type is not duplicate for same effective_from
    existing = session.scalar(
        select(FeeTaxRate).where(
            and_(
                FeeTaxRate.rate_type == request.rate_type,
                FeeTaxRate.effective_from == request.effective_from,
            )
        )
    )
    if existing:
        raise HTTPException(409, f"Rate type {request.rate_type} already exists for effective date {request.effective_from}")
    
    rate = FeeTaxRate(
        rate_type=request.rate_type,
        rate_value=request.rate_value,
        rate_unit=request.rate_unit,
        applies_to=request.applies_to,
        description=request.description,
        source=request.source,
        source_url=request.source_url,
        verification_status=request.verification_status,
        effective_from=request.effective_from,
        effective_to=request.effective_to,
    )
    session.add(rate)
    session.commit()
    session.refresh(rate)
    
    return FeeTaxRateResponse(
        id=rate.id,
        rate_type=rate.rate_type,
        rate_value=rate.rate_value,
        rate_unit=rate.rate_unit,
        applies_to=rate.applies_to,
        description=rate.description,
        source=rate.source,
        source_url=rate.source_url,
        verification_status=rate.verification_status,
        probe_date=rate.probe_date.isoformat() if rate.probe_date else None,
        effective_from=rate.effective_from.isoformat() if rate.effective_from else None,
        effective_to=rate.effective_to.isoformat() if rate.effective_to else None,
        created_at=rate.created_at.isoformat() if rate.created_at else None,
        updated_at=rate.updated_at.isoformat() if rate.updated_at else None,
    )


@router.get("/{rate_id}", summary="Get fee/tax rate (admin)")
def get_rate(
    rate_id: str,
    session: DbSession,
    user: AdminUser,
) -> FeeTaxRateResponse:
    """Get a specific fee/tax rate."""
    rate = session.get(FeeTaxRate, rate_id)
    if not rate:
        raise HTTPException(404, "Rate not found")
    
    return FeeTaxRateResponse(
        id=rate.id,
        rate_type=rate.rate_type,
        rate_value=rate.rate_value,
        rate_unit=rate.rate_unit,
        applies_to=rate.applies_to,
        description=rate.description,
        source=rate.source,
        source_url=rate.source_url,
        verification_status=rate.verification_status,
        probe_date=rate.probe_date.isoformat() if rate.probe_date else None,
        effective_from=rate.effective_from.isoformat() if rate.effective_from else None,
        effective_to=rate.effective_to.isoformat() if rate.effective_to else None,
        created_at=rate.created_at.isoformat() if rate.created_at else None,
        updated_at=rate.updated_at.isoformat() if rate.updated_at else None,
    )


@router.patch("/{rate_id}", summary="Update fee/tax rate (admin)")
def update_rate(
    rate_id: str,
    session: DbSession,
    user: AdminUser,
    request: FeeTaxRateUpdate,
) -> FeeTaxRateResponse:
    """Update a fee/tax rate. Does not recompute fees on existing transactions."""
    rate = session.get(FeeTaxRate, rate_id)
    if not rate:
        raise HTTPException(404, "Rate not found")
    
    # Only allow updating certain fields
    if request.rate_value is not None:
        rate.rate_value = request.rate_value
    if request.rate_unit is not None:
        rate.rate_unit = request.rate_unit
    if request.applies_to is not None:
        rate.applies_to = request.applies_to
    if request.description is not None:
        rate.description = request.description
    if request.source is not None:
        rate.source = request.source
    if request.source_url is not None:
        rate.source_url = request.source_url
    if request.verification_status is not None:
        rate.verification_status = request.verification_status
    if request.effective_to is not None:
        rate.effective_to = request.effective_to
    
    rate.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(rate)
    
    return FeeTaxRateResponse(
        id=rate.id,
        rate_type=rate.rate_type,
        rate_value=rate.rate_value,
        rate_unit=rate.rate_unit,
        applies_to=rate.applies_to,
        description=rate.description,
        source=rate.source,
        source_url=rate.source_url,
        verification_status=rate.verification_status,
        probe_date=rate.probe_date.isoformat() if rate.probe_date else None,
        effective_from=rate.effective_from.isoformat() if rate.effective_from else None,
        effective_to=rate.effective_to.isoformat() if rate.effective_to else None,
        created_at=rate.created_at.isoformat() if rate.created_at else None,
        updated_at=rate.updated_at.isoformat() if rate.updated_at else None,
    )


@router.delete("/{rate_id}", summary="Delete fee/tax rate (admin)")
def delete_rate(
    rate_id: str,
    session: DbSession,
    user: AdminUser,
) -> dict:
    """Delete a fee/tax rate. Does not affect existing transactions."""
    rate = session.get(FeeTaxRate, rate_id)
    if not rate:
        raise HTTPException(404, "Rate not found")
    
    session.delete(rate)
    session.commit()
    return {"detail": "Rate deleted"}


@router.post("/{rate_id}/verify", summary="Mark rate as verified (admin)")
def verify_rate(
    rate_id: str,
    session: DbSession,
    user: AdminUser,
) -> FeeTaxRateResponse:
    """Mark a rate as verified with current probe date."""
    rate = session.get(FeeTaxRate, rate_id)
    if not rate:
        raise HTTPException(404, "Rate not found")
    
    rate.verification_status = "verified"
    rate.probe_date = datetime.utcnow()
    rate.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(rate)
    
    return FeeTaxRateResponse(
        id=rate.id,
        rate_type=rate.rate_type,
        rate_value=rate.rate_value,
        rate_unit=rate.rate_unit,
        applies_to=rate.applies_to,
        description=rate.description,
        source=rate.source,
        source_url=rate.source_url,
        verification_status=rate.verification_status,
        probe_date=rate.probe_date.isoformat() if rate.probe_date else None,
        effective_from=rate.effective_from.isoformat() if rate.effective_from else None,
        effective_to=rate.effective_to.isoformat() if rate.effective_to else None,
        created_at=rate.created_at.isoformat() if rate.created_at else None,
        updated_at=rate.updated_at.isoformat() if rate.updated_at else None,
    )


# Add func import
from sqlalchemy import func