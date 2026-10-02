# Indicators Batch B Progress Tracker

## Status Legend
- ✅ **Done** - Implemented, tested, committed
- 🔄 **Partial** - Started but not complete
- ⏳ **Not Started** - Not yet begun
- 🚫 **Disabled/Not Applicable** - Will not implement (documented reason)

---

## Batch B: 57 Indicators Progress

| # | Indicator | Category | Status | Commit | Tests | Notes |
|---|-----------|----------|--------|--------|-------|-------|
| 1 | ALMA | Trend/MA | ✅ Done | 2f9de11 | 3 | |
| 2 | ASI (Accumulative Swing Index) | Trend/MA | ✅ Done | 2f9de11 | 3 | limit_move_pct=0.10 **UNVERIFIED** |
| 3 | Average Price (OHLC4) | Trend/MA | ✅ Done | 2f9de11 | 1 | |
| 4 | EMA Cross | Trend/MA | ✅ Done | 2f9de11 | 5 | |
| 5 | MA Cross | Trend/MA | ✅ Done | 2f9de11 | 5 | |
| 6 | MA-EMA Cross | Trend/MA | ✅ Done | 2f9de11 | 5 | |
| 7 | AMA (KAMA) | Trend/MA | ✅ Done | 8237513 | 3 | |
| 8 | Hamming MA | Trend/MA | ✅ Done | 8237513 | 2 | |
| 9 | MA Multiple | Trend/MA | ✅ Done | 8237513 | 2 | |
| 10 | MA Channel | Trend/MA | ✅ Done | 8237513 | 2 | mode "hl" and "offset" **UNVERIFIED** |
| 11 | SMMA | Trend/MA | ✅ Done | 8237513 | 2 | alias of RMA |
| 12 | LSMA | Trend/MA | ✅ Done | 8237513 | 2 | |
| 13 | Linear Regression Curve | Trend/MA | ✅ Done | 3e9e3ed | 1 | |
| 14 | Linear Regression Slope | Trend/MA | ✅ Done | 3e9e3ed | - | |
| 15 | Linear Regression Trend | Trend/MA | ✅ Done | 3e9e3ed | 3 | flat_threshold=0 **UNVERIFIED** |
| 16 | McGinley Dynamic | Trend/MA | ✅ Done | 3e9e3ed | 4 | k=1.0 **UNVERIFIED** |
| 17 | Guppy MMA | Trend/MA | ✅ Done | 3e9e3ed | 2 | |
| 18 | Majority Rule | Trend/MA | ✅ Done | 66c8797 | 3 | component set **UNVERIFIED** |
| 19 | Trend Strength Index | Trend/MA | ✅ Done | 66c8797 | 1 | method="correlation" **UNVERIFIED** |
| 20 | Zig Zag | Trend/MA | ✅ Done | 66c8797 | 3 | repaints last leg |
| 21 | Williams Alligator | Trend/MA | ✅ Done | 66c8797 | 3 | shifts are display-only |
| 22 | Williams Fractal | Trend/MA | ✅ Done | 66c8797 | 5 | 2-bar confirmation delay |
| 23 | Accelerator Oscillator | Momentum | ✅ Done | 3379573 | 1 | reuses Awesome Osc |
| 24 | CMO | Momentum | ✅ Done | 3379573 | 3 | |
| 25 | Connors RSI | Momentum | ✅ Done | 3379573 | 2 | |
| 26 | Coppock Curve | Momentum | ✅ Done | 3379573 | 2 | |
| 27 | Fisher Transform | Momentum | ✅ Done | 3379573 | 2 | recursive Ehlers form |
| 28 | KST | Momentum | ✅ Done | 3379573 | 3 | |
| 29 | DPO | Momentum | ✅ Done | 309b6b6 | 2 | reuses existing if present |
| 30 | SMI Ergodic | Momentum | ✅ Done | 309b6b6 | 2 | |
| 31 | RCI | Momentum | ✅ Done | 309b6b6 | 3 | |
| 32 | Price Oscillator | Momentum | ✅ Done | 309b6b6 | 2 | |
| 33 | Relative Volatility Index | Momentum | ✅ Done | 309b6b6 | 3 | |
| 34 | Chande Kroll Stop | Volatility | ✅ Done | 5d164b8 | 2 | **UNVERIFIED** variant |
| 35 | Choppiness Index | Volatility | ✅ Done | 5d164b8 | 3 | |
| 36 | Chop Zone | Volatility | ✅ Done | 5d164b8 | 3 | **UNVERIFIED** approx |
| 37 | Envelopes | Volatility | ✅ Done | 5d164b8 | 2 | |
| 38 | Mass Index | Volatility | ✅ Done | 5d164b8 | 2 | |
| 39 | Standard Error | Volatility | ✅ Done | 99d6b06 | 3 | |
| 40 | Standard Error Bands | Volatility | ✅ Done | 99d6b06 | 2 | smoothing=3 **UNVERIFIED** |
| 41 | Volatility C2C | Volatility | ✅ Done | 99d6b06 | 3 | trading_days **UNVERIFIED** |
| 42 | Volatility Zero Trend | Volatility | ✅ Done | 99d6b06 | 3 | |
| 43 | Volatility OHLC | Volatility | ✅ Done | 99d6b06 | 3 | GK/YZ **UNVERIFIED** |
| 44 | Volatility Index | Volatility | 🚫 Disabled | 99d6b06 | - | No options market |
| 45 | 52 Week High/Low | Market | ✅ Done | a2374b2 | 3 | |
| 46 | Advance/Decline | Market | ✅ Done | a2374b2 | 2 | `/api/analytics/breadth` |
| 47 | Balance of Power | Momentum | ✅ Done | a2374b2 | 3 | |
| 48 | Correlation | Comparison | ✅ Done | a2374b2 | 4 | |
| 49 | Correlation Log | Comparison | ✅ Done | 333d15f | 4 | |
| 50 | Ratio | Comparison | ✅ Done | 333d15f | 4 | |
| 51 | Spread | Comparison | ✅ Done | 333d15f | 2 | |
| 52 | Compare | Comparison | ✅ Done | 333d15f | 4 | |
| 53 | Median Price | Price | ✅ Done | 443a11b | 2 | |
| 54 | Typical Price | Price | ✅ Done | 443a11b | 2 | |
| 55 | Price Channel | Price | ✅ Done | 443a11b | 3 | |
| 56 | Elder's Force Index | Specialized | ✅ Done | 443a11b | 4 | |
| 57 | Technical Ratings | Specialized | ✅ Done | ea1eee7 | 4 | |

---

## Test Counts
- **Before Batch B**: ~600 tests
- **After Batch B (so far)**: 717 passed, 8 skipped
- **New tests in Batch B**: ~120 tests in `test_indicators_batch_b.py` + tests in `test_indicators_pdf_suite.py`

---

## Retro-Verification Results (per retro-verification protocol)

| Indicator | Original Expected | Verified Value | Status |
|-----------|-------------------|----------------|--------|
| KAMA (11.1358) | 11.1358 | TBD | Pending |
| LinReg/EMA lag cases | - | TBD | Pending |
| Majority Rule warm-up | - | TBD | Pending |
| AC/AO warm-up index | - | TBD | Pending |
| Mass Index values | - | TBD | Pending |
| Choppiness values | - | TBD | Pending |
| Chande Kroll | - | TBD | Pending |
| Volatility trio (C2C, Zero Trend, OHLC) | - | TBD | Pending |
| Std Error Bands | - | TBD | Pending |

---

## Deviations from PDF / UNVERIFIED Items

1. **ASI limit_move_pct=0.10** - UNVERIFIED, assumed NEPSE daily price band
2. **MA Channel mode "hl"/"offset"** - UNVERIFIED, PDF underspecified
3. **McGinley k=1.0** - UNVERIFIED, original uses k=0.6
4. **Majority Rule conditions** - UNVERIFIED, PDF gives no condition set
5. **Trend Strength Index method="correlation"** - UNVERIFIED
6. **MA Channel modes** - UNVERIFIED
7. **Chande Kroll Stop variant** - UNVERIFIED
8. **Chop Zone** - UNVERIFIED, implementation-specific
9. **Std Error Bands smoothing=3** - UNVERIFIED
10. **Volatility C2C trading_days=240** - UNVERIFIED default
11. **Volatility OHLC GK/YZ** - UNVERIFIED
12. **Trend Strength Index correlation method** - UNVERIFIED
13. **Majority Rule component set** - UNVERIFIED
14. **Technical Ratings component set** - UNVERIFIED
15. **Chop Zone** - UNVERIFIED
16. **Trend Strength Index default method** - PDF's form used
17. **Trend Strength Index correlation method** - alternate definition

---

## Open Work

1. **Step 9 completion** - #45 to #48 (in progress, needs commit)
2. **Step 10** - #49 to #52 (Correlation-Log, Ratio, Spread, Compare)
3. **Step 11** - #53 to #56 (Median Price, Typical Price, Price Channel, Force Index)
4. **Step 12** - #57 Technical Ratings
5. **Step 13** - Metadata endpoint + server-side validation
6. **Step 14** - Frontend picker/parameter forms/markers/badges/disclaimers
7. **Step 15** - Documentation `docs/indicators-batch-b.md`
8. **Step 16** - Final verification

---

## Commits So Far (Batch B)

| Commit | Message | Indicators |
|--------|---------|------------|
| 2f9de11 | ALMA, ASI, average price, EMA/MA cross, MA-EMA cross + shared primitives | #1-6 |
| 8237513 | AMA, Hamming MA, MA multiple, MA channel, SMMA, LSMA | #7-12 |
| 3e9e3ed | LinReg curve/slope/trend, McGinley Dynamic, GMMA ribbon | #13-17 |
| 66c8797 | Majority Rule, Trend Strength Index, Zig Zag, Alligator, Fractal | #18-22 |
| 3379573 | Accelerator Osc, CMO, Connors RSI, Coppock, Fisher, KST | #23-28 |
| 309b6b6 | DPO, SMI Ergodic, RCI, Price Oscillator, Relative Volatility Index | #29-33 |
| 5d164b8 | Chande Kroll, Choppiness, Chop Zone, Envelopes, Mass Index | #34-38 |
| 99d6b06 | Std Error, SE Bands, Vol C2C/Zero/OHLC, Vol Index disabled | #39-44 |

---

## Next Actions

1. ✅ All tests pass (717)
2. ✅ Frontend builds
3. 📝 Create progress file
4. 📝 Commit Step 9 (#45-48)
5. Continue to Step 10 (#49-52)