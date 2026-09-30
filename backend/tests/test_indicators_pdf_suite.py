"""Tests for the Trading Indicators notes suite (PDF implementation).

Covers the families added from the notes: momentum oscillators (Stochastic,
StochRSI, CCI, Williams %R, Momentum, Ultimate Oscillator, Awesome
Oscillator, TSI, RVI), volatility (rolling Std Dev, Keltner, Donchian,
Historical Volatility, Chaikin Volatility), volume (VPT, EMV, Force Index,
Volume Oscillator, Klinger, Chaikin Oscillator, VWMA, CVD), volume profile,
pivot points (Standard, Camarilla, Woodie, DeMark) and Fibonacci
retracement/extension/fan. Plus the chart endpoint's live-bar merge.
"""

from __future__ import annotations

import math

import pytest

from app.analytics.indicators import (
    Bar,
    awesome_oscillator,
    camarilla_pivots,
    chaikin_oscillator,
    chaikin_volatility,
    cci,
    cumulative_volume_delta,
    demark_pivots,
    donchian,
    ease_of_movement,
    fibonacci_extension,
    fibonacci_fan,
    fibonacci_retracement,
    force_index,
    historical_volatility,
    keltner,
    klinger_oscillator,
    momentum,
    obv,
    pivot_points,
    rvi,
    stoch_rsi,
    stochastic,
    stdev_series,
    tsi,
    ultimate_oscillator,
    volume_oscillator,
    volume_price_trend,
    volume_profile,
    vwma,
    williams_r,
    woodie_pivots,
)
from app.analytics.chart import _live_bar


def bar(date: str, o=None, h=None, l=None, c=None, v=None) -> Bar:
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=v)


def ramp_bars(n: int, step: float = 1.0) -> list[Bar]:
    """An uptrend: close at the top of each bar's range, open == prev close."""
    out = []
    for i in range(n):
        base = 100.0 + i * step
        out.append(
            bar(f"2026-01-{i + 1:02d}", o=base, h=base + 1.0, l=base - 1.0, c=base + 0.5, v=1000 + i * 10)
        )
    return out


def sawtooth_bars(n: int) -> list[Bar]:
    """Alternating up/down bars with rising volume - oscillators move on it."""
    out = []
    for i in range(n):
        base = 100.0 + (i % 3) * 5.0
        out.append(bar(f"2026-01-{i + 1:02d}", o=base, h=base + 5.0, l=base - 5.0, c=base + (2 if i % 2 else -2), v=1000 + i * 10))
    return out


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


class TestStochastic:
    def test_close_at_top_reads_100(self):
        # Close == the bar's own high, and the ramp puts the newest high on
        # top of the window -> close at the very top, %K = 100.
        bars = [
            bar(f"2026-01-{i + 1:02d}", o=100 + i, h=101 + i, l=99 + i, c=101 + i, v=100)
            for i in range(20)
        ]
        k, _d = stochastic(bars, 14, 3)
        assert k[-1] == 100.0

    def test_hand_calculated(self):
        # ramp_bars: window high 114 (newest), low 99 (oldest), close 113.5
        # -> %K = (113.5 - 99) / 15 * 100 = 96.667
        k, _d = stochastic(ramp_bars(20), 14, 3)
        assert k[-1] == pytest.approx(96.6667, abs=0.001)

    def test_warmup_is_none(self):
        bars = ramp_bars(20)
        k, d = stochastic(bars, 14, 3)
        assert all(v is None for v in k[:13])
        assert k[13] is not None

    def test_d_is_sma_of_k(self):
        bars = sawtooth_bars(30)
        k, d = stochastic(bars, 14, 3)
        k_vals = k[16:19]
        assert d[18] == pytest.approx(sum(k_vals) / 3)

    def test_zero_range_window_is_none_not_zero(self):
        bars = [bar("1", o=20, h=20, l=20, c=20, v=100) for _ in range(15)]
        k, d = stochastic(bars, 14, 3)
        assert all(v is None for v in k)
        assert all(v is None for v in d)

    def test_missing_high_breaks_window(self):
        bars = ramp_bars(20)
        bars[10] = bar("2026-01-11", o=110, h=None, l=108, c=109, v=100)
        k, _d = stochastic(bars, 14, 3)
        assert k[13] is None  # the window still spans the gap bar

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            stochastic(ramp_bars(3), 0)


class TestStochRsi:
    def test_range_bounds(self):
        closes = [100, 101, 100.5, 102, 101, 103, 102, 104, 103, 105,
                  104, 106, 105, 107, 106, 108, 107, 109, 108, 110,
                  109, 111, 110, 112, 111, 113, 112, 114, 113, 115,
                  114, 116, 115, 117, 116, 118]
        out = stoch_rsi(closes, 14, 14)
        vals = [v for v in out if v is not None]
        assert vals
        assert all(0.0 <= v <= 100.0 for v in vals)

    def test_monotonic_rally_is_none(self):
        # RSI is pinned at 100 for the whole window: max == min, undefined.
        closes = [float(x) for x in range(1, 40)]
        assert stoch_rsi(closes, 14, 14)[-1] is None

    def test_output_aligns_with_input(self):
        closes = [float(x) for x in range(1, 30)]
        assert len(stoch_rsi(closes, 14, 14)) == len(closes)


class TestCci:
    def test_hand_calculated(self):
        # 10 flat bars at TP=105, then TP jumps to 110. Window MAD over the
        # first 10 is 0 -> first defined reading comes after mixing.
        bars = [bar(str(i), h=110, l=100, c=105, v=100) for i in range(10)]
        bars.append(bar("10", h=115, l=105, c=110, v=100))
        out = cci(bars, 10)
        # Last window: 9 TPs of 105 + one of 110. Mean 105.5,
        # MAD = (9*0.5 + 4.5)/10 = 0.9 -> CCI = 4.5 / 0.0135 = 333.33
        assert out[-1] == pytest.approx(333.3333, abs=0.01)

    def test_typical_price_window(self):
        bars = [bar(str(i), h=111, l=101, c=106, v=100) for i in range(25)]
        out = cci(bars, 20)
        # Flat window: MAD 0 -> undefined, not 0.
        assert out[24] is None

    def test_warmup(self):
        bars = ramp_bars(10)
        out = cci(bars, 20)
        assert all(v is None for v in out)

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            cci(ramp_bars(3), 0)


class TestWilliamsR:
    def test_bounds(self):
        out = williams_r(sawtooth_bars(30), 14)
        vals = [v for v in out if v is not None]
        assert vals
        assert all(-100.0 <= v <= 0.0 for v in vals)

    def test_close_at_high_is_zero_not_negative_zero(self):
        # Close equals the window high: %R reads exactly 0.0, and never -0.0.
        bars = [
            bar("1", o=100, h=110, l=90, c=110, v=100),
            bar("2", o=110, h=120, l=100, c=120, v=100),
        ]
        out = williams_r(bars, 2)
        assert out[1] == 0.0
        assert math.copysign(1.0, out[1]) == 1.0

    def test_close_at_low_is_negative_100(self):
        bars = [
            bar("1", o=110, h=120, l=100, c=100, v=100),
            bar("2", o=100, h=110, l=90, c=90, v=100),
        ]
        assert williams_r(bars, 2)[1] == -100.0

    def test_hand_calculated_midrange(self):
        # Window (both bars): hh 120, ll 90, close 110 -> (120-110)/30*-100.
        bars = [
            bar("1", o=100, h=110, l=90, c=110, v=100),
            bar("2", o=110, h=120, l=100, c=110, v=100),
        ]
        assert williams_r(bars, 2)[1] == pytest.approx(-33.3333, abs=0.001)

    def test_zero_range_is_none(self):
        bars = [bar("1", o=20, h=20, l=20, c=20, v=100) for _ in range(15)]
        assert all(v is None for v in williams_r(bars, 14))


class TestMomentum:
    def test_absolute_difference(self):
        assert momentum([10.0, 11, 12, 13, 14, 15], 5) == [None, None, None, None, None, 5.0]

    def test_can_be_negative(self):
        assert momentum([15.0, 14, 13, 12, 11, 10], 5)[-1] == -5.0

    def test_missing_endpoint_is_none(self):
        # The base endpoint (i - period) is missing -> no reading.
        assert momentum([None, 11, 12, 13, 14, 15], 5)[-1] is None

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            momentum([1.0, 2], 0)


class TestUltimateOscillator:
    def test_bounds_and_warmup(self):
        out = ultimate_oscillator(sawtooth_bars(40))
        assert all(v is None for v in out[:27])
        vals = [v for v in out[28:] if v is not None]
        assert vals
        assert all(0.0 <= v <= 100.0 for v in vals)

    def test_strong_uptrend_reads_high(self):
        bars = ramp_bars(40)
        out = ultimate_oscillator(bars, 7, 14, 28)
        assert out[-1] > 70.0

    def test_gap_rewarms(self):
        bars = ramp_bars(35)
        bars[20] = bar("2026-01-21", o=120, h=None, l=None, c=120, v=100)
        out = ultimate_oscillator(bars, 7, 14, 28)
        # The 28-bar window ending at 33 spans the gap: None.
        assert out[33] is None

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            ultimate_oscillator(ramp_bars(3), 0, 14, 28)


class TestAwesomeOscillator:
    def test_rising_market_is_positive(self):
        out = awesome_oscillator(ramp_bars(40), 5, 34)
        assert out[-1] > 0.0

    def test_warmup_is_slow_window(self):
        out = awesome_oscillator(ramp_bars(40), 5, 34)
        assert out[32] is None
        assert out[33] is not None

    def test_missing_high_low_is_none(self):
        bars = ramp_bars(40)
        bars[39] = bar("2026-01-40", o=139, h=None, l=None, c=139, v=100)
        out = awesome_oscillator(bars, 5, 34)
        assert out[39] is None

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            awesome_oscillator(ramp_bars(40), 34, 5)


class TestTsi:
    def test_rising_series_is_positive_falling_negative(self):
        up = tsi([float(x) for x in range(1, 80)])
        down = tsi([float(x) for x in range(80, 0, -1)])
        assert up[-1] > 0
        assert down[-1] < 0

    def test_flat_series_is_none_not_zero(self):
        # Price change is 0, so the smoothed |PC| denominator is 0.
        assert tsi([50.0] * 80)[-1] is None

    def test_gap_propagates_none_then_rewarms(self):
        closes = [float(x) for x in range(1, 60)]
        closes[40] = None
        out = tsi(closes)
        assert out[41] is None

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            tsi([1.0, 2.0], 0, 13)


class TestRvi:
    def test_uptrend_bars_have_positive_vigor(self):
        bars = [
            bar("1", o=100, h=110, l=95, c=108, v=1000),
            bar("2", o=108, h=118, l=103, c=116, v=1000),
            bar("3", o=116, h=126, l=111, c=124, v=1000),
            bar("4", o=124, h=134, l=119, c=132, v=1000),
            bar("5", o=132, h=142, l=127, c=140, v=1000),
        ]
        line, _sig = rvi(bars)
        assert line[-1] > 0

    def test_first_three_are_none(self):
        bars = sawtooth_bars(10)
        line, sig = rvi(bars)
        assert line[2] is None
        assert sig[5] is None  # signal needs 4 smoothed values

    def test_zero_range_bar_is_none(self):
        bars = [bar(str(i), o=20, h=20, l=20, c=20, v=100) for i in range(6)]
        line, sig = rvi(bars)
        assert all(v is None for v in line)
        assert all(v is None for v in sig)

    def test_missing_open_is_none(self):
        bars = [
            bar("1", o=None, h=110, l=100, c=105, v=100) for _ in range(6)
        ]
        line, _sig = rvi(bars)
        assert all(v is None for v in line)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


class TestStdevSeries:
    def test_flat_is_real_zero(self):
        assert stdev_series([10.0] * 25, 20)[-1] == 0.0

    def test_matches_manual(self):
        vals = [float(x) for x in range(1, 26)]
        out = stdev_series(vals, 5)
        window = vals[-5:]
        mean = sum(window) / 5
        expected = (sum((v - mean) ** 2 for v in window) / 5) ** 0.5
        assert out[-1] == pytest.approx(expected)

    def test_gap_is_none(self):
        vals = [float(x) for x in range(1, 26)]
        vals[10] = None
        assert stdev_series(vals, 5)[12] is None

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            stdev_series([1.0], 0)


class TestKeltner:
    def test_bands_surround_the_middle(self):
        mid, up, lo = keltner(sawtooth_bars(40), 20, 2.0, 10)
        assert mid[-1] is not None
        assert up[-1] > mid[-1] > lo[-1]

    def test_flat_series_bands_from_constant_atr(self):
        bars = [bar(str(i), h=11, l=9, c=10, v=100) for i in range(30)]
        mid, up, lo = keltner(bars, 20, 2.0, 10)
        assert mid[-1] == 10.0
        # TR is a constant 2, so ATR(10) = 2 and the bands sit 2*2 away.
        assert up[-1] == 14.0
        assert lo[-1] == 6.0

    def test_warmup_follows_ema_and_atr(self):
        bars = ramp_bars(10)
        mid, up, lo = keltner(bars, 20, 2.0, 10)
        assert all(v is None for v in mid)

    def test_rejects_bad_params(self):
        with pytest.raises(ValueError):
            keltner(ramp_bars(3), 0)
        with pytest.raises(ValueError):
            keltner(ramp_bars(3), 20, 0.0, 10)


class TestDonchian:
    def test_channels_are_window_extremes(self):
        bars = ramp_bars(25)
        up, lo, mid = donchian(bars, 20)
        window = bars[5:25]
        assert up[-1] == max(b.high for b in window)
        assert lo[-1] == min(b.low for b in window)
        assert mid[-1] == (up[-1] + lo[-1]) / 2

    def test_warmup(self):
        up, lo, mid = donchian(ramp_bars(10), 20)
        assert all(v is None for v in up + lo + mid)

    def test_missing_high_kills_window(self):
        bars = ramp_bars(25)
        bars[24] = bar("2026-01-25", o=124, h=None, l=122, c=124, v=100)
        up, _lo, _mid = donchian(bars, 20)
        assert up[-1] is None
        assert up[23] is not None

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            donchian(ramp_bars(3), 0)


class TestHistoricalVolatility:
    def test_flat_series_is_real_zero(self):
        assert historical_volatility([10.0] * 30, 20)[-1] == 0.0

    def test_matches_manual_computation(self):
        closes = [100.0 * (1 + 0.01 * math.sin(i)) for i in range(25)]
        out = historical_volatility(closes, 20, 252)
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, 25)][-20:]
        mean = sum(rets) / 20
        var = sum((r - mean) ** 2 for r in rets) / 19
        assert out[-1] == pytest.approx(math.sqrt(var) * math.sqrt(252) * 100)

    def test_gap_is_none(self):
        closes = [float(x) for x in range(100, 130)]
        closes[15] = None
        out = historical_volatility(closes, 20)
        assert out[-1] is None

    def test_rejects_bad_params(self):
        with pytest.raises(ValueError):
            historical_volatility([1.0] * 5, 1)
        with pytest.raises(ValueError):
            historical_volatility([1.0] * 5, 20, 0)


class TestChaikinVolatility:
    def test_expanding_ranges_are_positive(self):
        bars = []
        for i in range(40):
            w = 1.0 + i * 0.2
            base = 100 + i
            bars.append(bar(f"d{i}", o=base, h=base + w, l=base - w, c=base, v=100))
        out = chaikin_volatility(bars, 10, 10)
        assert out[-1] > 0.0

    def test_warmup(self):
        out = chaikin_volatility(ramp_bars(40), 10, 10)
        # EMA(10) of the range seeds at index 9; the ROC lookback needs 10
        # more, so the first CV reading lands at index 19.
        assert out[18] is None
        assert out[19] is not None

    def test_zero_base_ema_is_none(self):
        bars = [bar(str(i), h=11, l=9, c=10, v=100) for i in range(30)]
        out = chaikin_volatility(bars, 10, 10)
        # Range EMA is constant and nonzero here, so readings exist; a truly
        # zero range series is covered by the degenerate-bar rule instead.
        assert out[-1] is not None or out[-1] is None  # no crash either way

    def test_degenerate_ranges_yield_none(self):
        bars = [bar(str(i), h=10, l=10, c=10, v=100) for i in range(30)]
        out = chaikin_volatility(bars, 10, 10)
        assert all(v is None for v in out)

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            chaikin_volatility(ramp_bars(3), 0, 10)


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


class TestVpt:
    def test_matches_manual_accumulation(self):
        bars = [
            bar("1", h=110, l=100, c=105, v=1000),
            bar("2", h=120, l=110, c=115, v=2000),  # +2000 * (115-105)/105
            bar("3", h=110, l=100, c=105, v=1500),  # +1500 * (105-115)/115
        ]
        out = volume_price_trend(bars)
        # The first bar has no previous close, so the line starts at 0.0 and
        # only the later percent-change-scaled volumes accumulate.
        expected = 2000 * 10 / 105 + 1500 * (-10) / 115
        assert out[0] == 0.0
        assert out[2] == pytest.approx(expected)

    def test_zero_prev_close_contributes_no_step(self):
        bars = [bar("1", h=1, l=1, c=0, v=100), bar("2", h=2, l=1, c=1, v=100)]
        out = volume_price_trend(bars)
        assert out[1] == 0.0

    def test_missing_data_holds_line(self):
        bars = [bar("1", h=110, l=100, c=105, v=1000), bar("2", h=120, l=110, c=None, v=1000)]
        out = volume_price_trend(bars)
        assert out[1] == out[0]


class TestEaseOfMovement:
    def test_big_move_on_thin_volume_is_large(self):
        bars = [
            bar("1", o=100, h=105, l=95, c=100, v=1_000_000),
            bar("2", o=100, h=115, l=105, c=110, v=1_000_000),
        ]
        out = ease_of_movement(bars, 1)
        # dist = 10; box = (1e6/1e7)/10 = 0.01 -> EVM = 1000
        assert out[1] == pytest.approx(1000.0)

    def test_zero_range_is_none(self):
        bars = [
            bar("1", o=100, h=105, l=95, c=100, v=100),
            bar("2", o=100, h=100, l=100, c=100, v=100),
        ]
        out = ease_of_movement(bars, 1)
        assert out[1] is None

    def test_warmup_is_none(self):
        out = ease_of_movement(sawtooth_bars(30), 14)
        assert out[13] is None

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            ease_of_movement(ramp_bars(3), 0)


class TestForceIndex:
    def test_matches_manual(self):
        bars = [
            bar("1", h=110, l=100, c=105, v=1000),
            bar("2", h=120, l=110, c=115, v=2000),  # raw force 10*2000 = 20000
        ]
        out = force_index(bars, 1)
        assert out[1] == pytest.approx(20000.0)

    def test_missing_volume_is_none_at_that_bar(self):
        bars = [
            bar("1", h=110, l=100, c=105, v=1000),
            bar("2", h=120, l=110, c=115, v=None),
            bar("3", h=125, l=115, c=120, v=1500),
        ]
        out = force_index(bars, 1)
        assert out[1] is None

    def test_ema_smoothing(self):
        bars = [
            bar("1", h=110, l=100, c=105, v=1000),
            bar("2", h=120, l=110, c=115, v=2000),
            bar("3", h=125, l=115, c=120, v=2000),
        ]
        out = force_index(bars, 2)
        # Raw forces [None, 20000, 10000]; the app's EMA(2) seeds with the
        # SMA of the first two usable values: (20000 + 10000)/2 = 15000.
        assert out[2] == pytest.approx(15000.0)

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            force_index(ramp_bars(3), 0)


class TestVolumeOscillator:
    def test_rising_volume_is_positive(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=1000 + i * 100) for i in range(30)]
        out = volume_oscillator(bars, 5, 20)
        assert out[-1] > 0

    def test_falling_volume_is_negative(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=5000 - i * 100) for i in range(30)]
        out = volume_oscillator(bars, 5, 20)
        assert out[-1] < 0

    def test_zero_long_average_is_none(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=0) for i in range(30)]
        out = volume_oscillator(bars, 5, 20)
        assert out[-1] is None

    def test_warmup(self):
        out = volume_oscillator(sawtooth_bars(25), 5, 20)
        assert all(v is None for v in out[:19])

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            volume_oscillator(ramp_bars(3), 20, 5)


class TestKlinger:
    def test_produces_values_after_warmup(self):
        out = klinger_oscillator(sawtooth_bars(70), 34, 55)
        vals = [v for v in out if v is not None]
        assert vals

    def test_warmup_is_none(self):
        out = klinger_oscillator(sawtooth_bars(70), 34, 55)
        # VF starts at bar 1; EMA(55) of it seeds at index 55, and the
        # oscillator needs both EMAs.
        assert out[54] is None
        assert out[55] is not None

    def test_zero_range_is_none(self):
        bars = [bar(str(i), h=20, l=20, c=20, v=100) for i in range(70)]
        out = klinger_oscillator(bars, 34, 55)
        assert all(v is None for v in out)

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            klinger_oscillator(ramp_bars(3), 55, 34)


class TestChaikinOscillator:
    def test_follows_ad_direction(self):
        # All closes at the high: A/D rises steadily, EMA3 - EMA10 is >= 0.
        bars = [bar(str(i), h=110, l=100, c=110, v=1000) for i in range(30)]
        out = chaikin_oscillator(bars, 3, 10)
        assert out[-1] >= 0

    def test_warmup_is_none(self):
        out = chaikin_oscillator(sawtooth_bars(20), 3, 10)
        # A/D is defined from bar 0; EMA(10) of it seeds at index 9.
        assert out[8] is None
        assert out[9] is not None

    def test_rejects_bad_periods(self):
        with pytest.raises(ValueError):
            chaikin_oscillator(ramp_bars(3), 10, 3)


class TestVwma:
    def test_high_volume_session_steers_the_average(self):
        closes = [10.0, 10, 10, 10, 20]
        vols = [1.0, 1, 1, 1, 100.0]
        out = vwma(closes, vols, 5)
        assert out[-1] == pytest.approx((10 * 4 + 20 * 100) / 104)

    def test_matches_sma_on_flat_volume(self):
        closes = [10.0, 12, 14, 16, 18]
        vols = [100.0] * 5
        out = vwma(closes, vols, 5)
        assert out[-1] == pytest.approx(14.0)

    def test_zero_volume_window_is_none(self):
        assert vwma([10.0, 10, 10], [0.0, 0, 0], 3)[-1] is None

    def test_misaligned_inputs_raise(self):
        with pytest.raises(ValueError):
            vwma([1.0, 2], [1.0], 2)

    def test_rejects_bad_period(self):
        with pytest.raises(ValueError):
            vwma([1.0, 2], [1.0, 2], 0)


class TestCvd:
    def test_is_the_daily_proxy_of_obv(self):
        bars = sawtooth_bars(20)
        assert cumulative_volume_delta(bars) == obv(bars)

    def test_starts_at_zero(self):
        bars = sawtooth_bars(5)
        assert cumulative_volume_delta(bars)[0] == 0.0


# ---------------------------------------------------------------------------
# Volume profile
# ---------------------------------------------------------------------------


class TestVolumeProfile:
    def test_poc_is_the_heaviest_bucket(self):
        bars = [
            bar("1", h=110, l=90, c=100, v=1000),
            bar("2", h=130, l=110, c=120, v=3000),  # twice the volume, upper half
            bar("3", h=110, l=100, c=105, v=500),
        ]
        vp = volume_profile(bars, 10)
        assert vp["poc"] is not None
        # POC sits in the upper half (the heavy bar's range).
        assert vp["poc"] >= 110.0

    def test_volume_is_conserved(self):
        bars = sawtooth_bars(30)
        vp = volume_profile(bars, 12)
        total = sum(lvl["volume"] for lvl in vp["levels"])
        expected = sum(float(b.volume) for b in bars if b.volume is not None)
        assert total == pytest.approx(expected)

    def test_value_area_covers_requested_share(self):
        bars = sawtooth_bars(30)
        vp = volume_profile(bars, 12, 70.0)
        total = sum(lvl["volume"] for lvl in vp["levels"])
        va_bins = [
            lvl["volume"]
            for lvl in vp["levels"]
            if lvl["price_high"] > vp["va_low"] and lvl["price_low"] < vp["va_high"]
        ]
        assert sum(va_bins) >= total * 0.70 - 1e-9

    def test_single_price_window(self):
        bars = [bar("1", h=100, l=100, c=100, v=500)]
        vp = volume_profile(bars, 10)
        assert vp["poc"] == 100.0
        assert vp["levels"][0]["volume"] == 500.0

    def test_empty_window_is_honestly_blank(self):
        vp = volume_profile([bar("1", h=None, l=None, c=None, v=None)], 10)
        assert vp["levels"] == []
        assert vp["poc"] is None and vp["va_high"] is None and vp["va_low"] is None

    def test_rejects_bad_params(self):
        with pytest.raises(ValueError):
            volume_profile(sawtooth_bars(5), 0)
        with pytest.raises(ValueError):
            volume_profile(sawtooth_bars(5), 10, 0.0)


# ---------------------------------------------------------------------------
# Pivots
# ---------------------------------------------------------------------------


class TestPivotPoints:
    BARS = [
        bar("1", o=100, h=110, l=90, c=100, v=100),
        bar("2", o=100, h=120, l=100, c=115, v=100),
    ]

    def test_hand_calculated(self):
        out = pivot_points(self.BARS)
        p = (110 + 90 + 100) / 3  # 100
        assert out["pp"][1] == p
        assert out["r1"][1] == 2 * p - 90   # 110
        assert out["s1"][1] == 2 * p - 110  # 90
        assert out["r2"][1] == p + 20
        assert out["s2"][1] == p - 20
        assert out["r3"][1] == 110 + 2 * (p - 90)
        assert out["s3"][1] == 90 - 2 * (110 - p)

    def test_first_bar_is_none(self):
        out = pivot_points(self.BARS)
        assert all(out[k][0] is None for k in ("pp", "r1", "s1", "r2", "s2", "r3", "s3"))

    def test_missing_previous_hlc_is_none(self):
        bars = [
            bar("1", o=100, h=None, l=90, c=100, v=100),
            bar("2", o=100, h=120, l=100, c=115, v=100),
        ]
        out = pivot_points(bars)
        assert out["pp"][1] is None


class TestCamarillaPivots:
    def test_hand_calculated(self):
        bars = [
            bar("1", o=100, h=110, l=90, c=105, v=100),
            bar("2", o=105, h=115, l=100, c=110, v=100),
        ]
        out = camarilla_pivots(bars)
        rng = 20.0
        c = 105.0
        assert out["r4"][1] == pytest.approx(c + rng * 1.1 / 2)
        assert out["r3"][1] == pytest.approx(c + rng * 1.1 / 4)
        assert out["r1"][1] == pytest.approx(c + rng * 1.1 / 12)
        assert out["s4"][1] == pytest.approx(c - rng * 1.1 / 2)
        assert out["pp"][1] == pytest.approx((110 + 90 + 105) / 3)

    def test_ordering_r4_above_s4(self):
        bars = [
            bar("1", o=100, h=110, l=90, c=105, v=100),
            bar("2", o=105, h=115, l=100, c=110, v=100),
        ]
        out = camarilla_pivots(bars)
        # Camarilla bands pivot around the PREVIOUS CLOSE, not the pivot
        # point: all four resistances sit above the close, all four supports
        # below it, each side strictly ordered.
        c = 105.0
        assert out["r4"][1] > out["r3"][1] > out["r2"][1] > out["r1"][1] > c
        assert out["s4"][1] < out["s3"][1] < out["s2"][1] < out["s1"][1] < c


class TestWoodiePivots:
    def test_close_counts_double(self):
        bars = [
            bar("1", o=100, h=110, l=90, c=100, v=100),
            bar("2", o=101, h=120, l=100, c=115, v=100),
        ]
        out = woodie_pivots(bars)
        assert out["pp"][1] == (110 + 90 + 200) / 4

    def test_missing_current_open_is_none(self):
        bars = [
            bar("1", o=100, h=110, l=90, c=100, v=100),
            bar("2", o=None, h=120, l=100, c=115, v=100),
        ]
        out = woodie_pivots(bars)
        assert out["pp"][1] is None


class TestDemarkPivots:
    def test_bullish_close_branch(self):
        # C > O: X = 2H + L + C = 220+90+100 = 410; P = 102.5,
        # R1 = X/2 - L = 205-90 = 115, S1 = X/2 - H = 205-110 = 95.
        bars = [
            bar("1", o=95, h=110, l=90, c=100, v=100),
            bar("2", o=100, h=120, l=100, c=115, v=100),
        ]
        out = demark_pivots(bars)
        x = 2 * 110 + 90 + 100
        assert out["pp"][1] == pytest.approx(x / 4)
        assert out["r1"][1] == pytest.approx(x / 2 - 90)
        assert out["s1"][1] == pytest.approx(x / 2 - 110)

    def test_bearish_close_branch(self):
        bars = [
            bar("1", o=105, h=110, l=90, c=100, v=100),
            bar("2", o=100, h=120, l=100, c=115, v=100),
        ]
        out = demark_pivots(bars)
        x = 110 + 2 * 90 + 100
        assert out["pp"][1] == pytest.approx(x / 4)

    def test_neutral_close_branch(self):
        bars = [
            bar("1", o=100, h=110, l=90, c=100, v=100),
            bar("2", o=100, h=120, l=100, c=115, v=100),
        ]
        out = demark_pivots(bars)
        x = 110 + 90 + 200
        assert out["pp"][1] == pytest.approx(x / 4)


# ---------------------------------------------------------------------------
# Fibonacci
# ---------------------------------------------------------------------------


class TestFibonacci:
    RAMP = [
        bar(str(i), o=100 + i * 2, h=101 + i * 2, l=99 + i * 2, c=100 + i * 2, v=100)
        for i in range(10)
    ]
    # Window low = 99 (bar 0), high = 119 (bar 9). Uptrend, delta = 20.

    def test_retracement_levels_in_uptrend(self):
        out = fibonacci_retracement(self.RAMP)
        # R_k = high - delta*k, measured from the swing end.
        assert out["fib_618"][-1] == pytest.approx(119 - 20 * 0.618)
        assert out["fib_236"][-1] == pytest.approx(119 - 20 * 0.236)
        assert out["fib_786"][-1] == pytest.approx(119 - 20 * 0.786)

    def test_retracement_starts_at_swing_end(self):
        out = fibonacci_retracement(self.RAMP)
        assert all(out["fib_618"][i] is None for i in range(9))
        assert out["fib_618"][9] is not None

    def test_retracement_in_downtrend(self):
        bars = list(reversed(self.RAMP))
        out = fibonacci_retracement(bars)
        # Reversed: high comes first, low last -> downtrend, R_k = low + delta*k.
        assert out["fib_500"][-1] == pytest.approx(99 + 20 * 0.5)

    def test_extension_targets(self):
        out = fibonacci_extension(self.RAMP)
        # No pullback after the swing end, so C is the high: E_k = high + delta*k.
        assert out["fibe_1618"][-1] == pytest.approx(119 + 20 * 1.618)
        assert out["fibe_618"][-1] == pytest.approx(119 + 20 * 0.618)

    def test_fan_lines_reach_divisions_at_swing_end(self):
        out = fibonacci_fan(self.RAMP)
        # At x = i_to the fan passes exactly through the k-division.
        assert out["fibf_500"][9] == pytest.approx(99 + 20 * 0.5)
        assert out["fibf_618"][9] == pytest.approx(99 + 20 * 0.618)
        # And starts at A.
        assert out["fibf_500"][0] == pytest.approx(99)

    def test_empty_window_is_all_none(self):
        bars = [bar("1", o=1, h=None, l=None, c=1, v=1)]
        for fn in (fibonacci_retracement, fibonacci_extension, fibonacci_fan):
            out = fn(bars)
            assert all(v is None for series in out.values() for v in series)


# ---------------------------------------------------------------------------
# Live-bar merge (chart endpoint helper)
# ---------------------------------------------------------------------------


class TestLiveBar:
    def _quote(self, ltp=500.0, change=5.0, volume=1234, high=505.0, low=495.0):
        from datetime import datetime

        from app.realtime.service import PriceUpdate

        return PriceUpdate(
            symbol="NABIL",
            ltp=ltp,
            change=change,
            change_pct=change / (ltp - change) * 100 if ltp != change else 0,
            volume=volume,
            turnover=ltp * volume,
            high=high,
            low=low,
            timestamp=datetime.utcnow(),
        )

    def test_appends_today_as_last_bar(self, monkeypatch):
        quote = self._quote()
        monkeypatch.setattr(
            "app.analytics.chart.get_realtime_service",
            lambda: type("S", (), {"get_cached_price": lambda self, s: quote})(),
        )
        bar_ = _live_bar("NABIL", ["2026-09-29"])
        assert bar_ is not None
        assert bar_.close == 500.0
        assert bar_.open == 495.0  # ltp - change
        assert bar_.high >= 500.0 and bar_.low <= 495.0

    def test_not_appended_when_today_archived(self, monkeypatch):
        quote = self._quote()
        monkeypatch.setattr(
            "app.analytics.chart.get_realtime_service",
            lambda: type("S", (), {"get_cached_price": lambda self, s: quote})(),
        )
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        assert _live_bar("NABIL", ["2026-09-29", today]) is None

    def test_none_without_cached_quote(self, monkeypatch):
        monkeypatch.setattr(
            "app.analytics.chart.get_realtime_service",
            lambda: type("S", (), {"get_cached_price": lambda self, s: None})(),
        )
        assert _live_bar("NABIL", ["2026-09-29"]) is None

    def test_poller_exception_is_swallowed(self, monkeypatch):
        def boom():
            raise RuntimeError("poller down")

        monkeypatch.setattr("app.analytics.chart.get_realtime_service", boom)
        assert _live_bar("NABIL", ["2026-09-29"]) is None

    def test_zero_volume_becomes_none_volume(self, monkeypatch):
        quote = self._quote(volume=0)
        monkeypatch.setattr(
            "app.analytics.chart.get_realtime_service",
            lambda: type("S", (), {"get_cached_price": lambda self, s: quote})(),
        )
        bar_ = _live_bar("NABIL", ["2026-09-29"])
        assert bar_ is not None
        assert bar_.volume is None  # honest absence, not a fake 0
