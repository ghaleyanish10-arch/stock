# Nepal Edge — roadmap

Adding what TradingView cannot give Nepali investors: a Nepal-aware layer on the
Smart Analytics NEPSE Data Service. Twelve work packages (WP1–WP12), built in
order, one work package per commit where possible, tests green before each
commit.

**Rules this plan runs under** (from the Nepal Edge spec):

- One backend process on :8000; new code is proven with a request only the new
  code accepts (FastAPI ignores unknown query params, so a bare 200 proves
  nothing).
- No invented data. Missing values use the provenance vocabulary
  (`ok`, `declared_zero`, `not_reported`, `not_published`,
  `upstream_unavailable`, `not_applicable`, `pending`) — never a zero, never a
  dash.
- Anything depending on Nepali market/tax/legal rules that cannot be proven
  from an official source is a **config value marked `spec_status:
  unverified`** in code, docs, API response and UI. See the UNVERIFIED list.
- NEPSE data only through `app/nepse/client.py`. New external sources get a
  terms check and a row in `docs/data-sources.md`, otherwise admin entry /
  CSV import.
- No MeroShare credentials, no BOID storage, ever.
- Tests carry hand-computed expectations in comments. User-owned tables get
  two-user isolation tests; admin endpoints get admin-only tests.

---

## Step 0 — audit (2026-10-06)

**State at audit time:** branch `feature/nepal-edge` cut from
`fix/chart-indicators-colors` @ `653c29d` (after committing the heatmap nav
fix). Working tree carries the user's own untracked scripts
(`backend/check_handlers.py`, `backend/check_tokens.py`,
`backend/compare_tokens.py`, `backend/test_nabil_chart.py`,
`backend/test_nabil_chart2.py`) and one uncommitted line
(`python-multipart==0.0.32`) in `backend/requirements.txt` — all left alone.

**Health at audit time:**

| Check | Result |
|---|---|
| `pytest -q` (backend) | **796 passed, 8 skipped** (44s) |
| `npx tsc -b` (frontend) | clean |
| `npm run build` (frontend) | ✓ built in 5.17s |
| colour-rule script | all cases pass |
| Backend live | `/api/nepse/market` 200, index 2578.73 (+11.96, +0.46%) 2026-10-06 |
| Upstream failure mapping | `/api/nepse/stocks/NABIL/history` (NEPSE graphdata upstream 500) → **HTTP 404** `NEPSE_DATA_NOT_FOUND` envelope, no raw 500. Index history 200. |

### What already exists per work package

The codebase is substantially further along than the Nepal Edge brief assumed.
Mapping each WP to reality:

- **WP1 (time/calendar):** `app/jobs/scheduler.py` already runs on NPT
  (UTC+5:45) with trading-day gating; `trading_days` table stores
  session/non-session/unknown per date. **Missing:** an admin-editable
  `holidays` table (name, source, verification status, CSV import), BS↔AD
  conversion, a shared `app/timeutil` module with
  `is_trading_day`/`next/previous_trading_day`/`trading_days_between`, and a
  fiscal-year helper (Shrawan start, unverified quarter boundaries).
- **WP2 (index archive + relative strength):** index history endpoint works
  and is archived via backfill; sub-indices live. **Missing:** an
  `index_points` archive table for NEPSE + sub-indices with backfill/coverage,
  and relative-strength (stock/index ratio, % outperformance) on chart and
  stock page. Compare tokens do not yet accept an index as the comparison
  symbol.
- **WP3 (corporate actions + adjusted prices):** `corporate_actions` table
  exists with book-close dates, bonus/right percentages, fiscal year; the
  company page derives adjusted close with factor ∏(1+bonus%)×(right ratio).
  **Missing:** a proper adjustment-factor engine (bonus 1/(1+b/100), right
  TERP/P, optional cash toggle) with documented formulas; `basis=adjusted` in
  `/api/analytics/chart` is an honest **no-op** that reports
  `price_mode.applied: "as_traded"` with the reason — make it real, keep
  `as_traded` default; ex-date convention as unverified config.
- **WP4 (calendar + last day to buy):** corporate-actions feed + upcoming
  book closures/AGMs exist. **Missing:** a calendar page/API combining
  holidays + book closures + AGMs + IPO/right dates, and the last-day-to-buy
  helper (book close − N trading days, N unverified config).
- **WP5 (IPO/right tracker):** offerings appear in the corporate-actions
  feed. **Missing:** a proper `offerings` table + per-user tracking
  (planned/applied/allotted/refunded) with reminders. No MeroShare login, no
  BOID storage.
- **WP6 (circuit tools + backtest):** alert rules can express circuit
  conditions. **Missing:** circuit classification from previous close vs
  day high/low (with unverified limit % and tick rounding), circuit streaks,
  upper/lower-circuit pages, and the minimal long-only backtest engine with
  fees, settlement delay and circuit-lock rules.
- **WP7 (cost-aware P&L):** **`HoldingLot` (FIFO, holding period, CGT) and
  `FeeTaxRate` (rates by `effective_from`, `verification_status`) already
  exist** — the two big leftovers from earlier phases are in. Portfolio has
  ledger + CSV import; calculator has break-even logic. **Missing:** verify
  valuation and calculator actually read the fee/tax table (not constants);
  buy/sell markers + average-cost + break-even lines on the chart; MeroShare
  CSV import (parser built against a synthetic file only; a real sample is a
  needs-user item).
- **WP8 (alerts):** `alert_rules`/`alert_channels`/`alert_events` with
  multiple channels exist. **Missing:** Nepal rule types (circuit hit, book
  closure in N days, IPO/right open/close, dividend/bonus announced),
  trading-day-only evaluation with dedupe modes, the post-15:00 daily digest,
  in-app notification center with unread badge, web push; **and the alert
  rule-creation rate limit (a Step-0 leftover) — no 429 path exists today.**
- **WP9 (i18n/BS/AI news):** AI page with consent gating exists. **Missing:**
  i18n layer (en + ne), BS dates beside AD dates, AI news summaries sourced
  from announcements with cache.
- **WP10 (macro panel):** nothing exists (no macro/remittance/tola code).
- **WP11 (mobile/low-data):** responsive shell exists (mobile drawer). 
  **Missing:** PWA manifest + service worker, data-saver toggle, gzip
  middleware, payload size budgets, measured before/after numbers.
- **WP12 (floorsheet):** investigation already done and documented:
  `docs/data-sources.md` records that floorsheet buyer/seller filters are
  ignored by the API, `buyerMemberId`/`sellerMemberId` are always null, and
  `nots/security/floorsheet/{id}` is WAF 403. This WP reduces to writing
  `docs/floorsheet-investigation.md` consolidating that finding plus a
  recommendation, and keeping UI state `not_published`.

### Step-0 leftovers — where they get fixed

| Leftover | Status at audit | Fixed in |
|---|---|---|
| NEPSE upstream 500 → clean 502/503 | **Already clean** (404/502/503 envelopes, see table above) | none needed |
| Lots table for holding period + CGT | **Already exists** (`holding_lots`) | verify in WP7 |
| Fee/tax rates read by valuation/calculator | table exists; wiring to verify | WP7 |
| Alert rule-creation rate limit | **Not present** | WP8 |
| Real sender tests | channels exist; sender tests to verify | WP8 |
| `basis=adjusted` no-op | honest no-op today | WP3 |

---

## Status board

| WP | Item | Status | Tests added | Commit |
|---|---|---|---|---|
| 0 | Audit + roadmap | done | — | (this commit) |
| 1 | NPT time + calendar foundation | not started | — | — |
| 2 | Index/sector archive + relative strength | not started | — | — |
| 3 | Corporate actions + adjusted prices | not started | — | — |
| 4 | Calendar page + last day to buy | not started | — | — |
| 5 | IPO/right tracker | not started | — | — |
| 6 | Circuit tools + minimal backtest | not started | — | — |
| 7 | Cost-aware P&L + MeroShare import | not started | — | — |
| 8 | Nepal alerts | not started | — | — |
| 9 | i18n + BS dates + AI news | not started | — | — |
| 10 | Macro panel | not started | — | — |
| 11 | Mobile-first + low-data mode | not started | — | — |
| 12 | Floorsheet investigation | not started | — | — |

---

## UNVERIFIED list

Config defaults that must be confirmed against an official source before they
can be presented as fact. Each ships as config with
`spec_status: "unverified"` in code, API response and UI.

*(populated as WPs land; initial entries:)*

- Weekly/monthly timeframe aggregation rule (week start, bar label mode) —
  inherited from the chart work, already marked unverified in
  `/api/analytics/chart`.
- FY 2083/84 CGT rates (7.5% long / 10% short) — sourced from IRD FAQ and a
  law-firm briefing, primary Finance Act 2083 gazette not accessible; already
  marked unverified in `fee_tax_rates` seed + `docs/data-sources.md`.

## Needs the user

Not blocking — work continues with documented defaults.

1. Settlement days (T+2 assumed, unverified) — WP4 last-day-to-buy, WP6 backtest.
2. Holiday list for the current fiscal year — WP1 `holidays` seed.
3. Circuit percentage and rounding/tick rule — WP6.
4. Ex-date convention (book-close based? NEPSE publishes no ex-dates) — WP3.
5. Fee and tax rates confirmation, esp. FY 2083/84 CGT gazette — WP7.
6. A real MeroShare CSV export sample — WP7 (parser tested on synthetic file).
7. Source choice for IPO/right announcements, NRB series, gold/silver — WP4/WP5/WP10.
8. Native review of Nepali translations — WP9.
9. Decision on a floorsheet data source — WP12.
10. Confirm NEPSE weekly-candle tooltips and AHL daily table from the earlier
    chart work (carried over).

---

## Work packages in full

Condensed from the Nepal Edge spec; the spec is authoritative where this file
is silent.

- **WP1** NPT helpers (`is_trading_day`, `next/previous_trading_day`,
  `trading_days_between`), Sun–Thu + admin-editable holiday table (CSV import,
  provenance), BS↔AD conversion with tested anchor pairs (BS 2082-01-01 =
  AD 2025-04-14), fiscal-year helper (Shrawan start, unverified quarters).
- **WP2** Archive NEPSE + sub-index daily values (`index_points`, paced
  resumable backfill, coverage reporting, gaps shown), compare/ratio tokens
  accepting an index symbol, relative strength vs index on chart + stock page,
  sector-relative strength. Inner-join alignment, no forward fill.
- **WP3** Adjustment-factor engine (bonus `1/(1+b/100)`, right
  `TERP/P = (P·o + R·n)/((o+n)·P)`, optional cash `(P−D)/P` default off),
  factors multiply backwards from ex-date, `basis=adjusted` real with applied
  factors listed, `as_traded` default, portfolio eligibility reuses the
  events table.
- **WP4** Calendar API + UI (month/list, filters by type/watchlist/portfolio),
  last-day-to-buy helper (book close − N trading days, N unverified),
  dashboard "next 7 days" widget.
- **WP5** `offerings` table (IPO/FPO/right/mutual fund), per-user tracking
  (planned/applied/not applied/allotted/refunded), manual entry + CSV only,
  closing-soon ordering, reminders. No MeroShare login, no BOID.
- **WP6** Circuit classification (unverified limit % + tick rounding, locked
  when high=low=limit), streaks, today's circuit pages, stock badge, minimal
  honest long-only backtest (fees, settlement delay, circuit locks, no
  look-ahead, neutral wording).
- **WP7** Lots + WAC reconciliation, fees by effective_from wired into
  valuation + calculator, chart markers/average-cost/break-even lines,
  MeroShare CSV import (synthetic tests only until a real sample arrives).
- **WP8** Circuit/book-close/IPO-right/dividend rules, trading-day-only
  evaluation, dedupe modes, daily digest after 15:00 NPT, in-app notification
  center, Telegram/email/web push, rule-creation rate limit, sender failure
  hygiene.
- **WP9** i18n en/ne (dependency justified in roadmap), BS dates beside AD,
  AI summaries with consent + labelling + source link + cache, no investment
  advice wording.
- **WP10** Macro series (policy rate, interbank, USD/NPR, remittance,
  gold/silver per tola) via legitimate sources or admin/CSV with provenance
  and staleness warnings; tola grams stated with source.
- **WP11** PWA (manifest + service worker), data-saver toggle, gzip, payload
  budgets with tests, measured before/after payload and bundle numbers.
- **WP12** `docs/floorsheet-investigation.md` consolidating the WAF/API
  findings and recommending a path; UI stays `not_published`.
