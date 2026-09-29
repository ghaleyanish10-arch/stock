"""Alert API routes."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, DbSession
from app.alerts.service import AlertService
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

_alerts = AlertService(ReferenceService(get_adapter()))


# --- Channels ---


@router.post("/channels", summary="Create notification channel")
def create_channel(
    session: DbSession,
    user: CurrentUser,
    channel_type: str,  # email, telegram, in_app
    config: dict,
) -> dict:
    channel = _alerts.create_channel(session, user.id, channel_type, config)
    return {
        "id": channel.id,
        "type": channel.channel_type,
        "config": channel.config,
        "is_active": channel.is_active,
        "is_verified": channel.is_verified,
    }


@router.get("/channels", summary="List notification channels")
def list_channels(
    session: DbSession,
    user: CurrentUser,
) -> dict:
    channels = _alerts.get_channels(session, user.id)
    return {
        "channels": [
            {
                "id": c.id,
                "type": c.channel_type,
                "config": c.config,
                "is_active": c.is_active,
                "is_verified": c.is_verified,
                "verified_at": c.verified_at.isoformat() if c.verified_at else None,
            }
            for c in channels
        ]
    }


@router.patch("/channels/{channel_id}", summary="Update notification channel")
def update_channel(
    channel_id: str,
    session: DbSession,
    user: CurrentUser,
    config: Optional[dict] = None,
    is_active: Optional[bool] = None,
) -> dict:
    channel = _alerts.update_channel(session, channel_id, user.id, config, is_active)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return {
        "id": channel.id,
        "type": channel.channel_type,
        "config": channel.config,
        "is_active": channel.is_active,
        "is_verified": channel.is_verified,
    }


@router.delete("/channels/{channel_id}", summary="Delete notification channel")
def delete_channel(
    channel_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _alerts.delete_channel(session, channel_id, user.id)
    if not deleted:
        raise HTTPException(404, "Channel not found")
    return {"detail": "Channel deleted"}


# --- Rules ---


@router.post("/rules", summary="Create alert rule")
def create_rule(
    session: DbSession,
    user: CurrentUser,
    kind: str,  # price_above, price_below, pct_change, volume_spike, etc.
    symbol: Optional[str] = None,
    params: dict = {},
    channel_id: Optional[str] = None,
    cooldown_seconds: int = 300,
    is_one_shot: bool = False,
) -> dict:
    try:
        rule = _alerts.create_rule(
            session, user.id, kind, symbol, params, channel_id, cooldown_seconds, is_one_shot
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "id": rule.id,
        "kind": rule.kind,
        "symbol": rule.symbol,
        "params": rule.params,
        "channel_id": rule.channel_id,
        "cooldown_seconds": rule.cooldown_seconds,
        "is_one_shot": rule.is_one_shot,
        "is_active": rule.is_active,
    }


@router.get("/rules", summary="List user's alert rules")
def list_rules(
    session: DbSession,
    user: CurrentUser,
) -> dict:
    rules = _alerts.get_rules(session, user.id)
    return {
        "rules": [
            {
                "id": r.id,
                "kind": r.kind,
                "symbol": r.symbol,
                "params": r.params,
                "channel_id": r.channel_id,
                "cooldown_seconds": r.cooldown_seconds,
                "is_one_shot": r.is_one_shot,
                "is_active": r.is_active,
                "trigger_count": r.trigger_count,
                "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rules
        ]
    }


@router.get("/rules/{rule_id}", summary="Get alert rule")
def get_rule(
    rule_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    rule = _alerts.get_rule(session, rule_id, user.id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return {
        "id": rule.id,
        "kind": rule.kind,
        "symbol": rule.symbol,
        "params": rule.params,
        "channel_id": rule.channel_id,
        "cooldown_seconds": rule.cooldown_seconds,
        "is_one_shot": rule.is_one_shot,
        "is_active": rule.is_active,
        "trigger_count": rule.trigger_count,
        "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


@router.patch("/rules/{rule_id}", summary="Update alert rule")
def update_rule(
    rule_id: str,
    session: DbSession,
    user: CurrentUser,
    **updates: Any,
) -> dict:
    rule = _alerts.update_rule(session, rule_id, user.id, **updates)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return {
        "id": rule.id,
        "kind": rule.kind,
        "symbol": rule.symbol,
        "params": rule.params,
        "channel_id": rule.channel_id,
        "cooldown_seconds": rule.cooldown_seconds,
        "is_one_shot": rule.is_one_shot,
        "is_active": rule.is_active,
    }


@router.delete("/rules/{rule_id}", summary="Delete alert rule")
def delete_rule(
    rule_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _alerts.delete_rule(session, rule_id, user.id)
    if not deleted:
        raise HTTPException(404, "Rule not found")
    return {"detail": "Rule deleted"}


@router.get("/rules/{rule_id}/events", summary="Get alert rule trigger history")
def get_rule_events(
    rule_id: str,
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    rule = _alerts.get_rule(session, rule_id, user.id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    events = _alerts.get_rule_events(session, rule_id, user.id, limit)
    return {
        "events": [
            {
                "id": e.id,
                "symbol": e.symbol,
                "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
                "triggered_params": e.triggered_params,
                "trigger_value": e.trigger_value,
                "delivery_status": e.delivery_status,
            }
            for e in events
        ]
    }


# --- Notification Channels ---


@router.post("/channels", summary="Add notification channel")
def create_channel(
    session: DbSession,
    user: CurrentUser,
    channel_type: str,  # email, telegram, in_app
    config: dict,
) -> dict:
    channel = _alerts.create_channel(session, user.id, channel_type, config)
    return {
        "id": channel.id,
        "type": channel.channel_type,
        "config": channel.config,
        "is_active": channel.is_active,
        "is_verified": channel.is_verified,
    }


@router.get("/channels", summary="List notification channels")
def list_channels(
    session: DbSession,
    user: CurrentUser,
) -> dict:
    channels = _alerts.get_channels(session, user.id)
    return {
        "channels": [
            {
                "id": c.id,
                "type": c.channel_type,
                "config": c.config,
                "is_active": c.is_active,
                "is_verified": c.is_verified,
                "verified_at": c.verified_at.isoformat() if c.verified_at else None,
            }
            for c in channels
        ]
    }


@router.patch("/channels/{channel_id}", summary="Update notification channel")
def update_channel(
    channel_id: str,
    session: DbSession,
    user: CurrentUser,
    config: Optional[dict] = None,
    is_active: Optional[bool] = None,
) -> dict:
    channel = _alerts.update_channel(session, channel_id, user.id, config, is_active)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return {
        "id": channel.id,
        "type": channel.channel_type,
        "config": channel.config,
        "is_active": channel.is_active,
        "is_verified": channel.is_verified,
    }


@router.delete("/channels/{channel_id}", summary="Delete notification channel")
def delete_channel(
    channel_id: str,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    deleted = _alerts.delete_channel(session, channel_id, user.id)
    if not deleted:
        raise HTTPException(404, "Channel not found")
    return {"detail": "Channel deleted"}


# --- Evaluation (for testing) ---


@router.post("/evaluate", summary="Manually evaluate a rule (for testing)")
def evaluate_rule(
    session: DbSession,
    user: CurrentUser,
    kind: str,
    symbol: str,
    params: dict,
) -> dict:
    """Evaluate a rule manually without creating it."""
    from app.db.models import AlertRule

    # Create a temporary rule object
    rule = AlertRule(
        user_id=user.id,
        kind=kind,
        symbol=symbol.upper(),
        params=params,
        is_active=True,
    )

    _alerts = AlertService(ReferenceService(get_adapter()))
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        result = _alerts.evaluate_rule(session, rule)
    finally:
        session.close()
    return {"triggered": result is not None, "result": result}