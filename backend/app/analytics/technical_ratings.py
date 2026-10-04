# ---------------------------------------------------------------------------
# Batch B doc #57: Technical Ratings
# ---------------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Sequence, Optional

from app.analytics.indicators import (
    Bar,
    adx,
    awesome_oscillator,
    cci,
    ema_on_valid,
    macd_on_valid,
    momentum,
    rsi_on_valid,
    sma_on_valid,
    stochastic,
    williams_r,
)

# The per-bar variant lives in indicators.py next to the single-bar original
# (one implementation, two import paths); re-exported here so callers of this
# module get both.
from app.analytics.indicators import (  # noqa: F401
    technical_ratings_series,
)


def technical_ratings(
    bars: Sequence[Bar],
    ma_periods: Sequence[int] = (10, 20, 30, 50, 100, 200),
    rsi_period: int = 14,
    stoch_period: int = 14,
    stoch_d_period: int = 3,
    cci_period: int = 20,
    adx_period: int = 14,
    awesome_period: int = 5,
    awesome_slow: int = 34,
    momentum_period: int = 10,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    williams_period: int = 14,
    threshold_strong: float = 0.5,
    threshold_moderate: float = 0.1,
    threshold_weak: float = 0.1,
    threshold_strong_bear: float = 0.5,
    min_components_pct: float = 0.6,
) -> dict[str, Any]:
    """Technical Ratings (doc #57): composite signal from MA and oscillator groups.

    MA group (12 signals): C vs SMA/EMA at 10, 20, 30, 50, 100, 200 -> +1 if C > MA, -1 if C < MA, 0 if equal.
    Oscillator group: RSI(14): +1 if RSI < 30 and rising, -1 if RSI > 70 and falling, else 0. Stochastic %K(14,3,3): +1 if K < 20 and K > D, -1 if K > 80 and K < D, else 0. CCI(20): +1 if < -100 and rising, -1 if > 100 and falling, else 0. ADX(14): +1 if ADX > 20 and +DI > -DI, -1 if ADX > 20 and +DI < -DI, else 0. Awesome Oscillator: +1 if > 0 and rising, -1 if < 0 and falling, else 0. Momentum(10): +1 if > 0, -1 if < 0. MACD(12,26,9): +1 if line > signal, -1 if <. Williams %R(14): +1 if < -80 and rising, -1 if > -20 and falling, else 0.
    Outputs: ma_rating, osc_rating, overall = mean of available component signals (each -1..+1), components_used / components_total, and the full component table (each component's value and signal) so users can see why.
    Label thresholds on the mean: > 0.5 "strong bullish setup"; 0.1 to 0.5 "bullish setup"; -0.1 to 0.1 "neutral"; -0.5 to -0.1 "bearish setup"; < -0.5 "strong bearish setup". Never use buy/sell wording.
    If fewer than 60% of components are available -> pending with the reason.
    Show the disclaimer on the UI. Thresholds and component rules are configurable and documented.
    """
    n = len(bars)
    if n == 0:
        return {
            "ma_rating": None,
            "osc_rating": None,
            "overall": None,
            "components_used": 0,
            "components_total": 20,
            "component_table": [],
            "label": "pending",
        }

    # --- MA Group (12 signals: SMA + EMA at each period) ---
    closes = [b.close for b in bars]
    ma_signals = []
    ma_components = []

    for period in ma_periods:
        # SMA
        sma_vals = sma_on_valid([c for c in closes if c is not None], period)
        sma_val = sma_vals[-1] if sma_vals else None
        if sma_val is not None and closes[-1] is not None:
            sig = 1 if closes[-1] > sma_val else (-1 if closes[-1] < sma_val else 0)
            ma_signals.append(sig)
            ma_components.append({
                "name": f"SMA({period})",
                "value": sma_val,
                "signal": sig,
            })
        else:
            ma_components.append({
                "name": f"SMA({period})",
                "value": sma_val,
                "signal": None,
            })

        # EMA
        ema_vals = ema_on_valid([c for c in closes if c is not None], period)
        ema_val = ema_vals[-1] if ema_vals else None
        if ema_val is not None and closes[-1] is not None:
            sig = 1 if closes[-1] > ema_val else (-1 if closes[-1] < ema_val else 0)
            ma_signals.append(sig)
            ma_components.append({
                "name": f"EMA({period})",
                "value": ema_val,
                "signal": sig,
            })
        else:
            ma_components.append({
                "name": f"EMA({period})",
                "value": ema_val,
                "signal": None,
            })

    # --- Oscillator Group ---
    osc_signals = []
    osc_components = []

    # RSI
    rsi_vals = rsi_on_valid([c for c in closes if c is not None], rsi_period)
    rsi_val = rsi_vals[-1] if rsi_vals else None
    if rsi_val is not None and len(rsi_vals) >= 2:
        rsi_prev = rsi_vals[-2]
        if rsi_val < 30 and rsi_val > rsi_prev:
            sig = 1
        elif rsi_val > 70 and rsi_val < rsi_prev:
            sig = -1
        else:
            sig = 0
        osc_signals.append(sig)
        osc_components.append({"name": "RSI", "value": rsi_val, "signal": sig})
    else:
        osc_components.append({"name": "RSI", "value": rsi_val, "signal": None})

    # Stochastic %K
    valid_bars = [b for b in bars if b.has_ohlcv]
    k_vals, d_vals = stochastic(valid_bars, stoch_period, stoch_d_period)
    k_val = k_vals[-1] if k_vals else None
    d_val = d_vals[-1] if d_vals else None
    if k_val is not None and d_val is not None:
        if k_val < 20 and k_val > d_val:
            sig = 1
        elif k_val > 80 and k_val < d_val:
            sig = -1
        else:
            sig = 0
        osc_signals.append(sig)
        osc_components.append({"name": "Stoch %K", "value": k_val, "signal": sig})
    else:
        osc_components.append({"name": "Stoch %K", "value": k_val, "signal": None})

    # CCI
    cci_vals = cci([b for b in bars if b.has_ohlcv], cci_period)
    cci_val = cci_vals[-1] if cci_vals else None
    if cci_val is not None and len(cci_vals) >= 2:
        cci_prev = cci_vals[-2]
        if cci_val < -100 and cci_val > cci_prev:
            sig = 1
        elif cci_val > 100 and cci_val < cci_prev:
            sig = -1
        else:
            sig = 0
        osc_signals.append(sig)
        osc_components.append({"name": "CCI", "value": cci_val, "signal": sig})
    else:
        osc_components.append({"name": "CCI", "value": cci_val, "signal": None})

    # ADX
    valid_bars = [b for b in bars if b.has_ohlcv]
    if len(valid_bars) > adx_period:
        plus_di, minus_di, dx, adx_vals = adx(valid_bars, adx_period)
        adx_val = adx_vals[-1] if adx_vals else None
        plus_di_val = plus_di[-1] if plus_di else None
        minus_di_val = minus_di[-1] if minus_di else None
        if adx_val is not None and plus_di_val is not None and minus_di_val is not None:
            if adx_val > 20 and plus_di_val > minus_di_val:
                sig = 1
            elif adx_val > 20 and plus_di_val < minus_di_val:
                sig = -1
            else:
                sig = 0
            osc_signals.append(sig)
            osc_components.append({"name": "ADX", "value": adx_val, "signal": sig})
        else:
            osc_components.append({"name": "ADX", "value": adx_val, "signal": None})
    else:
        osc_components.append({"name": "ADX", "value": None, "signal": None})

    # Awesome Oscillator
    ao_vals = awesome_oscillator(valid_bars, 5, 34)
    ao_val = ao_vals[-1] if ao_vals else None
    if ao_val is not None and len(ao_vals) >= 2:
        ao_prev = ao_vals[-2]
        if ao_val > 0 and ao_val > ao_prev:
            sig = 1
        elif ao_val < 0 and ao_val < ao_prev:
            sig = -1
        else:
            sig = 0
        osc_signals.append(sig)
        osc_components.append({"name": "Awesome Osc", "value": ao_val, "signal": sig})
    else:
        osc_components.append({"name": "Awesome Osc", "value": ao_val, "signal": None})

    # Momentum
    closes = [b.close for b in bars]
    mom_vals = momentum([c for c in closes if c is not None], momentum_period)
    mom_val = mom_vals[-1] if mom_vals else None
    if mom_val is not None:
        sig = 1 if mom_val > 0 else (-1 if mom_val < 0 else 0)
        osc_signals.append(sig)
        osc_components.append({"name": "Momentum", "value": mom_val, "signal": sig})
    else:
        osc_components.append({"name": "Momentum", "value": mom_val, "signal": None})

    # MACD
    closes_valid = [c for c in closes if c is not None]
    macd_line, macd_signal, macd_hist = macd_on_valid(closes_valid)
    macd_val = macd_line[-1] if macd_line else None
    sig_val = macd_signal[-1] if macd_signal else None
    if macd_val is not None and sig_val is not None:
        sig = 1 if macd_val > sig_val else (-1 if macd_val < sig_val else 0)
        osc_signals.append(sig)
        osc_components.append({"name": "MACD", "value": macd_val, "signal": sig})
    else:
        osc_components.append({"name": "MACD", "value": macd_val, "signal": None})

    # Williams %R
    wr_vals = williams_r(valid_bars, williams_period)
    wr_val = wr_vals[-1] if wr_vals else None
    if wr_val is not None and len(wr_vals) >= 2:
        wr_prev = wr_vals[-2]
        if wr_val < -80 and wr_val > wr_prev:
            sig = 1
        elif wr_val > -20 and wr_val < wr_prev:
            sig = -1
        else:
            sig = 0
        osc_signals.append(sig)
        osc_components.append({"name": "Williams %R", "value": wr_val, "signal": sig})
    else:
        osc_components.append({"name": "Williams %R", "value": wr_val, "signal": None})

    # --- Compute Ratings ---
    ma_used = [s for s in ma_signals if s is not None]
    osc_used = [s for s in osc_signals if s is not None]
    all_used = ma_used + osc_used

    ma_rating = sum(ma_used) / len(ma_used) if ma_used else None
    osc_rating = sum(osc_used) / len(osc_used) if osc_used else None
    overall = sum(all_used) / len(all_used) if all_used else None

    # Label thresholds
    label = "pending"
    if overall is not None:
        if overall > threshold_strong:
            label = "strong bullish setup"
        elif overall > threshold_moderate:
            label = "bullish setup"
        elif overall > -threshold_weak:
            label = "neutral"
        elif overall > -threshold_strong_bear:
            label = "bearish setup"
        else:
            label = "strong bearish setup"

    components_used = len(ma_used) + len(osc_used)
    components_total = len(ma_periods) * 2 + 8  # 12 MA + 8 oscillator

    # Check minimum component availability
    if components_total > 0 and (components_used / components_total) < min_components_pct:
        label = "pending"

    return {
        "ma_rating": ma_rating,
        "osc_rating": osc_rating,
        "overall": overall,
        "components_used": components_used,
        "components_total": components_total,
        "component_table": ma_components + osc_components,
        "label": label,
    }