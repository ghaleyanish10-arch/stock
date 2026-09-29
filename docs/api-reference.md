# Smart Analytics API Reference

Auto-generated from FastAPI OpenAPI spec. 85 endpoints.

## Base URL
```
http://localhost:8000
```

## Authentication
All personal endpoints require `Authorization: Bearer <JWT>` header.

## Endpoints by Tag

### ai
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/ai/ask` | Ask a grounded question |
| POST | `/api/ai/stream` | Stream a grounded answer |
| GET | `/api/ai/status` | Get AI service status |
| POST | `/api/ai/test` | Test AI (admin only) |

### alerts
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/alerts/channels` | Create notification channel |
| GET | `/api/alerts/channels` | List notification channels |
| PATCH | `/api/alerts/channels/{channel_id}` | Update notification channel |
| DELETE | `/api/alerts/channels/{channel_id}` | Delete notification channel |
| POST | `/api/alerts/rules` | Create alert rule |
| GET | `/api/alerts/rules` | List user's alert rules |
| GET | `/api/alerts/rules/{rule_id}` | Get alert rule |
| PATCH | `/api/alerts/rules/{rule_id}` | Update alert rule |
| DELETE | `/api/alerts/rules/{rule_id}` | Delete alert rule |
| GET | `/api/alerts/rules/{rule_id}/events` | Get alert rule trigger history |
| POST | `/api/alerts/evaluate` | Manually evaluate a rule (for testing) |

### analytics
| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/analytics/indicators/{symbol}` | Technical indicators |
| POST | `/api/analytics/compare` | Compare symbols |
| GET | `/api/analytics/summary/{symbol}` | Summary statistics |
| GET | `/api/analytics/visualisation/periods` | Available visualisation periods |
| GET | `/api/analytics/visualisation/heatmap` | Market heatmap |
| GET | `/api/analytics/screener` | Screener |
| GET | `/api/analytics/chart/{symbol}` | Technical chart |
| GET | `/api/analytics/quarterly/periods` | Available quarterly periods |
| GET | `/api/analytics/quarterly/{symbol}` | Quarterly analysis |
| GET | `/api/analytics/quarterly/{symbol}/history` | Quarterly history |

### archive
| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/archive/coverage` | Archive coverage |
| GET | `/api/archive/as-of` | As-of date |
| GET | `/api/archive/sessions` | Trading sessions |
| GET | `/api/archive/bars/{symbol}` | Daily bars |
| GET | `/api/archive/runs` | Backfill runs |
| POST | `/api/archive/backfill` | Trigger backfill |

### auth
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/auth/register` | Register |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Current user |
| POST | `/api/auth/logout` | Logout |
| POST | `/api/auth/change-password` | Change password |
| PATCH | `/api/auth/me` | Update profile |

### calculator
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/calculator/buy-sell` | Buy/sell cost with fees |
| POST | `/api/calculator/bonus-right` | Bonus/right share impact |
| POST | `/api/calculator/wacc` | Weighted Average Cost |
| POST | `/api/calculator/break-even` | Break-even price |
| POST | `/api/calculator/dividend-yield` | Dividend yield |
| POST | `/api/calculator/xirr` | XIRR from cashflows |
| POST | `/api/calculator/adjust-price` | Price adjustment for bonus/right |

### news
| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/news` | List news with filters |
| GET | `/api/news/{news_id}` | Get news item |
| POST | `/api/news/sync` | Sync news from NEPSE (admin) |
| GET | `/api/news/search` | Search news by keyword |

### portfolio
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/portfolio` | Create portfolio |
| GET | `/api/portfolio` | List portfolios |
| GET | `/api/portfolio/{portfolio_id}` | Get portfolio |
| PATCH | `/api/portfolio/{portfolio_id}` | Update portfolio |
| DELETE | `/api/portfolio/{portfolio_id}` | Delete portfolio |
| POST | `/api/portfolio/{portfolio_id}/transactions` | Add transaction |
| GET | `/api/portfolio/{portfolio_id}/transactions` | List transactions |
| PATCH | `/api/portfolio/{portfolio_id}/transactions/{transaction_id}` | Update transaction |
| DELETE | `/api/portfolio/{portfolio_id}/transactions/{transaction_id}` | Delete transaction |
| GET | `/api/portfolio/{portfolio_id}/holdings` | Get holdings |
| GET | `/api/portfolio/{portfolio_id}/valuation` | Portfolio valuation with P/L |
| GET | `/api/portfolio/{portfolio_id}/xirr` | Portfolio XIRR |

### quarterly
| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/analytics/quarterly/periods` | Available periods |
| GET | `/api/analytics/quarterly/{symbol}` | Quarterly analysis |
| GET | `/api/analytics/quarterly/{symbol}/history` | Full history |

### reference
| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/reference/securities` | Security master |
| GET | `/api/reference/sectors` | Sectors |
| GET | `/api/reference/brokers` | Brokers |
| GET | `/api/reference/funds` | Mutual funds |
| GET | `/api/reference/funds/{symbol}` | Fund detail |
| POST | `/api/reference/funds/{symbol}/nav` | Import NAV (admin) |
| GET | `/api/reference/funds/{symbol}/nav-history` | NAV history |
| GET | `/api/reference/dividends/{symbol}` | Dividends |
| GET | `/api/reference/dividends/analysis` | Dividend analysis |
| GET | `/api/reference/corporate-actions` | Corporate actions feed |
| GET | `/api/reference/corporate-actions/upcoming` | Upcoming corporate actions |
| POST | `/api/reference/enrich/{symbol}` | Enrich security |
| POST | `/api/reference/enrich-all` | Enrich all missing (admin) |
| POST | `/api/reference/sync` | Sync all reference data (admin) |
| GET | `/api/reference/companies/{symbol}` | Company profile |

### watchlist
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/watchlist` | Create watchlist |
| GET | `/api/watchlist` | List watchlists |
| GET | `/api/watchlist/{watchlist_id}` | Get watchlist |
| PATCH | `/api/watchlist/{watchlist_id}` | Update watchlist |
| DELETE | `/api/watchlist/{watchlist_id}` | Delete watchlist |
| POST | `/api/watchlist/{watchlist_id}/items` | Add symbol |
| DELETE | `/api/watchlist/{watchlist_id}/items/{symbol}` | Remove symbol |
| GET | `/api/watchlist/{watchlist_id}/items` | Get items with prices |
| PATCH | `/api/watchlist/{watchlist_id}/items/{symbol}/reorder` | Reorder item |

## Data Provenance
Every numeric field returns a `Measured` object:
```json
{
  "value": 123.45,
  "status": "ok",
  "as_of": "2026-09-28T15:00:00Z",
  "source": "nepse",
  "note": null
}
```
Status values: `ok`, `declared_zero`, `not_reported`, `not_published`, `upstream_unavailable`, `not_applicable`, `pending`.

## Rate Limits
- AI: 20 req/min, 50 req/day per user
- NEPSE upstream: paced at 120ms/call via shared adapter
- Other endpoints: standard FastAPI limits