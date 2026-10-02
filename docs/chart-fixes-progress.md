# Chart fixes — progress (A–F)

Branch: `fix/chart-indicators-colors`. Working symbol: **ANLB** (close 4,919.70 on
2026-10-01, O 4,935 H 4,935 L 4,821 — matches the user's NEPSE page).

## A. Diagnose with evidence

| Item | Status | Notes |
| --- | --- | --- |
| A1 Indicator bug root cause | ✅ done | Overlays shared the candle price scale (`priceScaleId:"right"`), so autoscale stretched to overlay extremes (pivot_r3 max 8,520) while candles live 4,800–4,935 → clipping + single-point dashes. API payload itself was correct (`sma_20` len 62, non-null 43, last 4,971.335). |
| A2 Archive data check | ✅ done | 62 rows 2026-06-30→09-30: 0 dupes, 0 nulls, 0 geometry violations, 0 zero-vol, 0 gaps >4d. 8 ±10% flags are real ±15% circuit moves (6,796.5→5,777.1 = −15.0% exactly). Fri/Sat flags are false positives — NEPSE trades Sun–Thu, rows are Mon–Fri. Tall July wicks (2026-07-17 H 7,560 / L 6,120, vol 267) are real thin-market data. No repairs needed. |
| A3 Colour rule traced | ✅ done | Red-positive header came from flipped `--up`/`--down` vars, not per-candle logic. |

Row-by-row NEPSE parity still needs the user's pasted daily table (open question in final report).

## B. Candle chart matches NEPSE

| Item | Status | Commit | Notes |
| --- | --- | --- | --- |
| B1 basis=as_traded/adjusted | ✅ done | 953f5d4 | Query param on `/chart/{symbol}`, wired into honest `price_mode` report; card select "Prices". |
| B2 Data defects | ✅ none found | — | A2 clean; no repairs needed. |
| B3 Default 3M, full view, no clipping | ✅ done | 5d76671 | `fitContent()` on load; candles-only autoscale (overlays use `autoscaleInfoProvider:()=>null`); default range 3M. Verified live: axis 4,800–7,560 with zero clipping. |
| B4 Rendering parity (body/wick, ordinal x, ranges, From/To, volume pane, tooltip) | ✅ done | 5d76671 | Trading-day x-axis (lightweight-charts is ordinal); RANGES 1W…ALL + custom dates; volume pane same-rule-coloured, hideable; OHLCV tooltip with change % and rule-based colour. |
| B5 Parity helper page | ✅ done | ddfb3c9 | `/dev/chart-parity?symbol=ANLB&range=3M`: renders the exact payload the chart shows as a table, plus a paste-box for NEPSE's daily table with per-row diff (green match / red mismatch with NEPSE−ours delta / grey missing). Parser tolerates commas, pipes, dd/mm/yyyy. Live-verified: exact rows match (green), a hand-wrong close flags MISMATCH with delta −5.00, out-of-window rows flagged, header lines ignored. |
| B6 Acceptance vs NEPSE table | ⏳ blocked on user | — | Values match the page the user quoted (close 4,919.70 / O 4,935 / H 4,935 / L 4,821). |
| B7 Live-merge phantom bar | ✅ done | this commit | Found via B5: `_live_bar` re-dated the poller's stale quote to "today", painting a phantom 2026-10-02 bar (a Friday) duplicating the 10-01 session (O 4,934.80, V 945) that NEPSE's own chart lacks. Fix: live merge only when NEPSE reports the market OPEN (same gate the card's header uses); status unreadable ⇒ no live bar. Verified: `dates[-1]` 2026-10-02 → 2026-10-01, `live.market_open: false` + honest note. Pinned by 3 new contract tests. |

## C. Green up / red down everywhere

| Item | Status | Commit | Notes |
| --- | --- | --- | --- |
| C1 CSS vars light+dark, setting | ✅ done | fd7f167 | `--up` green / `--down` red (light+dark); `[data-trend="nepse"]` restores red-up; topbar switch via `useTrendPalette()`, stored `sa.trend-palette`. |
| C2 One colour function + documented rule | ✅ done | fd7f167 | `changeColor(delta, pal)` for body+wick+volume; rule setting `prev_close` (default) vs `open` in `frontend/src/colorRule.ts`, per browser, live re-colour on change. Contract pinned by `frontend/scripts/check-color-rule.mjs` (18 hand-computed cases incl. gap-day disagreements) — logic lives in `frontend/src/chartColors.ts`. |
| C3 Applied everywhere | ✅ done | fd7f167 | Header, chart, tooltip, volume bars read the vars. Existing table/heatmap classes already consume `--up/--down`, so they follow automatically. |
| C4 NEPSE rule observation | ⏳ needs user | — | Default `prev_close` kept; user to confirm which rule NEPSE's chart uses on gap days. |

## D. Indicators plot immediately, legend, live

| Item | Status | Commit | Notes |
| --- | --- | --- | --- |
| D1 Immediate plot | ✅ done | 5d76671 | Verified live: RSI 14 (pane) and Median Price (overlay) drew instantly with legend values. |
| D2 Legend chips with values + statuses | ✅ done | 5d76671 | Latest values, remove ×, status reasons: warm-up / needs-N-bars / disabledByDesign / backend reason (lookup by `def.key` AND series key). |
| D3 Provenance (missing ≠ zero) | ✅ done | 5d76671 | Warm-up is null; reasons surfaced in legend. |
| D4 Live updates / market closed | ✅ done | 5d76671 | Header gated on `market.overview().status.is_open` — poller's stale cache no longer claims LIVE at 10pm; "market closed" badge + note. Live candle appends while open. |
| D5 Token caps | ✅ done | 5d76671 | MAX_ACTIVE=12 with visible notice; dev `window.__tcChart` for the parity page. |

## E. Indicator health sweep

| Item | Status | Commit | Notes |
| --- | --- | --- | --- |
| E1 scripts/indicator_health.py | ✅ done | f28e0d3 | Sweeps every picker token × 3 symbols (ANLB user's, NHPC liquid, BNT thin): HTTP status, series shape, null fraction, registry match. Writes `docs/indicator-health.md`; exit ≠ 0 on any broken token. |
| E2 Fix failing tokens | ✅ done | 5d76671 + 5cceb27 + f28e0d3 | `mfi` had no backend handler (silent dead button) → added. 8 backend tokens missing from picker → added. `roc`/`vwma` imported-but-unused (NameError → 500, 5cceb27); same class for `vortex` (f28e0d3). Sweep now reports 300/300 rows healthy, 0 registry mismatches; `vol_index`/compare-family are `not_applicable` with provenance reasons (healthy by design). |
| E3 Registry pytest | ✅ done | a1447c4 | `backend/tests/test_chart_contract.py`: every picker token must serve data **or** return a stated reason (fail-before evidence: would have caught mfi/roc/vwma/vortex), warm-up nulls, SMA hand math, ranges 1W/YTD/custom/400, basis honesty, OHLC geometry (max high 262.0 by hand), weekday sessions, no dupes. 12 passed. |
| E4 Frontend↔backend token smoke check | ✅ done | f28e0d3 | The sweep cross-checks picker tokens against the backend contract: 300/300 healthy, 0 mismatches. Also pinned in pytest (E3) so a future dropped handler fails CI instead of silently 500-ing. |

## F. Tests, verification, report

| Item | Status | Commit | Notes |
| --- | --- | --- | --- |
| F1 Parity/geometry/colour tests | ✅ done | fd7f167 + a1447c4 + d66646d | Colour: `node scripts/check-color-rule.mjs` ✓ 18/18 (gap-day disagreements both directions). Backend: contract pytest 15/15 after the live-gate tests (d66646d). Parity page live-verified against the real payload (B5). |
| F2 Full backend tests + npm build | ✅ done | this commit | Full suite: **756 passed, 8 skipped** (baseline before this branch's chart work: 717 passed, 8 skipped; +39). One transient network-flaky live-NEPSE test (test_brokers_registry_only) failed once and passed on re-run and in isolation — unrelated to chart changes. `npx tsc -b` clean, `npm run build` ✓, colour-rule script ✓. |
| F3 Manual verification | ✅ done | — | Verified live in the browser: full-range no-clip view; 1W = 5 sessions and YTD = 176 sessions (matches API); basis=adjusted shows the honest no-op reason; colour-rule flip persists (`chart-color-rule`) and rebuilds the chart; 12-indicator sweep (SMA/EMA/BB/PSAR/Supertrend/Ichimoku/RSI/MACD/TRIX/MFI/Stochastic/Median) plots instantly with legend values; cap notice at 12; series enumeration proves every overlay is autoscale-gated (only candles autoscale — supertrend max 7,914 does not stretch the axis); market-closed badge; console clean. |
| F4 Final report | ✅ done | — | See the chat report: A–F table with commit hashes, before/after numbers, and the two open questions (NEPSE daily table; NEPSE colour rule on gap days). |

## Open questions for the user

1. Paste NEPSE's daily table for ANLB 2026-06-30→09-30 for row-by-row parity proof.
2. On gap days, does NEPSE colour by close-vs-prev-close (our default) or close-vs-open?
