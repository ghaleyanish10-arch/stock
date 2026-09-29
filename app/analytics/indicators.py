"""Technical indicators computed server-side in pure Python.

Why here rather than in the chart library: one source of truth, unit-testable
without a browser, identical numbers in the API, the chart, the screener and
any export. The frontend only renders the series it is handed.

Every function follows the same honesty rules as the rest of the app:

* A value that cannot be computed is `None`, never `0`, `0.0` or `-1`.
* A genuine zero is returned as `0.0` and means what it says (a flat close, an
  unchanged OBV step).
* Insufficient history yields `None` for the warm-up window rather than a
  made-up number.
* A mathematical singularity (a day with high == low, which happens whenever a
  stock is locked at its ceiling or floor) yields `None`, because
  Chaikin's multiplier is genuinely undefined there, not zero.

All functions return lists the same length as their input, with `None` in
positions that cannot be computed, so results can be zipped with dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

#: A single OHLCV bar. Field names match NEPSE's `today-price` payload.
@dataclass(frozen=True, slots=True)
class Bar:
    """One session's data. All fields optional because NEPSE can omit any."""

    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None

    @property
    def has_ohlcv(self) -> bool:
        return None not in (self.open, self.high, self.low, self.close)

    @property
    def has_range(self) -> bool:
        """True when a price range exists and is non-degenerate."""
        return (
            self.high is not None
            and self.low is not None
            and self.high > self.low
        )

    @property
    def typical_price(self) -> Optional[float]:
        """(H + L + C) / 3, the basis for Chaikin's multiplier."""
        if self.high is None or self.low is None or self.close is None:
            return None
        return (self.high + self.low + self.close) / 3.0


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------


def sma(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Simple moving average, `None` during the warm-up window.

    A window containing a missing value yields `None` (we do not average over
    fewer observations than requested, which would silently bias results).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = []
    for i in range(len(values)):
        window = values[i - period + 1 : i + 1] if i >= period - 1 else []
        if len(window) < period or any(v is None for v in window):
            out.append(None)
        else:
            out.append(sum(float(v) for v in window) / period)  # type: ignore[arg-type]
    return out


def ema(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Exponential moving average seeded with an SMA of the first `period`.

    Runs of consecutive non-`None` values are averaged independently, and the
    warm-up window is `None`, so the output lines up with the input.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    alpha = 2.0 / (period + 1.0)
    out: list[Optional[float]] = [None] * len(values)
    run_start: Optional[int] = None
    for i, v in enumerate(values):
        if v is None:
            run_start = None  # a gap breaks the run
            continue
        if run_start is None:
            run_start = i
        offset = i - run_start
        if offset < period - 1:
            continue  # still warming up
        if offset == period - 1:
            window = values[run_start : i + 1]
            out[i] = sum(float(x) for x in window if x is not None) / period  # type: ignore[arg-type]
        else:
            prev = out[i - 1]
            if prev is None:  # pragma: no cover - unreachable within a run
                continue
            out[i] = alpha * float(v) + (1 - alpha) * prev
    return out


def wma(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Weighted Moving Average.

    Weights increase linearly from 1 (oldest) to `period` (most recent).
    Returns `None` during the warm-up window and when the window contains
    any missing value.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    weights = list(range(1, period + 1))
    weight_sum = sum(weights)
    out: list[Optional[float]] = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
            continue
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            out.append(None)
        else:
            weighted = sum(float(v) * w for v, w in zip(window, weights))  # type: ignore[arg-type]
            out.append(weighted / weight_sum)
    return out


def dema(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Double Exponential Moving Average.

    DEMA = 2 * EMA - EMA(EMA). Reduces lag by applying EMA twice.
    Returns `None` during the combined warm-up window.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    ema1 = ema(values, period)
    ema2 = ema(ema1, period)
    out: list[Optional[float]] = []
    for e1, e2 in zip(ema1, ema2):
        if e1 is None or e2 is None:
            out.append(None)
        else:
            out.append(2.0 * e1 - e2)
    return out


def tema(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Triple Exponential Moving Average.

    TEMA = 3 * EMA - 3 * EMA(EMA) + EMA(EMA(EMA)). Further reduces lag.
    Returns `None` during the combined warm-up window.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    ema1 = ema(values, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    out: list[Optional[float]] = []
    for e1, e2, e3 in zip(ema1, ema2, ema3):
        if e1 is None or e2 is None or e3 is None:
            out.append(None)
        else:
            out.append(3.0 * e1 - 3.0 * e2 + e3)
    return out


def hma(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Hull Moving Average.

    HMA = WMA(2 * WMA(n/2) - WMA(n), sqrt(n)). Very low lag, smooth curve.
    Returns `None` during the combined warm-up window.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    half_period = max(1, period // 2)
    sqrt_period = max(1, int(round(period ** 0.5)))
    wma_half = wma(values, half_period)
    wma_full = wma(values, period)
    intermediate: list[Optional[float]] = []
    for wh, wf in zip(wma_half, wma_full):
        if wh is None or wf is None:
            intermediate.append(None)
        else:
            intermediate.append(2.0 * wh - wf)
    out = wma(intermediate, sqrt_period)
    return out


def trix(values: Sequence[Optional[float]], period: int = 15) -> list[Optional[float]]:
    """TRIX: percent rate of change of a triple-smoothed EMA.

    The close is smoothed by the same EMA three times; TRIX is the day-over-day
    percent change of that result. Positive while the smoothed trend is
    accelerating upward, negative while decelerating.

    A flat series makes the day-over-day change genuinely zero, which is a real
    reading and is returned as 0.0. A zero base (a triple EMA at exactly 0) has
    no defined percent change and yields `None`. With `period=1` each EMA is
    the identity, so TRIX degenerates to ROC(1) on the raw closes.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    e3 = ema(ema(ema(values, period), period), period)
    out: list[Optional[float]] = [None] * len(e3)
    for i in range(1, len(e3)):
        prev, cur = e3[i - 1], e3[i]
        if prev is None or cur is None:
            continue
        if prev == 0:
            continue  # percent change on a zero base is undefined, not zero
        out[i] = (cur - prev) / prev * 100.0
    return out


# ---------------------------------------------------------------------------
# Trend strength
# ---------------------------------------------------------------------------


def adx(bars: Sequence[Bar], period: int = 14) -> tuple[
    list[Optional[float]], list[Optional[float]],
    list[Optional[float]], list[Optional[float]],
]:
    """Wilder's DMI: returns `(+DI, -DI, DX, ADX)`, aligned to `bars`.

    +DM/-DM compare each bar's range extension against the previous bar's;
    TR, +DM and -DM are Wilder-smoothed; +DI/-DI are the smoothed directions
    over smoothed TR; DX is the spread between the two DIs; ADX is Wilder's
    smoothing of DX. The first smoothed DI appears at index `period`, the
    first ADX at index `2*period - 1`.

    Honesty rules: a bar missing high/low/close breaks the smoothing and the
    series re-warms after it, exactly like RSI's gap handling. A zero total TR
    (every bar in the window locked at one price) makes DI undefined - `None`,
    not zero. DX of exactly 0 is a real reading (+DI == -DI), not a gap.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(bars)
    plus_di: list[Optional[float]] = [None] * n
    minus_di: list[Optional[float]] = [None] * n
    dx: list[Optional[float]] = [None] * n
    adx_out: list[Optional[float]] = [None] * n

    # Per-bar changes: index i uses bars[i] vs bars[i-1]; index 0 has none.
    tr: list[Optional[float]] = [None] * n
    plus_dm: list[Optional[float]] = [None] * n
    minus_dm: list[Optional[float]] = [None] * n
    for i in range(1, n):
        prev, cur = bars[i - 1], bars[i]
        if not cur.has_range or prev.high is None or prev.close is None:
            continue
        up_move = float(cur.high) - float(prev.high)
        down_move = float(prev.low) - float(cur.low)
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0
        tr[i] = true_range(float(cur.high), float(cur.low), float(prev.close))

    smooth_tr: Optional[float] = None
    smooth_plus: Optional[float] = None
    smooth_minus: Optional[float] = None
    dx_values: list[float] = []  # DX readings inside the current ADX window

    for i in range(1, n):
        if tr[i] is None:
            # Gap: reset the smoothing and the ADX accumulation.
            smooth_tr = smooth_plus = smooth_minus = None
            dx_values = []
            continue
        if smooth_tr is None:
            # Accumulate the first `period` changes.
            window_tr = [t for t in tr[max(1, i - period + 1) : i + 1] if t is not None]
            window_p = [p for p in plus_dm[max(1, i - period + 1) : i + 1] if p is not None]
            window_m = [m for m in minus_dm[max(1, i - period + 1) : i + 1] if m is not None]
            if len(window_tr) == period and len(window_p) == period and len(window_m) == period:
                smooth_tr = float(sum(window_tr))
                smooth_plus = float(sum(window_p))
                smooth_minus = float(sum(window_m))
            else:
                continue  # still warming up
        else:
            smooth_tr = smooth_tr - smooth_tr / period + float(tr[i])  # type: ignore[arg-type]
            smooth_plus = smooth_plus - smooth_plus / period + float(plus_dm[i])  # type: ignore[arg-type]
            smooth_minus = smooth_minus - smooth_minus / period + float(minus_dm[i])  # type: ignore[arg-type]

        if smooth_tr == 0.0:
            continue  # every bar locked: DI is undefined here, stay None
        di_plus = 100.0 * smooth_plus / smooth_tr
        di_minus = 100.0 * smooth_minus / smooth_tr
        plus_di[i] = di_plus
        minus_di[i] = di_minus
        total = di_plus + di_minus
        if total == 0.0:
            dx[i] = 0.0  # equal pressures: a genuine zero
            dx_values.append(0.0)
        else:
            dx[i] = 100.0 * abs(di_plus - di_minus) / total
            dx_values.append(dx[i])
        # ADX = Wilder-smoothed DX; the first value averages the first
        # `period` DX readings.
        if len(dx_values) == period:
            adx_out[i] = sum(dx_values) / period
        elif len(dx_values) > period and adx_out[i - 1] is not None:
            adx_out[i] = (adx_out[i - 1] * (period - 1) + dx[i]) / period

    return plus_di, minus_di, dx, adx_out


def aroon(bars: Sequence[Bar], period: int = 14) -> tuple[
    list[Optional[float]], list[Optional[float]]
]:
    """Aroon Up/Down: days since the window's extreme, as a percent.

    Aroon Up = 100 * (period - bars since the period-high) / period, and Down
    likewise for the low. The window covers `period + 1` bars (extremes may sit
    on either end), so the first value appears at index `period`. Ties resolve
    to the most recent bar, the usual convention, which is why a flat series
    reads 100/100 rather than something synthetic.

    A bar missing its high or low yields `None` for that index.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(bars)
    up: list[Optional[float]] = [None] * n
    down: list[Optional[float]] = [None] * n
    for i in range(period, n):
        window = bars[i - period : i + 1]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if any(h is None for h in highs) or any(l is None for l in lows):
            continue
        # Newest-first scan: the most recent extreme wins ties.
        high_off = next(j for j, h in enumerate(reversed(highs)) if h == max(highs))  # type: ignore[type-var]
        low_off = next(j for j, l in enumerate(reversed(lows)) if l == min(lows))  # type: ignore[type-var]
        up[i] = 100.0 * (period - high_off) / period
        down[i] = 100.0 * (period - low_off) / period
    return up, down


def psar(
    bars: Sequence[Bar], af_step: float = 0.02, af_max: float = 0.2
) -> list[Optional[float]]:
    """Wilder's Parabolic SAR (Stop And Reverse), aligned to `bars`.

    The SAR trails price with an acceleration factor that grows by `af_step`
    each time a new extreme point is made, capped at `af_max`. Per Wilder's
    rule the stop never sits inside the previous two bars' range, and when
    price crosses it the series reverses onto the trend's extreme point.

    The first value appears at the second bar of the first run with usable
    high/low/close on both bars (the seed needs a direction, taken from the
    two closes). A bar missing high/low/close ends the run and the series
    re-seeds after the gap. A run of degenerate bars (high == low) yields
    `None` - there is no range to trail.
    """
    if af_step <= 0 or af_max < af_step:
        raise ValueError("require 0 < af_step <= af_max")
    n = len(bars)
    out: list[Optional[float]] = [None] * n

    def seed(start: int) -> Optional[tuple[int, float, float, float, bool]]:
        """Find the first bar pair from `start` that can open a run.

        Returns (next index, sar, extreme point, af, trend-up) or None.
        """
        i = start
        while i + 1 < n:
            prev, cur = bars[i], bars[i + 1]
            if (
                prev.high is not None and prev.low is not None and prev.close is not None
                and cur.has_range and cur.close is not None
            ):
                up = float(cur.close) >= float(prev.close)
                sar = float(prev.low) if up else float(prev.high)
                ep = float(prev.high) if up else float(prev.low)
                return i + 1, sar, ep, af_step, up
            i += 1
        return None

    def clamp(level: float, i: int, up: bool) -> float:
        """Wilder: the stop may not sit inside the previous two bars' range."""
        bounds = []
        for j in (i - 2, i - 1):
            extreme = bars[j].low if up else bars[j].high
            if j >= 0 and extreme is not None:
                bounds.append(float(extreme))
        if not bounds:
            return level
        return min([level] + bounds) if up else max([level] + bounds)

    seeded = seed(0)
    while seeded is not None:
        i, sar, ep, af, up = seeded
        while i < n:
            cur = bars[i]
            if not cur.has_range or cur.close is None:
                seeded = seed(i + 1)  # gap: the run ends, re-seed after it
                break
            if up:
                sar_next = clamp(sar + af * (ep - sar), i, up)
                if float(cur.low) < sar_next:
                    # Reversal: SAR jumps to the uptrend's extreme point.
                    out[i] = ep
                    up, sar, ep, af = False, ep, float(cur.low), af_step
                else:
                    out[i] = sar_next
                    sar = sar_next
                    if float(cur.high) > ep:
                        ep = float(cur.high)
                        af = min(af + af_step, af_max)
            else:
                sar_next = clamp(sar - af * (sar - ep), i, up)
                if float(cur.high) > sar_next:
                    out[i] = ep
                    up, sar, ep, af = True, ep, float(cur.high), af_step
                else:
                    out[i] = sar_next
                    sar = sar_next
                    if float(cur.low) < ep:
                        ep = float(cur.low)
                        af = min(af + af_step, af_max)
            i += 1
        else:
            seeded = None  # ran off the end of the data
    return out


def supertrend(
    bars: Sequence[Bar], period: int = 10, mult: float = 3.0
) -> list[Optional[float]]:
    """Supertrend line, aligned to `bars`.

    Bands sit `mult` ATRs either side of the midpoint (high+low)/2. The upper
    band ratchets down and the lower band ratchets up (they only move in the
    trend's direction, or when the previous close crossed the old band), and
    the line rides the band price last stayed inside - flipping across close
    on a breakout.
    The line's position encodes the trend: below price while up, above while
    down.

    Warm-up matches ATR's: `None` until the ATR's first value (index
    `period - 1`); a missing bar inside ATR's first window keeps the whole
    series `None`, exactly as ATR itself reports.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if mult <= 0:
        raise ValueError("mult must be positive")
    atrs = atr(bars, period)
    n = len(bars)
    out: list[Optional[float]] = [None] * n
    final_upper: Optional[float] = None
    final_lower: Optional[float] = None
    is_up = True  # seeding convention: the line starts on the lower band
    for i, bar in enumerate(bars):
        a = atrs[i]
        if a is None:
            continue
        if bar.high is None or bar.low is None or bar.close is None:
            continue
        mid = (float(bar.high) + float(bar.low)) / 2.0
        basic_upper = mid + mult * float(a)
        basic_lower = mid - mult * float(a)
        close = float(bar.close)
        if final_upper is None or final_lower is None:
            # Seed bar: the bands start at their basic values.
            final_upper, final_lower = basic_upper, basic_lower
            out[i] = final_lower
            continue
        # Ratchet: each band may only tighten (or free up once the previous
        # close crossed it), never loosen against the trend.
        prev_close = (
            float(bars[i - 1].close)
            if i > 0 and bars[i - 1].close is not None
            else close
        )
        if basic_upper < final_upper or prev_close > final_upper:
            final_upper = basic_upper
        if basic_lower > final_lower or prev_close < final_lower:
            final_lower = basic_lower
        if is_up:
            if close >= final_lower:
                out[i] = final_lower
            else:
                out[i] = final_upper
                is_up = False
        else:
            if close <= final_upper:
                out[i] = final_upper
            else:
                out[i] = final_lower
                is_up = True
    return out


def ichimoku(
    bars: Sequence[Bar],
    conversion: int = 9,
    base: int = 26,
    span_b: int = 52,
) -> tuple[
    list[Optional[float]], list[Optional[float]],
    list[Optional[float]], list[Optional[float]],
    list[Optional[float]],
]:
    """Ichimoku Cloud: returns `(tenkan, kijun, senkou_a, senkou_b, chikou)`.

    Tenkan and kijun are midpoints of the high/low range over `conversion`
    and `base` bars. Senkou spans are those midpoints pushed FORWARD by
    `base` bars (the cloud drawn ahead of price), and chikou is the close
    pulled BACK by `base` bars. All five lists align with `bars`, so the
    last `base` positions carry no cloud values (they belong to future
    sessions the data does not contain) and chikou is `None` over the final
    `base` bars for the same reason.

    A window containing a bar with a missing high or low yields `None` at
    that anchor, and the spans inherit `None` from their anchors.
    """
    if min(conversion, base, span_b) <= 0:
        raise ValueError("conversion, base and span_b must be positive")

    def range_midpoint(period: int, index: int) -> Optional[float]:
        if index < period - 1:
            return None
        window = bars[index - period + 1 : index + 1]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if any(h is None for h in highs) or any(l is None for l in lows):
            return None
        return (
            max(float(h) for h in highs if h is not None)
            + min(float(l) for l in lows if l is not None)
        ) / 2.0

    n = len(bars)
    tenkan = [range_midpoint(conversion, i) for i in range(n)]
    kijun = [range_midpoint(base, i) for i in range(n)]
    donchian_b = [range_midpoint(span_b, i) for i in range(n)]

    senkou_a: list[Optional[float]] = [None] * n
    senkou_b: list[Optional[float]] = [None] * n
    for i in range(base, n):
        anchor = i - base
        t, k = tenkan[anchor], kijun[anchor]
        senkou_a[i] = (t + k) / 2.0 if t is not None and k is not None else None
        senkou_b[i] = donchian_b[anchor]

    chikou: list[Optional[float]] = [None] * n
    for i in range(n - base):
        chikou[i] = bars[i + base].close

    return tenkan, kijun, senkou_a, senkou_b, chikou


def vortex(bars: Sequence[Bar], period: int = 14) -> tuple[
    list[Optional[float]], list[Optional[float]]
]:
    """Vortex Indicator: returns `(VI+, VI-)`, aligned to `bars`.

    +VM is the distance from today's high to yesterday's low, -VM the distance
    from today's low to yesterday's high. Each VI divides the `period`-sum of
    its VM by the `period`-sum of true range, so the pair reads as ratios:
    VI+ above VI- marks an uptrend, and crossovers mark trend changes.

    The first value appears at index `period` (it needs `period` changes).
    A bar missing high/low/close clears the window and the sums re-accumulate
    after the gap, like ADX. A zero total true range cannot occur while every
    bar has a range, so no zero-division branch is needed here.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(bars)
    plus: list[Optional[float]] = [None] * n
    minus: list[Optional[float]] = [None] * n
    win_p: list[float] = []
    win_m: list[float] = []
    win_tr: list[float] = []
    for i in range(1, n):
        prev, cur = bars[i - 1], bars[i]
        if (
            not cur.has_range
            or not prev.has_range
            or prev.close is None
        ):
            win_p.clear()
            win_m.clear()
            win_tr.clear()
            continue
        win_p.append(abs(float(cur.high) - float(prev.low)))
        win_m.append(abs(float(cur.low) - float(prev.high)))
        win_tr.append(true_range(float(cur.high), float(cur.low), float(prev.close)))
        if len(win_tr) > period:
            win_p.pop(0)
            win_m.pop(0)
            win_tr.pop(0)
        if len(win_tr) == period:
            total_tr = sum(win_tr)
            plus[i] = sum(win_p) / total_tr
            minus[i] = sum(win_m) / total_tr
    return plus, minus


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


def rsi(closes: Sequence[Optional[float]], period: int = 14) -> list[Optional[float]]:
    """Wilder's RSI. The first value appears at index `period`.

    When there have been no losses in the window, RSI is exactly 100.0 and
    with no gains exactly 0.0 - real readings, not missing ones. With neither,
    the series is flat and 50.0 is returned.

    A gap in the close series resets the smoothing and restarts the warm-up,
    so values after a gap are `None` until a full fresh window exists. That is
    deliberate: carrying the old average across a gap would publish a number
    built from data that is no longer adjacent.
"""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return out

    # Wilder's smoothing: first average is simple, then exponential
    gains: list[Optional[float]] = [None] * len(closes)
    losses: list[Optional[float]] = [None] * len(closes)

    for i in range(1, len(closes)):
        if closes[i] is None or closes[i - 1] is None:
            # Gap resets everything
            continue
        change = float(closes[i]) - float(closes[i - 1])
        if change >= 0:
            gains[i] = change
            losses[i] = 0.0
        else:
            gains[i] = 0.0
            losses[i] = -change

    avg_gain: Optional[float] = None
    avg_loss: Optional[float] = None

    for i in range(1, len(closes)):
        if gains[i] is None or losses[i] is None:
            # Gap encountered, reset
            avg_gain = None
            avg_loss = None
            continue

        if avg_gain is None or avg_loss is None:
            # First window after a gap: need period observations
            window_start = i - period + 1
            if window_start < 1:
                continue
            window_gains = [g for g in gains[window_start : i + 1] if g is not None]
            window_losses = [l for l in losses[window_start : i + 1] if l is not None]
            if len(window_gains) == period and len(window_losses) == period:
                avg_gain = sum(window_gains) / period
                avg_loss = sum(window_losses) / period
                if avg_loss == 0:
                    out[i] = 100.0
                elif avg_gain == 0:
                    out[i] = 0.0
                else:
                    rs = avg_gain / avg_loss
                    out[i] = 100.0 - 100.0 / (1.0 + rs)
        else:
            # Wilder's smoothing
            alpha = 1.0 / period
            avg_gain = (1 - alpha) * avg_gain + alpha * gains[i]
            avg_loss = (1 - alpha) * avg_loss + alpha * losses[i]
            # Flat series (no gains, no losses) -> neutral 50
            if avg_gain == 0 and avg_loss == 0:
                out[i] = 50.0
            elif avg_loss == 0:
                out[i] = 100.0
            elif avg_gain == 0:
                out[i] = 0.0
            else:
                rs = avg_gain / avg_loss
                out[i] = 100.0 - 100.0 / (1.0 + rs)

    return out


def _parse_book_close(date_str: str) -> Optional[str]:
    """Parse book close date from DD/MM/YYYY to YYYY-MM-DD for comparison.

    Returns None if the format is unrecognized.
    """
    if not date_str:
        return None
    parts = date_str.split("/")
    if len(parts) == 3:
        day, month, year = parts
        if len(year) == 4 and len(month) == 2 and len(day) == 2:
            return f"{year}-{month}-{day}"
    # If already in ISO format, return as-is
    if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
        return date_str
    return None


def _adjustment_factor(
    corporate_actions: Sequence[dict],
    bar_date: str,
) -> float:
    """Compute the cumulative adjustment factor for a given bar date.

    The factor compounds (1 + bonus_pct/100) × right_ratio for each action
    whose book_close date is STRICTLY LESS than the bar_date.

    The book_close date is the last day the old shares trade. The adjustment
    applies from the NEXT trading day onwards.

    right_ratio = (1 + right_pct/100) when right_pct is provided,
    otherwise 1.0.
    """
    factor = 1.0
    for action in corporate_actions:
        book_close = _parse_book_close(action.get("book_close") or "")
        if book_close is None:
            continue
        # Adjustment applies from the day AFTER book_close
        if book_close < bar_date:
            bonus_pct = action.get("bonus_pct")
            right_pct = action.get("right_pct")
            if bonus_pct is not None:
                factor *= 1.0 + float(bonus_pct) / 100.0
            if right_pct is not None:
                # right_pct as percentage means e.g. 50% = 1:2 rights = 1.5 ratio
                factor *= 1.0 + float(right_pct) / 100.0
    return factor


def adjusted_close_series(
    bars: Sequence[Bar],
    corporate_actions: Sequence[dict],
) -> list[Optional[float]]:
    """Return adjusted close prices for each bar.

    Adjusted close = raw close × adjustment_factor, where the adjustment
    factor compounds (1 + bonus_pct/100) × right_ratio for each corporate
    action with book_close date ≤ the bar's date.

    If no corporate actions are provided, returns the raw close prices.
    Missing close values yield None.
    """
    out: list[Optional[float]] = []
    for bar in bars:
        close = bar.close
        if close is None:
            out.append(None)
            continue
        factor = _adjustment_factor(corporate_actions, bar.date)
        out.append(float(close) * factor)
    return out

    def _rsi(g: float, l: float) -> float:
        if l == 0.0:
            return 100.0 if g > 0.0 else 50.0
        rs = g / l
        return 100.0 - (100.0 / (1.0 + rs))

    count = 0  # consecutive valid changes
    seed_gain = 0.0
    seed_loss = 0.0
    avg_gain: Optional[float] = None
    avg_loss: Optional[float] = None

    for i in range(1, len(closes)):
        prev_c, cur_c = closes[i - 1], closes[i]
        if prev_c is None or cur_c is None:
            # Break the chain: restart the warm-up after this gap.
            count = seed_gain = seed_loss = 0
            avg_gain = avg_loss = None
            out[i] = None
            continue
        delta = float(cur_c) - float(prev_c)
        gain, loss = max(delta, 0.0), max(-delta, 0.0)
        count += 1

        if count < period:
            seed_gain += gain
            seed_loss += loss
            out[i] = None
            continue
        if count == period:
            avg_gain = (seed_gain + gain) / period
            avg_loss = (seed_loss + loss) / period
        else:
            assert avg_gain is not None and avg_loss is not None
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi(avg_gain, avg_loss)
    return out


def macd(
    closes: Sequence[Optional[float]], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """Return `(macd_line, signal_line, histogram)`.

    The histogram is `macd - signal` and is `None` until both lines exist, so
    a "no crossover" reading is never rendered as a value of zero.
    """
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    line: list[Optional[float]] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ema, slow_ema)
    ]
    signal_line = ema(line, signal)
    hist: list[Optional[float]] = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(line, signal_line)
    ]
    return line, signal_line, hist


def roc(values: Sequence[Optional[float]], period: int = 1) -> list[Optional[float]]:
    """Rate of change in percent. `None` if the base is missing or zero."""
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period, len(values)):
        base, cur = values[i - period], values[i]
        if base is None or cur is None or base == 0:
            continue
        out[i] = (float(cur) - float(base)) / float(base) * 100.0
    return out


# ---------------------------------------------------------------------------
# Volatility / bands
# ---------------------------------------------------------------------------


def stdev(values: Sequence[float]) -> float:
    """Population standard deviation (used by Bollinger Bands)."""
    n = len(values)
    if n == 0:
        raise ValueError("stdev of empty sequence")
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return var**0.5


def bollinger(
    closes: Sequence[Optional[float]], period: int = 20, mult: float = 2.0
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]],
           list[Optional[float]], list[Optional[float]]]:
    """Return `(middle, upper, lower, bandwidth_pct, percent_b)`."""
    middle = sma(closes, period)
    upper: list[Optional[float]] = []
    lower: list[Optional[float]] = []
    bandwidth: list[Optional[float]] = []
    pct_b: list[Optional[float]] = []
    for i, close in enumerate(closes):
        mid = middle[i]
        if mid is None or i < period - 1:
            upper.append(None)
            lower.append(None)
            bandwidth.append(None)
            pct_b.append(None)
            continue
        window = closes[i - period + 1 : i + 1]
        if any(v is None for v in window):
            upper.append(None)
            lower.append(None)
            bandwidth.append(None)
            pct_b.append(None)
            continue
        sd = stdev([float(v) for v in window if v is not None])  # type: ignore[arg-type]
        up = mid + mult * sd
        lo = mid - mult * sd
        upper.append(up)
        lower.append(lo)
        bandwidth.append(((up - lo) / mid * 100.0) if mid != 0 else None)
        close_v = float(close) if close is not None else None  # type: ignore[arg-type]
        if close_v is None or up == lo:
            pct_b.append(None)
        else:
            pct_b.append((close_v - lo) / (up - lo) * 100.0)
    return middle, upper, lower, bandwidth, pct_b


def true_range(
    high: float, low: float, prev_close: Optional[float]
) -> float:
    """TR = max(H-L, |H-prevClose|, |L-prevClose|).

    `prev_close` being absent degrades to `H - L` rather than being dropped.
    """
    candidates = [high - low]
    if prev_close is not None:
        candidates.append(abs(high - prev_close))
        candidates.append(abs(low - prev_close))
    return max(candidates)


def atr(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Wilder-smoothed Average True Range, aligned to `bars`."""
    trs: list[Optional[float]] = []
    prev_close: Optional[float] = None
    for bar in bars:
        if bar.high is None or bar.low is None:
            trs.append(None)
            continue
        trs.append(true_range(float(bar.high), float(bar.low), prev_close))
        prev_close = bar.close
    if len(trs) < period:
        return [None] * len(trs)
    first_window = trs[:period]
    if any(t is None for t in first_window):
        return [None] * len(trs)
    acc = sum(float(t) for t in first_window if t is not None) / period  # type: ignore[arg-type]
    out: list[Optional[float]] = [None] * (period - 1) + [acc]
    for i in range(period, len(trs)):
        t = trs[i]
        if t is None:
            out.append(None)
            continue
        acc = (acc * (period - 1) + float(t)) / period
        out.append(acc)
    return out


# ---------------------------------------------------------------------------
# Volume / accumulation-distribution family
# ---------------------------------------------------------------------------


def money_flow_multiplier(bar: Bar) -> Optional[float]:
    """Chaikin's Money Flow Multiplier: ((C-L) - (H-C)) / (H-L).

    Returns None when the denominator is zero or data is missing. A day with
    high == low (limit-locked, or a single print) makes this genuinely
    undefined - it is NOT zero, and returning 0.0 here would show a flat
    line on days that actually had a strong directional close.
    """
    if bar.close is None or bar.high is None or bar.low is None:
        return None
    if not bar.has_range:
        return None
    return ((bar.close - bar.low) - (bar.high - bar.close)) / (bar.high - bar.low)


def money_flow_volume(bar: Bar) -> Optional[float]:
    """Multiplier x volume, or None when the multiplier is undefined."""
    mfm = money_flow_multiplier(bar)
    if mfm is None or bar.volume is None:
        return None
    return mfm * float(bar.volume)


def accumulation_distribution_line(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Cumulative Accumulation/Distribution line (Chaikin).

    Starts at 0 on the first bar. Days with an undefined multiplier are
    *skipped* (contributing nothing) rather than being treated as a drop to
    zero, so a limit-locked day does not create a fake divergence. The line is
    None only before the first day we can actually compute.
    """
    out: list[Optional[float]] = []
    running: Optional[float] = None
    for bar in bars:
        mfv = money_flow_volume(bar)
        if mfv is not None:
            running = mfv if running is None else running + mfv
        out.append(running)
    return out


#: Historical alias: the same series, spelled the way charting libraries do.
accumulation_distribution = accumulation_distribution_line


def obv(bars: Sequence[Bar]) -> list[Optional[float]]:
    """On-Balance Volume.

    Accumulates signed volume: +V on an up close, -V on a down close, and
    exactly 0.0 on an unchanged close. A flat day adds nothing, which is a
    genuine zero, not missing data.
    """
    out: list[Optional[float]] = []
    running = 0.0
    prev_close: Optional[float] = None
    for bar in bars:
        close, volume = bar.close, bar.volume
        if close is None or volume is None:
            # Cannot judge direction without a close: report the value so far
            # rather than inventing a step.
            out.append(running)
            continue
        close_f = float(close)
        if prev_close is not None:
            if close_f > prev_close:
                running += float(volume)
            elif close_f < prev_close:
                running -= float(volume)
        prev_close = close_f
        out.append(running)
    return out


def chaikin_money_flow(bars: Sequence[Bar], period: int = 20) -> list[Optional[float]]:
    """Rolling Chaikin Money Flow in percent: sum(MFV) / sum(volume) * 100.

    `None` until `period` usable bars exist, and None for a window whose
    total volume is zero (undefined, not "0% buying pressure").
    """
    if period <= 0:
        raise ValueError("period must be positive")
    mfvs = [money_flow_volume(b) for b in bars]
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(period - 1, len(bars)):
        window_mfv = mfvs[i - period + 1 : i + 1]
        window_vol = [b.volume for b in bars[i - period + 1 : i + 1]]
        if any(m is None for m in window_mfv) or any(v is None for v in window_vol):
            continue
        total_vol = sum(float(v) for v in window_vol if v is not None)
        if total_vol == 0.0:
            continue  # undefined: no shares traded in the window
        total_mfv = sum(float(m) for m in window_mfv if m is not None)
        out[i] = total_mfv / total_vol * 100.0
    return out


def vwap(bars: Sequence[Bar]) -> Optional[float]:
    """Cumulative VWAP over the given bars: sum(TP*V) / sum(V).

    Returns None when volume is missing or sums to zero.
    """
    num = 0.0
    den = 0.0
    for bar in bars:
        tp, vol = bar.typical_price, bar.volume
        if tp is None or vol is None:
            continue
        num += tp * float(vol)
        den += float(vol)
    if den == 0.0:
        return None
    return num / den


def vwap_series(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Running VWAP from the first bar, aligned to `bars`."""
    out: list[Optional[float]] = []
    num = 0.0
    den = 0.0
    for bar in bars:
        tp, vol = bar.typical_price, bar.volume
        if tp is not None and vol is not None:
            num += tp * float(vol)
            den += float(vol)
        out.append((num / den) if den > 0.0 else None)
    return out


def volume_sma_ratio(
    bars: Sequence[Bar], lookback: int = 20
) -> list[Optional[float]]:
    """Today's volume divided by its `lookback` average, as a percent.

    The alert engine's "volume spike" input. None during warm-up and when the
    average is zero.
    """
    vols: list[Optional[float]] = [b.volume for b in bars]
    avg = sma(vols, lookback)
    out: list[Optional[float]] = []
    for i, v in enumerate(vols):
        base = avg[i]
        if v is None or base is None or base == 0:
            out.append(None)
        else:
            out.append(float(v) / float(base) * 100.0)
    return out


def money_flow_index(
    bars: Sequence[Bar], period: int = 14
) -> list[Optional[float]]:
    """Chaikin Money Flow Index (0-100): the RSI analogue for money flow.

    Standard MFI over raw money flow (typical price x volume). For each of the
    `period` days ending at `i`, money flow is added to the positive or
    negative side depending on whether that day's typical price rose or fell
    against the day before it, so `period + 1` typical prices are required.

    A window with no negative flow returns 100.0, one with no positive flow
    returns 0.0, and a window with no directional flow at all returns 50.0
    (neutral). Those are real readings, so they are returned, not hidden.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    tps = [b.typical_price for b in bars]
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(period, len(bars)):
        lo = i - period
        if any(t is None for t in tps[lo : i + 1]):
            continue
        if any(bars[j].volume is None for j in range(lo, i + 1)):
            continue
        positive = 0.0
        negative = 0.0
        for j in range(lo + 1, i + 1):
            raw = float(tps[j]) * float(bars[j].volume)  # type: ignore[arg-type]
            if tps[j] > tps[j - 1]:  # type: ignore[operator]
                positive += raw
            elif tps[j] < tps[j - 1]:  # type: ignore[operator]
                negative += raw
        if positive == 0.0 and negative == 0.0:
            out[i] = 50.0
        elif negative == 0.0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - (100.0 / (1.0 + positive / negative))
    return out
