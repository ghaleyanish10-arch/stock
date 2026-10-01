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

import math
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

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


def _compute_on_valid(
    values: Sequence[Optional[float]],
    func: Callable[[Sequence[float]], Sequence[Optional[float]]],
) -> list[Optional[float]]:
    """Compute an indicator on only the non-None values, then map back.

    This allows indicators to skip gaps (null closes) rather than having a single
    null value poison the entire subsequent window. The output aligns with the
    input: positions where `values[i] is None` remain None; other positions get
    the computed value from the clean series.

    `func` receives a list of floats (no None) and returns a list of same length
    with Optional[float] (None during its own warm-up).
    """
    # Extract non-None values and their original indices
    valid_indices = [i for i, v in enumerate(values) if v is not None]
    valid_values = [float(values[i]) for i in valid_indices]  # type: ignore[arg-type]

    if not valid_values:
        return [None] * len(values)

    # Compute on clean series
    clean_result = func(valid_values)

    # Map back to original positions
    out: list[Optional[float]] = [None] * len(values)
    for orig_idx, result in zip(valid_indices, clean_result):
        out[orig_idx] = result
    return out


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


def sma_on_valid(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """SMA that skips null values in the input series.

    Unlike `sma`, this computes the average on only the valid (non-None) values
    within each window, as long as at least `period` valid values exist.
    Positions where the input is None remain None in the output.
    """
    def _sma_clean(vals: Sequence[float]) -> list[Optional[float]]:
        if period <= 0:
            raise ValueError("period must be positive")
        res: list[Optional[float]] = [None] * len(vals)
        for i in range(period - 1, len(vals)):
            res[i] = sum(vals[i - period + 1 : i + 1]) / period
        return res
    return _compute_on_valid(values, _sma_clean)


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


def ema_on_valid(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """EMA that skips null values in the input series.

    Unlike `ema`, this computes on a clean series with nulls removed, then maps
    results back to original positions. A single null close no longer breaks
    the entire subsequent EMA.
    """
    def _ema_clean(vals: Sequence[float]) -> list[Optional[float]]:
        if period <= 0:
            raise ValueError("period must be positive")
        alpha = 2.0 / (period + 1.0)
        out: list[Optional[float]] = [None] * len(vals)
        for i in range(len(vals)):
            if i < period - 1:
                continue
            if i == period - 1:
                out[i] = sum(vals[:i+1]) / period
            else:
                out[i] = alpha * vals[i] + (1 - alpha) * out[i-1]
        return out
    return _compute_on_valid(values, _ema_clean)


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


def rsi_on_valid(closes: Sequence[Optional[float]], period: int = 14) -> list[Optional[float]]:
    """RSI that skips null values in the input series.

    Computes RSI on a clean series with nulls removed, then maps results back.
    A single null close no longer resets the entire subsequent RSI.
    """
    def _rsi_clean(vals: Sequence[float]) -> list[Optional[float]]:
        if period <= 0:
            raise ValueError("period must be positive")
        out: list[Optional[float]] = [None] * len(vals)
        if len(vals) <= period:
            return out

        gains: list[float] = [0.0] * len(vals)
        losses: list[float] = [0.0] * len(vals)

        for i in range(1, len(vals)):
            change = vals[i] - vals[i - 1]
            if change >= 0:
                gains[i] = change
            else:
                losses[i] = -change

        avg_gain: Optional[float] = None
        avg_loss: Optional[float] = None

        for i in range(1, len(vals)):
            if avg_gain is None or avg_loss is None:
                if i < period:
                    continue
                window_gains = gains[i - period + 1 : i + 1]
                window_losses = losses[i - period + 1 : i + 1]
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
                alpha = 1.0 / period
                avg_gain = (1 - alpha) * avg_gain + alpha * gains[i]
                avg_loss = (1 - alpha) * avg_loss + alpha * losses[i]
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

    return _compute_on_valid(closes, _rsi_clean)


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


def macd_on_valid(
    closes: Sequence[Optional[float]], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """MACD that skips null values in the input series.

    The line, signal and histogram are computed on the non-`None` closes only
    (via the None-safe `macd`, which keeps its own warm-up as `None`), then
    mapped back to the original positions. A null close yields `None` at its
    own position but no longer poisons the windows after it.
    """
    valid_indices = [i for i, v in enumerate(closes) if v is not None]
    valid_values = [float(closes[i]) for i in valid_indices]  # type: ignore[arg-type]

    if not valid_values:
        n = len(closes)
        empty = [None] * n
        return empty, list(empty), list(empty)

    line_clean, signal_clean, hist_clean = macd(valid_values, fast, slow, signal)

    n = len(closes)
    line_out: list[Optional[float]] = [None] * n
    sig_out: list[Optional[float]] = [None] * n
    hist_out: list[Optional[float]] = [None] * n
    for orig_idx, (ln, sg, hc) in zip(valid_indices, zip(line_clean, signal_clean, hist_clean)):
        line_out[orig_idx] = ln
        sig_out[orig_idx] = sg
        hist_out[orig_idx] = hc

    return line_out, sig_out, hist_out


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


def bollinger_on_valid(
    closes: Sequence[Optional[float]], period: int = 20, mult: float = 2.0
) -> tuple[
    list[Optional[float]], list[Optional[float]], list[Optional[float]],
    list[Optional[float]], list[Optional[float]]
]:
    """Bollinger Bands that skip null values in the input series."""
    # Extract valid values and their indices
    valid_indices = [i for i, v in enumerate(closes) if v is not None]
    valid_values = [float(closes[i]) for i in valid_indices]  # type: ignore[arg-type]

    if not valid_values:
        n = len(closes)
        empty: list[Optional[float]] = [None] * n
        return (list(empty), list(empty), list(empty), list(empty), list(empty))

    # Compute on clean series
    middle, upper, lower, bandwidth, pct_b = bollinger(valid_values, period, mult)

    # Map back to original positions
    n = len(closes)
    m_out = [None] * n
    u_out = [None] * n
    l_out = [None] * n
    b_out = [None] * n
    p_out = [None] * n
    for orig_idx, (m, u, l, b, p) in zip(valid_indices, zip(middle, upper, lower, bandwidth, pct_b)):
        m_out[orig_idx] = m
        u_out[orig_idx] = u
        l_out[orig_idx] = l
        b_out[orig_idx] = b
        p_out[orig_idx] = p

    return m_out, u_out, l_out, b_out, p_out


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


# ---------------------------------------------------------------------------
# Trading Indicators notes: momentum oscillators (Stochastic, StochRSI, CCI,
# Williams %R, Momentum, Ultimate Oscillator, Awesome Oscillator, TSI, RVI)
# ---------------------------------------------------------------------------


def stochastic(
    bars: Sequence[Bar], k_period: int = 14, d_period: int = 3
) -> tuple[list[Optional[float]], list[Optional[float]]]:
    """Stochastic Oscillator: returns `(%K, %D)`, aligned to `bars`.

    %K = 100 * (C - L_n) / (H_n - L_n) compares the close to the n-bar range;
    %D is the d-period SMA of %K (the signal line). Crossovers and the usual
    80/20 bands carry the signal.

    Honesty rules: the window must contain `k_period` bars with high and low,
    else None. A window locked at one price (high == low, e.g. limit boards)
    makes %K genuinely undefined - None, not 0 and not 50.
    """
    if k_period <= 0 or d_period <= 0:
        raise ValueError("periods must be positive")
    n = len(bars)
    raw_k: list[Optional[float]] = [None] * n
    for i in range(k_period - 1, n):
        window = bars[i - k_period + 1 : i + 1]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if any(h is None for h in highs) or any(l is None for l in lows):
            continue
        hi = max(float(h) for h in highs if h is not None)
        lo = min(float(l) for l in lows if l is not None)
        close = bars[i].close
        if close is None:
            continue
        if hi == lo:
            continue  # undefined on a zero range, not zero
        raw_k[i] = (float(close) - lo) / (hi - lo) * 100.0
    d_line = sma(raw_k, d_period)
    return raw_k, d_line


def stoch_rsi(
    closes: Sequence[Optional[float]], rsi_period: int = 14, stoch_period: int = 14
) -> list[Optional[float]]:
    """Stochastic RSI on the 0-100 scale, per the notes' formula.

    Applies the Stochastic formula to RSI values instead of price:
    100 * (RSI - min(RSI, n)) / (max(RSI, n) - min(RSI, n)). Reads 0 at the
    bottom of its recent RSI range and 100 at the top; the notes call it the
    most overbought/oversold-sensitive of the RSI family.

    A flat RSI window (max == min) makes the ratio undefined - None, not 0.
    The RSI underneath uses the null-skipping variant, so one missing close
    costs one point rather than re-warming the whole RSI.
    """
    if rsi_period <= 0 or stoch_period <= 0:
        raise ValueError("periods must be positive")
    r = rsi_on_valid(closes, rsi_period)
    out: list[Optional[float]] = [None] * len(r)
    for i in range(stoch_period - 1, len(r)):
        window = [v for v in r[i - stoch_period + 1 : i + 1]]
        if any(v is None for v in window):
            continue
        cur = r[i]
        if cur is None:
            continue
        hi = max(float(v) for v in window if v is not None)
        lo = min(float(v) for v in window if v is not None)
        if hi == lo:
            continue
        out[i] = (float(cur) - lo) / (hi - lo) * 100.0
    return out


def cci(bars: Sequence[Bar], period: int = 20) -> list[Optional[float]]:
    """Commodity Channel Index per the notes: (TP - SMA(TP)) / (0.015 * MAD).

    TP is the typical price (H+L+C)/3; MAD is the mean absolute deviation of
    TP over the window. Unbounded by design - the 0.015 constant keeps the
    typical reading inside roughly +/-100 while breakouts run past it.

    Warm-up is `period - 1`; a bar missing high/low/close, or a window whose
    MAD is zero (every typical price equal), yields None.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    tps = [b.typical_price for b in bars]
    out: list[Optional[float]] = [None] * len(bars)
    means = sma(tps, period)
    for i in range(period - 1, len(bars)):
        mean = means[i]
        window = tps[i - period + 1 : i + 1]
        if mean is None or any(t is None for t in window):
            continue
        mad = sum(abs(float(t) - mean) for t in window if t is not None) / period
        if mad == 0.0:
            continue  # flat window: TP == mean, ratio 0/0 is undefined
        out[i] = (float(tps[i]) - mean) / (0.015 * mad)  # type: ignore[arg-type]
    return out


def williams_r(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Williams %R on the notes' 0 to -100 scale.

    %R = -100 * (HH_n - C) / (HH_n - LL_n): 0 means the close is at the very
    top of the n-bar range, -100 at the very bottom. A zero-range window
    (high == low) is undefined and yields None.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(period - 1, len(bars)):
        window = bars[i - period + 1 : i + 1]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if any(h is None for h in highs) or any(l is None for l in lows):
            continue
        hi = max(float(h) for h in highs if h is not None)
        lo = min(float(l) for l in lows if l is not None)
        close = bars[i].close
        if close is None:
            continue
        if hi == lo:
            continue
        # The + 0.0 turns the close-at-high case into 0.0, not -0.0.
        out[i] = (hi - float(close)) / (hi - lo) * -100.0 + 0.0
    return out


def momentum(values: Sequence[Optional[float]], period: int = 10) -> list[Optional[float]]:
    """Momentum per the notes: C_t - C_(t-n), the absolute price change.

    Unlike ROC this is in price units, not percent. None during warm-up and
    when either endpoint is missing.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period, len(values)):
        base, cur = values[i - period], values[i]
        if base is None or cur is None:
            continue
        out[i] = float(cur) - float(base)
    return out


def ultimate_oscillator(
    bars: Sequence[Bar], p1: int = 7, p2: int = 14, p3: int = 28
) -> list[Optional[float]]:
    """Ultimate Oscillator (Larry Williams): three averaged buying pressures.

    BP = C - min(L, prevC); TR = max(H, prevC) - min(L, prevC). Average_n =
    sum(BP, n) / sum(TR, n) and UO = 100 * (4*A7 + 2*A14 + A28) / 7. Weighting
    the shortest window most reduces the false divergences single-timeframe
    oscillators produce.

    The first value appears once 28 consecutive usable changes exist; any bar
    missing high/low/close (or the previous close) breaks the run and the
    warm-up restarts after the gap. A zero total TR makes the average
    undefined - None, not 0.
    """
    if min(p1, p2, p3) <= 0:
        raise ValueError("periods must be positive")
    n = len(bars)
    out: list[Optional[float]] = [None] * n
    longest = max(p1, p2, p3)
    for i in range(longest, n):
        bps: list[Optional[float]] = [None] * longest
        trs: list[Optional[float]] = [None] * longest
        usable = True
        for j in range(i - longest + 1, i + 1):
            cur, prev = bars[j], bars[j - 1]
            if (
                cur.high is None or cur.low is None or cur.close is None
                or prev.close is None
            ):
                usable = False
                break
            prev_c = float(prev.close)
            bp = float(cur.close) - min(float(cur.low), prev_c)
            tr = max(float(cur.high), prev_c) - min(float(cur.low), prev_c)
            bps[j - (i - longest + 1)] = bp
            trs[j - (i - longest + 1)] = tr
        if not usable:
            continue
        def avg(period: int) -> Optional[float]:
            w_bp = bps[-period:]
            w_tr = trs[-period:]
            if any(b is None for b in w_bp) or any(t is None for t in w_tr):
                return None
            tot_tr = sum(float(t) for t in w_tr if t is not None)
            if tot_tr == 0.0:
                return None
            return sum(float(b) for b in w_bp if b is not None) / tot_tr
        a1, a2, a3 = avg(p1), avg(p2), avg(p3)
        if a1 is None or a2 is None or a3 is None:
            continue
        out[i] = 100.0 * (4.0 * a1 + 2.0 * a2 + a3) / 7.0
    return out


def awesome_oscillator(
    bars: Sequence[Bar], fast: int = 5, slow: int = 34
) -> list[Optional[float]]:
    """Awesome Oscillator (Bill Williams): SMA5(median) - SMA34(median).

    The median price is (H + L) / 2. Crosses above/below zero mark momentum
    shifts; the saucer and twin-peaks setups read the histogram's shape.
    """
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError("require 0 < fast < slow")
    medians = [
        ((b.high + b.low) / 2.0) if (b.high is not None and b.low is not None) else None
        for b in bars
    ]
    fast_ma = sma(medians, fast)
    slow_ma = sma(medians, slow)
    return [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ma, slow_ma)
    ]


def tsi(
    closes: Sequence[Optional[float]], long_period: int = 25, short_period: int = 13
) -> list[Optional[float]]:
    """True Strength Index: 100 * EMA13(EMA25(PC)) / EMA13(EMA25(|PC|)).

    Double-smoothed momentum that keeps trend direction readable through
    noise; divergences and signal-line crossings carry the interpretation.

    Uses the strict `ema` (a missing close breaks that run and both smoothings
    re-warm after it). A flat series makes the denominator zero - TSI is
    undefined there, None not 0.
    """
    if long_period <= 0 or short_period <= 0:
        raise ValueError("periods must be positive")
    pc: list[Optional[float]] = [None] * len(closes)
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None:
            continue
        pc[i] = float(cur) - float(prev)
    smooth_pc = ema(ema(pc, long_period), short_period)
    abs_pc = [None if p is None else abs(p) for p in pc]
    smooth_abs = ema(ema(abs_pc, long_period), short_period)
    out: list[Optional[float]] = [None] * len(closes)
    for i, (num, den) in enumerate(zip(smooth_pc, smooth_abs)):
        if num is None or den is None or den == 0.0:
            continue
        out[i] = 100.0 * num / den
    return out


def rvi(bars: Sequence[Bar]) -> tuple[list[Optional[float]], list[Optional[float]]]:
    """Relative Vigor Index per the notes' symmetric-weight formula.

    Value = (C - O) / (H - L) - where the close sits inside the bar's range
    relative to its open. RVI = (V + 2V1 + 2V2 + V3) / 6 weights the middle
    bars most; the signal line applies the same smoothing to RVI. Crossovers
    of the pair time the fade of counter-trend vigor.

    A bar missing open/high/low/close, or locked at one price (H == L), has no
    defined vigor and contributes None; the 4-bar smoothing needs four
    non-None values, and the signal needs four more.
    """
    n = len(bars)
    value: list[Optional[float]] = [None] * n
    for i, b in enumerate(bars):
        if None in (b.open, b.high, b.low, b.close):
            continue
        if not b.has_range:
            continue
        value[i] = (float(b.close) - float(b.open)) / (float(b.high) - float(b.low))  # type: ignore[arg-type]

    def sym_smooth(src: list[Optional[float]]) -> list[Optional[float]]:
        out: list[Optional[float]] = [None] * n
        for i in range(3, n):
            w = [src[i], src[i - 1], src[i - 2], src[i - 3]]
            if any(v is None for v in w):
                continue
            v0, v1, v2, v3 = (float(x) for x in w)  # type: ignore[arg-type]
            out[i] = (v0 + 2.0 * v1 + 2.0 * v2 + v3) / 6.0
        return out

    return sym_smooth(value), sym_smooth(sym_smooth(value))


# ---------------------------------------------------------------------------
# Trading Indicators notes: volatility (Std Dev, Keltner, Donchian,
# Historical Volatility, Chaikin Volatility)
# ---------------------------------------------------------------------------


def stdev_series(
    values: Sequence[Optional[float]], period: int = 20
) -> list[Optional[float]]:
    """Rolling population standard deviation of price.

    The dispersion measure behind Bollinger Bands, exposed on its own per the
    notes: higher readings = wider spread around the mean. None during the
    warm-up and for any window containing a missing value.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = stdev([float(v) for v in window if v is not None])  # type: ignore[arg-type]
    return out


def keltner(
    bars: Sequence[Bar], period: int = 20, mult: float = 2.0, atr_period: int = 10
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """Keltner Channels: returns `(middle, upper, lower)`.

    Middle = EMA(close, N); bands sit M ATRs either side. Price riding the
    upper band marks a strong uptrend, a close outside the bands often
    precedes a reversion back toward the middle line.

    A position is None when either the EMA or the ATR underneath it is still
    warming up (ATR's first-window gap rule applies, as elsewhere).
    """
    if period <= 0 or atr_period <= 0 or mult <= 0:
        raise ValueError("period, atr_period and mult must be positive")
    closes = [b.close for b in bars]
    mid = ema(closes, period)
    atrs = atr(bars, atr_period)
    upper: list[Optional[float]] = []
    lower: list[Optional[float]] = []
    for m, a in zip(mid, atrs):
        if m is None or a is None:
            upper.append(None)
            lower.append(None)
        else:
            upper.append(m + mult * float(a))
            lower.append(m - mult * float(a))
    return mid, upper, lower


def donchian(
    bars: Sequence[Bar], period: int = 20
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """Donchian Channels: returns `(upper, lower, middle)`.

    Upper is the highest high and lower the lowest low of the window (the
    current bar included), middle their average. Breakouts above the upper or
    below the lower channel are the classic trend-entry signal. A window with
    any missing high/low yields None at that position.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(bars)
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n
    middle: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        window = bars[i - period + 1 : i + 1]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if any(h is None for h in highs) or any(l is None for l in lows):
            continue
        hi = max(float(h) for h in highs if h is not None)
        lo = min(float(l) for l in lows if l is not None)
        upper[i] = hi
        lower[i] = lo
        middle[i] = (hi + lo) / 2.0
    return upper, lower, middle


def historical_volatility(
    closes: Sequence[Optional[float]], period: int = 20, trading_days: int = 252
) -> list[Optional[float]]:
    """Annualized Historical Volatility in percent.

    Sample standard deviation (N-1 denominator, per the notes) of log returns
    over the window, scaled by sqrt(trading_days) * 100. This is the risk
    yardstick: comparing symbols' HV ranks them by realized volatility.

    None during warm-up and for windows touching a missing close.
    """
    if period <= 1:
        raise ValueError("period must exceed 1 (at least one return per window)")
    if trading_days <= 0:
        raise ValueError("trading_days must be positive")
    returns: list[Optional[float]] = [None] * len(closes)
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None or prev <= 0:
            continue
        returns[i] = math.log(float(cur) / float(prev))
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period, len(returns)):
        window = returns[i - period + 1 : i + 1]
        if any(r is None for r in window):
            continue
        vals = [float(r) for r in window if r is not None]
        mean = sum(vals) / period
        var = sum((v - mean) ** 2 for v in vals) / (period - 1)
        out[i] = (var**0.5) * (trading_days**0.5) * 100.0
    return out


def chaikin_volatility(
    bars: Sequence[Bar], ema_period: int = 10, roc_period: int = 10
) -> list[Optional[float]]:
    """Chaikin Volatility: percent change of the EMA of the high-low range.

    CV = 100 * (EMA_t - EMA_(t-x)) / EMA_(t-x). Rising CV = ranges expanding
    (trends and panics), falling CV = ranges contracting (quiet, often ahead
    of a move). The first value appears after `roc_period` EMA readings exist;
    a zero base EMA (a run of exactly flat ranges) makes the ratio undefined -
    None, not 0.
    """
    if ema_period <= 0 or roc_period <= 0:
        raise ValueError("periods must be positive")
    ranges = [
        (float(b.high) - float(b.low)) if (b.high is not None and b.low is not None) else None
        for b in bars
    ]
    smoothed = ema(ranges, ema_period)
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(roc_period, len(bars)):
        cur, base = smoothed[i], smoothed[i - roc_period]
        if cur is None or base is None or base == 0.0:
            continue
        out[i] = (cur - base) / base * 100.0
    return out


# ---------------------------------------------------------------------------
# Trading Indicators notes: volume family (VPT, EMV, Force Index,
# Volume Oscillator, Klinger, Chaikin Oscillator, VWMA, CVD)
# ---------------------------------------------------------------------------


def volume_price_trend(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Volume Price Trend: cumulative volume scaled by percent price change.

    VPT_t = VPT_(t-1) + V * (C - C_prev) / C_prev. Unlike OBV's flat +/-V
    steps, a 10% move on thin volume can outweigh a 0.1% move on heavy
    volume, which is the notes' point.

    Starts at 0.0 (the first bar has no previous close to move from). A bar
    with a missing close or volume, or a zero previous close, contributes no
    step - the line holds its level, it does not reset.
    """
    out: list[Optional[float]] = []
    running = 0.0
    prev_close: Optional[float] = None
    for b in bars:
        if b.close is not None and b.volume is not None and prev_close not in (None, 0.0):
            running += float(b.volume) * (float(b.close) - prev_close) / prev_close  # type: ignore[arg-type]
        if b.close is not None:
            prev_close = float(b.close)
        out.append(running)
    return out


def ease_of_movement(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Ease of Movement (EVM) per the notes, SMA-smoothed.

    Distance Moved = midpoint(H,L)_t - midpoint(H,L)_(t-1); Box Ratio =
    (V / 10,000,000) / (H - L); EVM1 = Distance / Box Ratio. Big midpoint
    moves on little volume read as large positive/negative EVM - price moving
    "easily". The result is smoothed by a `period` SMA.

    A bar with high == low has no box (undefined, not infinite) and yields
    None; so does any window touching a missing high/low/volume.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(bars)
    raw: list[Optional[float]] = [None] * n
    for i in range(1, n):
        cur, prev = bars[i], bars[i - 1]
        if (
            not cur.has_range or not prev.has_range
            or cur.high is None or cur.low is None
            or prev.high is None or prev.low is None
            or cur.volume is None
        ):
            continue
        dist = (float(cur.high) + float(cur.low)) / 2.0 - (float(prev.high) + float(prev.low)) / 2.0
        box = (float(cur.volume) / 10_000_000.0) / (float(cur.high) - float(cur.low))
        raw[i] = dist / box
    return sma(raw, period)


def force_index(bars: Sequence[Bar], period: int = 13) -> list[Optional[float]]:
    """Force Index (Elder): EMA-smoothed (C - C_prev) * V.

    Direction times magnitude times participation. The raw 1-period force is
    None whenever the close, the previous close or the volume is missing; the
    EMA smoothing resumes after the gap, per the shared ema rules.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    raw: list[Optional[float]] = [None] * len(bars)
    for i in range(1, len(bars)):
        cur, prev = bars[i], bars[i - 1]
        if cur.close is None or prev.close is None or cur.volume is None:
            continue
        raw[i] = (float(cur.close) - float(prev.close)) * float(cur.volume)
    return ema(raw, period)


def volume_oscillator(
    bars: Sequence[Bar], short_period: int = 5, long_period: int = 20
) -> list[Optional[float]]:
    """Volume Oscillator in percent: (MA_short(V) - MA_long(V)) / MA_long * 100.

    Positive = volume expanding above its longer average (conviction behind
    the current move), negative = volume drying up. None until the long MA is
    warm, and None when the long average is exactly zero (no shares traded in
    the whole window - undefined, not -100%).
    """
    if short_period <= 0 or long_period <= 0 or short_period >= long_period:
        raise ValueError("require 0 < short_period < long_period")
    vols = [b.volume for b in bars]
    fast = sma(vols, short_period)
    slow = sma(vols, long_period)
    out: list[Optional[float]] = [None] * len(bars)
    for i, (f, s) in enumerate(zip(fast, slow)):
        if f is None or s is None or s == 0.0:
            continue
        out[i] = (f - s) / s * 100.0
    return out


def klinger_oscillator(
    bars: Sequence[Bar], fast: int = 34, slow: int = 55
) -> list[Optional[float]]:
    """Klinger Volume Oscillator per the notes' Volume Force formula.

    Trend = +1 when (H+L+C) rises against the previous bar, else -1; VF =
    V * |2 * Change/Range - 1| * Trend * 100; the oscillator is EMA34(VF) -
    EMA55(VF). Divergence between KVO and price is its long-term signal.

    A bar with a zero range (H == L) has an undefined Change/Range term and
    contributes None; missing high/low/close/volume likewise. The EMA runs
    re-warm after gaps per the shared ema rules.
    """
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError("require 0 < fast < slow")
    n = len(bars)
    vf: list[Optional[float]] = [None] * n
    for i in range(1, n):
        cur, prev = bars[i], bars[i - 1]
        if (
            cur.high is None or cur.low is None or cur.close is None or cur.volume is None
            or prev.high is None or prev.low is None or prev.close is None
        ):
            continue
        hlc_cur = float(cur.high) + float(cur.low) + float(cur.close)
        hlc_prev = float(prev.high) + float(prev.low) + float(prev.close)
        rng = float(cur.high) - float(cur.low)
        if rng == 0.0:
            continue
        trend = 1.0 if hlc_cur > hlc_prev else -1.0
        vf[i] = float(cur.volume) * abs(2.0 * (hlc_cur - hlc_prev) / rng - 1.0) * trend * 100.0
    fast_ma = ema(vf, fast)
    slow_ma = ema(vf, slow)
    return [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ma, slow_ma)
    ]


def chaikin_oscillator(
    bars: Sequence[Bar], fast: int = 3, slow: int = 10
) -> list[Optional[float]]:
    """Chaikin Oscillator: EMA3(A/D) - EMA10(A/D).

    The MACD construction applied to the Accumulation/Distribution line: a
    rising oscillator confirms money flowing in, a falling one distribution.
    None until both EMAs of the A/D line exist; the A/D's own leading-None
    rule propagates.
    """
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError("require 0 < fast < slow")
    ad = accumulation_distribution_line(bars)
    fast_ma = ema(ad, fast)
    slow_ma = ema(ad, slow)
    return [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ma, slow_ma)
    ]


def vwma(
    closes: Sequence[Optional[float]], volumes: Sequence[Optional[float]], period: int = 20
) -> list[Optional[float]]:
    """Volume-Weighted Moving Average: sum(C*V) / sum(V) over the window.

    High-volume sessions steer the average, which is the notes' contrast with
    the SMA. None during warm-up, for windows touching missing data, and when
    the window's total volume is zero (undefined, not 0).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) != len(volumes):
        raise ValueError("closes and volumes must align")
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        c_win = closes[i - period + 1 : i + 1]
        v_win = volumes[i - period + 1 : i + 1]
        if any(c is None for c in c_win) or any(v is None for v in v_win):
            continue
        total_v = sum(float(v) for v in v_win if v is not None)
        if total_v == 0.0:
            continue
        out[i] = sum(
            float(c) * float(v) for c, v in zip(c_win, v_win) if c is not None and v is not None
        ) / total_v
    return out


def cumulative_volume_delta(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Cumulative Volume Delta, daily-bar approximation, honestly labelled.

    The notes define delta as ask-side minus bid-side volume, which needs tick
    classification NEPSE does not publish. The standard daily proxy assumes
    the delta of a session takes the sign of its close-to-close change:
    delta = +V on an up close, -V on a down close, 0 on unchanged - i.e. the
    OBV step, accumulated the same way. Rendered as CVD it highlights
    sustained one-sided participation; it is NOT tick-grade order flow.

    Starts at 0.0; missing close/volume contributes no step (line holds).
    """
    return obv(bars)


# ---------------------------------------------------------------------------
# Trading Indicators notes: volume profile (VPFR / VPVR shared computation)
# ---------------------------------------------------------------------------


def volume_profile(
    bars: Sequence[Bar], bins: int = 24, value_area_pct: float = 70.0
) -> dict[str, Any]:
    """Volume-at-price histogram over the given bars, with POC and value area.

    Each bar's volume is spread uniformly across its high-low range and
    accumulated into `bins` price buckets spanning the window's lowest low to
    highest high. Returns:

      levels    - [{price_low, price_high, volume}] per bucket
      poc       - Point of Control: midpoint of the heaviest bucket
      va_high / va_low - the value-area bounds around the POC covering
                  `value_area_pct` of all volume (grown outward, taking the
                  fatter neighbour each step, the usual algorithm)

    The chart renders POC / value-area lines; the histogram itself is the
    levels list. Bars missing high/low/volume are skipped. A window with no
    usable bar returns empty levels and None bounds - an honest blank, never
    a synthetic level.
    """
    if bins <= 0:
        raise ValueError("bins must be positive")
    if not 0 < value_area_pct <= 100:
        raise ValueError("value_area_pct must be in (0, 100]")
    usable = [
        b for b in bars
        if b.high is not None and b.low is not None and b.volume is not None
    ]
    if not usable:
        return {"levels": [], "poc": None, "va_high": None, "va_low": None}
    lo = min(float(b.low) for b in usable)  # type: ignore[arg-type]
    hi = max(float(b.high) for b in usable)  # type: ignore[arg-type]
    if hi == lo:
        # The whole window traded at one price: a single bucket.
        total = sum(float(b.volume) for b in usable if b.volume is not None)  # type: ignore[arg-type]
        return {
            "levels": [{"price_low": lo, "price_high": hi, "volume": total}],
            "poc": lo,
            "va_high": hi,
            "va_low": lo,
        }
    width = (hi - lo) / bins
    vols = [0.0] * bins
    for b in usable:
        bar_lo, bar_hi = float(b.low), float(b.high)  # type: ignore[arg-type]
        vol = float(b.volume)  # type: ignore[arg-type]
        if bar_hi == bar_lo:
            idx = min(bins - 1, int((bar_lo - lo) / width))
            vols[idx] += vol
            continue
        first = max(0, int((bar_lo - lo) / width))
        last = min(bins - 1, int((bar_hi - lo) / width))
        span = bar_hi - bar_lo
        for k in range(first, last + 1):
            overlap = min(bar_hi, lo + (k + 1) * width) - max(bar_lo, lo + k * width)
            if overlap > 0:
                vols[k] += vol * (overlap / span)
    total = sum(vols)
    poc_idx = max(range(bins), key=lambda k: vols[k])

    # Value area: grow from the POC, always absorbing the fatter neighbour.
    lo_i, hi_i = poc_idx, poc_idx
    acc = vols[poc_idx]
    target = total * value_area_pct / 100.0
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        left = vols[lo_i - 1] if lo_i > 0 else -1.0
        right = vols[hi_i + 1] if hi_i < bins - 1 else -1.0
        if right >= left:
            hi_i += 1
            acc += vols[hi_i]
        else:
            lo_i -= 1
            acc += vols[lo_i]
    return {
        "levels": [
            {
                "price_low": lo + k * width,
                "price_high": lo + (k + 1) * width,
                "volume": vols[k],
            }
            for k in range(bins)
        ],
        "poc": lo + (poc_idx + 0.5) * width,
        "va_high": lo + (hi_i + 1) * width,
        "va_low": lo + lo_i * width,
    }


# ---------------------------------------------------------------------------
# Trading Indicators notes: pivot points (Standard, Camarilla, Woodie, DeMark)
# ---------------------------------------------------------------------------


def pivot_points(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Standard floor-trader pivots, one row per bar from the previous bar.

    P = (H + L + C) / 3 of the PREVIOUS session; R1/S1 = 2P -+ L/H, R2/S2 =
    P +-(H - L), R3 = H + 2(P - L), S3 = L - 2(H - P). Every series aligns
    with `bars`; the first bar (no previous session) is None, as is any bar
    whose predecessor is missing high/low/close.
    """
    n = len(bars)
    keys = ("pp", "r1", "r2", "r3", "s1", "s2", "s3")
    out = {k: [None] * n for k in keys}
    for i in range(1, n):
        prev = bars[i - 1]
        if prev.high is None or prev.low is None or prev.close is None:
            continue
        h, l, c = float(prev.high), float(prev.low), float(prev.close)
        p = (h + l + c) / 3.0
        out["pp"][i] = p
        out["r1"][i] = 2.0 * p - l
        out["s1"][i] = 2.0 * p - h
        out["r2"][i] = p + (h - l)
        out["s2"][i] = p - (h - l)
        out["r3"][i] = h + 2.0 * (p - l)
        out["s3"][i] = l - 2.0 * (h - p)
    return out


def camarilla_pivots(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Camarilla pivots: eight bands at 1.1*(H-L)/{12,6,4,2} around the close.

    R3/S3 are the range-trade reversal zones, R4/S4 the breakout levels. The
    central P is the standard (H+L+C)/3. Same alignment rules as the standard
    pivots: levels at bar i come from bar i-1's H/L/C.
    """
    n = len(bars)
    keys = ("pp", "r1", "r2", "r3", "r4", "s1", "s2", "s3", "s4")
    out = {k: [None] * n for k in keys}
    coeffs = {"r1": 12.0, "r2": 6.0, "r3": 4.0, "r4": 2.0}
    for i in range(1, n):
        prev = bars[i - 1]
        if prev.high is None or prev.low is None or prev.close is None:
            continue
        h, l, c = float(prev.high), float(prev.low), float(prev.close)
        rng = h - l
        out["pp"][i] = (h + l + c) / 3.0
        for key, den in coeffs.items():
            out[key][i] = c + rng * 1.1 / den
            out["s" + key[1:]][i] = c - rng * 1.1 / den
    return out


def woodie_pivots(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Woodie's pivots: the close counts double, the current open anchors.

    P = (H + L + 2C) / 4 of the PREVIOUS session, with R/S levels computed
    like the standard set; the pivot is only valid from the current bar's
    open, so a bar with a missing open yields None even when the previous
    bar's H/L/C are fine (the notes need O of the current period).
    """
    n = len(bars)
    keys = ("pp", "r1", "r2", "r3", "s1", "s2", "s3")
    out = {k: [None] * n for k in keys}
    for i in range(1, n):
        prev, cur = bars[i - 1], bars[i]
        if (
            prev.high is None or prev.low is None or prev.close is None
            or cur.open is None
        ):
            continue
        h, l, c = float(prev.high), float(prev.low), float(prev.close)
        p = (h + l + 2.0 * c) / 4.0
        out["pp"][i] = p
        out["r1"][i] = 2.0 * p - l
        out["s1"][i] = 2.0 * p - h
        out["r2"][i] = p + (h - l)
        out["s2"][i] = p - (h - l)
        out["r3"][i] = h + 2.0 * (p - l)
        out["s3"][i] = l - 2.0 * (h - p)
    return out


def demark_pivots(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """DeMark pivots: X depends on the previous session's close vs open.

    C < O: X = H + 2L + C; C > O: X = 2H + L + C; C = O: X = H + L + 2C.
    Then P = X/4, R1 = X/2 - L, S1 = X/2 - H - the notes project exactly one
    expected high and low. Alignment as usual: bar i's levels from bar i-1.
    """
    n = len(bars)
    out: dict[str, list[Optional[float]]] = {
        "pp": [None] * n,
        "r1": [None] * n,
        "s1": [None] * n,
    }
    for i in range(1, n):
        prev = bars[i - 1]
        if (
            prev.open is None or prev.high is None
            or prev.low is None or prev.close is None
        ):
            continue
        o, h, l, c = (float(prev.open), float(prev.high), float(prev.low), float(prev.close))
        if c < o:
            x = h + 2.0 * l + c
        elif c > o:
            x = 2.0 * h + l + c
        else:
            x = h + l + 2.0 * c
        out["pp"][i] = x / 4.0
        out["r1"][i] = x / 2.0 - l
        out["s1"][i] = x / 2.0 - h
    return out


# ---------------------------------------------------------------------------
# Trading Indicators notes: Fibonacci retracement / extension / fan
# ---------------------------------------------------------------------------


def _window_swings(bars: Sequence[Bar]) -> Optional[tuple[int, float, int, float, bool]]:
    """Locate the window's swing pair: (i_from, p_from, i_to, p_to, uptrend).

    The swing low/high are the window's lowest low / highest high. The move
    is an uptrend when the low happens first (price travelled low -> high);
    ties on equal extremes resolve to the earliest occurrence so the pair is
    deterministic. Returns None when the window has no usable high/low.
    """
    i_low: Optional[int] = None
    i_high: Optional[int] = None
    low = math.inf
    high = -math.inf
    for i, b in enumerate(bars):
        if b.low is not None and float(b.low) < low:
            low = float(b.low)
            i_low = i
        if b.high is not None and float(b.high) > high:
            high = float(b.high)
            i_high = i
    if i_low is None or i_high is None:
        return None
    if i_low <= i_high:
        return i_low, low, i_high, high, True
    return i_high, high, i_low, low, False


def fibonacci_retracement(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Fibonacci retracement of the window's swing, as aligned level series.

    Levels R_k sit at P2 -+ (|P2 - P1| * k) for k in {0.236, 0.382, 0.5,
    0.618, 0.786} - measured back from the swing END (P2) into the move
    (upwards off a low in an uptrend, downwards off a high in a downtrend,
    per the notes). Each series is None before the swing's end bar and flat
    at its level afterwards, so the lines start where the swing completes.
    """
    n = len(bars)
    keys = ("fib_236", "fib_382", "fib_500", "fib_618", "fib_786")
    ratios = (0.236, 0.382, 0.5, 0.618, 0.786)
    out = {k: [None] * n for k in keys}
    swing = _window_swings(bars)
    if swing is None:
        return out
    i_from, p_from, i_to, p_to, uptrend = swing
    delta = abs(p_to - p_from)
    for i in range(i_to, n):
        for key, k in zip(keys, ratios):
            out[key][i] = p_to - delta * k if uptrend else p_to + delta * k
    return out


def fibonacci_extension(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Fibonacci extension targets projected from the pullback point C.

    With A/B the swing pair, C is the deepest pullback after B (or B's close
    when no pullback exists yet). Targets E_k = C +-(AB * k) for k in {0.618,
    1.0, 1.272, 1.618, 2.618}, measured in the trend's direction. Series are
    None before B and flat afterwards; retracement less than the full swing
    leaves C between A and B, which is exactly the notes' construction.
    """
    n = len(bars)
    keys = ("fibe_618", "fibe_1000", "fibe_1272", "fibe_1618", "fibe_2618")
    ratios = (0.618, 1.0, 1.272, 1.618, 2.618)
    out = {k: [None] * n for k in keys}
    swing = _window_swings(bars)
    if swing is None:
        return out
    i_from, p_from, i_to, p_to, uptrend = swing
    ab = abs(p_to - p_from)
    # C: the most extreme price after the swing end, in the trend's direction.
    c_price = p_to
    for b in bars[i_to + 1 :]:
        if uptrend and b.low is not None and float(b.low) < c_price:
            c_price = float(b.low)
        if not uptrend and b.high is not None and float(b.high) > c_price:
            c_price = float(b.high)
    sign = 1.0 if uptrend else -1.0
    for i in range(i_to, n):
        for key, k in zip(keys, ratios):
            out[key][i] = c_price + sign * ab * k
    return out


def fibonacci_fan(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Fibonacci fan lines drawn from the swing start through its divisions.

    The vertical move between swing points is divided at k in {0.382, 0.5,
    0.618} (yk = yA + dy * k at the swing end's x); each fan line runs from A
    through (xB, yk) and keeps that slope past B, so the series values are
    the straight-line projections - diagonal support/resistance in price
    terms. None before the swing's start bar, as the fan has no origin before
    A. The slope degenerates to None when the swing spans a single bar
    (division by a zero x-span).
    """
    n = len(bars)
    keys = ("fibf_382", "fibf_500", "fibf_618")
    ratios = (0.382, 0.5, 0.618)
    out = {k: [None] * n for k in keys}
    swing = _window_swings(bars)
    if swing is None:
        return out
    i_from, p_from, i_to, p_to, _uptrend = swing
    if i_to == i_from:
        return out  # zero horizontal span: fan lines are vertical, undefined
    dy = p_to - p_from
    for i in range(i_from, n):
        t = (i - i_from) / (i_to - i_from)
        for key, k in zip(keys, ratios):
            out[key][i] = p_from + dy * k * t
    return out


# ---------------------------------------------------------------------------
# Batch B primitives: shared building blocks for the 57-indicator doc
# ---------------------------------------------------------------------------


def rma(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Wilder's smoothing (RMA / SMMA), seeded with an SMA of the first `period`.

    rma_t = (rma_{t-1} * (N - 1) + value_t) / N - the smoothing behind
    Wilder's ATR/ADX, the SMMA entry of the notes and the Alligator's jaw,
    teeth and lips. Runs of consecutive non-`None` values are smoothed
    independently and the warm-up window is `None`, mirroring `ema`.
    """
    if period <= 0:
        raise ValueError("period must be positive")
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
            out[i] = sum(float(x) for x in values[run_start : i + 1]) / period  # type: ignore[arg-type]
        else:
            prev = out[i - 1]
            if prev is None:  # pragma: no cover - unreachable within a run
                continue
            out[i] = (prev * (period - 1) + float(v)) / period
    return out


def highest(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Rolling maximum of the last `period` values.

    Same gap rule as `sma`: a window containing a missing value yields `None`,
    and the warm-up window is `None` too.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = max(float(v) for v in window)  # type: ignore[arg-type]
    return out


def lowest(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Rolling minimum of the last `period` values; gap rules as `highest`."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = min(float(v) for v in window)  # type: ignore[arg-type]
    return out


def _linreg_coeffs(ys: Sequence[float]) -> tuple[float, float]:
    """Least-squares fit y = a + b*x with x = 0..n-1. Returns (a, b)."""
    n = len(ys)
    if n < 2:
        raise ValueError("need at least two points for a linear fit")
    mean_x = (n - 1) / 2.0
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in range(n))
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(range(n), ys))
    b = sxy / sxx
    a = mean_y - b * mean_x
    return a, b


def linreg_endpoint(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Linear-regression curve: fitted value at the window's end (LSMA).

    Fits y = a + b*x over each window of `period` non-None values and reports
    a + b*(period - 1) - the value the fitted line takes at the newest bar.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        a, b = _linreg_coeffs([float(v) for v in window])  # type: ignore[arg-type]
        out[i] = a + b * (period - 1)
    return out


def linreg_slope(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Slope of the least-squares line over each trailing window.

    Positive when the series trends up, negative when down; units are price
    per bar. A perfectly flat window slopes 0.0 - a genuine zero, not a gap.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        _, b = _linreg_coeffs([float(v) for v in window])  # type: ignore[arg-type]
        out[i] = b
    return out


def percentrank(values: Sequence[Optional[float]], period: int) -> list[Optional[float]]:
    """Percent rank of the current value inside its trailing window (0-100).

    Counts how many of the window's other values are <= the current one and
    scales by (period - 1), so the window's minimum ranks 0.0 and its maximum
    ranks 100.0. `None` while the window is incomplete or contains a gap.
    Used by Connors RSI's percent-rank-of-ROC leg.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        cur = float(window[-1])  # type: ignore[arg-type]
        below = sum(1 for v in window[:-1] if float(v) <= cur)  # type: ignore[arg-type]
        out[i] = below / (period - 1) * 100.0
    return out


def hl2_series(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Median price per bar: (H + L) / 2; `None` when either is missing."""
    out: list[Optional[float]] = []
    for b in bars:
        if b.high is None or b.low is None:
            out.append(None)
        else:
            out.append((float(b.high) + float(b.low)) / 2.0)
    return out


def hlc3_series(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Typical price per bar: (H + L + C) / 3; `None` when any is missing."""
    out: list[Optional[float]] = []
    for b in bars:
        if b.high is None or b.low is None or b.close is None:
            out.append(None)
        else:
            out.append((float(b.high) + float(b.low) + float(b.close)) / 3.0)
    return out


def ohlc4_series(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Average price per bar: (O + H + L + C) / 4; `None` when any is missing."""
    out: list[Optional[float]] = []
    for b in bars:
        if b.open is None or b.high is None or b.low is None or b.close is None:
            out.append(None)
        else:
            out.append((float(b.open) + float(b.high) + float(b.low) + float(b.close)) / 4.0)
    return out


# ---------------------------------------------------------------------------
# Batch B doc #1-#6: ALMA, ASI, Average Price, EMA cross, MA cross, MA/EMA cross
# ---------------------------------------------------------------------------


def alma(
    values: Sequence[Optional[float]],
    period: int = 9,
    offset: float = 0.85,
    sigma: float = 6.0,
) -> list[Optional[float]]:
    """Arnaud Legoux Moving Average: Gaussian-weighted mean that trades lag
    for smoothness.

    Window weights w_i = exp(-((i - m)^2) / (2 s^2)) with m = offset *
    (period - 1) and s = period / sigma, i running oldest -> newest; the value
    is the w-weighted mean of the window. Defaults are the common 9 / 0.85 / 6
    setting. On a constant series ALMA equals that constant. `None` during the
    warm-up and for windows containing a gap, as everywhere here.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    m = offset * (period - 1)
    s = period / sigma
    denom = 2.0 * s * s
    weights = [math.exp(-((i - m) ** 2) / denom) for i in range(period)]
    wsum = sum(weights)
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(w * float(v) for w, v in zip(weights, window)) / wsum  # type: ignore[arg-type]
    return out


def asi(bars: Sequence[Bar], limit_move: Optional[float] = None) -> list[Optional[float]]:
    """Accumulative Swing Index (Wilder), cumulative across the series.

    Per bar (needs the current and previous session's OHLC):
      delta_c = C_t - C_{t-1};  body_t = C_t - O_t;  body_prev = C_{t-1} - O_{t-1}
      K = max(|H_t - C_{t-1}|, |L_t - C_{t-1}|)
      R by dominant leg: H_t - C_{t-1} strictly largest ->
          R = (H_t - C_{t-1}) - 0.5 (L_t - C_{t-1}) + 0.25 body_prev;
        L_t - C_{t-1} strictly largest ->
          R = (L_t - C_{t-1}) - 0.5 (H_t - C_{t-1}) + 0.25 body_prev;
        otherwise (including ties) -> R = (H_t - L_t) + 0.25 body_prev.
      SI = 50 * (delta_c + 0.5 body_t + 0.25 body_prev) / R, optionally * K/T
      when a commodity-style `limit_move` T is supplied. ASI accumulates SI.

    The doc's formula is a simplified variant and says implementations vary;
    this is the standard Wilder construction. NEPSE equities have no daily
    price limit constant, so `limit_move` defaults to None (K/T factor = 1).
    A bar whose inputs are missing or whose R == 0 contributes `None` and
    leaves the accumulator unchanged. The series starts at 0.0 the same way
    OBV starts at 0: a genuine cumulative base, not a filled value.
    """
    n = len(bars)
    out: list[Optional[float]] = [None] * n
    acc = 0.0
    for i in range(1, n):
        b, p = bars[i], bars[i - 1]
        if None in (b.open, b.high, b.low, b.close, p.open, p.high, p.low, p.close):
            continue
        o, h, l, c = (float(b.open), float(b.high), float(b.low), float(b.close))  # type: ignore[arg-type]
        po, ph, pl, pc = (float(p.open), float(p.high), float(p.low), float(p.close))  # type: ignore[arg-type]
        hc = h - pc
        lc = l - pc
        body_prev = pc - po
        if hc > lc and hc > abs(body_prev):
            r = hc - 0.5 * lc + 0.25 * body_prev
        elif lc > hc and lc > abs(body_prev):
            r = lc - 0.5 * hc + 0.25 * body_prev
        else:
            r = (h - l) + 0.25 * body_prev
        if r == 0:
            continue
        si = 50.0 * ((c - pc) + 0.5 * (c - o) + 0.25 * body_prev) / r
        if limit_move:
            si *= max(abs(hc), abs(lc)) / limit_move
        acc += si
        out[i] = acc
    return out


def average_price(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Average Price: (O + H + L + C) / 4, the doc's four-price mean."""
    return ohlc4_series(bars)


def _cross_signal(
    fast: Sequence[Optional[float]], slow: Sequence[Optional[float]]
) -> list[Optional[float]]:
    """+1.0 on the bar `fast` crosses above `slow`, -1.0 below, else None.

    A cross needs both series defined on this bar and the previous one; equal
    values count as 'not crossed' until they strictly separate.
    """
    n = min(len(fast), len(slow))
    out: list[Optional[float]] = [None] * n
    for i in range(1, n):
        f0, s0, f1, s1 = fast[i - 1], slow[i - 1], fast[i], slow[i]
        if None in (f0, s0, f1, s1):
            continue
        if f0 <= s0 and f1 > s1:  # type: ignore[operator]
            out[i] = 1.0
        elif f0 >= s0 and f1 < s1:  # type: ignore[operator]
            out[i] = -1.0
    return out


def ema_cross(
    closes: Sequence[Optional[float]], fast_period: int = 9, slow_period: int = 21
) -> dict[str, list[Optional[float]]]:
    """EMA crossover: EMA(fast) vs EMA(slow) plus per-bar cross markers.

    The doc: 'signal when Fast EMA crosses Slow EMA'. Markers are +1.0 on the
    bullish cross bar, -1.0 on the bearish one, `None` elsewhere.
    """
    fast = ema_on_valid(closes, fast_period)
    slow = ema_on_valid(closes, slow_period)
    return {"fast": fast, "slow": slow, "signal": _cross_signal(fast, slow)}


def ma_cross(
    closes: Sequence[Optional[float]], fast_period: int = 9, slow_period: int = 21
) -> dict[str, list[Optional[float]]]:
    """SMA crossover: MA(fast) vs MA(slow) plus per-bar cross markers."""
    fast = sma_on_valid(closes, fast_period)
    slow = sma_on_valid(closes, slow_period)
    return {"fast": fast, "slow": slow, "signal": _cross_signal(fast, slow)}


def ma_ema_cross(
    closes: Sequence[Optional[float]], fast_period: int = 9, slow_period: int = 21
) -> dict[str, list[Optional[float]]]:
    """MA with EMA cross: SMA(fast) against EMA(slow) plus cross markers."""
    fast = sma_on_valid(closes, fast_period)
    slow = ema_on_valid(closes, slow_period)
    return {"fast": fast, "slow": slow, "signal": _cross_signal(fast, slow)}


# ---------------------------------------------------------------------------
# Batch B doc #7-#12: adaptive MA, Hamming MA, MA multiple, MA channel,
# SMMA, LSMA
# ---------------------------------------------------------------------------


def ama(
    values: Sequence[Optional[float]],
    period: int = 9,
    fast: int = 2,
    slow: int = 30,
) -> list[Optional[float]]:
    """Kaufman's Adaptive Moving Average (the doc's 'Moving Average Adaptive').

    Efficiency ratio ER = |C_t - C_{t-N}| / sum(|C_i - C_{i-1}|) over the last
    N changes; smoothing constant sc = (ER * (2/(fast+1) - 2/(slow+1)) +
    2/(slow+1))^2, and AMA_t = AMA_{t-1} + sc * (C_t - AMA_{t-1}). Defaults
    9/2/30 are the common Kaufman setting. The series seeds with the close at
    the first bar that has N prior changes. A perfectly trending series has
    ER = 1 (fastest smoothing), a perfectly flat one ER -> 0 (slowest); when
    the denominator is 0 (no movement at all) ER is undefined and the value
    is `None` - a flat-but-unchanged close is not a computable ratio.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    fastest = 2.0 / (fast + 1)
    slowest = 2.0 / (slow + 1)
    out: list[Optional[float]] = [None] * len(values)
    ama_prev: Optional[float] = None
    for i in range(period, len(values)):
        c_now = values[i]
        c_then = values[i - period]
        window_changes = [
            float(values[j]) - float(values[j - 1])
            for j in range(i - period + 1, i + 1)
            if values[j] is not None and values[j - 1] is not None
        ]
        if c_now is None or c_then is None or len(window_changes) != period:
            ama_prev = None  # a gap restarts the recursion
            continue
        volatility = sum(abs(d) for d in window_changes)
        if volatility == 0:
            ama_prev = None
            continue
        er = abs(float(c_now) - float(c_then)) / volatility
        sc = (er * (fastest - slowest) + slowest) ** 2
        base = ama_prev if ama_prev is not None else float(c_now)
        out[i] = base + sc * (float(c_now) - base)
        ama_prev = out[i]
    return out


def ma_hamming(values: Sequence[Optional[float]], period: int = 20) -> list[Optional[float]]:
    """Moving Average Hamming: weighted mean with Hamming-window weights.

    w_i = 0.54 - 0.46 * cos(2 pi i / (period - 1)) for i = 0..period-1,
    applied oldest -> newest. The window is symmetric, so the result is
    phase-neutral like an SMA but with tapered ends. `None` during warm-up
    and for windows containing a gap.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    weights = [
        0.54 - 0.46 * math.cos(2.0 * math.pi * i / (period - 1))
        for i in range(period)
    ]
    wsum = sum(weights)
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(w * float(v) for w, v in zip(weights, window)) / wsum  # type: ignore[arg-type]
    return out


def ma_multiple(
    closes: Sequence[Optional[float]], periods: Sequence[int] = (20, 50, 100, 200)
) -> dict[str, list[Optional[float]]]:
    """MA Multiple: the same SMA at several lengths, one series per length.

    The doc: 'MA_i = MA(Close, N_i), for i = 1..k'. Keys are 'ma_multi_<N>'.
    """
    return {f"ma_multi_{p}": sma(closes, p) for p in periods}


def ma_channel(
    closes: Sequence[Optional[float]], period: int = 20, offset_pct: float = 10.0
) -> dict[str, list[Optional[float]]]:
    """MA Channel: middle = SMA(N), bands at MA +- offset.

    The doc writes the offset in absolute price units; a fixed absolute band
    is meaningless across symbols with different price scales, so the offset
    is expressed as a percent of the MA itself (default 10% - upper =
    MA * 1.10, lower = MA * 0.90). Keys: upper / middle / lower.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    middle = sma(closes, period)
    k = offset_pct / 100.0
    upper: list[Optional[float]] = [
        None if m is None else m * (1.0 + k) for m in middle
    ]
    lower: list[Optional[float]] = [
        None if m is None else m * (1.0 - k) for m in middle
    ]
    return {"upper": upper, "middle": middle, "lower": lower}


def smma(values: Sequence[Optional[float]], period: int = 20) -> list[Optional[float]]:
    """Smoothed Moving Average: SMMA_t = (SMMA_{t-1} * (N - 1) + Price_t) / N.

    Identical recursion to Wilder's RMA (seeded by an SMA of the first N),
    kept as a named entry because the doc lists it separately.
    """
    return rma(values, period)


def lsma(values: Sequence[Optional[float]], period: int = 25) -> list[Optional[float]]:
    """Least Squares Moving Average: the fitted regression value at the
    window's newest bar (identical construction to the linear-regression
    curve; kept as a named entry because the doc lists both)."""
    return linreg_endpoint(values, period)


# ---------------------------------------------------------------------------
# Batch B doc #13-#17: LinReg curve/slope/trend, McGinley Dynamic, GMMA
# ---------------------------------------------------------------------------


def linreg_curve(values: Sequence[Optional[float]], period: int = 100) -> list[Optional[float]]:
    """Linear Regression Curve (doc #13): fitted value at the window's end.

    Same construction as LSMA; the doc lists both, the curve with the longer
    default lookback.
    """
    return linreg_endpoint(values, period)


def linreg_trend(
    values: Sequence[Optional[float]], period: int = 100
) -> dict[str, list[Optional[float]]]:
    """Linear Regression Trend (doc #15): fitted line value plus direction.

    'value' is the fitted endpoint (a + b x (N-1)); 'direction' is +1.0 when
    the slope is positive, -1.0 when negative and 0.0 when exactly flat - a
    genuine zero for a perfectly level window, not a filled gap.
    """
    value = linreg_endpoint(values, period)
    slope = linreg_slope(values, period)
    direction: list[Optional[float]] = [
        None if s is None else (1.0 if s > 0 else (-1.0 if s < 0 else 0.0))
        for s in slope
    ]
    return {"value": value, "slope": slope, "direction": direction}


def mcginley(values: Sequence[Optional[float]], period: int = 14) -> list[Optional[float]]:
    """McGinley Dynamic: a price-following average that speeds up in
    downtrends and slows in uptrends.

    MD_t = MD_{t-1} + (P_t - MD_{t-1}) / (N * (P_t / MD_{t-1})^4), seeded with
    the first valid close. Runs of consecutive non-None values are tracked
    independently (a gap reseeds). A zero or negative denominator/price
    leaves the value None; a constant series keeps MD exactly at that price.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(values)
    md_prev: Optional[float] = None
    for i, v in enumerate(values):
        if v is None:
            md_prev = None  # a gap reseeds on the next valid bar
            continue
        p = float(v)
        if md_prev is None:
            md_prev = p
            out[i] = p
            continue
        ratio = p / md_prev
        if ratio <= 0 or md_prev <= 0:
            out[i] = None
            continue
        out[i] = md_prev + (p - md_prev) / (period * ratio**4)
        md_prev = out[i]
    return out


def gmma(
    closes: Sequence[Optional[float]],
    short: Sequence[int] = (3, 5, 8, 10, 12, 15),
    long: Sequence[int] = (30, 35, 40, 45, 50, 60),
) -> dict[str, list[Optional[float]]]:
    """Guppy Multiple Moving Average: two EMA ribbons.

    Short group EMA(3,5,8,10,12,15) tracks traders; long group
    EMA(30,35,40,45,50,60) tracks investors. Ribbon compression marks
    agreement (trend), expansion marks disagreement (transition). Keys are
    'gmma_s<N>' and 'gmma_l<N>'.
    """
    out: dict[str, list[Optional[float]]] = {}
    for p in short:
        out[f"gmma_s{p}"] = ema_on_valid(closes, p)
    for p in long:
        out[f"gmma_l{p}"] = ema_on_valid(closes, p)
    return out


# ---------------------------------------------------------------------------
# Batch B doc #18-#22: Majority Rule, Trend Strength Index, Zig Zag,
# Williams Alligator, Williams Fractal
# ---------------------------------------------------------------------------


def majority_rule(bars: Sequence[Bar]) -> dict[str, list[Optional[float]]]:
    """Majority Rule (doc #18): net bullish-minus-bearish vote of a fixed
    condition basket.

    The doc lets the trader pick the conditions; a picker of arbitrary
    indicators is not reproducible server-side, so this ships one documented
    basket of seven: close vs SMA20, SMA50, SMA100 and EMA21, SMA20 vs SMA50,
    close vs the previous close, and RSI(14) above/below 50. Each component
    votes +1 (bullish), -1 (bearish) or 0 (exact tie); 'score' is the sum and
    'components' the number that were computable that bar, so a vote taken on
    a short warm-up is visible as such instead of silently partial.
    """
    closes = [b.close for b in bars]
    sma20 = sma_on_valid(closes, 20)
    sma50 = sma_on_valid(closes, 50)
    sma100 = sma_on_valid(closes, 100)
    ema21 = ema_on_valid(closes, 21)
    rsi14 = rsi_on_valid(closes, 14)
    n = len(bars)
    score: list[Optional[float]] = [None] * n
    components: list[Optional[float]] = [None] * n
    for i in range(n):
        c = closes[i]
        if c is None:
            continue
        cf = float(c)
        votes: list[float] = []
        for ma in (sma20[i], sma50[i], sma100[i], ema21[i]):
            if ma is not None:
                votes.append(1.0 if cf > float(ma) else -1.0)
        if sma20[i] is not None and sma50[i] is not None:
            votes.append(1.0 if float(sma20[i]) > float(sma50[i]) else -1.0)  # type: ignore[arg-type]
        if i > 0 and closes[i - 1] is not None:
            prev = float(closes[i - 1])  # type: ignore[arg-type]
            votes.append(1.0 if cf > prev else (-1.0 if cf < prev else 0.0))
        if rsi14[i] is not None:
            r = float(rsi14[i])  # type: ignore[arg-type]
            votes.append(1.0 if r > 50.0 else (-1.0 if r < 50.0 else 0.0))
        if not votes:
            continue
        score[i] = float(sum(votes))
        components[i] = float(len(votes))
    return {"score": score, "components": components}


def trend_strength(
    closes: Sequence[Optional[float]], long_period: int = 25, short_period: int = 13
) -> list[Optional[float]]:
    """Trend Strength Index (doc #19): smoothed directional price change over
    smoothed absolute price change, x100.

    This is exactly the True Strength Index construction the doc calls
    'TSI-style'; it is registered under its own name because the doc lists it
    separately, but the numbers match the existing TSI entry by design.
    """
    return tsi(closes, long_period, short_period)


def zigzag(
    bars: Sequence[Bar], deviation_pct: float = 5.0
) -> dict[str, list[Optional[float]]]:
    """Zig Zag (doc #20): the price path reduced to swings that reverse by at
    least `deviation_pct`.

    A swing is recorded only when a later move against the running extreme
    crosses the threshold, so every emitted pivot is confirmed by definition;
    the still-developing leg's extreme is withheld until it confirms - which
    is the 'confirmed' contract for this indicator ('price' marks confirmed
    pivot bars, 'confirmed' is True exactly there and False elsewhere).
    Runs on closes; gaps in closes are skipped without resetting the leg.
    """
    if deviation_pct <= 0:
        raise ValueError("deviation_pct must be positive")
    n = len(bars)
    price: list[Optional[float]] = [None] * n
    confirmed = [False] * n
    up = 1.0 + deviation_pct / 100.0
    down = 1.0 - deviation_pct / 100.0
    direction = 0  # 0 undetermined, +1 rising leg, -1 falling leg
    hi_idx = hi_p = lo_idx = lo_p = None  # type: ignore[assignment]
    extreme_idx = extreme_p = None  # type: ignore[assignment]
    for i, b in enumerate(bars):
        c = b.close
        if c is None:
            continue
        cf = float(c)
        if direction == 0:
            # First confirmation is a reversal of dev% from a running
            # extreme; the check must precede the update so a bar that
            # extends an extreme is not compared against itself.
            if hi_p is not None and cf <= hi_p * down:
                price[hi_idx] = hi_p  # type: ignore[index]
                confirmed[hi_idx] = True  # type: ignore[index]
                direction = -1
                extreme_idx, extreme_p = i, cf
            elif lo_p is not None and cf >= lo_p * up:
                price[lo_idx] = lo_p  # type: ignore[index]
                confirmed[lo_idx] = True  # type: ignore[index]
                direction = 1
                extreme_idx, extreme_p = i, cf
            else:
                if hi_p is None or cf > hi_p:
                    hi_idx, hi_p = i, cf
                if lo_p is None or cf < lo_p:
                    lo_idx, lo_p = i, cf
        elif direction == 1:
            if cf > extreme_p:  # type: ignore[operator]
                extreme_idx, extreme_p = i, cf
            elif cf <= extreme_p * down:  # type: ignore[operator]
                price[extreme_idx] = extreme_p  # type: ignore[index]
                confirmed[extreme_idx] = True
                direction = -1
                extreme_idx, extreme_p = i, cf
        else:
            if cf < extreme_p:  # type: ignore[operator]
                extreme_idx, extreme_p = i, cf
            elif cf >= extreme_p * up:  # type: ignore[operator]
                price[extreme_idx] = extreme_p  # type: ignore[index]
                confirmed[extreme_idx] = True
                direction = 1
                extreme_idx, extreme_p = i, cf
    return {"price": price, "confirmed": confirmed}


def alligator(
    bars: Sequence[Bar],
    jaw: tuple[int, int] = (13, 8),
    teeth: tuple[int, int] = (8, 5),
    lips: tuple[int, int] = (5, 3),
) -> dict[str, list[Optional[float]]]:
    """Williams Alligator (doc #21): three SMMA lines on the median price,
    each displaced forward by its balance-period offset.

    Jaw = SMMA(HL2, 13) shifted 8, Teeth = SMMA(HL2, 8) shifted 5, Lips =
    SMMA(HL2, 5) shifted 3. The classic plot draws the displaced part in the
    future; this series keeps input alignment, so each line's first `shift`
    slots are None and the final `shift` values (the projection) are outside
    the request window - honest about what a same-length series can show.
    """
    src = hl2_series(bars)

    def shifted(period: int, offset: int) -> list[Optional[float]]:
        smoothed = rma(src, period)
        out: list[Optional[float]] = [None] * len(smoothed)
        for i in range(offset, len(smoothed)):
            out[i] = smoothed[i - offset]
        return out

    return {
        "jaw": shifted(jaw[0], jaw[1]),
        "teeth": shifted(teeth[0], teeth[1]),
        "lips": shifted(lips[0], lips[1]),
    }


def fractals(bars: Sequence[Bar], wings: int = 2) -> dict[str, list[Optional[float]]]:
    """Williams Fractal (doc #22): swing highs/lows strictly above/below the
    `wings` neighbouring bars on each side.

    A five-bar pattern (wings = 2) needs two bars on both sides, so a fractal
    is only knowable two bars after its centre - this implementation exposes
    a fractal only once those bars exist, and 'confirmed' is True exactly at
    emitted fractal bars (False elsewhere). A bar can be both a bullish and a
    bearish fractal (an outside bar). Strict inequality: equal neighbours
    disqualify, matching the doc's '>'.
    """
    if wings <= 0:
        raise ValueError("wings must be positive")
    n = len(bars)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    high: list[Optional[float]] = [None] * n
    low: list[Optional[float]] = [None] * n
    confirmed = [False] * n
    for t in range(wings, n - wings):
        hs = highs[t - wings : t + wings + 1]
        ls = lows[t - wings : t + wings + 1]
        h = highs[t]
        if h is not None and all(v is not None for v in hs):
            if all(h > float(v) for i2, v in enumerate(hs) if i2 != wings):
                high[t] = float(h)
                confirmed[t] = True
        l = lows[t]
        if l is not None and all(v is not None for v in ls):
            if all(l < float(v) for i2, v in enumerate(ls) if i2 != wings):
                low[t] = float(l)
                confirmed[t] = True
    return {"high": high, "low": low, "confirmed": confirmed}


# ---------------------------------------------------------------------------
# Batch B doc #23-#28: Accelerator Oscillator, CMO, Connors RSI, Coppock,
# Fisher Transform, KST
# ---------------------------------------------------------------------------


def accelerator_oscillator(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Accelerator Oscillator (doc #23): AC = AO - SMA(AO, 5).

    AO = SMA(median, 5) - SMA(median, 34) (the existing Awesome Oscillator);
    AC is AO's own 5-bar SMA subtracted from it - momentum's acceleration.
    A flat market has AO = 0 and AC = 0.0, a genuine zero. None until both
    smoothings have warmed (34-bar median window plus 5 on AO).
    """
    ao = awesome_oscillator(bars)
    return [
        None if (v is None or m is None) else v - m
        for v, m in zip(ao, sma(ao, 5))
    ]


def cmo(closes: Sequence[Optional[float]], period: int = 14) -> list[Optional[float]]:
    """Chande Momentum Oscillator (doc #24):
    100 * (sum gains - sum losses) / (sum gains + sum losses).

    Unlike RSI's smoothed ratios, CMO uses raw sums over the window, so it
    swings the full -100..+100 range. A window with no movement at all makes
    the denominator 0 - CMO is undefined there, None not 0.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    changes: list[Optional[float]] = [None] * len(closes)
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None:
            continue
        changes[i] = float(cur) - float(prev)
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period, len(closes)):
        window = changes[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        gains = sum(v for v in window if v > 0)  # type: ignore[type-var]
        losses = sum(-v for v in window if v < 0)  # type: ignore[type-var]
        if gains + losses == 0:
            continue
        out[i] = 100.0 * (gains - losses) / (gains + losses)
    return out


def _close_streaks(closes: Sequence[Optional[float]]) -> list[Optional[float]]:
    """Consecutive up/down close streak: +k after k rising closes, -k after k
    falling ones, 0.0 on an unchanged close; None until the first change."""
    out: list[Optional[float]] = [None] * len(closes)
    streak = 0.0
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None:
            streak = 0.0
            continue
        d = float(cur) - float(prev)
        if d > 0:
            streak = streak + 1.0 if streak > 0 else 1.0
        elif d < 0:
            streak = streak - 1.0 if streak < 0 else -1.0
        else:
            streak = 0.0
        out[i] = streak
    return out


def connors_rsi(
    closes: Sequence[Optional[float]],
    rsi_period: int = 3,
    streak_period: int = 2,
    roc_period: int = 100,
) -> list[Optional[float]]:
    """Connors RSI (doc #25): the mean of three legs.

    CRSI = (RSI(Close, 3) + RSI(streak, 2) + PercentRank(ROC(1), 100)) / 3.
    The streak leg is RSI of the consecutive up/down count, so one-day
    extremes dominate by design - this is a short-term mean-reversion gauge.
    None until all three legs are computable (the percent-rank leg needs
    `roc_period` valid one-day returns).
    """
    if rsi_period <= 0 or streak_period <= 0 or roc_period <= 1:
        raise ValueError("periods must be positive (roc_period > 1)")
    leg_rsi = rsi(closes, rsi_period)
    streaks = _close_streaks(closes)
    leg_streak = rsi(streaks, streak_period)
    rets = roc(closes, 1)
    leg_rank = percentrank(rets, roc_period)
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        a, b, c = leg_rsi[i], leg_streak[i], leg_rank[i]
        if None in (a, b, c):
            continue
        out[i] = (float(a) + float(b) + float(c)) / 3.0  # type: ignore[arg-type]
    return out


def coppock(
    closes: Sequence[Optional[float]],
    roc1_period: int = 14,
    roc2_period: int = 11,
    wma_period: int = 10,
) -> list[Optional[float]]:
    """Coppock Curve (doc #26): WMA(ROC(14) + ROC(11), 10).

    A long-horizon momentum oscillator; its classic buy signal is the first
    upturn after a dip below zero. A flat series has both ROCs 0 and the
    curve exactly 0.0. None until the WMA window fills.
    """
    if roc1_period <= 0 or roc2_period <= 0 or wma_period <= 0:
        raise ValueError("periods must be positive")
    r1 = roc(closes, roc1_period)
    r2 = roc(closes, roc2_period)
    combined: list[Optional[float]] = [
        None if (a is None or b is None) else a + b for a, b in zip(r1, r2)
    ]
    return wma(combined, wma_period)


def fisher(closes: Sequence[Optional[float]], period: int = 9) -> list[Optional[float]]:
    """Fisher Transform (doc #27): maps the close's position in its N-bar
    range through 0.5 * ln((1 + x) / (1 - x)) with x = 2 * position - 1,
    then halves-smooths toward the previous value.

    When the close sits exactly on the window's high or low, x = +-1 and the
    logarithm diverges - that bar is None (a boundary close is a genuine
    edge case, not a computable value). The smoothing reseeds after such a
    gap or after a window gap. Windows where high == low are undefined.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Optional[float]] = [None] * len(closes)
    prev_f: Optional[float] = None
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        if any(v is None for v in window):
            prev_f = None
            continue
        wf = [float(v) for v in window]  # type: ignore[arg-type]
        hi, lo, cur = max(wf), min(wf), wf[-1]
        if hi == lo:
            prev_f = None
            continue
        position = (cur - lo) / (hi - lo)
        if position <= 0.0 or position >= 1.0:
            out[i] = None
            prev_f = None
            continue
        x = 2.0 * position - 1.0
        raw = 0.5 * math.log((1.0 + x) / (1.0 - x))
        value = raw if prev_f is None else 0.5 * raw + 0.5 * prev_f
        out[i] = value
        prev_f = value
    return out


def kst(
    closes: Sequence[Optional[float]],
    roc_periods: Sequence[int] = (10, 15, 20, 30),
    sma_periods: Sequence[int] = (10, 10, 10, 15),
    weights: Sequence[float] = (1.0, 2.0, 3.0, 4.0),
) -> list[Optional[float]]:
    """Know Sure Thing (doc #28): the weighted sum of four smoothed ROCs.

    KST = sum_i w_i * SMA(ROC(Close, r_i), s_i) with the classic defaults
    r = (10, 15, 20, 30), s = (10, 10, 10, 15), w = (1, 2, 3, 4). None while
    the longest leg is still warming up.
    """
    if not (len(roc_periods) == len(sma_periods) == len(weights)):
        raise ValueError("need the same number of ROC, SMA and weight entries")
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    legs: list[list[Optional[float]]] = [
        sma_on_valid(roc(closes, r), s) for r, s in zip(roc_periods, sma_periods)
    ]
    for i in range(n):
        total = 0.0
        for leg, w in zip(legs, weights):
            v = leg[i]
            if v is None:
                total = 0.0
                break
            total += float(w) * v
        else:
            out[i] = total
    return out


# ---------------------------------------------------------------------------
# Batch B doc #29-#33: DPO, SMI Ergodic, RCI, Price Oscillator,
# Relative Volatility Index
# ---------------------------------------------------------------------------


def dpo(closes: Sequence[Optional[float]], period: int = 21) -> list[Optional[float]]:
    """Detrended Price Oscillator (doc #29): price shifted back N/2 + 1 bars
    minus the SMA(N).

    out[i] = close[i - (N // 2 + 1)] - SMA(N)[i]. The deliberate misalignment
    removes the dominant cycle so shorter swings stand out; values are None
    until both the shifted close and the SMA exist.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    shift = period // 2 + 1
    ma = sma(closes, period)
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(shift, len(closes)):
        p = closes[i - shift]
        if p is None or ma[i] is None:
            continue
        out[i] = float(p) - float(ma[i])  # type: ignore[arg-type]
    return out


def smi_ergodic(
    closes: Sequence[Optional[float]], long_period: int = 5, short_period: int = 5
) -> dict[str, list[Optional[float]]]:
    """SMI Ergodic (doc #30): double-smoothed price change over double-smoothed
    absolute price change, plus its EMA signal line.

    value = 100 * EMA(EMA(dC, r), s) / EMA(EMA(|dC|, r), s); signal =
    EMA(value, 5) - the doc names both an indicator and an oscillator form,
    which in practice is value and value-minus-signal; both series ship.
    This is TSI construction at (5, 5); the name is kept because the doc
    lists it separately.
    """
    value = tsi(closes, long_period, short_period)
    signal = ema_on_valid(value, 5)
    return {"value": value, "signal": signal}


def rci(closes: Sequence[Optional[float]], period: int = 14) -> list[Optional[float]]:
    """Rank Correlation Index (doc #31): Spearman's rank correlation between
    time and price over each window, scaled to -100..+100.

    RCI = (1 - 6 * sum(d^2) / (N * (N^2 - 1))) * 100, d = time rank (newest =
    1) minus price rank (highest = 1). Perfect new-high windows score +100,
    perfect new-low windows -100. Ties in price share averaged ranks.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    denom = period * (period * period - 1)
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        wf = [float(v) for v in window]  # type: ignore[arg-type]
        order = sorted(range(period), key=lambda j: wf[j], reverse=True)
        price_rank = [0] * period
        # Average ranks for equal prices: assign each tied member the mean
        # of the positions it spans.
        j = 0
        while j < period:
            k = j
            while k + 1 < period and wf[order[k + 1]] == wf[order[j]]:
                k += 1
            avg_rank = (j + k) / 2.0 + 1.0
            for m in range(j, k + 1):
                price_rank[order[m]] = avg_rank
            j = k + 1
        d2 = sum(
            (float(t + 1) - price_rank[period - 1 - t]) ** 2
            for t in range(period)
        )
        out[i] = (1.0 - 6.0 * d2 / denom) * 100.0
    return out


def price_oscillator(
    closes: Sequence[Optional[float]], fast_period: int = 10, slow_period: int = 30
) -> dict[str, list[Optional[float]]]:
    """Price Oscillator (doc #32): fast MA minus slow MA, both forms.

    'abs' is MA(fast) - MA(slow) in price units; 'pct' is that difference
    divided by the slow MA, x100. Keys: 'abs', 'pct'.
    """
    if fast_period <= 0 or slow_period <= 0 or fast_period >= slow_period:
        raise ValueError("require 0 < fast < slow")
    fast = sma_on_valid(closes, fast_period)
    slow = sma_on_valid(closes, slow_period)
    abs_out: list[Optional[float]] = [None] * len(closes)
    pct_out: list[Optional[float]] = [None] * len(closes)
    for i, (f, s) in enumerate(zip(fast, slow)):
        if f is None or s is None:
            continue
        sf = float(s)  # type: ignore[arg-type]
        diff = float(f) - sf  # type: ignore[arg-type]
        abs_out[i] = diff
        if sf != 0:
            pct_out[i] = diff / sf * 100.0
    return {"abs": abs_out, "pct": pct_out}


def relative_volatility_index(
    closes: Sequence[Optional[float]], period: int = 14
) -> list[Optional[float]]:
    """Relative Volatility Index (doc #33, Chande): the RSI idea applied to
    standard deviation.

    Per bar, sd = StdDev(close, N); 'upward volatility' collects sd on days
    the close rose, 'downward' on days it fell, and
    RVI = 100 * EMA(up, N) / (EMA(up, N) + EMA(down, N)).
    A window with no dispersion makes the denominator 0 - None, not 0.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(closes)
    sd = stdev_series(closes, period)
    up: list[Optional[float]] = [None] * n
    down: list[Optional[float]] = [None] * n
    for i in range(1, n):
        if sd[i] is None or closes[i] is None or closes[i - 1] is None:
            continue
        rose = float(closes[i]) > float(closes[i - 1])  # type: ignore[arg-type]
        fell = float(closes[i]) < float(closes[i - 1])  # type: ignore[arg-type]
        up[i] = float(sd[i]) if rose else 0.0  # type: ignore[arg-type]
        down[i] = float(sd[i]) if fell else 0.0  # type: ignore[arg-type]
    ema_up = ema_on_valid(up, period)
    ema_down = ema_on_valid(down, period)
    out: list[Optional[float]] = [None] * n
    for i in range(n):
        u, d = ema_up[i], ema_down[i]
        if u is None or d is None or (u + d) == 0:
            continue
        out[i] = 100.0 * u / (u + d)
    return out


# ---------------------------------------------------------------------------
# Batch B doc #34-#38: Chande Kroll Stop, Choppiness, Chop Zone, Envelopes,
# Mass Index
# ---------------------------------------------------------------------------


def chande_kroll_stop(
    bars: Sequence[Bar],
    atr_period: int = 10,
    atr_mult: float = 1.0,
    stop_period: int = 9,
) -> dict[str, list[Optional[float]]]:
    """Chande Kroll Stop (doc #34): ATR-based trailing stop levels.

    Preliminary long stop = HighestHigh(N) - ATR(N) * mult; preliminary short
    stop = LowestLow(N) + ATR(N) * mult. The final stops smooth those over
    `stop_period` bars: long = rolling max of the preliminary long stop (the
    most permissive), short = rolling min of the preliminary short stop.
    Keys: 'long_stop', 'short_stop'.
    """
    if atr_period <= 0 or stop_period <= 0:
        raise ValueError("periods must be positive")
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    atr_series = atr(bars, atr_period)
    pre_long: list[Optional[float]] = [
        None if (h is None or a is None) else float(h) - float(a) * atr_mult
        for h, a in zip(highest(highs, atr_period), atr_series)
    ]
    pre_short: list[Optional[float]] = [
        None if (l is None or a is None) else float(l) + float(a) * atr_mult
        for l, a in zip(lowest(lows, atr_period), atr_series)
    ]
    return {"long_stop": highest(pre_long, stop_period), "short_stop": lowest(pre_short, stop_period)}


def choppiness(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Choppiness Index (doc #35):
    100 * log10(sum(TR, N) / (HighestHigh(N) - LowestLow(N))) / log10(N).

    Reads 0-100: above ~61.8 the market is range-bound, below ~38.3 it is
    trending. A window with zero range (locked prices) divides 0 by 0 - the
    ratio is undefined there, None not 100.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    # True-range series, matching atr()'s convention: the first bar (or a bar
    # after a missing close) degrades to H - L.
    trs: list[Optional[float]] = []
    prev_close: Optional[float] = None
    for b in bars:
        if b.high is None or b.low is None:
            trs.append(None)
            prev_close = b.close
            continue
        trs.append(true_range(float(b.high), float(b.low), prev_close))
        prev_close = b.close
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    hh = highest(highs, period)
    ll = lowest(lows, period)
    n_log = math.log10(period)
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(period - 1, len(bars)):
        window = trs[i - period + 1 : i + 1]
        if any(v is None for v in window) or hh[i] is None or ll[i] is None:
            continue
        range_ = float(hh[i]) - float(ll[i])  # type: ignore[arg-type]
        if range_ == 0:
            continue
        out[i] = 100.0 * math.log10(sum(float(v) for v in window) / range_) / n_log
    return out


def chop_zone(bars: Sequence[Bar], period: int = 21, atr_period: int = 14) -> list[Optional[float]]:
    """Chop Zone (doc #36): a -4..+4 trend/chop classification.

    The doc's formula is implementation-specific; this version scores the
    open and the close against EMA(typical price, `period`) in ATR units:
    beyond +0.5 ATR above the line votes +2, above it +1, symmetrically -2/-1
    below, an exact touch votes 0. +4 = both prices clearly above (trending
    up), -4 clearly below (trending down), near 0 = chop. The exact scoring
    bands are this implementation's choice and are stated here for honesty.
    """
    if period <= 0 or atr_period <= 0:
        raise ValueError("periods must be positive")
    typical = hlc3_series(bars)
    line = ema_on_valid(typical, period)
    atr_series = atr(bars, atr_period)

    def vote(p: Optional[float], ema_v: Optional[float], a: Optional[float]) -> Optional[int]:
        if p is None or ema_v is None or a is None:
            return None
        d = float(p) - float(ema_v)
        half = 0.5 * float(a)
        if d > half:
            return 2
        if d > 0:
            return 1
        if d < -half:
            return -2
        if d < 0:
            return -1
        return 0

    out: list[Optional[float]] = [None] * len(bars)
    for i, b in enumerate(bars):
        v_open = vote(b.open, line[i], atr_series[i])
        v_close = vote(b.close, line[i], atr_series[i])
        if v_open is None or v_close is None:
            continue
        out[i] = float(v_open + v_close)
    return out


def envelopes(
    closes: Sequence[Optional[float]], period: int = 20, percent: float = 2.0
) -> dict[str, list[Optional[float]]]:
    """Envelopes (doc #37): SMA(N) plus/minus a fixed percent.

    Upper = MA * (1 + p/100), Lower = MA * (1 - p/100); default 2% on 20
    bars, the common envelope setting. Keys: 'upper', 'middle', 'lower'.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    middle = sma(closes, period)
    k = percent / 100.0
    upper: list[Optional[float]] = [None if m is None else m * (1.0 + k) for m in middle]
    lower: list[Optional[float]] = [None if m is None else m * (1.0 - k) for m in middle]
    return {"upper": upper, "middle": middle, "lower": lower}


def mass_index(
    bars: Sequence[Bar], ema_period: int = 9, sum_period: int = 25
) -> list[Optional[float]]:
    """Mass Index (doc #38): sum over `sum_period` of
    EMA(H-L, ema) / EMA(EMA(H-L, ema), ema).

    Range expansion pushes the ratio above 1 (double-EMA lags the expansion)
    and contraction pulls it below; the classic reversal warning is a 'reversal
    bulge' - the sum rising past 27 and falling back below 26.5. A flat range
    makes the ratio exactly 1.0 and the sum exactly `sum_period`.
    """
    if ema_period <= 0 or sum_period <= 0:
        raise ValueError("periods must be positive")
    ranges: list[Optional[float]] = [
        None if (b.high is None or b.low is None) else float(b.high) - float(b.low)
        for b in bars
    ]
    e1 = ema(ranges, ema_period)
    e2 = ema(e1, ema_period)
    ratio: list[Optional[float]] = [
        None if (a is None or b_ is None or b_ == 0) else a / b_ for a, b_ in zip(e1, e2)
    ]
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(sum_period - 1, len(bars)):
        window = ratio[i - sum_period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(float(v) for v in window)  # type: ignore[arg-type]
    return out


# ---------------------------------------------------------------------------
# Batch B doc #39-#44: Standard Error, Standard Error Bands, volatility
# close-to-close / zero-trend / OHLC, Volatility Index (disabled)
# ---------------------------------------------------------------------------


def standard_error(
    closes: Sequence[Optional[float]], period: int = 20
) -> list[Optional[float]]:
    """Standard Error (doc #39): root mean square distance from the fitted
    regression line, per the doc's formula sqrt(sum(residual^2) / (N - 2)).

    In price units. A perfectly linear window has SE exactly 0.0. Periods
    below 3 have no residual degrees of freedom and raise; windows with gaps
    are None.
    """
    if period <= 2:
        raise ValueError("period must be at least 3 (N - 2 denominator)")
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        wf = [float(v) for v in window]  # type: ignore[arg-type]
        a, b = _linreg_coeffs(wf)
        sse = sum((y - (a + b * x)) ** 2 for x, y in enumerate(wf))
        out[i] = math.sqrt(sse / (period - 2))
    return out


def standard_error_bands(
    closes: Sequence[Optional[float]], period: int = 20, mult: float = 2.0
) -> dict[str, list[Optional[float]]]:
    """Standard Error Bands (doc #40): regression endpoint plus/minus
    `mult` x standard error over the same window.

    Middle = the fitted line's value at the newest bar (the LSMA
    construction); upper/lower = middle +- k * SE. Keys: 'upper', 'middle',
    'lower'.
    """
    middle = linreg_endpoint(closes, period)
    se = standard_error(closes, period)
    upper: list[Optional[float]] = [
        None if (m is None or s is None) else m + mult * s for m, s in zip(middle, se)
    ]
    lower: list[Optional[float]] = [
        None if (m is None or s is None) else m - mult * s for m, s in zip(middle, se)
    ]
    return {"upper": upper, "middle": middle, "lower": lower}


def _annualized(per_bar_sd: float, annualization: float) -> float:
    """Scale a per-bar standard deviation to an annual percent.

    sd * sqrt(annualization) * 100 - the annualization multiplies the
    standard deviation by sqrt(252), it does not square it first.
    """
    return math.sqrt(annualization) * per_bar_sd * 100.0


def volatility_c2c(
    closes: Sequence[Optional[float]],
    period: int = 20,
    annualization: float = 252.0,
) -> list[Optional[float]]:
    """Volatility Close-to-Close (doc #41): annualized standard deviation of
    log returns.

    sigma = StdDev(ln(C_t / C_{t-1}), N) * sqrt(annualization), reported in
    percent (252 trading days is the default year). A run of identical
    returns has zero dispersion - a genuine 0.0, not a gap.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    log_rets: list[Optional[float]] = [None] * len(closes)
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None or prev <= 0 or cur <= 0:
            continue
        log_rets[i] = math.log(float(cur) / float(prev))  # type: ignore[arg-type]
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period, len(closes)):
        window = log_rets[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = _annualized(stdev([float(v) for v in window]), annualization)  # type: ignore[arg-type]
    return out


def volatility_zero_trend_c2c(
    closes: Sequence[Optional[float]],
    period: int = 20,
    annualization: float = 252.0,
) -> list[Optional[float]]:
    """Volatility Zero Trend Close-to-Close (doc #42): close-to-close
    volatility after stripping the linear trend from log prices.

    Residuals of ln(C) against its best-fit line over the window, then
    StdDev(residuals) * sqrt(annualization) in percent - a steady grind in
    one direction reports near-zero volatility instead of a large one.
    """
    if period <= 2:
        raise ValueError("period must be at least 3")
    log_closes: list[Optional[float]] = [
        None if (c is None or c <= 0) else math.log(float(c)) for c in closes
    ]
    out: list[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = log_closes[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        wf = [float(v) for v in window]  # type: ignore[arg-type]
        a, b = _linreg_coeffs(wf)
        residuals = [y - (a + b * x) for x, y in enumerate(wf)]
        out[i] = _annualized(stdev(residuals), annualization)
    return out


def volatility_ohlc(
    bars: Sequence[Bar], period: int = 20, annualization: float = 252.0
) -> list[Optional[float]]:
    """Volatility O-H-L-C (doc #43) via the Garman-Klass estimator.

    The doc leaves the OHLC method open; this implementation uses
    Garman-Klass: per bar, 0.5 * ln(H/L)^2 - (2 ln 2 - 1) * ln(C/O)^2,
    averaged over the window and annualized: sqrt(mean * 252) in percent.
    Uses only open/high/low/close, so it is more efficient than close-to-close
    on the same data. A bar with a missing OHLC field or a non-positive price
    is skipped; a completely flat window is a genuine 0.0.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    terms: list[Optional[float]] = []
    for b in bars:
        if None in (b.open, b.high, b.low, b.close):
            terms.append(None)
            continue
        o, h, l, c = (float(b.open), float(b.high), float(b.low), float(b.close))  # type: ignore[arg-type]
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            terms.append(None)
            continue
        terms.append(0.5 * math.log(h / l) ** 2 - (2.0 * math.log(2.0) - 1.0) * math.log(c / o) ** 2)
    out: list[Optional[float]] = [None] * len(bars)
    for i in range(period - 1, len(bars)):
        window = terms[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        # Garman-Klass terms are variance-style: sqrt(mean * ann) directly.
        out[i] = math.sqrt(sum(window) / period * annualization) * 100.0  # type: ignore[type-var,arg-type]
    return out


# ---------------------------------------------------------------------------
# Batch B doc #45-#48: 52 Week High/Low, Advance/Decline, Balance of Power,
# Correlation Coefficient
# ---------------------------------------------------------------------------


def high_low_52w(bars: Sequence[Bar], lookback: int = 252) -> dict[str, Optional[float]]:
    """52 Week High/Low (doc #45): the highest high and lowest low over the
    trailing `lookback` sessions (252 = one trading year).

    Levels, not a rolling series - the chart draws them as flat lines. None
    when the window holds no usable high/low at all.
    """
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    tail = list(bars)[-lookback:]
    highs = [float(b.high) for b in tail if b.high is not None]
    lows = [float(b.low) for b in tail if b.low is not None]
    return {
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
    }


def advance_decline(
    closes_by_symbol: dict[str, list[Optional[float]]]
) -> dict[str, list[Optional[float]]]:
    """Advance/Decline (doc #46): market breadth across symbols.

    `closes_by_symbol` maps symbol -> close series aligned to the same
    session index (the caller owns the alignment). Per session: advancers =
    symbols whose close rose vs the prior session, decliners = fell,
    unchanged = equal; a symbol without a close on either session is skipped
    and the counts say how many were comparable. The A/D line cumulates
    (advancers - decliners) from 0.0, the same base convention as OBV. A
    session with no comparable symbol reports None throughout.
    """
    n = max((len(v) for v in closes_by_symbol.values()), default=0)
    advancers: list[Optional[float]] = [None] * n
    decliners: list[Optional[float]] = [None] * n
    unchanged: list[Optional[float]] = [None] * n
    ad_line: list[Optional[float]] = [None] * n
    acc = 0.0
    for i in range(n):
        a = d = u = 0
        for series in closes_by_symbol.values():
            if i >= len(series):
                continue
            cur = series[i]
            prev = series[i - 1] if i > 0 else None
            if cur is None or prev is None:
                continue
            if cur > prev:
                a += 1
            elif cur < prev:
                d += 1
            else:
                u += 1
        if a + d + u == 0:
            continue
        advancers[i] = float(a)
        decliners[i] = float(d)
        unchanged[i] = float(u)
        acc += float(a - d)
        ad_line[i] = acc
    return {"advancers": advancers, "decliners": decliners, "unchanged": unchanged, "ad_line": ad_line}


def balance_of_power(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Balance of Power (doc #47): (Close - Open) / (High - Low), smoothed by
    an SMA over `period` bars.

    A locked bar (H == L) has no defined power and is None; the smoothing
    needs `period` computable bars. Zero is a genuine reading (close at the
    open), not a gap.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    raw: list[Optional[float]] = [None] * len(bars)
    for i, b in enumerate(bars):
        if b.open is None or b.close is None or not b.has_range:
            continue
        raw[i] = (float(b.close) - float(b.open)) / (float(b.high) - float(b.low))  # type: ignore[arg-type]
    return sma(raw, period)


def correlation(
    closes_a: Sequence[Optional[float]],
    closes_b: Sequence[Optional[float]],
    period: int = 20,
) -> list[Optional[float]]:
    """Correlation Coefficient (doc #48): rolling Pearson r between two
    aligned close series.

    r = sum((x - x̄)(y - ȳ)) / sqrt(sum((x - x̄)^2) * sum((y - ȳ)^2)) over each
    window. A window where either series is flat has zero variance - r is
    undefined there, None not 0. The caller must align the series by date.
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    n = min(len(closes_a), len(closes_b))
    out: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        wa = closes_a[i - period + 1 : i + 1]
        wb = closes_b[i - period + 1 : i + 1]
        if any(v is None for v in wa) or any(v is None for v in wb):
            continue
        xa = [float(v) for v in wa]  # type: ignore[arg-type]
        xb = [float(v) for v in wb]  # type: ignore[arg-type]
        ma = sum(xa) / period
        mb = sum(xb) / period
        sxx = sum((x - ma) ** 2 for x in xa)
        syy = sum((y - mb) ** 2 for y in xb)
        if sxx == 0 or syy == 0:
            continue
        sxy = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
        out[i] = sxy / math.sqrt(sxx * syy)
    return out


# ---------------------------------------------------------------------------
# Batch B doc #49-#52: Correlation-Log, Ratio, Spread, Compare
# ---------------------------------------------------------------------------


def correlation_log(
    closes_a: Sequence[Optional[float]],
    closes_b: Sequence[Optional[float]],
    period: int = 20,
) -> list[Optional[float]]:
    """Correlation on log returns (doc #49): Pearson r of ln(C_t/C_{t-1}).

    Log returns are computed after the two series are aligned by date
    (inner join). Fewer than `period` common sessions -> pending/None.
    Zero variance -> not_applicable (None).
    """
    if period <= 1:
        raise ValueError("period must be at least 2")
    # Compute log returns first
    rets_a: list[Optional[float]] = [None] * len(closes_a)
    rets_b: list[Optional[float]] = [None] * len(closes_b)
    for i in range(1, len(closes_a)):
        if closes_a[i] is not None and closes_a[i - 1] is not None and closes_a[i - 1] > 0:
            rets_a[i] = math.log(closes_a[i] / closes_a[i - 1])
    for i in range(1, len(closes_b)):
        if closes_b[i] is not None and closes_b[i - 1] is not None and closes_b[i - 1] > 0:
            rets_b[i] = math.log(closes_b[i] / closes_b[i - 1])
    # Now compute rolling correlation on the return series
    # The correlation function needs at least `period` valid values
    return correlation(rets_a, rets_b, period)


def ratio(
    closes_a: Sequence[Optional[float]],
    closes_b: Sequence[Optional[float]],
) -> list[Optional[float]]:
    """Ratio (doc #50): C_A / C_B on aligned sessions.

    Both series must be aligned by the caller (same index = same session).
    C_B = 0 -> not_applicable (None).
    Returns None for any index where either value is missing or C_B == 0.
    """
    n = min(len(closes_a), len(closes_b))
    out: list[Optional[float]] = [None] * n
    for i in range(n):
        a = closes_a[i]
        b = closes_b[i]
        if a is None or b is None or b == 0:
            continue
        out[i] = float(a) / float(b)
    return out


def spread(
    closes_a: Sequence[Optional[float]],
    closes_b: Sequence[Optional[float]],
) -> list[Optional[float]]:
    """Spread (doc #51): C_A - C_B on aligned sessions."""
    n = min(len(closes_a), len(closes_b))
    out: list[Optional[float]] = [None] * n
    for i in range(n):
        a = closes_a[i]
        b = closes_b[i]
        if a is None or b is None:
            continue
        out[i] = float(a) - float(b)
    return out


def compare(
    closes_a: Sequence[Optional[float]],
    closes_b: Sequence[Optional[float]],
    mode: str = "rebase",
) -> list[Optional[float]]:
    """Compare (doc #52): rebases series B to series A's first common value.

    mode="rebase": 100 * C_B / C_B0 where B0 is B's value at first common index.
    mode="percent": (C_B / C_B0 - 1) * 100.
    Returns None where either series is missing.
    """
    n = min(len(closes_a), len(closes_b))
    out: list[Optional[float]] = [None] * n
    # Find first index where both have values
    base_idx = -1
    for i in range(n):
        if closes_a[i] is not None and closes_b[i] is not None:
            base_idx = i
            break
    if base_idx == -1:
        return out
    base_b = closes_b[base_idx]
    if base_b is None or base_b == 0:
        return out
    if mode == "rebase":
        for i in range(base_idx, n):
            if closes_a[i] is None or closes_b[i] is None:
                continue
            out[i] = 100.0 * float(closes_b[i]) / float(base_b)
    elif mode == "percent":
        for i in range(base_idx, n):
            if closes_a[i] is None or closes_b[i] is None:
                continue
            out[i] = (float(closes_b[i]) / float(base_b) - 1.0) * 100.0
    else:
        raise ValueError("mode must be 'rebase' or 'percent'")
    return out


# ---------------------------------------------------------------------------
# Batch B doc #53-#56: Median Price, Typical Price, Price Channel,
# Elder's Force Index
# ---------------------------------------------------------------------------


def median_price(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Median Price (doc #53): (H + L) / 2.

    Simple midpoint of the day's range. None if H or L is missing.
    """
    out: list[Optional[float]] = [None] * len(bars)
    for i, b in enumerate(bars):
        if b.high is not None and b.low is not None:
            out[i] = (float(b.high) + float(b.low)) / 2.0
    return out


def typical_price(bars: Sequence[Bar]) -> list[Optional[float]]:
    """Typical Price (doc #54): (H + L + C) / 3.

    The standard typical price used by many indicators. None if any of
    H, L, C is missing.
    """
    out: list[Optional[float]] = [None] * len(bars)
    for i, b in enumerate(bars):
        if b.high is not None and b.low is not None and b.close is not None:
            out[i] = (float(b.high) + float(b.low) + float(b.close)) / 3.0
    return out


def price_channel(
    bars: Sequence[Bar], period: int = 20, include_current: bool = True
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """Price Channel (doc #55): returns `(upper, lower, middle)`.

    Upper = HIGHEST(H, N); Lower = LOWEST(L, N); Middle = (Upper + Lower) / 2.
    Window includes the current bar by default (param `include_current`).
    Returns None during warm-up and for windows with missing H/L.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(bars)
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n
    middle: list[Optional[float]] = [None] * n
    for i in range(n):
        end = i + 1 if include_current else i
        start = end - period
        if start < 0:
            continue
        window = bars[start:end]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if any(h is None for h in highs) or any(l is None for l in lows):
            continue
        hi = max(float(h) for h in highs if h is not None)
        lo = min(float(l) for l in lows if l is not None)
        upper[i] = hi
        lower[i] = lo
        middle[i] = (hi + lo) / 2.0
    return upper, lower, middle


def force_index(bars: Sequence[Bar], period: int = 13) -> list[Optional[float]]:
    """Elder's Force Index (doc #56): EMA-smoothed (C_t - C_{t-1}) * V_t.

    Direction times magnitude times participation. The raw 1-period force is
    None whenever the close, the previous close or the volume is missing; the
    EMA smoothing resumes after the gap, per the shared ema rules.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    raw: list[Optional[float]] = [None] * len(bars)
    for i in range(1, len(bars)):
        cur, prev = bars[i], bars[i - 1]
        if cur.close is None or prev.close is None or cur.volume is None:
            continue
        raw[i] = (float(cur.close) - float(prev.close)) * float(cur.volume)
    return ema(raw, period)
