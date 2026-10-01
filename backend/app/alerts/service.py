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
            if kind in ("price_above", "price_below"):
                return self._evaluate_price_rule(session, rule)
            elif kind == "pct_change":
                return self._evaluate_pct_change_rule(session, rule)
            elif kind == "volume_spike":
                return self._evaluate_volume_rule(session, rule)
            elif kind in ("rsi_above", "rsi_below", "rsi_cross"):
                return self._evaluate_rsi_rule(session, rule)
            elif kind in ("macd_cross", "macd_signal_cross"):
                return self._evaluate_macd_rule(session, rule)
            elif kind == "announcement":
                return self._evaluate_announcement_rule(session, rule)
            elif kind in ("book_closure", "agm_approaching", "book_closure_within"):
                return self._evaluate_book_closure_within_rule(session, rule)
            elif kind == "circuit_hit":
                return self._evaluate_circuit_hit_rule(session, rule)
            elif kind in ("52w_high", "52w_low"):
                return self._evaluate_52w_rule(session, rule)
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
        """Evaluate RSI-based rules using archive data."""
        from app.db.models import DailyBar
        from app.analytics.indicators import calculate_rsi

        symbol = rule.symbol
        params = rule.params
        period = params.get("period", 14)
        threshold = params.get("threshold")
        kind = rule.kind

        if threshold is None:
            return None

        # Get enough bars for RSI calculation
        bars = session.scalars(
            select(DailyBar)
            .where(DailyBar.symbol == symbol)
            .order_by(DailyBar.business_date.desc())
            .limit(period + 10)
        ).all()

        if len(bars) < period + 1:
            return None

        # Extract closes in chronological order (oldest first)
        closes = [b.close for b in reversed(bars) if b.close is not None]
        if len(closes) < period + 1:
            return None

        # Calculate RSI
        rsi_values = calculate_rsi(closes, period)
        if not rsi_values:
            return None

        current_rsi = rsi_values[-1]
        triggered = False
        message = ""

        if kind == "rsi_above" and current_rsi > threshold:
            triggered = True
            message = f"{symbol} RSI({period}) {current_rsi:.1f} crossed above {threshold}"
        elif kind == "rsi_below" and current_rsi < threshold:
            triggered = True
            message = f"{symbol} RSI({period}) {current_rsi:.1f} dropped below {threshold}"
        elif kind == "rsi_cross":
            # Cross of threshold (either direction)
            if len(rsi_values) >= 2:
                prev_rsi = rsi_values[-2]
                if (prev_rsi <= threshold < current_rsi) or (prev_rsi >= threshold > current_rsi):
                    triggered = True
                    direction = "above" if current_rsi > threshold else "below"
                    message = f"{symbol} RSI({period}) crossed {direction} {threshold}"

        if triggered:
            return {
                "triggered": True,
                "message": message,
                "value": current_rsi,
                "threshold": threshold,
            }
        return None

    def _evaluate_macd_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate MACD crossover rules using archive data."""
        from app.db.models import DailyBar
        from app.analytics.indicators import calculate_macd

        symbol = rule.symbol
        params = rule.params
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal = params.get("signal", 9)
        kind = rule.kind

        # Get enough bars for MACD
        bars = session.scalars(
            select(DailyBar)
            .where(DailyBar.symbol == symbol)
            .order_by(DailyBar.business_date.desc())
            .limit(slow + signal + 10)
        ).all()

        if len(bars) < slow + signal:
            return None

        closes = [b.close for b in reversed(bars) if b.close is not None]
        if len(closes) < slow + signal:
            return None

        macd_result = calculate_macd(closes, fast, slow, signal)
        if not macd_result or not macd_result["macd"]:
            return None

        macd_line = macd_result["macd"]
        signal_line = macd_result["signal"]

        if len(macd_line) < 2 or len(signal_line) < 2:
            return None

        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        prev_macd = macd_line[-2]
        prev_signal = signal_line[-2]

        triggered = False
        message = ""

        if kind == "macd_cross":
            # MACD line crosses signal line
            if prev_macd <= prev_signal and current_macd > current_signal:
                triggered = True
                message = f"{symbol} MACD crossed above signal (bullish)"
            elif prev_macd >= prev_signal and current_macd < current_signal:
                triggered = True
                message = f"{symbol} MACD crossed below signal (bearish)"
        elif kind == "macd_signal_cross":
            # MACD crosses zero
            if prev_macd <= 0 and current_macd > 0:
                triggered = True
                message = f"{symbol} MACD crossed above zero"
            elif prev_macd >= 0 and current_macd < 0:
                triggered = True
                message = f"{symbol} MACD crossed below zero"

        if triggered:
            return {
                "triggered": True,
                "message": message,
                "value": current_macd,
                "signal": current_signal,
            }
        return None

    def _evaluate_pct_change_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate percentage change rules."""
        from app.db.models import DailyBar

        symbol = rule.symbol
        params = rule.params
        threshold = params.get("threshold")  # e.g., 5 for 5%
        period = params.get("period", 1)  # days to look back

        if threshold is None:
            return None

        bars = session.scalars(
            select(DailyBar)
            .where(DailyBar.symbol == symbol)
            .order_by(DailyBar.business_date.desc())
            .limit(period + 2)
        ).all()

        if len(bars) < period + 1:
            return None

        closes = [b.close for b in reversed(bars) if b.close is not None]
        if len(closes) < period + 1:
            return None

        current_close = closes[-1]
        prev_close = closes[-(period + 1)]

        if prev_close and prev_close > 0:
            pct_change = ((current_close - prev_close) / prev_close) * 100

            triggered = False
            if pct_change >= threshold:
                triggered = True
                message = f"{symbol} gained {pct_change:.2f}% over {period} day(s) (threshold: {threshold}%)"
            elif pct_change <= -threshold:
                triggered = True
                message = f"{symbol} dropped {abs(pct_change):.2f}% over {period} day(s) (threshold: {threshold}%)"

            if triggered:
                return {
                    "triggered": True,
                    "message": message,
                    "value": pct_change,
                    "threshold": threshold,
                }
        return None

    def _evaluate_circuit_hit_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate circuit breaker hit rule."""
        from app.db.models import DailyBar

        symbol = rule.symbol
        params = rule.params
        circuit_type = params.get("type", "both")  # "upper", "lower", "both"

        # Get today's bar
        today = date.today().isoformat()
        bar = session.scalar(
            select(DailyBar).where(
                and_(DailyBar.symbol == symbol, DailyBar.business_date == today)
            )
        )

        if not bar or bar.high is None or bar.low is None:
            return None

        # Circuit limits are typically +/- 10% from previous close
        prev_close = bar.prev_close
        if not prev_close:
            return None

        upper_limit = prev_close * 1.10
        lower_limit = prev_close * 0.90

        triggered = False
        message = ""

        if circuit_type in ("upper", "both") and bar.high >= upper_limit:
            triggered = True
            message = f"{symbol} hit upper circuit at {bar.high} (limit: {upper_limit:.2f})"
        elif circuit_type in ("lower", "both") and bar.low <= lower_limit:
            triggered = True
            message = f"{symbol} hit lower circuit at {bar.low} (limit: {lower_limit:.2f})"

        if triggered:
            return {
                "triggered": True,
                "message": message,
                "value": bar.high if circuit_type in ("upper", "both") else bar.low,
                "limit": upper_limit if circuit_type in ("upper", "both") else lower_limit,
            }
        return None

    def _evaluate_52w_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate 52-week high/low rules."""
        from app.db.models import DailyBar

        symbol = rule.symbol
        params = rule.params
        rule_type = params.get("type", "high")  # "high" or "low"

        # Get 52 weeks of data (~252 trading days)
        bars = session.scalars(
            select(DailyBar)
            .where(DailyBar.symbol == symbol)
            .order_by(DailyBar.business_date.desc())
            .limit(300)
        ).all()

        if not bars:
            return None

        highs = [b.high for b in bars if b.high is not None]
        lows = [b.low for b in bars if b.low is not None]

        if not highs or not lows:
            return None

        high_52w = max(highs)
        low_52w = min(lows)

        # Get current price
        current_bar = bars[0]
        current_price = current_bar.close or current_bar.high or current_bar.low
        if not current_price:
            return None

        triggered = False
        message = ""

        if rule_type == "high" and current_price >= high_52w:
            triggered = True
            message = f"{symbol} at 52-week high {current_price} (prev high: {high_52w})"
        elif rule_type == "low" and current_price <= low_52w:
            triggered = True
            message = f"{symbol} at 52-week low {current_price} (prev low: {low_52w})"

        if triggered:
            return {
                "triggered": True,
                "message": message,
                "value": current_price,
                "threshold": high_52w if rule_type == "high" else low_52w,
            }
        return None

    def _evaluate_book_closure_within_rule(
        self,
        session: "Session",
        rule: "AlertRule",
    ) -> Optional[Dict[str, Any]]:
        """Evaluate book closure within N days rule."""
        from app.db.models import CorporateAction
        from datetime import date, timedelta

        symbol = rule.symbol
        params = rule.params
        days_ahead = params.get("days_ahead", 30)

        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        actions = session.scalars(
            select(CorporateAction).where(
                CorporateAction.symbol == symbol,
                CorporateAction.book_close.is_not(None),
                CorporateAction.book_close >= today.isoformat(),
                CorporateAction.book_close <= end_date.isoformat(),
            )
        ).all()

        for ca in actions:
            return {
                "triggered": True,
                "message": f"{symbol} book closure on {ca.book_close} (fiscal year: {ca.fiscal_year})",
                "event_type": "book_closure",
                "date": ca.book_close,
                "fiscal_year": ca.fiscal_year,
            }
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

    # --- Notification Senders ---

    def send_notification(
        self,
        session: "Session",
        channel: "AlertChannel",
        subject: str,
        message: str,
    ) -> bool:
        """Send notification via channel."""
        if channel.channel_type == "email":
            return self._send_email(channel, subject, message)
        elif channel.channel_type == "telegram":
            return self._send_telegram(channel, message)
        elif channel.channel_type == "in_app":
            return self._send_in_app(session, channel, subject, message)
        return False

    def _send_email(self, channel: "AlertChannel", subject: str, message: str) -> bool:
        """Send email notification (placeholder - requires SMTP config)."""
        # In production, implement SMTP sending
        # For now, log the email
        import logging
        logging.info(f"EMAIL to {channel.config.get('email')}: {subject} - {message}")
        return True

    def _send_telegram(self, channel: "AlertChannel", message: str) -> bool:
        """Send Telegram notification (placeholder - requires bot token)."""
        # In production, implement Telegram bot API call
        import logging
        logging.info(f"TELEGRAM to {channel.config.get('chat_id')}: {message}")
        return True

    def _send_in_app(
        self,
        session: "Session",
        channel: "AlertChannel",
        subject: str,
        message: str,
    ) -> bool:
        """Create in-app notification (stored in alert_events delivery_status)."""
        # In-app notifications are just recorded in the event
        # The frontend polls for new events
        return True

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
        from app.db.models import AlertRule, AlertChannel

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
                                session.flush()

                                # Update rule
                                rule.last_triggered_at = datetime.utcnow()
                                rule.trigger_count += 1
                                if rule.is_one_shot:
                                    rule.is_active = False

                                # Send notifications via channel
                                if rule.channel_id:
                                    channel = session.get(AlertChannel, rule.channel_id)
                                    if channel and channel.is_active and channel.is_verified:
                                        subject = f"Alert: {rule.kind} for {rule.symbol}"
                                        message = result.get("message", "Alert triggered")
                                        sent = self.send_notification(session, channel, subject, message)
                                        event.delivery_status[channel.channel_type] = "sent" if sent else "failed"

                                session.commit()

                        except Exception as e:
                            # Log error but continue with other rules
                            pass
                finally:
                    session.close()

            except Exception:
                pass

            # Rate limit: don't evaluate more than once per interval
            await asyncio.sleep(interval_seconds)