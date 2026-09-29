"""Alert service: manages alert rules and evaluation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.db.models import (
    AlertRule,
    AlertEvent,
    AlertChannel,
    Security,
    DailyBar,
    User,
)
from app.nepse.registry import get_adapter
from app.reference.service import ReferenceService


class AlertService:
    """Manages alert rules and evaluation."""

    def __init__(self, reference_service: ReferenceService):
        self._reference = reference_service
        self._adapter = get_adapter()
        self._evaluation_task: Optional[asyncio.Task] = None
        self._running = False

    # --- Channel CRUD ---

    def create_channel(
        self,
        session: "Session",
        user_id: str,
        channel_type: str,  # "email", "telegram", "in_app"
        config: Dict[str, Any],
    ) -> "AlertChannel":
        """Create a notification channel."""
        from app.db.models import AlertChannel
        channel = AlertChannel(
            user_id=user_id,
            channel_type=channel_type,
            config=config,
        )
        session.add(channel)
        session.commit()
        session.refresh(channel)
        return channel

    def get_channels(self, session: "Session", user_id: str) -> List["AlertChannel"]:
        """List user's notification channels."""
        from app.db.models import AlertChannel
        return list(
            session.scalars(
                select(AlertChannel)
                .where(AlertChannel.user_id == user_id)
                .order_by(AlertChannel.created_at.desc())
            )
        )

    def update_channel(
        self,
        session: "Session",
        channel_id: str,
        user_id: str,
        config: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None,
    ) -> Optional["AlertChannel"]:
        """Update channel settings."""
        from app.db.models import AlertChannel
        channel = session.get(AlertChannel, channel_id)
        if not channel or channel.user_id != user_id:
            return None
        if config is not None:
            channel.config = config
        if is_active is not None:
            channel.is_active = is_active
        channel.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(channel)
        return channel

    def delete_channel(self, session: "Session", channel_id: str, user_id: str) -> bool:
        from app.db.models import AlertChannel
        channel = session.get(AlertChannel, channel_id)
        if not channel or channel.user_id != user_id:
            return False
        session.delete(channel)
        session.commit()
        return True

    # --- Rule CRUD ---

    def create_rule(
        self,
        session: "Session",
        user_id: str,
        kind: str,
        symbol: Optional[str],
        params: Dict[str, Any],
        channel_id: Optional[str] = None,
        cooldown_seconds: int = 300,
        is_one_shot: bool = False,
    ) -> "AlertRule":
        """Create an alert rule."""
        from app.db.models import AlertRule
        rule = AlertRule(
            user_id=user_id,
            channel_id=channel_id,
            kind=kind,
            symbol=symbol.upper() if symbol else None,
            params=params,
            cooldown_seconds=cooldown_seconds,
            is_one_shot=is_one_shot,
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        return rule

    def get_rules(self, session: "Session", user_id: str) -> List["AlertRule"]:
        from app.db.models import AlertRule
        return list(
            session.scalars(
                select(AlertRule)
                .where(AlertRule.user_id == user_id)
                .order_by(AlertRule.created_at.desc())
            )
        )

    def get_rule(self, session: "Session", rule_id: str, user_id: str) -> Optional["AlertRule"]:
        from app.db.models import AlertRule
        rule = session.get(AlertRule, rule_id)
        if rule and rule.user_id == user_id:
            return rule
        return None

    def update_rule(
        self,
        session: "Session",
        rule_id: str,
        user_id: str,
        **updates: Any,
    ) -> Optional["AlertRule"]:
        from app.db.models import AlertRule
        rule = session.get(AlertRule, rule_id)
        if not rule or rule.user_id != user_id:
            return None
        for key, value in updates.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        rule.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(rule)
        return rule

    def delete_rule(self, session: "Session", rule_id: str, user_id: str) -> bool:
        from app.db.models import AlertRule
        rule = session.get(AlertRule, rule_id)
        if not rule or rule.user_id != user_id:
            return False
        session.delete(rule)
        session.commit()
        return True

    def get_rule_events(
        self,
        session: "Session",
        rule_id: str,
        user_id: str,
        limit: int = 100,
    ) -> List["AlertEvent"]:
        from app.db.models import AlertEvent
        return list(
            session.scalars(
                select(AlertEvent)
                .where(AlertEvent.rule_id == rule_id, AlertEvent.user_id == user_id)
                .order_by(AlertEvent.triggered_at.desc())
                .limit(limit)
            )
        )

    # --- Rule Evaluation ---

    def evaluate_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate a single rule and return trigger info if triggered."""
        if not rule.is_active:
            return None

        # Check cooldown
        if rule.last_triggered_at:
            if datetime.utcnow() - rule.last_triggered_at < timedelta(seconds=rule.cooldown_seconds):
                return None

        symbol = rule.symbol
        if not symbol:
            return None

        kind = rule.kind
        params = rule.params

        # Get current price/data
        try:
            if kind in ("price_above", "price_below", "pct_change"):
                return self._evaluate_price_rule(session, rule)
            elif kind == "volume_spike":
                return self._evaluate_volume_rule(session, rule)
            elif kind in ("rsi_above", "rsi_below", "rsi_cross"):
                return self._evaluate_rsi_rule(session, rule)
            elif kind in ("macd_cross", "macd_signal_cross"):
                return self._evaluate_macd_rule(session, rule)
            elif kind == "announcement":
                return self._evaluate_announcement_rule(session, rule)
            elif kind in ("book_closure", "agm_approaching"):
                return self._evaluate_corporate_action_rule(session, rule)
        except Exception as e:
            # Log error but don't crash the evaluation loop
            return None

        return None

    def _evaluate_price_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate price-based rules."""
        symbol = rule.symbol
        params = rule.params
        threshold = params.get("threshold")
        if threshold is None:
            return None

        # Get latest price
        try:
            price_data = self._reference._client.call(
                f"stock:{symbol}",
                lambda: self._reference._client.get_stock_info(symbol),
            )
        except Exception:
            return None

        if not price_data:
            return None

        current_price = price_data.get("last_traded_price") or price_data.get("close_price")
        if current_price is None:
            return None

        kind = rule.kind
        triggered = False
        message = ""

        if kind == "price_above" and current_price > threshold:
            triggered = True
            message = f"{rule.symbol} price {current_price} crossed above {threshold}"
        elif kind == "price_below" and current_price < threshold:
            triggered = True
            message = f"{rule.symbol} price {current_price} dropped below {threshold}"
        elif kind == "pct_change":
            # Need previous close
            prev_close = None
            # Would need previous close from archive
            # For now, just return None if we can't compute
            return None

        if triggered:
            return {
                "triggered": True,
                "message": message,
                "value": current_price,
                "threshold": threshold,
            }
        return None

    def _evaluate_volume_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate volume spike rule."""
        symbol = rule.symbol
        params = rule.params
        threshold = params.get("threshold", 2.0)  # 2x average volume

        # Get recent volume data
        from app.db.models import DailyBar
        bars = session.scalars(
            select(DailyBar)
            .where(DailyBar.symbol == rule.symbol)
            .order_by(DailyBar.business_date.desc())
            .limit(21)
        ).all()

        if len(bars) < 2:
            return None

        volumes = [b.volume for b in bars if b.volume]
        if len(volumes) < 2:
            return None

        current_volume = volumes[0]
        avg_volume = sum(volumes[1:]) / len(volumes[1:]) if len(volumes) > 1 else 0

        if avg_volume > 0 and current_volume >= avg_volume * threshold:
            return {
                "triggered": True,
                "message": f"{rule.symbol} volume {current_volume:,} is {current_volume/avg_volume:.1f}x 20-day average",
                "value": current_volume,
                "threshold": avg_volume * threshold,
            }
        return None

    def _evaluate_rsi_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate RSI-based rules."""
        # RSI evaluation would need indicator data
        # For now, return None - would need indicator calculation
        return None

    def _evaluate_macd_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate MACD crossover rules."""
        # MACD evaluation would need indicator data
        return None

    def _evaluate_announcement_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate new announcement rules."""
        from app.db.models import Announcement
        symbol = rule.symbol
        params = rule.params
        announcement_types = params.get("types", ["dividend", "bonus", "rights", "agm", "book_closure"])

        # Check for new announcements since last check
        since = rule.last_triggered_at or datetime.utcnow() - timedelta(days=1)
        announcements = session.scalars(
            select(Announcement)
            .where(
                Announcement.symbol == rule.symbol,
                Announcement.published_at > since,
                Announcement.news_type.in_(announcement_types),
            )
        ).all()

        if announcements:
            ann = announcements[0]
            return {
                "triggered": True,
                "message": f"New announcement for {rule.symbol}: {ann.headline}",
                "headline": ann.headline,
                "type": ann.news_type,
                "published_at": ann.published_at.isoformat() if ann.published_at else None,
            }
        return None

    def _evaluate_corporate_action_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate upcoming book closure/AGM rules."""
        from app.db.models import CorporateAction
        from datetime import date, timedelta

        symbol = rule.symbol
        params = rule.params
        days_ahead = params.get("days_ahead", 7)
        event_types = params.get("types", ["book_closure", "agm"])

        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        query = select(CorporateAction).where(
            CorporateAction.symbol == rule.symbol,
        )

        if "book_closure" in event_types:
            query = query.where(
                CorporateAction.book_close.is_not(None),
                CorporateAction.book_close >= date.today().isoformat(),
                CorporateAction.book_close <= end_date.isoformat(),
            )

        actions = session.scalars(query).all()

        for ca in actions:
            for event_type in event_types:
                event_date = ca.book_close if event_type == "book_closure" else ca.agm_date
                if event_date and today <= event_date <= end_date:
                    return {
                        "triggered": True,
                        "message": f"{rule.symbol} {event_type.replace('_', ' ').title()} on {event_date}",
                        "event_type": event_type,
                        "date": event_date,
                        "fiscal_year": ca.fiscal_year,
                    }
        return None

    # --- Background Evaluation Loop ---

    async def start_evaluation_loop(self, interval_seconds: int = 30):
        """Start the background evaluation loop."""
        if self._running:
            return
        self._running = True
        self._evaluation_task = asyncio.create_task(self._evaluation_loop(interval_seconds))

    async def stop_evaluation_loop(self):
        """Stop the background evaluation loop."""
        self._running = False
        if self._evaluation_task:
            self._evaluation_task.cancel()
            try:
                await self._evaluation_task
            except asyncio.CancelledError:
                pass

    async def _evaluation_loop(self, interval_seconds: int):
        """Background loop that evaluates all active rules."""
        from app.db.session import SessionLocal
        from app.db.models import AlertRule

        while self._running:
            try:
                session = SessionLocal()
                try:
                    # Get all active rules
                    rules = session.scalars(
                        select(AlertRule).where(AlertRule.is_active == True)
                    ).all()

                    for rule in rules:
                        try:
                            result = self.evaluate_rule(session, rule)
                            if result:
                                # Create alert event
                                from app.db.models import AlertEvent
                                event = AlertEvent(
                                    rule_id=rule.id,
                                    user_id=rule.user_id,
                                    symbol=rule.symbol,
                                    triggered_params=rule.params,
                                    trigger_value=result.get("value"),
                                    delivery_status={},
                                )
                                session.add(event)

                                # Update rule
                                rule.last_triggered_at = datetime.utcnow()
                                rule.trigger_count += 1
                                if rule.is_one_shot:
                                    rule.is_active = False
                                session.commit()

                                # TODO: Send notifications via channels
                        except Exception as e:
                            # Log error but continue with other rules
                            pass
                finally:
                    session.close()

            except Exception:
                pass

            await asyncio.sleep(interval_seconds)