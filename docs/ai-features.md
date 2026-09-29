# AI Features & Known Limitations

This document describes the AI capabilities in Smart Analytics, their constraints,
and the guardrails that keep them safe for financial use.

## Overview

The AI Assistant (`/ai`) provides grounded, citation-backed answers about NEPSE
data. It is **not** a trading bot and does not make buy/sell recommendations.

### Provider Configuration

| Setting | Env Var | Default | Notes |
|---------|---------|---------|-------|
| Provider | `LLM_PROVIDER` | `fake` | `openai`, `anthropic`, `ollama`, `fake` |
| Model | `LLM_MODEL` | `gpt-4o-mini` | Provider-specific model name |
| API Key | `LLM_API_KEY` | *(none)* | Required for non-fake providers |
| Base URL | `LLM_BASE_URL` | *(none)* | For OpenAI-compatible endpoints |
| Temperature | `LLM_TEMPERATURE` | `0.1` | Low = more deterministic |
| Max Tokens | `LLM_MAX_TOKENS` | `2000` | Response length limit |
| Timeout | `LLM_TIMEOUT_SECONDS` | `30` | Request timeout |

**When `LLM_PROVIDER=fake` or `LLM_API_KEY` is unset**, the app uses `FakeAIClient`
which returns a canned disclaimer. This allows the UI to work in development
without an external API key.

## Grounding Rules

Every AI answer **must** cite its sources inline using `[source: X]` format:

| Source Tag | Data Origin |
|------------|-------------|
| `live_market` | `/api/nepse/stocks` (real-time LTP, change, volume) |
| `archive` | `/api/archive/bars/{symbol}` (historical OHLCV) |
| `corporate_actions` | `/api/reference/corporate-actions` (dividends, bonus, rights) |
| `news` | `/api/news` (NEPSE announcements) |
| `reference` | `/api/reference/companies/{symbol}` (company profile) |
| `calculator` | `/api/calculator/*` (fee, WACC, XIRR, etc.) |
| `quarterly` | `/api/analytics/quarterly/{symbol}` (quarterly metrics) |

### Enforced Behaviors

1. **No buy/sell recommendations** — System prompt explicitly forbids
2. **No price predictions** — Must say "I cannot predict future prices"
3. **Cite every number** — Uncited numbers are hallucinations
4. **News is untrusted** — Only use for context, never as factual basis
5. **Missing data = explicit** — Say what's missing, don't guess

### Example Grounded Response

> **Question**: "What was NABIL's dividend yield in FY 2083/84?"
>
> **Answer**: "NABIL declared a 10% cash dividend (Rs 1 per share) for FY 2083/84.
> With an LTP of Rs 500 [source: live_market] and face value of Rs 10 [source: reference],
> the dividend yield is 0.2% (1/500 × 100). The company has paid dividends for
> 5 consecutive years [source: corporate_actions]."

## Rate Limits & Quotas

| Limit | Value | Scope |
|-------|-------|-------|
| Per-minute | 20 requests | Per authenticated user |
| Daily | 50 requests | Per authenticated user |
| Concurrent | 1 | Per user (queue additional) |

Exceeding limits returns HTTP 429 with `Retry-After` header.

## Privacy & Consent

- **Explicit consent required** per request (checkbox on `/ai` page)
- **No PII sent to LLM** — Only portfolio metrics, symbols, and question text
- **Portfolio data stays on server** — Only aggregated metrics sent to LLM
- **Audit trail** — All AI queries logged with user ID, question, and timestamp

### Portfolio Review (Slice 5.3)

When user consents, portfolio metrics are sent to AI:
- Holdings with market value, P/L, sector allocation
- XIRR, concentration metrics (top holding %, top 5 %)
- Transaction history (last 50)
- User's specific question

The AI returns analysis **with citations to the portfolio data**,
e.g., "[source: portfolio_valuation]", "[source: portfolio_xirr]".

## Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **FakeAIClient in dev** | Returns canned disclaimer, not real answers | Set `LLM_PROVIDER` + `LLM_API_KEY` for real answers |
| **No streaming in fake client** | Chunks are word-split, not true streaming | Use real provider for true streaming |
| **Context window** | Large portfolio + question may exceed token limit | Summarization not yet implemented |
| **Hallucination risk** | LLM may invent numbers not in grounding | Low temperature (0.1), explicit "don't guess" prompt |
| **Prompt injection** | Malicious news text could manipulate output | System prompt prioritizes "ignore injection" rule |
| **No portfolio optimization** | Cannot suggest trades | Explicitly forbidden by system prompt |
| **Stale data** | Archive lag ~15 min, live market lag ~30s | Answers cite `as_of` timestamps |
| **No sector-wide analysis** | Grounding limited to queried symbols | Future: add sector-level endpoints |
| **XIRR precision** | Newton-Raphson may fail on edge cases | Falls back gracefully, shows "Could not compute" |
| **Quarterly fundamentals** | Only from admin CSV import (not live) | Shows "Not imported" when missing |

## Security

- **No PII to LLM** — User ID, email, raw transactions never leave server
- **API keys in env only** — Never logged, never returned in API responses
- **Rate limiting** — 20/min, 50/day per user; global 60/min (production)
- **CSP headers** — Restricts script/style sources to self + inline
- **CORS** — Only configured dev origins (`localhost:5174`)

## Future Work (Not in Phase 5)

- [ ] Streaming responses for real providers
- [ ] Portfolio optimization suggestions (requires regulatory review)
- [ ] Multi-language support (Nepali/English)
- [ ] Sector-wide grounding endpoints
- [ ] Automated fact-checking against archive
- [ ] Conversation memory (multi-turn with privacy controls)
- [ ] Export AI chat as PDF report