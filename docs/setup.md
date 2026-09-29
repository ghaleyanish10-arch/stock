# Setup

## Requirements

- Python 3.11+ (developed on 3.14)
- Node 20+ for the frontend
- No NEPSE credentials: the public API needs none
- SQLite by default; Postgres is a config change, not a code change

## Install

```powershell
# backend (Python package lives in backend/)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

cd frontend
npm install
npm run build
```

`npm run build` produces `frontend/dist`, which the API serves from the same
origin, so the app runs as a single process.

## Run

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. API docs are at `/docs`.

For frontend development with hot reload, run the API on `:8000` and Vite on
`:5174`; CORS allows that origin already.

## The first administrator

Registration cannot grant admin, so a fresh install has no admin until you
create one. This is a local CLI, not an endpoint, which keeps privilege
escalation off the HTTP surface entirely.

```powershell
# from backend/
..\.venv\Scripts\python.exe -m app.cli create-admin --email you@example.com
```

The password is prompted without echo. Other commands:

```powershell
..\.venv\Scripts\python.exe -m app.cli grant-admin --email someone@example.com
..\.venv\Scripts\python.exe -m app.cli list-users
```

`grant-admin` bumps the account's token version, so sessions issued before the
promotion are invalidated.

## Configuration

All settings are environment variables; see `.env.example`. Nothing is
required for development.

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_DATABASE_URL` | SQLite in `data/` | Any SQLAlchemy URL. |
| `APP_JWT_SECRET` | insecure dev value | **Set this in production.** |
| `APP_DEBUG` | `1` | When off, startup fails on a dev JWT secret. |
| `APP_JWT_TTL_MINUTES` | `10080` (7 days) | Token lifetime. |
| `APP_ARCHIVE_FLOOR` | `2025-09-28` | Earliest date NEPSE serves. |
| `APP_ARCHIVE_PAUSE_MS` | `900` | Pause between backfill fetches. |
| `APP_POST_CLOSE_HHMM` | `15:30` | Post-close snapshot, Nepal time. |
| `NEPSE_TIMEOUT` | `15` | Per-request timeout, seconds. |
| `NEPSE_CACHE_TTL` | `30` | Response cache TTL, seconds. |
| `NEPSE_OUTBOUND_MIN_INTERVAL_MS` | `120` | Upstream pacing. |

Startup refuses to run when `APP_DEBUG` is off and `APP_JWT_SECRET` is still
the development fallback, so a deploy cannot silently use a public signing
key.

## Database and migrations

`init_db()` creates missing tables and then applies the small set of recorded
migrations in `app/db/migrations.py`. It is intentionally not Alembic: the
schema is small and the changes are additive or renames. If the schema ever
needs data backfills or dialect branching, replace that module with a real
migration tool.

SQLite runs in WAL mode with foreign keys on and a busy timeout, so the
backfill and the dashboard's polling do not block each other.

## Backfilling history

Only administrators can trigger a backfill, because it issues hundreds of
upstream requests.

```powershell
curl -X POST http://127.0.0.1:8000/api/archive/backfill `
  -H "Authorization: Bearer $TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"start": "2026-01-01"}'
```

It runs in the background and resumes from what is already stored. Check
progress at `/api/archive/runs` and the resulting coverage at
`/api/archive/coverage`.

A post-close snapshot runs automatically at `APP_POST_CLOSE_HHMM` Nepal time
(15:30 by default). Two rules keep the archive honest:

- **A run before the close does not count as done.** If something saved today's
  rows early — a manual trigger, a mis-set `APP_POST_CLOSE_HHMM`, or a snapshot
  taken while the session was still running — the scheduler still comes back
  after 15:30 and overwrites those partial rows with the published close.
- **The job refuses to save while the market is open.** It checks NEPSE's own
  market status first and records a `deferred` run if the session is live, so
  an intraday snapshot is never written as final.

A date that returns no rows is recorded as `deferred` and retried later rather
than being assumed to be a holiday. Every attempt, including deferrals, is
visible at `/api/archive/jobs`.

## Before deploying

- Set `APP_JWT_SECRET` to a strong random value and `APP_DEBUG=0`.
- Put a rate limiter in front of `/api/auth/*`. The app caps failed logins
  per email in memory, which blunts online guessing but is not a substitute
  for a real limiter, and the cap resets on restart.
- Serve over HTTPS: tokens are bearer credentials in `localStorage`, so they
  are only as protected as the connection.
- Consider Postgres if the archive outgrows a single SQLite file.
