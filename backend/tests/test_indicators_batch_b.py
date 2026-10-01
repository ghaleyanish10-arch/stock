"""Batch B indicator tests: hand-computed expectations, spec doc indicator by indicator.

Every expected number below was computed by hand from the doc's formula (and the
standard construction it references), not by running the implementation. Gaps and
warm-ups must yield None, never 0 - the same honesty contract as the rest of the app.
"""

import math

import pytest

from app.analytics.indicators import (
    Bar,
    alma,
    asi,
    average_price,
    ema_cross,
    highest,
    hl2_series,
    hlc3_series,
    linreg_endpoint,
    linreg_slope,
    lowest,
    ma_cross,
    ma_ema_cross,
    ohlc4_series,
    percentrank,
    rma,
)


def bar(o, h, l, c, v=1000.0, date="2026-01-01"):
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=v)


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class TestRma:
    def test_seed_and_recursion(self):
        # Seed = SMA(1,2,3,4) = 2.5; then (2.5*3 + 5)/4 = 3.125,
        # (3.125*3 + 6)/4 = 3.84375, (3.84375*3 + 7)/4 = 4.6328125.
        out = rma([1, 2, 3, 4, 5, 6, 7], 4)
        assert out[:3] == [None, None, None]
        assert out[3] == pytest.approx(2.5)
        assert out[4] == pytest.approx(3.125)
        assert out[5] == pytest.approx(3.84375)
        assert out[6] == pytest.approx(4.6328125)

    def test_gap_breaks_run(self):
        out = rma([1, 2, None, 4, 5], 2)
        assert out[1] == pytest.approx(1.5)
        assert out[2] is None  # warm-up of the new run
        assert out[3] is None
        assert out[4] == pytest.approx(4.5)


class TestHighestLowest:
    def test_basic(self):
        vals = [1, None, 3, 5, 2, 4]
        assert highest(vals, 3) == [None, None, None, None, 5.0, 5.0]
        assert lowest(vals, 3) == [None, None, None, None, 2.0, 2.0]

    def test_no_gaps(self):
        assert highest([1, 2, 3, 2, 1], 3) == [None, None, 3.0, 3.0, 3.0]
        assert lowest([1, 2, 3, 2, 1], 3) == [None, None, 1.0, 2.0, 1.0]


class TestLinreg:
    def test_endpoint_perfect_line(self):
        out = linreg_endpoint([1, 2, 3, 4, 5], 5)
        assert out[4] == pytest.approx(5.0)

    def test_endpoint_and_slope_hand_fit(self):
        # y = [1,2,3,4,6]: mean 3.2, Sxy = 12.0, Sxx = 10 -> b = 1.2, a = 0.8;
        # endpoint = 0.8 + 1.2*4 = 5.6.
        assert linreg_endpoint([1, 2, 3, 4, 6], 5)[4] == pytest.approx(5.6)
        assert linreg_slope([1, 2, 3, 4, 6], 5)[4] == pytest.approx(1.2)

    def test_flat_slope_is_genuine_zero(self):
        assert linreg_slope([5, 5, 5, 5], 4)[3] == 0.0

    def test_warmup_and_gaps(self):
        assert all(v is None for v in linreg_endpoint([1, 2, 3], 5))
        out = linreg_slope([1, None, 3, 4, 5, 6], 3)
        assert out[2] is None  # window contains the gap
        assert out[4] == pytest.approx(1.0)  # [3,4,5]
        assert out[5] == pytest.approx(1.0)  # [4,5,6]


class TestPercentrank:
    def test_hand_ranked(self):
        # idx2 window [1,3,2]: cur=2, one smaller value -> 1/2*100 = 50.
        # idx3 window [3,2,5]: cur=5, both smaller -> 100. idx4 [2,5,4] -> 50.
        out = percentrank([1, 3, 2, 5, 4], 3)
        assert out[:2] == [None, None]
        assert out[2] == pytest.approx(50.0)
        assert out[3] == pytest.approx(100.0)
        assert out[4] == pytest.approx(50.0)


class TestPricePrimitives:
    BARS = [bar(10, 12, 10, 11), bar(None, 12, 10, 11)]

    def test_hl2_hlc3_ohlc4(self):
        assert hl2_series(self.BARS) == [11.0, 11.0]
        # hlc3 needs high/low/close only - present in both bars.
        assert hlc3_series(self.BARS) == [11.0, 11.0]
        assert ohlc4_series(self.BARS) == [10.75, None]


# ---------------------------------------------------------------------------
# Doc #1 ALMA
# ---------------------------------------------------------------------------


class TestAlma:
    def test_hand_computed_weights(self):
        # period 5, offset 0.85, sigma 6: m = 3.4, s = 5/6, 2s^2 = 1.38889.
        # w = [0.000242, 0.015764, 0.243965, 0.891180, 0.771688], sum 1.922839.
        # On [1..5]: (0.000126*1 + 0.008196*2 + 0.126893*3 + 0.463502*4
        #             + 0.401283*5) = 4.25762.
        out = alma([1, 2, 3, 4, 5], 5)
        assert out[4] == pytest.approx(4.2576, abs=1e-3)
        assert out[:4] == [None, None, None, None]

    def test_constant_series_is_exact(self):
        out = alma([7.0] * 9, 9)
        assert out[8] == pytest.approx(7.0)

    def test_insufficient_history(self):
        assert all(v is None for v in alma([1, 2, 3], 5))


# ---------------------------------------------------------------------------
# Doc #2 ASI
# ---------------------------------------------------------------------------


class TestAsi:
    def test_hand_computed_cumulation(self):
        # bar1 vs bar0: dc=1.5, body=1.5, body_prev=1; H-C_prev=2 dominant ->
        # R = 2 - 0.5*0 + 0.25 = 2.25; SI = 50*(1.5+0.75+0.25)/2.25 = 55.5556.
        # bar2 vs bar1: dc=1, body=1, body_prev=1.5; H-C_prev=1.5 ties
        # |body_prev|=1.5 -> R = (14-12) + 0.375 = 2.375;
        # SI = 50*(1+0.5+0.375)/2.375 = 39.4737; ASI = 95.0292.
        bars = [bar(10, 12, 10, 11), bar(11, 13, 11, 12.5), bar(12.5, 14, 12, 13.5)]
        out = asi(bars)
        assert out[0] is None
        assert out[1] == pytest.approx(55.5556, abs=1e-3)
        assert out[2] == pytest.approx(95.0292, abs=1e-3)

    def test_flat_bar_leaves_accumulator(self):
        # H == L and everything flat: R = 0 + 0 -> 0, SI undefined, ASI holds.
        bars = [bar(10, 10, 10, 10), bar(10, 10, 10, 10), bar(10, 11, 10, 10.5)]
        out = asi(bars)
        assert out[1] is None
        # bar2: dc=0.5, body=0.5, body_prev=0; H-C_prev=1 dominant ->
        # R = 1 - 0.5*0 + 0 = 1; SI = 50*(0.5+0.25+0)/1 = 37.5.
        assert out[2] == pytest.approx(37.5)

    def test_missing_ohlc_is_none(self):
        bars = [bar(10, 12, 10, 11), bar(None, 13, 11, 12.5)]
        assert asi(bars)[1] is None


# ---------------------------------------------------------------------------
# Doc #3 Average Price; crosses #4-#6
# ---------------------------------------------------------------------------


class TestAveragePrice:
    def test_hand_value(self):
        assert average_price([bar(10, 12, 10, 11)]) == [10.75]
        assert average_price([bar(10, 12, 10, None)]) == [None]


FLAT_THEN_STEP = [10.0] * 6 + [11.0] * 6


class TestCrosses:
    def test_ema_cross_marks_first_step_bar(self):
        # Both EMAs sit at 10.0 through idx5. At idx6: EMA3 = 10.5,
        # EMA5 = 10.3333 -> strict up-cross on the first lifted bar.
        r = ema_cross(FLAT_THEN_STEP, 3, 5)
        assert r["signal"][6] == pytest.approx(1.0)
        assert all(v is None for v in r["signal"][:6])
        assert r["fast"][6] == pytest.approx(10.5)
        assert r["slow"][6] == pytest.approx(10.333333, rel=1e-5)

    def test_ma_cross_marks_first_step_bar(self):
        # SMA3 = 10.3333 vs SMA5 = 10.2 at idx6; equal (10.0) before.
        r = ma_cross(FLAT_THEN_STEP, 3, 5)
        assert r["signal"][6] == pytest.approx(1.0)

    def test_ma_ema_cross_tie_then_cross(self):
        # SMA3 = EMA5 = 10.33333 at idx6 (tie -> no marker); at idx7
        # SMA3 = 10.6667 > EMA5 = 10.5556 -> marker lands one bar later.
        r = ma_ema_cross(FLAT_THEN_STEP, 3, 5)
        assert r["signal"][6] is None
        assert r["signal"][7] == pytest.approx(1.0)

    def test_downward_cross(self):
        closes = [11.0] * 6 + [10.0] * 6
        r = ma_cross(closes, 3, 5)
        assert r["signal"][6] == pytest.approx(-1.0)

    def test_short_series_all_none(self):
        r = ema_cross([1.0, 2.0], 3, 5)
        assert r["signal"] == [None, None]
        assert r["fast"] == [None, None]
