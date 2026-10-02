# Chart fixes — progress (A–F, H, J)

Branch: `fix/chart-indicators-colors`. Working symbol: **AHL** (verified).

## A. Timeframe aggregation (doc B)

| Item | Status | Notes |
| --- | --- | --- |
| A1 Weekly aggregation (Sun-Thu, Mon-Fri) | ✅ done | `_aggregate_ohlcv` with `week_start` param (sunday\|monday), tests pass |
| A2 Monthly aggregation (calendar month) | ✅ done | Groups by YYYY-MM, tests pass |
| A3 Auto timeframe per range (1W→D, 1M→D, 3M→W, 6M→W, YTD→W, 1Y→W, ALL→W) | ✅ done | `_auto_timeframe` function, marked `spec_status: unverified` |
| A4 Bar label mode (last_session \| period_start) | ✅ done | `bar_label_mode` param, default `period_start` inferred from AHL 3M labels |
| A5 Timeframe tests | ✅ done | 22 tests in `test_timeframe.py` (normal week, holiday, month split, partial week, SMA/RSI warmup, VWMA, live quote, invalid tf) |

## B. Frontend timeframe selector

| Item | Status | Notes |
| --- | --- | --- |
| B1 Auto\|D\|W\|M selector in toolbar | ✅ done | Persisted per symbol in localStorage (`chart-tf:{symbol}`) |
| B2 Auto-resolved label shown | ✅ done | Selector shows "Auto (W)" etc. |
| B3 Week start selector (when tf=W) | ✅ done | Sunday\|Monday dropdown, only visible for Weekly |
| B4 Bar label mode selector | ✅ done | Last session \| Period start dropdown |
| B4 Aggregated-candle tooltip (period dates, OHLC, change%, volume) | ✅ done | Tooltip uses aggregated series data |
| B5 Legend chips show warm_up reason | ✅ done | Uses backend `warm_up` field per indicator |
| B6 Right padding limited | ✅ done | `rightOffset: 1` on timeScale |
| B7 Legend space reserved | ✅ done | Legend rendered outside chart in card toolbar |
| B8 y-domain contains all visible high/low | ✅ done | Only candle series participates in autoscale |

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
| F1 SMA20/EMA20/WMA20/MA-EMA Cross start first candle | ⏳ pending | API returns 14/14 non-null on 3M weekly, 62/62 on 3M daily. Awaiting NEPSE tooltip confirmation. |
| F2 3M weekly auto-resolves correctly | ✅ verified | `tf=auto` → `applied: "W"` for 3M range |
| F3 No empty right area | ⏳ pending | `rightOffset: 1`, no extra space. Awaiting visual confirmation. |
| F4 Nothing clipped/covered | ⏳ pending | Overlays use `autoscaleInfoProvider: () => null`. Awaiting visual confirmation. |

## H. Health sweep (AHL, ANLB, NHPC, BNT on D/W/M)

| Item | Status | Notes |
| --- | --- | --- |
| H1 Daily timeframe | ✅ done | All 100 tokens healthy for all 4 symbols |
| H2 Weekly timeframe | ⚠️ expected | 8 tokens flagged (insufficient weekly bars for long-lookback indicators) |
| H3 Monthly timeframe | ⚠️ expected | 63+ tokens flagged (insufficient monthly bars) |
| H4 Results written to docs/indicator-health.md | ✅ done | Grouped by symbol and timeframe |

## J. Docs & progress

| Item | Status | Notes |
| --- | --- | --- |
| J1 chart-fixes-progress.md updated | ✅ done | This file |
| J2 indicator-health.md updated | ✅ done | Includes D/W/M results |
| J3 All backend tests pass | ✅ done | 783 passed, 8 skipped |
| J4 Frontend builds clean | ✅ done | `npm run build` ✓ |

## Unverified settings (spec_status: unverified)

1. **Auto timeframe table**: 1W→D, 1M→D, 3M→W, 6M→W, YTD→W, 1Y→W, ALL→W
2. **Week start default**: `week_start=monday` (inferred from NEPSE AHL 3M labels: Mon 6 Jul, 20 Jul, 3 Aug, 17 Aug, 14 Sep, 28 Sep; NOT confirmed by NEPSE)
3. **Monthly (M) timeframe**: Manual only (not in Auto table)
4. **Bar label mode default**: `period_start` (inferred from NEPSE AHL 3M labels; NOT confirmed by NEPSE)
5. **Gap-day colour rule**: Default `prev_close` (unverified) — setting visible in toolbar (Highcharts normally colours by close vs open)
6. **Resize behaviour**: Unknown — NEPSE may or may not auto-switch D/W/M on resize

## Open items for user (nothing marked verified until these are provided)

1. Paste NEPSE's daily table for AHL 2026-06-30→09-30 for `/dev/chart-parity?symbol=AHL&range=3M` row-by-row parity
2. Provide three NEPSE weekly AHL candle hover tooltips for aggregation verification
3. Confirm NEPSE's gap-day colour rule (prev_close vs open)