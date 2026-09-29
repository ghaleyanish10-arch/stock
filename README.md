# Smart Analytics - NEPSE Data Service

Market data, historical archive, technical analytics and reference data for
the Nepal Stock Exchange, built on the
[`nepse-data-api`](https://github.com/ra8in/nepse_data_api) Python library
(`nepse-data-api==1.0.0.4`, which targets NEPSE's **current**
`www.nepalstock.com.np` platform) and exposed as a FastAPI service with a
React dashboard.

The application never talks to the library directly. All NEPSE access goes
through one adapter, shared process-wide, so the data source can be swapped
out later without touching routes or business logic.

Two design rules run through the whole codebase:

- **The adapter is the only importer of the library.** A test enforces it, so
  upstream calls cannot leak into business logic.
- **A missing value is never a zero.** Every measured value carries a
  provenance status (`ok`, `declared_zero`, `not_reported`, `not_published`,
  `upstream_unavailable`, `not_applicable`, `pending`). See
  [`docs/data-sources.md`](docs/data-sources.md).

> **Data limitations are part of this README on purpose.** NEPSE does not
> publish broker trade attribution, mutual fund NAV, company fundamentals, or
> intraday candles. The UI states each gap where it would otherwise look like
> unfinished work, rather than filling it with an estimate.

> **History:** this service originally used the `nepse-api` package (July
> 2021), whose host `newweb.nepalstock.com` no longer exists (NXDOMAIN -
> NEPSE retired that infrastructure). The adapter was replaced with
> `nepse-data-api` against the live platform; the service layer, models,
> and endpoint contract stayed unchanged, which is exactly what the
> layered architecture was designed for.

## Architecture

```text
React dashboard (frontend/)  ── served from the same origin ──┐
                                                                v
FastAPI routes                                                  │
  app/api/routes.py        GET  /api/nepse/*     (enveloped)  │
  app/archive/routes.py    *    /api/archive/*   (plain)      │
  app/analytics/routes.py  *    /api/analytics/* (plain)      │
  app/reference/routes.py  *    /api/reference/* (plain)      │
  app/auth/routes.py       *    /api/auth/*      (plain)      │
        |                                                   │
        v                                                   │
Shared adapter registry (app/nepse/registry.py)             │
        |  one client, one rate limiter, one cache          │
        v                                                   │
NepseClientAdapter (app/nepse/client.py)  the ONLY module importing the library
        |
        v
nepse-data-api (site-packages)          WASM auth, requests session
        |
        v
NEPSE current API  (www.nepalstock.com.np/api/nots/...)
```

The library is synchronous; the adapter runs its calls in a worker thread
(`asyncio.to_thread`) with a per-request timeout so the async service is never
blocked. NEPSE closes the connection on bursts, so the adapter paces itself and
all services share one instance - see `app/nepse/registry.py`.

Archive and reference data are persisted (SQLAlchemy, SQLite by default),
which is what makes the app accumulate history beyond NEPSE's ~227-session
window.

## Repository layout

```
backend/    FastAPI service: app/, tests/, scripts/, pytest.ini,
            requirements.txt, .env.example; the SQLite archive lives
            in backend/data/ (created on first run, never committed)
frontend/   React 19 + TypeScript + Vite dashboard
docs/       setup, data-source audit, API reference
```

## Installation

Windows (PowerShell), from the project root:

```bash
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

## Frontend (React dashboard)

A React 19 + TypeScript + Vite dashboard in `frontend/`. Server state is
handled by TanStack Query (cache, deduplication, invalidation after the
backfill mutation); routing by React Router.

Pages: Market overview, Movers, Stocks, Archive, Analytics, Securities,
Brokers, Funds, and sign-in. Light and dark themes, with NEPSE's red-up /
green-down convention. Every page that renders a value uses the provenance
component, so a missing number shows its reason rather than a dash.

Two ways to run it:

1. **Served by the backend (simplest):**

    ```bash
    cd frontend
    npm install
    npm run build          # outputs frontend/dist
    ```

    Then just start the FastAPI service - it automatically serves the built
    dashboard at `http://127.0.0.1:8000/` (same origin, no CORS involved).

2. **Vite dev server (hot reload):**

    ```bash
    cd frontend
    npm run dev            # http://localhost:5174
    ```

    The dev server proxies `/api` to `127.0.0.1:8000`, so the backend must
    be running. CORS for `localhost:5174` is already allowed in `app/main.py`.

## Accounts

Registration cannot grant admin. A fresh install creates its first
administrator through a local CLI, so privilege escalation never has an HTTP
surface:

```bash
cd backend
..\.venv\Scripts\python -m app.cli create-admin --email you@example.com
..\.venv\Scripts\python -m app.cli grant-admin --email someone@example.com
..\.venv\Scripts\python -m app.cli list-users
```

Full setup, configuration and deployment notes: [`docs/setup.md`](docs/setup.md).

## Configuration

Copy `.env.example` to `.env` and adjust. Never commit `.env`.
No credentials are needed: NEPSE's public API requires none, and the service
never accepts arbitrary URLs from clients. (The library handles NEPSE's
scrambled-token authentication internally.)

| Variable              | Default | Purpose                                        |
| --------------------- | ------- | ---------------------------------------------- |
| `NEPSE_TIMEOUT`       | `15`    | Per-request timeout (seconds) for NEPSE calls  |
| `NEPSE_CACHE_TTL`     | `30`    | TTL (seconds) of the response cache            |
| `NEPSE_ERROR_TTL`     | `60`    | How long a failed key stays remembered (fail fast) |
| `NEPSE_CACHE_MAXSIZE` | `512`   | Maximum number of cached responses             |
| `NEPSE_LOG_LEVEL`     | `INFO`  | Log verbosity                                  |
| `NEPSE_HOST`          | `127.0.0.1` | uvicorn bind host                          |
| `NEPSE_PORT`          | `8000`  | uvicorn bind port                              |

## Running the service

```bash
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# or
..\.venv\Scripts\python -m app.main
```

Interactive API docs: `http://127.0.0.1:8000/docs`

## Available endpoints

| Endpoint                                   | Method | Purpose                                        |
| ------------------------------------------ | ------ | ---------------------------------------------- |
| `/api/nepse/health`                        | GET    | Liveness probe (no NEPSE call)                 |
| `/api/nepse/status`                        | GET    | Whether the market is open (+ as-of timestamp) |
| `/api/nepse/market`                        | GET    | Status + latest summary + NEPSE index          |
| `/api/nepse/market/summary`                | GET    | Latest market turnover summary                 |
| `/api/nepse/indices`                       | GET    | NEPSE index + all sector sub-indices (live)    |
| `/api/nepse/indices/{name}/history`        | GET    | Historical daily OHLCV for one index           |
| `/api/nepse/market-caps?day=`              | GET    | Market cap series (optionally from one date)   |
| `/api/nepse/stocks`                        | GET    | All securities that traded today               |
| `/api/nepse/stocks/{symbol}`               | GET    | One security's daily figures                   |
| `/api/nepse/stocks/{symbol}/live`          | GET    | One security's live price/volume row           |
| `/api/nepse/stocks/{symbol}/history`       | GET    | Per-security chart data for a date range       |
| `/api/nepse/top-gainers?limit=`            | GET    | Top gainers of the latest session              |
| `/api/nepse/top-losers?limit=`             | GET    | Top losers of the latest session               |

### Reference (Phase 3)

| Endpoint                                          | Method | Purpose                                                                              |
| ------------------------------------------------- | ------ | ------------------------------------------------------------------------------------ |
| `/api/reference/securities`                       | GET    | Security master (568 symbols)                                                        |
| `/api/reference/security/{symbol}`                | GET    | One security with its provenance                                                     |
| `/api/reference/sectors`                          | GET    | Sector master (12)                                                                   |
| `/api/reference/brokers`                          | GET    | Official 92-member registry + attribution status                                     |
| `/api/reference/funds`                            | GET    | Mutual funds with NAV status, tabs: Close-Ended / Open-Ended / Matured               |
| `/api/reference/funds/{symbol}`                   | GET    | Full fund detail: metadata, NAV, dividends, NAV history                              |
| `/api/reference/funds/{symbol}/nav`               | POST   | Import NAV for a fund (admin)                                                        |
| `/api/reference/funds/{symbol}/nav-history`       | GET    | NAV history for a fund                                                               |
| `/api/reference/dividends/{symbol}`               | GET    | Dividends and bonus shares for one symbol                                            |
| `/api/reference/dividends/analysis`               | GET    | Dividend analysis across all symbols (yields, consecutive years, rankings)           |
| `/api/reference/holidays/{year}`                  | GET    | NEPSE holiday list                                                                   |
| `/api/reference/sync`                             | POST   | Sync securities, sectors, brokers                                                    |
| `/api/reference/enrich/{symbol}`                  | POST   | Fetch a symbol's metadata on demand                                                  |
| `/api/reference/enrich-all`                       | POST   | Bulk enrich all symbols missing listed shares (admin)                                |
| `/api/reference/companies/{symbol}`               | GET    | Full company profile: price, valuation, dividends, promoter split, news, depth       |
| `/api/reference/corporate-actions`                | GET    | Market-wide corporate actions feed (dividends, bonus, right, book close, AGM, IPO)   |
| `/api/reference/corporate-actions/upcoming`       | GET    | Upcoming book closures and AGMs                                                     |
| `/api/auth/register`, `/login`                    | POST   | Account creation, sign in (returns a JWT)                                            |
| `/api/auth/me`                                    | GET/PATCH | Current profile, theme preference                                               |
| `/api/auth/change-password`                       | POST   | Change password, invalidate other sessions                                           |
| `/api/auth/logout`                                | POST   | Invalidate every issued token                                                        |

### Analytics (Phase 2)

| Endpoint                                | Method | Purpose                                     |
| --------------------------------------- | ------ | ------------------------------------------- |
| `/api/analytics/visualisation/periods`  | GET    | Available periods and size metrics for treemap |
| `/api/analytics/visualisation/heatmap`  | GET    | Treemap/pie data for a period and size metric |
| `/api/analytics/screener`               | GET    | Technical screener with filters, exports    |
| `/api/analytics/chart/{symbol}`         | GET    | Technical chart data with 9 indicators      |

### Reference (Phase 3)

| Endpoint                                         | Method | Purpose                                                                              |
| ------------------------------------------------ | ------ | ------------------------------------------------------------------------------------ |
| `/api/reference/securities`                      | GET    | Security master (568 symbols)                                                        |
| `/api/reference/security/{symbol}`               | GET    | One security with its provenance                                                     |
| `/api/reference/sectors`                         | GET    | Sector master (12)                                                                   |
| `/api/reference/brokers`                         | GET    | Official 92-member registry + attribution status                                     |
| `/api/reference/funds`                           | GET    | Mutual funds with NAV status, tabs: Close-Ended / Open-Ended / Matured               |
| `/api/reference/funds/{symbol}`                  | GET    | Full fund detail: metadata, NAV, dividends, NAV history                              |
| `/api/reference/funds/{symbol}/nav`              | POST   | Import NAV for a fund (admin)                                                        |
| `/api/reference/funds/{symbol}/nav-history`      | GET    | NAV history for a fund                                                               |
| `/api/reference/dividends/{symbol}`              | GET    | Dividends and bonus shares for one symbol                                            |
| `/api/reference/dividends/analysis`              | GET    | Dividend analysis across all symbols (yields, consecutive years, rankings)           |
| `/api/reference/holidays/{year}`                 | GET    | NEPSE holiday list                                                                   |
| `/api/reference/sync`                            | POST   | Sync securities, sectors, brokers                                                    |
| `/api/reference/enrich/{symbol}`                 | POST   | Fetch a symbol's metadata on demand                                                  |
| `/api/reference/enrich-all`                      | POST   | Bulk enrich all symbols missing listed shares (admin)                                |
| `/api/reference/companies/{symbol}`              | GET    | Full company profile: price, valuation, dividends, promoter split, news, depth       |
| `/api/reference/corporate-actions`               | GET    | Market-wide corporate actions feed (dividends, bonus, right, book close, AGM, IPO)   |
| `/api/reference/corporate-actions/upcoming`      | GET    | Upcoming book closures and AGMs                                                      |
| `/api/auth/register`, `/login`                    | POST   | Account creation, sign in (returns a JWT)                                            |
| `/api/auth/me`                                   | GET/PATCH | Current profile, theme preference                                               |
| `/api/auth/change-password`                      | POST   | Change password, invalidate other sessions                                           |
| `/api/auth/logout`                               | POST   | Invalidate every issued token                                                        |

Index names accepted by `/indices/{name}/history`: `nepse`, `sensitive`,
`float`, `sensitive-float`, `banking`, `hydropower`, `finance`, `hotel`,
`investment`, `manufacturing`, `microfinance`, `mutual-fund`, `nepse-energy`/
`energy`, `non-life`, `others`, `life`, `trading`, or `all` (see the
library's `INDEX_MAP`).

## Response format

The `/api/nepse/*` endpoints return an envelope. The Phase 1 endpoints
(`/api/archive/*`, `/api/analytics/*`, `/api/reference/*`, `/api/auth/*`)
return plain JSON, because their payloads already carry per-field provenance
and a second wrapper would only add noise.

Success:

```json
{ "success": true, "data": { ... } }
```

Error (no stack traces ever reach the client):

```json
{
  "success": false,
  "error": {
    "code": "NEPSE_UNAVAILABLE",
    "message": "NEPSE service is currently unavailable"
  }
}
```

Error code to HTTP status mapping:

| Code                     | HTTP | Meaning                              |
| ------------------------ | ---- | ------------------------------------ |
| `NEPSE_SYMBOL_NOT_FOUND` | 404  | Unknown/invalid symbol               |
| `NEPSE_DATA_NOT_FOUND`   | 404  | No data for the requested date       |
| `NEPSE_UNAVAILABLE`      | 503  | NEPSE unreachable or down            |
| `NEPSE_TIMEOUT`          | 504  | NEPSE did not answer in time         |
| `NEPSE_INVALID_RESPONSE` | 502  | NEPSE answered with unusable data    |
| `NEPSE_AUTH_FAILED`      | 502  | Token rejected even after re-auth    |
| `NEPSE_RATE_LIMITED`     | 429  | NEPSE asked us to slow down (429)    |
| `NEPSE_API_ERROR`        | 502  | Unexpected NEPSE service failure     |

Resilience behavior (all in `app/nepse/client.py`): the auth token is
refreshed proactively every 240s and once more on any rejection; HTTP 429
and 5xx are retried twice with linear backoff (1s, 2s); every request
sends browser-like headers and a 15s timeout; index endpoints log HTTP
status, content-type, and the first 500 chars of any failing raw body
under the `app.nepse.client` logger for forensics.

## Example requests

```bash
curl http://127.0.0.1:8000/api/nepse/health
curl http://127.0.0.1:8000/api/nepse/status
curl http://127.0.0.1:8000/api/nepse/market
curl "http://127.0.0.1:8000/api/nepse/indices/nepse/history?start=2026-09-01&end=2026-09-27"
curl "http://127.0.0.1:8000/api/nepse/market-caps?day=2026-04-24"
curl http://127.0.0.1:8000/api/nepse/stocks
curl http://127.0.0.1:8000/api/nepse/stocks/NABIL
curl "http://127.0.0.1:8000/api/nepse/top-gainers?limit=5"
```

Symbols are validated server-side (`^[A-Z0-9][A-Z0-9-]{0,15}$`, case
insensitive input); invalid symbols return 404 without any upstream call.

## Example responses

All examples below are **real responses captured live** from the running
service (September 2026), trimmed for brevity.

`GET /api/nepse/status`:

```json
{ "success": true, "data": { "is_open": false, "as_of": "2026-09-24T15:00:00" } }
```

`GET /api/nepse/market`:

```json
{
  "success": true,
  "data": {
    "status": { "is_open": false, "as_of": "2026-09-24T15:00:00" },
    "summary": {
      "business_date": null,
      "total_turnover": 5447313168.2,
      "total_traded_shares": 17270449,
      "total_transactions": 51716,
      "traded_scrips": 356
    },
    "nepse_index": {
      "name": "NEPSE Index", "value": 2618.04,
      "change": 11.77, "change_percentage": 0.44
    }
  }
}
```

`GET /api/nepse/stocks/NABIL`:

```json
{
  "success": true,
  "data": {
    "symbol": "NABIL",
    "security_id": 131,
    "security_name": "Nabil Bank Limited",
    "open_price": 566.0,
    "high_price": 570.0,
    "low_price": 566.0,
    "close_price": null,
    "last_traded_price": 569.0,
    "previous_close": 565.0,
    "change_percentage": 0.71,
    "total_traded_quantity": 70749,
    "total_traded_value": 40123456.0,
    "total_trades": 495,
    "fifty_two_week_high": 605.0,
    "fifty_two_week_low": 410.0,
    "last_updated": null
  }
}
```

`GET /api/nepse/indices/nepse/history?start=2026-09-01&end=2026-09-27`
(one row of many):

```json
{
  "success": true,
  "data": {
    "index": "nepse", "count": 15,
    "history": [
      {
        "index_name": "NEPSE",
        "business_date": "2026-09-24",
        "open": 2611.03, "high": 2629.94, "low": 2605.32, "close": 2629.81,
        "turnover": 5447313168.2, "volume": 17270449,
        "total_transactions": 51716
      }
    ]
  }
}
```

Fields a given source does not provide are `null` rather than invented.

## Testing

```bash
cd backend
..\.venv\Scripts\python -m pytest -q
```

243 tests, all with the library mocked - no real NEPSE requests are made in
the test suite. Covered: market/stock/history/index success paths, invalid and
unknown symbols, upstream error classes, cache behaviour, the shared-adapter
invariant, live endpoint shapes, fund classification, market cap derivation,
scheduler UTC and retry handling, deferred sessions, schema migrations, and the
admin CLI.

Frontend:

```bash
cd frontend
npm run build        # tsc -b && vite build; the type check is the real gate
```

Live end-to-end check against NEPSE, writing a report of what was fetched:

```bash
cd backend
..\.venv\Scripts\python scripts\phase1_e2e.py
```

## Limitations

Library (`nepse-data-api==1.0.0.4`, unofficial - not affiliated with NEPSE):

* Handles NEPSE's WASM token authentication and TLS internally (the library
  disables TLS verification - acceptable for public market data, not for
  anything sensitive).
* Verified working live: market status, market summary, indices, index
  history with date ranges, live market (all ~356 symbols), price/volume,
  market-cap series, security details, top gainers/losers.
* Broken upstream (NEPSE's side, verified 2026-09): the per-security chart
  endpoint (`/api/nots/market/graphdata/{id}`) returns HTTP 500, so
  `/stocks/{symbol}/history` reports `NEPSE_DATA_NOT_FOUND` until NEPSE
  fixes it. Market depth returns non-JSON, per-date daily-trade stats and
  sectorwise-by-date return empty/epoch data. These are upstream issues,
  not service bugs; the service surfaces them as clean 404/502 envelopes.
* "Live" means NEPSE's published snapshots, not real-time tick data.
* Pre-open window (before 11:00 NPT): NEPSE's live-market list is empty or
  carries symbol-less auction placeholder rows, and its auth endpoint flaps
  (intermittent HTTP 401 HTML bodies that the library maps to empty lists).
  The service falls back to the price/volume feed (last session's data) for
  the stock list and per-symbol lookups; the index falls back to the last
  real close (skipping NEPSE's seeded zero row for the new session).
* Unofficial: NEPSE can change or gate these endpoints at any time.

This implementation:

* Persists archive and reference data in SQLAlchemy (SQLite by default,
  WAL mode so a backfill and the dashboard's polling do not block each
  other). Postgres is a config change, not a code change. Live market
  endpoints are still cached in memory only.
* Caching is in-process memory with per-key locking plus failure memory
  (`NEPSE_ERROR_TTL`); restart clears it. A shared cache (Redis) can be
  added behind `TTLResponseCache` without changing the service interface.
* Migrations live in `app/db/migrations.py` and are applied at startup after
  `create_all`, which is enough for the additive and rename changes made so
  far. It is not a general migration framework.
* The index-history endpoint is the recommended historical source: it
  provides daily OHLCV + turnover for every index and reliably supports
  date ranges.
* Phase 1 stops here. Broker attribution, fundamentals, fund NAV, intraday
  data and intraday depth are Phase 2 or later, and each is blocked on the
  source rather than on the code - see `docs/data-sources.md`.
