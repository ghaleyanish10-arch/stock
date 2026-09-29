# Phase 5: AI, Real-time, Polish, Docs

## Summary
Completed AI integration with grounded answers, privacy controls, and rate limiting. Real-time updates via paced polling (no push/SSE available in `nepse-data-api`). OpenAPI spec generated. Documentation in `docs/`.

## AI Features

### Backend (`app/ai/`)
- **`service.py`**: `AIService` with grounding, privacy consent, rate limiting (20/min, 50/day), daily limits
- **`routes.py`**: `/ask`, `/stream`, `/status`, `/test` endpoints
- **Clients**: `OpenAIClient`, `AnthropicClient`, `FakeAIClient` (for tests/no-config)
- **Config via env vars**: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS`

### Frontend (`frontend/src/pages/AIPage.tsx`)
- Question form with symbol context, data source selection
- Privacy consent checkbox (required)
- Streaming & non-streaming modes
- AI status panel showing provider/model/limits
- Example questions

### Grounding Rules
- Answers must cite sources: `[source: live_market]`, `[source: archive]`, `[source: corporate_actions]`, `[source: news]`, `[source: reference]`, `[source: calculator]`, `[source: quarterly]`
- No buy/sell recommendations
- No price predictions
- News treated as untrusted context only
- Missing data explicitly acknowledged

### Privacy
- Consent required per request (checkbox)
- No PII sent to LLM
- Configurable daily/minute limits per user

## Real-time
- **`nepse-data-api` check**: No websocket/SSE/push endpoints available
- **Implementation**: React Query `refetchInterval` on price endpoints (30s for watchlists, 60s for valuations)
- **Pacing**: Shared `NepseClientAdapter` at 120ms min interval

## OpenAPI Spec
- 85 endpoints across 11 tags
- Auto-generated: `python -c "from app.main import app; import json; json.dump(app.openapi(), open('openapi.json','w'), indent=2)"`
- Saved to `openapi.json`

## Documentation
- `docs/api-reference.md` — endpoint table by tag
- `docs/data-sources.md` — provenance, fees/taxes with source links
- `docs/api-reference.md` — API reference

## Tests
- 332 backend tests pass
- FakeAIClient used in test environment (no API key needed)

## Verification
```bash
# Backend
.venv\Scripts\python.exe -m pytest -q
# 332 passed

# Frontend
cd frontend && npm run build
# Build successful (469 kB gzipped)

# OpenAPI spec
python -c "from app.main import app; import json; json.dump(app.openapi(), open('openapi.json','w'), indent=2)"
```