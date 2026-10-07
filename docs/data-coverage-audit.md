# Data Coverage Audit Matrix

## Legend
- ✅ **shown** - fully implemented and visible in UI
- 🔧 **backend only** - API exists but no frontend component
- 📦 **frontend shell** - UI exists but shows empty/loading state
- ❌ **missing** - not implemented at all

## Data Coverage Matrix

| Item | Backend Endpoint | Frontend Page/Component | Current Source | Returns Real Data? | Status |
|---|---|---|---|---|---|
| **1. NEPSE Data** |
| Market status | `/api/nepse/status` | MarketPage (topbar) | NEPSE (free) | ✅ | ✅ shown |
| Market summary | `/api/nepse/market` | MarketPage | NEPSE (free) | ✅ | ✅ shown |
| NEPSE index (live) | `/api/nepse/indices` | MarketPage (sub-indices strip) | NEPSE (free) | ✅ | ✅ shown |
| Sector sub-indices | `/api/nepse/indices` | MarketPage | NEPSE (free) | ✅ | ✅ shown |
| Index history (OHLCV) | `/api/nepse/indices/{name}/history` | MarketPage (chart) | NEPSE (free) | ✅ | ✅ shown |
| Market cap series | `/api/nepse/market-caps` | - | NEPSE (free) | ✅ | 🔧 backend only |
| Live market (all stocks) | `/api/nepse/stocks` | StocksPage, MarketPage | NEPSE (free) | ✅ | ✅ shown |
| Per-security live quote | `/api/nepse/stocks/{symbol}/live` | CompanyPage, TechnicalChart | NEPSE (free) | ✅ | ✅ shown |
| Security master | `/api/reference/securities` | SecuritiesPage, StocksPage | NEPSE (free) | ✅ | ✅ shown |
| Per-security detail | `/api/reference/security/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Promoter/public split | `/api/reference/security/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Company news/announcements | `/api/reference/companies/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Market-wide news | `/api/nepse/news` | NewsPage | NEPSE (free) | ✅ | ✅ shown |
| Corporate actions (bonus/right) | `/api/reference/corporate-actions` | CorporateActionsPage, CompanyPage | NEPSE (free) | ✅ (partial) | ✅ shown |
| Cash dividend % | From announcements | DividendAnalysisPage, CompanyPage | NEPSE (free) | ✅ (derived) | ✅ shown |
| Book closure date | From announcements | CompanyPage | NEPSE (free) | ✅ (derived) | ✅ shown |
| AGM date | From announcements | CompanyPage | NEPSE (free) | ✅ (derived) | ✅ shown |
| Right issue % | `/api/reference/corporate-actions` | CorporateActionsPage | NEPSE (free) | ✅ | ✅ shown |
| Market depth | `/api/reference/companies/{symbol}` | CompanyPage | NEPSE (free) | ❌ (empty) | ❌ missing |
| Security price history | `/api/nepse/stocks/{symbol}/history` | AnalyticsPage, CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Today price (archive) | `/api/archive/today-price` | - | NEPSE (free) | ✅ | 🔧 backend only |
| Sector master | `/api/reference/sectors` | SecuritiesPage, ScreenerPage | NEPSE (free) | ✅ | ✅ shown |
| Broker registry | `/api/reference/brokers` | BrokersPage | NEPSE (free) | ✅ | ✅ shown |
| Margin trading list | `/api/reference/margin-list` | - | NEPSE (free) | ✅ | 🔧 backend only |
| Security profile text | `/api/reference/security/{id}/profile` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Board of directors | `/api/reference/security/{id}/board` | - | NEPSE (free) | ✅ | 🔧 backend only |
| Security classification | `/api/reference/security/{id}/classification` | - | NEPSE (free) | ✅ | 🔧 backend only |
| NEPSE reports list | `/api/reference/reports` | - | NEPSE (free) | ✅ | 🔧 backend only |
| Holiday calendar | `/api/reference/holidays/{year}` | CalendarPage | NEPSE (free) | ✅ | ✅ shown |
| Adjusted price history | Derived (bonus/right) | AnalyticsPage | Derived | ✅ (approx) | ✅ shown |
| Per-broker trade flow | Unavailable | - | N/A | ❌ | ❌ missing |
| Mutual fund NAV | Unpublished | FundsPage | N/A | ❌ | ❌ missing |
| Company fundamentals | Unpublished | - | N/A | ❌ | ❌ missing |
| Intraday candles/ticks | Unpublished | - | N/A | ❌ | ❌ missing |
| Fund holdings | Unpublished | - | N/A | ❌ | ❌ missing |

## 2. Company Profile
| Item | Backend Endpoint | Frontend Page | Current Source | Returns Real Data? | Status |
|---|---|---|---|---|---|
| Company info (name, sector, ISIN) | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Board members | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Holding structure | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Price snapshot (LTP, change, range) | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| 52-week range | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Market cap | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Dividend yield | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| P/E, P/B, ROE, ratios | Unpublished | CompanyPage | N/A | ❌ | ❌ missing |
| Quarterly reports | Unpublished | QuarterlyPage | N/A | ❌ | ❌ missing |
| Balance sheet | Unpublished | CompanyPage | N/A | ❌ | ❌ missing |
| Income statement | Unpublished | CompanyPage | N/A | ❌ | ❌ missing |
| Historical financial data | Unpublished | - | N/A | ❌ | ❌ missing |
| Promoter/public split | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Dividends & corporate actions | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Book closure date | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| AGM date | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ✅ | ✅ shown |
| Market depth | `/api/reference/company/{symbol}` | CompanyPage | NEPSE (free) | ❌ | ❌ missing |

## 3. Investment Opportunities & Corporate Actions
| Item | Backend Endpoint | Frontend Page | Current Source | Returns Real Data? | Status |
|---|---|---|---|---|---|
| IPO/FPO | `/api/reference/corporate-actions` | CorporateActionsPage | NEPSE (free) | ✅ (partial) | ✅ shown |
| Right share issues | `/api/reference/corporate-actions` | CorporateActionsPage | NEPSE (free) | ✅ | ✅ shown |
| Dividend/bonus | `/api/reference/corporate-actions` | CorporateActionsPage, DividendAnalysisPage | NEPSE (free) | ✅ | ✅ shown |
| Merger & acquisition | Unpublished | - | N/A | ❌ | ❌ missing |
| AGM/SGM | `/api/reference/corporate-actions` | CorporateActionsPage, CompanyPage | NEPSE (free) | ✅ | ✅ shown |

## 4. Financial Data
| Item | Backend Endpoint | Frontend Page | Current Source | Returns Real Data? | Status |
|---|---|---|---|---|---|
| Quarterly reports | Unpublished | QuarterlyPage | N/A | ❌ | ❌ missing |
| Balance sheets | Unpublished | CompanyPage | N/A | ❌ | ❌ missing |
| Income statements | Unpublished | CompanyPage | N/A | ❌ | ❌ missing |
| General ratios (NRB) | Unpublished | CompanyPage | N/A | ❌ | ❌ missing |
| Historical financial data | Unpublished | - | N/A | ❌ | ❌ missing |

## 5. Mutual Funds
| Item | Backend Endpoint | Frontend Page | Current Source | Returns Real Data? | Status |
|---|---|---|---|---|---|
| Fund profile | `/api/reference/funds/{symbol}` | FundsPage | NEPSE (free) | ✅ | ✅ shown |
| Income statement | Unpublished | FundsPage | N/A | ❌ | ❌ missing |
| NAV statement | `/api/reference/funds/{symbol}/nav-history` | FundsPage | Admin import | ❌ (admin only) | ❌ missing |
| Share holding | Unpublished | FundsPage | N/A | ❌ | ❌ missing |

## 5. Live Data & Delay Display (WP-L1 to WP-L3)
| Feature | Status | Notes |
|---|---|---|
| Central poller (WP-L1) | ❌ not implemented | Need single poller, 20-30s interval, trading hours only |
| Snapshot storage (ring buffer + DB) | ❌ not implemented | Ring buffer (30 min) + DB last-good |
| Display delay by role (WP-L2) | ❌ not implemented | Admin 0s, public 60s default |
| SSE delivery (WP-L3) | ❌ not implemented | SSE endpoint with heartbeat |
| Live candle on chart | ✅ partial | TechnicalChart merges live quote as synthetic candle |
| Delay badge | ❌ not implemented | "LIVE · delayed ~Ns · as of HH:MM:SS NPT" |
| Market hours gate | ✅ implemented | Scheduler checks `market_is_open` |
| Data age measurement | ❌ not implemented | Need `data_age_seconds` in responses |

## Vendor Sources (WP-B through WP-E)
| Source | Adapter | Status | Items Mapped | Notes |
|---|---|---|---|---|
| ShareHub Nepal | ❌ not implemented | Planned | Offerings, dividends, announcements, holidays, companies, financial ratios, price-volume, index charts | Need API keys |
| SmartWealthPro | ❌ not implemented | Planned | Market status, indices, live market, price/volume, security details, IPO/FPO, dividends, financial ratios | Need API keys, docs show only headings |
| nepseauth (Go) | ❌ not integrated | Reference only | Floorsheet, market depth, company news, board, financials | Reference only; no Go in stack |

## UNVERIFIED Items (need user confirmation)
1. Settlement days (T+2 assumed, unverified)
2. Holiday list for current fiscal year
3. Circuit percentage and rounding rule
4. Ex-date convention (book-close based)
5. Fee and tax rates confirmation (FY 2083/84 CGT)
6. MeroShare CSV sample format
7. IPO/right announcement source
8. NRB data source for ratios
9. Gold/silver price source
10. Native Nepali translation review
11. Floorsheet source decision
12. NEPSE weekly-candle tooltips confirmation

## Needs the User
1. Run latency report during market hours
2. Confirm public delay (60s default) and NEPSE terms
3. Vendor demo keys / test mode / fixed IP
4. Native translation review
5. Floorsheet source decision
6. Confirm NEPSE weekly-candle tooltips and AHL daily table