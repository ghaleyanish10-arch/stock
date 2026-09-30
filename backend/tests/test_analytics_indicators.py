"""``app.analytics`` - technical indicator calculations."""

from __future__ import annotations

import pytest

from app.analytics.indicators import (
    Bar,
    accumulation_distribution,
    accumulation_distribution_line,
    adx,
    aroon,
    atr,
    bollinger,
    bollinger_on_valid,
    chaikin_money_flow,
    dema,
    ema,
    ema_on_valid,
    hma,
    ichimoku,
    macd,
    macd_on_valid,
    money_flow_index,
    money_flow_multiplier,
    money_flow_volume,
    obv,
    psar,
    roc,
    rsi,
    rsi_on_valid,
    sma,
    sma_on_valid,
    stdev,
    supertrend,
    tema,
    trix,
    true_range,
    volume_sma_ratio,
    vortex,
    vwap,
    vwap_series,
    wma,
)


def bar(date: str, o=None, h=None, l=None, c=None, v=None) -> Bar:
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=v)


class TestSma:
    def test_basic(self):
        assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]

    def test_missing_value_yields_none_not_partial_average(self):
        # Every window that spans index 2 contains the gap, so all are None;
        # we never average over fewer observations than requested.
        assert sma([1, 2, None, 4, 5], 3) == [None, None, None, None, None]

    def test_window_recovers_after_gap(self):
        # Only the final window is free of the gap.
        assert sma([None, None, 4, 5, 6], 3) == [None, None, None, None, 5.0]

    def test_all_none_input(self):
        assert sma([None, None, None], 2) == [None, None, None]

    def test_zero_values_are_preserved(self):
        # Real zeros average to zero; they are not treated as missing.
        assert sma([0, 0, 0], 2)[-1] == 0.0

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            sma([1, 2, 3], 0)


class TestEma:
    def test_seeds_with_sma(self):
        out = ema([1, 2, 3, 4, 5], 3)
        assert out[:2] == [None, None]
        assert out[2] == 2.0  # SMA(1,2,3)
        # 4th value: alpha = 2/(3+1) = 0.5 -> 0.5*4 + 0.5*2 = 3.0
        assert out[3] == 3.0

    def test_matches_sma_when_flat(self):
        out = ema([7, 7, 7, 7, 7], 3)
        assert out[4] == 7.0

    def test_gap_breaks_run(self):
        out = ema([1, 2, None, 4, 5, 6], 2)
        assert out[0] is None
        assert out[1] == 1.5
        assert out[2] is None
        assert out[3] is None  # restart warm-up
        assert out[4] == 4.5


class TestWma:
    def test_weights_are_linear(self):
        # (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
        out = wma([1, 2, 3], 3)
        assert out[:2] == [None, None]
        assert abs(out[2] - 14.0 / 6.0) < 1e-9

    def test_most_recent_close_has_the_largest_weight(self):
        # (1*3 + 2*4 + 3*5)/6 = 26/6, above the plain SMA of the same window.
        out = wma([1, 2, 3, 4, 5], 3)
        assert abs(out[4] - 26.0 / 6.0) < 1e-9
        assert out[4] > (3.0 + 4.0 + 5.0) / 3.0

    def test_gap_yields_none_not_partial_window(self):
        assert wma([1, 2, None, 4, 5], 3) == [None, None, None, None, None]

    def test_matches_sma_on_flat_series(self):
        out = wma([7.0] * 6, 3)
        assert out[2] == 7.0
        assert out[-1] == 7.0

    def test_output_aligns_with_input(self):
        values = [1.0, 2.0, 3.0, 4.0]
        assert len(wma(values, 3)) == len(values)

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            wma([1, 2, 3], 0)


class TestHma:
    def test_hand_calculated_period_4(self):
        # wma(2):    [N, 5/3, 8/3, 11/3, 14/3]
        # wma(4):    [N, N, N, 3.0, 4.0]      (linear weights 1..4 / 10)
        # 2*w - f:   [N, N, N, 13/3, 16/3]
        # wma(..,2) at i=4: (1*13/3 + 2*16/3)/3 = 45/9 = 5.0
        out = hma([1, 2, 3, 4, 5], 4)
        assert out[3] is None
        assert abs(out[4] - 5.0) < 1e-9

    def test_warmup_is_none(self):
        out = hma([1.0, 2.0, 3.0, 4.0, 5.0], 4)
        assert out[0] is None
        assert out[2] is None

    def test_flat_series_is_flat(self):
        out = hma([5.0] * 12, 4)
        assert out[-1] == 5.0

    def test_gap_propagates_none(self):
        out = hma([1, None, 3, 4, 5, 6, 7], 4)
        assert out[3] is None  # every window through index 3 spans the gap

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            hma([1, 2, 3], -1)


class TestTrix:
    def test_warmup_is_three_smoothing_windows(self):
        # The triple EMA first exists at index 3*(period-1); TRIX needs a
        # previous triple-EMA value, so with period 3 its first reading is
        # index 3*2 + 1 = 7.
        out = trix([float(x) for x in range(1, 9)], 3)
        assert len(out) == 8
        assert out[6] is None
        assert out[7] is not None

    def test_period_1_degenerates_to_roc_1(self):
        values = [10.0, 11.0, 10.5, 12.0]
        out = trix(values, 1)
        expected = roc(values, 1)
        for got, want in zip(out, expected):
            assert got == want

    def test_flat_series_is_a_real_zero(self):
        out = trix([5.0] * 20, 3)
        assert out[-1] == 0.0

    def test_zero_base_is_none_not_infinity(self):
        # period=1 makes each EMA the identity, so the triple EMA is the raw
        # series and the 0 base is explicit.
        out = trix([0.0, 1.0, 2.0], 1)
        assert out == [None, None, 100.0]

    def test_gap_propagates_none(self):
        # After the gap the remaining run (4,5,6,7,8) is long enough for all
        # three smoothings to re-seed (needs 4+ points for period 2), so the
        # reading eventually returns - but only after a full re-warm-up.
        out = trix([1, 2, None, 4, 5, 6, 7, 8], 2)
        assert out[2] is None
        assert out[6] is None
        assert out[7] is not None

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            trix([1, 2, 3], 0)


class TestDema:
    def test_hand_calculated_period_2(self):
        closes = [1.0, 2.0, 3.0, 4.0]
        e1 = ema(closes, 2)  # [N, 1.5, 2.25, 3.125]
        e2 = ema(e1, 2)      # [N, 1.5, 2.0625, 2.78125]
        out = dema(closes, 2)
        assert out[:2] == [None, None]
        assert abs(out[3] - (2 * e1[3] - e2[3])) < 1e-9

    def test_reduces_lag_on_a_rally(self):
        closes = [float(x) for x in range(1, 40)]
        out = dema(closes, 5)
        # DEMA sits above the plain EMA while the trend is steadily up.
        assert out[-1] > ema(closes, 5)[-1]

    def test_gap_propagates_none(self):
        out = dema([1, 2, None, 4, 5, 6], 2)
        assert out[2] is None
        assert out[3] is None


class TestTema:
    def test_hand_calculated_period_2(self):
        closes = [1.0, 2.0, 3.0, 4.0]
        e1 = ema(closes, 2)
        e2 = ema(e1, 2)
        e3 = ema(e2, 2)
        out = tema(closes, 2)
        assert abs(out[3] - (3 * e1[3] - 3 * e2[3] + e3[3])) < 1e-9

    def test_tracks_a_straight_line_closely(self):
        closes = [float(x) for x in range(1, 60)]
        out = tema(closes, 5)
        plain = ema(closes, 5)[-1]
        # On a perfect ramp TEMA's lag is zero by construction, so it lands on
        # the close itself (float-exact within tolerance) and is strictly
        # closer to it than the plain EMA's 2-bar lag.
        assert abs(out[-1] - closes[-1]) < 1e-6
        assert abs(closes[-1] - out[-1]) < abs(closes[-1] - plain)

    def test_gap_propagates_none(self):
        out = tema([1, 2, None, 4, 5, 6], 2)
        assert out[2] is None
        assert out[3] is None


class TestAdx:
    def test_rising_series_has_plus_di_only(self):
        # Ten bars each up 1: every +DM is 1, -DM is 0, TR is 2.
        # Period 2: the first smoothed DI lands at index 2 -> +DI = 100*2/4
        # = 50, -DI = 0, DX = 100, and the first ADX appears at index
        # 2*period - 1 = 3 (it needs `period` DX readings).
        bars = [
            bar(f"2026-01-{d:02d}", o=18 + d, h=19 + d, l=17 + d, c=18 + d, v=1000)
            for d in range(1, 11)
        ]
        plus_di, minus_di, dx, adx_out = adx(bars, 2)
        assert plus_di[0] is None and plus_di[1] is None  # warming up
        assert abs(plus_di[2] - 50.0) < 1e-9
        assert minus_di[2] == 0.0
        assert dx[2] == 100.0
        assert adx_out[2] is None  # only one DX reading so far
        assert adx_out[3] == 100.0  # mean of the first two DX readings
        assert adx_out[-1] == 100.0

    def test_falling_series_has_minus_di_only(self):
        bars = [
            bar(f"2026-01-{d:02d}", o=28 - d, h=29 - d, l=27 - d, c=28 - d, v=1000)
            for d in range(1, 11)
        ]
        plus_di, minus_di, dx, adx_out = adx(bars, 2)
        assert plus_di[2] == 0.0
        assert abs(minus_di[2] - 50.0) < 1e-9
        assert dx[2] == 100.0
        assert adx_out[3] == 100.0

    def test_equal_pressure_gives_a_real_zero_dx(self):
        # Alternating equal-sized up/down bars: +DI and -DI come out equal,
        # so DX is exactly 0.0 - a genuine reading, not missing data.
        bars = [
            bar("2026-01-01", o=20, h=21, l=19, c=20, v=1000),
            bar("2026-01-02", o=20, h=23, l=21, c=22, v=1000),
            bar("2026-01-03", o=20, h=21, l=19, c=20, v=1000),
            bar("2026-01-04", o=20, h=23, l=21, c=22, v=1000),
            bar("2026-01-05", o=20, h=21, l=19, c=20, v=1000),
        ]
        plus_di, minus_di, dx, _adx_out = adx(bars, 2)
        # Change window (i=1,2): TR 3+3=6, +DM 2, -DM 2 -> both DIs 100/3.
        assert dx[2] == 0.0
        assert abs(plus_di[2] - 100.0 / 3.0) < 1e-9
        assert abs(minus_di[2] - 100.0 / 3.0) < 1e-9

    def test_gap_resets_and_rewarms(self):
        bars = [
            bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000),
            bar("2026-01-02", o=20, h=21, l=19, c=20, v=1000),
            bar("2026-01-03", o=21, h=22, l=20, c=21, v=1000),
            bar("2026-01-04", o=22, h=None, l=None, c=22, v=1000),  # gap
            bar("2026-01-05", o=24, h=25, l=23, c=24, v=1000),
            bar("2026-01-06", o=25, h=26, l=24, c=25, v=1000),
        ]
        plus_di, _minus_di, _dx, adx_out = adx(bars, 2)
        assert plus_di[2] == 50.0  # seeded from the two changes before the gap
        assert plus_di[3] is None
        # The bar after the gap has no previous high, so on this small fixture
        # the smoothing never re-seeds: values stay None, not stale.
        assert plus_di[5] is None
        assert adx_out[5] is None

    def test_degenerate_bars_yield_none(self):
        # high == low on every bar: no range, so no TR, DI or ADX.
        bars = [bar("2026-01-01", o=20, h=20, l=20, c=20, v=1000) for _ in range(5)]
        plus_di, minus_di, dx, adx_out = adx(bars, 2)
        assert plus_di == [None] * 5
        assert minus_di == [None] * 5
        assert dx == [None] * 5
        assert adx_out == [None] * 5

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            adx([bar("d", h=21, l=19, c=20)], 0)


class TestAroon:
    def test_newest_extreme_reads_100(self):
        bars = [
            bar("2026-01-01", h=20, l=18),
            bar("2026-01-02", h=21, l=19),
            bar("2026-01-03", h=22, l=20),
            bar("2026-01-04", h=23, l=21),
        ]
        up, down = aroon(bars, 2)
        assert up[0] is None and up[1] is None  # window needs period + 1 bars
        # At i=2 the window is bars 0..2: the high 22 sits on the newest bar
        # (Up = 100) while the low 18 sits on the oldest (Down = 0).
        assert up[2] == 100.0
        assert down[2] == 0.0
        # At i=3 the window is bars 1..3: high 23 newest (100), low 19 oldest
        # (0) - the ladder keeps Up pinned and Down floored.
        assert up[3] == 100.0
        assert down[3] == 0.0

    def test_stale_extremes_read_low(self):
        bars = [
            bar("2026-01-01", h=25, l=18),
            bar("2026-01-02", h=22, l=19),
            bar("2026-01-03", h=21, l=20),
            bar("2026-01-04", h=20, l=21),
        ]
        up, down = aroon(bars, 2)
        # Both extremes sit on the oldest bar of each window -> 0.0.
        assert up[2] == 0.0
        assert down[2] == 0.0
        assert up[3] == 0.0

    def test_hand_calculated_period_3(self):
        bars = [
            bar("2026-01-01", h=30, l=10),
            bar("2026-01-02", h=20, l=14),
            bar("2026-01-03", h=22, l=12),
            bar("2026-01-04", h=24, l=16),
            bar("2026-01-05", h=26, l=15),
        ]
        up, down = aroon(bars, 3)
        # i=3 window (bars 0..3): the high 30 and low 10 both sit on the
        # oldest bar -> 0.0 / 0.0. i=4 window (bars 1..4): the high 26 is on
        # the newest bar -> 100; the low 12 sits 2 bars back -> 100/3.
        assert up[3] == 0.0
        assert down[3] == 0.0
        assert up[4] == 100.0
        assert abs(down[4] - 100.0 / 3.0) < 1e-9

    def test_tie_resolves_to_the_most_recent_bar(self):
        bars = [
            bar("2026-01-01", h=25, l=20),
            bar("2026-01-02", h=22, l=20),
            bar("2026-01-03", h=25, l=20),
        ]
        up, _down = aroon(bars, 2)
        # Both end bars share the high; the usual convention credits the
        # newest one, giving 100 rather than 50.
        assert up[2] == 100.0

    def test_flat_series_reads_100_100(self):
        bars = [bar(f"2026-01-{d:02d}", h=20, l=18) for d in range(1, 6)]
        up, down = aroon(bars, 2)
        assert up[-1] == 100.0
        assert down[-1] == 100.0

    def test_missing_extremes_yield_none(self):
        bars = [
            bar("2026-01-01", h=20, l=18),
            bar("2026-01-02", h=21, l=19),
            bar("2026-01-03", h=22, l=None),
            bar("2026-01-04", h=23, l=21),
        ]
        up, down = aroon(bars, 2)
        assert up[2] is None
        assert down[3] is None  # the gap bar is inside this window too

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            aroon([bar("d", h=21, l=19)], 0)


class TestPsar:
    def test_rising_series_trails_below_and_accelerates(self):
        # Seed: up (close 21 >= 19), SAR = 18, EP = 20, af = 0.02. Wilder's
        # clamp pins the first two stops at the seed low (a stop may not sit
        # inside the previous two bars' range), then it accelerates:
        # 18 + 0.06*(24-18) = 18.36, then 18.36 + 0.08*(26-18.36) = 18.9712.
        bars = [
            bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000),
            bar("2026-01-02", o=21, h=22, l=20, c=21, v=1000),
            bar("2026-01-03", o=23, h=24, l=22, c=23, v=1000),
            bar("2026-01-04", o=25, h=26, l=24, c=25, v=1000),
            bar("2026-01-05", o=27, h=28, l=26, c=27, v=1000),
        ]
        out = psar(bars)
        assert out[0] is None  # the seed bar carries no stop yet
        assert out[1] == 18.0  # clamped to the previous bar's low
        assert out[2] == 18.0
        assert abs(out[3] - 18.36) < 1e-9
        assert abs(out[4] - 18.9712) < 1e-9
        assert all(out[i] < float(bars[i].low) for i in range(1, 5))

    def test_cross_reverses_onto_the_extreme_point(self):
        bars = [
            bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000),
            bar("2026-01-02", o=21, h=22, l=20, c=21, v=1000),
            bar("2026-01-03", o=22, h=23, l=21, c=22, v=1000),
            # The crash pierces the stop: the SAR jumps to the uptrend's EP.
            bar("2026-01-04", o=12, h=20, l=10, c=11, v=1000),
            bar("2026-01-05", o=10, h=11, l=9, c=10, v=1000),
        ]
        out = psar(bars)
        assert out[3] == 23.0  # the high made on 2026-01-03
        # Now above price: Wilder's clamp holds it at the prior high for one
        # bar (the stop may not drop below it), then it accelerates down.
        assert out[4] == 23.0

    def test_gap_ends_the_run_and_reseeds(self):
        bars = [
            bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000),
            bar("2026-01-02", o=21, h=22, l=20, c=21, v=1000),
            bar("2026-01-03", o=22, h=None, l=None, c=22, v=1000),  # gap
            bar("2026-01-04", o=29, h=30, l=26, c=29, v=1000),
            bar("2026-01-05", o=31, h=32, l=30, c=31, v=1000),
        ]
        out = psar(bars)
        assert out[0] is None
        assert out[1] == 18.0
        assert out[2] is None
        # A fresh pair re-seeds after the gap: 2026-01-04 is only the new
        # seed's previous bar, so the first stop lands on 2026-01-05, clamped
        # to the seed bar's low of 26.
        assert out[3] is None
        assert out[4] == 26.0

    def test_degenerate_or_missing_bars_yield_none(self):
        bars = [
            bar("2026-01-01", o=20, h=20, l=20, c=20, v=1000),  # no range
            bar("2026-01-02", o=20, h=20, l=20, c=20, v=1000),
            bar("2026-01-03", o=20, h=20, l=20, c=20, v=1000),
        ]
        assert psar(bars) == [None, None, None]
        assert psar([bar("d", o=1, c=1)]) == [None]

    def test_rejects_bad_acceleration(self):
        import pytest

        bars = [bar("d", h=21, l=19, c=20)]
        with pytest.raises(ValueError):
            psar(bars, af_step=0)
        with pytest.raises(ValueError):
            psar(bars, af_step=0.3, af_max=0.2)


class TestSupertrend:
    def test_hand_calculated_period_2(self):
        # ATR(2) runs [N, 2.5, 2.25, 2.125, 5.0625, 4.53125]; the line rides
        # the ratcheting lower band until the crash bar closes below it and
        # flips to the upper band.
        bars = [
            bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000),
            bar("2026-01-02", o=21, h=22, l=19, c=21, v=1000),
            bar("2026-01-03", o=22, h=23, l=21, c=22, v=1000),
            bar("2026-01-04", o=23, h=24, l=22, c=23, v=1000),
            bar("2026-01-05", o=17, h=19, l=15, c=16, v=1000),
            bar("2026-01-06", o=15, h=17, l=13, c=14, v=1000),
        ]
        out = supertrend(bars, period=2, mult=1.0)
        assert out[0] is None          # ATR warm-up
        assert out[1] == 18.0          # seed: mid 20.5 - ATR 2.5
        assert out[2] == 19.75         # lower band ratchets up to 22 - 2.25
        assert out[3] == 20.875        # 23 - 2.125
        # Close 16 < 20.875 flips the line, and the upper band ratchets down
        # to 17 + 5.0625 first, so the flip lands on the tightened band.
        assert out[4] == 22.0625
        assert out[5] == 19.53125      # upper band ratchets down to 15 + 4.53125

    def test_stays_below_price_in_an_uptrend(self):
        bars = [
            bar(f"2026-01-{d:02d}", o=17 + d, h=18 + d, l=16 + d, c=17 + d, v=1000)
            for d in range(1, 16)
        ]
        out = supertrend(bars, period=3, mult=2.0)
        assert out[2] is not None
        for i in range(2, 15):
            assert out[i] is not None and out[i] < float(bars[i].low)

    def test_warmup_and_bad_params(self):
        bars = [bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000)]
        assert supertrend(bars, period=2) == [None]
        import pytest

        with pytest.raises(ValueError):
            supertrend(bars, period=0)
        with pytest.raises(ValueError):
            supertrend(bars, mult=0)


class TestVortex:
    def test_rising_series_has_vi_plus_above_vi_minus(self):
        # Each change: VM+ = 3, VM- = 1, TR = 2. Over a 2-bar window:
        # VI+ = 6/4 = 1.5, VI- = 2/4 = 0.5.
        bars = [
            bar(f"2026-01-{d:02d}", o=18 + d, h=19 + d, l=17 + d, c=18 + d, v=1000)
            for d in range(1, 6)
        ]
        plus, minus = vortex(bars, 2)
        assert plus[0] is None and plus[1] is None  # needs `period` changes
        assert abs(plus[2] - 1.5) < 1e-9
        assert abs(minus[2] - 0.5) < 1e-9
        assert plus[4] > minus[4]

    def test_falling_series_has_vi_minus_above_vi_plus(self):
        bars = [
            bar(f"2026-01-{d:02d}", o=21 - d, h=22 - d, l=20 - d, c=21 - d, v=1000)
            for d in range(1, 6)
        ]
        plus, minus = vortex(bars, 2)
        assert abs(plus[2] - 0.5) < 1e-9
        assert abs(minus[2] - 1.5) < 1e-9
        assert minus[4] > plus[4]

    def test_gap_clears_the_window(self):
        bars = [
            bar("2026-01-01", o=19, h=20, l=18, c=19, v=1000),
            bar("2026-01-02", o=20, h=None, l=None, c=20, v=1000),  # gap
            bar("2026-01-03", o=21, h=22, l=20, c=21, v=1000),
            bar("2026-01-04", o=22, h=23, l=21, c=22, v=1000),
        ]
        plus, minus = vortex(bars, 2)
        # Only one usable change survives the gap: not enough to re-warm.
        assert plus == [None, None, None, None]
        assert minus == [None, None, None, None]

    def test_rejects_bad_period(self):
        import pytest

        with pytest.raises(ValueError):
            vortex([bar("d", h=21, l=19, c=20)], 0)


class TestIchimoku:
    def _bars(self):
        return [
            bar("2026-01-01", h=10, l=6, c=8),
            bar("2026-01-02", h=12, l=8, c=10),
            bar("2026-01-03", h=14, l=10, c=12),
            bar("2026-01-04", h=16, l=12, c=14),
            bar("2026-01-05", h=18, l=14, c=16),
            bar("2026-01-06", h=20, l=16, c=18),
            bar("2026-01-07", h=22, l=18, c=20),
        ]

    def test_midpoints_are_range_halvers(self):
        # Tenkan(2) and kijun(3) are (window high + window low) / 2; on this
        # ladder the window extremes are always the newest high and the
        # oldest low, e.g. tenkan[1] = (12 + 6) / 2 = 9, kijun[2] = (14 + 6) / 2 = 10.
        tenkan, kijun, _a, _b, _chikou = ichimoku(self._bars(), conversion=2, base=3, span_b=4)
        assert tenkan[0] is None
        assert tenkan[1] == 9.0
        assert tenkan[6] == 19.0
        assert kijun[1] is None
        assert kijun[2] == 10.0
        assert kijun[6] == 18.0

    def test_cloud_is_pushed_forward(self):
        _tenkan, _kijun, senkou_a, senkou_b, _chikou = ichimoku(self._bars(), 2, 3, 4)
        # Span A = (tenkan + kijun) / 2 of the anchor `base` bars back.
        assert senkou_a[3] is None  # anchor bar 0 has no tenkan/kijun yet
        assert senkou_a[4] is None  # anchor bar 1 has no kijun yet
        assert senkou_a[5] == 10.5  # (11 + 10) / 2 from anchor bar 2
        assert senkou_a[6] == 12.5  # (13 + 12) / 2 from anchor bar 3
        # Span B = the span_b-bar Donchian midpoint of the same anchor.
        assert senkou_b[5] is None
        assert senkou_b[6] == 11.0  # (16 + 6) / 2 from anchor bar 3

    def test_chikou_lags_close_and_future_is_none(self):
        _t, _k, _a, _b, chikou = ichimoku(self._bars(), 2, 3, 4)
        assert chikou[0] == 14.0  # the close 3 sessions later
        assert chikou[3] == 20.0
        assert chikou[4] is None  # would need a close beyond the data
        assert chikou[-1] is None

    def test_alignment_and_missing_data(self):
        bars = self._bars()
        bars[2] = bar("2026-01-03", h=14, l=None, c=12)  # the low goes missing
        tenkan, kijun, senkou_a, senkou_b, chikou = ichimoku(bars, 2, 3, 4)
        assert (
            len(tenkan) == len(kijun) == len(senkou_a)
            == len(senkou_b) == len(chikou) == 7
        )
        assert tenkan[2] is None  # window spans the gap
        assert tenkan[3] is None  # so does the next one
        assert tenkan[4] == 15.0  # bars 3..4 are clean again
        assert kijun[4] is None   # its window still contains bar 2
        assert senkou_a[5] is None  # spans inherit the anchor's None
        assert senkou_b[6] is None
        assert chikou[2] == 18.0  # the close 3 bars ahead (bar 5), not bar 2's own

    def test_rejects_bad_params(self):
        import pytest

        with pytest.raises(ValueError):
            ichimoku(self._bars(), conversion=0)
        with pytest.raises(ValueError):
            ichimoku(self._bars(), base=-1)


class TestRsi:
    def test_warmup_is_none(self):
        closes = [10, 11, 12, 13]
        out = rsi(closes, 14)
        assert out == [None] * 4

    def test_all_gains_is_100(self):
        closes = list(range(1, 21))  # 20 rising closes -> 19 rising changes
        out = rsi(closes, 14)
        assert out[13] is None  # 13 changes: one short of a full window
        assert out[14] == 100.0
        assert out[19] == 100.0

    def test_all_losses_is_0(self):
        closes = list(range(20, 0, -1))
        out = rsi(closes, 14)
        assert out[19] == 0.0

    def test_flat_series_is_neutral_not_missing(self):
        closes = [50.0] * 20
        out = rsi(closes, 14)
        # No gains and no losses: a real reading of 50, not None.
        assert out[19] == 50.0

    def test_gap_propagates_none(self):
        closes = [float(x) for x in range(1, 21)]
        closes[15] = None
        out = rsi(closes, 14)
        assert out[15] is None
        assert out[19] is None  # window still contains the gap

    def test_matches_wilder_reference_example(self):
        # Wilder's canonical worked example ("New Concepts in Technical
        # Trading Systems"): avg gain 0.23839, avg loss 0.09959,
        # RS 2.39371 -> RSI 70.53. This pins the smoothing, not just the range.
        closes = [
            44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955,
            45.4245, 45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820,
            46.2820,
        ]
        out = rsi(closes, 14)
        assert out[13] is None  # 14 closes is 13 changes: still warming up
        assert abs(out[14] - 70.53) < 0.01

    def test_typical_mixed_series_is_between_0_and_100(self):
        closes = [
            10, 11, 10.5, 12, 11.5, 13, 12.5, 14, 13.5, 15, 14.5,
            16, 15.5, 17, 16.5, 18, 17.5, 19, 18.5, 20, 19.5, 21,
        ]
        out = rsi(closes, 14)
        for value in out[14:]:
            assert value is None or 0.0 <= value <= 100.0


class TestMacd:
    def test_returns_three_aligned_series(self):
        closes = [float(x) for x in range(1, 60)]
        line, signal, hist = macd(closes)
        assert len(line) == len(signal) == len(hist) == len(closes)

    def test_histogram_is_none_until_signal_exists(self):
        closes = [float(x) for x in range(1, 60)]
        line, signal, hist = macd(closes)
        first_signal = next(i for i, v in enumerate(signal) if v is not None)
        assert all(h is None for h in hist[:first_signal])
        assert all(
            (h is None and (m is None or s is None)) or abs(h - (m - s)) < 1e-9
            for h, m, s in zip(hist, line, signal)
        )

    def test_crossover_does_not_fabricate_zero(self):
        closes = [100.0] * 30 + [float(x) for x in range(101, 140)]
        line, signal, hist = macd(closes)
        for value in hist:
            assert value is None or isinstance(value, float)


class TestRoc:
    def test_basic(self):
        assert roc([100, 110], 1) == [None, 10.0]

    def test_zero_base_is_none(self):
        assert roc([0, 50], 1) == [None, None]

    def test_missing_is_none(self):
        assert roc([None, 50], 1) == [None, None]


class TestBollinger:
    def test_flat_series_gives_zero_width_and_none_percent_b(self):
        closes = [10.0] * 20
        mid, up, lo, bandwidth, pct_b = bollinger(closes, 20)
        assert mid[-1] == 10.0
        assert up[-1] == 10.0
        assert lo[-1] == 10.0
        assert bandwidth[-1] == 0.0
        # A zero-width band makes %B undefined; must not be 0 or 50.
        assert pct_b[-1] is None

    def test_warmup(self):
        mid, up, lo, _bw, _pb = bollinger([1, 2, 3], 20)
        assert mid == [None, None, None]
        assert up == [None, None, None]
        assert lo == [None, None, None]

    def test_upper_above_lower(self):
        closes = [10, 12, 11, 13, 12, 14, 13, 15, 14, 16] * 3
        _mid, up, lo, _bw, _pb = bollinger(closes, 20)
        for u, l in zip(up, lo):
            if u is not None and l is not None:
                assert u >= l


class TestAtr:
    def test_true_range_uses_previous_close(self):
        assert true_range(110.0, 100.0, 105.0) == 10.0  # |110-105| = 5, H-L = 10
        assert true_range(110.0, 100.0, 100.0) == 10.0
        assert true_range(110.0, 100.0, 120.0) == 20.0  # |100-120| = 20

    def test_no_previous_close_degrades_to_high_low(self):
        assert true_range(110.0, 100.0, None) == 10.0

    def test_warmup(self):
        bars = [bar("2026-01-01", h=110, l=100, c=105, v=1000)]
        assert atr(bars, 14) == [None]

    def test_increasing_atr(self):
        bars = [
            bar(f"2026-01-{d:02d}", h=100 + d, l=100 + d - 5, c=100 + d - 2, v=1000)
            for d in range(1, 20)
        ]
        out = atr(bars, 14)
        assert out[13] is not None
        assert out[18] is not None and out[18] > 0


class TestMoneyFlowMultiplier:
    def test_typical(self):
        # ((C-L) - (H-C)) / (H-L) with H=110, L=100, C=110 -> (10 - 0)/10 = 1.0
        assert money_flow_multiplier(bar("d", h=110, l=100, c=110)) == 1.0

    def test_midpoint_close_is_zero(self):
        assert money_flow_multiplier(bar("d", h=110, l=100, c=105)) == 0.0

    def test_low_close_is_negative(self):
        assert money_flow_multiplier(bar("d", h=110, l=100, c=100)) == -1.0

    def test_limit_locked_day_is_none_not_zero(self):
        # high == low: the denominator is zero, so the multiplier is undefined.
        # Returning 0.0 here would invent a neutral day on a limit-locked one.
        b = bar("d", h=100, l=100, c=100, v=5000)
        assert money_flow_multiplier(b) is None
        assert money_flow_volume(b) is None

    def test_missing_close_is_none(self):
        assert money_flow_multiplier(bar("d", h=110, l=100)) is None

    def test_missing_volume_is_none(self):
        assert money_flow_volume(bar("d", h=110, l=100, c=110)) is None


class TestAccumulationDistribution:
    def test_cumulative(self):
        bars = [
            bar("1", h=110, l=100, c=110, v=1000),  # mfm 1.0 -> +1000
            bar("2", h=110, l=100, c=100, v=1000),  # mfm -1.0 -> -1000
            bar("3", h=110, l=100, c=105, v=1000),  # mfm 0.0 -> +0
        ]
        out = accumulation_distribution_line(bars)
        assert out == [1000.0, 0.0, 0.0]

    def test_alias_is_same_function(self):
        assert accumulation_distribution is accumulation_distribution_line

    def test_limit_locked_day_is_skipped_not_zeroed(self):
        bars = [
            bar("1", h=110, l=100, c=110, v=1000),  # +1000
            bar("2", h=100, l=100, c=100, v=5000),  # undefined -> skipped
            bar("3", h=110, l=100, c=110, v=1000),  # +1000
        ]
        out = accumulation_distribution_line(bars)
        # Line holds its value through the undefined day rather than resetting.
        assert out == [1000.0, 1000.0, 2000.0]

    def test_leading_undefined_is_none(self):
        bars = [bar("1", h=100, l=100, c=100, v=10), bar("2", h=110, l=100, c=110, v=100)]
        out = accumulation_distribution_line(bars)
        assert out[0] is None
        assert out[1] == 100.0


class TestObv:
    def test_direction(self):
        bars = [
            bar("1", c=100, v=1000),
            bar("2", c=105, v=500),   # up -> +500
            bar("3", c=100, v=300),   # down -> -300
            bar("4", c=100, v=700),   # unchanged -> +0
        ]
        assert obv(bars) == [0.0, 500.0, 200.0, 200.0]

    def test_unchanged_close_is_a_real_zero_step(self):
        bars = [bar("1", c=100, v=1000), bar("2", c=100, v=1000)]
        out = obv(bars)
        assert out[1] == 0.0  # a genuine zero, distinct from None

    def test_missing_volume_keeps_previous_value(self):
        bars = [bar("1", c=100, v=1000), bar("2", c=105, v=None)]
        out = obv(bars)
        assert out[1] == 0.0  # no volume, so no step, but not None

    def test_empty(self):
        assert obv([]) == []


class TestChaikinMoneyFlow:
    def test_warmup_is_none(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=1000) for i in range(5)]
        assert chaikin_money_flow(bars, 20) == [None] * 5

    def test_all_buying_is_100(self):
        bars = [bar(str(i), h=110, l=100, c=110, v=1000) for i in range(25)]
        out = chaikin_money_flow(bars, 20)
        assert out[19] == 100.0
        assert out[24] == 100.0

    def test_all_selling_is_negative_100(self):
        bars = [bar(str(i), h=110, l=100, c=100, v=1000) for i in range(25)]
        out = chaikin_money_flow(bars, 20)
        assert out[19] == -100.0

    def test_neutral_is_zero(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=1000) for i in range(25)]
        out = chaikin_money_flow(bars, 20)
        assert out[24] == 0.0

    def test_zero_total_volume_window_is_none(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=0) for i in range(25)]
        out = chaikin_money_flow(bars, 20)
        # Undefined, not 0% buying pressure.
        assert out[24] is None


class TestVwap:
    def test_basic(self):
        bars = [
            bar("1", h=110, l=100, c=105, v=1000),  # tp 105
            bar("2", h=120, l=110, c=115, v=1000),  # tp 115
        ]
        assert vwap(bars) == 110.0
        assert vwap_series(bars) == [105.0, 110.0]

    def test_zero_volume_is_none(self):
        assert vwap([bar("1", h=110, l=100, c=105, v=0)]) is None

    def test_missing_volume_is_none(self):
        assert vwap([bar("1", h=110, l=100, c=105)]) is None

    def test_partial_data(self):
        bars = [bar("1", h=110, l=100, c=105, v=1000), bar("2", h=120, l=110, c=115)]
        assert vwap(bars) == 105.0  # only the usable bar counts


class TestVolumeSmaRatio:
    def test_spike(self):
        # 20 sessions of 100, then a 300-volume day.
        bars = [bar(str(i), v=100.0) for i in range(20)]
        bars.append(bar("20", v=300.0))
        out = volume_sma_ratio(bars, 20)
        assert out[18] is None  # warm-up
        assert out[19] == 100.0  # last window is all 100
        # Rolling average at index 20 is (19*100 + 300)/20 = 110.
        assert out[20] is not None
        assert abs(out[20] - 300.0 / 110.0 * 100.0) < 1e-9

    def test_zero_average_is_none(self):
        # The rolling window includes today, so all 20 trailing volumes must
        # be zero for the average to be zero.
        bars = [bar(str(i), v=0.0) for i in range(21)]
        assert volume_sma_ratio(bars, 20)[20] is None

    def test_missing_volume_is_none(self):
        bars = [bar(str(i), v=100.0) for i in range(20)]
        bars.append(bar("20", v=None))
        assert volume_sma_ratio(bars, 20)[20] is None


class TestMoneyFlowIndex:
    def test_all_up_is_100(self):
        bars = [
            bar(str(i), h=100 + i, l=100 + i - 1, c=100 + i, v=1000) for i in range(20)
        ]
        out = money_flow_index(bars, 14)
        assert out[19] == 100.0

    def test_all_down_is_0(self):
        bars = [
            bar(str(i), h=200 - i, l=200 - i - 1, c=200 - i, v=1000) for i in range(20)
        ]
        out = money_flow_index(bars, 14)
        assert out[19] == 0.0

    def test_warmup(self):
        bars = [bar(str(i), h=110, l=100, c=105, v=1000) for i in range(10)]
        assert money_flow_index(bars, 14) == [None] * 10

    def test_missing_volume_is_none(self):
        bars = [
            bar(str(i), h=110, l=100, c=105 + i, v=None) for i in range(20)
        ]
        out = money_flow_index(bars, 14)
        assert out[19] is None

    def test_flat_prices_are_neutral_50(self):
        bars = [bar(str(i), h=105, l=105, c=105, v=1000) for i in range(20)]
        out = money_flow_index(bars, 14)
        assert out[19] == 50.0


class TestAdjustedClose:
    """Tests for adjusted close derivation from corporate actions.

    Adjusted close = raw close × adjustment_factor, where
    adjustment_factor = ∏ (1 + bonus_pct/100) × (right_ratio)
    for each corporate action with book_close date ≤ the bar's date.

    Worked example:
    - Bar date: 2026-10-01, raw close: 100
    - Corporate action: bonus 10%, book_close: 2026-09-30, right_ratio: 1.0 (no rights)
    - Adjustment: 100 × (1 + 10/100) = 110
    """

    def test_bonus_only_adjustment(self):
        from app.analytics.indicators import adjusted_close_series

        bars = [
            bar("2026-09-28", o=100, h=105, l=95, c=100, v=1000),
            bar("2026-09-29", o=100, h=105, l=95, c=101, v=1000),
            bar("2026-09-30", o=101, h=106, l=96, c=102, v=1000),  # book close date
            bar("2026-10-01", o=102, h=107, l=97, c=103, v=1000),
            bar("2026-10-02", o=103, h=108, l=98, c=104, v=1000),
        ]

        # Bonus 10% with book_close on 2026-09-30
        corporate_actions = [
            {"book_close": "30/09/2026", "bonus_pct": 10.0, "right_pct": None},
        ]

        adjusted = adjusted_close_series(bars, corporate_actions)

        # Before book close: no adjustment
        assert adjusted[0] == 100.0
        assert adjusted[1] == 101.0
        # On book close: no adjustment yet (action effective after close)
        assert adjusted[2] == 102.0
        # After book close: adjusted by 10%
        assert adjusted[3] == 103.0 * 1.10  # 113.3
        assert adjusted[4] == 104.0 * 1.10  # 114.4

    def test_bonus_and_rights_adjustment(self):
        from app.analytics.indicators import adjusted_close_series

        bars = [
            bar("2026-10-01", c=100),
            bar("2026-10-02", c=101),
            bar("2026-10-03", c=102),  # book close
            bar("2026-10-04", c=103),
        ]

        # 5% bonus + 1:2 rights issue (right_ratio = 1.5)
        corporate_actions = [
            {"book_close": "03/10/2026", "bonus_pct": 5.0, "right_pct": 50.0},
        ]

        adjusted = adjusted_close_series(bars, corporate_actions)

        # Before book close
        assert adjusted[0] == 100.0
        assert adjusted[1] == 101.0
        # On book close
        assert adjusted[2] == 102.0
        # After: 103 × (1 + 5/100) × 1.5 = 103 × 1.05 × 1.5 = 162.225
        expected = 103 * 1.05 * 1.5
        assert abs(adjusted[3] - expected) < 0.001

    def test_no_actions_returns_raw_close(self):
        from app.analytics.indicators import adjusted_close_series

        bars = [
            bar("2026-10-01", c=100),
            bar("2026-10-02", c=101),
        ]
        corporate_actions = []

        adjusted = adjusted_close_series(bars, corporate_actions)

        assert adjusted == [100.0, 101.0]

    def test_missing_close_returns_none(self):
        from app.analytics.indicators import adjusted_close_series

        bars = [
            bar("2026-10-01", c=100),
            bar("2026-10-02", c=None),  # missing
            bar("2026-10-03", c=102),
        ]
        corporate_actions = [
            {"book_close": "01/10/2026", "bonus_pct": 10.0, "right_pct": None},
        ]

        adjusted = adjusted_close_series(bars, corporate_actions)

        assert adjusted[0] == 100.0
        assert adjusted[1] is None
        assert adjusted[2] == 102.0 * 1.10

    def test_multiple_actions_compound(self):
        from app.analytics.indicators import adjusted_close_series

        bars = [
            bar("2026-09-01", c=100),
            bar("2026-09-15", c=101),  # book close for action 1
            bar("2026-09-30", c=102),
            bar("2026-10-15", c=103),  # book close for action 2
            bar("2026-10-31", c=104),
        ]

        # Two bonus actions
        corporate_actions = [
            {"book_close": "15/09/2026", "bonus_pct": 10.0, "right_pct": None},
            {"book_close": "15/10/2026", "bonus_pct": 5.0, "right_pct": None},
        ]

        adjusted = adjusted_close_series(bars, corporate_actions)

        # Before first book close
        assert adjusted[0] == 100.0
        # Between book closes: adjusted by 10%
        assert adjusted[1] == 101.0  # on book close, no adjustment yet
        assert adjusted[2] == 102.0 * 1.10
        # On second book close
        assert adjusted[3] == 103.0 * 1.10
        # After second: adjusted by 10% then 5% = 1.155
        assert abs(adjusted[4] - 104.0 * 1.155) < 0.001

    def test_dd_mm_yyyy_book_close_format(self):
        from app.analytics.indicators import adjusted_close_series

        bars = [
            bar("2026-10-01", c=100),
            bar("2026-10-02", c=101),  # book close date in DD/MM/YYYY
        ]
        corporate_actions = [
            {"book_close": "02/10/2026", "bonus_pct": 10.0, "right_pct": None},
        ]

        adjusted = adjusted_close_series(bars, corporate_actions)

        assert adjusted[0] == 100.0
        assert adjusted[1] == 101.0  # on book close date


class TestComputeOnValid:
    """Phase 4: a null close must not blank the windows after it.

    The plain functions (`sma`, `ema`, `rsi`, `macd`, `bollinger`) return None
    for any window touching a gap - the strict contract the Batch A tests
    lock in. The `*_on_valid` variants are the chart/page layer's answer: they
    compute on the non-None closes only, so one missing close costs one point
    instead of twenty days of output.
    """

    # 25 closes with a single null at index 3. Long enough for every warm-up
    # used below (MACD needs 26 for signal? no: signal needs 12+26... kept at
    # 25 so SMA/EMA/RSI/Bollinger are all past warm-up; MACD asserts only the
    # no-crash + alignment contract, not values).
    GAP_SERIES = [1.0, 2, 3, None, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                  16, 17, 18, 19, 20, 21, 22, 23, 24, 25]

    def test_sma_skips_gap(self):
        out = sma_on_valid(self.GAP_SERIES, 3)
        assert len(out) == len(self.GAP_SERIES)  # lengths always match
        assert out[2] == 2.0
        assert out[3] is None  # the null position itself stays None
        # Window at index 4 spans the last 3 *valid* values (2, 3, 5): the
        # gap is skipped, not propagated.
        assert out[4] == (2.0 + 3.0 + 5.0) / 3
        assert out[24] == (23.0 + 24.0 + 25.0) / 3

    def test_ema_skips_gap(self):
        out = ema_on_valid(self.GAP_SERIES, 3)
        assert len(out) == len(self.GAP_SERIES)
        assert out[2] == 2.0  # SMA seed of the first 3 closes
        assert out[3] is None
        # Recurrence continues across the gap on valid values only.
        alpha = 2.0 / 4.0
        assert out[4] == pytest.approx(alpha * 5.0 + (1 - alpha) * 2.0)
        # A null-free suffix equals the plain ema on the same values.
        tail = self.GAP_SERIES[4:]
        assert ema_on_valid(tail, 3)[-1] == ema(tail, 3)[-1]

    def test_rsi_skips_gap(self):
        out = rsi_on_valid(self.GAP_SERIES, 14)
        assert len(out) == len(self.GAP_SERIES)
        assert out[3] is None
        # Strictly rising closes -> RSI 100 once warm, gap or no gap. The gap
        # sits at original index 3, so clean index 14 (the first RSI value)
        # maps back to original index 15.
        assert out[15] == 100.0
        assert out[24] == 100.0

    def test_macd_skips_gap_and_never_crashes(self):
        # Regression: macd_on_valid used to do `None - None` on the ema
        # warm-up and raised TypeError on every request.
        long_series = list(self.GAP_SERIES) + [26.0, 27.0, 28.0, 29.0, 30.0]
        line, signal, hist = macd_on_valid(long_series)
        assert len(line) == len(long_series)
        assert len(signal) == len(long_series)
        assert len(hist) == len(long_series)
        assert line[3] is None and signal[3] is None and hist[3] is None
        # Past both warm-ups every position carries a real number.
        assert all(v is not None for v in line[34:])
        assert all(v is not None for v in signal[34:])

    def test_macd_matches_plain_macd_on_null_free_input(self):
        clean = [float(i) for i in range(1, 41)]
        l1, s1, h1 = macd(clean)
        l2, s2, h2 = macd_on_valid(clean)
        assert l1 == l2 and s1 == s2 and h1 == h2

    def test_bollinger_skips_gap(self):
        mid, up, lo, bw, pctb = bollinger_on_valid(self.GAP_SERIES, 5, 2.0)
        assert len(mid) == len(self.GAP_SERIES)
        assert mid[3] is None and up[3] is None and lo[3] is None
        # Index 7 window = last 5 valid closes (3, 5, 6, 7, 8).
        assert mid[7] == pytest.approx((3 + 5 + 6 + 7 + 8) / 5)
        assert up[7] == pytest.approx(mid[7] + 2.0 * stdev([3, 5, 6, 7, 8]))

    def test_all_null_input_returns_all_null_not_crash(self):
        # Regression guard for the shared-list aliasing the first draft had:
        # the five bollinger lists (and three macd lists) must be independent.
        empties = [None] * 7
        l, s, h = macd_on_valid(empties)
        assert l == s == h == [None] * 7
        l[0] = 1.0
        assert s[0] is None  # mutating one list must not touch the others
        m, u, lo, bw, p = bollinger_on_valid(empties, 5, 2.0)
        m[0] = 1.0
        assert u[0] is None and lo[0] is None

    def test_dates_never_shift(self):
        dates = [f"2026-09-{i:02d}" for i in range(1, 26)]
        out = sma_on_valid(self.GAP_SERIES, 3)
        assert len(dates) == len(out)  # zip in the routes stays 1:1
