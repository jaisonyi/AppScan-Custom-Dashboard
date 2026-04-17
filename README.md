# AppScan Custom Dashboard

Documentation-first monorepo for a read-only HCL AppScan dashboard with multi-data-source aggregation.

## Core Principles
- Read-only integration for all external ASoC and AppScan 360 calls
- Multi-data-source support (endpoint registry with per-source SSL policy; UI toggle for self-signed cert environments)
- Role and asset-group scoped access controls on all data endpoints
- Cache-first analytics responses with refresh override paths
- Backend authorization and connector safety checks as non-negotiable guardrails

## Repository Layout
- `backend/` FastAPI backend, repositories, services, workers, Alembic migrations
- `frontend/` React + TypeScript dashboard UI
- `docs/` architecture, development, operations, continuity
- `scripts/` local setup helpers (including PostgreSQL bootstrap scripts)
- `infra/` deployment/runtime assets
- `data/` local export artifacts

## Backend Snapshot
- App entrypoint: `backend/app/main.py`
- API root: `/api/v1`
- Enabled route groups:
	- `/auth`, `/scans`, `/applications`, `/asset-groups`, `/issues`
	- `/analytics`, `/dashboards`, `/reports`, `/pipeline-bom`, `/audit`, `/endpoints`
- Startup jobs:
	- DB/table init + seed data
	- data source bootstrap from environment
	- optional scheduler and analytics prewarm workers
- Production static serving:
	- serves `frontend/dist` when built

## Persistence and Migrations
- Runtime DB: PostgreSQL (`DATABASE_URL`)
- Alembic migrations: `backend/migrations/versions/`
- Current migration chain:
	- `0001_initial_sqlite_schema.py`
	- `0002_schedule_retry_and_report_artifacts.py`
	- `0003_analytics_snapshots_cache.py`
	- `0004_data_sources.py`

## Local Development
1. Start local PostgreSQL:
	 - `scripts/postgres/install_local_postgres.sh`
	 - `scripts/postgres/start.sh`
2. Start backend:
	 - `cd backend`
	 - `python3 -m pip install -e '.[dev]'`
	 - `python3 -m uvicorn app.main:app --reload --port 8000`
3. Start frontend:
	 - `cd frontend`
	 - `npm install`
	 - `npm run dev`

## Installer
A pre-built source ZIP is available at the project parent directory:
- `AppScan-Custom-Dashboard-v0.1-source.zip` (38 MB) — includes all source files, migrations, and scripts required for a clean install

## Safety Guarantee
ASoC connector calls are read-only by policy and code guard. Mutating operations are blocked except token login (`POST /api/v4/Account/ApiKeyLogin`).

## Related Docs
- `docs/development/coding-standards.md`
- `docs/development/test-strategy.md`
- `docs/development/api-compliance-checklist.md`
- `docs/operations/runbook.md`
