# Installation Guide

## Prerequisites
- Python 3.12+
- Node.js 20+
- PostgreSQL 16+

## Local Data Storage
- Dashboard and report persistence uses PostgreSQL.
- For local development, PostgreSQL can be installed and initialized under the project root at `.postgres/`.
- Persisted entities include dashboards, dashboard versions, report templates, report schedules, report history, and audit events.
- Analytics responses are cached in database snapshots for fast page loads.
- Generated report artifacts are stored under `data/exports` and can be downloaded via API.
- Schedule cadence parsing uses `croniter` for standard cron expressions.
- The repository layer (`postgres_store.py`) uses a module-level connection with thread-safe locking — connections are reused across requests rather than opened per-request. An `atexit` handler closes the connection cleanly on shutdown.

## Project-Local PostgreSQL Setup
1. From repository root, run:
	- `scripts/postgres/install_local_postgres.sh`
2. This installs PostgreSQL binaries (via Homebrew when missing), initializes `.postgres/data`, starts DB on port `55432`, and creates DB `aspm`.
3. Runtime DB URL:
	- `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/aspm`
4. Helper scripts:
	- `scripts/postgres/start.sh`
	- `scripts/postgres/stop.sh`
	- `scripts/postgres/status.sh`

## Migrations (Alembic)
1. Install backend dev dependencies (includes Alembic).
2. Apply migrations from `backend/`:
	- `alembic -c alembic.ini upgrade head`
3. Create future migrations:
	- `alembic -c alembic.ini revision -m "describe change"`

## Configure Environment
1. Copy `.env.example` to `.env`.
2. Set `ASOC_SERVICE_URL`, `ASOC_API_KEY`, and `ASOC_API_SECRET`.
	- US cloud base: `https://cloud.appscan.com`
	- EU cloud base: `https://eu.cloud.appscan.com`
	- Effective v4 endpoint pattern is `<ASOC_SERVICE_URL>/api/v4/...`
	- Legacy value `https://cloud.appscan.com/eu` is normalized to `https://eu.cloud.appscan.com`.
3. Keep `ASOC_READ_ONLY=true`.
4. Set `JWT_SECRET` to a long random string for production deployments.
	- If `JWT_SECRET` is **not** set, a secure random value is auto-generated at startup (`secrets.token_urlsafe(32)`) and a warning is logged.
	- **Important**: an auto-generated secret means all issued tokens are invalidated on every restart. Always set `JWT_SECRET` explicitly in production.
5. Choose auth mode:
	- `AUTH_MODE=local` (default): uses bootstrap login endpoint for local development.
	- `AUTH_MODE=oidc` (optional): local login is disabled; provide enterprise bearer token.
5. Scheduler options (enabled by default):
	- `REPORT_SCHEDULER_ENABLED=true`
	- `REPORT_SCHEDULER_INTERVAL_SECONDS=30`
 	- `REPORT_SCHEDULER_MAX_RETRIES=5`
 	- `REPORT_SCHEDULER_BACKOFF_BASE_SECONDS=60`
 	- `REPORT_SCHEDULER_BACKOFF_MAX_SECONDS=3600`
6. Analytics cache tuning:
	- `ANALYTICS_CACHE_TTL_SECONDS=180`
	- `ANALYTICS_CACHE_CLEANUP_INTERVAL_SECONDS=600`
	- Use `?refresh=true` on analytics endpoints for a forced refresh when needed.
7. For OIDC mode, set:
	- `OIDC_ISSUER_URL`
	- `OIDC_JWKS_URL` (optional if issuer discovery is available)
	- `OIDC_AUDIENCE` (optional, tenant-specific)
	- `OIDC_ROLE_CLAIM`, `OIDC_ASSET_GROUPS_CLAIM` (optional overrides)

## Backend
1. Create virtual environment.
2. Install dependencies from `backend/pyproject.toml`.
3. Run API: `uvicorn app.main:app --reload --port 8000`.
4. Verify DB connectivity by calling `GET /health` and one protected endpoint after login.
5. Scheduler loop starts with backend startup and executes due report schedules automatically.
6. Optional schedule operations:
	- `GET /api/v1/reports/schedules/monitor` for monitor widget data
	- `POST /api/v1/reports/schedules/{schedule_id}/run-now` to trigger immediate execution

## Frontend
1. Install dependencies in `frontend/`.
2. Run web app: `npm run dev`.
3. Default local access is HTTP:
	- `http://localhost:5173`
	- `https://localhost:5173` is not enabled by default.

## HTTPS Deployment Note (Planned Installer Capability)
- Current local/developer default remains HTTP for simplicity.
- Next installer enhancement will provide an explicit HTTPS mode selection during install:
	1. Self-signed certificate mode
	2. CA-authorized certificate mode (domain + certificate chain)
- Planned installer prompts for HTTPS mode:
	- Enable HTTPS? (yes/no)
	- If self-signed: generate cert/key automatically
	- If CA mode: collect domain, cert path, key path, optional chain path
	- Select HTTPS port and validate conflict
- Planned runtime policy:
	- If HTTPS is enabled, installer will validate files/ports first and notify before applying changes.
	- If conflicts are detected (port in use, invalid cert path, permission issue), installer will stop and request confirmation instead of forcing changes.
- Planned uninstall policy:
	- Remove only this dashboard instance by default.
	- Do not remove shared dependencies automatically when other instances are detected.

## First Login
- Use bootstrap login endpoint in local mode, then map role and accessible asset groups.

## OIDC Optional Flow
- Call `GET /api/v1/auth/mode` to verify backend mode and OIDC readiness.
- If mode is `oidc`, provide external bearer token from your IdP in the frontend token input.
- If OIDC settings are missing and mode is `oidc`, protected routes return `503` with missing fields.
