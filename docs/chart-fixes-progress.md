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
| B5 Parity helper page | ⬜ todo | — | `/dev/chart-parity` planned. |
| B6 Acceptance vs NEPSE table | ⏳ blocked on user | — | Values match the page the user quoted (close 4,919.70 / O 4,935 / H 4,935 / L 4,821). |

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
| E3 Registry pytest | ✅ done | this commit | `backend/tests/test_chart_contract.py`: every picker token must serve data **or** return a stated reason (fail-before evidence: would have caught mfi/roc/vwma/vortex), warm-up nulls, SMA hand math, ranges 1W/YTD/custom/400, basis honesty, OHLC geometry (max high 262.0 by hand), weekday sessions, no dupes. 12 passed. |
| E4 Frontend↔backend token smoke check | ✅ done | f28e0d3 | The sweep cross-checks picker tokens against the backend contract: 300/300 healthy, 0 mismatches. Also pinned in pytest (E3) so a future dropped handler fails CI instead of silently 500-ing. |

## F. Tests, verification, report

| Item | Status | Commit | Notes |
| --- | --- | --- | --- |
| F1 Parity/geometry/colour tests | 🔄 partial | this commit | Colour: `node scripts/check-color-rule.mjs` ✓ 18/18. Backend registry/geometry/parity pytest ✓ 12/12 (this commit). Remaining: B5 parity page. |
| F2 Full backend tests + npm build | 🔄 partial | this commit | `npx tsc -b` clean, `npm run build` ✓ (722 kB bundle). Backend test suite rerun pending with E/F items. |
| F3 Manual verification | 🔄 partial | this commit | Done: full-range no-clip view, green-up, RSI+Median instant plot, legend, tooltip, persistence across reload, market-closed badge. Remaining: 8 overlays + 4 osc sweep, basis toggle, colour-rule flip, 1W/YTD buttons in UI. |
| F4 Final report | ⬜ todo | — | |

## Open questions for the user

1. Paste NEPSE's daily table for ANLB 2026-06-30→09-30 for row-by-row parity proof.
2. On gap days, does NEPSE colour by close-vs-prev-close (our default) or close-vs-open?
