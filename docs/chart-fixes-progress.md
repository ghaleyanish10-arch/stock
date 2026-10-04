# Chart fixes — progress (A–F, H, J)

Branch: `fix/chart-indicators-colors`. Working symbol: **AHL** (verified).

## A. Timeframe aggregation (doc B)

| Item | Status | Notes |
| --- | --- | --- |
| A1 Weekly aggregation (Sun-Thu, Mon-Fri) | ✅ done | `_aggregate_ohlcv` with `week_start` param (sunday\|monday); weeks are Mon-Sun (monday) or Sun-Sat (sunday); trading days Sun-Thu; tests pass |
| A2 Monthly aggregation (calendar month) | ✅ done | Groups by YYYY-MM; period_start = 1st of month; tests pass |
| A3 Auto timeframe per range (1W→D, 1M→D, 3M→W, 6M→W, YTD→W, 1Y→W, ALL→W) | ✅ done | `_auto_timeframe` function, marked `spec_status: unverified` |
| A4 Bar label mode (last_session \| period_start) | ✅ done | `period_start` = CALENDAR start (Mon for week_start=monday, Sun for sunday, 1st for monthly), NOT first trading session; `last_session` = last trading day in bucket; tests pass |
| A5 Timeframe tests | ✅ done | **33 tests** in `test_timeframe.py`: week mapping (14), weekly OHLCV (4), label modes (2), Mon-Fri week (4), monthly (2), SMA/RSI warmup (3), parity (1), warmup reason (1), panel (1), VWMA (1), live quote (2), invalid tf (1) |

## B. Frontend timeframe selector

| Item | Status | Notes |
| --- | --- | --- |
| B1 Auto\|D\|W\|M selector in toolbar | ✅ done | Persisted per symbol in localStorage (`chart-tf:{symbol}`) |
| B2 Auto-resolved label shown | ✅ done | Selector shows "Auto (W)" etc. |
| B3 Week start selector (when tf=W) | ✅ done | Sunday\|Monday dropdown, only visible for Weekly |
| B4 Bar label mode selector | ✅ done | Last session \| Period start dropdown; default `period_start` |
| B5 Aggregated-candle tooltip | ✅ done | Shows "Week of Mon 21 Sep, sessions 22 Sep to 24 Sep" using `first_session_dates` / `last_session_dates` |
| B6 Legend chips show warm_up reason | ✅ done | Uses backend `warm_up` field per indicator |
| B7 Right padding limited | ✅ done | `rightOffset: 1` on timeScale |
| B8 Legend space reserved | ✅ done | Legend rendered in card toolbar (outside chart canvas) |
| B9 y-domain contains all visible high/low | ✅ done | Only candle series participates in autoscale (`autoscaleInfoProvider: () => null` on overlays) |

## C. Live candle for W/M

| Item | Status | Notes |
| --- | --- | --- |
| C1 Live candle updates current period for W/M | ✅ done | Merges live quote into last aggregated bar |
| C2 Live candle disabled when tf≠D | ✅ done | Only updates current period, doesn't append new bar |

## D. Aggregated candle colour rule

| Item | Status | Notes |
| --- | --- | --- |
| D1 Colour = close vs previous period close | ✅ done | Uses `changeRef` with previous aggregated close |

## E. price_mode.requested consumers

| Item | Status | Notes |
| --- | --- | --- |
| E1 All consumers updated (adjusted\|as_traded) | ✅ done | Backend reports `price_mode` honestly; frontend shows reason when differs |

## F. Verification on AHL

| Item | Status | Notes |
| --- | --- | --- |
| F1 SMA20/EMA20/WMA20/MA-EMA Cross start first candle | ⏳ pending | API returns 13/13 non-null on 3M weekly, 62/62 on 3M daily. Awaiting NEPSE tooltip confirmation. |
| F2 3M weekly auto-resolves correctly | ✅ verified | `tf=auto` → `applied: "W"` for 3M range |
| F3 No empty right area | ⏳ pending | `rightOffset: 1`, no extra space. Awaiting visual confirmation. |
| F4 Nothing clipped/covered | ⏳ pending | Overlays use `autoscaleInfoProvider: () => null`. Awaiting visual confirmation. |

## H. Health sweep (AHL, ANLB, NHPC, BNT on D/W/M)

| Item | Status | Notes |
| --- | --- | --- |
| H1 Daily timeframe | ✅ done | All 108 tokens healthy for all 4 symbols (batch-B tokens included since the parser fix) |
| H2 Weekly timeframe | ✅ done | 108/108 healthy; long-lookback all-nulls are reported warm-ups (short weekly archive), not breakage |
| H3 Monthly timeframe | ✅ done | 108/108 healthy; same warm-up rule (AHL has only ~14 monthly buckets) |
| H4 Results written to docs/indicator-health.md | ✅ done | Regenerated 2026-10-04; script sweeps all 108 tokens (comment-stripped union regex) |

## J. Docs & progress

| Item | Status | Notes |
| --- | --- | --- |
| J1 chart-fixes-progress.md updated | ✅ done | This file |
| J2 indicator-health.md updated | ✅ done | Includes D/W/M results |
| J3 All backend tests pass | ✅ done | **789 passed, 8 skipped** (791 collected) |
| J4 Frontend builds clean | ✅ done | `npm run build` ✓ |

## Unverified settings (spec_status: unverified)

1. **Auto timeframe table**: 1W→D, 1M→D, 3M→W, 6M→W, YTD→W, 1Y→W, ALL→W
2. **Week start default**: `week_start=monday` (inferred from NEPSE AHL 3M labels: Mon 6 Jul, 20 Jul, 3 Aug, 17 Aug, 14 Sep, 28 Sep; **NOT confirmed by NEPSE**)
3. **Bar label mode default**: `period_start` (inferred from NEPSE AHL 3M labels; **NOT confirmed by NEPSE**)
4. **Gap-day colour rule**: Default `prev_close` (unverified) — selector visible in toolbar (Highcharts normally colours by close vs open)
5. **Resize behaviour**: Unknown — NEPSE may/may not auto-switch D/W/M on resize

## Open items for user (nothing marked verified until these are provided)

1. Paste NEPSE's daily table for AHL 2026-06-30→09-30 for `/dev/chart-parity?symbol=AHL&range=3M` row-by-row parity
2. Provide three NEPSE weekly AHL candle hover tooltips for aggregation verification
3. Confirm NEPSE's gap-day colour rule (prev_close vs open)

## K. "Use all indicators" + fix everything not shown (2026-10-04)

| Item | Status | Tests | Commit |
| --- | --- | --- | --- |
| K1 `compare` token dead (Query param shadowed the fn → TypeError, empty series, no reason) | ✅ fixed | contract: compare-with-partner regression (pins tf=D) | d025969 |
| K2 `technical_ratings` drew a single invisible point | ✅ fixed | contract draws-across-window + 3 batch-B series tests (251/260 non-null on fixture, last bar == single-bar fn) | d025969 |
| K3 compare family dropped first bucket + holiday-Monday weeks on W/M (label-vs-session-date mismatch) | ✅ fixed | hand-computed weekly rebase 100×107/102 = 104.90196 | d025969 |
| K4 health sweep truncated at 100 tokens (`;` inside a comment) | ✅ fixed | contract parser strips comments (≥105 tokens) | d025969 |
| K5 sweep flagged reported warm-ups as broken | ✅ fixed | sweep consults payload `warm_up` reasons like the contract test | d025969 |
| K6 picker capped at 12 indicators ("use all the indicators") | ✅ fixed | All/None buttons; 108/108 selectable; live AHL: 8 panes / 171 series | d9ffd19 |
| K7 cross `*_signal` events never drawn | ✅ fixed | arrowUp/arrowDown markers on the price pane for ema/ma/ma_ema cross | d9ffd19 |

## L. Indicator working/not-working report (2026-10-04)

Full per-token detail: `docs/indicator-health.md` (108 tokens × AHL/ANLB/NHPC/BNT × D/W/M). Summary:

- **Working and drawn (108/108 tokens):** every token now returns HTTP 200 with either non-null series or an honest reason. Daily timeframe: 0 flags across all 4 symbols. The 8 batch-B tokens (median_price, typical_price, price_channel, correlation_log, ratio, spread, compare, technical_ratings) were invisible until this session — two were genuinely broken (K1, K2), the sweep missed the rest.
- **Correctly not drawn (warm-up, by design):** long-lookback indicators on W/M where the archive is shorter than the lookback — e.g. AHL monthly (~14 buckets) leaves SMA20+, RSI, MACD, BB null, and weekly leaves TEMA/linreg_curve_100 null. The legend shows the backend's warm-up reason; values are never faked as zero.
- **Not applicable by design (1):** `vol_index` — NEPSE publishes no options/derivatives data; backend reports it disabled rather than faking values.
- **Needs a partner (5):** correlation, correlation_log, ratio, spread, compare — work with `compare=SYM` (the sweep pairs AHL↔NHPC); they carry a disabled reason without one.
- **Events, not lines (3):** ema_cross/ma_cross/ma_ema_cross `*_signal` now draw as arrows (K7); the fast/slow lines were always drawn.
- **Shape-dependent (3):** fractal_low/hi and zigzag need real local extremes; on monotone fixture legs they are legitimately empty (live data confirms they populate).