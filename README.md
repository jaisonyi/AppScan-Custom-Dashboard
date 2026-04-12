# ASoC ASPM Dashboard

Documentation-first monorepo for a custom HCL AppScan on Cloud (ASoC) ASPM dashboard.

## Core Principles
- Read-only integration with ASoC data sources
- Configurable API key, API key secret, and service URL
- Role and asset-group scoped access controls
- Open and extensible architecture for future capabilities
- Documentation and continuity artifacts as first-class deliverables

## Monorepo Layout
- `docs/` architecture, development, operations, and continuity docs
- `backend/` FastAPI service and domain modules
- `frontend/` React application
- `data/` local runtime data (report export artifacts)
- `.postgres/` project-local PostgreSQL cluster data directory (created by setup script)
- `infra/` runtime/deployment assets
- `scripts/` helper scripts

## Persistence and Migrations
- Runtime database: PostgreSQL (`DATABASE_URL`)
- Migration tooling: Alembic under `backend/migrations/`
- Baseline migration: `backend/migrations/versions/0001_initial_sqlite_schema.py`

## Local PostgreSQL Runtime
- Install/init/start local PostgreSQL under project folder:
	- `scripts/postgres/install_local_postgres.sh`
- Start/stop/status:
	- `scripts/postgres/start.sh`
	- `scripts/postgres/stop.sh`
	- `scripts/postgres/status.sh`

## Safety Guarantee
The backend connector enforces a **read-only** policy for ASoC APIs. Mutating requests are blocked by default.

## Quick Start
See:
- `docs/operations/install-guide.md`
- `docs/operations/runbook.md`
- `docs/operations/troubleshooting-auth-refresh.md`
- `docs/operations/troubleshooting-application-filter-list.md`
