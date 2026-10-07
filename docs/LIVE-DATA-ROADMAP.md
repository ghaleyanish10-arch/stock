# Live Data & Multi-Source Roadmap

**Branch:** `feature/live-data-and-sources` (created from `feature/nepal-edge` @ `bdacc1f`)

## Overview
Add free near-real-time NEPSE data with visible delay, plus optional vendor sources for data the free source cannot provide. All vendor sources are opt-in, disabled by default, and require user-provided API keys.

## Work Packages

### WP-L1. Central Poller & Snapshots (Free Source)
**Status:** ⬜ Not started
- Single backend poller running in NPT trading hours (Sun-Thu, 11:00-15:00)
- Interval: 20-30s (configurable, min 15s) with jitter
- Ring buffer (30 min) in memory + last-good snapshot in DB
- Exponential backoff on errors/429; circuit breaker
- Outside trading hours: one fetch after close, then 5-min or off
- Snapshot stores `fetched_at` (our clock) and `source_time` (NEPSE's timestamp)

**Tests needed:**
- Poller respects trading hours (Sun-Thu)
- Ring buffer eviction works
- Backoff on 429/5xx
- Snapshot stores both timestamps

**Commit:** (pending)

---

### WP-L2. Display Delay & Roles
**Status:** ⬜ Not started
- Delay by role: admin = `admin_data_delay_seconds` (default 0), public = `public_data_delay_seconds` (default 60s)
- Served snapshot = newest with `fetched_at <= now - delay`
- Response carries: `as_of`, `configured_delay_seconds`, `data_age_seconds`, `market_open`, `stale` (age > 3x poll interval during trading)
- Test: fake clock, snapshots at t=0,30,60,90s with delay=60s → at t=90 the t=30 snapshot is served

**Commit:** (pending)

---

### WP-L3. Browser Delivery (SSE)
**Status:** ⬜ Not started
- SSE endpoint `/api/live/market-data` with heartbeat (15s) and reconnect backoff
- Pushes only on new snapshot; polling fallback ≥ poller interval
- ETag/304, gzip, compact diff payloads
- Frontend: badge "LIVE · delayed ~Ns · as of HH:MM:SS NPT", amber when stale, "Market closed" after close
- Green/red flash on price change (uses CSS vars --up/--down)
- Batch DOM updates with `requestAnimationFrame`; virtualize long tables
- Pause updates when tab hidden (Page Visibility API)
- Data-saver mode: no auto-refresh, smaller ranges, fewer indicators, compact JSON
- Test: 50 simulated clients → only poller's upstream calls; SSE reconnect; role-based delay

**Commit:** (pending)

---

### WP-B. Source Adapter Layer (Merged Adapter)
**Status:** 🟨 Partial (nepse_lib exists)
- `SourceAdapter` interface with capabilities map (item → supported/partial/unknown)
- Current `NepseClientAdapter` wrapped as `nepse_lib` (default for all items it serves)
- Config `data_sources: item -> source` with per-item fallback chain
- Normalized Pydantic schemas for all item types (offerings, dividends, announcements, holidays, company profile, ratios, stock table row, sector perf, movers, heatmap, index contrib, price-volume, floorsheet, mutual fund)
- Every record carries `source`, `as_of`, `verification_status`
- Cache, single-flight, budget guard, last-good snapshots
- `vendor_data_public` gating (admin-only by default)
- Tests: fallback, budget exhaustion, cache TTL, gating, default behavior unchanged when vendor sources disabled

**Commit:** (pending)

---

### WP-L1. Live Quote Poller (Backend)
**Status:** 🟨 Partial (realtime service exists)
- `RealtimeService` exists with 30s poll, but needs integration with new poller architecture
- Needs to use shared adapter, respect rate limits, emit snapshots to SSE hub
- Currently polls `/api/nepse/stocks` and caches in memory

**Commit:** (pending)

---

### WP-L2. Delay Middleware & Response Envelope
**Status:** ⬜ Not started
- Response envelope for all live endpoints:
  ```json
  {
    "data": {...},
    "meta": {
      "as_of": "2026-10-07T12:30:00+05:45",
      "fetched_at": "2026-10-07T12:31:00+05:45",
      "configured_delay_seconds": 60,
      "data_age_seconds": 30,
      "market_open": true,
      "stale": false
    }
  }
  ```
- Admin delay = 0s default, public = 60s default (configurable)

---

### WP-L3. SSE Endpoint & Frontend Hook
**Status:** ⬜ Not started
- `GET /api/live/market-data` (SSE) with `last_event_id` resume
- Heartbeat every 15s (`: heartbeat\n\n`)
- Frontend: `useLiveMarketData()` hook with auto-reconnect (exponential backoff 1s, 2s, 4s, max 30s)
- Badge component: `LiveBadge` with role-based delay display
- Chart live candle merge (already exists in `TechnicalChart`)

---

### WP-B. Source Adapter Layer
**Status:** ⬜ Not started
- Interface: `SourceAdapter { capabilities: Map<Item, SupportLevel>; fetch(item, params): Promise<NormalizedData> }`
- `nepse_lib` (default), `sharehub_adapter`, `smartwealth_adapter`
- Config: `data_sources: { item: "nepse_lib" | "sharehub" | "smartwealth" }` with fallback chain
- Normalized schemas (Pydantic): `Offering`, `Dividend`, `Announcement`, `Holiday`, `CompanyProfile`, `RatioRow`, `StockRow`, `SectorPerf`, `Mover`, `HeatmapNode`, `IndexContrib`, `PriceVolumeRow`, `FloorsheetRow`, `MutualFundProfile`, `NavPoint`, `Holding`
- Every record: `source`, `as_of`, `verification_status`
- Cache: TTL per item type, single-flight, budget guard
- `vendor_data_public` flag gates vendor data in public responses

---

### WP-F. Unified Backend Routes
**Status:** ⬜ Not started
- `/api/market-data/*` returning normalized schemas with `source`, `as_of`, `stale`, `demo` flag
- Free source first; vendor only when enabled for that item
- Admin-only for vendor-gated data
- Clean error mapping: upstream failure → 502/503 with last-good data + "as of" time

---

### WP-G. Frontend Pages (Missing Data Only)
**Status:** ⬜ Not started
Build only for items missing/broken in audit. Reuse existing components.

| Page | Route | Components | Source Priority |
|------|-------|------------|-----------------|
| Public Offerings | `/offerings` | `OfferingsTable`, `OfferingCard`, filters | Free → ShareHub |
| Dividends & Bonus | `/dividends` | `DividendTable`, filters | Free → ShareHub |
| Announcements Feed | `/announcements` | `AnnouncementFeed`, category filters | Free → ShareHub |
| Company Page Additions | `/company/:symbol` | `OwnershipSplit`, `RatiosTable`, `FinancialsPanels` | Free → ShareHub |
| Fundamentals & Ratios | `/fundamentals` | `RatioTable`, `QuarterlyPanel`, `BS/IS panels` | Free → ShareHub |
| Mutual Funds | `/funds` | `FundProfile`, `NavTable`, `HoldingsTable` | Free → ShareHub |
| Market Insights | `/insights` | `SectorPerf`, `MoversTimeline`, `Heatmap`, `IndexContrib` | Free → ShareHub |
| Floorsheet/Brokers | `/floorsheet` | `BrokerFlowTable`, `BrokerAggTable` | Vendor only (admin) |

---

### WP-C. ShareHub Adapter
**Status:** ⬜ Not started
- Login + refresh, bearer header, test-mode header
- Pagination (`Page`, `Size` max 500)
- Error mapping: `UNAUTHORIZED`→401, `NO_ACCESS`→403, `SERVICE_NOT_ENABLED`→503, `IP_NOT_ALLOWED`→403, `RATE_LIMITED`→429, `INVALID_*`→400, `503`→503
- `my-ip` helper for allow-list
- Map endpoints to normalized schemas
- Unknown fields → `not_published` with reason
- Licence terms documented as UNVERIFIED

---

### WP-D. SmartWealthPro Adapter + Discovery
**Status:** ⬜ Not started
- Auth headers from env
- **Discovery script** `backend/scripts/vendor_discovery.py`: user runs once with demo keys; tries likely paths from docs; saves sanitized samples to git-ignored folder; writes `docs/vendor-discovery.md`
- Budget-aware, manual run only
- Implement mapping only for items with confirmed shape; others `unknown` with "vendor shape not yet confirmed"

---

### WP-E. nepseauth Reference (No Go)
**Status:** ⬜ Not started
- Read library source (`voidarchive/nepseauth`, `voidarchive/go-nepse`)
- Test floorsheet via our Python adapter's auth
- If works: add paging + budget + end-of-day agg by buyer/seller broker
- If not: record evidence, leave `not_published`
- **No Go in stack**

---

### WP-H. Comparison Script & Admin Page
**Status:** ⬜ Not started
- `backend/scripts/source_comparison.py` (manual run, respects limits)
- For each item × enabled source: works/partial/no, status, fields, row count, freshness, latency, field-level diff vs current source (prices, volumes, index values) with tolerance
- Output `docs/source-comparison.md` + JSON in git-ignored folder
- Optional admin page with side-by-side view
- **Never write comparison data to production tables**

---

### WP-I. Docs & Close-out
**Status:** ⬜ Not started
- `docs/data-sources.md` updated
- `.env.example` placeholders
- Roadmap final matrix: what is `shown`, what needs key/decision
- Test totals before/after, `npm run build`, `git log --oneline -30`

---

## UNVERIFIED List (Config Defaults Marked `spec_status: unverified`)
| Config | Default | Needs Verification From |
|---|---|---|
| `settlement_days` | 2 (T+2) | Broker / SEBON |
| `holiday_list` (current FY) | [] | NEPSE official calendar |
| `circuit_pct` | 10% | NEPSE rulebook |
| `circuit_rounding` | nearest 0.01 | NEPSE |
| `ex_date_convention` | book_close based | NEPSE / broker |
| `fee_tax_rates` (FY 2083/84 CGT) | 7.5%/10% | IRD gazette / Finance Act 2083 PDF |
| `public_data_delay_seconds` | 60 | User preference / NEPSE terms |
| `admin_data_delay_seconds` | 0 | User preference |
| `vendor_data_public` | false | Legal review |
| `sharehub_test_mode` | false | ShareHub enablement |
| `smartwealth_keys` | - | SmartWealthPro |

---

## Needs the User (Non-blocking, Documented)
1. Run `backend/scripts/live_latency_report.py` during market hours
2. Confirm public delay & NEPSE public display terms
3. Vendor demo keys / test mode / fixed IP (home IPs change)
4. Source choice for IPO/right announcements, NRB series, gold/silver
5. Native Nepali translation review
6. Floorsheet source decision
7. NEPSE weekly-candle tooltips & AHL daily table confirmation

---

## Progress Tracker
| WP | Name | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| WP-L1 | Central Poller | ⬜ | | | |
| WP-L2 | Delay & Roles | ⬜ | | | |
| WP-L3 | SSE Delivery | ⬜ | | | |
| WP-B | Source Adapter | ⬜ | | | |
| WP-L1 | Live Quote Poller | 🟨 | | | RealtimeService exists |
| WP-L2 | Delay Middleware | ⬜ | | | |
| WP-L3 | SSE Endpoint | ⬜ | | | |
| WP-B | Source Adapter | ⬜ | | | |
| WP-F | Unified Routes | ⬜ | | | |
| WP-G | Frontend Pages | ⬜ | | | |
| WP-C | ShareHub | ⬜ | | | Needs keys |
| WP-D | SmartWealthPro | ⬜ | | | Needs keys + discovery |
| WP-E | nepseauth Ref | ⬜ | | | No Go |
| WP-H | Comparison | ⬜ | | | |
| WP-I | Docs | ⬜ | | | |

---

## Current Git State
- Branch: `feature/live-data-and-sources` (to be created from `feature/nepal-edge` @ `bdacc1f`)
- Base: `feature/nepal-edge` @ `bdacc1f` (after WP2 index archive + relative strength)
- Uncommitted: test fixes in `tests/test_index_archive.py`, chart bug fix in `app/analytics/chart.py:1126`

## Next Steps
1. Create branch `feature/live-data-and-sources`
2. Start WP-L1: Central poller with ring buffer + DB snapshot
3. Implement delay middleware (WP-L2)
4. Add SSE endpoint (WP-L3)
5. Build source adapter interface (WP-B)
6. Create unified routes (WP-F)
7. Build frontend pages (WP-G)
7. Document UNVERIFIED list & needs-user items