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
    ama,
    asi,
    average_price,
    ema_cross,
    highest,
    hl2_series,
    hlc3_series,
    linreg_endpoint,
    linreg_slope,
    lowest,
    ma_channel,
    ma_cross,
    ma_ema_cross,
    ma_hamming,
    ma_multiple,
    ohlc4_series,
    percentrank,
    rma,
    linreg_curve,
    linreg_trend,
    lsma,
    mcginley,
    gmma,
    smma,
    ema_on_valid,
    alligator,
    fractals,
    majority_rule,
    trend_strength,
    zigzag,
    tsi,
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


# ---------------------------------------------------------------------------
# Doc #7 AMA (Kaufman adaptive); #8 Hamming MA; #9 MA Multiple;
# #10 MA Channel; #11 SMMA; #12 LSMA
# ---------------------------------------------------------------------------


class TestAma:
    RAMP = [float(x) for x in range(1, 16)]  # 1..15: ER = 1 -> sc = (2/3)^2 = 4/9

    def test_trending_series_hand_values(self):
        out = ama(self.RAMP, 9)
        # Seeds with the close at idx9 (first bar with 9 prior changes).
        assert out[8] is None
        assert out[9] == pytest.approx(10.0)
        # Perfect trend -> ER = 1 -> fastest sc = (2/3)^2 = 4/9:
        assert out[10] == pytest.approx(10.0 + 4.0 / 9.0)
        # idx11: 10.4444 + (4/9) * (12 - 10.4444) = 11.1358.
        assert out[11] == pytest.approx(11.1358, abs=1e-4)

    def test_flat_series_is_none_not_zero(self):
        # volatility = 0 -> ER undefined -> None (honesty rule).
        out = ama([5.0] * 20, 9)
        assert all(v is None for v in out)

    def test_gap_restarts(self):
        vals = [float(x) for x in range(1, 12)] + [None] + [13.0]
        out = ama(vals, 9)
        assert out[9] == pytest.approx(10.0)
        assert out[11] is None


class TestMaHamming:
    def test_symmetric_window_hand_value(self):
        # p=4: w = [0.08, 0.77, 0.77, 0.08] (cos terms -0.5 at 2pi/3, 4pi/3);
        # (0.08*1 + 0.77*2 + 0.77*3 + 0.08*4) / 1.7 = 2.5.
        out = ma_hamming([1, 2, 3, 4], 4)
        assert out[3] == pytest.approx(2.5)
        assert out[:3] == [None, None, None]

    def test_constant_series_is_exact(self):
        assert ma_hamming([7.0] * 5, 4)[4] == pytest.approx(7.0)


class TestMaMultiple:
    def test_keys_and_values_match_sma(self):
        closes = [float(x) for x in range(1, 31)]
        out = ma_multiple(closes, (20, 50))
        assert set(out) == {"ma_multi_20", "ma_multi_50"}
        # SMA(11..30) = 20.5; the 50-period series never warms up.
        assert out["ma_multi_20"][29] == pytest.approx(20.5)
        assert all(v is None for v in out["ma_multi_50"])


class TestMaChannel:
    def test_percent_bands(self):
        closes = [float(x) for x in range(1, 31)]
        r = ma_channel(closes, 20, 10.0)
        mid = 20.5  # SMA(11..30)
        assert r["middle"][29] == pytest.approx(mid)
        assert r["upper"][29] == pytest.approx(mid * 1.10)
        assert r["lower"][29] == pytest.approx(mid * 0.90)

    def test_warmup(self):
        r = ma_channel([1.0, 2.0, 3.0], 20, 10.0)
        assert all(v is None for v in r["upper"])


class TestSmmaLsma:
    def test_smma_is_rma(self):
        vals = [1.0, 2.5, 3.0, None, 4.0, 5.5, 6.0, 7.0]
        assert smma(vals, 5) == rma(vals, 5)

    def test_smma_hand_seed(self):
        out = smma([1, 2, 3, 4, 5, 6], 4)
        assert out[3] == pytest.approx(2.5)
        assert out[4] == pytest.approx((2.5 * 3 + 5) / 4)

    def test_lsma_matches_linreg_endpoint(self):
        vals = [1.0, 2.0, 3.0, 4.0, 6.0]
        assert lsma(vals, 5)[4] == pytest.approx(5.6)
        assert lsma(vals, 5) == linreg_endpoint(vals, 5)


# ---------------------------------------------------------------------------
# Doc #13 LinReg curve; #15 LinReg trend; #16 McGinley; #17 GMMA
# ---------------------------------------------------------------------------


class TestLinregCurveTrend:
    def test_curve_matches_endpoint(self):
        vals = [1.0, 2.0, 3.0, 4.0, 6.0]
        assert linreg_curve(vals, 5) == linreg_endpoint(vals, 5)

    def test_trend_direction_signs(self):
        up = linreg_trend([float(x) for x in range(1, 11)], 5)
        assert up["direction"][9] == 1.0
        down = linreg_trend([float(x) for x in range(10, 0, -1)], 5)
        assert down["direction"][9] == -1.0
        flat = linreg_trend([4.0] * 8, 5)
        assert flat["direction"][7] == 0.0  # genuine zero: perfectly level

    def test_trend_warmup(self):
        out = linreg_trend([1.0, 2.0, 3.0], 5)
        assert all(v is None for v in out["value"])
        assert all(v is None for v in out["direction"])


class TestMcginley:
    def test_constant_series_is_exact(self):
        out = mcginley([7.0] * 5, 14)
        assert out == [7.0, 7.0, 7.0, 7.0, 7.0]

    def test_hand_value_after_one_step(self):
        # MD_2 = 10 + (11 - 10) / (14 * (11/10)^4) = 10 + 1/20.4974 = 10.0488.
        out = mcginley([10.0, 11.0], 14)
        assert out[0] == 10.0
        assert out[1] == pytest.approx(10.0488, abs=1e-4)

    def test_gap_reseeds(self):
        out = mcginley([10.0, 11.0, None, 12.0], 14)
        assert out[2] is None
        assert out[3] == 12.0  # reseeds with the first valid close after the gap

    def test_insufficient_input(self):
        assert mcginley([], 14) == []
        assert mcginley([None, None], 14) == [None, None]


class TestGmma:
    def test_keys_and_hand_value(self):
        closes = [float(x) for x in range(1, 31)]
        out = gmma(closes)
        assert set(out) == {f"gmma_s{p}" for p in (3, 5, 8, 10, 12, 15)} | {
            f"gmma_l{p}" for p in (30, 35, 40, 45, 50, 60)
        }
        # EMA(3) lag on a unit ramp is (1-a)/a = 1, so the value trails the
        # last close by 1: 30 - 1 = 29.
        assert out["gmma_s3"][29] == pytest.approx(29.0, abs=0.01)
        # EMA(30) warms up exactly on the last of 30 closes (SMA seed 15.5);
        # the 60-period ribbon never does.
        assert out["gmma_l30"][28] is None
        assert out["gmma_l30"][29] == pytest.approx(15.5)
        assert all(v is None for v in out["gmma_l60"])

    def test_matches_ema_on_valid(self):
        closes = [1.0, 2.0, 3.0, None, 5.0, 6.0]
        assert gmma(closes, short=(3,))["gmma_s3"] == ema_on_valid(closes, 3)


# ---------------------------------------------------------------------------
# Doc #18 Majority Rule; #19 Trend Strength; #20 Zig Zag; #21 Alligator;
# #22 Fractal
# ---------------------------------------------------------------------------


def flat_bar(p, date="2026-01-01"):
    return bar(p, p, p, p, date=date)


class TestMajorityRule:
    def test_strong_uptrend_scores_positive(self):
        bars = [bar(100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i) for i in range(30)]
        out = majority_rule(bars)
        assert out["score"][29] is not None
        assert out["score"][29] > 0
        # Short warm-up: only 4 of 7 conditions are computable on 30 bars
        # (SMA50/100 still warming) - disclosed in 'components'.
        assert out["components"][0] is None
        assert out["components"][29] == 4.0

    def test_downtrend_scores_negative(self):
        bars = [bar(130.0 - i, 131.0 - i, 129.0 - i, 130.0 - i) for i in range(30)]
        out = majority_rule(bars)
        assert out["score"][29] < 0

    def test_partial_votes_are_disclosed(self):
        bars = [bar(10, 11, 9, 10), bar(None, 11, 9, 11)]
        out = majority_rule(bars)
        # Only the prior-close condition is computable at idx1: a single +1
        # vote on one component - the count says so.
        assert out["score"][1] == 1.0
        assert out["components"][1] == 1.0
        # idx0 has no prior close and no warm averages: no votes at all.
        assert out["score"][0] is None
        assert out["components"][0] is None


class TestTrendStrength:
    def test_is_tsi_math(self):
        closes = [
            100.0, 101.5, 100.8, 102.3, 103.1, 102.0, 103.8, 104.9, 104.1,
            105.5, 106.2, 105.0, 106.8, 107.4, 106.1, 107.9, 108.5, 107.2,
        ]
        assert trend_strength(closes, 5, 3) == tsi(closes, 5, 3)


class TestZigzag:
    def test_hand_swings_dev10(self):
        bars = [flat_bar(p) for p in (100.0, 104.0, 92.0, 98.0, 108.0)]
        out = zigzag(bars, 10.0)
        # 92 <= 104 * 0.9 confirms the high at idx1; 108 >= 92 * 1.1 confirms
        # the low at idx2; the running high at idx4 is still provisional.
        assert out["price"] == [None, 104.0, 92.0, None, None]
        assert out["confirmed"] == [False, True, True, False, False]

    def test_below_threshold_no_pivots(self):
        bars = [flat_bar(p) for p in (100.0, 105.0, 102.0)]
        out = zigzag(bars, 10.0)
        assert all(v is None for v in out["price"])
        assert not any(out["confirmed"])

    def test_gap_closes_skipped(self):
        bars = [flat_bar(100.0), flat_bar(104.0), flat_bar(None), flat_bar(92.0)]
        out = zigzag(bars, 10.0)
        assert out["price"][1] == 104.0


class TestAlligator:
    def test_constant_market(self):
        bars = [flat_bar(7.0) for _ in range(25)]
        out = alligator(bars)
        # HL2 = 7 throughout; SMMA(p) seeds at idx p-1 and appears `shift`
        # bars later: lips (5,3) first at idx7, teeth (8,5) at idx12,
        # jaw (13,8) at idx20.
        assert out["lips"][6] is None and out["lips"][7] == pytest.approx(7.0)
        assert out["teeth"][11] is None and out["teeth"][12] == pytest.approx(7.0)
        assert out["jaw"][19] is None and out["jaw"][20] == pytest.approx(7.0)

    def test_hand_recursion_on_ramp(self):
        bars = [flat_bar(float(x)) for x in range(1, 31)]
        out = alligator(bars)
        # lips: SMMA(5) on 1..30: seed idx4 = 3.0; idx5 = (3*4 + 6)/5 = 3.6;
        # idx6 = (3.6*4 + 7)/5 = 4.28; shifted 3 -> lips[9] = 4.28.
        assert out["lips"][9] == pytest.approx(4.28)


class TestFractals:
    def test_five_bar_patterns(self):
        bars = [bar(2, 1.0, 5.0, 2), bar(2, 2.0, 4.0, 2), bar(2, 3.0, 3.0, 2),
                bar(2, 2.0, 4.0, 2), bar(2, 1.0, 5.0, 2)]
        out = fractals(bars)
        assert out["high"][2] == 3.0
        assert out["low"][2] == 3.0
        assert out["confirmed"][2] is True
        assert out["confirmed"][1] is False

    def test_strict_inequality_rejects_ties(self):
        bars = [bar(2, 2.0, 3.0, 2), bar(2, 2.0, 3.0, 2), bar(2, 2.0, 3.0, 2),
                bar(2, 2.0, 3.0, 2), bar(2, 2.0, 3.0, 2)]
        out = fractals(bars)
        assert all(v is None for v in out["high"])
        assert all(v is None for v in out["low"])

    def test_unconfirmable_tail_and_head(self):
        # n=4 with wings=2: no centre bar has two neighbours on both sides.
        bars = [bar(2, 3.0, 1.0, 2), bar(2, 2.0, 2.0, 2), bar(2, 1.0, 3.0, 2),
                bar(2, 2.0, 2.0, 2)]
        out = fractals(bars)
        assert all(v is None for v in out["high"])
        assert all(v is None for v in out["low"])

    def test_outside_bar_is_both(self):
        bars = [bar(2, 2.0, 2.0, 2), bar(2, 3.0, 3.0, 2), bar(2, 5.0, 1.0, 2),
                bar(2, 3.0, 3.0, 2), bar(2, 2.0, 2.0, 2)]
        out = fractals(bars)
        assert out["high"][2] == 5.0
        assert out["low"][2] == 1.0
